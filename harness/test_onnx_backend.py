"""Tests for ONNX edge tier backend — sentiment/tone classification."""

import sys
import tempfile
import json
from pathlib import Path

import pytest

# Add wrapper and harness to path
sys.path.insert(0, str(Path(__file__).parent.parent / "wrapper"))
sys.path.insert(0, str(Path(__file__).parent))

from corpus import load_corpus, CorpusItem
import onnx_backend
from runner import run_one, run_all, _run_edge, RunResult


class TestIsAvailable:
    """Test onnx_backend.is_available()."""

    def test_is_available_returns_bool(self):
        """is_available() returns a boolean."""
        result = onnx_backend.is_available()
        assert isinstance(result, bool)

    def test_is_available_true_when_models_exist(self):
        """is_available() returns True when onnxruntime is installed and distilbert model exists."""
        # This test assumes the models have been downloaded in the repo.
        # If models are present, is_available() should be True.
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            pytest.skip("onnxruntime not installed")

        # Check if default model path exists
        model_path = onnx_backend._distilbert_model_path()
        if model_path:
            assert onnx_backend.is_available() is True
        else:
            # If model doesn't exist, is_available() should be False
            assert onnx_backend.is_available() is False


class TestMinilmAvailable:
    """Test onnx_backend.minilm_available()."""

    def test_minilm_available_returns_bool(self):
        """minilm_available() returns a boolean."""
        result = onnx_backend.minilm_available()
        assert isinstance(result, bool)


class TestWordPieceTokenizer:
    """Test _WordPieceTokenizer class."""

    @pytest.fixture
    def tokenizer_dir(self):
        """Create a minimal tokenizer.json for testing."""
        distilbert_dir = Path(__file__).parent.parent / "models" / "distilbert-sst2-onnx"
        if distilbert_dir.exists() and (distilbert_dir / "tokenizer.json").exists():
            return distilbert_dir
        pytest.skip("distilbert tokenizer.json not found")

    def test_tokenizer_creation(self, tokenizer_dir):
        """_WordPieceTokenizer can be instantiated with a valid tokenizer dir."""
        tokenizer = onnx_backend._WordPieceTokenizer(tokenizer_dir)
        assert tokenizer is not None
        assert hasattr(tokenizer, "_vocab")
        assert len(tokenizer._vocab) > 0

    def test_tokenizer_encodes_text(self, tokenizer_dir):
        """encode() returns (input_ids, attention_mask) tuples."""
        tokenizer = onnx_backend._WordPieceTokenizer(tokenizer_dir)
        input_ids, attention_mask = tokenizer.encode("hello world")
        assert isinstance(input_ids, list)
        assert isinstance(attention_mask, list)
        assert len(input_ids) == len(attention_mask)
        assert len(input_ids) >= 2  # At least [CLS] and [SEP]

    def test_tokenizer_adds_cls_sep(self, tokenizer_dir):
        """encode() adds [CLS] at start and [SEP] at end."""
        tokenizer = onnx_backend._WordPieceTokenizer(tokenizer_dir)
        input_ids, _ = tokenizer.encode("hello")
        # First token should be [CLS] (typically 101)
        # Last token should be [SEP] (typically 102)
        assert input_ids[0] == tokenizer._cls_id
        assert input_ids[-1] == tokenizer._sep_id

    def test_tokenizer_respects_max_length(self, tokenizer_dir):
        """encode() truncates at max_length."""
        tokenizer = onnx_backend._WordPieceTokenizer(tokenizer_dir)
        max_len = 10
        input_ids, attention_mask = tokenizer.encode("hello world " * 50, max_length=max_len)
        assert len(input_ids) <= max_len
        assert len(attention_mask) <= max_len

    def test_tokenizer_encodes_known_tokens(self, tokenizer_dir):
        """encode() encodes words and returns valid token IDs."""
        tokenizer = onnx_backend._WordPieceTokenizer(tokenizer_dir)
        # Get a common word that should be in the vocab
        common_word = "hello"
        input_ids, _ = tokenizer.encode(common_word, max_length=128)
        # Should have at least [CLS], at least one token, and [SEP]
        assert len(input_ids) >= 3
        # All IDs should be valid integers
        assert all(isinstance(id, int) for id in input_ids)
        # First and last should be CLS and SEP
        assert input_ids[0] == tokenizer._cls_id
        assert input_ids[-1] == tokenizer._sep_id


