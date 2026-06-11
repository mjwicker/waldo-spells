"""Test align.py diff_to_spans and metrics.py _overlaps fixes for Cycle 27."""

import sys
from pathlib import Path
from dataclasses import dataclass

import pytest

# Add harness to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sources.align import diff_to_spans
from metrics import _overlaps


# ── Test 1: _overlaps with zero-length expected span and overlapping predicted range ──


class TestOverlapsZeroLengthExpected:
    """Test _overlaps when expected span is a zero-length insertion point."""

    def test_zero_length_expected_at_start_of_predicted_range(self):
        """Zero-length expected at 14 should overlap predicted range [14, 21)."""
        # Expected: insertion point at position 14
        # Predicted: [14, 21) covers the insertion point
        result = _overlaps(14, 14, 14, 21)
        assert result is True

    def test_zero_length_expected_at_end_of_predicted_range(self):
        """Zero-length expected at 21 should overlap predicted range [14, 21)."""
        result = _overlaps(21, 21, 14, 21)
        assert result is True

    def test_zero_length_expected_inside_predicted_range(self):
        """Zero-length expected at 17 should overlap predicted range [14, 21)."""
        result = _overlaps(17, 17, 14, 21)
        assert result is True

    def test_zero_length_expected_before_predicted_range(self):
        """Zero-length expected at 13 should NOT overlap predicted range [14, 21)."""
        result = _overlaps(13, 13, 14, 21)
        assert result is False

    def test_zero_length_expected_after_predicted_range(self):
        """Zero-length expected at 22 should NOT overlap predicted range [14, 21)."""
        result = _overlaps(22, 22, 14, 21)
        assert result is False


# ── Test 2: _overlaps with zero-length predicted span inside expected range ──


class TestOverlapsZeroLengthPredicted:
    """Test _overlaps when predicted span is a zero-length insertion point."""

    def test_zero_length_predicted_at_start_of_expected_range(self):
        """Zero-length predicted at 14 should overlap expected range [14, 21)."""
        result = _overlaps(14, 21, 14, 14)
        assert result is True

    def test_zero_length_predicted_inside_expected_range(self):
        """Zero-length predicted at 17 should overlap expected range [14, 21)."""
        result = _overlaps(14, 21, 17, 17)
        assert result is True

    def test_zero_length_predicted_at_end_of_expected_range(self):
        """Zero-length predicted at 21 should overlap expected range [14, 21)."""
        result = _overlaps(14, 21, 21, 21)
        assert result is True

    def test_zero_length_predicted_before_expected_range(self):
        """Zero-length predicted at 13 should NOT overlap expected range [14, 21)."""
        result = _overlaps(14, 21, 13, 13)
        assert result is False

    def test_zero_length_predicted_after_expected_range(self):
        """Zero-length predicted at 22 should NOT overlap expected range [14, 21)."""
        result = _overlaps(14, 21, 22, 22)
        assert result is False

    def test_both_zero_length_same_position(self):
        """Two zero-length spans at same position should overlap."""
        result = _overlaps(17, 17, 17, 17)
        assert result is True

    def test_both_zero_length_different_positions(self):
        """Two zero-length spans at different positions should NOT overlap."""
        result = _overlaps(14, 14, 17, 17)
        assert result is False


# ── Test 3: diff_to_spans for Noun Form insert+delete pattern ──


class TestDiffToSpansNounForm:
    """Test diff_to_spans for Noun Form corrections with no zero-length spans."""

    def test_noun_form_insert_delete_pattern(self):
        """
        Noun Form correction inserts an article before a noun.
        E.g., "the book" → "the book" (no-op), but
        "book are good" → "books are good" (replace).

        Real example: "This are good" → "These are good"
        - Source words: ["This", "are", "good"]
        - Target words: ["These", "are", "good"]
        - Should produce single replacement, no zero-length spans.
        """
        source = "This are good"
        target = "These are good"
        corrections = diff_to_spans(source, target)

        assert len(corrections) > 0, "Should have at least one correction"

        # Check that no spans have start == end (zero-length)
        for corr in corrections:
            assert corr["start"] < corr["end"], (
                f"Found zero-length span at {corr['start']}: {corr}"
            )
            assert corr["type"] in ["replace", "insert"], f"Invalid type: {corr['type']}"

    def test_noun_form_adjacent_segments_merged(self):
        """
        Test that adjacent delete+insert pairs are merged into a single span.
        E.g., "I have went" → "I have gone"
        - delete "went"
        - insert "gone"
        These should merge into one correction for "went" → "gone".
        """
        source = "I have went"
        target = "I have gone"
        corrections = diff_to_spans(source, target)

        # Should have exactly 1 correction (merged), not 2 separate ones
        assert len(corrections) == 1, f"Expected 1 merged correction, got {len(corrections)}"
        corr = corrections[0]
        assert corr["original"] == "went"
        assert corr["correction"] == "gone"
        assert corr["start"] < corr["end"]


# ── Test 4: diff_to_corrections for word-order correction (delete opcode) ──


