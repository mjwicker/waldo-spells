# Waldo Spells Wrapper

Local-tier spell and grammar checking wrapper for the Waldo Spells browser extension.

## Purpose

A local-first, tier-dispatching grammar and spell checker that runs entirely on user hardware with zero cloud dependencies. Routes requests to spell-check (Fast), grammar correction (Better), or context-aware prose improvement (Smart) based on requested tier and available models.

## Installation

### System Dependencies

```bash
sudo apt install libhunspell-dev hunspell-en-us
```

### Python Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### CLI (stdin/stdout JSON line protocol)

```bash
echo '{"tier":"fast","text":"Helo wrold","context_hint":null,"request_id":"1"}' | python main.py
```

### JSON Schema

**Request** (one per line on stdin):
```json
{
    "tier": "fast|better|smart",
    "text": "string to check",
    "context_hint": "optional context string or null",
    "request_id": "string identifier"
}
```

**Response** (one per line on stdout):
```json
{
    "request_id": "string",
    "tier_used": "string",
    "corrections": [
        {
            "start": 0,
            "end": 4,
            "original": "Helo",
            "suggestions": ["Hello", "Held", "Help"],
            "type": "spelling"
        }
    ],
    "latency_ms": 12.34,
    "error": null
}
```

### Flags

- `--selftest`: Run a simple test (check "Helo wrold" and "Hello world"), print results to stderr, exit 0/1
- `--help`: Print usage and JSON schema

## Tier Status

| Tier | Model | Status | Notes |
|------|-------|--------|-------|
| **Fast** | Hunspell | Ready | Pure spell-check, no grammar. Used on N6000 (CPU-only, 4GB RAM). |
| **Better** | T5 GGUF | Stub | Grammar correction with local GGUF. Awaiting verification in research/t5_gguf_status.md. |
| **Smart** | Qwen2.5-3B | Stub | Context-aware prose improvement. Requires LLAMA_MODEL_PATH env var and sufficient GPU. |

## Error Handling

All errors are returned as JSON responses with `error` field set:
- `json_parse_error`: Malformed JSON input
- `request_error`: Missing or invalid fields
- `invalid_tier`: Tier name not in [fast, better, smart]
- `tier_unavailable`: Tier backend not installed/configured
- `backend_error`: Exception during correction

The wrapper never crashes; all exceptions are caught and returned as error responses.

## Architecture

```
main.py
  ├── stdin_loop(): Read JSON requests, route to tier_router
  ├── selftest(): Test Fast tier with fixtures
  └── tier_router.route(request)
       ├── nuspell_backend.py (Fast) — Hunspell spell-check
       ├── t5_backend.py (Better) — T5 GGUF stub
       └── llama_backend.py (Smart) — Qwen2.5-3B stub
```

Each backend exports:
- `is_available() -> bool`: Can this tier run?
- `correct(text, context_hint) -> list[Correction]`: Run corrections

## Testing

```bash
# Unit tests
pytest tests/

# Self-test
python main.py --selftest

# Manual test
echo '{"tier":"fast","text":"The qwick brown fox","context_hint":null,"request_id":"test1"}' | python main.py
```

## Future Work

- Smart/Better tier implementation (post-v0.1.0)
- HTTP server for OpenAI-compatible API (post-v0.1.0)
- Extended grammar rules beyond spell-check (post-v0.1.0)
