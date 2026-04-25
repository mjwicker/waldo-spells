"""HTTP server wrapping the tier router. Start with: python -m wrapper.server"""

import argparse
import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tier_router
from protocol import Request


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
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/analyze":
            self._send_json(404, {"error": "not_found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid_json"})
            return

        text = body.get("text", "")
        tier = body.get("tier", "fast")
        context_hint = body.get("context_hint")

        if not isinstance(text, str) or not text.strip():
            self._send_json(200, {"corrections": [], "latency_ms": 0.0,
                                  "tier_used": tier, "error": None})
            return

        request = Request(
            tier=tier,
            text=text,
            context_hint=context_hint,
            request_id=str(uuid.uuid4()),
        )
        response = tier_router.route(request)
        self._send_json(200, response.to_dict())


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
