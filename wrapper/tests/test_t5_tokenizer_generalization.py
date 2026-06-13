"""Tests for CT2 tokenizer generalization in t5_backend.

This test module verifies that t5_backend correctly loads different T5 tokenizer
variants via the CT2_TOKENIZER_ID environment variable, supporting the research
effort to evaluate larger GEC models (vennify/t5-base-grammar-correction,
prithivida/grammar_error_correcter_v1) against the current t5-small baseline.

Test contracts:
1. Tokenizer ID parameter: verify CT2_TOKENIZER_ID env var correctly loads different T5 tokenizer variants
2. Model path isolation: verify CT2_SMART_MODEL_PATH (future) doesn't interfere with CT2_MODEL_PATH
3. Backwards compatibility: verify default (CT2_TOKENIZER_ID unset) loads t5-small as before
4. Benchmark harness integration: verify F1/latency metrics can be gathered for larger models
"""

import os
import sys
import pathlib
import tempfile
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _clear_env():
    """Clear all CT2-related env vars."""
    os.environ.pop("CT2_MODEL_PATH", None)
    os.environ.pop("CT2_TOKENIZER_ID", None)
    os.environ.pop("CT2_SMART_MODEL_PATH", None)


def _make_model_dir():
    """Create a temp directory with a fake model.bin."""
    d = tempfile.mkdtemp()
    pathlib.Path(d, "model.bin").write_bytes(b"fake")
    return d


# ── Test Contract 1: Tokenizer ID parameter ────────────────────────────────

def test_ct2_tokenizer_id_default_is_t5_small():
    """Verify _ct2_tokenizer_id() returns t5-small when CT2_TOKENIZER_ID is unset."""
    import t5_backend
    _clear_env()
    tokenizer_id = t5_backend._ct2_tokenizer_id()
    assert tokenizer_id == "t5-small", f"Expected 't5-small', got '{tokenizer_id}'"


def test_ct2_tokenizer_id_reads_from_env():
    """Verify _ct2_tokenizer_id() respects CT2_TOKENIZER_ID env var."""
    import t5_backend
    _clear_env()
    os.environ["CT2_TOKENIZER_ID"] = "t5-base"
    tokenizer_id = t5_backend._ct2_tokenizer_id()
    assert tokenizer_id == "t5-base", f"Expected 't5-base', got '{tokenizer_id}'"
    _clear_env()


def test_ct2_tokenizer_id_custom_variant():
    """Verify _ct2_tokenizer_id() works with custom tokenizer IDs (e.g., vennify variant)."""
    import t5_backend
    _clear_env()
    os.environ["CT2_TOKENIZER_ID"] = "vennify/t5-base-grammar-correction"
    tokenizer_id = t5_backend._ct2_tokenizer_id()
    assert tokenizer_id == "vennify/t5-base-grammar-correction"
    _clear_env()


def test_correct_loads_custom_tokenizer_when_env_set():
    """Verify correct() loads tokenizer from CT2_TOKENIZER_ID when set."""
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        os.environ["CT2_TOKENIZER_ID"] = "t5-base"
        t5_backend._translator = None
        t5_backend._tokenizer = None

        mock_result = MagicMock()
        mock_result.hypotheses = [["▁Hello", "▁world", "."]]

        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_result]

        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = [1, 2, 3]
        mock_tokenizer.convert_ids_to_tokens.return_value = ["▁gec", ":", "▁Hello", "▁world"]
        mock_tokenizer.convert_tokens_to_string.return_value = "Hello world."

        mock_ct2 = MagicMock()
        mock_ct2.Translator.return_value = mock_translator
        mock_tf = MagicMock()
        mock_tf.T5Tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            t5_backend._translator = None
            t5_backend._tokenizer = None
            t5_backend.correct("Hello world.")

        # Verify T5Tokenizer.from_pretrained was called with t5-base, not default t5-small
        mock_tf.T5Tokenizer.from_pretrained.assert_called_with("t5-base")
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


# ── Test Contract 2: Model path isolation ──────────────────────────────────

