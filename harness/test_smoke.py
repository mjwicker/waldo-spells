"""Smoke tests for harness modules."""

import sys
from pathlib import Path

import pytest

# Add wrapper and harness to path
sys.path.insert(0, str(Path(__file__).parent.parent / "wrapper"))
sys.path.insert(0, str(Path(__file__).parent))

from corpus import load_corpus
from runner import run_one, run_all
from metrics import latency_stats


class TestCorpusLoads:
    """Test corpus loading."""

    def test_corpus_loads(self):
        """Test that corpus loads and has items."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        assert len(corpus) > 0, "Corpus should have items"

    def test_corpus_items_have_required_fields(self):
        """Test that all corpus items have required fields."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        for item in corpus:
            assert item.id, "Each item must have an id"
            assert item.text, "Each item must have text"
            assert item.input_type, "Each item must have input_type"
            assert hasattr(item, "expected_corrections"), "Item must have expected_corrections"
            assert hasattr(item, "should_skip"), "Item must have should_skip"


class TestRunOne:
    """Test single item runner."""

    def test_run_one_fast(self):
        """Test running a single item on fast tier."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        # Find first non-skip item
        item = next((i for i in corpus if not i.should_skip), None)
        assert item is not None, "Should have at least one non-skip item"

        result = run_one(item, "fast")
        assert result.item_id == item.id
        assert result.tier == "fast"
        assert result.input_type == item.input_type
        assert result.latency_ms >= 0, "Latency should be non-negative"
        assert isinstance(result.corrections, list), "Corrections should be a list"


class TestMetrics:
    """Test metrics calculation."""

    def test_latency_stats_empty(self):
        """Test latency stats with empty list."""
        stats = latency_stats([])
        assert "p50" in stats
        assert "p95" in stats
        assert "p99" in stats
        assert "mean" in stats
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["mean"] == 0.0


class TestRunAll:
    """Test full corpus runner."""

    def test_run_all_returns_list(self):
        """Test that run_all returns a list."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        # Limit to first 3 items for speed
        limited_corpus = corpus[:3]

        results = run_all(limited_corpus, tiers=("fast",))
        assert isinstance(results, list), "run_all should return a list"
        assert len(results) > 0, "Should have results"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
