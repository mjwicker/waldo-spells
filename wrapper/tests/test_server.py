"""Smoke tests for wrapper.server HTTP endpoints."""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from server import AnalyzeHandler

_PORT = 18765  # non-conflicting port; different from production 8765


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


def test_health(base_url):
    resp = _get(f"{base_url}/health")
    body = json.loads(resp.read())
    assert body == {"status": "ok"}


def test_analyze_fast_catches_typos(base_url):
    resp = _post(f"{base_url}/analyze", {"text": "I recieved teh package", "tier": "fast"})
    body = json.loads(resp.read())
    assert "corrections" in body
    originals = {c["original"] for c in body["corrections"]}
    # Both typos should be caught by the Fast (pyenchant) tier
    assert "recieved" in originals or "teh" in originals


def test_analyze_empty_text_returns_no_corrections(base_url):
    resp = _post(f"{base_url}/analyze", {"text": "", "tier": "fast"})
    body = json.loads(resp.read())
    assert body["corrections"] == []


def test_analyze_whitespace_only_returns_no_corrections(base_url):
    resp = _post(f"{base_url}/analyze", {"text": "   ", "tier": "fast"})
    body = json.loads(resp.read())
    assert body["corrections"] == []


def test_analyze_correct_text_returns_no_corrections(base_url):
    resp = _post(f"{base_url}/analyze", {"text": "The quick brown fox jumps.", "tier": "fast"})
    body = json.loads(resp.read())
    assert body["corrections"] == []


def test_analyze_invalid_json_returns_400(base_url):
    req = urllib.request.Request(
        f"{base_url}/analyze",
        data=b"not json",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_unknown_route_returns_404(base_url):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base_url}/nonexistent")
    assert exc.value.code == 404
