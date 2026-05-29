"""Edge tier: ONNX classification runner for tone/sentiment.

Two bundled models (both sourced from Xenova/ on HuggingFace, INT8 quantised):

  distilbert-sst2  — DistilBERT fine-tuned on SST-2; outputs logits for
                     NEGATIVE (0) / POSITIVE (1). ~66 MB on disk.
                     This is the primary classification model.

  all-MiniLM-L6-v2 — Sentence embeddings (384-dim). Used for similarity
                     scoring; no built-in classification head.

Both live under models/ relative to the repo root:
  models/distilbert-sst2-onnx/model_int8.onnx
  models/all-MiniLM-L6-v2-onnx/model_int8.onnx

Environment variables (optional overrides):
  ONNX_DISTILBERT_PATH   — absolute path to distilbert model_int8.onnx
  ONNX_MINILM_PATH       — absolute path to all-MiniLM model_int8.onnx

Setup (one-time):
  uv add onnxruntime

Latency target (Pentium N6000, CPU INT8): ≤ 200 ms per sentence.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent
_MODELS_DIR = _REPO_ROOT / "models"

_DISTILBERT_DEFAULT = _MODELS_DIR / "distilbert-sst2-onnx" / "model_int8.onnx"
_MINILM_DEFAULT = _MODELS_DIR / "all-MiniLM-L6-v2-onnx" / "model_int8.onnx"

# Tokenizer JSON lives beside the model
_DISTILBERT_TOKENIZER_DIR = _DISTILBERT_DEFAULT.parent
_MINILM_TOKENIZER_DIR = _MINILM_DEFAULT.parent

# ── Lazy singletons ───────────────────────────────────────────────────────────

_distilbert_session = None
_distilbert_tokenizer = None
_minilm_session = None
_minilm_tokenizer = None


# ── Label mapping ─────────────────────────────────────────────────────────────

# DistilBERT SST-2: index 0 → NEGATIVE, index 1 → POSITIVE
_DISTILBERT_LABELS: Dict[int, str] = {0: "negative", 1: "positive"}


# ── Availability ─────────────────────────────────────────────────────────────


def _distilbert_model_path() -> Optional[Path]:
    env = os.environ.get("ONNX_DISTILBERT_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    if _DISTILBERT_DEFAULT.is_file():
        return _DISTILBERT_DEFAULT
    return None


def _minilm_model_path() -> Optional[Path]:
    env = os.environ.get("ONNX_MINILM_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    if _MINILM_DEFAULT.is_file():
        return _MINILM_DEFAULT
    return None


def is_available() -> bool:
    """True when onnxruntime is importable and at least the DistilBERT model file exists."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        logger.debug("[onnx_backend] onnxruntime not installed")
        return False
    if not _distilbert_model_path():
        logger.debug(
            "[onnx_backend] distilbert model not found at %s", _DISTILBERT_DEFAULT
        )
        return False
    return True


def minilm_available() -> bool:
    """True when the MiniLM model file also exists (optional)."""
    return is_available() and _minilm_model_path() is not None


# ── Simple word-piece tokenizer (no transformers dependency) ──────────────────


class _WordPieceTokenizer:
    """Minimal BertTokenizer built from tokenizer.json (HuggingFace fast-tokenizer format).

    Supports:
      - WordPiece vocabulary lookup
      - [CLS] / [SEP] padding
      - max_length truncation
      - attention_mask generation

    Only implements what ONNX inference needs — not a full tokenizer.
    """

    def __init__(self, tokenizer_dir: Path) -> None:
        tok_path = tokenizer_dir / "tokenizer.json"
        if not tok_path.exists():
            raise FileNotFoundError(f"tokenizer.json not found at {tok_path}")
        with open(tok_path, encoding="utf-8") as f:
            tok_data = json.load(f)

        vocab: Dict[str, int] = tok_data["model"]["vocab"]
        self._vocab = vocab
        self._inv_vocab: Dict[int, str] = {v: k for k, v in vocab.items()}

        # Special token IDs
        self._unk_id = vocab.get("[UNK]", 100)
        self._cls_id = vocab.get("[CLS]", 101)
        self._sep_id = vocab.get("[SEP]", 102)
        self._pad_id = vocab.get("[PAD]", 0)

    def _tokenize_word(self, word: str) -> List[int]:
        """Greedy longest-match WordPiece tokenization for a single word."""
        chars = word.lower()
        if chars in self._vocab:
            return [self._vocab[chars]]

        ids = []
        start = 0
        while start < len(chars):
            end = len(chars)
            found = False
            prefix = "" if start == 0 else "##"
            while end > start:
                sub = prefix + chars[start:end]
                if sub in self._vocab:
                    ids.append(self._vocab[sub])
                    start = end
                    found = True
                    break
                end -= 1
            if not found:
                ids.append(self._unk_id)
                start += 1
        return ids

    def encode(
        self, text: str, max_length: int = 128
    ) -> Tuple[List[int], List[int]]:
        """Return (input_ids, attention_mask) as plain Python lists.

        Adds [CLS] at start and [SEP] at end; truncates to max_length.
        """
        import re

        words = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
        token_ids: List[int] = []
        for word in words:
            token_ids.extend(self._tokenize_word(word))

        # Reserve 2 slots for [CLS] and [SEP]
        max_content = max_length - 2
        token_ids = token_ids[:max_content]

        input_ids = [self._cls_id] + token_ids + [self._sep_id]
        attention_mask = [1] * len(input_ids)
        return input_ids, attention_mask


