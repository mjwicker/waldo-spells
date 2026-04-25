"""Test runner for corpus items against all tiers."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# Add wrapper to path
sys.path.insert(0, str(Path(__file__).parent.parent / "wrapper"))

from tier_router import route
from protocol import Request, Correction
import nuspell_backend
import t5_backend
import llama_backend


TIER_BACKENDS = {
    "fast": nuspell_backend,
    "better": t5_backend,
    "smart": llama_backend,
}


@dataclass
class RunResult:
    """Result of running a single item against a tier."""
    item_id: str
    tier: str
    input_type: str
    latency_ms: float
    corrections: List[dict]
    expected: List[dict]
    error: str = None
    available: bool = True


def run_one(item, tier: str) -> RunResult:
    """
    Run a single corpus item against a tier.

    Args:
        item: CorpusItem from corpus.
        tier: Tier name ("fast", "better", or "smart").

    Returns:
        RunResult with metrics and corrections.
    """
    # Check if backend is available
    if tier not in TIER_BACKENDS:
        return RunResult(
            item_id=item.id,
            tier=tier,
            input_type=item.input_type,
            latency_ms=0.0,
            corrections=[],
            expected=item.expected_corrections,
            error=f"invalid_tier: {tier}",
            available=False,
        )

    backend = TIER_BACKENDS[tier]
    if not backend.is_available():
        return RunResult(
            item_id=item.id,
            tier=tier,
            input_type=item.input_type,
            latency_ms=0.0,
            corrections=[],
            expected=item.expected_corrections,
            error=f"tier_unavailable: {tier}",
            available=False,
        )

    # Build request and measure latency
    request = Request(
        tier=tier,
        text=item.text,
        context_hint=item.input_type,
        request_id=item.id,
    )

    response = route(request)
    latency_ms = response.latency_ms

    # Convert Correction objects to dicts
    corrections_list = [c.to_dict() for c in response.corrections]

    return RunResult(
        item_id=item.id,
        tier=tier,
        input_type=item.input_type,
        latency_ms=latency_ms,
        corrections=corrections_list,
        expected=item.expected_corrections,
        error=response.error,
        available=True,
    )


def run_all(
    corpus: List, tiers: Tuple[str, ...] = ("fast", "better", "smart")
) -> List[RunResult]:
    """
    Run all corpus items against specified tiers.

    Args:
        corpus: List of CorpusItem objects.
        tiers: Tuple of tier names to test.

    Returns:
        Flat list of RunResult objects.
    """
    results = []
    for item in corpus:
        if item.should_skip:
            continue
        for tier in tiers:
            result = run_one(item, tier)
            results.append(result)
    return results
