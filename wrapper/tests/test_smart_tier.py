"""Tests for the Smart tier (/smart endpoint) with hardware gate and llama-server proxy.

Contracts verified:
  (1) /smart endpoint with hardware gate mocked (both pass and fail)
  (2) llama-server unreachable path (returns degraded response)
  (3) Empty text fast-path (returns corrections: [])
  (4) Full proxy path returning corrections from llama-server
  (5) /smart_status GET returns correct available/hardware_ok/server_ok/message fields
  (6) _system_ram_bytes() parsing logic from /proc/meminfo
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from server import (
    AnalyzeHandler,
    _system_ram_bytes,
    _smart_hardware_ok,
    _llama_server_reachable,
    _SMART_RAM_FLOOR_BYTES,
)

_PORT = 18766  # non-conflicting port; different from other wrapper tests


@pytest.fixture(scope="module")
def base_url():
    srv = HTTPServer(("127.0.0.1", _PORT), AnalyzeHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{_PORT}"
    srv.shutdown()


def _get(url):
    return urllib.request.urlopen(url)


def _post(url, data: dict):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)


# ============================================================================
# Test _system_ram_bytes() parsing
# ============================================================================

class TestSystemRamBytes:
    """Verify _system_ram_bytes() parses /proc/meminfo correctly."""

    def test_system_ram_bytes_parses_memtotal(self):
        """_system_ram_bytes() should extract MemTotal and convert kB to bytes."""
        from io import StringIO

        meminfo_content = "MemTotal:      12345678 kB\nMemFree:       1234567 kB\n"

        with patch("builtins.open") as mock_open:
            mock_open.return_value = StringIO(meminfo_content)

            ram = _system_ram_bytes()
            # 12345678 kB * 1024 bytes/kB
            assert ram == 12345678 * 1024

    def test_system_ram_bytes_handles_missing_memtotal(self):
        """If MemTotal line is missing, _system_ram_bytes() should return 0."""
        from io import StringIO

        meminfo_content = "MemFree:       1234567 kB\nMemAvailable:  1000000 kB\n"

        with patch("builtins.open") as mock_open:
            mock_open.return_value = StringIO(meminfo_content)

            ram = _system_ram_bytes()
            assert ram == 0

    def test_system_ram_bytes_handles_missing_file(self):
        """If /proc/meminfo doesn't exist, _system_ram_bytes() should return 0."""
        with patch("builtins.open", side_effect=OSError("no such file")):
            ram = _system_ram_bytes()
            assert ram == 0


# ============================================================================
# Test /smart_status endpoint
# ============================================================================

