"""Tests for protocol serialization."""

import json
import sys
import os

# Add parent directory to path so we can import wrapper modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol import Correction, Request, Response


def test_correction_roundtrip():
    """Test Correction serialization and deserialization."""
    original = Correction(
        start=0,
        end=4,
        original="Helo",
        suggestions=["Hello", "Held"],
        type="spelling"
    )

    # to_dict -> from_dict
    data = original.to_dict()
    restored = Correction.from_dict(data)

    assert restored.start == original.start
    assert restored.end == original.end
    assert restored.original == original.original
    assert restored.suggestions == original.suggestions
    assert restored.type == original.type


def test_request_json_roundtrip():
    """Test Request JSON serialization and deserialization."""
    original = Request(
        tier="fast",
        text="Helo wrold",
        context_hint=None,
        request_id="req-1"
    )

    # to_dict -> JSON -> from_dict
    data = original.to_dict()
    json_str = json.dumps(data)
    restored = Request.from_dict(json.loads(json_str))

    assert restored.tier == original.tier
    assert restored.text == original.text
    assert restored.context_hint == original.context_hint
    assert restored.request_id == original.request_id


def test_request_from_json():
    """Test Request.from_json() directly."""
    json_line = '{"tier":"better","text":"The qwick brown fox","context_hint":"formal","request_id":"req-2"}'
    request = Request.from_json(json_line)

    assert request.tier == "better"
    assert request.text == "The qwick brown fox"
    assert request.context_hint == "formal"
    assert request.request_id == "req-2"


def test_response_roundtrip():
    """Test Response serialization and deserialization."""
    corrections = [
        Correction(0, 4, "Helo", ["Hello"], "spelling"),
        Correction(5, 10, "wrold", ["world"], "spelling"),
    ]

    original = Response(
        request_id="req-1",
        tier_used="fast",
        corrections=corrections,
        latency_ms=15.3,
        error=None
    )

    # to_dict -> from_dict
    data = original.to_dict()
    restored = Response.from_dict(data)

    assert restored.request_id == original.request_id
    assert restored.tier_used == original.tier_used
    assert len(restored.corrections) == 2
    assert restored.latency_ms == original.latency_ms
    assert restored.error is None


def test_response_with_error():
    """Test Response with error message."""
    response = Response(
        request_id="req-1",
        tier_used="smart",
        corrections=[],
        latency_ms=5.0,
        error="tier_unavailable: smart"
    )

    json_line = response.to_json()
    restored = Response.from_dict(json.loads(json_line))

    assert restored.error == "tier_unavailable: smart"
    assert len(restored.corrections) == 0


if __name__ == "__main__":
    test_correction_roundtrip()
    test_request_json_roundtrip()
    test_request_from_json()
    test_response_roundtrip()
    test_response_with_error()
    print("All protocol tests passed!")
