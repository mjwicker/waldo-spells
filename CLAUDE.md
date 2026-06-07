# Waldo Spells — Project Context

Firefox/Zen Browser extension. Context-aware word-choice checker — flags contextually wrong 
words like "then/than", "affect/effect". Runs locally with zero cloud dependencies.
"Grammarly but private" — ships as a browser extension + local executable.

Target: GitHub FOSS publish. Portfolio piece demonstrating architecture reuse for future system apps
(Windows/Mac/Linux/iOS/Android).

## Planning and Roadmap
See `~/Documents/Waldo/Wiki/projects/grammar-checker/roadmap.md` for full roadmap, sprint state,
and architecture decisions. The Wiki is the source of truth for all planning — this file is
identity + conventions only.

## Architecture
- **Manifest V3**, Firefox WebExtensions API
- Content script watches text inputs, sends to local executable
- Analysis backend: local executable (llama.cpp binary + model) via `localhost:8000`
- OpenAI-compatible API interface — swaps to Waldo endpoint later with zero frontend changes
- Inline highlighting: DOM mutation to flag words without blocking input

## Backend Strategy (Post-Research)
- **v0.2**: Local executable (llama.cpp) + specific pretrained model (TBD after research phase)
- **v0.3**: Expanded input coverage (contenteditable, per-site enable/disable)
- **v1.0**: GitHub publish
- **Long-term**: System apps (Windows/Mac/Linux desktop + iOS/Android) reusing same analysis backend

## Commit Convention
- Format: `vX.Y.Z - Short description`
- Independent git repo — not part of WaldoAI versioning
- Co-authored commits: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

### Before Every Commit
1. Update `Wiki/projects/grammar-checker/changelog.md` — new entry at top (ADDED/FIXED/CHANGED/REMOVED + WHY); explain why changes were made, not just what changed
2. Stage changelog + code in one commit
3. Append to `Wiki/log.md`: `## [YYYY-MM-DD] claude | commit | waldo-spells — vX.Y.Z description`
4. Update `Wiki/sprint.md` task status if applicable (🔵 → ✅)

Do NOT report a task as complete until the changelog entry is staged.

## Shared-State Discipline
See parent `../.claude/CLAUDE.md` for shared-state rules. Also update `Wiki/projects/grammar-checker/roadmap.md` if sprint state changed.

## Key Claims

These are verifiable code-state facts. `doc-check` runs each command and reports VERIFIED or WRONG.

| Claim | Verify with |
|-------|-------------|
| Firefox extension directory exists | `test -d extension` |
| Extension manifest exists | `test -f extension/manifest.json` |
| Harness runner exists | `test -f harness/runner.py` |
| Harness metrics module exists | `test -f harness/metrics.py` |
| Models directory exists | `test -d models` |
| Wrapper (HTTP server layer) exists | `test -d wrapper` |
| Run script exists | `test -f run_harness.sh` |
