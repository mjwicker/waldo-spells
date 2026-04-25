const ANALYZE_URL = "http://127.0.0.1:8765/analyze";
const HEALTH_URL  = "http://127.0.0.1:8765/health";

browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "analyze") {
    handleAnalyze(msg).then(sendResponse);
    return true; // keep channel open for async response
  }
  if (msg.action === "health") {
    checkHealth().then(sendResponse);
    return true;
  }
});

async function handleAnalyze({ text, context_hint }) {
  const { enabled = true } = await browser.storage.local.get("enabled");
  if (!enabled) return { corrections: [] };

  try {
    const resp = await fetch(ANALYZE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, tier: "fast", context_hint }),
    });
    if (!resp.ok) return { corrections: [], error: `http_${resp.status}` };
    return await resp.json();
  } catch (_) {
    return { corrections: [], error: "server_unreachable" };
  }
}

async function checkHealth() {
  try {
    const resp = await fetch(HEALTH_URL);
    return { ok: resp.ok };
  } catch (_) {
    return { ok: false };
  }
}
