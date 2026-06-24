"""Smart tier: Qwen2.5-3B-Instruct via llama-server (llama.cpp).

Setup:
  1. Build llama.cpp and place llama-server in PATH (or set LLAMA_SERVER_BIN).
  2. Download Qwen2.5-3B-Instruct-Q4_K_M.gguf from HuggingFace and set LLAMA_MODEL_PATH.
     e.g.: huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF \
               Qwen2.5-3B-Instruct-Q4_K_M.gguf --local-dir ~/models/
  3. Expected latency on Pentium N6000 (CPU-only): 30–90 seconds per sentence.
     Expected RAM: ~2.5–3 GB resident.

Environment variables:
  LLAMA_MODEL_PATH   — absolute path to .gguf file (required)
  LLAMA_SERVER_BIN   — path to llama-server binary (default: search PATH)
  LLAMA_SERVER_PORT  — port for llama-server (default: 8080)
  LLAMA_SERVER_HOST  — host for llama-server (default: 127.0.0.1)
"""

import atexit
import json
import os
import re
import shutil
import subprocess
import time
from typing import List, Optional

import requests

from logging_utils import WaldoSpellsLogger
from protocol import Correction

logger = WaldoSpellsLogger("llama_backend")

_server_process: Optional[subprocess.Popen] = None


def _server_bin() -> Optional[str]:
    custom = os.environ.get("LLAMA_SERVER_BIN")
    if custom:
        return custom if os.path.isfile(custom) else None
    return shutil.which("llama-server")


def _model_path() -> Optional[str]:
    path = os.environ.get("LLAMA_MODEL_PATH")
    if path and os.path.isfile(path) and os.access(path, os.R_OK):
        return path
    return None


def _host() -> str:
    return os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")


def _port() -> int:
    return int(os.environ.get("LLAMA_SERVER_PORT", "8081"))


def is_available() -> bool:
    """True only when both LLAMA_MODEL_PATH points to a readable file and llama-server is in PATH."""
    model = _model_path()
    if not model:
        path_val = os.environ.get("LLAMA_MODEL_PATH", "(not set)")
        print(
            f"[llama_backend] unavailable: LLAMA_MODEL_PATH={path_val} not found or unreadable",
            flush=True,
        )
        return False
    binary = _server_bin()
    if not binary:
        print(
            "[llama_backend] unavailable: llama-server binary not found in PATH or LLAMA_SERVER_BIN",
            flush=True,
        )
        return False
    return True


def _start_server() -> None:
    """Start llama-server if not already running. Blocks until /health returns 200."""
    global _server_process
    if _server_process is not None and _server_process.poll() is None:
        return  # Already running

    binary = _server_bin()
    model = _model_path()
    host = _host()
    port = _port()

    cmd = [
        binary,
        "-m",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "-c",
        "2048",
        "--n-gpu-layers",
        "0",
    ]
    logger.info(f"Starting llama-server: {' '.join(str(c) for c in cmd if c)}")
    _server_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(_stop_server)

    # Wait until healthy
    health_url = f"http://{host}:{port}/health"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            r = requests.get(health_url, timeout=2)
            if r.status_code == 200:
                return
        except requests.exceptions.RequestException:
            logger.error("llama-server health poll failed; retrying", exc_info=True)
        if _server_process.poll() is not None:
            raise RuntimeError("llama-server exited unexpectedly during startup")
        time.sleep(1)

    _stop_server()
    raise RuntimeError("llama-server did not become healthy within 60s")


def _stop_server() -> None:
    global _server_process
    if _server_process is not None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()
        _server_process = None


_SYSTEM_PROMPT = """\
You are a grammar correction tool. Identify grammatical errors in the text.
Return ONLY a valid JSON object — no prose, no markdown, no extra fields.

Output format (follow this exactly, including bracket and brace order):
{"corrections": [{"original": "wrong word or phrase", "suggestion": "corrected form"}]}

Example with one correction:
Input: "I should of gone earlier."
Output: {"corrections": [{"original": "of", "suggestion": "have"}]}

Example with no errors:
Input: "She went to the store."
Output: {"corrections": []}

Rules:
- Use ONLY square brackets [ ] to delimit the "corrections" array; NEVER use round parentheses ( ) for arrays or structural elements.
- The array MUST be opened by [ immediately after the colon and closed by ] immediately before the final }.
- Each item in the array must be closed with } before the next , or ]
- The array must be closed with ] before the outer }
- Bad example to avoid: {"corrections": [)}  or {"corrections": [...])}  -- wrong closer.
- Preserve the author's meaning. Do not paraphrase or rewrite. Flag only clear errors."""


