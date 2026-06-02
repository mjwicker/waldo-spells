"""Tests for CoLA grammar acceptability classification — T-SPELLS-EDGE-3.

Tests the replacement of DistilBERT SST-2 (sentiment model) with
textattack/bert-base-uncased-CoLA (grammar acceptability model) in the edge tier.
"""

import sys
from pathlib import Path

import pytest

# Add wrapper and harness to path
sys.path.insert(0, str(Path(__file__).parent.parent / "wrapper"))
sys.path.insert(0, str(Path(__file__).parent))

from corpus import load_corpus, CorpusItem
import onnx_backend
from runner import run_one, _run_edge, RunResult


class TestColaAvailable:
    """Test onnx_backend.cola_available()."""

    def test_cola_available_returns_bool(self):
        """cola_available() returns a boolean."""
        result = onnx_backend.cola_available()
        assert isinstance(result, bool)


class TestClassifyGrammar:
    """Test onnx_backend.classify_grammar()."""

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_returns_dict(self):
        """classify_grammar() returns a dict with required keys."""
        result = onnx_backend.classify_grammar("This is a grammatically correct sentence.")
        assert isinstance(result, dict)
        assert "label" in result
        assert "score" in result
        assert "scores" in result
        assert "model" in result

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_label_is_valid(self):
        """classify_grammar() returns label as 'acceptable' or 'unacceptable'."""
        result = onnx_backend.classify_grammar("The dog runs quickly.")
        assert result["label"] in ("acceptable", "unacceptable")

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_score_in_range(self):
        """classify_grammar() returns score in [0, 1]."""
        result = onnx_backend.classify_grammar("Dogs are loyal animals.")
        assert 0.0 <= result["score"] <= 1.0

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_scores_dict_has_both_labels(self):
        """classify_grammar() returns scores with acceptable and unacceptable."""
        result = onnx_backend.classify_grammar("I love cats.")
        assert "acceptable" in result["scores"]
        assert "unacceptable" in result["scores"]
        assert 0.0 <= result["scores"]["acceptable"] <= 1.0
        assert 0.0 <= result["scores"]["unacceptable"] <= 1.0
        # Probabilities should sum to ~1.0 (allow floating point tolerance)
        total = result["scores"]["acceptable"] + result["scores"]["unacceptable"]
        assert 0.99 <= total <= 1.01

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_model_field_identifies_cola(self):
        """classify_grammar() 'model' field includes CoLA identifier."""
        result = onnx_backend.classify_grammar("This sentence is fine.")
        assert "model" in result
        assert "CoLA" in result["model"] or "cola" in result["model"].lower()

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_acceptable_example(self):
        """classify_grammar() classifies clearly acceptable sentence as acceptable."""
        result = onnx_backend.classify_grammar("The quick brown fox jumps over the lazy dog.")
        # Should be acceptable with reasonable confidence
        assert result["label"] == "acceptable"
        assert result["scores"]["acceptable"] > 0.5

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_classify_grammar_unacceptable_example(self):
        """classify_grammar() classifies clearly unacceptable sentence as unacceptable."""
        result = onnx_backend.classify_grammar("I goed to the store yesterday.")
        # Should be unacceptable (wrong past tense) with reasonable confidence
        assert result["label"] == "unacceptable"
        assert result["scores"]["unacceptable"] > 0.5

    def test_classify_grammar_raises_if_unavailable(self):
        """classify_grammar() raises RuntimeError if CoLA model is unavailable."""
        if onnx_backend.cola_available():
            pytest.skip("CoLA model is available; skipping unavailable test")

        with pytest.raises(RuntimeError, match="CoLA"):
            onnx_backend.classify_grammar("test")


