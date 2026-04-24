# Grammar Checker (Context-Aware)

A Firefox/Zen Browser extension that watches text inputs and flags words that don't fit their surrounding context — like Grammarly, but private and local.

> **Status:** Scaffold (v0.1.0). Structure in place. Backend not yet implemented.

---

## What It Does

- **Watches all text inputs** — `<textarea>`, `<input type="text">`, `contenteditable` elements
- **Flags contextually wrong words** — uses masked language modeling to detect words that are semantically out of place (e.g. "more then 10" — "then" vs "than")
- **Runs locally** — no text leaves your machine; model runs in the browser or via a local endpoint
- **API-configurable** — connect to any OpenAI-compatible endpoint for the language model backend

---

## Approach

A masked language model (e.g. DistilBERT ~66MB, or any instruction-tuned model via API) scores each word in context. Words where the original token isn't in the top-K predictions get flagged with an inline highlight.

For proof of concept: send text to **OpenRouter** or **local Ollama** via a `/v1/chat/completions` call.
For production: run DistilBERT ONNX in-browser or via a local inference server.

---

## Installation

Not yet available. Check back when v0.2.0 is tagged.

---

## License

MIT — open source, self-hostable, no cloud required.