def _parse_json_with_repair(raw: str) -> dict:
    """Parse JSON from model output, applying bracket/brace repair if needed.

    Qwen2.5-3B can emit malformed JSON such as extra closing braces (`}}]`),
    missing closers, truncation, junk, or mixed brackets/parens (e.g. [) or })
    in place of [] / }]. Apply targeted repairs before raising so the harness
    sees corrections instead of silent drop on "All repair passes failed".

    Repair passes (applied in order until one succeeds):
      1. Direct parse — no repair needed.
      2. Normalize parens/brackets: fix [) → [], }) → }], ) } → ] }  (mixed [) cases).
      3. Replace `}}]` with `}]` (extra closing brace before array close).
      4. Replace `}(...)$` pattern with `}]}` (missing array close bracket).
      5. Truncated array: append outer `}` if ends with `]`.
      6. Strip junk after last `}` (also re-apply paren+brace repairs).
    """
    # Pass 1: try raw parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    repaired = raw

    # Pass 2: normalize parens used as brackets/closers (qwen2.5-3b [) / }) slips)
    # Targeted structural patterns only (bare } ) etc never appear inside "strings")
    # Covers reported: {"corrections": [)}  and {"corrections": [{...}])}
    repaired = re.sub(r"\}\s*\)", "}]", repaired)
    repaired = re.sub(r"\[\s*\)", "[]", repaired)
    repaired = re.sub(r"\)\s*\}", "]}", repaired)
    try:
        result = json.loads(repaired)
        logger.debug("[llama_backend] JSON repaired via pass 2 (paren→bracket normalize [)→[] })→}])")
        return result
    except json.JSONDecodeError:
        pass

    # Pass 3: replace `}}+]` → `}]`  (one or more extra closing braces before array close)
    repaired = re.sub(r"\}(\}+)\]", "}]", repaired)
    try:
        result = json.loads(repaired)
        logger.debug("[llama_backend] JSON repaired via pass 3 (}}] → }])")
        return result
    except json.JSONDecodeError:
        pass

    # Pass 4: missing `]` — model emits `}}}` instead of `}]}`.
    # Pattern: last array item ends with `}}+` without a `]` before outer close.
    repaired4 = re.sub(r"\}(\}+)$", "}]}", repaired.rstrip())
    try:
        result = json.loads(repaired4)
        logger.debug("[llama_backend] JSON repaired via pass 4 (}}+ → }]})")
        return result
    except json.JSONDecodeError:
        pass

    # Pass 5: truncated — missing closing `}` after array; append it
    repaired5 = repaired.rstrip()
    if repaired5.endswith("]"):
        candidate = repaired5 + "}"
        try:
            result = json.loads(candidate)
            logger.debug("[llama_backend] JSON repaired via pass 5 (appended outer })")
            return result
        except json.JSONDecodeError:
            pass

    # Pass 6: strip junk after the last valid `}` and retry
    last_brace = raw.rfind("}")
    if last_brace != -1:
        candidate = raw[: last_brace + 1]
        # Apply paren-normalize + brace repairs on truncated string too
        candidate = re.sub(r"\}\s*\)", "}]", candidate)
        candidate = re.sub(r"\[\s*\)", "[]", candidate)
        candidate = re.sub(r"\}(\}+)\]", "}]", candidate)
        try:
            result = json.loads(candidate)
            logger.debug(
                "[llama_backend] JSON repaired via pass 6 (truncated at last })"
            )
            return result
        except json.JSONDecodeError:
            pass

    # All passes failed — let the caller handle it
    raise json.JSONDecodeError("All repair passes failed", raw, 0)


def correct(text: str, context_hint: Optional[str] = None) -> List[Correction]:
    """
    Grammar correction via Qwen2.5-3B-Instruct through llama-server.

    Raises RuntimeError if not available (is_available() is False).
    Returns empty list if model finds no errors or JSON parsing fails.
    """
    if not is_available():
        missing = []
        if not _model_path():
            missing.append("LLAMA_MODEL_PATH not set or file not found")
        if not _server_bin():
            missing.append("llama-server binary not found")
        raise RuntimeError(
            "Smart tier unavailable: " + "; ".join(missing) + "\n"
            "Install: build llama.cpp (https://github.com/ggerganov/llama.cpp) and set LLAMA_MODEL_PATH."
        )

    _start_server()

    user_content = text
    if context_hint:
        user_content = f"[Context: {context_hint}]\n{text}"

    payload = {
        "model": "qwen",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }

    host = _host()
    port = _port()
    url = f"http://{host}:{port}/v1/chat/completions"

    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        _stop_server()
        logger.error("llama-server timed out after 120s", exc_info=True)
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"llama-server request failed: {e}", exc_info=True)
        return []

    try:
        body = resp.json()
        raw = body["choices"][0]["message"]["content"]
        data = _parse_json_with_repair(raw)
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as e:
        logger.error(
            f"Failed to parse llama-server response: {e} — raw: {resp.text[:200]}",
            exc_info=True,
        )
        return []

    corrections: List[Correction] = []
    seen_starts: set = set()
    for item in data.get("corrections", []):
        try:
            original = item["original"]
            suggestion = item["suggestion"]
            if not original or not suggestion:
                continue
            # LLMs report unreliable offsets — find the span ourselves.
            start = text.find(original)
            if start == -1:
                # Try case-insensitive match
                lower_text = text.lower()
                lower_orig = original.lower()
                start = lower_text.find(lower_orig)
                if start == -1:
                    continue
                original = text[start : start + len(original)]
            if start in seen_starts:
                continue
            seen_starts.add(start)
            end = start + len(original)
            corrections.append(
                Correction(
                    start=start,
                    end=end,
                    original=original,
                    suggestions=[suggestion],
                    type="grammar",
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return corrections
