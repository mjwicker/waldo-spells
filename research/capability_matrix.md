# Waldo Spells: Capability Matrix Research

**Project**: Waldo Spells (Grammar Checker, Firefox Extension)  
**Research Date**: April 2026  
**Focus**: Three-tier architecture validation with performance targets  
**Hardware Context**: Dev (Pentium N6000 CPU-only, 4GB RAM) vs. Target (RTX 3060 12GB)

---

## Overview

This document presents a capability matrix for a three-tier grammar/spell checking system designed for local-first deployment. The research evaluates 15+ models and tools across three performance tiers, each with distinct latency targets and use cases:

1. **Fast Tier** — Spell-check only, sub-50ms on CPU (keystroke-level)
2. **Mid Tier** — Context-aware grammar correction, <200ms on RTX 3060 (user-triggered)
3. **Smart Tier** — Tone/voice suggestions, <500ms on RTX 3060 (user-triggered)

**Key Question**: Can one model serve all tiers in <200ms, or is a tiered architecture necessary?

---

## Tier 1: Fast (Spell-Check Only)

**Use Case**: Real-time keystroke feedback. Target: <50ms on CPU.  
**Scope**: Typos, misspellings, basic punctuation. No grammar analysis required.

| Model | Size (params) | Tier | License | Latency N6000 CPU (est.) | Latency RTX 3060 (est.) | Capabilities | Notes |
|-------|---------------|------|---------|--------------------------|--------------------------|--------------|-------|
| **hunspell** | ~10 MB dict | Tool | LGPL (Python wrapper: GPL/MIT) | <1 ms | <1 ms | Spell checking only, suggestions via trie lookup | Dictionary-based, no ML. Sub-millisecond. Proven in production (LibreOffice, Firefox). Limited to lexicon; misses context-dependent errors. Wrapper: `hunspell-py` or `hunspell-cli`. |
| **Nuspell** | ~10 MB dict | Tool | MPL-2.0 | <2 ms | <2 ms | Spell checking, faster suggestions than Hunspell | Modern C++ rewrite of Hunspell. 3.5× faster than Hunspell, 8× faster suggestions. Direct replacement for production systems. Requires C binding in Python. |
| **symspellpy** | ~10 MB dict | Tool | MIT | 1–5 ms | 1–5 ms | Spell checking via symmetric delete algorithm | Python-native. Fast edit-distance-based lookup. No grammar understanding. Suitable for low-resource deployment. |
| **sdadas/byt5-text-correction** | 150 M | GGUF → ~50 MB (Q4) | Apache 2.0 | 800–1200 ms | 45–80 ms | Spell + light punctuation, multilingual | BytT5 (character-level). Slow on CPU. Good on GPU. Designed for web text cleanup (missing caps, punctuation). Not context-aware. |
| **oliverguhr/spelling-correction-english-base** | 139 M (BART) | GGUF → ~45 MB (Q4) | MIT | 700–1000 ms | 40–70 ms | Spell + punctuation correction | BART-base. MIT license (FOSS-friendly). Proof-of-concept; noted to produce artifacts. Better than raw T5-small on spelling. Also slow on CPU. |

**Tier 1 Summary**: Non-LLM tools (hunspell, Nuspell, symspellpy) achieve <5 ms and are sub-millisecond in practice. ML-based spell checkers (T5-small variants, BytT5) exceed 50ms on CPU—too slow for keystroke level. **Recommendation**: Use Nuspell for Fast Tier; it's the fastest dictionary-based option with proven accuracy.

---

## Tier 2: Mid (Context-Aware Grammar Correction)

**Use Case**: User-triggered correction (button click, right-click menu). Target: <200ms on RTX 3060.  
**Scope**: Grammar errors (subject-verb agreement, tense, articles), word-choice clarity, punctuation in context.

