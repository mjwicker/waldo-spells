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

// ── Context menu: "Fix this with Waldo" on orange squiggles ──────────────────
//
// We register one context menu item that only appears when the user right-clicks
// a flagged sentence.  The content script stores the sentence text in
// waldo_ctx_squiggle (storage.local) on mousedown; we read it back here.
// After generating suggestions we send a "suggest_fix" message to the tab so
// the content script can display the panel near the squiggle.

browser.contextMenus.create({
  id:       "waldo-fix-suggestion",
  title:    "Fix this with Waldo…",
  contexts: ["all"],
});

browser.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "waldo-fix-suggestion") return;
  if (!tab?.id) return;

  // Read corrections stored by the right-click mousedown handler in content.js.
  // waldo_ctx_data = JSON { text, corrections: [{original, suggestions[]}] }
  const stored = await browser.storage.local.get("waldo_ctx_data");
  let ctxData = null;
  try { ctxData = stored.waldo_ctx_data ? JSON.parse(stored.waldo_ctx_data) : null; } catch (_) {}

  if (!ctxData || !ctxData.corrections?.length) {
    console.log("[WaldoSpells][ctx-menu] no active corrections to show");
    return;
  }

  console.log(`[WaldoSpells][ctx-menu] ${ctxData.corrections.length} correction(s) cached`);

  // Use cached Fast-tier corrections directly — no LLM round-trip needed.
  // If Smart tier is available, enrich with explanation for the first item.
  let explanation = "";
  const corrections = ctxData.corrections;

  try {
    const smartResult = await analyzeSmart(ctxData.text, "context_menu");
    if (smartResult.available && (smartResult.corrections ?? []).length > 0) {
      explanation = smartResult.corrections[0].explanation ?? "";
    }
  } catch (_) {
    // Smart tier unavailable — proceed with Fast-tier suggestions only
  }

  browser.tabs.sendMessage(tab.id, {
    action: "suggest_fix",
    sentence:    ctxData.text,
    explanation,
    corrections, // full list: [{original, suggestions[]}]
    suggestions: corrections[0]?.suggestions ?? [],
  }).catch((err) => {
    console.warn(`[WaldoSpells][ctx-menu] ✗ could not relay to tab:`, String(err));
  });
});

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

async function handleEdgeAnalyze({ text, ts_content_send }) {
  const ts_bg_receive = Date.now();
  const { enabled = true } = await browser.storage.local.get("enabled");
  if (!enabled) return { sentences: [], ts_content_send };

  console.log(`[WaldoSpells][edge] → ${text.length}ch`);

  try {
    const flagged = await analyzeEdge(text);
    const ts_bg_reply = Date.now();
    const latency_bg_to_worker = flagged._ts_worker_end && flagged._ts_worker_start
      ? flagged._ts_worker_end - flagged._ts_worker_start
      : null;
    const latency_to_bg = ts_bg_receive - (ts_content_send ?? 0);
    const latency_from_bg = ts_bg_reply - ts_bg_receive;
    console.log(`[WaldoSpells][edge] ← ${flagged.length} flagged (to_bg=${latency_to_bg}ms, worker=${latency_bg_to_worker}ms, from_bg=${latency_from_bg}ms)`);
    return { sentences: flagged, ts_content_send };
  } catch (err) {
    console.error(`[WaldoSpells][edge] ✗`, String(err));
    return { sentences: [], error: String(err), ts_content_send };
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
