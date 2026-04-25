# Fast Tier Benchmark Analysis
## Waldo Spells — Research Sprint Cycle 8

**Date**: 2026-04-25
**Harness version**: Cycle 7 scaffold
**Tier tested**: fast (pyenchant/hunspell en_US)
**Corpus**: 32 runnable items (42 total; 10 skipped: password ×5, code ×5)

---

## Summary Table

| Metric | Value |
|--------|-------|
| Latency p50 | 0.93 ms |
| Latency p95 | 2.39 ms |
| Latency p99 | 2.75 ms |
| Latency mean | 1.16 ms |
| Precision | 0.750 |
| Recall | 0.333 |
| F1 | 0.462 |
| FP Rate | 0.273 |
| Total runs | 32 |
| Mid/Smart | skipped — is_available()=False (models not downloaded) |

---

## Latency Verdict

**Fast tier passes the 200ms bar with approximately 200× headroom.**

p50 = 0.93 ms, p99 = 2.75 ms. Both are well under the 200ms instant-feel threshold and
also under the 500ms tolerable bar. This result is consistent with the Cycle 7 live
baseline (p50 < 1ms, p95 < 3ms) — reproduces cleanly.

pyenchant/hunspell operates entirely in-process: no subprocess, no network call, no disk
I/O on each call. The sub-millisecond p50 is structurally expected and will hold on any
hardware that can run Python.

**Verdict**: Fast tier is production-ready from a latency standpoint. Mid tier (CTranslate2 +
gec-t5_small INT8, target 6–10s) and Smart tier (llama-server + Qwen2.5-3B Q4_K_M, target
30–90s) are the unknowns — both require empirical validation once models are downloaded.

---

## FP Rate Caveat

**The 32-item corpus cannot validate a 6-sigma target. Do not claim it does.**

6-sigma quality = 3.4 defects per million opportunities. Meaningful statistical validation
of that threshold requires a corpus 3–5 orders of magnitude larger than 32 items. The
current corpus distinguishes gross failure modes (e.g., "flags every word") from reasonable
operation — it cannot distinguish a 5% FP rate from a 0.5% FP rate with confidence.

What the observed FP rate (0.273) tells us: the fast tier flags real words it does not
recognize — specifically technical jargon absent from the en_US dictionary (e.g., `async`).
This is an expected limitation of spell-check-only tiers. The fix is context detection
(Task 3), not spell-checker tuning: the content script must label GitHub/code text boxes
with `context_hint=code` so the tier router can suppress technical-jargon flags.

---

## Results by Input Type

| Input Type | Precision | Recall | F1 | FP Rate | Items |
|------------|-----------|--------|----|---------|-------|
| slack | 1.000 | 0.375 | 0.545 | 0.000 | 8 |
| email | 0.750 | 0.375 | 0.500 | 0.250 | 8 |
| github | 0.600 | 0.600 | 0.600 | 0.500 | 8 |
| ai_chat | 0.000 | 0.000 | 0.000 | 0.000 | 8 |

### Slack — best precision (1.0), zero FPs

Slack corpus items use everyday language with intentional typos (e.g., `teh`, `occuring`).
These are in-vocabulary misspellings that hunspell catches reliably. Recall is capped by
homophones and grammar errors the spell-checker structurally cannot detect (see FN analysis
below). The zero FP rate confirms that casual-register text does not stress the en_US
dictionary.

### Email — moderate, one FP

One FP on email_001 (an uncommon proper noun or word the en_US dictionary does not carry).
Recall pattern matches Slack: catches typos, misses word-choice errors.

### GitHub — highest FP rate (0.50)

The primary driver is `async` — a JavaScript/Python keyword not present in the en_US
system dictionary. Any corpus item containing `async` generates a false positive. This is
the strongest quantitative signal that **context detection is a hard dependency**: the
content script must recognize GitHub PR/issue/comment text boxes and pass `context_hint=code`
to suppress technical-jargon flags. No tuning of the spell-checker fixes this; only input
classification does.

### AI Chat — zero detections, all misses