# ── Lazy loaders ──────────────────────────────────────────────────────────────


def _load_distilbert() -> Tuple[object, _WordPieceTokenizer]:
    global _distilbert_session, _distilbert_tokenizer
    if _distilbert_session is None:
        import onnxruntime as ort

        model_path = _distilbert_model_path()
        logger.info("[onnx_backend] loading distilbert from %s", model_path)
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        _distilbert_session = ort.InferenceSession(
            str(model_path), sess_options=opts
        )
        _distilbert_tokenizer = _WordPieceTokenizer(_DISTILBERT_TOKENIZER_DIR)
    return _distilbert_session, _distilbert_tokenizer


def _load_minilm() -> Tuple[object, _WordPieceTokenizer]:
    global _minilm_session, _minilm_tokenizer
    if _minilm_session is None:
        import onnxruntime as ort

        model_path = _minilm_model_path()
        logger.info("[onnx_backend] loading minilm from %s", model_path)
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        _minilm_session = ort.InferenceSession(
            str(model_path), sess_options=opts
        )
        _minilm_tokenizer = _WordPieceTokenizer(_MINILM_TOKENIZER_DIR)
    return _minilm_session, _minilm_tokenizer


# ── Inference helpers ─────────────────────────────────────────────────────────


def _numpy_softmax(logits: list) -> list:
    """Numerically stable softmax over a 1-D list of floats."""
    import math

    max_v = max(logits)
    exps = [math.exp(v - max_v) for v in logits]
    total = sum(exps)
    return [e / total for e in exps]


def classify_tone(text: str, max_length: int = 128) -> Dict:
    """
    Run DistilBERT SST-2 on *text* and return a classification dict:

      {
        "label": "positive" | "negative",
        "score": float,          # confidence of winning class [0, 1]
        "scores": {"positive": float, "negative": float},
      }

    Raises RuntimeError if is_available() is False.
    """
    if not is_available():
        raise RuntimeError(
            "[onnx_backend] unavailable — check is_available() before calling"
        )

    import numpy as np

    session, tokenizer = _load_distilbert()
    input_ids, attention_mask = tokenizer.encode(text, max_length=max_length)

    feed = {
        "input_ids": np.array([input_ids], dtype=np.int64),
        "attention_mask": np.array([attention_mask], dtype=np.int64),
    }
    (logits_out,) = session.run(["logits"], feed)
    logits = logits_out[0].tolist()  # shape [2]

    probs = _numpy_softmax(logits)
    pred_idx = int(probs.index(max(probs)))
    label = _DISTILBERT_LABELS[pred_idx]

    return {
        "label": label,
        "score": probs[pred_idx],
        "scores": {
            "negative": probs[0],
            "positive": probs[1],
        },
    }


def embed(text: str, max_length: int = 128) -> List[float]:
    """
    Run all-MiniLM-L6-v2 on *text* and return a mean-pooled 384-dim embedding.

    Raises RuntimeError if minilm_available() is False.
    """
    if not minilm_available():
        raise RuntimeError(
            "[onnx_backend] MiniLM unavailable — check minilm_available()"
        )

    import numpy as np

    session, tokenizer = _load_minilm()
    input_ids, attention_mask = tokenizer.encode(text, max_length=max_length)

    # MiniLM needs token_type_ids (all zeros)
    token_type_ids = [0] * len(input_ids)

    feed = {
        "input_ids": np.array([input_ids], dtype=np.int64),
        "attention_mask": np.array([attention_mask], dtype=np.int64),
        "token_type_ids": np.array([token_type_ids], dtype=np.int64),
    }
    (hidden_state,) = session.run(["last_hidden_state"], feed)
    # hidden_state shape: [1, seq_len, 384]
    # Mean pool over non-padding positions
    mask = np.array(attention_mask, dtype=np.float32).reshape(1, -1, 1)
    masked = hidden_state * mask
    pooled = masked.sum(axis=1) / mask.sum(axis=1)
    return pooled[0].tolist()


# ── Batch benchmark helpers ───────────────────────────────────────────────────


def benchmark_tone(
    texts: List[str],
    labels: List[str],
    model: str = "distilbert",
) -> Dict:
    """
    Score a list of (text, label) pairs against tone classification.

    model: "distilbert" (default) — only supported value currently.

    Returns a dict:
      {
        "model": str,
        "n_total": int,
        "n_correct": int,
        "accuracy": float,
        "latency_ms_mean": float,
        "latency_ms_p95": float,
      }
    """
    import time

    if not is_available():
        raise RuntimeError("[onnx_backend] unavailable")

    if model != "distilbert":
        raise ValueError(f"Unsupported model for tone benchmark: {model!r}")

    latencies: List[float] = []
    n_correct = 0

    for text, expected_label in zip(texts, labels):
        t0 = time.perf_counter()
        result = classify_tone(text)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        if result["label"] == expected_label.lower():
            n_correct += 1

    n = len(latencies)
    sorted_lat = sorted(latencies)
    mean_lat = sum(latencies) / n if n else 0.0
    p95_lat = sorted_lat[int(n * 0.95)] if n else 0.0

    return {
        "model": "Xenova/distilbert-base-uncased-finetuned-sst-2-english (INT8)",
        "n_total": n,
        "n_correct": n_correct,
        "accuracy": n_correct / n if n else 0.0,
        "latency_ms_mean": mean_lat,
        "latency_ms_p95": p95_lat,
    }
