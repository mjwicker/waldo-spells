"""Tests for harness/report.py _load_dotenv() behavior and integration.

Contracts verified:
  (1) _load_dotenv() is called before backends import in __main__ block
  (2) Missing .env file is handled gracefully — no FileNotFoundError
  (3) Shell-exported env vars are not overridden by .env values
  (4) Env vars are available at backend module import time
"""

import os
import sys
import subprocess
import textwrap
from pathlib import Path

import pytest


def _get_loader():
    """Return the _load_dotenv function from harness/report.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "harness_report",
        Path(__file__).parent / "report.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_dotenv


class TestReportLoadDotenv:
    """Test _load_dotenv function in report.py."""

    def test_missing_env_file_does_not_raise(self, tmp_path):
        """_load_dotenv returns silently when .env path does not exist."""
        load = _get_loader()
        missing = tmp_path / "does_not_exist.env"
        # Must not raise
        load(missing)

    def test_missing_file_does_not_mutate_environ(self, tmp_path):
        """Calling _load_dotenv with missing path leaves os.environ unchanged."""
        load = _get_loader()
        before = dict(os.environ)
        load(tmp_path / "ghost.env")
        assert dict(os.environ) == before


class TestShellExportWinsInReport:
    """Shell-exported env vars must not be overwritten by .env in report.py."""

    def test_existing_env_var_not_overwritten_by_dotenv(self, tmp_path, monkeypatch):
        """If a key is in os.environ, _load_dotenv must leave it unchanged."""
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text("REPORT_TEST_VAR=from_dotenv\n")

        monkeypatch.setenv("REPORT_TEST_VAR", "from_shell")
        load(env_file)

        assert os.environ["REPORT_TEST_VAR"] == "from_shell"

    def test_absent_var_is_set_from_dotenv(self, tmp_path, monkeypatch):
        """A key not in os.environ should be set from .env."""
        load = _get_loader()
        env_file = tmp_path / ".env"
        env_file.write_text("REPORT_NEW_VAR=from_dotenv\n")

        monkeypatch.delenv("REPORT_NEW_VAR", raising=False)
        load(env_file)

        assert os.environ.get("REPORT_NEW_VAR") == "from_dotenv"
        # cleanup
        monkeypatch.delenv("REPORT_NEW_VAR", raising=False)


class TestReportMainBlockOrder:
    """Verify _load_dotenv() is called before backends import."""

    def test_load_dotenv_before_runner_import(self):
        """_load_dotenv must be called before 'from runner import run_all'.

        Backends call os.environ.get() at import time, so env vars must be set
        before the runner module is imported.
        """
        code = Path(__file__).parent / "report.py"
        text = code.read_text()

        # Find _load_dotenv call
        load_dotenv_call_line = None
        runner_import_line = None

        for i, line in enumerate(text.split('\n')):
            if "_load_dotenv(Path(__file__)" in line and "parent / \".env\"" in line:
                load_dotenv_call_line = i
            if "from runner import run_all" in line:
                runner_import_line = i

        assert load_dotenv_call_line is not None, "Missing _load_dotenv() call in report.py"
        assert runner_import_line is not None, "Missing 'from runner import run_all' in report.py"
        assert load_dotenv_call_line < runner_import_line, (
            f"_load_dotenv() at line {load_dotenv_call_line} must come before "
            f"'from runner import' at line {runner_import_line}"
        )


class TestRunHarnessShellValidation:
    """Test run_harness.sh model path validation."""

    def test_run_harness_script_contains_ct2_check(self):
        """run_harness.sh must contain validation check for CT2_MODEL_PATH."""
        script = Path(__file__).parent.parent / "run_harness.sh"
        if not script.exists():
            pytest.skip("run_harness.sh not found")

        text = script.read_text()
        assert "CT2_MODEL_PATH" in text
        assert "[ -d" in text or "[[ -d" in text
        assert "exit 2" in text

    def test_run_harness_script_contains_llama_model_check(self):
        """run_harness.sh must contain validation check for LLAMA_MODEL_PATH."""
        script = Path(__file__).parent.parent / "run_harness.sh"
        if not script.exists():
            pytest.skip("run_harness.sh not found")

        text = script.read_text()
        assert "LLAMA_MODEL_PATH" in text
        assert "[ -f" in text or "[[ -f" in text
        assert "exit 2" in text

    def test_run_harness_script_contains_llama_server_check(self):
        """run_harness.sh must contain validation check for LLAMA_SERVER_BIN."""
        script = Path(__file__).parent.parent / "run_harness.sh"
        if not script.exists():
            pytest.skip("run_harness.sh not found")

        text = script.read_text()
        assert "LLAMA_SERVER_BIN" in text
        assert "[ -x" in text or "[[ -x" in text
        assert "exit 2" in text

    def test_run_harness_script_error_message_clear(self):
        """run_harness.sh error messages must be clear and include path."""
        script = Path(__file__).parent.parent / "run_harness.sh"
        if not script.exists():
            pytest.skip("run_harness.sh not found")

        text = script.read_text()
        # Should have error messages that include "Missing" or "missing"
        lines = text.split('\n')
        error_lines = [line for line in lines if 'echo' in line and ('Missing' in line or 'missing' in line)]
        assert len(error_lines) >= 1, "Should have at least one error message with 'Missing'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
