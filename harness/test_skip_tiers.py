"""Tests for skip_tiers feature — verifies fast-tier scope limiting and metrics exclusion.

Contracts verified:
  (1) skip_tiers annotation carries through harness pipeline (corpus.py → runner.py)
  (2) tier_not_applicable items are excluded from tier metrics (metrics.py)
  (3) CorpusItem.to_dict() serializes skip_tiers field correctly
  (4) Other tiers (better, smart) still evaluate all items despite skip_tiers
  (5) Fast tier (hunspell) evaluates only items without skip_tiers: ["fast"]
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from corpus import CorpusItem, load_corpus
from runner import RunResult, run_one
from metrics import by_tier


class TestCorpusItemSkipTiersSerialization:
    """Test that skip_tiers field is correctly serialized and deserialized."""

    def test_to_dict_includes_skip_tiers_empty_list(self):
        """to_dict() should include skip_tiers even when empty."""
        item = CorpusItem(
            id="test1",
            input_type="email",
            text="Some text",
            expected_corrections=[],
            should_skip=False,
            skip_tiers=[],
        )
        d = item.to_dict()
        assert "skip_tiers" in d
        assert d["skip_tiers"] == []

    def test_to_dict_includes_skip_tiers_with_values(self):
        """to_dict() should include skip_tiers when it contains tier names."""
        item = CorpusItem(
            id="test2",
            input_type="email",
            text="Some text",
            expected_corrections=[],
            should_skip=False,
            skip_tiers=["fast"],
        )
        d = item.to_dict()
        assert "skip_tiers" in d
        assert d["skip_tiers"] == ["fast"]

    def test_to_dict_includes_skip_tiers_multiple_tiers(self):
        """to_dict() should handle multiple tiers in skip_tiers."""
        item = CorpusItem(
            id="test3",
            input_type="email",
            text="Some text",
            expected_corrections=[],
            should_skip=False,
            skip_tiers=["fast", "better"],
        )
        d = item.to_dict()
        assert "skip_tiers" in d
        assert d["skip_tiers"] == ["fast", "better"]

    def test_from_dict_restores_skip_tiers_empty(self):
        """from_dict() should restore empty skip_tiers list."""
        data = {
            "id": "test4",
            "input_type": "email",
            "text": "Some text",
            "expected_corrections": [],
            "should_skip": False,
            "skip_tiers": [],
        }
        item = CorpusItem.from_dict(data)
        assert item.skip_tiers == []

    def test_from_dict_restores_skip_tiers_with_values(self):
        """from_dict() should restore skip_tiers when present."""
        data = {
            "id": "test5",
            "input_type": "email",
            "text": "Some text",
            "expected_corrections": [],
            "should_skip": False,
            "skip_tiers": ["fast"],
        }
        item = CorpusItem.from_dict(data)
        assert item.skip_tiers == ["fast"]

    def test_from_dict_defaults_skip_tiers_missing(self):
        """from_dict() should default skip_tiers to [] when missing from data."""
        data = {
            "id": "test6",
            "input_type": "email",
            "text": "Some text",
            "expected_corrections": [],
            "should_skip": False,
        }
        item = CorpusItem.from_dict(data)
        assert item.skip_tiers == []

    def test_roundtrip_to_dict_from_dict(self):
        """Roundtrip conversion should preserve skip_tiers."""
        original = CorpusItem(
            id="test7",
            input_type="email",
            text="Some text",
            expected_corrections=[{"start": 0, "end": 5, "correction": "fixed"}],
            should_skip=False,
            skip_tiers=["fast"],
        )
        d = original.to_dict()
        restored = CorpusItem.from_dict(d)
        assert restored.skip_tiers == original.skip_tiers
        assert restored.id == original.id
        assert restored.text == original.text


class TestSkipTiersInRunner:
    """Test that runner.py respects skip_tiers and returns tier_not_applicable error."""

    def test_run_one_returns_tier_not_applicable_error(self):
        """run_one() should return tier_not_applicable error when tier in skip_tiers."""
        item = CorpusItem(
            id="grammar_error_001",
            input_type="email",
            text="This are wrong",
            expected_corrections=[{"start": 5, "end": 9, "original": "are", "correction": "is"}],
            should_skip=False,
            skip_tiers=["fast"],
        )
        result = run_one(item, "fast")
        assert result.available is False
        assert result.error == "tier_not_applicable: fast"
        assert result.latency_ms == 0.0
        assert result.corrections == []

    def test_run_one_skips_tier_when_in_skip_tiers_list(self):
        """run_one() should skip the tier if it appears in item.skip_tiers."""
        item = CorpusItem(
            id="homophone_002",
            input_type="email",
            text="Their car is their",
            expected_corrections=[
                {"start": 0, "end": 5, "original": "Their", "correction": "Their"},
            ],
            should_skip=False,
            skip_tiers=["fast"],
        )
        result = run_one(item, "fast")
        assert result.available is False
        assert "tier_not_applicable" in result.error

    def test_run_one_does_not_skip_other_tiers(self):
        """run_one() should not skip tiers that are not in skip_tiers."""
        item = CorpusItem(
            id="error_003",
            input_type="email",
            text="This are wrong",
            expected_corrections=[],
            should_skip=False,
            skip_tiers=["fast"],
        )
        # When running against "better" tier, should not get tier_not_applicable
        result = run_one(item, "better")
        # The result may be unavailable for other reasons (backend not installed),
        # but not due to skip_tiers
        if result.error:
            assert "tier_not_applicable" not in result.error


class TestMetricsExcludeNotApplicable:
    """Test that metrics.by_tier() excludes tier_not_applicable rows from calculations."""

    def test_by_tier_excludes_tier_not_applicable_from_f1(self):
        """by_tier() should exclude tier_not_applicable rows from F1 and other metrics."""
        results = [
            # Two applicable fast-tier results
            RunResult(
                item_id="i1",
                tier="fast",
                input_type="email",
                latency_ms=10.0,
                corrections=[{"start": 0, "end": 4, "correction": "fixed"}],
                expected=[{"start": 0, "end": 4, "correction": "fixed"}],
                error=None,
                available=True,
            ),
            RunResult(
                item_id="i2",
                tier="fast",
                input_type="email",
                latency_ms=12.0,
                corrections=[],
                expected=[],
                error=None,
                available=True,
            ),
            # One tier_not_applicable (grammar error against spell-check)
            RunResult(
                item_id="i3",
                tier="fast",
                input_type="email",
                latency_ms=0.0,
                corrections=[],
                expected=[],
                error="tier_not_applicable: fast",
                available=False,
            ),
        ]

        metrics = by_tier(results)
        fast_metrics = metrics.get("fast", {})

        # Should count only the 2 applicable items
        assert fast_metrics.get("n_items") == 2
        # Should report how many were not applicable
        assert fast_metrics.get("n_not_applicable") == 1

    def test_by_tier_n_items_excludes_not_applicable(self):
        """by_tier() n_items should count only applicable rows, not tier_not_applicable."""
        results = [
            RunResult(
                item_id="i1",
                tier="fast",
                input_type="email",
                latency_ms=10.0,
                corrections=[],
                expected=[],
                error=None,
                available=True,
            ),
            RunResult(
                item_id="i2",
                tier="fast",
                input_type="email",
                latency_ms=0.0,
                corrections=[],
                expected=[],
                error="tier_not_applicable: fast",
                available=False,
            ),
            RunResult(
                item_id="i3",
                tier="fast",
                input_type="email",
                latency_ms=0.0,
                corrections=[],
                expected=[],
                error="tier_not_applicable: fast",
                available=False,
            ),
        ]

        metrics = by_tier(results)
        fast_metrics = metrics.get("fast", {})

        # Only 1 applicable item
        assert fast_metrics.get("n_items") == 1
        # 2 not applicable
        assert fast_metrics.get("n_not_applicable") == 2

    def test_by_tier_latency_stats_exclude_not_applicable(self):
        """by_tier() should compute latency stats using only applicable rows."""
        results = [
            RunResult(
                item_id="i1",
                tier="fast",
                input_type="email",
                latency_ms=100.0,
                corrections=[],
                expected=[],
                error=None,
                available=True,
            ),
            RunResult(
                item_id="i2",
                tier="fast",
                input_type="email",
                latency_ms=0.0,
                corrections=[],
                expected=[],
                error="tier_not_applicable: fast",
                available=False,
            ),
        ]

        metrics = by_tier(results)
        fast_metrics = metrics.get("fast", {})

        # Latency p50 should be from the single applicable item
        assert fast_metrics.get("latency_p50") == 100.0


class TestBuiltinCorpusSkipTiers:
    """Test that the builtin corpus (corpus.jsonl) has skip_tiers annotations loaded."""

    def test_builtin_corpus_loads_skip_tiers(self):
        """Load corpus.jsonl and verify skip_tiers field is present and loaded."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        items = load_corpus(corpus_path)

        assert len(items) > 0, "Expected builtin corpus to have items"
        # Check that at least some items have skip_tiers
        has_skip_tiers = any(item.skip_tiers for item in items)
        assert has_skip_tiers, "Expected at least some items to have skip_tiers annotations"

    def test_builtin_corpus_skip_tiers_is_list(self):
        """All loaded items should have skip_tiers as a list."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        items = load_corpus(corpus_path)

        for item in items:
            assert isinstance(item.skip_tiers, list), (
                f"Item {item.id} skip_tiers is {type(item.skip_tiers)}, not a list"
            )

    def test_builtin_corpus_grammar_errors_skipped_for_fast(self):
        """Builtin grammar-error items should have skip_tiers: ['fast']."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        items = load_corpus(corpus_path)

        # Find items with grammar error type
        grammar_items = [
            item for item in items
            if any(
                corr.get("type") == "grammar"
                for corr in item.expected_corrections
            )
        ]

        # All grammar items should skip the fast tier
        for item in grammar_items:
            assert "fast" in item.skip_tiers, (
                f"Grammar item {item.id} should skip fast tier, got skip_tiers={item.skip_tiers}"
            )

    def test_builtin_corpus_homophone_errors_skipped_for_fast(self):
        """Builtin homophone-error items should have skip_tiers: ['fast']."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        items = load_corpus(corpus_path)

        # Find items with homophone error type
        homophone_items = [
            item for item in items
            if any(
                corr.get("type") == "homophone"
                for corr in item.expected_corrections
            )
        ]

        # All homophone items should skip the fast tier
        for item in homophone_items:
            assert "fast" in item.skip_tiers, (
                f"Homophone item {item.id} should skip fast tier, got skip_tiers={item.skip_tiers}"
            )

    def test_spelling_errors_not_skipped_for_fast(self):
        """Builtin spelling-error items should NOT skip the fast tier."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        items = load_corpus(corpus_path)

        # Find pure spelling items (only spelling errors, no grammar/homophone)
        spelling_only = [
            item for item in items
            if all(
                corr.get("type") == "spelling"
                for corr in item.expected_corrections
            ) and item.expected_corrections
        ]

        # Spelling items should not skip fast tier
        for item in spelling_only:
            assert "fast" not in item.skip_tiers, (
                f"Spelling item {item.id} should NOT skip fast tier, got skip_tiers={item.skip_tiers}"
            )


