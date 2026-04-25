"""Route requests to the appropriate backend tier."""

import time
from typing import Callable

from protocol import Request, Response, Correction
import nuspell_backend
import t5_backend
import llama_backend


# Map tier names to backend modules
TIER_MAP = {
    "fast": nuspell_backend,
    "better": t5_backend,
    "smart": llama_backend,
}


def route(request: Request) -> Response:
    """
    Route a request to the appropriate backend.

    Args:
        request: The incoming request.

    Returns:
        Response with corrections or error message.
    """
    tier = request.tier.lower()
    start_time = time.perf_counter()

    # Check if tier is valid
    if tier not in TIER_MAP:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return Response(
            request_id=request.request_id,
            tier_used=tier,
            corrections=[],
            latency_ms=elapsed_ms,
            error=f"invalid_tier: {tier}",
        )

    backend = TIER_MAP[tier]

    # Check if backend is available
    if not backend.is_available():
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return Response(
            request_id=request.request_id,
            tier_used=tier,
            corrections=[],
            latency_ms=elapsed_ms,
            error=f"tier_unavailable: {tier}",
        )

    # Run the backend
    try:
        corrections = backend.correct(request.text, request.context_hint)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return Response(
            request_id=request.request_id,
            tier_used=tier,
            corrections=corrections,
            latency_ms=elapsed_ms,
            error=None,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return Response(
            request_id=request.request_id,
            tier_used=tier,
            corrections=[],
            latency_ms=elapsed_ms,
            error=f"backend_error: {type(e).__name__}: {str(e)}",
        )
