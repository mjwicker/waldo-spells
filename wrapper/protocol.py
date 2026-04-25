"""JSON line protocol for grammar/spell checking requests and responses."""

import json
from dataclasses import dataclass, asdict
from typing import Optional, List


@dataclass
class Correction:
    """A single spelling/grammar correction."""
    start: int
    end: int
    original: str
    suggestions: List[str]
    type: str  # "spelling", "grammar", "style"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Correction":
        return cls(**data)


@dataclass
class Request:
    """Incoming request for correction."""
    tier: str  # "fast", "better", "smart"
    text: str
    context_hint: Optional[str]
    request_id: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Request":
        return cls(**data)

    @classmethod
    def from_json(cls, line: str) -> "Request":
        """Parse a JSON line into a Request."""
        data = json.loads(line)
        return cls.from_dict(data)


@dataclass
class Response:
    """Outgoing response with corrections."""
    request_id: str
    tier_used: str
    corrections: List[Correction]
    latency_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "tier_used": self.tier_used,
            "corrections": [c.to_dict() for c in self.corrections],
            "latency_ms": self.latency_ms,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Response":
        corrections = [Correction.from_dict(c) for c in data.get("corrections", [])]
        return cls(
            request_id=data["request_id"],
            tier_used=data["tier_used"],
            corrections=corrections,
            latency_ms=data["latency_ms"],
            error=data.get("error"),
        )

    def to_json(self) -> str:
        """Serialize to JSON line."""
        return json.dumps(self.to_dict())
