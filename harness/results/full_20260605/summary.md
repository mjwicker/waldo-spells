# Test Harness Results — full_20260605

## Tier Availability

| Tier | Ran | Skipped (tier_unavailable) |
|------|-----|----------------------------|
| better | 4782 | 0 |
| fast | 3032 | 1750 |
| smart | 0 | 4782 |

## Overall Metrics

- Total runs: 14346
- Latency (ms): p50=25.79, p95=94.49, p99=143.82, mean=29.49
- String match rate: 0.477
- Context detection accuracy: n/a
- Tone accuracy: n/a

## Results by Tier

| Tier | Precision | Recall | F1 | FP Rate | Str Match | Items | Latency P50 |
|------|-----------|--------|-----|---------|-----------|-------|-------------|
| better | 0.457 | 0.338 | 0.388 | 0.365 | 0.481 | 4782 | 32.07 |
| fast | 0.012 | 0.333 | 0.023 | 0.233 | 0.000 | 3032 | 1.92 |
| smart | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 4782 | 0.00 |

## Results by Input Type

| Input Type | Precision | Recall | F1 | FP Rate | Items | Latency P50 |
|------------|-----------|--------|-----|---------|-------|-------------|
| ai_chat | 0.250 | 0.056 | 0.091 | 0.333 | 24 | 39.39 |
| email | 0.667 | 0.333 | 0.444 | 0.333 | 24 | 44.17 |
| general | 0.342 | 0.107 | 0.162 | 0.204 | 14250 | 25.80 |
| github | 0.500 | 0.267 | 0.348 | 0.364 | 24 | 40.44 |
| slack | 0.583 | 0.318 | 0.412 | 0.625 | 24 | 20.07 |

## Results by Error Type

| Error Type | Precision | Recall | F1 | Str Match | Items |
|------------|-----------|--------|-----|-----------|-------|
| Article | 1.000 | 0.333 | 0.500 | 1.000 | 744 |
| Noun Form | 0.000 | 0.000 | 0.000 | 0.000 | 819 |
| Preposition | 1.000 | 0.200 | 0.333 | 1.000 | 714 |
| Pronoun | 0.000 | 0.000 | 0.000 | 0.000 | 747 |
| Subject-Verb Agreement | 1.000 | 0.333 | 0.500 | 0.000 | 831 |
| Verb Tense | 1.000 | 0.167 | 0.286 | 0.000 | 708 |
| Word Order | 0.000 | 0.000 | 0.000 | 0.000 | 687 |
| unknown | 0.556 | 0.253 | 0.348 | 0.000 | 96 |

## Context Detection Accuracy

- Accuracy: n/a
- Eligible runs (hint omitted): 0

## Tone Accuracy

- Accuracy: n/a
- Tone-task runs: 9000
