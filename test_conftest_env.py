"""Tests for root conftest .env loader behavior.

Contracts verified:
  (1) Shell-exported env var wins over .env value (no overwrite)
  (2) Missing .env file is handled gracefully — no FileNotFoundError
  (3) CT2_MODEL_PATH and LLAMA_MODEL_PATH are present in os.environ after collection
  (4) Malformed .env lines (no =, comments, blank lines) are skipped without error
"""

import os
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Re-import the private loader so we can call it in isolation without
# mutating the real os.environ globally.  We extract _load_dotenv from the
# root conftest module.
# ---------------------------------------------------------------------------

def _get_loader():
    """Return the _load_dotenv function from the root conftest."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "root_conftest",
        Path(__file__).parent / "conftest.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_dotenv


class TestShellExportWins:
    """Shell-exported env var must not be overwritten by .env value."""

    def test_existing_env_var_not_overwritten(self, tmp_path, monkeypatch):
        """If a key is already in os.environ, _load_dotenv must leave it unchanged."""
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_VAR=from_dotenv\n")

        monkeypatch.setenv("MY_TEST_VAR", "from_shell")
        load(env_file)

        assert os.environ["MY_TEST_VAR"] == "from_shell"

    def test_absent_var_is_set_from_dotenv(self, tmp_path, monkeypatch):
        """A key not in os.environ should be set from .env."""
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text("MY_NEW_VAR=from_dotenv\n")

        monkeypatch.delenv("MY_NEW_VAR", raising=False)
        load(env_file)

        assert os.environ.get("MY_NEW_VAR") == "from_dotenv"
        # cleanup
        monkeypatch.delenv("MY_NEW_VAR", raising=False)


class TestMissingEnvFile:
    """A missing .env file must not raise FileNotFoundError."""

    def test_missing_file_does_not_raise(self, tmp_path):
        """_load_dotenv returns silently when the path does not exist."""
        load = _get_loader()
        missing = tmp_path / "does_not_exist.env"
        # Must not raise
        load(missing)

    def test_missing_file_does_not_mutate_environ(self, tmp_path):
        """Calling _load_dotenv with a missing path leaves os.environ unchanged."""
        load = _get_loader()
        before = dict(os.environ)
        load(tmp_path / "ghost.env")
        assert dict(os.environ) == before


class TestEnvVarPresenceAfterCollection:
    """CT2_MODEL_PATH and LLAMA_MODEL_PATH must be present after pytest collection.

    conftest.py runs _load_dotenv at import time, so by the time any test
    executes both keys should be in os.environ (either from the real .env or
    from the shell environment).
    """

    def test_ct2_model_path_present(self):
        assert "CT2_MODEL_PATH" in os.environ, (
            "CT2_MODEL_PATH missing — check WaldoSpells/.env or shell export"
        )

    def test_llama_model_path_present(self):
        assert "LLAMA_MODEL_PATH" in os.environ, (
            "LLAMA_MODEL_PATH missing — check WaldoSpells/.env or shell export"
        )


class TestMalformedDotenvLines:
    """Malformed lines must be skipped without raising an exception."""

    def _write_and_load(self, tmp_path, content, monkeypatch):
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text(textwrap.dedent(content))
        # Remove any vars we're about to test so we can detect if they were set
        monkeypatch.delenv("GOOD_VAR", raising=False)
        load(env_file)
        return os.environ.get("GOOD_VAR")

    def test_comment_lines_skipped(self, tmp_path, monkeypatch):
        """Lines starting with # are ignored."""
        value = self._write_and_load(
            tmp_path,
            """\
            # This is a comment
            GOOD_VAR=hello
            """,
            monkeypatch,
        )
        assert value == "hello"
        monkeypatch.delenv("GOOD_VAR", raising=False)

    def test_blank_lines_skipped(self, tmp_path, monkeypatch):
        """Blank lines between entries do not cause errors."""
        value = self._write_and_load(
            tmp_path,
            """\

            GOOD_VAR=world

            """,
            monkeypatch,
        )
        assert value == "world"
        monkeypatch.delenv("GOOD_VAR", raising=False)

    def test_line_without_equals_skipped(self, tmp_path, monkeypatch):
        """A line with no '=' is skipped; subsequent valid lines still load."""
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text("NOEQUALS\nGOOD_VAR=ok\n")
        monkeypatch.delenv("NOEQUALS", raising=False)
        monkeypatch.delenv("GOOD_VAR", raising=False)
        # Must not raise
        load(env_file)
        assert os.environ.get("GOOD_VAR") == "ok"
        assert "NOEQUALS" not in os.environ
        monkeypatch.delenv("GOOD_VAR", raising=False)

    def test_all_malformed_no_exception(self, tmp_path):
        """A .env with only malformed lines does not raise."""
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nNO_EQUALS_HERE\n   \n")
        # Must not raise
        load(env_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