| Model | Size (params) | Tier | License | Latency N6000 CPU (est.) | Latency RTX 3060 (est.) | Capabilities | Notes |
|-------|---------------|------|---------|--------------------------|--------------------------|--------------|-------|
| **Unbabel/gec-t5_small** | 60 M | GGUF → ~20 MB (Q4) | Apache 2.0 | 300–500 ms | 25–40 ms | Grammatical error correction (GEC), multilingual | T5-small fine-tuned on GEC datasets. Apache 2.0 license. Lightweight. Limited context window (~512 tokens). |
| **AventIQ-AI/T5-small-grammar-correction** | 60 M | GGUF → ~20 MB (Q4) | Not declared¹ | 300–500 ms | 25–40 ms | Grammar correction on JFLEG dataset | T5-small, FP16 quantized. BLEU 0.8888. No explicit license stated; assume CC-BY or similar. Fast on GPU. |
| **vennify/t5-base-grammar-correction** | 220 M | GGUF → ~70 MB (Q4) | CC-BY-NC-SA-4.0 | 1500–2500 ms | 80–120 ms | Grammar correction, beam search (5 beams) | T5-base; larger context. **Commercial use restricted** (NC clause). Slower than t5-small but higher quality. Requires `grammar: ` prefix. |
| **pszemraj/grammar-synthesis-small** | 77 M | GGUF → ~25 MB (Q4) | Apache 2.0 | 350–600 ms | 30–50 ms | Single-shot grammar correction, semantic preservation | Based on T5-small. Apache 2.0 (FOSS-friendly). Work-in-progress; verify outputs. Designed to avoid over-correction. |
| **visheratin/t5-efficient-tiny-grammar-correction** | ~35 M | GGUF → ~12 MB (Q4) | Not declared² | 200–350 ms | 18–28 ms | Grammar correction on C4_200M subset | T5-Efficient-TINY. Smallest grammar model. License not stated. Minimal context. Fastest T5 variant. |
| **Qwen2.5-0.5B-Instruct** | 494 M | GGUF Q4_K_M → ~180 MB | Apache 2.0 | 2000–4000 ms | 120–180 ms | Grammar via instruction; also general chat | Instruction-tuned LLM. Prompt: `"Fix grammar: [text]"`. Handles longer context (4K tokens). Slower than T5 but more flexible. Apache 2.0. Can provide explanations. |
| **Llama-3.2-1B-Instruct** | 1 B | GGUF Q4_K_M → ~650 MB | Llama 2 License (research use) | 4000–7000 ms | 200–300 ms | Grammar + general reasoning, instruction-tuned | 1B parameters. Slower on CPU (>200ms target on RTX). Good on GPU but slightly exceeds mid-tier latency if not optimized. Better reasoning than Qwen 0.5B. |
| **SmolLM2-1.7B-Instruct** | 1.7 B | GGUF Q4_K_M → ~650 MB | MIT | 6000–10000 ms | 250–350 ms | Grammar, text rewriting, summarization, function calls | 1.7B parameters. MIT license (FOSS-friendly). Exceeds 200ms target on RTX; acceptable for user-triggered (non-critical). Good for tone/style tasks too. |
| **Phi-3.5-mini-Instruct** | 3.8 B | GGUF Q4_K_M → ~1.4 GB | MIT | 10000+ ms (OOM likely) | 400–600 ms | Instruction-tuned reasoning, grammar, writing tasks | 3.8B. MIT license. Exceeds RTX 3060 VRAM if not aggressively quantized (would need Q3). Exceeds 200ms mid-tier target. Better for smart tier. |
| **grammarly/coedit-large** | 770 M | GGUF → ~250 MB (Q4, if supported) | CC-BY-NC-4.0 | 2500–4000 ms | 150–200 ms | Grammar, style, tone via task-specific instruction | Fine-tuned FLAN-T5-large. **Commercial use restricted** (NC clause). High quality but license incompatible with FOSS distribution. Hits mid-tier latency on RTX. |

**Tier 2 Summary**:
- **FOSS-compatible sub-200ms options**: Unbabel/gec-t5_small (25–40 ms), pszemraj/grammar-synthesis-small (30–50 ms), visheratin/t5-efficient-tiny (18–28 ms).
- **General instruction models**: Qwen2.5-0.5B (120–180 ms), SmolLM2-1.7B (250–350 ms, slightly over budget but usable).
- **License issues**: vennify (CC-BY-NC-SA), coedit-large (CC-BY-NC) are restricted; not suitable for FOSS/commercial repackaging.
- **Recommendation**: Lead with **Unbabel/gec-t5_small** (Apache 2.0, 25–40 ms, proven GEC) for mid-tier baseline. Reserve **Qwen2.5-0.5B** as fallback for users needing longer context or explanations (still <200ms on RTX).

