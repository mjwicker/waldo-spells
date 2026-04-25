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
import logging
import os
import shutil
import subprocess
import time
from typing import List, Optional

import requests

from protocol import Correction

logger = logging.getLogger(__name__)

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
    return int(os.environ.get("LLAMA_SERVER_PORT", "8080"))


def is_available() -> bool:
    """True only when both LLAMA_MODEL_PATH points to a readable file and llama-server is in PATH."""
    model = _model_path()
    if not model:
        path_val = os.environ.get("LLAMA_MODEL_PATH", "(not set)")
        print(f"[llama_backend] unavailable: LLAMA_MODEL_PATH={path_val} not found or unreadable", flush=True)
        return False
    binary = _server_bin()
    if not binary:
        print("[llama_backend] unavailable: llama-server binary not found in PATH or LLAMA_SERVER_BIN", flush=True)
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
        "-m", model,
        "--host", host,
        "--port", str(port),
        "-c", "2048",
        "--n-gpu-layers", "0",
    ]
    logger.info("Starting llama-server: %s", " ".join(cmd))
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
            pass
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
Return ONLY a JSON object with this exact schema — no prose, no markdown:
{"corrections": [{"original": "wrong word or phrase", "suggestion": "corrected form", \
"offset": <int char offset in input>, "length": <int char length of original>, \
"rule": "short rule label e.g. then/than or affect/effect"}]}
If there are no errors, return: {"corrections": []}
Preserve the author's meaning. Do not paraphrase or rewrite. Flag only clear errors."""


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
        "max_tokens": 512,
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
        logger.error("llama-server timed out after 120s")
        return []
    except requests.exceptions.RequestException as e:
        logger.error("llama-server request failed: %s", e)
        return []

    try:
        body = resp.json()
        raw = body["choices"][0]["message"]["content"]
        data = json.loads(raw)
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse llama-server response: %s — raw: %.200s", e, resp.text)
        return []

    corrections: List[Correction] = []
    for item in data.get("corrections", []):
        try:
            start = int(item["offset"])
            length = int(item["length"])
            end = start + length
            if start < 0 or end > len(text):
                continue
            if text[start:end] != item.get("original", ""):
                continue
            corrections.append(Correction(
                start=start,
                end=end,
                original=item["original"],
                suggestions=[item["suggestion"]],
                type="grammar",
            ))
        except (KeyError, TypeError, ValueError):
            continue

    return corrections
