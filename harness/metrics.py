"""Metrics computation for test results."""

import math
from statistics import mean

# ── Semantic similarity thresholds ────────────────────────────────────────────
SEMANTIC_GOLD   = 0.95   # essentially the same word/phrase
SEMANTIC_SILVER = 0.80   # right semantic neighbourhood, different word
SEMANTIC_BRONZE = 0.60   # related but drifting


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Check if two character ranges overlap.

    Zero-length spans (start == end) represent insertion points rather than
    character ranges.  A zero-length span at position P overlaps a range [X, Y)
    when X <= P <= Y (the insertion point falls within the range or at either
    boundary).  Two zero-length spans overlap only when they share the same
    position.  This handles GEC corrections where the model inserts words
    before an existing token: the expected span may be an insertion point P
    while the predicted correction covers [P, P+k).
    """
    # Both zero-length: match only if same position.
    if a_start == a_end and b_start == b_end:
        return a_start == b_start
    # a is a zero-length insertion point: overlaps b if it falls within b.
    if a_start == a_end:
        return b_start <= a_start <= b_end
    # b is a zero-length insertion point: overlaps a if it falls within a.
    if b_start == b_end:
        return a_start <= b_start <= a_end
    # Both are proper ranges: standard half-open interval overlap check.
    return not (a_end <= b_start or b_end <= a_start)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def true_positives(result) -> int:
    """Count corrections that overlap with expected corrections."""
    count = 0
    for correction in result.corrections:
        c_start = correction["start"]
        c_end = correction["end"]
        for expected in result.expected:
            e_start = expected["start"]
            e_end = expected["end"]
            if _overlaps(c_start, c_end, e_start, e_end):
                count += 1
                break
    return count


def false_positives(result) -> int:
    """Count corrections that don't overlap with any expected correction."""
    count = 0
    for correction in result.corrections:
        c_start = correction["start"]
        c_end = correction["end"]
        has_overlap = any(
            _overlaps(c_start, c_end, e["start"], e["end"])
            for e in result.expected
        )
        if not has_overlap:
            count += 1
    return count


def false_negatives(result) -> int:
    """Count expected corrections not overlapped by any returned correction."""
    count = 0
    for expected in result.expected:
        e_start = expected["start"]
        e_end = expected["end"]
        has_overlap = any(
            _overlaps(c["start"], c["end"], e_start, e_end)
            for c in result.corrections
        )
        if not has_overlap:
            count += 1
    return count


def true_negatives(result) -> int:
    if len(result.expected) == 0 and len(result.corrections) == 0:
        return 1
    return 0


def string_match_rate(results: list) -> float:
    """
    Of all overlapping (TP) correction pairs, fraction where predicted
    replacement matches gold correction (case-insensitive, whitespace-normalized).
    Returns 0.0 if no TPs.
    """
    matched = 0
    total_tp = 0
    for result in results:
        for correction in result.corrections:
            c_start, c_end = correction["start"], correction["end"]
            pred_text = _normalize(correction.get("correction", correction.get("replacement", "")))
            for expected in result.expected:
                if _overlaps(c_start, c_end, expected["start"], expected["end"]):
                    total_tp += 1
                    gold_text = _normalize(expected.get("correction", ""))
                    if pred_text == gold_text:
                        matched += 1
                    break
    return matched / total_tp if total_tp else 0.0


def precision(results: list) -> float:
    tp = sum(true_positives(r) for r in results)
    fp = sum(false_positives(r) for r in results)
    return tp / (tp + fp) if (tp + fp) else 0.0


def recall(results: list) -> float:
    tp = sum(true_positives(r) for r in results)
    fn = sum(false_negatives(r) for r in results)
    return tp / (tp + fn) if (tp + fn) else 0.0


def f1(results: list) -> float:
    prec = precision(results)
    rec = recall(results)
    return 2 * (prec * rec) / (prec + rec) if (prec + rec) else 0.0


def fp_rate(results: list) -> float:
    fp = sum(false_positives(r) for r in results)
    tn = sum(true_negatives(r) for r in results)
    return fp / (fp + tn) if (fp + tn) else 0.0