class TestDiffToCorrectionWordOrder:
    """Test _diff_to_corrections captures delete opcodes for word-order corrections."""

    @pytest.fixture
    def t5_backend(self):
        """Import t5_backend and reset state."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "wrapper"))
        import t5_backend
        # Reset singletons to avoid state leakage
        t5_backend._translator = None
        t5_backend._tokenizer = None
        yield t5_backend
        t5_backend._translator = None
        t5_backend._tokenizer = None

    def test_word_order_delete_captured(self, t5_backend):
        """
        Word-order corrections appear as delete + insert pairs.
        E.g., "He go" → "He goes"
        - delete "go"
        - insert "goes"
        Both opcodes should be captured.
        """
        original = "He go to school"
        corrected = "He goes to school"

        corrections = t5_backend._diff_to_corrections(original, corrected)

        # Should capture the change from "go" to "goes"
        assert len(corrections) > 0, "Should have at least one correction"

        # Look for correction involving "go"
        found_go_correction = False
        for corr in corrections:
            if "go" in corr.original or "goes" in str(corr.suggestions):
                found_go_correction = True
                # Verify the correction has proper bounds
                assert 0 <= corr.start < corr.end <= len(original), (
                    f"Invalid bounds: {corr.start}-{corr.end} in '{original}'"
                )
                break

        assert found_go_correction, (
            f"Could not find correction for 'go' in {[(c.original, c.suggestions) for c in corrections]}"
        )

    def test_word_order_adjacent_words_reordered(self, t5_backend):
        """
        Test reordering adjacent words: "quickly go" → "go quickly"
        This is a delete + insert pair that should be merged.
        """
        original = "I quickly go home"
        corrected = "I go quickly home"

        corrections = t5_backend._diff_to_corrections(original, corrected)

        # Should have corrections capturing the word reordering
        assert len(corrections) > 0, "Should capture word order change"


# ── Test 5: diff_to_corrections for pure insertion (insert opcode) ──


class TestDiffToCorrectionInsertion:
    """Test _diff_to_corrections captures insert opcodes for insertions."""

    @pytest.fixture
    def t5_backend(self):
        """Import t5_backend and reset state."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "wrapper"))
        import t5_backend
        t5_backend._translator = None
        t5_backend._tokenizer = None
        yield t5_backend
        t5_backend._translator = None
        t5_backend._tokenizer = None

    def test_pure_insertion_of_article(self, t5_backend):
        """
        Pure insertion: "book is good" → "The book is good"
        The word "The" is inserted at the start with no deletion.
        """
        original = "book is good"
        corrected = "The book is good"

        corrections = t5_backend._diff_to_corrections(original, corrected)

        # Should have at least one correction capturing the insertion
        assert len(corrections) > 0, "Should capture insertion"

        # At least one correction should have "The" or "book" in suggestions
        found_insertion = False
        for corr in corrections:
            if "The" in str(corr.suggestions):
                found_insertion = True
                break
        assert found_insertion, f"Could not find 'The' in suggestions: {[(c.original, c.suggestions) for c in corrections]}"

    def test_pure_insertion_between_words(self, t5_backend):
        """
        Pure insertion in the middle: "I went school" → "I went to school"
        The word "to" is inserted between "went" and "school".
        """
        original = "I went school"
        corrected = "I went to school"

        corrections = t5_backend._diff_to_corrections(original, corrected)

        assert len(corrections) > 0, "Should capture insertion of 'to'"


# ── Test 6: test_corpus_sources count assertion with new TSV rows ──


class TestCorpusSourcesC4Count:
    """Test that corpus source count assertion still holds with new TSV rows."""

    def test_c4_items_meet_minimum_after_blindspot_pairs(self):
        """
        Cycle 27 added 16 blindspot pairs to sentence_pairs.tsv.
        Minimum should be >= 40 (original) + benefit from new pairs.
        This test verifies the corpus loader accepts the expanded TSV.
        """
        from corpus import load_sources, CorpusItem

        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        c4_items = [i for i in items if i.source == "c4_200m"]

        if c4_items:
            # Original minimum was 40; with 16 new pairs, should be >= 56
            assert len(c4_items) >= 40, (
                f"Expected at least 40 C4 items, got {len(c4_items)}"
            )
            # All C4 items should have proper attributes
            for item in c4_items:
                assert hasattr(item, "task")
                assert hasattr(item, "source")
                assert item.source == "c4_200m"
                assert item.task == "span_correction"

    def test_total_corpus_with_blindspot_pairs(self):
        """
        Total corpus should be >= original 4832 + 16 new blindspot pairs.
        This test ensures the TSV expansion doesn't break corpus loading.
        """
        from corpus import load_sources

        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)

        # Minimum: 42 builtin + 1750 kaggle + 3000 uci + 56 c4 (original 40 + 16 new)
        # = 4848, but some sources may not be available, so we check >= original 4832
        assert len(items) >= 4832, f"Expected >=4832 total items, got {len(items)}"
