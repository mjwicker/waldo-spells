# CT2 Smart Tier Research — Decision Document

## Objective

Evaluate whether a larger CTranslate2 (CT2) GEC model can replace the llama-server smart tier entirely, running in-process with no subprocess dependency. This research cycle determines feasibility and captures benchmark data for a follow-on implement task.

## Motivation

The current **smart tier** (T-SPELLS-SMART-1) uses Qwen2.5-3B-Instruct via llama-server, achieving strong F1 (0.443) and recall (0.515) but incurring:
- 30–90 second latency p50 on CPU
- 2.5–3 GB RAM overhead (llama-server process separate from frontend)
- External subprocess management complexity

The **better tier** (Mid) uses Unbabel/gec-t5_small via CTranslate2, running in-process with excellent latency (49ms p50) but lower F1 (0.388). A larger T5 variant (or equivalent GEC model in CT2 format) could close the F1 gap while preserving in-process execution and latency benefits.

## Candidates for Evaluation

### Option A: vennify/t5-base-grammar-correction
- **HuggingFace ID**: `vennify/t5-base-grammar-correction`
- **Architecture**: T5-base encoder-decoder (220M params vs. gec-t5_small's 60M)
- **Expected performance**: Higher capacity than t5-small; unknown exact F1/recall on Waldo corpus
- **Conversion**: Standard T5 → CT2 via `ct2-transformers-converter --quantization int8`
- **Tokenizer**: `T5Tokenizer` (standard, same as current Mid tier)

### Option B: prithivida/grammar_error_correcter_v1
- **HuggingFace ID**: `prithivida/grammar_error_correcter_v1`
- **Architecture**: T5-base variant, trained on broader GEC corpus
- **Expected performance**: Likely competitive with Option A; less documentation available
- **Conversion**: T5 → CT2 via same pathway
- **Tokenizer**: `T5Tokenizer` (standard)

## Benchmark Plan

For each candidate, measure:

1. **F1 score** (Waldo corpus baseline: F1=0.443 for llama smart tier)
   - Use existing harness infrastructure
   - Overlap-based precision/recall per metrics.py
   - Report F1, precision, recall

2. **Latency (p50)** (baseline: 49ms for current t5-small)
   - Single-sentence per-model execution time
   - Hardware: MW Tower (i5-8400, 11.5GB RAM) + constrained Mini PC (Pentium N6000, 3.6GB RAM)
   - Report p50, p95, p99 across 500+ test sentences

3. **RAM footprint** (baseline: ~120–150 MB resident for current t5-small)
   - Peak resident memory during model load + correction pass
   - Compare single-sentence latency / memory tradeoffs

## Implementation Strategy (Post-Research)

If a candidate achieves **F1 ≥ 0.42** and **p50 latency ≤ 500ms** on constrained hardware:

1. **Generalize t5_backend.py tokenizer**:
   - Currently hard-coded to `T5Tokenizer.from_pretrained("t5-small")` at line 78
   - Add `CT2_SMART_MODEL_TOKENIZER` env var (default: `t5-base` if not set)
   - Parameterize `_load()` to accept model ID for tokenizer

2. **Update t5_converter.py**:
   - Add `--model` and `--tokenizer` flags for flexible model/tokenizer pairs
   - Reuse existing `ct2-transformers-converter` subprocess call

3. **Minimal tier_router.py change** (one-line swap):
   - Create new backend module `t5_smart_backend.py` (copy of t5_backend.py + new tokenizer logic)
   - OR: parameterize existing t5_backend to support multiple model configs
   - Update `TIER_MAP["smart"] = ct2_smart_backend`

4. **Separate env var namespace**:
   - Use `CT2_SMART_MODEL_PATH` (not shared with existing `CT2_MODEL_PATH`)
   - Avoids accidental fallback to wrong model for mid tier

## Success Criteria

**Research cycle complete when**:
- Both candidates converted to CT2 INT8 format
- Benchmark results logged (F1, latency p50/p95/p99, RAM) for both candidates + baselines
- Decision document updated with findings
- No code changes to tier_router.py or backend modules this cycle

**Implement task eligible when**:
- F1 ≥ 0.42 (acceptable gap closure vs. 0.443 llama baseline)
- p50 latency ≤ 500ms on constrained hardware
- Consensus that in-process execution + no subprocess overhead outweighs any model quality loss

## Related Prior Work

- **T-SPELLS-SMART-1** (✅ shipped): llama-server baseline, F1=0.443, p50=1952ms
- **T-SPELLS-SMART-ONNX** (in research): Phi-3 in-browser, zero-server fallback
- **T-SPELLS-BETTER** (✅ shipped): t5-small CT2, F1=0.388, p50=49ms

This research sits between 1 and ONNX: pragmatic middle path with in-process execution, no server, no browser constraint.

## Notes

- Do NOT rewire `TIER_MAP["smart"]` this cycle — decision doc first.
- Conversion and benchmarking can run in parallel across candidates.
- If both candidates underperform (F1 < 0.40), consider: (a) even larger T5 variants, (b) domain-specific fine-tuning on C4200m, or (c) accept llama-server as permanent smart tier and close this research.