class TestFastTierEvaluatesOnlySpelling:
    """Test that fast tier effectively evaluates only items it can handle after skip_tiers filtering."""

    def test_fast_tier_corpus_subset_in_runner(self):
        """Verify runner skips fast-tier for all items with skip_tiers: ['fast']."""
        corpus = [
            CorpusItem(
                id="spelling_001",
                input_type="email",
                text="Thsi is a misspeling",
                expected_corrections=[
                    {"start": 0, "end": 4, "original": "Thsi", "correction": "This"},
                    {"start": 14, "end": 24, "original": "misspeling", "correction": "misspelling"},
                ],
                should_skip=False,
                skip_tiers=[],
            ),
            CorpusItem(
                id="grammar_001",
                input_type="email",
                text="This are wrong",
                expected_corrections=[
                    {"start": 5, "end": 9, "original": "are", "correction": "is"},
                ],
                should_skip=False,
                skip_tiers=["fast"],
            ),
        ]

        # Run both against fast tier
        spelling_result = run_one(corpus[0], "fast")
        grammar_result = run_one(corpus[1], "fast")

        # Spelling should be evaluable (no tier_not_applicable)
        if spelling_result.error:
            assert "tier_not_applicable" not in spelling_result.error

        # Grammar should be explicitly skipped
        assert "tier_not_applicable" in grammar_result.error
        assert grammar_result.available is False


class TestOtherTiersEvaluateAll:
    """Test that better and smart tiers don't use skip_tiers (they handle all error types)."""

    def test_better_tier_does_not_skip_grammar_errors(self):
        """The 'better' tier should not skip grammar errors."""
        item = CorpusItem(
            id="grammar_001",
            input_type="email",
            text="This are wrong",
            expected_corrections=[],
            should_skip=False,
            skip_tiers=["fast"],
        )
        result = run_one(item, "better")
        # Should not get tier_not_applicable (may be unavailable for other reasons)
        if result.error:
            assert "tier_not_applicable" not in result.error

    def test_smart_tier_does_not_skip_homophone_errors(self):
        """The 'smart' tier should not skip homophone errors."""
        item = CorpusItem(
            id="homophone_001",
            input_type="email",
            text="Their error is their",
            expected_corrections=[],
            should_skip=False,
            skip_tiers=["fast"],
        )
        result = run_one(item, "smart")
        # Should not get tier_not_applicable (may be unavailable for other reasons)
        if result.error:
            assert "tier_not_applicable" not in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
