"""
Generate C4_200M sentence pairs and write TSV files to data_sources/C4_200M*/sentence_pairs/.

This script orchestrates the full pipeline:
  1. Read edit records from bz2 or plain-text edits TSV files
  2. Look up target sentences from a C4 json.gz directory (allenai format)
  3. Apply edits to produce (source, target) sentence pairs
  4. Write output TSV to the expected location for sources/c4_200m.py

Prerequisites
-------------
English edits (from Kaggle):
  https://www.kaggle.com/datasets/felixstahlberg/the-c4-200m-dataset-for-gec
  Place edits.tsv-00000-of-00010 ... edits.tsv-00009-of-00010 in:
    data_sources/C4_200M-synthetic-dataset-for-grammatical-error-correction-main/
    C4_200M-synthetic-dataset-for-grammatical-error-correction-main/

C4 corpus in json.gz format (allenai):
  https://github.com/allenai/allennlp/discussions/5056
  ~300GB download. Store the *train*.json.gz files in a directory and
  pass it as --c4-dir.

Multilingual edits (already present as bz2 in multilingual/):
  de, es, ro, ru bz2 files are already in the repo.
  Pass --lang de (or es, ro, ru) to generate multilingual pairs.
  Still requires multilingual C4 target sentences.

Usage
-----
# English (requires Kaggle edits + C4 json.gz):
python scripts/generate_c4200m_pairs.py --c4-dir /path/to/c4/en/

# Single shard (faster for testing):
python scripts/generate_c4200m_pairs.py --c4-dir /path/to/c4/en/ --shards 0

# Multilingual (de):
python scripts/generate_c4200m_pairs.py --lang de --c4-dir /path/to/c4/de/

# Dry-run: count edits available without generating pairs:
python scripts/generate_c4200m_pairs.py --dry-run
"""

import argparse
import bz2
import gzip
import hashlib
import heapq
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_DATA_ROOT = _REPO_ROOT / "data_sources"
_C4_DIR_NAME = (
    "C4_200M-synthetic-dataset-for-grammatical-error-correction-main"
    "/C4_200M-synthetic-dataset-for-grammatical-error-correction-main"
)
_EDITS_DIR = _DATA_ROOT / _C4_DIR_NAME
_MULTILINGUAL_DIR = _EDITS_DIR / "multilingual"
_PAIRS_OUT_DIR = _DATA_ROOT / "C4_200M-synthetic-dataset-for-grammatical-error-correction-main" / "sentence_pairs"

LOGGING_STEPS = 50_000


# ---------------------------------------------------------------------------
# Edit parsing
# ---------------------------------------------------------------------------

def _open_edits(path: Path):
    """Open a plain TSV or bz2-compressed edits file as a text stream."""
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _iter_edits(edits_path: Path):
    """Yield (md5, [(byte_start, byte_end, replacement), ...]) groups."""
    current_md5 = None
    current_edits = []
    with _open_edits(edits_path) as f:
        for line in f:
            line = line.rstrip("\n")
            parts = line.split("\t", 3)
            if len(parts) < 3:
                continue
            md5 = parts[0]
            try:
                byte_start = int(parts[1])
                byte_end = int(parts[2])
            except ValueError:
                continue
            replacement = parts[3] if len(parts) == 4 else ""
            if md5 != current_md5:
                if current_md5 is not None:
                    yield current_md5, current_edits
                current_md5 = md5
                current_edits = []
            current_edits.append((byte_start, byte_end, replacement))
    if current_md5 is not None:
        yield current_md5, current_edits


def _apply_edits(edits, target_text: str) -> str:
    """Apply byte-offset edits to a target sentence to recover the source."""
    target_bytes = target_text.encode("utf-8")
    last_pos = 0
    source = ""
    for byte_start, byte_end, replacement in edits:
        source += target_bytes[last_pos:byte_start].decode("utf-8")
        source += replacement
        last_pos = byte_end
    source += target_bytes[last_pos:].decode("utf-8")
    return source


# ---------------------------------------------------------------------------
# Hash lookup
# ---------------------------------------------------------------------------

def _collect_hashes(edits_paths) -> set:
    """Return the set of all MD5 hashes referenced in the edits files."""
    hashes = set()
    for path in edits_paths:
        with _open_edits(path) as f:
            for line in f:
                h = line.split("\t", 1)[0]
                if h:
                    hashes.add(h)
    return hashes


def _find_target_sentences(c4_dir: Path, remaining_hashes: set) -> list:
    """
    Scan allenai-format C4 *train*.json.gz files for sentences whose MD5
    matches the edit records.  Returns a min-heap of (md5, sentence) tuples
    sorted by md5 (required by make_sentence_pairs).
    """
    results = []
    total_examples = 0
    files = sorted(
        p for p in c4_dir.iterdir()
        if p.suffix == ".gz" and "train" in p.name
    )
    if not files:
        print(f"[generate] No *train*.json.gz files found in {c4_dir}", file=sys.stderr)
        return results

    for gz_path in files:
        print(f"[generate] Scanning {gz_path.name} ({len(remaining_hashes)} hashes left)…")
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            import json
            for i, line in enumerate(f):
                try:
                    example = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for sentence in example.get("text", "").split("\n"):
                    h = hashlib.md5(sentence.encode("utf-8")).hexdigest()
                    if h in remaining_hashes:
                        heapq.heappush(results, (h, sentence))
                        remaining_hashes.discard(h)
                if not remaining_hashes:
                    break
                total_examples += 1
                if total_examples % LOGGING_STEPS == 0:
                    print(
                        f"[generate]   {total_examples} examples done, "
                        f"{len(remaining_hashes)} hashes remaining"
                    )
        if not remaining_hashes:
            break

    print(
        f"[generate] Found {len(results)} target sentences "
        f"({len(remaining_hashes)} not found)."
    )
    return results


