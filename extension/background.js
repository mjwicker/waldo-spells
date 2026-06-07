// background.js — Waldo Spells background service module (MV3)
//
// Handles message actions:
//   "analyze"       — forward text to local server (fast / better tiers)
//   "edge_analyze"  — run CoLA BERT Edge tier directly in-extension via Transformers.js
//   "smart_analyze" — forward paragraph to Smart tier via wrapper /smart endpoint
//   "smart_status"  — query /smart_status without sending text (popup badge)
//   "health"        — ping local server health endpoint
//
// Logging convention (extension DevTools console):
//   [WaldoSpells][tier] → Nch [| hint]   — request received from content script
//   [WaldoSpells][tier] ← N results       — result returned to content script
//   [WaldoSpells][tier] ✗ reason          — error (warn level for server-down, error for crashes)

import { analyzeEdge, warmUp } from "./edge_worker.js";
import { analyzeSmart, checkSmartStatus } from "./smart_worker.js";

const ANALYZE_URL = "http://127.0.0.1:8765/analyze";
const HEALTH_URL  = "http://127.0.0.1:8765/health";

// Warm up the Edge pipeline on service-worker start so the first request is fast.
warmUp();

browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "analyze") {
    handleAnalyze(msg).then(sendResponse);
    return true;
  }
  if (msg.action === "edge_analyze") {
    handleEdgeAnalyze(msg).then(sendResponse);
    return true;
  }
  if (msg.action === "smart_analyze") {
    handleSmartAnalyze(msg).then(sendResponse);
    return true;
  }
  if (msg.action === "smart_status") {
    checkSmartStatus().then(sendResponse);
    return true;
  }
  if (msg.action === "health") {
    checkHealth().then(sendResponse);
    return true;
  }
});

// ── Fast tier — local server ──────────────────────────────────────────────────

async function handleAnalyze({ text, context_hint }) {
  const { enabled = true } = await browser.storage.local.get("enabled");
  if (!enabled) return { corrections: [] };

  console.log(`[WaldoSpells][fast] → ${text.length}ch${context_hint ? ` | ${context_hint}` : ""}`);

  try {
    const resp = await fetch(ANALYZE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, tier: "fast", context_hint }),
    });
    if (!resp.ok) {
      console.warn(`[WaldoSpells][fast] ✗ http_${resp.status}`);
      return { corrections: [], error: `http_${resp.status}` };
    }
    const data = await resp.json();
    console.log(`[WaldoSpells][fast] ← ${(data.corrections ?? []).length} corrections`);
    return data;
  } catch (_) {
    console.warn(`[WaldoSpells][fast] ✗ server_unreachable`);
    return { corrections: [], error: "server_unreachable" };
  }
}

// ── Smart tier — Qwen2.5-3B-Instruct via wrapper /smart ──────────────────────

async function handleSmartAnalyze({ text, context_hint }) {
  const { enabled = true } = await browser.storage.local.get("enabled");
  if (!enabled) return { corrections: [], available: false };

  console.log(`[WaldoSpells][smart] → ${text.length}ch${context_hint ? ` | ${context_hint}` : ""}`);
  return analyzeSmart(text, context_hint);
}

// ── Edge tier — in-extension CoLA BERT ONNX ──────────────────────────────────

async function handleEdgeAnalyze({ text }) {
  const { enabled = true } = await browser.storage.local.get("enabled");
  if (!enabled) return { sentences: [] };

  console.log(`[WaldoSpells][edge] → ${text.length}ch`);

  try {
    const flagged = await analyzeEdge(text);
    console.log(`[WaldoSpells][edge] ← ${flagged.length} flagged`);
    return { sentences: flagged };
  } catch (err) {
    console.error(`[WaldoSpells][edge] ✗`, String(err));
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
