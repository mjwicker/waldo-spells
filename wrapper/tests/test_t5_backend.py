"""Tests for t5_backend — all mocked, no ctranslate2/transformers required."""

import os
import sys
import pathlib
import tempfile
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _clear_env():
    os.environ.pop("CT2_MODEL_PATH", None)


def _make_model_dir():
    """Create a temp directory with a fake model.bin."""
    d = tempfile.mkdtemp()
    pathlib.Path(d, "model.bin").write_bytes(b"fake")
    return d


# ── is_available() ──────────────────────────────────────────────────────────

def test_is_available_no_env():
    import t5_backend
    t5_backend._translator = None
    t5_backend._tokenizer = None
    _clear_env()
    with patch.dict("sys.modules", {"ctranslate2": MagicMock(), "transformers": MagicMock()}):
        import importlib
        importlib.reload(t5_backend)
        assert t5_backend.is_available() is False


def test_is_available_no_ctranslate2():
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        saved = sys.modules.pop("ctranslate2", None)
        result = t5_backend.is_available()
        assert result is False
    finally:
        if saved:
            sys.modules["ctranslate2"] = saved
        os.environ.pop("CT2_MODEL_PATH", None)
        import shutil; shutil.rmtree(d)


def test_is_available_no_transformers():
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        mock_ct2 = MagicMock()
        saved_tf = sys.modules.pop("transformers", None)
        with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
            result = t5_backend.is_available()
        assert result is False
    finally:
        if saved_tf:
            sys.modules["transformers"] = saved_tf
        os.environ.pop("CT2_MODEL_PATH", None)
        import shutil; shutil.rmtree(d)


def test_is_available_model_dir_missing():
    import t5_backend
    _clear_env()
    os.environ["CT2_MODEL_PATH"] = "/nonexistent/path"
    mock_ct2 = MagicMock()
    mock_tf = MagicMock()
    try:
        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            result = t5_backend.is_available()
        assert result is False
    finally:
        _clear_env()


def test_is_available_model_bin_missing():
    import t5_backend
    _clear_env()
    d = tempfile.mkdtemp()  # dir exists but no model.bin
    try:
        os.environ["CT2_MODEL_PATH"] = d
        mock_ct2 = MagicMock()
        mock_tf = MagicMock()
        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            result = t5_backend.is_available()
        assert result is False
    finally:
        _clear_env()
        import shutil; shutil.rmtree(d)


def test_is_available_all_present():
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        mock_ct2 = MagicMock()
        mock_tf = MagicMock()
        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            result = t5_backend.is_available()
        assert result is True
    finally:
        _clear_env()
        import shutil; shutil.rmtree(d)


# ── correct() ───────────────────────────────────────────────────────────────

def test_correct_raises_when_unavailable():
    import t5_backend
    _clear_env()
    try:
        t5_backend.correct("Hello world")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        msg = str(e)
        assert "unavailable" in msg.lower() or "CT2_MODEL_PATH" in msg


def test_correct_error_message_includes_install_hint():
    import t5_backend
    _clear_env()
    try:
        t5_backend.correct("test")
    except RuntimeError as e:
        assert "ctranslate2" in str(e)
        assert "CT2_MODEL_PATH" in str(e)


def test_correct_no_errors_returns_empty():
    import t5_backend
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
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
            corrections = t5_backend.correct("Hello world.")
        assert corrections == []
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


def test_correct_returns_correction_for_changed_text():
    import t5_backend
    from protocol import Correction
    _clear_env()
    d = _make_model_dir()
    try:
        os.environ["CT2_MODEL_PATH"] = d
        t5_backend._translator = None
        t5_backend._tokenizer = None

        mock_result = MagicMock()
        mock_result.hypotheses = [["▁I", "▁went", "▁to", "▁the", "▁store"]]

        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_result]

        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = [1, 2, 3, 4, 5]
        mock_tokenizer.convert_ids_to_tokens.return_value = ["▁gec", ":", "▁I", "▁goed", "▁to", "▁the", "▁store"]
        mock_tokenizer.convert_tokens_to_string.return_value = "I went to the store"

        mock_ct2 = MagicMock()
        mock_ct2.Translator.return_value = mock_translator
        mock_tf = MagicMock()
        mock_tf.T5Tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch.dict("sys.modules", {"ctranslate2": mock_ct2, "transformers": mock_tf}):
            t5_backend._translator = None
            t5_backend._tokenizer = None
            corrections = t5_backend.correct("I goed to the store")

        assert len(corrections) == 1
        assert corrections[0].original == "goed"
        assert corrections[0].suggestions == ["went"]
        assert corrections[0].type == "grammar"
    finally:
        _clear_env()
        t5_backend._translator = None
        t5_backend._tokenizer = None
        import shutil; shutil.rmtree(d)


# ── _diff_to_corrections() ──────────────────────────────────────────────────

def test_diff_no_change():
    import t5_backend
    result = t5_backend._diff_to_corrections("Hello world", "Hello world")
    assert result == []


def test_diff_single_word_change():
    import t5_backend
    result = t5_backend._diff_to_corrections("I goed home", "I went home")
    assert len(result) == 1
    assert result[0].original == "goed"
    assert result[0].suggestions == ["went"]
    assert result[0].start == 2
    assert result[0].end == 6


def test_diff_offset_within_bounds():
    import t5_backend
    text = "She don't know"
    corrected = "She doesn't know"
    result = t5_backend._diff_to_corrections(text, corrected)
    for c in result:
        assert 0 <= c.start < c.end <= len(text)


if __name__ == "__main__":
    test_is_available_no_env()
    test_is_available_model_bin_missing()
    test_is_available_all_present()
    test_correct_raises_when_unavailable()
    test_correct_error_message_includes_install_hint()
    test_diff_no_change()
    test_diff_single_word_change()
    test_diff_offset_within_bounds()
    print("All t5_backend tests passed!")
