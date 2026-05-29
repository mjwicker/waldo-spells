"""Test runner for corpus items against all tiers."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# Add wrapper to path
sys.path.insert(0, str(Path(__file__).parent.parent / "wrapper"))

from tier_router import route
from protocol import Request, Correction
import nuspell_backend
import t5_backend
import llama_backend

# harness-level ONNX classification backend (edge tier)
sys.path.insert(0, str(Path(__file__).parent))
import onnx_backend


TIER_BACKENDS = {
    "fast": nuspell_backend,
    "better": t5_backend,
    "smart": llama_backend,
    "edge": onnx_backend,
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
    task: str = "span_correction"
    expected_label: Optional[str] = None
    error_type: Optional[str] = None
    source: Optional[str] = None
    detected_input_type: Optional[str] = None   # router's detected context (no hint)
    predicted_label: Optional[str] = None        # for tone task
    error: str = None
    available: bool = True


def _extract_tone(response) -> Optional[str]:
    """
    Best-effort extraction of positive/negative sentiment from a response.
    Looks for the words in the error field or correction text if present.
    Smart tier may encode tone in corrections or metadata — check both.
    """
    text = (response.error or "").lower()
    for corr in getattr(response, "corrections", []):
        text += " " + str(corr).lower()
    if "positive" in text:
        return "positive"
    if "negative" in text:
        return "negative"
    return None


def run_one(item, tier: str) -> RunResult:
    """Run a single corpus item against a tier."""
    if tier not in TIER_BACKENDS:
        return RunResult(
            item_id=item.id, tier=tier, input_type=item.input_type,
            latency_ms=0.0, corrections=[], expected=item.expected_corrections,
            task=getattr(item, "task", "span_correction"),
            expected_label=getattr(item, "expected_label", None),
            error_type=getattr(item, "error_type", None),
            source=getattr(item, "source", None),
            error=f"invalid_tier: {tier}", available=False,
        )

    if tier in getattr(item, "skip_tiers", []):
        return RunResult(
            item_id=item.id, tier=tier, input_type=item.input_type,
            latency_ms=0.0, corrections=[], expected=item.expected_corrections,
            task=getattr(item, "task", "span_correction"),
            expected_label=getattr(item, "expected_label", None),
            error_type=getattr(item, "error_type", None),
            source=getattr(item, "source", None),
            error=f"tier_not_applicable: {tier}", available=False,
        )

    backend = TIER_BACKENDS[tier]
    if not backend.is_available():
        return RunResult(
            item_id=item.id, tier=tier, input_type=item.input_type,
            latency_ms=0.0, corrections=[], expected=item.expected_corrections,
            task=getattr(item, "task", "span_correction"),
            expected_label=getattr(item, "expected_label", None),
            error_type=getattr(item, "error_type", None),
            source=getattr(item, "source", None),
            error=f"tier_unavailable: {tier}", available=False,
        )

    # Edge tier: ONNX classification backend — bypasses tier_router.
    # Only handles tone tasks; all other tasks are not applicable.
    if tier == "edge":
        return _run_edge(item)

    # Run with context hint (normal path)
    request = Request(
        tier=tier,
        text=item.text,
        context_hint=item.input_type,
        request_id=item.id,
    )
    response = route(request)
    corrections_list = [c.to_dict() for c in response.corrections]

    # Run without hint to measure context-detection accuracy
    detect_request = Request(
        tier=tier,
        text=item.text,
        context_hint=None,
        request_id=f"{item.id}_detect",
    )
    try:
        detect_response = route(detect_request)
        detected = getattr(detect_response, "detected_input_type", None)
    except Exception:
        detected = None

    predicted_label = None
    if getattr(item, "task", "span_correction") == "tone":
        predicted_label = _extract_tone(response)

    return RunResult(
        item_id=item.id,
        tier=tier,
        input_type=item.input_type,
        latency_ms=response.latency_ms,
        corrections=corrections_list,
        expected=item.expected_corrections,
        task=getattr(item, "task", "span_correction"),
        expected_label=getattr(item, "expected_label", None),
        error_type=getattr(item, "error_type", None),
        source=getattr(item, "source", None),
        detected_input_type=detected,
        predicted_label=predicted_label,
        error=response.error,
        available=True,
    )


def _run_edge(item) -> RunResult:
    """Run a single corpus item against the ONNX edge tier.

    The edge tier only handles tone tasks; span_correction items are marked
    tier_not_applicable so they are excluded from metric aggregation.
    """
    import time

    task = getattr(item, "task", "span_correction")

    if task != "tone":
        return RunResult(
            item_id=item.id, tier="edge", input_type=item.input_type,
            latency_ms=0.0, corrections=[], expected=item.expected_corrections,
            task=task,
            expected_label=getattr(item, "expected_label", None),
            error_type=getattr(item, "error_type", None),
            source=getattr(item, "source", None),
            error="tier_not_applicable: edge (tone tasks only)",
            available=False,
        )

    t0 = time.perf_counter()
    try:
        result = onnx_backend.classify_tone(item.text)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return RunResult(
            item_id=item.id, tier="edge", input_type=item.input_type,
            latency_ms=elapsed_ms, corrections=[], expected=item.expected_corrections,
            task=task,
            expected_label=getattr(item, "expected_label", None),
            error_type=getattr(item, "error_type", None),
            source=getattr(item, "source", None),
            predicted_label=result["label"],
            available=True,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return RunResult(
            item_id=item.id, tier="edge", input_type=item.input_type,
            latency_ms=elapsed_ms, corrections=[], expected=item.expected_corrections,
            task=task,
            expected_label=getattr(item, "expected_label", None),
            error_type=getattr(item, "error_type", None),
            source=getattr(item, "source", None),
            error=f"backend_error: {type(exc).__name__}: {exc}",
            available=False,
        )


def run_all(
    corpus: List, tiers: Tuple[str, ...] = ("fast", "better", "smart", "edge")
) -> List[RunResult]:
    """Run all corpus items against specified tiers."""
    results = []
    for item in corpus:
        if item.should_skip:
            continue
        for tier in tiers:
            result = run_one(item, tier)
            results.append(result)
    return results
