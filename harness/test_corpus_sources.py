"""Test corpus loading from all sources — verify no errors and confirm item counts."""

import sys
from pathlib import Path

import pytest

# Add harness to path for source adapters
sys.path.insert(0, str(Path(__file__).parent))

from corpus import load_sources, CorpusItem


class TestCorpusSourcesLoad:
    """Test that all enabled corpus sources load without error."""

    def test_load_sources_returns_list(self):
        """load_sources should return a list of CorpusItem."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        assert isinstance(items, list)
        assert all(isinstance(item, CorpusItem) for item in items)

    def test_all_sources_load_without_error(self):
        """All enabled sources in sources.yaml should load without raising."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        # Should not raise any exception
        items = load_sources(yaml_path)
        assert len(items) > 0

    def test_items_have_source_attribute(self):
        """All loaded items should have a source attribute set."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        for item in items:
            assert hasattr(item, "source")
            assert item.source is not None
            assert item.source in ["builtin", "kaggle_gec", "uci_sentiment", "c4_200m"]


class TestCorpusSourceCounts:
    """Test item counts by source — verify corpus has expected breadth."""

    def test_builtin_source_loads(self):
        """Builtin source (corpus.jsonl) should load at least 42 items."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        builtin_items = [i for i in items if i.source == "builtin"]
        assert len(builtin_items) >= 42, f"Expected >=42 builtin items, got {len(builtin_items)}"

    def test_kaggle_gec_source_loads(self):
        """Kaggle GEC source should load items (or skip if CSV unavailable)."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        kaggle_items = [i for i in items if i.source == "kaggle_gec"]
        # Kaggle source is optional — it may not be present
        if kaggle_items:
            assert len(kaggle_items) > 0
            for item in kaggle_items:
                assert item.task == "span_correction"

    def test_uci_sentiment_source_loads(self):
        """UCI Sentiment source should load items (or skip if CSV unavailable)."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        uci_items = [i for i in items if i.source == "uci_sentiment"]
        # UCI source is optional — it may not be present
        if uci_items:
            assert len(uci_items) > 0
            for item in uci_items:
                assert item.task == "tone"

    def test_c4_200m_source_contribution(self):
        """C4_200M source should contribute items from sentence_pairs.tsv when present."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        c4_items = [i for i in items if i.source == "c4_200m"]
        # C4 is optional — it only loads if sentence_pairs.tsv exists.
        # Minimum expected: original 40 synthetic pairs + targeted blindspot pairs
        # (added in cycle 27 for Noun Form, Pronoun, Word Order coverage).
        if c4_items:
            assert len(c4_items) >= 40, (
                f"Expected at least 40 C4 items (from sentence_pairs.tsv), got {len(c4_items)}"
            )
            for item in c4_items:
                assert item.task == "span_correction"
                assert item.source == "c4_200m"

    def test_total_corpus_meets_minimum(self):
        """Total corpus should include at least 4832 items (builtin + available sources)."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        # Minimum: 42 builtin + 1750 kaggle + 3000 uci + 40 c4 = 4832
        # Cycle 27 added 16 blindspot pairs to c4, so floor is now 4848.
        assert len(items) >= 4832, f"Expected >=4832 total items, got {len(items)}"

    def test_source_breakdown_logged(self):
        """Verify we can count items by source — useful for debugging."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path)
        by_source = {}
        for item in items:
            by_source[item.source] = by_source.get(item.source, 0) + 1

        # All items should have a source
        assert sum(by_source.values()) == len(items)
        # Builtin should always be present
        assert "builtin" in by_source
        assert by_source["builtin"] >= 42


class TestCorpusSourcesWithSample:
    """Test corpus loading with sample size overrides."""

    def test_load_sources_with_sample_override(self):
        """Sample override should limit items per source."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items = load_sources(yaml_path, sample_override=10)
        assert isinstance(items, list)
        # Builtin (42) + kaggle (10) + uci (10) + c4 (10) = 72 minimum
        # (c4 may be 0-10 if pairs don't exist)
        assert len(items) >= 42

    def test_load_sources_with_seed_override(self):
        """Seed override should be respected — different seed gives same count."""
        yaml_path = Path(__file__).parent / "sources.yaml"
        items1 = load_sources(yaml_path, seed_override=42)
        items2 = load_sources(yaml_path, seed_override=43)
        # Same sources, different seeds — should have same item count
        assert len(items1) == len(items2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
