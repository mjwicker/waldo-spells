"""Metrics computation for test results."""

from typing import List, Dict
from statistics import median, mean


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Check if two character ranges overlap."""
    return not (a_end <= b_start or b_end <= a_start)


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
        has_overlap = False
        for expected in result.expected:
            e_start = expected["start"]
            e_end = expected["end"]
            if _overlaps(c_start, c_end, e_start, e_end):
                has_overlap = True
                break
        if not has_overlap:
            count += 1
    return count


def false_negatives(result) -> int:
    """Count expected corrections that don't overlap with any returned correction."""
    count = 0
    for expected in result.expected:
        e_start = expected["start"]
        e_end = expected["end"]
        has_overlap = False
        for correction in result.corrections:
            c_start = correction["start"]
            c_end = correction["end"]
            if _overlaps(c_start, c_end, e_start, e_end):
                has_overlap = True
                break
        if not has_overlap:
            count += 1
    return count


def true_negatives(result) -> int:
    """Count items with no expected and no returned corrections."""
    if len(result.expected) == 0 and len(result.corrections) == 0:
        return 1
    return 0


def precision(results: List) -> float:
    """
    Calculate precision: TP / (TP + FP).
    Returns 0.0 if no predictions made.
    """
    tp = sum(true_positives(r) for r in results)
    fp = sum(false_positives(r) for r in results)
    if tp + fp == 0:
        return 0.0
    return tp / (tp + fp)


def recall(results: List) -> float:
    """
    Calculate recall: TP / (TP + FN).
    Returns 0.0 if no expected corrections exist.
    """
    tp = sum(true_positives(r) for r in results)
    fn = sum(false_negatives(r) for r in results)
    if tp + fn == 0:
        return 0.0
    return tp / (tp + fn)


def f1(results: List) -> float:
    """
    Calculate F1 score: 2 * (precision * recall) / (precision + recall).
    Returns 0.0 if both precision and recall are 0.
    """
    prec = precision(results)
    rec = recall(results)
    if prec + rec == 0:
        return 0.0
    return 2 * (prec * rec) / (prec + rec)


def fp_rate(results: List) -> float:
    """
    Calculate false positive rate: FP / (FP + TN).
    Returns 0.0 if no negatives exist.
    """
    fp = sum(false_positives(r) for r in results)
    tn = sum(true_negatives(r) for r in results)
    if fp + tn == 0:
        return 0.0
    return fp / (fp + tn)


def latency_stats(results: List) -> Dict:
    """
    Calculate latency percentiles for available results.

    Returns:
        Dict with p50, p95, p99, mean keys (ms).
        Returns zeros if no available results.
    """
    available_latencies = [
        r.latency_ms for r in results if r.available and r.latency_ms >= 0
    ]
    if not available_latencies:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}

    available_latencies_sorted = sorted(available_latencies)
    return {
        "p50": available_latencies_sorted[len(available_latencies_sorted) // 2],
        "p95": available_latencies_sorted[int(len(available_latencies_sorted) * 0.95)],
        "p99": available_latencies_sorted[int(len(available_latencies_sorted) * 0.99)],
        "mean": mean(available_latencies),
    }


def by_input_type(results: List) -> Dict[str, Dict]:
    """
    Group results by input_type and compute metrics.

    Returns:
        Dict mapping input_type to {precision, recall, f1, fp_rate, n_items, latency_p50}.
    """
    by_type = {}
    for result in results:
        input_type = result.input_type
        if input_type not in by_type:
            by_type[input_type] = []
        by_type[input_type].append(result)

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
    """
    Group results by tier and compute metrics.

    Returns:
        Dict mapping tier to {precision, recall, f1, fp_rate, n_items, latency_p50}.
    """
    by_t = {}
    for result in results:
        tier = result.tier
        if tier not in by_t:
            by_t[tier] = []
        by_t[tier].append(result)

    output = {}
    for tier, tier_results in by_t.items():
        stats = latency_stats(tier_results)
        output[tier] = {
            "precision": precision(tier_results),
            "recall": recall(tier_results),
            "f1": f1(tier_results),
            "fp_rate": fp_rate(tier_results),
            "n_items": len(tier_results),
            "latency_p50": stats["p50"],
        }
    return output
