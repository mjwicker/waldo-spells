"""Tests for tier_unavailable handling in report.py main().

Contracts verified:
  (1) 100% tier_unavailable on smart tier → exit 0, WARNING printed to stderr.
  (2) 100% tier_unavailable on ALL tiers → exit 0, quality gate passes.
  (3) Mixed tier_unavailable + backend_error: if backend_error ratio >=95%, still exits 2.
  (4) check_quality_gate with skipped_tiers containing all tiers → True (all-skip pass).
  (5) check_quality_gate with skipped_tiers containing only some tiers and a non-skipped
      tier below threshold → False.
"""

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from runner import RunResult
from report import check_quality_gate, QUALITY_GATE_F1


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


class TestTierUnavailableExitsZero:
    """100% tier_unavailable rows → exit 0 with WARNING, not exit 2."""

    def test_all_tier_unavailable_on_smart_exits_zero(self, capsys):
        """When all smart-tier rows are tier_unavailable, main() exits 0 (not 2)."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(10)
        ]
        # All smart-tier rows are tier_unavailable (llama-server absent)
        results = [
            _make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}")
            for i in range(10)
        ]

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "smart"]),
        ):
            try:
                main()
                exit_code = 0
            except SystemExit as e:
                exit_code = e.code

        assert exit_code == 0, (
            f"Expected exit 0 for 100% tier_unavailable on smart, got exit {exit_code}"
        )

    def test_all_tier_unavailable_prints_warning_to_stderr(self, capsys):
        """When all rows are tier_unavailable, a WARNING is printed to stderr."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(10)
        ]
        results = [
            _make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}")
            for i in range(10)
        ]

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "smart"]),
        ):
            try:
                main()
            except SystemExit:
                pass

        captured = capsys.readouterr()
        assert "WARNING" in captured.err, (
            "Expected WARNING in stderr when tier is 100% tier_unavailable"
        )
        assert "smart" in captured.err, (
            "WARNING should mention the tier name"
        )

    def test_all_tiers_unavailable_exits_zero(self, capsys):
        """When every tier is 100% tier_unavailable, main() exits 0 (CI without LLM)."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(5)
        ]
        # fast and smart both entirely tier_unavailable
        results = (
            [_make_result("fast",  available=False, error="tier_unavailable: enchant not found", item_id=f"i{i}") for i in range(5)] +
            [_make_result("smart", available=False, error="tier_unavailable: llama-server not found", item_id=f"i{i}") for i in range(5)]
        )

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast,smart"]),
        ):
            try:
                main()
                exit_code = 0
            except SystemExit as e:
                exit_code = e.code

        assert exit_code == 0, (
            f"Expected exit 0 when ALL tiers are tier_unavailable, got exit {exit_code}"
        )


class TestMixedUnavailableAndBackendError:
    """When a tier has backend_error (not tier_unavailable) at >=95%, it still exits 2."""

    def test_backend_error_ratio_high_still_exits_2(self, capsys):
        """19/20 rows backend_error (not tier_unavailable) → exit 2."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(20)
        ]
        # 1 ran, 19 backend_error (not tier_unavailable)
        results = (
            [_make_result("fast", available=True,  error=None,             item_id="i0")] +
            [_make_result("fast", available=False, error="backend_error",  item_id=f"i{i}") for i in range(1, 20)]
        )

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2, (
            "Expected exit 2 when >=95% of rows are backend_error (not tier_unavailable)"
        )

    def test_mixed_unavailable_and_backend_error_exits_2_on_error_ratio(self, capsys):
        """A tier with some tier_unavailable AND mostly backend_error rows.

        Only backend_error rows count toward the >=95% error threshold.
        10 tier_unavailable + 9 backend_error out of 20 eligible:
        tier_unavailable_ratio = 10/20 = 0.50 → does NOT skip (< 0.95)
        error_ratio = 9/20 = 0.45 → does NOT exit 2 (< 0.95)
        → no exit
        """
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(20)
        ]
        results = (
            [_make_result("fast", available=True,  error=None,                                 item_id="i0")] +
            [_make_result("fast", available=False, error="tier_unavailable: model missing",    item_id=f"i{i}") for i in range(1, 11)] +
            [_make_result("fast", available=False, error="backend_error",                      item_id=f"i{i}") for i in range(11, 20)]
        )

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast"]),
        ):
            try:
                main()
                exit_code = 0
            except SystemExit as e:
                exit_code = e.code

        # Neither 50% unavailable nor 45% error reaches threshold — no forced exit
        assert exit_code != 2, (
            "Should not exit 2 when neither unavailable_ratio nor error_ratio reaches 0.95"
        )

    def test_all_tier_unavailable_does_not_exit_2(self, capsys):
        """100% tier_unavailable rows must never trigger the error-ratio exit 2 path."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(20)
        ]
        # All tier_unavailable — must NOT exit 2
        results = [
            _make_result("fast", available=False, error="tier_unavailable: enchant not found", item_id=f"i{i}")
            for i in range(20)
        ]

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast"]),
        ):
            try:
                main()
                exit_code = 0
            except SystemExit as e:
                exit_code = e.code

        assert exit_code != 2, (
            "100% tier_unavailable must not exit 2 — it should be treated as a skip"
        )


class TestQualityGateSkippedTiers:
    """check_quality_gate() with skipped_tiers — all-skip pass and partial-skip fail."""

    def test_all_tiers_in_skipped_tiers_returns_true(self):
        """When every tier in tier_metrics is in skipped_tiers, gate returns True."""
        metrics = {
            "fast":  {"n_items": 0, "f1": 0.00},
            "smart": {"n_items": 0, "f1": 0.00},
        }
        assert check_quality_gate(metrics, skipped_tiers={"fast", "smart"}) is True

    def test_skipped_tiers_with_non_skipped_below_threshold_returns_false(self):
        """When a non-skipped tier has n_items > 0 and f1 < threshold, gate returns False."""
        metrics = {
            "fast":  {"n_items": 10, "f1": 0.01},   # ran, below threshold
            "smart": {"n_items": 0,  "f1": 0.00},   # skipped (backend absent)
        }
        assert check_quality_gate(metrics, skipped_tiers={"smart"}) is False

    def test_skipped_tiers_only_some_with_passing_non_skipped_returns_true(self):
        """When a non-skipped tier passes the threshold, gate returns True even if some skipped."""
        metrics = {
            "fast":  {"n_items": 10, "f1": 0.50},   # ran, above threshold
            "smart": {"n_items": 0,  "f1": 0.00},   # skipped (backend absent)
        }
        assert check_quality_gate(metrics, skipped_tiers={"smart"}) is True

    def test_skipped_tiers_none_falls_back_to_normal_evaluation(self):
        """skipped_tiers=None is the same as skipped_tiers=set() — no change in behavior."""
        metrics = {"fast": {"n_items": 5, "f1": QUALITY_GATE_F1}}
        assert check_quality_gate(metrics, skipped_tiers=None) is True

    def test_all_tiers_skipped_with_items_still_returns_true(self):
        """Even if a skipped tier has n_items > 0 (edge case), the gate passes
        because the tier was explicitly skipped (backend absent)."""
        metrics = {
            "smart": {"n_items": 5, "f1": 0.00},   # in skipped_tiers despite having items
        }
        assert check_quality_gate(metrics, skipped_tiers={"smart"}) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
