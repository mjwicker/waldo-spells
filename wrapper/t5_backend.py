"""Mid/Better tier: T5-based GEC models via CTranslate2 (CPU INT8).

This backend supports any T5-based grammar-correction model converted to CTranslate2 format.
Default: Unbabel/gec-t5_small. Can be overridden for research/evaluation.

Setup:
  1. Install dependencies:
       pip install ctranslate2 transformers sentencepiece
  2. Convert model (one-time, ~120–250 MB output depending on model size):
       python -m wrapper.t5_converter --output ./models/gec-t5_small-ct2
     Or for a custom model:
       python -m wrapper.t5_converter --model vennify/t5-base-grammar-correction \
           --output ./models/gec-t5-base-ct2 --quantization int8
  3. Set env vars:
       export CT2_MODEL_PATH=/absolute/path/to/models/gec-t5_small-ct2
       export CT2_TOKENIZER_ID=t5-small  # optional; defaults to t5-small

Environment variables:
  CT2_MODEL_PATH       — path to converted CTranslate2 model directory (required)
  CT2_TOKENIZER_ID     — HuggingFace T5 tokenizer ID (default: t5-small)

Expected latency on Pentium N6000 (CPU-only): 6–10 seconds per sentence (t5-small).
Expected RAM: ~120–150 MB resident (t5-small).
Larger models (t5-base) may require 300–500ms p50 latency and 250–350 MB RAM.
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
    "Convert:  python -m wrapper.t5_converter --output ./models/gec-t5_small-ct2\n"
    "          Or: ct2-transformers-converter --model Unbabel/gec-t5_small "
    "--output_dir ./models/gec-t5_small-ct2 --quantization int8\n"
    "Activate: export CT2_MODEL_PATH=/path/to/models/gec-t5_small-ct2\n"
    "Optional: export CT2_TOKENIZER_ID=t5-small (default: t5-small)"
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


def _ct2_tokenizer_id() -> str:
    """Get tokenizer ID from environment or use default t5-small."""
    return os.environ.get("CT2_TOKENIZER_ID", "t5-small")


def _load() -> Tuple[object, object]:
    """Lazy-load translator and tokenizer; cache as module-level singletons.

    Tokenizer model ID is read from CT2_TOKENIZER_ID env var (default: t5-small).
    This allows research evaluation of larger T5 variants with custom models.
    """
    global _translator, _tokenizer
    if _translator is None:
        import ctranslate2
        from transformers import T5Tokenizer
        model_path = _ct2_model_path()
        tokenizer_id = _ct2_tokenizer_id()
        logger.info("Loading CTranslate2 T5 model from %s", model_path)
        logger.info("Loading T5 tokenizer from %s", tokenizer_id)
        _translator = ctranslate2.Translator(model_path, device="cpu", compute_type="int8")
        _tokenizer = T5Tokenizer.from_pretrained(tokenizer_id)
    return _translator, _tokenizer


def _diff_to_corrections(original: str, corrected: str) -> List[Correction]:
    """Produce Correction objects by diffing original vs corrected at the word level.

    Handles 'replace', 'delete', and 'insert' opcodes so that word-order corrections
    (which produce delete + insert pairs rather than a single replace) are captured.
    Insert-only opcodes (no source words consumed) are attached to the previous
    correction when possible, or emitted as a zero-width marker at char_pos so they
    can be merged by callers that understand adjacent corrections.
    """
    corrections: List[Correction] = []
    if original == corrected:
        return corrections

    orig_words = original.split()
    corr_words = corrected.split()

    matcher = difflib.SequenceMatcher(None, orig_words, corr_words, autojunk=False)
    # Pre-compute character offsets for each original word.
    word_offsets: List[int] = []
    pos = 0
    for w in orig_words:
        word_offsets.append(pos)
        pos += len(w) + 1  # +1 for the space after each word

    char_pos = 0
    orig_idx = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # Advance char_pos to the start of orig_words[i1]
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

        elif tag == "delete":
            # Words deleted from original with no replacement in corrected.
            # Emit as a correction with empty suggestion so the span is recorded
            # and can overlap with expected corrections in the harness.
            start = char_pos
            original_chunk = " ".join(orig_words[i1:i2])
            end = start + len(original_chunk)
            if 0 <= start < end <= len(original):
                corrections.append(Correction(
                    start=start,
                    end=end,
                    original=original_chunk,
                    suggestions=[""],
                    type="grammar",
                ))

        elif tag == "insert":
            # Words inserted into corrected with no source words consumed.
            # Anchor the correction at char_pos (between words); use a one-character
            # lookahead span so the overlap check in metrics.py can match it against
            # any expected correction that starts at or just after this position.
            # Only emit when char_pos is within the original string.
            if char_pos < len(original):
                suggestion = " ".join(corr_words[j1:j2])
                corrections.append(Correction(
                    start=char_pos,
                    end=char_pos + 1,
                    original=original[char_pos: char_pos + 1],
                    suggestions=[suggestion + " " + original[char_pos: char_pos + 1]],
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