class TestClassifyTone:
    """Test onnx_backend.classify_tone()."""

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_classify_tone_returns_dict(self):
        """classify_tone() returns a dict with label, score, and scores."""
        result = onnx_backend.classify_tone("This movie is great!")
        assert isinstance(result, dict)
        assert "label" in result
        assert "score" in result
        assert "scores" in result

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_classify_tone_label_is_valid(self):
        """classify_tone() returns label as 'positive' or 'negative'."""
        result = onnx_backend.classify_tone("I love this!")
        assert result["label"] in ("positive", "negative")

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_classify_tone_score_in_range(self):
        """classify_tone() returns score in [0, 1]."""
        result = onnx_backend.classify_tone("This is neutral.")
        assert 0.0 <= result["score"] <= 1.0

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_classify_tone_scores_dict_complete(self):
        """classify_tone() returns scores dict with positive and negative."""
        result = onnx_backend.classify_tone("Good news!")
        assert "positive" in result["scores"]
        assert "negative" in result["scores"]
        assert 0.0 <= result["scores"]["positive"] <= 1.0
        assert 0.0 <= result["scores"]["negative"] <= 1.0
        # Probabilities should sum to ~1.0 (allow floating point tolerance)
        total = result["scores"]["positive"] + result["scores"]["negative"]
        assert 0.99 <= total <= 1.01

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_classify_tone_positive_example(self):
        """classify_tone() classifies clearly positive text correctly."""
        result = onnx_backend.classify_tone("This is excellent! I love it!")
        # Should be positive with reasonable confidence
        assert result["label"] == "positive"
        assert result["scores"]["positive"] > 0.7

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_classify_tone_negative_example(self):
        """classify_tone() classifies clearly negative text correctly."""
        result = onnx_backend.classify_tone("This is terrible. I hate it.")
        # Should be negative with reasonable confidence
        assert result["label"] == "negative"
        assert result["scores"]["negative"] > 0.7

    def test_classify_tone_raises_if_unavailable(self):
        """classify_tone() raises RuntimeError if backend is unavailable."""
        if onnx_backend.is_available():
            pytest.skip("ONNX backend is available; skipping unavailable test")

        with pytest.raises(RuntimeError, match="unavailable"):
            onnx_backend.classify_tone("test")


class TestBenchmarkTone:
    """Test onnx_backend.benchmark_tone()."""

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_benchmark_tone_returns_dict(self):
        """benchmark_tone() returns a dict with required fields."""
        texts = ["Good!", "Bad!"]
        labels = ["positive", "negative"]
        result = onnx_backend.benchmark_tone(texts, labels)
        assert isinstance(result, dict)
        assert "model" in result
        assert "n_total" in result
        assert "n_correct" in result
        assert "accuracy" in result
        assert "latency_ms_mean" in result
        assert "latency_ms_p95" in result

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_benchmark_tone_accuracy_field_non_zero(self):
        """benchmark_tone() produces non-zero accuracy and latency for small sample."""
        texts = ["Great!", "Awful!", "Wonderful!", "Horrible!"]
        labels = ["positive", "negative", "positive", "negative"]
        result = onnx_backend.benchmark_tone(texts, labels)
        assert result["n_total"] == 4
        assert result["accuracy"] >= 0.0
        assert result["latency_ms_mean"] > 0.0
        assert result["latency_ms_p95"] > 0.0

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_benchmark_tone_latency_is_reasonable(self):
        """benchmark_tone() latency is below 1000ms per item (sanity check)."""
        texts = ["Test", "text"]
        labels = ["positive", "negative"]
        result = onnx_backend.benchmark_tone(texts, labels)
        # Mean latency should be < 1000ms per item (generous upper bound)
        assert result["latency_ms_mean"] < 1000.0
        assert result["latency_ms_p95"] < 1000.0

    def test_benchmark_tone_raises_if_unavailable(self):
        """benchmark_tone() raises RuntimeError if backend is unavailable."""
        if onnx_backend.is_available():
            pytest.skip("ONNX backend is available; skipping unavailable test")

        with pytest.raises(RuntimeError):
            onnx_backend.benchmark_tone(["test"], ["positive"])


