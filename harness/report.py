"""Report generation for test results."""

import argparse
import csv
import sys
from pathlib import Path

from corpus import load_corpus
from runner import run_all
from metrics import by_input_type, by_tier, latency_stats


def write_csv(results, path: Path) -> None:
    """
    Write results to CSV file.

    Args:
        results: List of RunResult objects.
        path: Path to output CSV file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "item_id",
                "tier",
                "input_type",
                "latency_ms",
                "n_corrections",
                "n_expected",
                "tp",
                "fp",
                "fn",
                "error",
                "available",
            ]
        )

        for result in results:
            from metrics import true_positives, false_positives, false_negatives
            tp = true_positives(result)
            fp = false_positives(result)
            fn = false_negatives(result)

            writer.writerow(
                [
                    result.item_id,
                    result.tier,
                    result.input_type,
                    f"{result.latency_ms:.2f}",
                    len(result.corrections),
                    len(result.expected),
                    tp,
                    fp,
                    fn,
                    result.error or "",
                    str(result.available),
                ]
            )


def write_summary(results, path: Path) -> None:
    """
    Write markdown summary with per-tier and per-input-type tables.

    Args:
        results: List of RunResult objects.
        path: Path to output markdown file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        f.write("# Test Harness Results\n\n")

        # Overall stats
        stats = latency_stats(results)
        f.write("## Overall Metrics\n\n")
        f.write(f"- Total runs: {len(results)}\n")
        f.write(
            f"- Latency (ms): p50={stats['p50']:.2f}, p95={stats['p95']:.2f}, p99={stats['p99']:.2f}, mean={stats['mean']:.2f}\n\n"
        )

        # Per-tier table
        tier_metrics = by_tier(results)
        f.write("## Results by Tier\n\n")
        f.write(
            "| Tier | Precision | Recall | F1 | FP Rate | Items | Latency P50 (ms) |\n"
        )
        f.write("|------|-----------|--------|----|---------| ------|------------------|\n")
        for tier in sorted(tier_metrics.keys()):
            m = tier_metrics[tier]
            f.write(
                f"| {tier} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['fp_rate']:.3f} | {m['n_items']} | {m['latency_p50']:.2f} |\n"
            )
        f.write("\n")

        # Per-input-type table
        type_metrics = by_input_type(results)
        f.write("## Results by Input Type\n\n")
        f.write(
            "| Input Type | Precision | Recall | F1 | FP Rate | Items | Latency P50 (ms) |\n"
        )
        f.write("|------------|-----------|--------|----|---------| ------|------------------|\n")
        for input_type in sorted(type_metrics.keys()):
            m = type_metrics[input_type]
            f.write(
                f"| {input_type} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['fp_rate']:.3f} | {m['n_items']} | {m['latency_p50']:.2f} |\n"
            )
        f.write("\n")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run grammar checker test harness and generate reports."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).parent / "corpus.jsonl",
        help="Path to corpus JSONL file",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="Output directory for results",
    )
    parser.add_argument(
        "--tiers",
        type=str,
        default="fast,better,smart",
        help="Comma-separated list of tiers to test",
    )

    args = parser.parse_args()

    # Load corpus
    print(f"Loading corpus from {args.corpus}...")
    corpus = load_corpus(args.corpus)
    print(f"Loaded {len(corpus)} items")

    # Parse tiers
    tiers = tuple(t.strip() for t in args.tiers.split(","))
    print(f"Testing tiers: {tiers}")

    # Run tests
    print("Running tests...")
    results = run_all(corpus, tiers=tiers)
    print(f"Completed {len(results)} runs")

    # Write reports
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "results.csv"
    summary_path = args.out_dir / "summary.md"

    print(f"Writing CSV to {csv_path}...")
    write_csv(results, csv_path)

    print(f"Writing summary to {summary_path}...")
    write_summary(results, summary_path)

    print("Done!")


if __name__ == "__main__":
    main()