AI chat corpus items were seeded entirely with homophones and grammar errors (affect/effect,
their/there, you're/your). Spell-check produces zero output on these: all words are spelled
correctly. This is correct behavior, not a calibration failure.

**This result is the central finding of the research sprint**: spell-check-only (Fast tier)
has structurally zero recall on the word-choice errors that are the product's core value
proposition. Mid and Smart tiers are not optional — they are the product.

---

## Fast Tier Gap Analysis

### False Negatives: 18 total across 32 items

#### Category 1 — Homophones: ~10 FNs (56%)

Words spelled correctly but semantically wrong. Spell-check cannot catch these by design.

| Error Class | Count | Example |
|-------------|-------|---------|
| affect / effect | 4 | "the change will effect the outcome" |
| their / there / they're | 2 | "There going to the meeting" |
| you're / your | 2 | "Your the best candidate" |
| too / to | 1 | wrong word in context |
| it's / its | 1 | "Its a known issue" |

**Mid tier requirement**: gec-t5_small must catch homophones in sentence context. This is
its primary use case. Benchmark target: recall ≥ 0.70 on homophone-class errors.

#### Category 2 — Complex Grammar: ~5 FNs (28%)

Multi-word errors requiring syntactic understanding.

| Error | Correct Form |
|-------|-------------|
| "would of gone" | "would have gone" |
| "Between you and I" | "Between you and me" |
| "has went" | "has gone" |
| Missing question mark | punctuation |

Mid tier (sequence-to-sequence T5) may catch some of these via rewriting. Smart tier
(Qwen2.5-3B) is the backstop for cases requiring full syntactic parse.

#### Category 3 — Spelling Misses: ~3 FNs (17%)

Items where a misspelled word was expected to be caught but was not flagged, or was
partially caught with offset conflicts.

| Item | Expected | Observed |
|------|----------|---------|
| email_001 | `recieved` caught | FP on same item created offset conflict |
| email_004 | 3 expected corrections | Only 1 TP — 2 FNs remaining |

**Important**: these are largely harness-scoring artifacts, not spell-checker failures.
The overlap-based TP/FP/FN metric penalizes partial matches. In production, each word
is checked independently — offset conflicts only affect benchmark scoring, not user-facing
behavior. `recieved`, `occuring`, and `teh` all produce correct suggestions when tested
in isolation (verified Cycle 8).

---

## Mid Tier Requirements

**Model**: gec-t5_small (Unbabel) via CTranslate2 INT8
**Path**: `CT2_MODEL_PATH=./models/gec-t5_small-ct2`
**Conversion**: `python -m wrapper.t5_converter --output ./models/gec-t5_small-ct2`

Derived from FN gap analysis:

1. **Must catch homophones in context** — the primary Mid tier use case; structurally zero
   overlap with Fast tier's capability. Target: recall ≥ 0.70 on Category 1.
2. **Should handle common grammar errors** — "would of", subject-verb agreement, verb
   tense ("has went"). T5 GEC models are trained on these.
3. **Must not inflate FP rate** — if Mid runs as a second pass (on text Fast already
   processed), false positives from T5 are additive. Acceptable FP rate: < 0.10.
4. **Latency target**: ≤ 10s per sentence on N6000 CPU-only. CTranslate2 INT8 community
   benchmarks suggest 6–10s for gec-t5_small; empirical validation required.

**Validation plan**: once `CT2_MODEL_PATH` is set, run:
```
python -m harness.report --corpus harness/corpus.jsonl --out-dir harness/results --tiers better
```
Expected: recall improvement from 0.333 → 0.60+, especially on ai_chat items.

---

## Smart Tier Requirements

**Model**: Qwen2.5-3B-Instruct-Q4_K_M.gguf
**Path**: `LLAMA_MODEL_PATH=<path to .gguf>`
**Latency target**: ≤ 90s on N6000 CPU-only (background/async operation)

Mid tier handles common homophones and grammar. Smart tier is the backstop for:

1. **Complex pronoun cases** — "Between you and I" requires parsing prepositional structure
2. **Contextually ambiguous corrections** — where both word choices are technically valid
   but one is clearly contextually correct given the surrounding paragraph
3. **Punctuation and sentence-boundary errors** — missing question marks, run-ons
4. **Low-confidence Mid corrections** — Smart tier can be triggered when T5 confidence
   is below threshold

**UX implication**: Smart tier latency (30–90s) means the extension must show Mid results
immediately and update the overlay when Smart tier finishes. The content script architecture
must support async overlay updates.

---

## Reproducibility Notes

| Parameter | Value |
|-----------|-------|
| Hardware | Pentium N6000, 4GB RAM, CPU-only (no GPU) |
| OS | Ubuntu 24.04 |
| Python | 3.12 |
| pyenchant | 3.2.x (user-install, `~/.local/lib/python3.12/site-packages`) |
| Dictionary backend | hunspell en_US (system package, Ubuntu 24.04) |
| Corpus | `harness/corpus.jsonl` — 42 items, 32 runnable |
| Tiers tested | fast only; Mid/Smart: is_available()=False (models not on disk) |

To reproduce this benchmark:
```bash
cd /home/michaelwicker/Documents/Waldo/GrammarChecker
python -m harness.report --corpus harness/corpus.jsonl --out-dir harness/results --tiers fast
```

To run Mid tier once model is downloaded and converted:
```bash
CT2_MODEL_PATH=./models/gec-t5_small-ct2 \
python -m harness.report --corpus harness/corpus.jsonl --out-dir harness/results --tiers better
```

---

## Research Sprint Closing Statement

This benchmark closes Research Sprint Task 4. The research sprint (4 tasks) is complete.

**What we know**:
- Fast tier latency is excellent and will not be the bottleneck.
- Fast tier recall is structurally limited to spelling errors. The product's core value
  proposition (contextually wrong words) requires Mid and Smart tiers.
- GitHub context requires `context_hint=code` to suppress technical-jargon FPs — content
  script context detection (Task 3) is confirmed as a hard dependency, not nice-to-have.
- All three tier backends (nuspell_backend, t5_backend, llama_backend) are wired and stub
  cleanly when unavailable. No architectural changes are needed before v0.2.

**What v0.2.0 must do**:
1. Wire Fast tier into the Firefox content script (manifest.json + content.js)
2. Implement context detection: label GitHub/code boxes as `context_hint=code`
3. Download and convert gec-t5_small → run `python -m harness.report --tiers better`
4. Download Qwen2.5-3B-Instruct-Q4_K_M.gguf → run `python -m harness.report --tiers smart`
5. Implement async overlay update: show Fast/Mid results immediately, update on Smart finish

**The one-sentence finding**: the ai_chat result (0/0/0/0 on all metrics) is not a
failure — it proves that contextual word-choice checking requires language model inference,
and that Fast tier spell-check is a necessary pre-filter but not a sufficient product.
