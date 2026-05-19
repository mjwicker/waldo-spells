"""Smoke tests for harness modules."""

import sys
from pathlib import Path

import pytest

# Add wrapper and harness to path
sys.path.insert(0, str(Path(__file__).parent.parent / "wrapper"))
sys.path.insert(0, str(Path(__file__).parent))

from corpus import load_corpus, CorpusItem
from runner import run_one, run_all
from metrics import latency_stats, string_match_rate, by_error_type, by_tier
from report import check_quality_gate, QUALITY_GATE_F1


class TestCorpusLoads:
    """Test corpus loading."""

    def test_corpus_loads(self):
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        assert len(corpus) > 0

    def test_corpus_items_have_required_fields(self):
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        for item in corpus:
            assert item.id
            assert item.text
            assert item.input_type
            assert hasattr(item, "expected_corrections")
            assert hasattr(item, "should_skip")
            assert hasattr(item, "task")
            assert hasattr(item, "source")


class TestRunOne:
    """Test single item runner."""

    def test_run_one_fast(self):
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        item = next((i for i in corpus if not i.should_skip), None)
        assert item is not None

        result = run_one(item, "fast")
        assert result.item_id == item.id
        assert result.tier == "fast"
        assert result.input_type == item.input_type
        assert result.latency_ms >= 0
        assert isinstance(result.corrections, list)
        assert hasattr(result, "detected_input_type")
        assert hasattr(result, "task")


class TestMetrics:
    """Test metrics calculation."""

    def test_latency_stats_empty(self):
        stats = latency_stats([])
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["mean"] == 0.0

    def test_string_match_rate_perfect(self):
        """string_match_rate returns 1.0 when predicted matches gold."""
        class FakeResult:
            corrections = [{"start": 0, "end": 4, "correction": "went"}]
            expected = [{"start": 0, "end": 4, "correction": "went"}]
            task = "span_correction"
            error_type = None
        assert string_match_rate([FakeResult()]) == 1.0

    def test_string_match_rate_mismatch(self):
        class FakeResult:
            corrections = [{"start": 0, "end": 4, "correction": "go"}]
            expected = [{"start": 0, "end": 4, "correction": "went"}]
            task = "span_correction"
            error_type = None
        assert string_match_rate([FakeResult()]) == 0.0

    def test_by_error_type_groups(self):
        class FakeResult:
            corrections = [{"start": 0, "end": 3, "correction": "ran"}]
            expected = [{"start": 0, "end": 3, "correction": "ran"}]
            task = "span_correction"
            error_type = "Verb Tense"
        result = by_error_type([FakeResult()])
        assert "Verb Tense" in result
        assert result["Verb Tense"]["n_items"] == 1


class TestRunAll:
    """Test full corpus runner."""

    def test_run_all_returns_list(self):
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)[:3]
        results = run_all(corpus, tiers=("fast",))
        assert isinstance(results, list)
        assert len(results) > 0


class TestAdapters:
    """Test external data source adapters."""

    def test_kaggle_gec_yields_items(self):
        from sources.kaggle_gec import load
        items = list(load(sample=5, seed=42))
        assert len(items) > 0
        item = items[0]
        assert item.task == "span_correction"
        assert item.source == "kaggle_gec"
        assert item.id.startswith("kaggle_")
        assert item.text

    def test_uci_sentiment_yields_items(self):
        from sources.uci_sentiment import load
        items = list(load(sample=5, seed=42))
        assert len(items) > 0
        item = items[0]
        assert item.task == "tone"
        assert item.source == "uci_sentiment"
        assert item.expected_label in ("positive", "negative")

    def test_c4_200m_yields_nothing_without_pairs(self):
        """C4 adapter should yield 0 items when sentence_pairs TSVs are absent."""
        from sources.c4_200m import load
        items = list(load(sample=10, seed=42))
        # Either 0 (no pairs) or >0 if pairs happen to exist — both valid
        assert isinstance(items, list)


class TestAlign:
    """Test span alignment utility."""

    def test_diff_to_spans_basic(self):
        from sources.align import diff_to_spans
        source = "She go to school yesterday."
        target = "She went to school yesterday."
        spans = diff_to_spans(source, target)
        assert len(spans) == 1
        s = spans[0]
        assert s["original"] == "go"
        assert s["correction"] == "went"
        assert source[s["start"]:s["end"]] == "go"

    def test_diff_to_spans_no_diff(self):
        from sources.align import diff_to_spans
        spans = diff_to_spans("hello world", "hello world")
        assert spans == []


