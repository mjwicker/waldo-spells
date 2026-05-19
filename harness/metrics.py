"""Metrics computation for test results."""

from typing import List, Dict
from statistics import median, mean


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Check if two character ranges overlap."""
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


def string_match_rate(results: List) -> float:
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


def precision(results: List) -> float:
    tp = sum(true_positives(r) for r in results)
    fp = sum(false_positives(r) for r in results)
    return tp / (tp + fp) if (tp + fp) else 0.0


def recall(results: List) -> float:
    tp = sum(true_positives(r) for r in results)
    fn = sum(false_negatives(r) for r in results)
    return tp / (tp + fn) if (tp + fn) else 0.0


def f1(results: List) -> float:
    prec = precision(results)
    rec = recall(results)
    return 2 * (prec * rec) / (prec + rec) if (prec + rec) else 0.0


def fp_rate(results: List) -> float:
    fp = sum(false_positives(r) for r in results)
    tn = sum(true_negatives(r) for r in results)
    return fp / (fp + tn) if (fp + tn) else 0.0


def latency_stats(results: List) -> Dict:
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


def context_detection_accuracy(results: List) -> float:
    """Fraction of items where detected_input_type matches item.input_type."""
    eligible = [r for r in results if r.detected_input_type is not None]
    if not eligible:
        return float("nan")
    correct = sum(1 for r in eligible if r.detected_input_type == r.input_type)
    return correct / len(eligible)


def tone_accuracy(results: List) -> float:
    """Fraction of tone-task items where predicted_label matches expected_label."""
    tone = [r for r in results if getattr(r, "task", None) == "tone"
            and r.expected_label is not None and r.predicted_label is not None]
    if not tone:
        return float("nan")
    correct = sum(1 for r in tone if r.predicted_label == r.expected_label)
    return correct / len(tone)


def by_input_type(results: List) -> Dict[str, Dict]:
    by_type: Dict[str, List] = {}
    for result in results:
        by_type.setdefault(result.input_type, []).append(result)
    output = {}
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


def by_tier(results: List) -> Dict[str, Dict]:
    by_t: Dict[str, List] = {}
    for result in results:
        by_t.setdefault(result.tier, []).append(result)
    output = {}
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


def by_error_type(results: List) -> Dict[str, Dict]:
    """Group span_correction results by error_type and compute metrics."""
    by_et: Dict[str, List] = {}
    for result in results:
        if getattr(result, "task", "span_correction") != "span_correction":
            continue
        et = getattr(result, "error_type", None) or "unknown"
        by_et.setdefault(et, []).append(result)
    output = {}
    for et, et_results in by_et.items():
        output[et] = {
            "precision": precision(et_results),
            "recall": recall(et_results),
            "f1": f1(et_results),
            "n_items": len(et_results),
            "string_match_rate": string_match_rate(et_results),
        }
    return output
