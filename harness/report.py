"""Report generation for test results."""

import argparse
import csv
import math
import os
import sys
from datetime import datetime
from pathlib import Path

# Load .env into os.environ before importing backends that read env vars at import time
def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader — no external dependency required."""
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Only set if not already present in environment (shell export wins)
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path(__file__).parent.parent / ".env")

import sys as _sys
_sys.path.insert(0, os.path.dirname(__file__))

from corpus import load_corpus, load_sources
from runner import run_all
from metrics import (
    by_input_type, by_tier, by_error_type,
    latency_stats, context_detection_accuracy, tone_accuracy,
    string_match_rate,
)

_SOURCES_YAML = Path(__file__).parent / "sources.yaml"
_HARNESS_DIR = Path(__file__).parent

QUALITY_GATE_F1 = 0.05


def write_csv(results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "item_id", "tier", "input_type", "task", "source",
            "latency_ms", "n_corrections", "n_expected",
            "tp", "fp", "fn", "string_match_rate",
            "detected_input_type", "expected_label", "predicted_label",
            "error_type", "error", "available",
        ])
        for result in results:
            from metrics import true_positives, false_positives, false_negatives
            tp = true_positives(result)
            fp = false_positives(result)
            fn = false_negatives(result)
            smr = string_match_rate([result])

            writer.writerow([
                result.item_id, result.tier, result.input_type,
                getattr(result, "task", "span_correction"),
                getattr(result, "source", ""),
                f"{result.latency_ms:.2f}",
                len(result.corrections), len(result.expected),
                tp, fp, fn, f"{smr:.3f}",
                getattr(result, "detected_input_type", "") or "",
                getattr(result, "expected_label", "") or "",
                getattr(result, "predicted_label", "") or "",
                getattr(result, "error_type", "") or "",
                result.error or "", str(result.available),
            ])


def _fmt(v) -> str:
    if isinstance(v, float):
        if math.isnan(v):
            return "n/a"
        return f"{v:.3f}"
    return str(v)


def check_quality_gate(
    tier_metrics: dict,
    threshold: float = QUALITY_GATE_F1,
    skipped_tiers: set[str] | None = None,
) -> bool:
    """Returns True if at least one tier with n_items > 0 has f1 >= threshold.

    Skips tiers where n_items == 0 (all rows were tier_unavailable).
    Also skips tiers listed in skipped_tiers (backend not installed on this machine).
    Returns True (pass) when every tier in tier_metrics was skipped due to backend
    unavailability, so CI machines without a local LLM do not fail the quality gate.
    Returns False when tier_metrics is empty (no corpus items ran at all — unexpected).
    """
    if not tier_metrics:
        # Nothing ran at all (e.g. empty corpus) — treat as gate failure.
        return False
    skipped = skipped_tiers or set()
    evaluated_tiers = {t for t in tier_metrics if t not in skipped and tier_metrics[t].get('n_items', 0) > 0}
    if not evaluated_tiers:
        # All tiers that ran were either skipped (backend absent) or had zero evaluated items.
        # This is expected on CI machines without a local LLM — not a test-logic failure.
        return True
    for tier in evaluated_tiers:
        m = tier_metrics[tier]
        if m.get('f1', 0.0) >= threshold:
            return True
    return False


def write_summary(results, path: Path, run_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        f.write(f"# Test Harness Results — {run_id}\n\n")

        # Tier availability table
        all_tiers = sorted({r.tier for r in results})
        f.write("## Tier Availability\n\n")
        f.write("| Tier | Ran | Skipped (tier_unavailable) |\n")
        f.write("|------|-----|----------------------------|\n")
        for tier in all_tiers:
            tier_rows = [r for r in results if r.tier == tier]
            ran = sum(1 for r in tier_rows if r.available)
            skipped = len(tier_rows) - ran
            f.write(f"| {tier} | {ran} | {skipped} |\n")
        f.write("\n")

        stats = latency_stats(results)
        f.write("## Overall Metrics\n\n")
        f.write(f"- Total runs: {len(results)}\n")
        f.write(
            f"- Latency (ms): p50={stats['p50']:.2f}, p95={stats['p95']:.2f}, "
            f"p99={stats['p99']:.2f}, mean={stats['mean']:.2f}\n"
        )
        f.write(f"- String match rate: {_fmt(string_match_rate(results))}\n")
        f.write(f"- Context detection accuracy: {_fmt(context_detection_accuracy(results))}\n")
        f.write(f"- Tone accuracy: {_fmt(tone_accuracy(results))}\n\n")

        # Per-tier
        tier_metrics = by_tier(results)
        f.write("## Results by Tier\n\n")
        f.write("| Tier | Precision | Recall | F1 | FP Rate | Str Match | Items | Latency P50 |\n")
        f.write("|------|-----------|--------|-----|---------|-----------|-------|-------------|\n")
        for tier in sorted(tier_metrics.keys()):
            m = tier_metrics[tier]
            f.write(
                f"| {tier} | {_fmt(m['precision'])} | {_fmt(m['recall'])} | {_fmt(m['f1'])} | "
                f"{_fmt(m['fp_rate'])} | {_fmt(m['string_match_rate'])} | {m['n_items']} | "
                f"{m['latency_p50']:.2f} |\n"
            )
        f.write("\n")

        # Per-input-type
        type_metrics = by_input_type(results)
        f.write("## Results by Input Type\n\n")
        f.write("| Input Type | Precision | Recall | F1 | FP Rate | Items | Latency P50 |\n")
        f.write("|------------|-----------|--------|-----|---------|-------|-------------|\n")
        for input_type in sorted(type_metrics.keys()):
            m = type_metrics[input_type]
            f.write(
                f"| {input_type} | {_fmt(m['precision'])} | {_fmt(m['recall'])} | {_fmt(m['f1'])} | "
                f"{_fmt(m['fp_rate'])} | {m['n_items']} | {m['latency_p50']:.2f} |\n"
            )
        f.write("\n")

        # Per-error-type
        et_metrics = by_error_type(results)
        if et_metrics:
            f.write("## Results by Error Type\n\n")
            f.write("| Error Type | Precision | Recall | F1 | Str Match | Items |\n")
            f.write("|------------|-----------|--------|-----|-----------|-------|\n")
            for et in sorted(et_metrics.keys()):
                m = et_metrics[et]
                f.write(
                    f"| {et} | {_fmt(m['precision'])} | {_fmt(m['recall'])} | {_fmt(m['f1'])} | "
                    f"{_fmt(m['string_match_rate'])} | {m['n_items']} |\n"
                )
            f.write("\n")

        # Context detection
        cda = context_detection_accuracy(results)
        f.write("## Context Detection Accuracy\n\n")
        f.write(f"- Accuracy: {_fmt(cda)}\n")
        eligible = [r for r in results if getattr(r, "detected_input_type", None) is not None]
        f.write(f"- Eligible runs (hint omitted): {len(eligible)}\n\n")

        # Tone
        ta = tone_accuracy(results)
        tone_results = [r for r in results if getattr(r, "task", None) == "tone"]
        f.write("## Tone Accuracy\n\n")
        f.write(f"- Accuracy: {_fmt(ta)}\n")
        f.write(f"- Tone-task runs: {len(tone_results)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run grammar checker test harness and generate reports."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="Path to a single JSONL corpus file (bypasses sources.yaml)",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="NAME",
        help="Source name from sources.yaml to include (repeatable; default: all enabled)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Override sample size for all external sources",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override random seed",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=datetime.now().strftime("%Y%m%dT%H%M%S"),
        help="Run identifier (used as results subdirectory name)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="Root output directory; results go to <out-dir>/<run-id>/",
    )
    parser.add_argument(
        "--tiers",
        type=str,
        default="fast,better,smart",
        help="Comma-separated tiers to test",
    )

    args = parser.parse_args()
    tiers = tuple(t.strip() for t in str(args.tiers).split(","))
    run_dir = args.out_dir / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Load corpus
    if args.corpus:
        print(f"Loading corpus from {args.corpus}...")
        corpus = load_corpus(args.corpus)
        for item in corpus:
            item.source = "builtin"
    else:
        yaml_path = _SOURCES_YAML
        print(f"Loading sources from {yaml_path}...")
        corpus = load_sources(
            yaml_path,
            selected=args.sources,
            sample_override=args.sample,
            seed_override=args.seed,
        )

    print(f"Loaded {len(corpus)} items total")
    print(f"Testing tiers: {tiers}")
    print("Running tests...")
    results = run_all(corpus, tiers=tiers)
    print(f"Completed {len(results)} runs")

    # Track tiers skipped due to backend unavailability (llama-server absent, etc.)
    # so the quality gate does not penalise CI machines without a local LLM.
    skipped_tiers: set[str] = set()

    for tier in tiers:
        tier_rows = [r for r in results if r.tier == tier]
        if not tier_rows:
            continue
        # tier_not_applicable rows are expected skips (grammar errors vs. spell-check tier)
        # — they do not count toward the tier_unavailable failure check.
        not_applicable = sum(
            1 for r in tier_rows
            if not r.available and (r.error or "").startswith("tier_not_applicable")
        )
        # tier_unavailable: backend not installed (llama-server absent, model missing, etc.)
        # — expected on CI machines without a local LLM; treat as "skip" not "fail".
        tier_unavailable_count = sum(
            1 for r in tier_rows
            if not r.available and (r.error or "").startswith("tier_unavailable")
        )
        # other_error_count: backend crashed, returned bad data, etc. — unexpected failures.
        other_error_count = sum(
            1 for r in tier_rows
            if not r.available
            and not (r.error or "").startswith("tier_not_applicable")
            and not (r.error or "").startswith("tier_unavailable")
        )
        eligible = len(tier_rows) - not_applicable
        unavailable_ratio = tier_unavailable_count / eligible if eligible > 0 else 0.0
        error_ratio = other_error_count / eligible if eligible > 0 else 0.0

        if unavailable_ratio >= 0.95:
            # Backend not present — expected on CI without a local LLM.
            # Warn and skip this tier; do not fail the run.
            print(
                f"WARNING: Tier '{tier}': {tier_unavailable_count}/{eligible} eligible rows "
                f"tier_unavailable ({unavailable_ratio:.0%}). "
                f"Backend not installed — skipping tier.",
                file=sys.stderr,
            )
            skipped_tiers.add(tier)
            continue

        if error_ratio >= 0.95:
            print(
                f"ERROR: Tier '{tier}': {other_error_count}/{eligible} eligible rows "
                f"errored ({error_ratio:.0%}). Check model path or backend.",
                file=sys.stderr,
            )
            sys.exit(2)

        # Per-tier accuracy summary — visible in CI logs for all functional tiers.
        # Uses applicable rows (excludes tier_not_applicable skips) so the numbers
        # reflect actual evaluated items, not corpus-level counts.
        applicable_rows = [
            r for r in tier_rows
            if not (r.error or "").startswith("tier_not_applicable")
        ]
        ran = sum(1 for r in applicable_rows if r.available)
        _no_metrics: dict[str, float | int] = {}
        tier_m = by_tier(results).get(tier, _no_metrics)
        tier_f1 = tier_m.get("f1", float("nan"))
        tier_prec = tier_m.get("precision", float("nan"))
        tier_rec = tier_m.get("recall", float("nan"))
        f1_str = f"{tier_f1:.3f}" if not math.isnan(tier_f1) else "n/a"
        prec_str = f"{tier_prec:.3f}" if not math.isnan(tier_prec) else "n/a"
        rec_str = f"{tier_rec:.3f}" if not math.isnan(tier_rec) else "n/a"
        print(f"Tier '{tier}': {ran}/{eligible} ran | precision={prec_str} recall={rec_str} F1={f1_str}")

    csv_path = run_dir / "results.csv"
    summary_path = run_dir / "summary.md"

    print(f"Writing CSV to {csv_path}...")
    write_csv(results, csv_path)

    print(f"Writing summary to {summary_path}...")
    write_summary(results, summary_path, run_id=args.run_id)

    # Quality gate check: at least one non-skipped tier must reach F1 >= QUALITY_GATE_F1
    tier_metrics = by_tier(results)
    if not check_quality_gate(tier_metrics, skipped_tiers=skipped_tiers):
        failing = [
            t for t, m in tier_metrics.items()
            if t not in skipped_tiers and m.get('n_items', 0) > 0 and m.get('f1', 0.0) < QUALITY_GATE_F1
        ]
        print(f"QUALITY GATE FAILED: no tier reached F1 >= {QUALITY_GATE_F1}. Failing tiers: {failing}", file=sys.stderr)
        sys.exit(1)

    print(f"Done! Results in {run_dir}")


if __name__ == "__main__":
    main()