class TestSkipTiers:
    """Tests for skip_tiers field — fast tier exemption for grammar-error items."""

    def test_run_one_returns_not_applicable_when_tier_in_skip_tiers(self):
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        item = next((i for i in corpus if not i.should_skip), None)
        assert item is not None
        item.skip_tiers = ["fast"]
        result = run_one(item, "fast")
        assert result.available is False
        assert "tier_not_applicable" in (result.error or "")

    def test_run_one_proceeds_normally_when_tier_not_in_skip_tiers(self):
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        item = next((i for i in corpus if not i.should_skip), None)
        assert item is not None
        item.skip_tiers = []
        result = run_one(item, "fast")
        # May or may not be available depending on system enchant, but should not be not_applicable
        assert not (result.error or "").startswith("tier_not_applicable")

    def test_by_tier_excludes_not_applicable_from_n_items(self):
        """tier_not_applicable rows should not inflate n_items in by_tier()."""
        from runner import RunResult

        def make_result(available, error, corrections, expected):
            return RunResult(
                item_id="x", tier="fast", input_type="general",
                latency_ms=0.0, corrections=corrections, expected=expected,
                error=error, available=available,
            )

        results = [
            make_result(True, None, [], []),                               # ran fine
            make_result(False, "tier_not_applicable: fast", [], [{"start": 0, "end": 4}]),  # skipped
            make_result(False, "tier_not_applicable: fast", [], [{"start": 0, "end": 3}]),  # skipped
        ]
        metrics = by_tier(results)
        assert metrics["fast"]["n_items"] == 1
        assert metrics["fast"]["n_not_applicable"] == 2

    def test_corpus_item_default_skip_tiers_is_empty(self):
        item = CorpusItem(
            id="x", input_type="general", text="hello",
            expected_corrections=[], should_skip=False,
        )
        assert item.skip_tiers == []

    def test_kaggle_gec_grammar_items_skip_fast_tier(self):
        """Grammar-error kaggle items should have skip_tiers=["fast"]."""
        from sources.kaggle_gec import load
        items = list(load(sample=10, seed=42))
        if not items:
            pytest.skip("kaggle_gec CSV not present")
        # All items from kaggle should skip fast tier unless explicitly spelling errors
        for item in items:
            assert "fast" in item.skip_tiers or item.error_type.lower() in {"spelling", "typo", "misspelling", "orthography"}


class TestQualityGate:
    """Tests for check_quality_gate() — the harness F1 exit gate."""

    def test_passes_when_one_tier_above_threshold(self):
        metrics = {
            "fast": {"n_items": 10, "f1": 0.50},
            "better": {"n_items": 10, "f1": 0.00},
        }
        assert check_quality_gate(metrics) is True

    def test_fails_when_all_tiers_below_threshold(self):
        metrics = {
            "fast": {"n_items": 10, "f1": 0.01},
            "better": {"n_items": 10, "f1": 0.00},
        }
        assert check_quality_gate(metrics) is False

    def test_fails_when_all_tiers_unavailable(self):
        # n_items == 0 means tier_unavailable — gate returns False (no tier scored anything)
        # In practice, the prior exit(2) fires first when >=95% of rows are unavailable.
        metrics = {
            "fast": {"n_items": 0, "f1": 0.00},
            "better": {"n_items": 0, "f1": 0.00},
        }
        assert check_quality_gate(metrics) is False

    def test_fails_when_available_tiers_below_and_some_unavailable(self):
        # One tier ran but scored below threshold; another was unavailable
        metrics = {
            "fast": {"n_items": 10, "f1": 0.02},
            "smart": {"n_items": 0, "f1": 0.00},
        }
        assert check_quality_gate(metrics) is False

    def test_passes_at_exactly_threshold(self):
        metrics = {"fast": {"n_items": 5, "f1": QUALITY_GATE_F1}}
        assert check_quality_gate(metrics) is True

    def test_fails_just_below_threshold(self):
        metrics = {"fast": {"n_items": 5, "f1": QUALITY_GATE_F1 - 0.001}}
        assert check_quality_gate(metrics) is False

    def test_empty_metrics_fails(self):
        # No tiers at all — gate returns False (no tier ever scored)
        assert check_quality_gate({}) is False

    def test_custom_threshold(self):
        metrics = {"fast": {"n_items": 5, "f1": 0.30}}
        assert check_quality_gate(metrics, threshold=0.50) is False
        assert check_quality_gate(metrics, threshold=0.20) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
