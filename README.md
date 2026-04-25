# Waldo Spells

Context-aware spelling and word-choice checker. Runs locally — no text leaves your machine.
Firefox extension + 3-tier local backend.

> **Status: v0.2.0 alpha** — Fast tier (spell-check) end-to-end and working.
> Mid (T5/gec-t5_small) and Smart (Qwen2.5-3B) tiers are wired but require model downloads (see below).

---

## What it does

Watches text inputs in Firefox and flags spelling errors with a tooltip on blur.
Designed to extend to contextually wrong words (then/than, affect/effect) once the LLM tiers are loaded.

```
Firefox extension ──HTTP──▶ wrapper/server.py ──▶ tier_router ──▶ Fast | Mid | Smart
```

| Tier | Backend | Latency | Status |
|------|---------|---------|--------|
| Fast | pyenchant over system hunspell | < 1 ms | Working |
| Mid | gec-t5_small via CTranslate2 INT8 | 6–10 s | Wired, model not bundled |
| Smart | Qwen2.5-3B-Q4_K_M via llama.cpp | 30–90 s | Wired, model not bundled |

---

## Install and run

**Requirements (Fast tier):**

```bash
sudo apt install hunspell hunspell-en-us
pip install pyenchant
```

**Start the server:**

```bash
python3 -m wrapper.server
# Listening on http://127.0.0.1:8765
```

**Load the extension in Firefox:**

1. Open `about:debugging`
2. Click **This Firefox** → **Load Temporary Add-on**
3. Select `extension/manifest.json`

**Test it:**

Type `I recieved teh package` in any text input → tooltip appears on blur showing corrections.

---

## Optional: Mid and Smart tiers

**Mid tier (gec-t5_small, ~300 MB):**

```bash
pip install ctranslate2 transformers sentencepiece
python3 wrapper/t5_converter.py  # downloads and converts model to CTranslate2 INT8
```

**Smart tier (Qwen2.5-3B, ~2 GB GGUF):**

```bash
# Download Qwen2.5-3B-Q4_K_M.gguf from HuggingFace and place in models/
# Install llama.cpp and start llama-server on port 8080
python3 -m wrapper.server  # tier_router auto-detects llama-server
```

---

## Project layout

```
wrapper/      Python HTTP server + 3-tier backends (Fast/Mid/Smart) + tests
extension/    Firefox MV3 extension (content script, background, popup)
harness/      Test corpus (42 items), benchmark runner, metrics, reports
research/     Model research notes and T5/GGUF investigation reports
```

---

## Benchmark results

Fast tier baseline from `harness/results/analysis.md`:

- Latency: p50 = 0.93 ms, p95 = 2.31 ms (passes the 200 ms target)
- Precision: 0.750 · Recall: 0.333 · F1: 0.462
- False positive rate: 0.273 (on 32 test items — corpus too small for 6-sigma validation)
- Mid and Smart tier benchmarks pending model downloads

---

## Roadmap

- **v0.3.0** — `contenteditable` support (Notion, Gmail), per-site enable/disable
- **v1.0.0** — Mozilla AMO publish, homophone detection via Mid/Smart tiers

---

## License

MIT — see [LICENSE](LICENSE).
