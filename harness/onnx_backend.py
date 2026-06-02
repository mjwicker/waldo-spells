"""Edge tier: ONNX classification runner for grammar acceptability and tone.

Three bundled models:

  bert-cola        — BERT fine-tuned on CoLA (Corpus of Linguistic Acceptability).
                     Outputs logits for UNACCEPTABLE (0) / ACCEPTABLE (1).
                     Primary grammar-detection model for the fast/edge tier.
                     Export with: python scripts/export_cola_onnx.py
                     Lives at: models/bert-cola-onnx/model_int8.onnx

  distilbert-sst2  — DistilBERT fine-tuned on SST-2; outputs logits for
                     NEGATIVE (0) / POSITIVE (1). ~66 MB on disk.
                     Retained for tone/sentiment tasks only.
                     Lives at: models/distilbert-sst2-onnx/model_int8.onnx

  all-MiniLM-L6-v2 — Sentence embeddings (384-dim). Used for similarity
                     scoring; no built-in classification head.
                     Lives at: models/all-MiniLM-L6-v2-onnx/model_int8.onnx

Environment variables (optional overrides):
  ONNX_COLA_PATH         — absolute path to bert-cola model_int8.onnx
  ONNX_DISTILBERT_PATH   — absolute path to distilbert model_int8.onnx
  ONNX_MINILM_PATH       — absolute path to all-MiniLM model_int8.onnx

Setup (one-time):
  uv add onnxruntime
  python scripts/export_cola_onnx.py   # requires optimum + torch

Latency target (Pentium N6000, CPU INT8): ≤ 200 ms per sentence.

Model fix (T-SPELLS-EDGE-3):
  The original edge tier used DistilBERT SST-2 for grammar detection, producing
  near-random output (F1 = 0.005, precision 1.2%, recall 0.3%) because SST-2 is
  a sentiment model with no grammar signal. Replaced with textattack/bert-base-uncased-CoLA
  (eval_mcc ≈ 0.534), a model explicitly trained to judge grammatical acceptability.
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

# CoLA (grammatical acceptability) — primary grammar detection model
_COLA_DEFAULT = _MODELS_DIR / "bert-cola-onnx" / "model_int8.onnx"
_COLA_TOKENIZER_DIR = _COLA_DEFAULT.parent

# SST-2 (sentiment) — retained for tone tasks only
_DISTILBERT_DEFAULT = _MODELS_DIR / "distilbert-sst2-onnx" / "model_int8.onnx"
_DISTILBERT_TOKENIZER_DIR = _DISTILBERT_DEFAULT.parent

# Sentence embeddings (similarity scoring)
_MINILM_DEFAULT = _MODELS_DIR / "all-MiniLM-L6-v2-onnx" / "model_int8.onnx"
_MINILM_TOKENIZER_DIR = _MINILM_DEFAULT.parent

# ── Lazy singletons ───────────────────────────────────────────────────────────

_cola_session = None
_cola_tokenizer = None
_distilbert_session = None
_distilbert_tokenizer = None
_minilm_session = None
_minilm_tokenizer = None


# ── Label mappings ────────────────────────────────────────────────────────────

# CoLA (textattack/bert-base-uncased-CoLA): index 0 → UNACCEPTABLE, index 1 → ACCEPTABLE
# A sentence is "unacceptable" when it contains a grammar error.
_COLA_LABELS: Dict[int, str] = {0: "unacceptable", 1: "acceptable"}

# DistilBERT SST-2: index 0 → NEGATIVE, index 1 → POSITIVE
_DISTILBERT_LABELS: Dict[int, str] = {0: "negative", 1: "positive"}


# ── Availability ─────────────────────────────────────────────────────────────


def _cola_model_path() -> Optional[Path]:
    env = os.environ.get("ONNX_COLA_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    if _COLA_DEFAULT.is_file():
        return _COLA_DEFAULT
    return None


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


def cola_available() -> bool:
    """True when onnxruntime is importable and the CoLA grammar model file exists.

    The CoLA model (textattack/bert-base-uncased-CoLA, exported to ONNX INT8) is
    the primary grammar-detection model for the edge tier.  Run
    `python scripts/export_cola_onnx.py` to generate it.
    """
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return _cola_model_path() is not None


def is_available() -> bool:
    """True when onnxruntime is importable and at least one classification model exists.

    Prefers the CoLA grammar model; falls back to DistilBERT SST-2 for tone tasks.
    Use `cola_available()` to check specifically for the grammar model.
    """
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        logger.debug("[onnx_backend] onnxruntime not installed")
        return False
    if _cola_model_path():
        return True
    if _distilbert_model_path():
        logger.debug(
            "[onnx_backend] CoLA model not found at %s — falling back to SST-2 "
            "(tone tasks only; grammar detection will be inaccurate). "
            "Run: python scripts/export_cola_onnx.py",
            _COLA_DEFAULT,
        )
        return True
    logger.debug(
        "[onnx_backend] no classification model found (checked %s and %s)",
        _COLA_DEFAULT,
        _DISTILBERT_DEFAULT,
    )
    return False


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


def _load_cola() -> Tuple[object, _WordPieceTokenizer]:
    """Load the CoLA ONNX grammar model (bert-cola-onnx)."""
    global _cola_session, _cola_tokenizer
    if _cola_session is None:
        import onnxruntime as ort

        model_path = _cola_model_path()
        if model_path is None:
            raise RuntimeError(
                "[onnx_backend] CoLA model not found. "
                "Run: python scripts/export_cola_onnx.py"
            )
        logger.info("[onnx_backend] loading CoLA grammar model from %s", model_path)
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        _cola_session = ort.InferenceSession(str(model_path), sess_options=opts)
        _cola_tokenizer = _WordPieceTokenizer(_COLA_TOKENIZER_DIR)
    return _cola_session, _cola_tokenizer


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


def classify_grammar(text: str, max_length: int = 128) -> Dict:
    """
    Run the CoLA grammar model on *text* and return a classification dict:

      {
        "label": "acceptable" | "unacceptable",
        "score": float,          # confidence of winning class [0, 1]
        "scores": {"acceptable": float, "unacceptable": float},
        "model": str,            # model identifier for logging
      }

    "unacceptable" means the sentence is grammatically incorrect.
    "acceptable" means the sentence is grammatically well-formed.

    Model: textattack/bert-base-uncased-CoLA (CoLA fine-tune, eval_mcc ≈ 0.534).
    Run `python scripts/export_cola_onnx.py` to generate the ONNX weights.

    Raises RuntimeError if cola_available() is False.
    """
    if not cola_available():
        raise RuntimeError(
            "[onnx_backend] CoLA grammar model unavailable. "
            "Run: python scripts/export_cola_onnx.py"
        )

    import numpy as np

    session, tokenizer = _load_cola()
    input_ids, attention_mask = tokenizer.encode(text, max_length=max_length)

    # BERT-based models need token_type_ids (all zeros for single-sequence input)
    token_type_ids = [0] * len(input_ids)

    feed = {
        "input_ids": np.array([input_ids], dtype=np.int64),
        "attention_mask": np.array([attention_mask], dtype=np.int64),
        "token_type_ids": np.array([token_type_ids], dtype=np.int64),
    }
    (logits_out,) = session.run(["logits"], feed)
    logits = logits_out[0].tolist()  # shape [2]

    probs = _numpy_softmax(logits)
    pred_idx = int(probs.index(max(probs)))
    label = _COLA_LABELS[pred_idx]

    return {
        "label": label,
        "score": probs[pred_idx],
        "scores": {
            "unacceptable": probs[0],
            "acceptable": probs[1],
        },
        "model": "textattack/bert-base-uncased-CoLA (INT8 ONNX)",
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


def benchmark_grammar(
    texts: List[str],
    labels: List[str],
) -> Dict:
    """
    Score a list of (text, label) pairs against grammar acceptability classification.

    labels must be "acceptable" or "unacceptable" (CoLA convention).
    Use this to evaluate the CoLA edge tier model against grammar corpora
    (UCI sentiment pairs, kaggle_gec, etc.).

    Returns a dict:
      {
        "model": str,
        "n_total": int,
        "n_correct": int,
        "accuracy": float,
        "latency_ms_mean": float,
        "latency_ms_p95": float,
      }

    Raises RuntimeError if cola_available() is False.
    """
    import time

    if not cola_available():
        raise RuntimeError(
            "[onnx_backend] CoLA grammar model unavailable. "
            "Run: python scripts/export_cola_onnx.py"
        )

    latencies: List[float] = []
    n_correct = 0

    for text, expected_label in zip(texts, labels):
        t0 = time.perf_counter()
        result = classify_grammar(text)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        if result["label"] == expected_label.lower():
            n_correct += 1

    n = len(latencies)
    sorted_lat = sorted(latencies)
    mean_lat = sum(latencies) / n if n else 0.0
    p95_lat = sorted_lat[int(n * 0.95)] if n else 0.0

    return {
        "model": "textattack/bert-base-uncased-CoLA (INT8 ONNX)",
        "n_total": n,
        "n_correct": n_correct,
        "accuracy": n_correct / n if n else 0.0,
        "latency_ms_mean": mean_lat,
        "latency_ms_p95": p95_lat,
    }