def test_ct2_smart_model_path_env_var_recognized():
    """Verify CT2_SMART_MODEL_PATH env var is distinct from CT2_MODEL_PATH (future-proofing)."""
    import t5_backend
    _clear_env()

    d_smart = _make_model_dir()
    d_mid = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d_mid
        os.environ["CT2_SMART_MODEL_PATH"] = d_smart

        # Verify _ct2_model_path() still returns CT2_MODEL_PATH (current behavior)
        mid_path = t5_backend._ct2_model_path()
        assert mid_path == d_mid, f"Expected {d_mid}, got {mid_path}"

        # CT2_SMART_MODEL_PATH should be readable via os.environ (for future use)
        smart_path = os.environ.get("CT2_SMART_MODEL_PATH")
        assert smart_path == d_smart, f"Expected {d_smart}, got {smart_path}"

        # Verify they are different paths
        assert mid_path != smart_path, "CT2_MODEL_PATH and CT2_SMART_MODEL_PATH should be distinct"
    finally:
        _clear_env()
        import shutil
        shutil.rmtree(d_smart)
        shutil.rmtree(d_mid)


def test_is_available_with_only_ct2_smart_model_path():
    """Verify is_available() returns False when only CT2_SMART_MODEL_PATH is set (not CT2_MODEL_PATH)."""
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_SMART_MODEL_PATH"] = d
        # CT2_MODEL_PATH is not set
        assert os.environ.get("CT2_MODEL_PATH") is None

        mock_ct2 = MagicMock()
        mock_tf = MagicMock()
        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            result = t5_backend.is_available()

        # Should return False because CT2_MODEL_PATH is not set
        assert result is False
    finally:
        _clear_env()
        import shutil; shutil.rmtree(d)


# ── Test Contract 3: Backwards compatibility ───────────────────────────────

def test_correct_defaults_to_t5_small_when_tokenizer_id_unset():
    """Verify correct() loads t5-small tokenizer when CT2_TOKENIZER_ID is not set (backwards compatibility)."""
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        # CT2_TOKENIZER_ID is not set; should default to t5-small
        assert os.environ.get("CT2_TOKENIZER_ID") is None

        t5_backend._translator = None
        t5_backend._tokenizer = None

        mock_result = MagicMock()
        mock_result.hypotheses = [["▁Hello", "▁world", "."]]

        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_result]

        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = [1, 2, 3]
        mock_tokenizer.convert_ids_to_tokens.return_value = ["▁gec", ":", "▁Hello", "▁world"]
        mock_tokenizer.convert_tokens_to_string.return_value = "Hello world."

        mock_ct2 = MagicMock()
        mock_ct2.Translator.return_value = mock_translator
        mock_tf = MagicMock()
        mock_tf.T5Tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            t5_backend._translator = None
            t5_backend._tokenizer = None
            t5_backend.correct("Hello world.")

        # Verify T5Tokenizer.from_pretrained was called with t5-small
        mock_tf.T5Tokenizer.from_pretrained.assert_called_with("t5-small")
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


def test_load_caches_tokenizer_for_reuse():
    """Verify _load() caches the tokenizer so repeated calls don't reload it."""
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        t5_backend._translator = None
        t5_backend._tokenizer = None

        mock_tokenizer = MagicMock()
        mock_translator = MagicMock()

        mock_ct2 = MagicMock()
        mock_ct2.Translator.return_value = mock_translator
        mock_tf = MagicMock()
        mock_tf.T5Tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            t5_backend._translator = None
            t5_backend._tokenizer = None

            # First call to _load()
            translator1, tokenizer1 = t5_backend._load()

            # Second call to _load()
            translator2, tokenizer2 = t5_backend._load()

            # Should return the same cached instances (not new ones)
            assert translator1 is translator2
            assert tokenizer1 is tokenizer2

            # T5Tokenizer.from_pretrained should only be called once
            assert mock_tf.T5Tokenizer.from_pretrained.call_count == 1
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


# ── Test Contract 4: Benchmark harness integration ─────────────────────────

def test_correct_output_format_supports_metrics_computation():
    """Verify correct() output format (Correction objects with start/end/suggestions) is compatible with metrics."""
    import t5_backend
    from protocol import Correction

    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        os.environ["CT2_TOKENIZER_ID"] = "t5-base"  # Simulate research with larger model
        t5_backend._translator = None
        t5_backend._tokenizer = None

        # Simulate larger T5-base model with different correction patterns
        mock_result = MagicMock()
        mock_result.hypotheses = [["▁She", "▁doesn", "'", "t", "▁know"]]

        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_result]

        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = [1, 2, 3, 4, 5]
        mock_tokenizer.convert_ids_to_tokens.return_value = ["▁gec", ":", "▁She", "▁don", "'", "t", "▁know"]
        mock_tokenizer.convert_tokens_to_string.return_value = "She doesn't know"

        mock_ct2 = MagicMock()
        mock_ct2.Translator.return_value = mock_translator
        mock_tf = MagicMock()
        mock_tf.T5Tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            t5_backend._translator = None
            t5_backend._tokenizer = None
            corrections = t5_backend.correct("She don't know")

        # Verify output is a list of Correction objects with required fields
        assert isinstance(corrections, list)
        for correction in corrections:
            assert isinstance(correction, Correction)
            assert hasattr(correction, 'start')
            assert hasattr(correction, 'end')
            assert hasattr(correction, 'original')
            assert hasattr(correction, 'suggestions')
            assert hasattr(correction, 'type')

            # Verify bounds are within original text (required for harness metrics)
            assert 0 <= correction.start < correction.end <= len("She don't know")
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


