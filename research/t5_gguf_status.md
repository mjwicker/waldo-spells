# T5 GGUF Support Research for Waldo Grammar Checker (Mid Tier)

**Research Date**: 2026-04-25  
**Target Model**: Unbabel/gec-t5_small  
**Hardware Target**: Pentium N6000, 4GB RAM (constrained)

---

## 1. Model Under Investigation

### Unbabel/gec-t5_small Specifications

| Property | Value |
|----------|-------|
| **Architecture** | T5ForConditionalGeneration (encoder-decoder) |
| **Base Model** | Google T5-small |
| **Task** | Grammatical Error Correction (GEC) |
| **Parameters** | ~60 million (T5-small baseline) |
| **Approximate Size (FP32)** | 240–250 MB |
| **Size (INT8 quantized)** | ~60–70 MB |
| **F₀.₅ Score (GEC)** | 60.70 |
| **Inference Input Format** | "gec: " + input text |
| **License** | Apache 2.0 |
| **HuggingFace Repo** | [Unbabel/gec-t5_small](https://huggingface.co/Unbabel/gec-t5_small) |

**Key Characteristics**:
- Compact encoder-decoder model designed for real-time grammar correction
- Two quantization variants already available on HuggingFace (no GGUF noted)
- Well-tested on grammatical error correction benchmarks
- Fits easily in memory even at FP32 on constrained hardware

---

## 2. llama.cpp T5 Support Status

### Current Implementation (as of April 2025)

| Component | Status | Notes |
|-----------|--------|-------|
| **Conversion (convert_hf_to_gguf.py)** | ✅ Merged (PR #8055, June 2024) | Supports T5-small through T5-11B, all FLAN-T5 variants |
| **Encoder-Decoder Inference** | ✅ Merged (PR #8141, July 2024) | Full encoder-decoder architecture support |
| **llama-cli Support** | ✅ Full | Can run T5 models end-to-end |
| **llama-server Support** | ❌ Not yet | Web API does not support encoder-decoder |
| **Quantization (imatrix)** | ⚠️ Partial | No KV cache quantization support for T5 |

### Key Limitations

**1. No Encoder Caching**
- Encoder recalculates on every input change (no KV cache)
- Re-encoding entire sequence each inference = O(seq_len²) attention computation
- **Impact**: Batch processing of single sentences is fine; dynamic chat histories would cause re-encoding overhead

**2. llama-server Unsupported**
- Only llama-cli can run T5 models
- No HTTP API wrapper yet for seamless integration
- **Workaround**: Build custom C++ wrapper or use llama-cli subprocess integration

**3. Quantization Quality**
- imatrix (importance weighting) not supported for T5
- Simple quantization (q4_0, q8_0) work but may lose accuracy on fine-grained grammar corrections
- **Recommendation**: Use q8_0 or f16 for grammar task precision

### GitHub References

- **Issue #5763**: [Add T5 (encoder-decoder) support](https://github.com/ggml-org/llama.cpp/issues/5763) — Closed/Merged
- **PR #8055**: [Model conversion support for T5 and FLAN-T5](https://github.com/ggml-org/llama.cpp/pull/8055) — Merged (June 24, 2024)
- **PR #8141**: [Inference support for T5 and FLAN-T5](https://github.com/ggerganov/llama.cpp/pull/8141) — Merged (July 4, 2024)

---

## 3. GGUF Availability

### Existing GGUF Models

#### T5-Small Variants
- **agkavin/t5-small-Q8_0-GGUF** — [Link](https://huggingface.co/agkavin/t5-small-Q8_0-GGUF)
  - Google T5-small converted to GGUF (Q8_0 quantization)
  - Size: ~68 MB
  - Status: Available, tested with llama.cpp

#### FLAN-T5-Small Variants
- **Plasmoxy/flan-t5-small-Q8_0-GGUF** — [Link](https://huggingface.co/Plasmoxy/flan-t5-small-Q8_0-GGUF)
  - Size: ~82.9 MB
  - Quantization: Q8_0 (8-bit)

- **AncientCatz/flan-t5-small-Q2_K-GGUF** — [Link](https://huggingface.co/AncientCatz/flan-t5-small-Q2_K-GGUF)
  - Extreme quantization: Q2_K
  - Size: ~36.9 MB
  - Trade-off: Smaller but lower quality

#### Larger T5 Models (for reference)
- **city96/t5-v1_1-xxl-encoder-gguf** — [Link](https://huggingface.co/city96/t5-v1_1-xxl-encoder-gguf)
  - T5-XXL encoder (decoder-only) in GGUF format
  - Multiple quantization levels (Q3_K, Q4_K, Q5_K, Q6_K, Q8_0, f16)
  - Ecosystem maturity signal: XXL models already quantized

### Status of gec-t5_small Specifically

**No pre-converted GGUF mirror found.** However:
- Unbabel/gec-t5_small has 2 quantization variants available (format unclear — likely safetensors/PyTorch)
- Can be converted using llama.cpp's `convert_hf_to_gguf.py` script
- Expected output size: ~60–70 MB (Q8_0), ~50 MB (Q5_K), ~40 MB (Q4_K)

**Conversion Command** (estimated):
```bash
python convert_hf_to_gguf.py \
  /path/to/Unbabel/gec-t5_small \
  --outfile gec-t5_small-q8_0.gguf \
  --outtype q8_0
```

---

## 4. Alternative Runtime Options

### Option A: llama.cpp with T5 GGUF (Primary Path)

**Advantages**:
- ✅ Full T5 encoder-decoder support (merged, production-ready)
- ✅ Inference works on CPU with q8_0 quantization
- ✅ Smallest model footprint (60–70 MB)
- ✅ Mature ecosystem (multiple working examples)
- ✅ No heavy Python runtime dependency for inference

**Disadvantages**:
- ❌ No llama-server HTTP API yet (CLI only)
- ❌ No encoder KV caching (re-encodes each pass)
- ❌ Requires building custom wrapper for integration
- ⚠️ Quantization quality unknown for grammar task (needs benchmarking)

**Integration Path**: Build C++ wrapper around llama-cli or raw llama.cpp library calls.

**Estimated Latency on N6000**:
- **First pass (encode + decode)**: 8–12 seconds per sentence
- **Batch (10 sentences)**: ~80–120 seconds
- **Inference memory**: ~150–200 MB (model + activations)

---

### Option B: CTranslate2 (T5-Specific, Production-Ready)

**Model State**: T5 is **fully supported** in CTranslate2 with INT8 quantization.

**Architecture**:
- C++ inference framework optimized for transformer encoder-decoder models
- Native INT8 quantization on CPU
- Supports NVIDIA GPU when available (fallback to CPU)
- Faster inference than transformers + PyTorch on CPU

**Conversion**:
```bash
ct2-transformers-converter \
  --model Unbabel/gec-t5_small \
  --output_dir ./gec-t5_small-ct2 \
  --quantization int8 \
  --target_arch x86_64
```

**Advantages**:
- ✅ Purpose-built for encoder-decoder inference
- ✅ INT8 quantization mature and benchmarked
- ✅ Reported 2x speedup vs FP32 on CPU
- ✅ ~100 MB footprint with INT8 (some sources report lower)
- ✅ Python bindings available (`ctranslate2` package)
- ✅ Robust error handling and dynamic batching

**Disadvantages**:
- ❌ Separate runtime dependency (not in llama.cpp ecosystem)
- ❌ Less integration with Waldo's llama-server architecture
- ⚠️ Smaller ecosystem than llama.cpp (but production-proven)

**Integration Path**: Wrap `ctranslate2` Python bindings in Waldo's standard tool interface.

**Estimated Latency on N6000**:
- **First pass (encode + decode)**: 6–10 seconds per sentence
- **Batch (10 sentences)**: ~60–100 seconds
- **Inference memory**: ~120–150 MB

---

### Option C: Transformers + PyTorch + INT8 (Heavy, Not Recommended)

**Architecture**: Native PyTorch with HuggingFace Transformers.

**Quantization Method** (using bitsandbytes or torch native INT8):
```python
from transformers import T5ForConditionalGeneration, T5Tokenizer
import torch

model = T5ForConditionalGeneration.from_pretrained(
    "Unbabel/gec-t5_small",
    load_in_8bit=True,  # bitsandbytes INT8
    device_map="cpu"
)
tokenizer = T5Tokenizer.from_pretrained("t5-small")
```

**Advantages**:
- ✅ Familiar Python API
- ✅ INT8 support via bitsandbytes or torch
- ✅ Full precision available if needed

**Disadvantages**:
- ❌ Heavy runtime: PyTorch (~500 MB) + transformers (~100 MB)
- ❌ Slow on CPU: INT8 PyTorch CPU inference slower than FP32 in some cases
- ❌ Memory spike at load time (model + activations + overhead = 300–400 MB)
- ❌ Barely fits in 4GB Pentium N6000 during inference
- ❌ Incompatible with Waldo's model-agnostic architecture
- ⚠️ Not recommended for constrained tier

**Expected Memory Usage**:
- Model weights (INT8): ~60 MB
- Activations (batch size 1): ~80–120 MB
- PyTorch/transformers overhead: ~200–300 MB
- **Total**: ~350–480 MB (60% of 4GB RAM)

**Estimated Latency on N6000**:
- **First pass**: 10–15 seconds per sentence
- **Batch (10 sentences)**: ~100–150 seconds
- Slower than both llama.cpp and CTranslate2 due to runtime overhead

---

## 5. Decision + Recommendation

### Recommended Path: **CTranslate2**

**Rationale**:
1. **Balance of Speed and Integration**: 6–10s per sentence on constrained hardware is acceptable for Mid tier; faster than PyTorch, comparable to llama.cpp CLI
2. **Maturity for T5**: Encoder-decoder support is production-proven; T5 is first-class, not experimental
3. **Memory Efficiency**: ~100–120 MB footprint leaves 3.9 GB for other Mid-tier processes
4. **Python Integration**: Wraps cleanly into Waldo's existing Python tool framework
5. **No Architecture Debt**: Unlike llama.cpp (which lacks llama-server for T5), CTranslate2 has stable inference APIs

### Secondary Path: **llama.cpp GGUF** (if ecosystem preference dominates)

If Waldo prioritizes staying within the llama.cpp ecosystem (for consistency across all models), use llama.cpp with T5 GGUF:
- Build C++ wrapper with subprocess or native bindings
- Accept ~8–12s per sentence latency
- Work around lack of llama-server by wrapping llama-cli
- Plan to migrate to llama-server once T5 HTTP API support lands

### Not Recommended: PyTorch + INT8

Memory footprint is too tight on constrained 4GB hardware; latency gains don't justify the integration complexity.

---

## 6. Estimated CPU Latency on N6000

### Hardware Profile
- **CPU**: Intel Pentium Silver N6000 (6-core, 2.7–3.5 GHz)
- **RAM**: 4 GB DDR4
- **Storage**: SSD (inference model loading)
- **No GPU**

### Latency Estimates (per sentence, ~20 tokens input + 15 tokens output)

| Runtime | Quantization | First Pass | Batch (10 sentences) | Memory |
|---------|-------------|-----------|----------------------|--------|
| **CTranslate2** | INT8 | 6–10s | 60–100s | 120 MB |
| **llama.cpp** | Q8_0 | 8–12s | 80–120s | 150 MB |
| **llama.cpp** | Q5_K | 7–11s | 70–110s | 140 MB |
| **PyTorch** | INT8 | 10–15s | 100–150s | 350 MB |
| **PyTorch** | FP32 | 15–20s | 150–200s | 500 MB+ |

**Notes**:
- Latencies assume single-threaded inference; N6000 can parallelize some operations
- "First pass" includes model loading if not cached
- "Batch" is sequential (not parallel) inference on 10 sentences
- Memory figures are active during inference (model + activations)

### Practical User Experience

**CTranslate2 Target**: 6–10 seconds per correction is acceptable for browser extension (user sees correction within one keystroke cycle)

**Batch Processing**: Mid tier is expected to handle ~50–100 corrections/min in background; at 6–10s each, this means 5–10 concurrent contexts or heavy queuing.

---

## 7. Integration Path (CTranslate2)

### File Structure
```
GrammarChecker/
├── wrapper/
│   ├── t5_backend.py          (CTranslate2 inference wrapper)
│   ├── t5_converter.py        (convert model to CT2 format)
│   └── quantization_config.py (INT8 settings)
├── models/
│   └── gec-t5_small-ct2/      (converted model directory)
└── tests/
    └── test_t5_latency.py     (benchmark on N6000)
```

### Implementation Steps

#### 1. Download and Convert Model
```bash
# One-time conversion step
python wrapper/t5_converter.py \
  --model_id Unbabel/gec-t5_small \
  --output_dir models/gec-t5_small-ct2 \
  --quantization int8
```

#### 2. Build Inference Wrapper
```python
# wrapper/t5_backend.py
import ctranslate2
from typing import List

class T5Backend:
    def __init__(self, model_path: str):
        self.model = ctranslate2.Translator(
            model_path,
            device="cpu",
            computation_type="int8"  # CPU INT8
        )
        self.tokenizer = T5Tokenizer.from_pretrained("t5-small")
    
    def correct(self, text: str) -> str:
        input_text = f"gec: {text}"
        inputs = self.tokenizer.encode([input_text])
        outputs = self.model.translate_batch(inputs)
        corrected = self.tokenizer.decode(outputs[0][0])
        return corrected
    
    def correct_batch(self, texts: List[str]) -> List[str]:
        inputs = [f"gec: {t}" for t in texts]
        tokenized = self.tokenizer.encode(inputs)
        outputs = self.model.translate_batch(tokenized)
        corrected = [self.tokenizer.decode(o[0]) for o in outputs]
        return corrected
```

#### 3. Integration with Waldo Tool System
```python
# capability/grammar_checker.py (Waldo manifest integration)
from wrapper.t5_backend import T5Backend

class GrammarChecker:
    def __init__(self, config):
        self.t5 = T5Backend(
            model_path=config["model_path"],
            cache_dir=config.get("cache_dir")
        )
    
    async def execute(self, text: str, context: dict) -> str:
        # Waldo capability interface
        return self.t5.correct(text)
```

#### 4. Memory Management
- Pre-load model on startup (or lazy-load on first request)
- Batch corrections if queue grows (call `correct_batch()`)
- Monitor memory; re-encode on low-memory signal if needed

#### 5. Fallback Strategy
- If CTranslate2 load fails → fall back to PyTorch (heavier but guaranteed)
- If both fail → disable grammar correction capability gracefully

---

## 8. Open Questions & Next Steps

### Resolved via Research
- ✅ T5 encoder-decoder support is production-ready in llama.cpp (PR #8141 merged)
- ✅ gec-t5_small can be converted to GGUF using standard llama.cpp tools
- ✅ CTranslate2 has mature T5 support with INT8 quantization
- ✅ GGUF models (flan-t5-small) already exist, proving ecosystem maturity

### Unresolved (Requires Benchmarking)

1. **Quantization Quality for Grammar Task**
   - Q8_0 and INT8 preserve accuracy on grammar corrections?
   - Need test: side-by-side comparison (gec-t5_small FP32 vs Q8_0 vs INT8) on grammar benchmark
   - Target: <2% F₀.₅ score loss acceptable

2. **Actual Latency on N6000**
   - Estimates above are conservative; real hardware may be faster/slower
   - Need test: run 100-sentence batch on actual N6000 Pentium hardware
   - Current estimate: 6–10s/sentence; acceptable if <8s/sentence

3. **Encoder Re-encoding Overhead (llama.cpp)**
   - How much penalty for dynamic (chat) corrections vs static batch?
   - Is per-sentence re-encoding noticeable to user?
   - May favor CTranslate2 if overhead is >20% for dynamic workload

4. **CTranslate2 vs llama.cpp Side-by-Side**
   - Memory profiling (actual VM RSS on N6000)
   - CPU utilization and thermal behavior
   - Integration effort (CTranslate2 Python vs llama.cpp C++)

### Next Steps

1. **Build benchmarking harness** (task #4 pending):
   - Download both gec-t5_small (original) and flan-t5-small GGUF
   - Implement inference wrappers for both CTranslate2 and llama.cpp
   - Run on N6000 with latency/memory profiling
   - Compare F₀.₅ scores on GEC benchmark

2. **Prototype CTranslate2 integration**:
   - Convert gec-t5_small to CT2 format
   - Build wrapper matching Waldo capability interface
   - Test with real browser extension context samples

3. **Decide on quantization level**:
   - If Q8_0 acceptable: use it (slightly faster, smaller)
   - If quality loss >2%: stick with F16 GGUF (larger but full precision)

---

## References

### llama.cpp T5 Support
- [PR #8055: Model conversion support](https://github.com/ggml-org/llama.cpp/pull/8055)
- [PR #8141: Inference support for T5](https://github.com/ggerganov/llama.cpp/pull/8141)
- [Issue #5763: Add T5 encoder-decoder support](https://github.com/ggml-org/llama.cpp/issues/5763)

### Model & GGUF Availability
- [Unbabel/gec-t5_small on HuggingFace](https://huggingface.co/Unbabel/gec-t5_small)
- [agkavin/t5-small-Q8_0-GGUF](https://huggingface.co/agkavin/t5-small-Q8_0-GGUF)
- [Plasmoxy/flan-t5-small-Q8_0-GGUF](https://huggingface.co/Plasmoxy/flan-t5-small-Q8_0-GGUF)

### CTranslate2
- [CTranslate2 GitHub](https://github.com/OpenNMT/CTranslate2)
- [CTranslate2 Quantization Docs](https://opennmt.net/CTranslate2/quantization.html)
- [CTranslate2 on PyPI](https://pypi.org/project/ctranslate2/)

### Quantization & Latency
- [HuggingFace Quantization Docs](https://huggingface.co/docs/transformers/main_classes/quantization)
- [PyTorch INT8 Quantization](https://pytorch.org/blog/int8-quantization/)
- [INT8 Quantization for x86 CPU](https://pytorch.org/blog/int8-quantization/)

---

## Document History

| Date | Author | Change |
|------|--------|--------|
| 2026-04-25 | Claude Code | Initial research on T5 GGUF support for Waldo Grammar Checker (Mid tier) |
