"""Corpus loading and management for test harness."""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Ensure harness dir is on path so source adapters can do `from corpus import CorpusItem`
_HARNESS_DIR = Path(__file__).parent
if str(_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_DIR))


@dataclass
class CorpusItem:
    """A single test corpus item."""
    id: str
    input_type: str
    text: str
    expected_corrections: List[dict]
    should_skip: bool
    task: str = "span_correction"          # "span_correction" | "tone" | "context_detection"
    expected_label: Optional[str] = None   # for tone/context_detection tasks
    error_type: Optional[str] = None       # Kaggle Error_Type column
    source: Optional[str] = None          # which adapter produced this item
    skip_tiers: List[str] = field(default_factory=list)  # tiers that cannot evaluate this item

    @classmethod
    def from_dict(cls, data: dict) -> "CorpusItem":
        return cls(
            id=data["id"],
            input_type=data["input_type"],
            text=data["text"],
            expected_corrections=data.get("expected_corrections", []),
            should_skip=data.get("should_skip", False),
            task=data.get("task", "span_correction"),
            expected_label=data.get("expected_label"),
            error_type=data.get("error_type"),
            source=data.get("source", "builtin"),
            skip_tiers=data.get("skip_tiers", []),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "input_type": self.input_type,
            "text": self.text,
            "expected_corrections": self.expected_corrections,
            "should_skip": self.should_skip,
            "task": self.task,
            "expected_label": self.expected_label,
            "error_type": self.error_type,
            "source": self.source,
            "skip_tiers": self.skip_tiers,
        }


def load_corpus(path: Path) -> List[CorpusItem]:
    """Load corpus from a JSONL file."""
    items = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            items.append(CorpusItem.from_dict(data))
    return items


def load_sources(yaml_path: Path, selected: Optional[List[str]] = None,
                 sample_override: Optional[int] = None,
                 seed_override: Optional[int] = None) -> List[CorpusItem]:
    """
    Load corpus items from all enabled sources in sources.yaml.

    Args:
        yaml_path: Path to sources.yaml
        selected: If set, only load these source names (plus "builtin" always loads)
        sample_override: Override per-source sample size
        seed_override: Override global seed
    """
    import yaml
    from sources import REGISTRY

    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    seed = seed_override if seed_override is not None else config.get("seed", 1337)
    items: List[CorpusItem] = []

    for name, cfg in config.get("sources", {}).items():
        if not cfg.get("enabled", True):
            continue
        if selected and name not in selected:
            continue

        if name == "builtin":
            # Load the hand-authored JSONL relative to yaml_path's parent
            jsonl_rel = cfg.get("path", "harness/corpus.jsonl")
            jsonl_path = yaml_path.parent.parent / jsonl_rel
            if jsonl_path.exists():
                builtin = load_corpus(jsonl_path)
                for item in builtin:
                    item.source = "builtin"
                items.extend(builtin)
            else:
                print(f"[builtin] JSONL not found at {jsonl_path} — skipping")
            continue

        if name not in REGISTRY:
            print(f"[load_sources] Unknown source '{name}' — skipping")
            continue

        sample = sample_override if sample_override is not None else cfg.get("sample", 500)
        adapter = REGISTRY[name]
        source_items = list(adapter(sample=sample, seed=seed))
        print(f"[{name}] Loaded {len(source_items)} items")
        items.extend(source_items)

    return items
