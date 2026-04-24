# Grammar Checker — Project Context

Firefox/Zen Browser extension. Context-aware grammar/word-choice checker using masked language
modeling — "Grammarly but private." Target: GitHub FOSS publish.

## Planning and Roadmap
See `~/Documents/Waldo/Wiki/projects/grammar-checker/roadmap.md` for full roadmap, sprint state,
and architecture decisions. The Wiki is the source of truth for all planning — this file is
identity + conventions only.

## Architecture
- **Manifest V3**, Firefox WebExtensions API
- Content script watches text inputs, streams text for analysis
- Analysis backend: any OpenAI-compatible `POST /v1/chat/completions` endpoint
  (OpenRouter/Claude for PoC → local DistilBERT ONNX or Ollama → Waldo endpoint eventually)
- Inline highlighting: DOM mutation to flag contextually wrong words without blocking input

## Backend Strategy
- **PoC**: OpenRouter or Claude API — call with masked-style prompt, get top-K suggestions back
- **v1**: Local Ollama with a small masked LM (DistilBERT ~66MB, ~50-100ms/sentence on N6000)
- **v2**: ONNX in-browser (no server required)
- All API input is OpenAI-compatible — swap endpoint URL, zero frontend changes

## Commit Convention
- Format: `vX.Y.Z - Short description`
- Independent git repo — not part of WaldoAI versioning
- Co-authored commits: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

## Shared-State Discipline
After any significant task or session:
1. Append to `~/Documents/Waldo/Wiki/log.md`:
   `## [YYYY-MM-DD] claude | action | grammar-checker — subject`
2. Update `Wiki/projects/grammar-checker/roadmap.md` if sprint state changed
3. Update `Wiki/sprint.md` task status (⚪ → 🔵 when starting, 🔵 → ✅ when done)
4. Update `Wiki/project-index.md` `updated:` date if any source-of-truth file moved
