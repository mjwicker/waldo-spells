"""Adapter: Kaggle grammar_error_dataset.csv -> CorpusItem (CC0 Public Domain).

Error types in this dataset are grammar errors (Article, Preposition, Verb Tense, etc.)
that are correctly-spelled words used in the wrong role. The fast (spell-check) tier
cannot detect these, so items are tagged skip_tiers=["fast"] unless the error type is
explicitly spelling-related.
"""

import csv
from pathlib import Path
from typing import Iterator, Optional

from .align import diff_to_spans

# Resolved at import time relative to data_sources/
_CSV_PATH = (
    Path(__file__).parent.parent.parent
    / "data_sources"
    / "archive"
    / "grammar_error_dataset.csv"
)


def _iter_rows(path: Path) -> Iterator[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield row


# Error types that are actual misspellings — fast tier (spell-check) is applicable.
# All other types are grammar errors on correctly-spelled words: fast tier skips them.
_SPELLING_ERROR_TYPES = {"spelling", "typo", "misspelling", "orthography"}


def _is_spelling_error(error_type: Optional[str]) -> bool:
    if not error_type:
        return False
    return error_type.lower().strip() in _SPELLING_ERROR_TYPES


def load(sample: int, seed: int):
    """Yield CorpusItems from the Kaggle GEC CSV."""
    # Import here to avoid circular dependency at module level
    from corpus import CorpusItem
    from .base import reservoir_sample

    if not _CSV_PATH.exists():
        print(f"[kaggle_gec] CSV not found at {_CSV_PATH} — skipping")
        return

    rows = reservoir_sample(_iter_rows(_CSV_PATH), sample, seed)

    for i, row in enumerate(rows):
        source = row.get("Original_Sentence", "").strip()
        target = row.get("Corrected_Sentence", "").strip()
        error_type = row.get("Error_Type", "").strip() or None

        if not source or not target:
            continue

        spans = diff_to_spans(source, target)

        # Grammar errors (Article, Preposition, Verb Tense, etc.) are correctly-spelled
        # words in the wrong role — the spell-check (fast) tier cannot detect them.
        fast_skip = [] if _is_spelling_error(error_type) else ["fast"]

        yield CorpusItem(
            id=f"kaggle_{i:05d}",
            input_type="general",
            text=source,
            expected_corrections=spans,
            should_skip=False,
            task="span_correction",
            expected_label=None,
            error_type=error_type,
            source="kaggle_gec",
            skip_tiers=fast_skip,
        )