# ---------------------------------------------------------------------------
# Pair generation
# ---------------------------------------------------------------------------

def _make_pairs(edits_paths, target_heap: list) -> list:
    """
    Join edits with target sentences (both sorted by md5) to produce
    (source, target) pairs.
    """
    pairs = []
    # Convert heap to sorted list
    sorted_targets = []
    temp = list(target_heap)
    heapq.heapify(temp)
    while temp:
        sorted_targets.append(heapq.heappop(temp))
    target_map = dict(sorted_targets)

    for edits_path in edits_paths:
        for md5, edits in _iter_edits(edits_path):
            if md5 not in target_map:
                continue
            target_text = target_map[md5]
            source_text = _apply_edits(edits, target_text)
            pairs.append((source_text, target_text))

    return pairs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _find_english_edits() -> list:
    """Return sorted list of English edits TSV paths (plain or bz2)."""
    paths = []
    for pattern in ["edits.tsv-*-of-*", "edits*.tsv", "edits*.tsv.bz2"]:
        paths.extend(_EDITS_DIR.glob(pattern))
    return sorted(paths)


def _find_multilingual_edits(lang: str) -> list:
    """Return list of multilingual edits bz2 paths for the given language code."""
    candidates = [
        _MULTILINGUAL_DIR / f"{lang}.tsv.bz2",
        _MULTILINGUAL_DIR / f"{lang}.tsv",
    ]
    return [p for p in candidates if p.exists()]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Language code: 'en' (default) or multilingual code (de, es, ro, ru).",
    )
    parser.add_argument(
        "--c4-dir",
        type=Path,
        default=None,
        help="Directory containing *train*.json.gz C4 files (allenai format).",
    )
    parser.add_argument(
        "--shards",
        type=str,
        default=None,
        help="Comma-separated shard indices to process (e.g. '0,1'). Default: all.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_PAIRS_OUT_DIR,
        help=f"Output directory for sentence_pairs TSVs (default: {_PAIRS_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count available edits and exit without generating pairs.",
    )
    args = parser.parse_args()

    # --- Locate edits files ---
    if args.lang == "en":
        edits_paths = _find_english_edits()
        if not edits_paths:
            print(
                "[generate] ERROR: No English edits TSV files found.\n"
                "  Download from: https://www.kaggle.com/datasets/felixstahlberg/the-c4-200m-dataset-for-gec\n"
                f"  Place edits.tsv-00000-of-00010 ... in:\n  {_EDITS_DIR}\n",
                file=sys.stderr,
            )
            sys.exit(1)
        output_name = "sentence_pairs_en.tsv"
    else:
        edits_paths = _find_multilingual_edits(args.lang)
        if not edits_paths:
            print(
                f"[generate] ERROR: No edits file found for lang={args.lang!r}.\n"
                f"  Expected: {_MULTILINGUAL_DIR / args.lang}.tsv[.bz2]\n",
                file=sys.stderr,
            )
            sys.exit(1)
        output_name = f"sentence_pairs_{args.lang}.tsv"

    # --- Filter shards (English only) ---
    if args.shards and args.lang == "en":
        wanted = set(int(s) for s in args.shards.split(","))
        edits_paths = [
            p for p in edits_paths
            if any(f"-{i:05d}-of-" in p.name for i in wanted)
        ]

    print(f"[generate] Edits files ({len(edits_paths)}):")
    for p in edits_paths:
        print(f"  {p}")

    # --- Dry-run ---
    if args.dry_run:
        total = 0
        for path in edits_paths:
            n = sum(1 for _ in _iter_edits(path))
            print(f"  {path.name}: {n} edit groups")
            total += n
        print(f"[generate] Total edit groups: {total}")
        print("[generate] Dry-run complete — no TSV written.")
        return

    # --- C4 directory required for full run ---
    if args.c4_dir is None:
        print(
            "[generate] ERROR: --c4-dir is required for pair generation.\n"
            "  Download C4 (allenai format, ~300GB) from:\n"
            "  https://github.com/allenai/allennlp/discussions/5056\n"
            "  Then run:\n"
            f"  python scripts/generate_c4200m_pairs.py --c4-dir /path/to/c4/{args.lang}/\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.c4_dir.is_dir():
        print(f"[generate] ERROR: --c4-dir {args.c4_dir!r} is not a directory.", file=sys.stderr)
        sys.exit(1)

    # --- Step 1: collect all MD5 hashes from edits ---
    print("[generate] Step 1: collecting edit hashes…")
    hashes = _collect_hashes(edits_paths)
    print(f"[generate]   {len(hashes)} unique sentence hashes.")

    # --- Step 2: find target sentences in C4 ---
    print("[generate] Step 2: scanning C4 for target sentences…")
    target_heap = _find_target_sentences(args.c4_dir, set(hashes))

    if not target_heap:
        print("[generate] ERROR: No target sentences found. Check --c4-dir path.", file=sys.stderr)
        sys.exit(1)

    # --- Step 3: apply edits to produce pairs ---
    print("[generate] Step 3: applying edits to generate sentence pairs…")
    pairs = _make_pairs(edits_paths, target_heap)
    print(f"[generate]   {len(pairs)} sentence pairs generated.")

    # --- Step 4: write output TSV ---
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / output_name
    print(f"[generate] Step 4: writing {out_path}…")
    with open(out_path, "w", encoding="utf-8") as f:
        for source, target in pairs:
            f.write(f"{source}\t{target}\n")

    print(f"[generate] Done — {len(pairs)} pairs written to {out_path}.")
    print(f"[generate] The c4_200m source adapter will pick this up automatically.")


if __name__ == "__main__":
    main()
