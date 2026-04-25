"""Tests for Nuspell/Hunspell backend."""

import sys
import os

# Add parent directory to path so we can import wrapper modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import nuspell_backend


def test_is_available():
    """Test that is_available() returns a boolean."""
    available = nuspell_backend.is_available()
    assert isinstance(available, bool)


def test_correct_with_misspelling():
    """Test that misspellings are detected."""
    if not nuspell_backend.is_available():
        print("SKIP: hunspell not installed")
        return

    corrections = nuspell_backend.correct("Helo wrold", context_hint=None)

    # Should find at least one misspelling
    assert len(corrections) > 0, "Expected corrections for 'Helo wrold'"

    # Check that Helo is flagged
    helo_corrections = [c for c in corrections if c.original == "Helo"]
    assert len(helo_corrections) > 0, "Expected 'Helo' to be flagged"

    # Check that it has suggestions
    helo = helo_corrections[0]
    assert len(helo.suggestions) > 0, "Expected suggestions for 'Helo'"
    assert "Hello" in helo.suggestions, "Expected 'Hello' in suggestions"

    # Check that wrold is flagged
    wrold_corrections = [c for c in corrections if c.original == "wrold"]
    assert len(wrold_corrections) > 0, "Expected 'wrold' to be flagged"


def test_correct_with_correct_text():
    """Test that correct text passes without corrections."""
    if not nuspell_backend.is_available():
        print("SKIP: hunspell not installed")
        return

    corrections = nuspell_backend.correct("Hello world", context_hint=None)

    # Should find no corrections
    assert len(corrections) == 0, f"Expected no corrections, got {corrections}"


def test_correction_positions():
    """Test that correction positions are accurate."""
    if not nuspell_backend.is_available():
        print("SKIP: hunspell not installed")
        return

    text = "This is a tst"
    corrections = nuspell_backend.correct(text, context_hint=None)

    # Should flag "tst"
    tst_corrections = [c for c in corrections if c.original == "tst"]
    assert len(tst_corrections) > 0, "Expected 'tst' to be flagged"

    # Check position
    tst = tst_corrections[0]
    assert text[tst.start:tst.end] == "tst", "Correction positions are incorrect"


def test_correction_type():
    """Test that corrections are marked as spelling type."""
    if not nuspell_backend.is_available():
        print("SKIP: hunspell not installed")
        return

    corrections = nuspell_backend.correct("Helo", context_hint=None)

    # Should have at least one correction marked as spelling
    spelling_corrections = [c for c in corrections if c.type == "spelling"]
    assert len(spelling_corrections) > 0, "Expected spelling type corrections"


if __name__ == "__main__":
    test_is_available()
    print("✓ is_available()")

    test_correct_with_misspelling()
    print("✓ correct() with misspellings")

    test_correct_with_correct_text()
    print("✓ correct() with correct text")

    test_correction_positions()
    print("✓ correction positions")

    test_correction_type()
    print("✓ correction type")

    print("\nAll tests passed!")
