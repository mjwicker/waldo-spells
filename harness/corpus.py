"""Corpus loading and management for test harness."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class CorpusItem:
    """A single test corpus item."""
    id: str
    input_type: str
    text: str
    expected_corrections: List[dict]
    should_skip: bool

    @classmethod
    def from_dict(cls, data: dict) -> "CorpusItem":
        return cls(
            id=data["id"],
            input_type=data["input_type"],
            text=data["text"],
            expected_corrections=data.get("expected_corrections", []),
            should_skip=data.get("should_skip", False),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "input_type": self.input_type,
            "text": self.text,
            "expected_corrections": self.expected_corrections,
            "should_skip": self.should_skip,
        }


def load_corpus(path: Path) -> List[CorpusItem]:
    """
    Load corpus from JSONL file.

    Args:
        path: Path to JSONL corpus file.

    Returns:
        List of CorpusItem objects.
    """
    items = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            items.append(CorpusItem.from_dict(data))
    return items
