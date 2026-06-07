// smart_worker.js — Smart tier fetch wrapper for Waldo Spells
//
// Sends a paragraph to the unified wrapper (localhost:8765/smart) and returns
// the correction payload.  The wrapper owns hardware-gate detection and the
// llama-server proxy — this module never talks to port 8081 directly.
//
// Exported functions:
//   analyzeSmart(text, contextHint?)  → { corrections, available, message?, error? }
//   checkSmartStatus()                → { available, hardware_ok, server_ok, message }
//   getCachedSmartStatus()            → last cached status or null

const SMART_URL        = "http://127.0.0.1:8765/smart";
const SMART_STATUS_URL = "http://127.0.0.1:8765/smart_status";

let _lastStatus = null;

/**
 * Analyze a paragraph through the Smart tier (Qwen2.5-3B-Instruct).
 *
 * Degradation contract (mirrors wrapper/server.py _handle_smart):
 *   - hardware gate fails   → { available: false, corrections: [], message: "Smart tier requires more RAM" }
 *   - llama-server offline  → { available: false, corrections: [], message: "Smart tier offline …" }
 *   - network error         → { available: false, corrections: [], error: "fetch_error" }
 */
export async function analyzeSmart(text, contextHint) {
  try {
    const resp = await fetch(SMART_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, context_hint: contextHint ?? null }),
    });
    if (!resp.ok) {
      console.warn(`[WaldoSpells][smart] ✗ http_${resp.status}`);
      return { corrections: [], available: false, error: `http_${resp.status}` };
    }
    const data = await resp.json();
    const available = data.available ?? true;
    const nc = (data.corrections ?? []).length;
    if (available) {
      console.log(`[WaldoSpells][smart] ← ${nc} corrections`);
    } else {
      console.warn(`[WaldoSpells][smart] ← unavailable | ${data.message ?? ""}`);
    }
    _lastStatus = {
      available,
      hardware_ok: available,
      server_ok:   available,
      message:     data.message ?? (available ? "Smart tier ready" : "Smart tier offline"),
    };
    return data;
  } catch (_) {
    console.warn(`[WaldoSpells][smart] ✗ server_unreachable`);
    _lastStatus = {
      available:   false,
      hardware_ok: false,
      server_ok:   false,
      message:     "Smart tier — server unreachable",
    };
    return { corrections: [], available: false, error: "fetch_error" };
  }
}

/**
 * Query wrapper /smart_status without sending text.
 * Use this on popup open to show current availability without triggering analysis.
 */
export async function checkSmartStatus() {
  try {
    const resp = await fetch(SMART_STATUS_URL);
    if (!resp.ok) {
      console.warn(`[WaldoSpells][smart] status ✗ http_${resp.status}`);
      const fallback = { available: false, hardware_ok: false, server_ok: false,
                         message: "Smart tier — status check failed" };
      _lastStatus = fallback;
      return fallback;
    }
    const data = await resp.json();
    console.log(`[WaldoSpells][smart] status: available=${data.available} hw=${data.hardware_ok} srv=${data.server_ok}`);
    _lastStatus = data;
    return data;
  } catch (_) {
    console.warn(`[WaldoSpells][smart] status ✗ server_unreachable`);
    const fallback = { available: false, hardware_ok: false, server_ok: false,
                       message: "Smart tier — server unreachable" };
    _lastStatus = fallback;
    return fallback;
  }
}

/** Return the last cached status without a network call (may be null before first check). */
export function getCachedSmartStatus() {
  return _lastStatus;
}
