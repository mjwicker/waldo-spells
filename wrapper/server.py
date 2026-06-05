"""HTTP server wrapping the tier router. Start with: python -m wrapper.server"""

import argparse
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests as _requests

sys.path.insert(0, str(Path(__file__).parent))
import tier_router
from protocol import Request

# llama-server port for the Smart tier (Qwen2.5-3B-Instruct).
# Kept distinct from production 8080 so wrapper can proxy without a naming clash.
_LLAMA_PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8081"))
_LLAMA_HOST = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")

# Hardware gate: Smart tier requires at least this much RAM (bytes).
# 8 GB is the minimum for comfortable CPU-only inference with a 3B Q4 model.
_SMART_RAM_FLOOR_BYTES = 8 * 1024 * 1024 * 1024


def _system_ram_bytes() -> int:
    """Return total system RAM in bytes by reading /proc/meminfo."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    # MemTotal:      12345678 kB
                    kb = int(line.split()[1])
                    return kb * 1024
    except OSError:
        pass
    return 0


def _smart_hardware_ok() -> bool:
    """True when the host has enough RAM to run the Smart tier."""
    return _system_ram_bytes() >= _SMART_RAM_FLOOR_BYTES


def _llama_server_reachable() -> bool:
    """Ping llama-server health endpoint. Returns False if not running."""
    try:
        r = _requests.get(
            f"http://{_LLAMA_HOST}:{_LLAMA_PORT}/health", timeout=2
        )
        return r.status_code == 200
    except _requests.exceptions.RequestException:
        return False


class AnalyzeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress per-request noise

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path == "/smart_status":
            self._handle_smart_status()
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_smart_status(self) -> None:
        """Report whether the Smart tier is available.

        Response fields:
          available   — bool: True only when hardware gate passes AND llama-server
                        is reachable.  False means detection-only mode (Edge still fires).
          hardware_ok — bool: host meets the 8 GB RAM floor.
          server_ok   — bool: llama-server responded to /health on port 8081.
          message     — str: human-readable status shown in the toolbar.
        """
        hw_ok = _smart_hardware_ok()
        srv_ok = _llama_server_reachable() if hw_ok else False
        available = hw_ok and srv_ok

        if not hw_ok:
            msg = "Smart tier requires more RAM (8 GB minimum)"
        elif not srv_ok:
            msg = "Smart tier offline — start llama-server to enable rewrites"
        else:
            msg = "Smart tier ready"

        self._send_json(200, {
            "available": available,
            "hardware_ok": hw_ok,
            "server_ok": srv_ok,
            "message": msg,
        })

    def do_POST(self):
        if self.path == "/analyze":
            self._handle_analyze()
        elif self.path == "/smart":
            self._handle_smart()
        else:
            self._send_json(404, {"error": "not_found"})

    def _read_body(self) -> dict[str, object] | None:
        """Read and JSON-parse the request body.  Returns None on error (response already sent)."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid_json"})
            return None

    def _handle_analyze(self) -> None:
        body = self._read_body()
        if body is None:
            return

        text = body.get("text", "")
        tier = body.get("tier", "fast")
        context_hint = body.get("context_hint")

        if not isinstance(text, str) or not text.strip():
            self._send_json(200, {"corrections": [], "latency_ms": 0.0,
                                  "tier_used": tier, "error": None})
            return

        tier_str: str = tier if isinstance(tier, str) else "fast"
        hint_str: str | None = context_hint if isinstance(context_hint, str) else None

        request = Request(
            tier=tier_str,
            text=text,
            context_hint=hint_str,
            request_id=str(uuid.uuid4()),
        )
        response = tier_router.route(request)
        self._send_json(200, response.to_dict())

    def _handle_smart(self) -> None:
        """Proxy a Smart-tier request to llama-server (port 8081).

        The extension always talks to port 8765 (the wrapper).  The wrapper
        owns the hardware gate check, the llama-server proxy, and the
        degradation path — so the extension never has to know which port
        llama-server is on.

        Degradation:
          - Hardware gate fails  → 200 with {available: false, corrections: [],
                                   message: "Smart tier requires more RAM"}
          - llama-server not up  → 200 with {available: false, corrections: [],
                                   message: "Smart tier offline …"}
          - Proxy error          → 200 with {corrections: [], error: "proxy_error"}
        """
        body = self._read_body()
        if body is None:
            return

        text = body.get("text", "")
        context_hint = body.get("context_hint")

        if not isinstance(text, str) or not text.strip():
            self._send_json(200, {
                "corrections": [], "latency_ms": 0.0,
                "available": True, "error": None,
            })
            return

        hint_str: str | None = context_hint if isinstance(context_hint, str) else None

        # Hardware gate
        if not _smart_hardware_ok():
            self._send_json(200, {
                "available": False,
                "corrections": [],
                "latency_ms": 0.0,
                "message": "Smart tier requires more RAM (8 GB minimum)",
                "error": "hardware_gate",
            })
            return

        # llama-server reachability
        if not _llama_server_reachable():
            self._send_json(200, {
                "available": False,
                "corrections": [],
                "latency_ms": 0.0,
                "message": "Smart tier offline — start llama-server to enable rewrites",
                "error": "server_unreachable",
            })
            return

        # Proxy through the existing llama_backend (reuses all JSON-repair logic)
        request = Request(
            tier="smart",
            text=text,
            context_hint=hint_str,
            request_id=str(uuid.uuid4()),
        )
        response = tier_router.route(request)
        payload = response.to_dict()
        payload["available"] = True
        self._send_json(200, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Waldo Spells local HTTP server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), AnalyzeHandler)
    print(f"Waldo Spells server running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