---

## Tier 3: Smart (Tone/Voice Suggestions)

**Use Case**: User-triggered rewrites (button or menu). Target: <500ms on RTX 3060.  
**Scope**: Detect overly formal/casual language, suggest simpler or more professional phrasing, style rewrite (not just error fixing).

| Model | Size (params) | Tier | License | Latency N6000 CPU (est.) | Latency RTX 3060 (est.) | Capabilities | Notes |
|-------|---------------|------|---------|--------------------------|--------------------------|--------------|-------|
| **Qwen2.5-3B-Instruct** | 3 B | GGUF Q4_K_M → ~1.1 GB | Apache 2.0 | 15000–25000 ms | 400–550 ms | Grammar, tone detection, style rewrite, reasoning | Instruction-tuned. Handles complex tone prompts. Apache 2.0. Fits VRAM on RTX 3060 at Q4. Acceptable latency for non-critical user-triggered task. |
| **Llama-3.2-3B-Instruct** | 3 B | GGUF Q4_K_M → ~1.1 GB | Llama 2 (research) | 15000–25000 ms | 400–550 ms | Grammar, reasoning, tone via instruction. Multilingual. | 3B parameters. Llama 2 license (research-use restriction). Matches Qwen2.5-3B latency. Slightly better reasoning than Qwen. |
| **Phi-3.5-mini-Instruct** | 3.8 B | GGUF Q3 → ~1.3 GB (Q3 for VRAM) | MIT | 20000–30000 ms | 450–650 ms | Instruction-tuned, reasoning, writing tasks, tone | MIT license (FOSS-friendly). Slightly larger (3.8B). May require Q3 quantization on RTX 3060 for safety. Latency varies with quantization level. |
| **grammarly/coedit-xl** | 3 B | GGUF → ~1.0 GB (Q4, if supported) | CC-BY-NC-4.0 | 15000–25000 ms | 400–600 ms | Grammar, style, tone, task-specific instruction tuning | FLAN-T5-XL variant. Higher quality than coedit-large. **Commercial use restricted** (NC clause). License incompatible with FOSS. Excellent tone capabilities but unavailable for redistribution. |
| **SmolLM2-1.7B-Instruct** | 1.7 B | GGUF Q4_K_M → ~650 MB | MIT | 6000–10000 ms | 250–350 ms | Rewriting, tone, summarization. MIT license. | Fits well under 500ms. MIT license (FOSS-friendly). Can handle tone tasks; smaller than 3B but less context. Good compromise for constrained tier. |

