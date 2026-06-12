"""Tests for write_summary() filtering of unavailable runs in report.py.

Contracts verified:
  (1) write_summary() reports "Total runs" with only available runs counted
  (2) Unavailable rows (tier_unavailable, backend_error) are excluded from count
  (3) Mixed tier availability (some tiers available, some unavailable) correctly
      filters to show only available rows
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from runner import RunResult


def _make_result(
    tier: str,
    available: bool = True,
    error: str | None = None,
    corrections: list | None = None,
    expected: list | None = None,
    item_id: str = "x",
) -> RunResult:
    return RunResult(
        item_id=item_id,
        tier=tier,
        input_type="general",
        latency_ms=1.0,
        corrections=corrections if corrections is not None else [],
        expected=expected if expected is not None else [],
        error=error,
        available=available,
    )


class TestWriteSummaryRunCount:
    """Verify write_summary() correctly counts available runs."""

    def test_all_available_runs_reported(self, tmp_path):
        """When all runs are available, Total runs = len(results)."""
        from report import write_summary

        results = [
            _make_result("fast", available=True, item_id=f"i{i}")
            for i in range(10)
        ]
        summary_path = tmp_path / "summary.md"

        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "- Total runs: 10\n" in content, (
            "When all 10 runs are available, Total runs should be 10"
        )

    def test_unavailable_runs_excluded_from_count(self, tmp_path):
        """When some runs are unavailable, Total runs excludes them."""
        from report import write_summary

        # 5 available, 5 unavailable (tier_unavailable)
        results = (
            [_make_result("smart", available=True, item_id=f"i{i}") for i in range(5)] +
            [_make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}") for i in range(5, 10)]
        )
        summary_path = tmp_path / "summary.md"

        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "- Total runs: 5\n" in content, (
            "With 5 available + 5 unavailable, Total runs should be 5 (unavailable excluded)"
        )

    def test_mixed_tiers_with_different_availability(self, tmp_path):
        """Mixed-tier scenario: fast all available, smart all unavailable."""
        from report import write_summary

        results = (
            [_make_result("fast", available=True, item_id=f"i{i}") for i in range(10)] +
            [_make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}") for i in range(10, 20)]
        )
        summary_path = tmp_path / "summary.md"

        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "- Total runs: 10\n" in content, (
            "With 10 fast (available) + 10 smart (unavailable), Total runs should be 10"
        )

    def test_backend_error_excluded_from_count(self, tmp_path):
        """Backend errors (available=False, not tier_unavailable) are excluded."""
        from report import write_summary

        # 5 successful, 5 backend_error
        results = (
            [_make_result("fast", available=True, item_id=f"i{i}") for i in range(5)] +
            [_make_result("fast", available=False, error="backend_error", item_id=f"i{i}") for i in range(5, 10)]
        )
        summary_path = tmp_path / "summary.md"

        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "- Total runs: 5\n" in content, (
            "With 5 available + 5 backend_error, Total runs should be 5"
        )

    def test_zero_available_runs_reports_zero(self, tmp_path):
        """When all runs are unavailable, Total runs = 0."""
        from report import write_summary

        results = [
            _make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}")
            for i in range(10)
        ]
        summary_path = tmp_path / "summary.md"

        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "- Total runs: 0\n" in content, (
            "When all 10 runs are unavailable, Total runs should be 0"
        )

    def test_single_available_run_among_many_unavailable(self, tmp_path):
        """Edge case: 1 available, 99 unavailable → Total runs = 1."""
        from report import write_summary

        results = (
            [_make_result("smart", available=True, item_id="i0")] +
            [_make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}") for i in range(1, 100)]
        )
        summary_path = tmp_path / "summary.md"

        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "- Total runs: 1\n" in content, (
            "With 1 available + 99 unavailable, Total runs should be 1"
        )


class TestWriteSummaryLatencyStats:
    """Verify write_summary() includes latency stats (unchanged by this fix)."""

    def test_latency_stats_included_in_summary(self, tmp_path):
        """Summary must include latency p50, p95, p99, mean."""
        from report import write_summary

        results = [
            _make_result("fast", available=True, item_id=f"i{i}", corrections=[], expected=[])
            for i in range(5)
        ]
        # Set varying latencies to get meaningful stats
        for i, r in enumerate(results):
            r.latency_ms = float(i + 1)  # 1, 2, 3, 4, 5

        summary_path = tmp_path / "summary.md"
        write_summary(results, summary_path, run_id="test_run")

        content = summary_path.read_text()
        assert "p50=" in content, "Summary should include p50 latency"
        assert "p95=" in content, "Summary should include p95 latency"
        assert "p99=" in content, "Summary should include p99 latency"
        assert "mean=" in content, "Summary should include mean latency"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
