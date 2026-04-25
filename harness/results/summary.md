# Test Harness Results

## Overall Metrics

- Total runs: 32
- Latency (ms): p50=0.93, p95=2.39, p99=2.75, mean=1.16

## Results by Tier

| Tier | Precision | Recall | F1 | FP Rate | Items | Latency P50 (ms) |
|------|-----------|--------|----|---------| ------|------------------|
| fast | 0.750 | 0.333 | 0.462 | 0.273 | 32 | 0.93 |

## Results by Input Type

| Input Type | Precision | Recall | F1 | FP Rate | Items | Latency P50 (ms) |
|------------|-----------|--------|----|---------| ------|------------------|
| ai_chat | 0.000 | 0.000 | 0.000 | 0.000 | 8 | 0.90 |
| email | 0.750 | 0.375 | 0.500 | 0.250 | 8 | 0.98 |
| github | 0.600 | 0.600 | 0.600 | 0.500 | 8 | 1.42 |
| slack | 1.000 | 0.375 | 0.545 | 0.000 | 8 | 0.94 |

