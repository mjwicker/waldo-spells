#!/usr/bin/env python3
"""CLI entrypoint for grammar checker wrapper."""

import sys
import json
import argparse

from protocol import Request, Response, Correction
from tier_router import route


HELP_TEXT = """
Waldo Spells — Grammar & Spell-Check Wrapper

A local-first, tier-based spell and grammar checker.
Reads JSON line requests from stdin, writes JSON line responses to stdout.

USAGE:
    python main.py                  # Read requests from stdin
    python main.py --selftest       # Run a simple test and exit
    python main.py --help           # Show this help

REQUEST SCHEMA (one JSON object per line):
{
    "tier": "fast|better|smart",
    "text": "string",
    "context_hint": "string or null",
    "request_id": "string"
}

RESPONSE SCHEMA (one JSON object per line):
{
    "request_id": "string",
    "tier_used": "string",
    "corrections": [
        {
            "start": int,
            "end": int,
            "original": "string",
            "suggestions": ["string"],
            "type": "spelling|grammar|style"
        }
    ],
    "latency_ms": float,
    "error": "string or null"
}

TIER STATUS:
    - fast: Ready (Hunspell spell-check)
    - better: Stub (T5 GGUF, not yet verified)
    - smart: Stub (Qwen2.5-3B, not yet configured)

EXAMPLES:
    # Simple spell-check
    echo '{"tier":"fast","text":"Helo wrold","context_hint":null,"request_id":"1"}' | python main.py

    # Request unavailable tier (returns error)
    echo '{"tier":"smart","text":"Hello world","context_hint":null,"request_id":"2"}' | python main.py
"""


def main():
    parser = argparse.ArgumentParser(
        prog="waldo-spells-wrapper",
        description="Waldo Spells grammar checker wrapper",
        add_help=False,
    )
    parser.add_argument("--selftest", action="store_true", help="Run self-test")
    parser.add_argument("--help", action="store_true", help="Show help")

    args = parser.parse_args()

    if args.help:
        print(HELP_TEXT)
        sys.exit(0)

    if args.selftest:
        return selftest()

    # Main loop: read requests from stdin
    return stdin_loop()


def stdin_loop() -> int:
    """Read JSON line requests from stdin and write responses to stdout."""
    exit_code = 0

    for line_num, line in enumerate(sys.stdin, 1):
        line = line.rstrip("\n")

        if not line:
            # Skip empty lines
            continue

        request = None
        try:
            request = Request.from_json(line)
        except json.JSONDecodeError as e:
            # Parse error: return error response with a synthetic ID
            response = Response(
                request_id="error",
                tier_used="unknown",
                corrections=[],
                latency_ms=0.0,
                error=f"json_parse_error: {str(e)}",
            )
            print(response.to_json(), flush=True)
            exit_code = 1
            continue
        except Exception as e:
            # Other error: return error response
            response = Response(
                request_id=getattr(request, "request_id", "error"),
                tier_used="unknown",
                corrections=[],
                latency_ms=0.0,
                error=f"request_error: {str(e)}",
            )
            print(response.to_json(), flush=True)
            exit_code = 1
            continue

        # Route the request
        response = route(request)

        # Write response to stdout
        print(response.to_json(), flush=True)

    return exit_code


def selftest() -> int:
    """Run a simple self-test using the Fast tier."""
    print("Running self-test...", file=sys.stderr)

    # Test 1: Known misspelling
    test_request = Request(
        tier="fast",
        text="Helo wrold",
        context_hint=None,
        request_id="selftest-1",
    )

    response = route(test_request)
    print(f"Test 1 response: {response.to_json()}", file=sys.stderr)

    if response.error:
        print(f"ERROR: {response.error}", file=sys.stderr)
        return 1

    # Check that we got corrections
    if not response.corrections:
        print("WARNING: No corrections found for 'Helo wrold'", file=sys.stderr)
        return 1

    print(f"OK: Found {len(response.corrections)} corrections", file=sys.stderr)

    # Test 2: Correct text
    test_request2 = Request(
        tier="fast",
        text="Hello world",
        context_hint=None,
        request_id="selftest-2",
    )

    response2 = route(test_request2)
    print(f"Test 2 response: {response2.to_json()}", file=sys.stderr)

    if response2.corrections:
        print("WARNING: Found corrections for 'Hello world' (should be clean)", file=sys.stderr)
        return 1

    print("OK: Correct text passes clean", file=sys.stderr)

    print("Self-test PASSED", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
