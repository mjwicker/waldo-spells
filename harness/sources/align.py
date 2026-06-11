"""Compute character-span corrections by diffing source/target sentence pairs."""

import difflib
from typing import List, Dict, Any


def diff_to_spans(source: str, target: str) -> List[Dict[str, Any]]:
    """
    Derive expected_corrections from a (source, target) sentence pair.

    Returns a list of correction dicts compatible with CorpusItem.expected_corrections:
      {start, end, original, correction, type}

    Uses a word-level SequenceMatcher to produce correction spans. Word-level
    diffing is preferred over character-level because GEC corrections typically
    replace whole words or groups of words — character-level diffs produce
    degenerate zero-length insert spans (start==end) that can never satisfy the
    overlap check in metrics.py, silently inflating false-negative counts for
    error types like Noun Form where the model inserts new words before an
    existing word.

    Word-level spans are then mapped back to character offsets by tracking the
    cumulative position through the source string.  Adjacent changed word-groups
    (delete immediately followed by insert, or two back-to-back changes) are
    merged into a single span covering the full changed region so the harness
    overlap logic has the best chance to find a match.
    """
    if source == target:
        return []

    src_words = source.split()
    tgt_words = target.split()

    # Pre-compute the character start offset of each source word.
    word_char_start: List[int] = []
    pos = 0
    for w in src_words:
        word_char_start.append(pos)
        pos += len(w) + 1  # +1 for the trailing space

    matcher = difflib.SequenceMatcher(None, src_words, tgt_words, autojunk=False)
    raw: List[Dict[str, Any]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        # Map word indices to character offsets in source.
        if i1 < len(word_char_start):
            char_start = word_char_start[i1]
        else:
            # Pure insert after all source words — anchor at end of source.
            char_start = len(source)

        if i2 > 0 and i2 <= len(src_words):
            # char end = start of word[i2] if it exists, else end of source.
            char_end = word_char_start[i2] - 1 if i2 < len(src_words) else len(source)
        else:
            char_end = char_start

        # Ensure char_end is at least char_start (pure inserts have i1==i2).
        char_end = max(char_start, char_end)

        original_chunk = " ".join(src_words[i1:i2])
        correction_chunk = " ".join(tgt_words[j1:j2])

        raw.append({
            "start": char_start,
            "end": char_end,
            "original": original_chunk,
            "correction": correction_chunk,
        })

    if not raw:
        return []

    # Merge consecutive segments that are adjacent or share boundaries.
    # This collapses delete+insert pairs (common in word-order and noun-form
    # corrections) into a single span.
    merged: List[Dict[str, Any]] = [raw[0]]
    for seg in raw[1:]:
        prev = merged[-1]
        # Adjacent: seg starts where prev ends (or there's no gap in words).
        if seg["start"] <= prev["end"] + 1:
            new_end = max(prev["end"], seg["end"])
            merged[-1] = {
                "start": prev["start"],
                "end": new_end,
                "original": source[prev["start"]: new_end],
                "correction": (
                    (prev["correction"] + " " + seg["correction"]).strip()
                    if prev["correction"] and seg["correction"]
                    else prev["correction"] or seg["correction"]
                ),
            }
        else:
            merged.append(seg)

    corrections = []
    for seg in merged:
        # Re-derive original from character slice to guarantee consistency.
        original = source[seg["start"]: seg["end"]]
        corrections.append({
            "start": seg["start"],
            "end": seg["end"],
            "original": original,
            "correction": seg["correction"],
            "type": "replace" if original else "insert",
        })

    return corrections