class TestBenchmarkGrammar:
    """Test onnx_backend.benchmark_grammar()."""

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_benchmark_grammar_returns_dict(self):
        """benchmark_grammar() returns a dict with required fields."""
        texts = ["The dog runs.", "I goed there."]
        labels = ["acceptable", "unacceptable"]
        result = onnx_backend.benchmark_grammar(texts, labels)
        assert isinstance(result, dict)
        assert "model" in result
        assert "n_total" in result
        assert "n_correct" in result
        assert "accuracy" in result
        assert "latency_ms_mean" in result
        assert "latency_ms_p95" in result

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_benchmark_grammar_counts_items(self):
        """benchmark_grammar() counts all items correctly."""
        texts = ["Good sentence.", "Bad sentences.", "Another good one.", "He do go."]
        labels = ["acceptable", "unacceptable", "acceptable", "unacceptable"]
        result = onnx_backend.benchmark_grammar(texts, labels)
        assert result["n_total"] == 4

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_benchmark_grammar_latency_is_reasonable(self):
        """benchmark_grammar() latency is below 1000ms per item (sanity check)."""
        texts = ["Test sentence.", "Another test."]
        labels = ["acceptable", "acceptable"]
        result = onnx_backend.benchmark_grammar(texts, labels)
        # Mean latency should be < 1000ms per item (generous upper bound)
        assert result["latency_ms_mean"] < 1000.0
        assert result["latency_ms_p95"] < 1000.0

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_benchmark_grammar_accuracy_field_exists(self):
        """benchmark_grammar() produces accuracy and latency metrics."""
        texts = ["He runs fast.", "He do run fast."]
        labels = ["acceptable", "unacceptable"]
        result = onnx_backend.benchmark_grammar(texts, labels)
        assert result["accuracy"] >= 0.0
        assert result["latency_ms_mean"] > 0.0
        assert result["latency_ms_p95"] > 0.0

    def test_benchmark_grammar_raises_if_unavailable(self):
        """benchmark_grammar() raises RuntimeError if CoLA model is unavailable."""
        if onnx_backend.cola_available():
            pytest.skip("CoLA model is available; skipping unavailable test")

        with pytest.raises(RuntimeError, match="unavailable"):
            onnx_backend.benchmark_grammar(["test"], ["acceptable"])


class TestRunEdgeGrammarTask:
    """Test _run_edge() with grammar task."""

    @pytest.fixture
    def grammar_item_acceptable(self):
        """Create a mock acceptable grammar task corpus item."""
        return CorpusItem(
            id="grammar_acceptable_001",
            input_type="general",
            text="The cat sits on the mat.",
            expected_corrections=[],
            should_skip=False,
            task="grammar",
            expected_label="acceptable",
        )

    @pytest.fixture
    def grammar_item_unacceptable(self):
        """Create a mock unacceptable grammar task corpus item."""
        return CorpusItem(
            id="grammar_unacceptable_001",
            input_type="general",
            text="The cat sit on the mat.",
            expected_corrections=[{"start": 8, "end": 11, "correction": "sits"}],
            should_skip=False,
            task="grammar",
            expected_label="unacceptable",
        )

    def test_run_edge_grammar_cola_unavailable(self, grammar_item_acceptable):
        """_run_edge() returns tier_unavailable when CoLA model is missing."""
        if onnx_backend.cola_available():
            pytest.skip("CoLA model is available; skipping unavailable test")

        result = _run_edge(grammar_item_acceptable)
        assert result.item_id == grammar_item_acceptable.id
        assert result.tier == "edge"
        assert result.task == "grammar"
        assert result.available is False
        assert "tier_unavailable" in (result.error or "")

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_run_edge_grammar_returns_valid_runresult(self, grammar_item_acceptable):
        """_run_edge() with grammar task returns a valid RunResult."""
        result = _run_edge(grammar_item_acceptable)
        assert isinstance(result, RunResult)
        assert result.item_id == grammar_item_acceptable.id
        assert result.tier == "edge"
        assert result.task == "grammar"
        assert result.available is True
        assert result.latency_ms >= 0.0
        assert isinstance(result.corrections, list)
        assert isinstance(result.expected, list)

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_run_edge_grammar_acceptable_label(self, grammar_item_acceptable):
        """_run_edge() grammar task returns predicted_label for acceptable sentence."""
        result = _run_edge(grammar_item_acceptable)
        assert result.predicted_label in ("acceptable", "unacceptable")
        # For a clearly acceptable sentence, expect acceptable label
        assert result.predicted_label == "acceptable"

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_run_edge_grammar_unacceptable_label(self, grammar_item_unacceptable):
        """_run_edge() grammar task returns predicted_label for unacceptable sentence."""
        result = _run_edge(grammar_item_unacceptable)
        assert result.predicted_label in ("acceptable", "unacceptable")
        # For a clearly unacceptable sentence, expect unacceptable label
        assert result.predicted_label == "unacceptable"