class TestSmartStatus:
    """Verify /smart_status endpoint reports hardware and server status."""

    def test_smart_status_all_ok(self, base_url):
        """When hardware OK and llama-server reachable, status should be available."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv:
            mock_hw.return_value = True
            mock_srv.return_value = True

            resp = _get(f"{base_url}/smart_status")
            body = json.loads(resp.read())

            assert body["available"] is True
            assert body["hardware_ok"] is True
            assert body["server_ok"] is True
            assert body["message"] == "Smart tier ready"

    def test_smart_status_hardware_gate_fails(self, base_url):
        """When hardware gate fails, status should report hardware_ok=False."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv:
            mock_hw.return_value = False
            mock_srv.return_value = True

            resp = _get(f"{base_url}/smart_status")
            body = json.loads(resp.read())

            assert body["available"] is False
            assert body["hardware_ok"] is False
            assert body["server_ok"] is False  # server_ok should not be checked if HW fails
            assert "8 GB minimum" in body["message"]

    def test_smart_status_server_unreachable(self, base_url):
        """When hardware OK but llama-server unreachable, status should reflect it."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv:
            mock_hw.return_value = True
            mock_srv.return_value = False

            resp = _get(f"{base_url}/smart_status")
            body = json.loads(resp.read())

            assert body["available"] is False
            assert body["hardware_ok"] is True
            assert body["server_ok"] is False
            assert "offline" in body["message"]


# ============================================================================
# Test /smart endpoint
# ============================================================================

class TestSmartEndpoint:
    """Verify /smart endpoint proxy and degradation paths."""

    def test_smart_empty_text_fast_path(self, base_url):
        """Empty or whitespace-only text should return corrections: [] immediately."""
        resp = _post(f"{base_url}/smart", {"text": "", "context_hint": None})
        body = json.loads(resp.read())

        assert body["corrections"] == []
        assert body["latency_ms"] == 0.0

    def test_smart_whitespace_only_fast_path(self, base_url):
        """Whitespace-only text should return corrections: [] immediately."""
        resp = _post(f"{base_url}/smart", {"text": "   \n\t  ", "context_hint": None})
        body = json.loads(resp.read())

        assert body["corrections"] == []
        assert body["latency_ms"] == 0.0

    def test_smart_hardware_gate_fails(self, base_url):
        """When hardware gate fails, /smart should return error and empty corrections."""
        with patch("server._smart_hardware_ok") as mock_hw:
            mock_hw.return_value = False

            resp = _post(f"{base_url}/smart", {"text": "Write some text here"})
            body = json.loads(resp.read())

            assert body["available"] is False
            assert body["corrections"] == []
            assert body["error"] == "hardware_gate"
            assert "8 GB minimum" in body["message"]

    def test_smart_server_unreachable(self, base_url):
        """When hardware OK but llama-server unreachable, /smart degrades gracefully."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv:
            mock_hw.return_value = True
            mock_srv.return_value = False

            resp = _post(f"{base_url}/smart", {"text": "Write some text here"})
            body = json.loads(resp.read())

            assert body["available"] is False
            assert body["corrections"] == []
            assert body["error"] == "server_unreachable"
            assert "offline" in body["message"]

    def test_smart_full_proxy_path(self, base_url):
        """When all gates pass, /smart proxies to llama-server (mocked tier_router)."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv, \
             patch("server.tier_router.route") as mock_route:
            mock_hw.return_value = True
            mock_srv.return_value = True

            # Mock tier_router.route to simulate a Smart tier response with corrections
            mock_response = MagicMock()
            mock_response.to_dict.return_value = {
                "corrections": [
                    {
                        "original": "recieve",
                        "suggestion": "receive",
                        "tier": "smart",
                        "reason": "Common misspelling"
                    }
                ],
                "latency_ms": 150.0,
                "tier_used": "smart",
                "error": None,
            }
            mock_route.return_value = mock_response

            resp = _post(f"{base_url}/smart", {"text": "I recieve your message"})
            body = json.loads(resp.read())

            assert body["available"] is True
            assert len(body["corrections"]) == 1
            assert body["corrections"][0]["original"] == "recieve"
            assert body["tier_used"] == "smart"

    def test_smart_proxy_error_handling(self, base_url):
        """If tier_router.route raises an exception, /smart returns empty corrections with error."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv, \
             patch("server.tier_router.route") as mock_route:
            mock_hw.return_value = True
            mock_srv.return_value = True
            mock_route.side_effect = Exception("tier_router failed")

            # The current implementation doesn't wrap tier_router.route in a try-catch,
            # so this will propagate. Documenting the current behavior.
            # If error handling is added later, this test should be updated.
            with pytest.raises(Exception):
                _post(f"{base_url}/smart", {"text": "Some text"})


# ============================================================================
# Test context_hint parameter passing
# ============================================================================

class TestContextHint:
    """Verify context_hint parameter is passed through to tier_router."""

    def test_smart_context_hint_passed(self, base_url):
        """context_hint parameter should be passed to tier_router.route."""
        with patch("server._smart_hardware_ok") as mock_hw, \
             patch("server._llama_server_reachable") as mock_srv, \
             patch("server.tier_router.route") as mock_route:
            mock_hw.return_value = True
            mock_srv.return_value = True

            captured_request = None
            def capture_route(req):
                nonlocal captured_request
                captured_request = req
                mock_response = MagicMock()
                mock_response.to_dict.return_value = {
                    "corrections": [],
                    "latency_ms": 100.0,
                    "tier_used": "smart",
                    "error": None,
                }
                return mock_response

            mock_route.side_effect = capture_route

            resp = _post(f"{base_url}/smart", {
                "text": "Some text to analyze",
                "context_hint": "formal_letter"
            })
            body = json.loads(resp.read())

            assert body["corrections"] == []
            assert captured_request is not None
            assert captured_request.context_hint == "formal_letter"
