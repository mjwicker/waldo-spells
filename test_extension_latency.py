"""Extension latency constants and message shape tests.

Tests the latency improvements in cycle 28:
- EDGE_DEBOUNCE_MS constant verification (600ms target)
- Timestamp fields present in message objects across extension/content.js,
  extension/background.js, and extension/edge_worker.js
"""

import re
from pathlib import Path


class TestEdgeDebounceConstant:
    """Verify EDGE_DEBOUNCE_MS is correctly set to 600ms."""

    def test_edge_debounce_ms_is_600(self):
        """EDGE_DEBOUNCE_MS should be 600 after reduction from 1200ms."""
        content_js = Path(__file__).parent / "extension" / "content.js"
        assert content_js.exists(), f"content.js not found at {content_js}"

        with open(content_js, "r") as f:
            content = f.read()

        # Match the constant definition: const EDGE_DEBOUNCE_MS = 600;
        match = re.search(r"const\s+EDGE_DEBOUNCE_MS\s*=\s*(\d+)", content)
        assert match, "EDGE_DEBOUNCE_MS constant not found in content.js"

        value = int(match.group(1))
        assert value == 600, f"Expected EDGE_DEBOUNCE_MS to be 600, got {value}"


class TestTimestampFields:
    """Verify timestamp fields are present in message objects."""

    def test_content_js_sends_ts_content_send(self):
        """content.js should send ts_content_send in the message to background."""
        content_js = Path(__file__).parent / "extension" / "content.js"
        assert content_js.exists(), f"content.js not found at {content_js}"

        with open(content_js, "r") as f:
            content = f.read()

        # Look for timestamp creation
        assert "const ts_content_send = Date.now()" in content, \
            "ts_content_send timestamp not found in content.js"

        # Look for sending it in message
        assert "ts_content_send" in content and "sendMessage" in content, \
            "ts_content_send not sent in message to background"

        # Verify it's sent in the action message
        match = re.search(
            r'browser\.runtime\.sendMessage\(\s*\{\s*action:\s*"edge_analyze",\s*text,\s*ts_content_send',
            content
        )
        assert match, \
            "ts_content_send not sent as parameter in edge_analyze action message"

    def test_background_js_receives_and_timestamps(self):
        """background.js should receive ts_content_send and create response timestamps."""
        background_js = Path(__file__).parent / "extension" / "background.js"
        assert background_js.exists(), f"background.js not found at {background_js}"

        with open(background_js, "r") as f:
            content = f.read()

        # Verify it creates receive timestamp
        assert "const ts_bg_receive = Date.now()" in content, \
            "ts_bg_receive timestamp not found in background.js"

        # Verify it creates reply timestamp
        assert "const ts_bg_reply = Date.now()" in content, \
            "ts_bg_reply timestamp not found in background.js"

        # Verify it uses ts_content_send from message
        assert "ts_content_send" in content, \
            "ts_content_send not referenced in background.js"

    def test_edge_worker_js_creates_worker_timestamps(self):
        """edge_worker.js should create ts_worker_start and ts_worker_end timestamps."""
        edge_worker_js = Path(__file__).parent / "extension" / "edge_worker.js"
        assert edge_worker_js.exists(), f"edge_worker.js not found at {edge_worker_js}"

        with open(edge_worker_js, "r") as f:
            content = f.read()

        # Verify worker timestamps are created
        assert "const ts_worker_start = Date.now()" in content, \
            "ts_worker_start timestamp not found in edge_worker.js"

        assert "const ts_worker_end = Date.now()" in content, \
            "ts_worker_end timestamp not found in edge_worker.js"

        # Verify they're attached to output (prefixed with _)
        assert "output._ts_worker_start = ts_worker_start" in content, \
            "ts_worker_start not attached to output in edge_worker.js"

        assert "output._ts_worker_end = ts_worker_end" in content, \
            "ts_worker_end not attached to output in edge_worker.js"

    def test_timestamp_chain_complete(self):
        """Verify the full timestamp chain: content → bg_receive → worker → bg_reply."""
        # This is an integration check across all three files
        content_js = Path(__file__).parent / "extension" / "content.js"
        background_js = Path(__file__).parent / "extension" / "background.js"
        edge_worker_js = Path(__file__).parent / "extension" / "edge_worker.js"

        with open(content_js, "r") as f:
            content = f.read()
        with open(background_js, "r") as f:
            background = f.read()
        with open(edge_worker_js, "r") as f:
            edge_worker = f.read()

        # content.js: creates and sends ts_content_send
        assert "ts_content_send = Date.now()" in content
        assert "sendMessage" in content and "ts_content_send" in content

        # background.js: receives content message, creates bg_receive, calls worker, gets worker result, creates bg_reply
        assert "ts_bg_receive = Date.now()" in background
        assert "ts_bg_reply = Date.now()" in background
        assert "ts_content_send" in background  # receives it
        assert "_ts_worker_start" in background  # receives worker timestamps
        assert "_ts_worker_end" in background

        # edge_worker.js: creates and returns worker timestamps
        assert "ts_worker_start = Date.now()" in edge_worker
        assert "ts_worker_end = Date.now()" in edge_worker
        assert "output._ts_worker_start" in edge_worker
        assert "output._ts_worker_end" in edge_worker