**Tier 3 Summary**:
- **FOSS-compatible**: Qwen2.5-3B (Apache 2.0, 400–550 ms), Llama-3.2-3B (research license, check user's intent), Phi-3.5-mini (MIT, 450–650 ms at Q3).
- **Restricted**: coedit-xl (CC-BY-NC-4.0, high quality but not redistributable).
- **Tone definition**: Tone/voice in this context means detecting register (formal vs. casual) and suggesting rewrites, not just grammar fixes. This requires semantic understanding—dictionary tools and small T5 models are insufficient.
- **Recommendation**: **Qwen2.5-3B** (Apache 2.0, hits <500ms, instruction-tuned for tone tasks, widely available GGUF quantizations). Fall back to **SmolLM2-1.7B** if VRAM is tight on target hardware.

---

## Synthesis: Can One Model Handle All Three Tiers?

**Question**: Can a single model achieve spell-check (Fast, <50ms), grammar correction (Mid, <200ms), and tone rewrite (Smart, <500ms)?

**Analysis**:

1. **Speed impossibility**: A model fast enough for spell-check (sub-50ms, keystroke-level) must be dictionary-based or extremely lightweight. No neural model can hit 50ms latency on CPU. The jump from spell-check (<50ms) to grammar correction (<200ms) is a 4× gap; filling it requires model inference.

2. **Architectural mismatch**:
   - **Fast tier** (Nuspell) is a lookup table, not a transformer.
   - **Mid tier** (Unbabel gec-t5_small, 60M params) is optimized for GEC, not tone detection.
   - **Smart tier** (Qwen2.5-3B, 3B params) is optimized for instruction following and reasoning, overkill for spell-check.

3. **VRAM/latency trade-off**: A 3B model (needed for tone) would take 3–5 seconds on CPU, making it unsuitable for keystroke-level work. A 60M model (suitable for grammar) cannot reason about tone and style.

4. **Conclusion**: **A tiered architecture is necessary and optimal**. Each tier serves a distinct use case with different latency requirements, and trying to unify them would bloat Fast tier (wasted VRAM on CPU) or cripple Smart tier (insufficient parameters for nuanced tone detection).

### Recommended Tiered Architecture

```
┌─────────────────────────────────────────────┐
│         Waldo Spells: Three-Tier Stack      │
├─────────────────────────────────────────────┤
│ FAST   (Keystroke)  │ Nuspell              │ <5 ms
│                     │ (Dictionary)          │
├─────────────────────────────────────────────┤
│ MID    (Click)      │ Unbabel/gec-t5_small │ 25–40 ms
│                     │ (60M, Apache 2.0)    │
├─────────────────────────────────────────────┤
│ SMART  (User-trig)  │ Qwen2.5-3B-Instruct  │ 400–550 ms
│                     │ (3B, Apache 2.0)     │
└─────────────────────────────────────────────┘
```

**Advantages**:
- Each model optimized for its latency target.
- FOSS licenses (Apache 2.0 / MIT) for all three tiers—no commercial restrictions.
- Fast tier (Nuspell) can run in parallel or preload without GPU.
- Mid tier fits in RTX 3060 VRAM at Q4 (20 MB + overhead ~100 MB).
- Smart tier fits RTX 3060 at Q4_K_M (1.1 GB + overhead ~1.5 GB total, leaving ~10.5 GB for browser/OS).
- Graceful degradation: keystroke → spell, click → grammar, user menu → tone. No model blocking user.

---

## Hardware Assumptions

### Dev Machine (Pentium N6000, 4GB RAM, CPU-only)
- **Fast tier** (Nuspell): <1 ms, no memory pressure.
- **Mid tier** (Unbabel gec-t5_small): 300–500 ms, ~100 MB (dict + model loaded). Acceptable for non-keystroke scenarios.
- **Smart tier** (Qwen2.5-3B): 15–25 seconds, would cause OOM or thrashing. Not viable on dev machine in real-time. Recommend: precompute or skip on CPU.

### Target Machine (RTX 3060 12GB)
- **Fast tier** (Nuspell): <1 ms, ~50 MB.
- **Mid tier** (Unbabel gec-t5_small): 25–40 ms, ~120 MB (GPU VRAM).
- **Smart tier** (Qwen2.5-3B Q4_K_M): 400–550 ms, ~1.5 GB (GPU VRAM). Total stack: ~2 GB, leaving ~10 GB for browser/OS (safe margin).

**Latency Estimates Source**: Model size heuristics + published benchmarks on similar hardware (RTX 3060 inference speeds from community reports averaging 25–45 tok/s for 1B models, 10–15 tok/s for 3B models). Spell-check (<1 ms) from [Nuspell GitHub](https://github.com/nuspell/nuspell). Grammar correction T5-small (25–40 ms) extrapolated from RTX 3060 inference speeds at 300–500 tokens/sec throughput.

---

## Model Licensing Summary

| Tier | Model | License | FOSS-OK | Commercial-OK | Redistribution-OK |
|------|-------|---------|---------|---------------|-------------------|
| Fast | Nuspell | MPL-2.0 | ✓ | ✓ | ✓ |
| Mid | Unbabel/gec-t5_small | Apache 2.0 | ✓ | ✓ | ✓ |
| Smart | Qwen2.5-3B-Instruct | Apache 2.0 | ✓ | ✓ | ✓ |
| *Alt Mid* | vennify/t5-base | CC-BY-NC-SA-4.0 | ✓ | ✗ | ✗ (requires attribution, non-commercial) |
| *Alt Mid* | grammarly/coedit-large | CC-BY-NC-4.0 | ✓ | ✗ | ✗ (non-commercial restriction) |
| *Alt Smart* | Phi-3.5-mini-Instruct | MIT | ✓ | ✓ | ✓ |
| *Alt Smart* | SmolLM2-1.7B-Instruct | MIT | ✓ | ✓ | ✓ |

**Key Constraint**: Waldo Spells must support both FOSS (free tier) and commercial Waldo Pro/Rack deployments. Licensed models with NC (non-commercial) or SA (share-alike) clauses are acceptable for FOSS personal use but incompatible with Waldo Pro's business model. **Primary recommendation prioritizes Apache 2.0 / MIT models.**

---

## Quantization Notes

- **GGUF Q4_K_M** (recommended for all tiers): 4-bit quantization with custom KQV projection. Balances quality and file size. Supported by llama.cpp.
- **T5 models** (Unbabel, pszemraj, etc.): Encoder-decoder architecture. GGUF conversion is supported as of llama.cpp PR #8055 (2024). Q5_K_M or larger recommended for T5 due to sensitivity to quantization.
- **Nuspell**: Not quantizable (dictionary-based tool, not a neural network).
- **File sizes** (Q4_K_M):
  - T5-small (60M): ~20 MB
  - T5-base (220M): ~70 MB
  - Qwen2.5-0.5B: ~180 MB
  - Qwen2.5-3B: ~1.1 GB
  - SmolLM2-1.7B: ~650 MB
  - Llama-3.2-1B: ~650 MB
  - Phi-3.5-mini (3.8B): ~1.4 GB at Q4_K_M, ~1.3 GB at Q3 (if needed for VRAM)

---

## Next Steps (Tasks 2 & 3)

This matrix feeds into:

1. **Task 2: Build minimal llama.cpp / vllm wrapper executable**
   - Integrate Nuspell (Fast tier) via Python `hunspell` or `nuspell` bindings.
   - Load Unbabel/gec-t5_small (Mid tier) via llama.cpp with T5 encoder-decoder support.
   - Load Qwen2.5-3B (Smart tier) via llama.cpp with instruction prompt template.
   - Expose HTTP/IPC API for browser extension to call each tier independently.

2. **Task 3: Build instrumented test harness (context + latency + accuracy)**
   - Measure latency of each tier on target hardware (RTX 3060).
   - Test on dev hardware (N6000 CPU) to confirm viability or identify fallbacks.
   - Accuracy: benchmark each model on public GEC datasets (JFLEG, CoNLL-2014) and custom Waldo test cases.
   - Context: measure handling of long documents (e.g., forum posts, emails with quoted history).
   - Automation: log all results to `capability_matrix_benchmarks.md` for future reference.

---

## Data Sources

- [Nuspell GitHub Benchmarks](https://github.com/nuspell/spell-checkers-comparison)
- [Unbabel/gec-t5_small Model Card](https://huggingface.co/Unbabel/gec-t5_small)
- [AventIQ-AI/T5-small-grammar-correction](https://huggingface.co/AventIQ-AI/T5-small-grammar-correction)
- [pszemraj/grammar-synthesis-small](https://huggingface.co/pszemraj/grammar-synthesis-small)
- [Qwen2.5-3B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF)
- [Qwen2.5-0.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)
- [Llama-3.2-1B-Instruct-GGUF (bartowski)](https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF)
- [Llama-3.2-3B-Instruct-GGUF (bartowski)](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF)
- [SmolLM2-1.7B-Instruct-GGUF](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF)
- [Phi-3.5-mini-Instruct-GGUF (bartowski)](https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF)
- [grammarly/coedit-large](https://huggingface.co/grammarly/coedit-large)
- [grammarly/coedit-xl](https://huggingface.co/grammarly/coedit-xl)
- [vennify/t5-base-grammar-correction](https://huggingface.co/vennify/t5-base-grammar-correction)
- [RTX 3060 LLM Performance Benchmarks (CraftRigs)](https://craftrigs.com/guides/best-llm-rtx-3060-12gb-vram-2026/)
- [LocalLLM Speed Comparison (Ajit Singh)](https://singhajit.com/llm-inference-speed-comparison/)

---

## Footnotes

¹ **AventIQ-AI/T5-small-grammar-correction**: Model card does not list an explicit license. Assumption: CC-BY or CC-BY-NC (common for academic/community fine-tunes). Verify before redistribution.

² **visheratin/t5-efficient-tiny-grammar-correction**: License not declared on model card. Assume default HuggingFace license (CC-BY-NC-4.0) or contact author for clarity. Suitable for research/evaluation, may require explicit permission for commercial use.