class TestRunEdgeToneTask:
    """Test _run_edge() with tone task (should use SST-2, not CoLA)."""

    @pytest.fixture
    def tone_item(self):
        """Create a mock tone task corpus item."""
        return CorpusItem(
            id="tone_001",
            input_type="general",
            text="I absolutely love this!",
            expected_corrections=[],
            should_skip=False,
            task="tone",
            expected_label="positive",
        )

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_run_edge_tone_returns_valid_result(self, tone_item):
        """_run_edge() with tone task still works (uses SST-2)."""
        result = _run_edge(tone_item)
        assert result.item_id == tone_item.id
        assert result.tier == "edge"
        assert result.task == "tone"
        assert result.available is True
        assert result.predicted_label in ("positive", "negative")


class TestRunEdgeSpanCorrectionRejection:
    """Test _run_edge() rejects span_correction tasks with updated error."""

    @pytest.fixture
    def span_correction_item(self):
        """Create a mock span correction corpus item."""
        return CorpusItem(
            id="span_001",
            input_type="email",
            text="I goed to the store.",
            expected_corrections=[{"start": 2, "end": 6, "correction": "went"}],
            should_skip=False,
            task="span_correction",
        )

    def test_run_edge_span_correction_rejected(self, span_correction_item):
        """_run_edge() marks span_correction as tier_not_applicable."""
        result = _run_edge(span_correction_item)
        assert result.item_id == span_correction_item.id
        assert result.tier == "edge"
        assert result.task == "span_correction"
        assert result.available is False
        assert "tier_not_applicable" in (result.error or "")
        # Updated error message should mention grammar and tone tasks only
        assert "grammar" in (result.error or "").lower() or "tone" in (result.error or "").lower()


class TestRunOneEdgeTier:
    """Test run_one() with edge tier and grammar tasks."""

    @pytest.fixture
    def grammar_item(self):
        """Create a mock grammar task corpus item."""
        return CorpusItem(
            id="grammar_002",
            input_type="general",
            text="She walks to school every day.",
            expected_corrections=[],
            should_skip=False,
            task="grammar",
            expected_label="acceptable",
        )

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_run_one_grammar_with_edge_tier(self, grammar_item):
        """run_one() with tier='edge' and grammar task returns result."""
        result = run_one(grammar_item, "edge")
        assert result.tier == "edge"
        assert result.task == "grammar"
        assert result.available is True
        assert result.predicted_label in ("acceptable", "unacceptable")


class TestEdgeTierIntegration:
    """Integration tests for edge tier with grammar tasks."""

    @pytest.mark.skipif(
        not onnx_backend.cola_available(),
        reason="CoLA model not available"
    )
    def test_edge_tier_grammar_integration(self):
        """Edge tier correctly processes grammar task from corpus."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        if not corpus_path.exists():
            pytest.skip("corpus.jsonl not found")

        corpus = load_corpus(corpus_path)
        grammar_items = [item for item in corpus if getattr(item, "task", "span_correction") == "grammar"]

        if not grammar_items:
            pytest.skip("No grammar tasks in corpus")

        # Test first grammar item
        item = grammar_items[0]
        result = _run_edge(item)
        assert result.tier == "edge"
        assert result.task == "grammar"
        assert result.available is True
        assert result.predicted_label in ("acceptable", "unacceptable")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
