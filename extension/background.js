// background.js — Waldo Spells background service module (MV3)
//
// Handles two message actions:
//   "analyze"      — forward text to local server (fast / better / smart tiers)
//   "edge_analyze" — run DistilBERT Edge tier directly in-extension via Transformers.js
//   "health"       — ping local server health endpoint

import { analyzeEdge, warmUp } from "./edge_worker.js";

const ANALYZE_URL = "http://127.0.0.1:8765/analyze";
const HEALTH_URL  = "http://127.0.0.1:8765/health";

// Warm up the Edge pipeline on service-worker start so the first request is fast.
warmUp();

browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "analyze") {
    handleAnalyze(msg).then(sendResponse);
    return true; // keep channel open for async response
  }
  if (msg.action === "edge_analyze") {
    handleEdgeAnalyze(msg).then(sendResponse);
    return true;
  }
  if (msg.action === "health") {
    checkHealth().then(sendResponse);
    return true;
  }
});

// ── Fast / Better / Smart tier — local server ─────────────────────────────────

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

// ── Edge tier — in-extension DistilBERT ONNX ─────────────────────────────────

async function handleEdgeAnalyze({ text }) {
  const { enabled = true } = await browser.storage.local.get("enabled");
  if (!enabled) return { sentences: [] };

  try {
    const flagged = await analyzeEdge(text);
    return { sentences: flagged };
  } catch (err) {
    return { sentences: [], error: String(err) };
  }
}

// ── Health check ──────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const resp = await fetch(HEALTH_URL);
    return { ok: resp.ok };
  } catch (_) {
    return { ok: false };
  }
}