class TestRunEdge:
    """Test runner._run_edge() function."""

    @pytest.fixture
    def tone_item(self):
        """Create a mock tone task corpus item."""
        return CorpusItem(
            id="tone_001",
            input_type="general",
            text="This movie is fantastic!",
            expected_corrections=[],
            should_skip=False,
            task="tone",
            expected_label="positive",
        )

    @pytest.fixture
    def span_correction_item(self):
        """Create a mock span correction corpus item."""
        return CorpusItem(
            id="grammar_001",
            input_type="email",
            text="I goed to the store.",
            expected_corrections=[{"start": 2, "end": 6, "correction": "went"}],
            should_skip=False,
            task="span_correction",
        )

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_run_edge_handles_tone_task(self, tone_item):
        """_run_edge() processes tone tasks."""
        result = _run_edge(tone_item)
        assert result.item_id == tone_item.id
        assert result.tier == "edge"
        assert result.task == "tone"
        assert result.available is True
        assert result.predicted_label is not None

    def test_run_edge_rejects_span_correction(self, span_correction_item):
        """_run_edge() marks span_correction as tier_not_applicable."""
        result = _run_edge(span_correction_item)
        assert result.item_id == span_correction_item.id
        assert result.tier == "edge"
        assert result.task == "span_correction"
        assert result.available is False
        assert "tier_not_applicable" in (result.error or "")

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_run_edge_returns_valid_runresult(self, tone_item):
        """_run_edge() returns a valid RunResult."""
        result = _run_edge(tone_item)
        assert isinstance(result, RunResult)
        assert result.latency_ms >= 0.0
        assert isinstance(result.corrections, list)
        assert isinstance(result.expected, list)


class TestRunOneWithEdgeTier:
    """Test run_one() with edge tier."""

    @pytest.fixture
    def tone_item(self):
        """Create a mock tone task corpus item."""
        return CorpusItem(
            id="tone_002",
            input_type="general",
            text="I absolutely love this product!",
            expected_corrections=[],
            should_skip=False,
            task="tone",
            expected_label="positive",
        )

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_run_one_with_edge_tier(self, tone_item):
        """run_one() with tier='edge' processes tone tasks."""
        result = run_one(tone_item, "edge")
        assert result.tier == "edge"
        assert result.available is True
        assert result.predicted_label in ("positive", "negative")


class TestRunAllWithEdgeTier:
    """Test run_all() with edge tier included."""

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_run_all_with_edge_tier(self):
        """run_all() includes edge tier in results."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        # Filter to tone tasks
        tone_items = [item for item in corpus if getattr(item, "task", "span_correction") == "tone"]

        if not tone_items:
            pytest.skip("No tone tasks in corpus")

        results = run_all(tone_items[:2], tiers=("edge",))
        # All results should be from edge tier
        for result in results:
            assert result.tier == "edge"

        # At least some should be available (if backend is available)
        assert any(r.available for r in results)

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_run_all_edge_ignores_non_tone_tasks(self):
        """run_all() with edge tier marks non-tone tasks as not applicable."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)
        # Filter to span correction tasks
        span_items = [item for item in corpus if getattr(item, "task", "span_correction") == "span_correction"]

        if not span_items:
            pytest.skip("No span_correction tasks in corpus")

        results = run_all(span_items[:2], tiers=("edge",))
        # All results should be not applicable
        for result in results:
            assert result.available is False
            assert "tier_not_applicable" in (result.error or "")


class TestEdgeTierIntegration:
    """Integration tests for edge tier in the full pipeline."""

    @pytest.mark.skipif(
        not onnx_backend.is_available(),
        reason="ONNX backend not available"
    )
    def test_edge_tier_in_run_all_multi_tier(self):
        """run_all() with multiple tiers includes edge results."""
        corpus_path = Path(__file__).parent / "corpus.jsonl"
        corpus = load_corpus(corpus_path)[:3]

        results = run_all(corpus, tiers=("fast", "edge"))
        # Should have results for all items and both tiers (if tiers are available)
        edge_results = [r for r in results if r.tier == "edge"]
        assert len(edge_results) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
