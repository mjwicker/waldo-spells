"""Smart tier: Qwen2.5-3B context-aware grammar correction stub."""

from typing import List, Optional
from protocol import Correction


def is_available() -> bool:
    """Check if Qwen model is available and configured."""
    # Model not yet downloaded/configured
    return False


def correct(text: str, context_hint: Optional[str] = None) -> List[Correction]:
    """
    Context-aware grammar/style correction using Qwen2.5-3B.

    Args:
        text: The text to check.
        context_hint: Optional context hint (e.g., document type, tone).

    Raises:
        NotImplementedError: Qwen not yet configured.
    """
    raise NotImplementedError(
        "Qwen2.5-3B not yet configured — set LLAMA_MODEL_PATH env var"
    )
