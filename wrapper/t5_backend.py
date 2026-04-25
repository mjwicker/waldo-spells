"""Better tier: T5 GGUF grammar correction stub."""

from typing import List, Optional
from protocol import Correction


def is_available() -> bool:
    """Check if T5 GGUF backend is available."""
    # T5 GGUF support not yet verified
    return False


def correct(text: str, context_hint: Optional[str] = None) -> List[Correction]:
    """
    Grammar/style correction using T5 GGUF model.

    Args:
        text: The text to check.
        context_hint: Optional context hint for better corrections.

    Raises:
        NotImplementedError: T5 support not yet ready.
    """
    raise NotImplementedError(
        "T5 GGUF support not yet verified — see research/t5_gguf_status.md"
    )
