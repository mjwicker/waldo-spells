"""Fast tier: spell-check backend via pyenchant (wraps system hunspell/nuspell dicts)."""

import re
from typing import List, Optional

from protocol import Correction


def is_available() -> bool:
    """Check if enchant + en_US dictionary is available."""
    try:
        import enchant
        return enchant.dict_exists("en_US")
    except ImportError:
        return False


def correct(text: str, context_hint: Optional[str] = None) -> List[Correction]:
    """
    Spell-check text using system hunspell dictionaries via pyenchant.

    context_hint is accepted but unused — Fast tier is dictionary-only.
    Production may swap to native nuspell binding for sub-5ms latency.
    """
    import enchant
    d = enchant.Dict("en_US")
    corrections = []

    for match in re.finditer(r"\b[\w']+\b", text):
        token = match.group()
        if not d.check(token):
            corrections.append(Correction(
                start=match.start(),
                end=match.end(),
                original=token,
                suggestions=d.suggest(token)[:5],
                type="spelling",
            ))

    return corrections
