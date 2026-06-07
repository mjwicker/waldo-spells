// edge_worker.js — Edge tier inference using locally bundled ORT + Transformers.js
//
// Do NOT set globalThis[Symbol.for("onnxruntime")]. If that symbol is present,
// Transformers.js skips its device-setup block (et/op stay empty → no valid devices
// → "Unsupported device" error at pipeline creation time).
//
// ORT is imported statically (synchronous) so background.js can finish registering
// its onMessage listener before any heavy async work starts. Transformers.js is
// loaded lazily inside getPipeline() — the top-level await that was here before
// blocked background.js from fully initializing, causing Firefox to restart the
// background page mid-load and abort the in-flight ORT worker fetch (AbortError).

// ── Step 1: Load ORT (static import — synchronous, registers backends) ──────────
import * as ort from "./vendor/ort.wasm.min.mjs";

// ── Step 2: Configure ORT WASM paths (before any session is created) ─────────
ort.env.wasm.wasmPaths = self.location.origin + "/vendor/wasm/";
ort.env.wasm.numThreads = 1;

// ── Lazy Transformers.js loader ───────────────────────────────────────────────
// Imported inside getPipeline() so this module evaluates synchronously and
// background.js registers its listeners immediately.

let _transformers = null;

async function loadTransformers() {
  if (_transformers) return _transformers;

  // ── Diagnostic pre-flight ─────────────────────────────────────────────────
  console.log("[WaldoSpells][edge] SAB:", typeof SharedArrayBuffer);
  console.log("[WaldoSpells][edge] wasmPaths:", ort.env.wasm.wasmPaths);

  // Can we reach the WASM binary?
  try {
    const r = await fetch(ort.env.wasm.wasmPaths + "ort-wasm-simd.wasm", { method: "HEAD" });
    console.log("[WaldoSpells][edge] wasm HEAD:", r.ok, r.status, r.headers.get("content-type"));
  } catch (e) { console.error("[WaldoSpells][edge] wasm HEAD failed:", e); }

  // Can we reach the model config?
  const modelBase = self.location.origin + "/models/textattack/bert-base-uncased-CoLA/";
  try {
    const r = await fetch(modelBase + "config.json");
    console.log("[WaldoSpells][edge] config.json:", r.ok, r.status);
  } catch (e) { console.error("[WaldoSpells][edge] config.json failed:", e); }

  // ── Load Transformers.js ──────────────────────────────────────────────────
  console.log("[WaldoSpells][edge] importing transformers.js…");
  const tj = await import("./vendor/transformers.web.min.js");
  console.log("[WaldoSpells][edge] transformers.js loaded, env keys:", Object.keys(tj.env).join(", "));

  tj.env.localModelPath    = self.location.origin + "/models/";
  tj.env.allowLocalModels  = true;
  tj.env.allowRemoteModels = false;
  tj.env.useBrowserCache   = false;
  tj.env.useWasmCache      = false;  // extension context can't use browser cache API
  _transformers = tj;
  return _transformers;
}

// ── Singleton pipeline ────────────────────────────────────────────────────────

const MODEL_ID = "textattack/bert-base-uncased-CoLA";

let _pipe    = null;
let _loading = false;
let _ready   = false;
let _failed  = false;   // set permanently on first failure — prevents reload storms
const _waitQueue = [];

async function getPipeline() {
  if (_ready) return _pipe;
  if (_failed) throw new Error("edge pipeline permanently failed — reload extension to retry");

  return new Promise((resolve, reject) => {
    _waitQueue.push({ resolve, reject });
    if (_loading) return;
    _loading = true;

    console.log("[WaldoSpells][edge] pipeline loading…");
    loadTransformers()
      .then(({ pipeline }) => pipeline("text-classification", MODEL_ID, { dtype: "fp32" }))
      .then((p) => {
        console.log("[WaldoSpells][edge] pipeline ready");
        _pipe  = p;
        _ready = true;
        for (const w of _waitQueue) w.resolve(p);
        _waitQueue.length = 0;
      })
      .catch((err) => {
        console.error("[WaldoSpells][edge] pipeline failed:", err);
        _failed  = true;   // disable further attempts this session
        _loading = false;
        for (const w of _waitQueue) w.reject(err);
        _waitQueue.length = 0;
      });
  });
}

// ── Sentence splitter ─────────────────────────────────────────────────────────

function splitSentences(text) {
  return text
    .split(/(?<=[.?!])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 3);
}

// ── Public API ────────────────────────────────────────────────────────────────

export async function analyzeEdge(text) {
  const pipe = await getPipeline();
  const sentences = splitSentences(text);
  if (!sentences.length) return [];

  const results = await pipe(sentences, { topk: 1 });
  const normalised = sentences.length === 1 ? [results] : results;

  return normalised
    .map((result, i) => {
      const top = Array.isArray(result) ? result[0] : result;
      return { sentence: sentences[i], label: top.label, score: top.score };
    })
    .filter((r) => r.label === "UNACCEPTABLE" && r.score >= 0.65);
}

export function warmUp() {
  getPipeline().catch(() => {});
}
