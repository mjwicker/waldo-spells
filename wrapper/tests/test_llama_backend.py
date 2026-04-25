"""Tests for llama_backend stub behavior (no model required)."""

import os
import sys
import pathlib
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llama_backend


def _clear_env():
    for k in ("LLAMA_MODEL_PATH", "LLAMA_SERVER_BIN", "LLAMA_SERVER_PORT", "LLAMA_SERVER_HOST"):
        os.environ.pop(k, None)


def test_is_available_no_env():
    _clear_env()
    assert llama_backend.is_available() is False


def test_is_available_nonexistent_model():
    _clear_env()
    os.environ["LLAMA_MODEL_PATH"] = "/tmp/nonexistent_model.gguf"
    assert llama_backend.is_available() is False


def test_is_available_file_exists_no_server():
    _clear_env()
    with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
        f.write(b"fake")
        tmp = f.name
    try:
        os.environ["LLAMA_MODEL_PATH"] = tmp
        # No server binary in env — returns False unless llama-server happens to be in PATH
        # We force it absent by pointing to a nonexistent binary
        os.environ["LLAMA_SERVER_BIN"] = "/nonexistent/llama-server"
        assert llama_backend.is_available() is False
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


def test_correct_raises_when_unavailable():
    _clear_env()
    try:
        llama_backend.correct("Hello world")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "unavailable" in str(e).lower()
        assert "LLAMA_MODEL_PATH" in str(e)


def test_correct_error_message_includes_install_hint():
    _clear_env()
    try:
        llama_backend.correct("test")
    except RuntimeError as e:
        assert "llama.cpp" in str(e) or "LLAMA_MODEL_PATH" in str(e)


def test_is_available_returns_bool():
    _clear_env()
    result = llama_backend.is_available()
    assert isinstance(result, bool)