def latency_stats(results: list) -> dict[str, float]:
    available_latencies = [
        r.latency_ms for r in results if r.available and r.latency_ms >= 0
    ]
    if not available_latencies:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
    s = sorted(available_latencies)
    n = len(s)
    return {
        "p50": s[n // 2],
        "p95": s[int(n * 0.95)],
        "p99": s[int(n * 0.99)],
        "mean": mean(s),
    }


def context_detection_accuracy(results: list) -> float:
    """Fraction of items where detected_input_type matches item.input_type."""
    eligible = [r for r in results if r.detected_input_type is not None]
    if not eligible:
        return float("nan")
    correct = sum(1 for r in eligible if r.detected_input_type == r.input_type)
    return correct / len(eligible)


def tone_accuracy(results: list) -> float:
    """Fraction of tone-task items where predicted_label matches expected_label."""
    tone = [r for r in results if getattr(r, "task", None) == "tone"
            and r.expected_label is not None and r.predicted_label is not None]
    if not tone:
        return float("nan")
    correct = sum(1 for r in tone if r.predicted_label == r.expected_label)
    return correct / len(tone)


def by_input_type(results: list) -> dict[str, dict[str, float | int]]:
    by_type: dict[str, list] = {}
    for result in results:
        by_type.setdefault(result.input_type, []).append(result)
    output: dict[str, dict[str, float | int]] = {}
    for input_type, type_results in by_type.items():
        stats = latency_stats(type_results)
        output[input_type] = {
            "precision": precision(type_results),
            "recall": recall(type_results),
            "f1": f1(type_results),
            "fp_rate": fp_rate(type_results),
            "n_items": len(type_results),
            "latency_p50": stats["p50"],
        }
    return output


def by_tier(results: list) -> dict[str, dict[str, float | int]]:
    by_t: dict[str, list] = {}
    for result in results:
        by_t.setdefault(result.tier, []).append(result)
    output: dict[str, dict[str, float | int]] = {}
    for tier, tier_results in by_t.items():
        # Exclude tier_not_applicable rows — these items explicitly cannot be evaluated
        # by this tier (e.g., grammar-error items evaluated against a spell-check tier).
        applicable = [
            r for r in tier_results
            if not (r.error or "").startswith("tier_not_applicable")
        ]
        stats = latency_stats(applicable)
        output[tier] = {
            "precision": precision(applicable),
            "recall": recall(applicable),
            "f1": f1(applicable),
            "fp_rate": fp_rate(applicable),
            "n_items": len(applicable),
            "latency_p50": stats["p50"],
            "string_match_rate": string_match_rate(applicable),
            "n_not_applicable": len(tier_results) - len(applicable),
        }
    return output


def _cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a * norm_b > 0.0 else 0.0


def semantic_match_score(results: list) -> dict:
    """Embed predicted and gold replacement text for each TP pair with MiniLM
    and return cosine similarity statistics.

    Requires models/all-MiniLM-L6-v2-onnx/model_int8.onnx on disk.
    Returns {"available": False, ...} gracefully when model is absent.

    Thresholds:
      gold   >= 0.95 — essentially the same word/phrase
      silver  0.80–0.95 — right semantic neighbourhood, different word
      bronze  0.60–0.80 — related but drifting
      miss   < 0.60 — different semantic field
    """
    try:
        import os, sys
        sys.path.insert(0, os.path.dirname(__file__))
        import onnx_backend
        available = onnx_backend.minilm_available()
    except ImportError:
        available = False

    _empty = {"mean": float("nan"), "n_scored": 0,
               "gold": 0.0, "silver": 0.0, "bronze": 0.0, "miss": 0.0,
               "available": available}

    if not available:
        return _empty

    scores = []
    for result in results:
        for correction in result.corrections:
            c_start, c_end = correction["start"], correction["end"]
            pred_text = _normalize(
                correction.get("correction", correction.get("replacement", ""))
            )
            for expected in result.expected:
                if _overlaps(c_start, c_end, expected["start"], expected["end"]):
                    gold_text = _normalize(expected.get("correction", ""))
                    if pred_text and gold_text:
                        try:
                            sim = _cosine_similarity(
                                onnx_backend.embed(pred_text),
                                onnx_backend.embed(gold_text),
                            )
                            scores.append(sim)
                        except Exception:
                            pass
                    break

    if not scores:
        return _empty

    n = len(scores)
    gold   = sum(1 for s in scores if s >= SEMANTIC_GOLD)
    silver = sum(1 for s in scores if SEMANTIC_SILVER <= s < SEMANTIC_GOLD)
    bronze = sum(1 for s in scores if SEMANTIC_BRONZE <= s < SEMANTIC_SILVER)
    miss   = sum(1 for s in scores if s < SEMANTIC_BRONZE)

    return {
        "mean":     sum(scores) / n,
        "n_scored": n,
        "gold":     gold   / n,
        "silver":   silver / n,
        "bronze":   bronze / n,
        "miss":     miss   / n,
        "available": True,
    }


def by_error_type(results: list) -> dict[str, dict[str, float | int]]:
    """Group span_correction results by error_type and compute metrics."""
    by_et: dict[str, list] = {}
    for result in results:
        if getattr(result, "task", "span_correction") != "span_correction":
            continue
        et = getattr(result, "error_type", None) or "unknown"
        by_et.setdefault(et, []).append(result)
    output: dict[str, dict[str, float | int]] = {}
    for et, et_results in by_et.items():
        output[et] = {
            "precision": precision(et_results),
            "recall": recall(et_results),
            "f1": f1(et_results),
            "n_items": len(et_results),
            "string_match_rate": string_match_rate(et_results),
        }
    return output
