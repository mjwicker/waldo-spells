"""Mid/Better tier: Unbabel/gec-t5_small via CTranslate2 (CPU INT8).

Setup:
  1. Install dependencies:
       pip install ctranslate2 transformers sentencepiece
  2. Convert model (one-time, ~120 MB output):
       python -m wrapper.t5_converter --output ./models/gec-t5_small-ct2
     Or manually:
       ct2-transformers-converter --model Unbabel/gec-t5_small \
           --output_dir ./models/gec-t5_small-ct2 --quantization int8
  3. Set env var:
       export CT2_MODEL_PATH=/absolute/path/to/models/gec-t5_small-ct2

Environment variables:
  CT2_MODEL_PATH  — path to converted CTranslate2 model directory (required)

Expected latency on Pentium N6000 (CPU-only): 6–10 seconds per sentence.
Expected RAM: ~120–150 MB resident.
"""

import difflib
import logging
import os
from typing import List, Optional, Tuple

from protocol import Correction

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "T5 backend unavailable.\n"
    "Install:  pip install ctranslate2 transformers sentencepiece\n"
    "Convert:  ct2-transformers-converter --model Unbabel/gec-t5_small "
    "--output_dir ./models/gec-t5_small-ct2 --quantization int8\n"
    "Activate: export CT2_MODEL_PATH=/path/to/models/gec-t5_small-ct2"
)

# Lazy-loaded singletons; initialised on first correct() call.
_translator = None
_tokenizer = None


def _ct2_model_path() -> Optional[str]:
    path = os.environ.get("CT2_MODEL_PATH")
    if path and os.path.isdir(path) and os.path.isfile(os.path.join(path, "model.bin")):
        return path
    return None


def is_available() -> bool:
    """True only when ctranslate2, transformers, and CT2_MODEL_PATH are all present."""
    try:
        import ctranslate2  # noqa: F401
    except ImportError:
        print("[t5_backend] unavailable: ctranslate2 not installed", flush=True)
        return False
    try:
        import transformers  # noqa: F401
    except ImportError:
        print("[t5_backend] unavailable: transformers not installed", flush=True)
        return False
    if not _ct2_model_path():
        path_val = os.environ.get("CT2_MODEL_PATH", "(not set)")
        print(f"[t5_backend] unavailable: CT2_MODEL_PATH={path_val} not found or missing model.bin", flush=True)
        return False
    return True


def _load() -> Tuple[object, object]:
    """Lazy-load translator and tokenizer; cache as module-level singletons."""
    global _translator, _tokenizer
    if _translator is None:
        import ctranslate2
        from transformers import T5Tokenizer
        model_path = _ct2_model_path()
        logger.info("Loading CTranslate2 T5 model from %s", model_path)
        _translator = ctranslate2.Translator(model_path, device="cpu", compute_type="int8")
        _tokenizer = T5Tokenizer.from_pretrained("t5-small")
    return _translator, _tokenizer


def _diff_to_corrections(original: str, corrected: str) -> List[Correction]:
    """Produce Correction objects by diffing original vs corrected at the word level."""
    corrections: List[Correction] = []
    if original == corrected:
        return corrections

    orig_words = original.split()
    corr_words = corrected.split()

    matcher = difflib.SequenceMatcher(None, orig_words, corr_words, autojunk=False)
    char_pos = 0
    orig_idx = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # Advance char_pos to the start of orig_words[orig_idx]
        while orig_idx < i1:
            char_pos += len(orig_words[orig_idx]) + 1  # +1 for space
            orig_idx += 1

        if tag == "replace":
            start = char_pos
            original_chunk = " ".join(orig_words[i1:i2])
            suggestion = " ".join(corr_words[j1:j2])
            end = start + len(original_chunk)
            if 0 <= start < end <= len(original):
                corrections.append(Correction(
                    start=start,
                    end=end,
                    original=original_chunk,
                    suggestions=[suggestion],
                    type="grammar",
                ))

    return corrections


def correct(text: str, context_hint: Optional[str] = None) -> List[Correction]:
    """
    Grammar correction via Unbabel/gec-t5_small through CTranslate2.

    Raises RuntimeError if not available (is_available() is False).
    Returns Correction objects derived from diffing input vs model output.
    """
    if not is_available():
        raise RuntimeError(_INSTALL_HINT)

    translator, tokenizer = _load()

    input_text = f"gec: {text}"
    tokens = tokenizer.convert_ids_to_tokens(tokenizer.encode(input_text))

    results = translator.translate_batch([tokens])
    output_tokens = results[0].hypotheses[0]
    corrected = tokenizer.convert_tokens_to_string(output_tokens)

    return _diff_to_corrections(text, corrected)