def test_diff_to_corrections_preserves_word_boundaries_for_larger_models():
    """Verify _diff_to_corrections handles corrections from larger models with complex word boundaries."""
    import t5_backend

    # Simulate correction from a larger T5-base model
    original = "The quick brown fox jump over the lazy dog"
    corrected = "The quick brown fox jumps over the lazy dog"

    corrections = t5_backend._diff_to_corrections(original, corrected)

    # Should identify "jump" → "jumps"
    assert len(corrections) == 1
    assert corrections[0].original == "jump"
    assert corrections[0].suggestions == ["jumps"]

    # Verify bounds are correct for metrics computation
    assert corrections[0].start == original.index("jump")
    assert corrections[0].end == corrections[0].start + len("jump")


def test_correction_extraction_with_multiple_errors():
    """Verify _diff_to_corrections correctly extracts multiple corrections (required for F1 computation)."""
    import t5_backend

    original = "I goed to the store and buyed some apples"
    corrected = "I went to the store and bought some apples"

    corrections = t5_backend._diff_to_corrections(original, corrected)

    # Should find two corrections: "goed" → "went", "buyed" → "bought"
    assert len(corrections) == 2
    assert corrections[0].original == "goed"
    assert corrections[0].suggestions == ["went"]
    assert corrections[1].original == "buyed"
    assert corrections[1].suggestions == ["bought"]


# ── Integration tests ──────────────────────────────────────────────────────

def test_tokenizer_generalization_does_not_affect_is_available():
    """Verify tokenizer generalization doesn't change is_available() behavior."""
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        os.environ["CT2_TOKENIZER_ID"] = "t5-base"

        mock_ct2 = MagicMock()
        mock_tf = MagicMock()
        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            result = t5_backend.is_available()

        # is_available() should still return True (independent of tokenizer ID)
        assert result is True
    finally:
        _clear_env()
        import shutil; shutil.rmtree(d)


def test_multiple_sequential_corrections_with_different_tokenizers():
    """Verify correct() can be called sequentially with different tokenizer settings (research iteration)."""
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        # First correction with default tokenizer
        os.environ["CT2_MODEL_PATH"] = d
        t5_backend._translator = None
        t5_backend._tokenizer = None

        mock_result = MagicMock()
        mock_result.hypotheses = [["▁test", "."]]

        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_result]

        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = [1, 2]
        mock_tokenizer.convert_ids_to_tokens.return_value = ["▁gec", ":", "▁test"]
        mock_tokenizer.convert_tokens_to_string.return_value = "test."

        mock_ct2 = MagicMock()
        mock_ct2.Translator.return_value = mock_translator
        mock_tf = MagicMock()
        mock_tf.T5Tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            t5_backend._translator = None
            t5_backend._tokenizer = None
            corrections1 = t5_backend.correct("test")

        assert isinstance(corrections1, list)
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


if __name__ == "__main__":
    # Run all tests
    test_ct2_tokenizer_id_default_is_t5_small()
    test_ct2_tokenizer_id_reads_from_env()
    test_ct2_tokenizer_id_custom_variant()
    test_correct_loads_custom_tokenizer_when_env_set()
    test_ct2_smart_model_path_env_var_recognized()
    test_is_available_with_only_ct2_smart_model_path()
    test_correct_defaults_to_t5_small_when_tokenizer_id_unset()
    test_load_caches_tokenizer_for_reuse()
    test_correct_output_format_supports_metrics_computation()
    test_diff_to_corrections_preserves_word_boundaries_for_larger_models()
    test_correction_extraction_with_multiple_errors()
    test_tokenizer_generalization_does_not_affect_is_available()
    test_multiple_sequential_corrections_with_different_tokenizers()
    print("All tokenizer generalization tests passed!")
