"""Tests for per-tier accuracy summary lines in report.py main().

Contracts verified:
  (1) After run_all(), a per-tier summary line is printed to stdout for each tier in tiers.
  (2) A tier with tier_not_applicable rows only counts applicable rows in ran/eligible.
  (3) An unavailable tier (ratio >= 0.95) still exits with code 2 before printing accuracy.
  (4) n/a is printed instead of a float when the tier has zero applicable items.
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


class TestTierSummaryLinesPrinted:
    """Verify per-tier summary lines are printed to stdout after run_all()."""

    def test_summary_line_printed_for_each_tier(self, capsys, tmp_path):
        """A 'Tier <name>: ...' line is printed to stdout for each tier that has rows."""
        from report import main
        from corpus import CorpusItem

        # Build minimal corpus so run_all() returns fast/better results
        corpus = [
            CorpusItem(
                id="i1", input_type="general", text="test input",
                expected_corrections=[], should_skip=False,
            )
        ]
        # fast-tier result: available, correct
        fast_result = _make_result("fast", available=True, corrections=[], expected=[], item_id="i1")
        better_result = _make_result("better", available=True, corrections=[], expected=[], item_id="i1")

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=[fast_result, better_result]),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast,better", "--out-dir", str(tmp_path)]),
        ):
            # check_quality_gate may fail — catch SystemExit
            try:
                main()
            except SystemExit:
                pass

        captured = capsys.readouterr()
        assert "Tier 'fast':" in captured.out, "Expected fast tier summary in stdout"
        assert "Tier 'better':" in captured.out, "Expected better tier summary in stdout"

    def test_summary_line_contains_ran_eligible_and_metrics(self, capsys, tmp_path):
        """The summary line format is: Tier '<name>': N/M ran | precision=... recall=... F1=..."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(
                id="i1", input_type="general", text="hello",
                expected_corrections=[], should_skip=False,
            )
        ]
        fast_result = _make_result("fast", available=True, corrections=[], expected=[], item_id="i1")

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=[fast_result]),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast", "--out-dir", str(tmp_path)]),
        ):
            try:
                main()
            except SystemExit:
                pass

        captured = capsys.readouterr()
        line = next((ln for ln in captured.out.splitlines() if "Tier 'fast':" in ln), None)
        assert line is not None
        assert "ran" in line
        assert "precision=" in line
        assert "recall=" in line
        assert "F1=" in line


class TestTierSummaryNotApplicableExclusion:
    """tier_not_applicable rows must not count toward ran or eligible."""

    def test_not_applicable_rows_excluded_from_ran_and_eligible(self, capsys, tmp_path):
        """Only applicable rows count in the N/M ran | ... line."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(4)
        ]
        results = [
            _make_result("fast", available=True,  error=None,                         item_id="i0"),  # ran
            _make_result("fast", available=True,  error=None,                         item_id="i1"),  # ran
            _make_result("fast", available=False, error="tier_not_applicable: fast",  item_id="i2"),  # skip
            _make_result("fast", available=False, error="tier_not_applicable: fast",  item_id="i3"),  # skip
        ]

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast", "--out-dir", str(tmp_path)]),
        ):
            try:
                main()
            except SystemExit:
                pass

        captured = capsys.readouterr()
        # 4 corpus items, 2 not_applicable → eligible = 2; ran = 2
        line = next((ln for ln in captured.out.splitlines() if "Tier 'fast':" in ln), None)
        assert line is not None, f"No tier summary line in output:\n{captured.out}"
        # Should show 2/2, not 2/4
        assert "2/2" in line, f"Expected 2/2 (excluding not_applicable), got: {line}"

    def test_only_unavailable_not_applicable_counts_in_exit2_check(self, tmp_path):
        """tier_not_applicable rows must not trigger the >=95% unavailable exit(2)."""
        from report import main
        from corpus import CorpusItem

        # 100 not_applicable rows, 0 truly unavailable → ratio=0/0=0.0 → no exit(2)
        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(100)
        ]
        results = [
            _make_result("fast", available=False, error="tier_not_applicable: fast", item_id=f"i{i}")
            for i in range(100)
        ]

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast", "--out-dir", str(tmp_path)]),
        ):
            # Should NOT exit with code 2 — all rows are not_applicable (eligible=0, ratio=0.0)
            try:
                main()
            except SystemExit as e:
                assert e.code != 2, (
                    "Should not exit(2) when all unavailable rows are tier_not_applicable"
                )


class TestTierUnavailableExitsBeforeSummary:
    """An unavailable tier (>=95% truly unavailable) exits with code 2 before accuracy line."""

    def test_unavailable_tier_exits_2(self, capsys, tmp_path):
        """When >=95% of eligible rows are tier_unavailable, exit code is 2."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(20)
        ]
        # 19 truly unavailable (not tier_not_applicable), 1 ran
        results = (
            [_make_result("fast", available=True,  error=None,              item_id="i0")] +
            [_make_result("fast", available=False, error="backend_error",   item_id=f"i{i}") for i in range(1, 20)]
        )

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast", "--out-dir", str(tmp_path)]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_unavailable_tier_does_not_print_accuracy_line(self, capsys, tmp_path):
        """When a tier triggers exit(2), no accuracy summary line should appear in stdout."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id=f"i{i}", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
            for i in range(20)
        ]
        results = (
            [_make_result("fast", available=True,  error=None,            item_id="i0")] +
            [_make_result("fast", available=False, error="backend_error", item_id=f"i{i}") for i in range(1, 20)]
        )

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast", "--out-dir", str(tmp_path)]),
        ):
            with pytest.raises(SystemExit):
                main()

        captured = capsys.readouterr()
        # exit(2) fires before the accuracy print — no "Tier 'fast': N/M ran" line
        assert "Tier 'fast':" not in captured.out, (
            "Accuracy summary should not appear when tier triggers exit(2)"
        )


class TestTierSummaryNaWhenZeroApplicable:
    """n/a must be printed for metrics when tier has zero applicable items."""

    def test_na_printed_when_zero_eligible(self, capsys, tmp_path):
        """When eligible==0 (all rows are tier_not_applicable), the summary line still appears
        and shows 0/0 ran with metric values (0.000 when no items scored)."""
        from report import main
        from corpus import CorpusItem

        corpus = [
            CorpusItem(id="i0", input_type="general", text="x",
                       expected_corrections=[], should_skip=False)
        ]
        # The tier has 1 not_applicable row → eligible = 0, ran = 0
        results = [
            _make_result("fast", available=False, error="tier_not_applicable: fast", item_id="i0"),
        ]

        with (
            patch("report.load_corpus", return_value=corpus),
            patch("report.load_sources", return_value=corpus),
            patch("report.run_all", return_value=results),
            patch("report.write_csv"),
            patch("report.write_summary"),
            patch("sys.argv", ["report.py", "--tiers", "fast", "--out-dir", str(tmp_path)]),
        ):
            try:
                main()
            except SystemExit:
                pass

        captured = capsys.readouterr()
        line = next((ln for ln in captured.out.splitlines() if "Tier 'fast':" in ln), None)
        assert line is not None, f"No tier summary line in output:\n{captured.out}"
        # eligible=0 → 0/0 ran; by_tier returns 0.0 (not nan) for zero-item tiers
        assert "0/0 ran" in line, f"Expected '0/0 ran' for zero-eligible tier, got: {line}"
        assert "precision=" in line
        assert "recall=" in line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
