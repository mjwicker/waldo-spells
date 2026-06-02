// edge_worker.js — Edge tier inference using Transformers.js v4 + BERT-CoLA ONNX
//
// Loaded as an ES module from background.js via dynamic import.
// Classifies grammatical acceptability (ACCEPTABLE / UNACCEPTABLE) using
// textattack/bert-base-uncased-CoLA (INT8 ONNX).
// The model is ~100 MB; Transformers.js fetches and caches it in the browser
// Cache API on first use — no network required after initial download.
//
// Model fix (T-SPELLS-EDGE-3):
//   The previous model (Xenova/distilbert-base-uncased-finetuned-sst-2-english)
//   was a 2-class sentiment classifier, not a grammar detector.  It produced
//   near-random output (F1 = 0.005) on grammar corpora because POSITIVE/NEGATIVE
//   sentiment has no correlation with grammatical acceptability.
//   Replaced with textattack/bert-base-uncased-CoLA which is fine-tuned on the
//   Corpus of Linguistic Acceptability (CoLA) and outputs ACCEPTABLE/UNACCEPTABLE.
//
// Architecture: zero-dependency on the local server (port 8765).
// This tier runs entirely inside the extension process.

// ── Transformers.js bootstrap ─────────────────────────────────────────────────
//
// Import from the locally-bundled vendor copy so the extension works offline
// after the model has been cached. The ONNX Runtime WASM backend files are
// loaded from jsDelivr CDN at first run; after that they are cached by the
// browser. Users on air-gapped machines should load the extension once while
// online to prime the cache.

import { pipeline, env } from "./vendor/transformers.web.min.js";

// Point WASM runtime at jsDelivr so we don't have to ship 13 MB of WASM.
// After first run the browser caches these automatically.
env.backends.onnx.wasm.wasmPaths =
  "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.26.0/dist/";

// Allow remote model download on first run; Cache API stores the result.
env.allowRemoteModels = true;
env.useBrowserCache  = true;

// ── Singleton pipeline ────────────────────────────────────────────────────────

// CoLA-trained grammar acceptability model.
// Labels: ACCEPTABLE (sentence is grammatically well-formed) /
//         UNACCEPTABLE (sentence has a grammar error).
// Source: textattack/bert-base-uncased-CoLA on HuggingFace.
// Note: Transformers.js will load the ONNX weights from the HuggingFace Hub.
// The model is fine-tuned on CoLA (Corpus of Linguistic Acceptability),
// eval_mcc ≈ 0.534 on the CoLA dev set.
const MODEL_ID = "textattack/bert-base-uncased-CoLA";

let _pipe    = null;   // pipeline instance once loaded
let _loading = false;  // guard against concurrent init
let _ready   = false;  // true once pipeline is usable

const _waitQueue = []; // callbacks waiting for pipeline to be ready

/**
 * Initialise (or return the cached) classification pipeline.
 * Safe to call concurrently — concurrent callers wait on the same promise.
 */
async function getPipeline() {
  if (_ready) return _pipe;

  return new Promise((resolve, reject) => {
    _waitQueue.push({ resolve, reject });

    if (_loading) return; // another caller already booting the pipeline
    _loading = true;

    pipeline("text-classification", MODEL_ID, {
      quantized: true, // request INT8 ONNX variant
      dtype: "int8",
    })
      .then((p) => {
        _pipe  = p;
        _ready = true;
        for (const waiter of _waitQueue) waiter.resolve(p);
        _waitQueue.length = 0;
      })
      .catch((err) => {
        _loading = false; // allow retry
        for (const waiter of _waitQueue) waiter.reject(err);
        _waitQueue.length = 0;
      });
  });
}

// ── Sentence splitter ─────────────────────────────────────────────────────────

/**
 * Split `text` into sentences on . ? ! boundaries.
 * Preserves trailing punctuation. Skips blank fragments.
 *
 * @param {string} text
 * @returns {string[]}
 */
function splitSentences(text) {
  // Split on sentence-ending punctuation followed by whitespace or end-of-string.
  // Avoids splitting on decimal numbers (e.g. "3.14") by requiring the
  // character before the period to be a word character (not a digit).
  return text
    .split(/(?<=[.?!])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 3); // ignore very short fragments
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Classify each sentence in `text` for grammatical acceptability.
 * Returns an array of objects describing any grammatically unacceptable sentences.
 *
 * Labels from the CoLA model:
 *   ACCEPTABLE   — sentence is grammatically well-formed
 *   UNACCEPTABLE — sentence contains a grammar error
 *
 * Only sentences classified as UNACCEPTABLE with score ≥ 0.65 are returned.
 * Callers (e.g. content.js) render these as inline grammar error highlights.
 *
 * @param {string} text
 * @returns {Promise<Array<{sentence: string, label: string, score: number}>>}
 */
export async function analyzeEdge(text) {
  const pipe = await getPipeline();

  const sentences = splitSentences(text);
  if (!sentences.length) return [];

  const results = await pipe(sentences, { topk: 1 });

  // `results` is an array of arrays when multiple inputs are passed,
  // or a single array when one input is passed.
  const normalised = sentences.length === 1 ? [results] : results;

  return normalised
    .map((result, i) => {
      const top = Array.isArray(result) ? result[0] : result;
      return {
        sentence : sentences[i],
        label    : top.label,  // "ACCEPTABLE" or "UNACCEPTABLE"
        score    : top.score,
      };
    })
    // Surface UNACCEPTABLE sentences only — these are the grammar errors.
    // Threshold 0.65: lower than the old 0.70 to improve recall for short sentences.
    .filter((r) => r.label === "UNACCEPTABLE" && r.score >= 0.65);
}

/**
 * Warm up the CoLA grammar pipeline in the background.
 * Called once at service-worker startup so the first user request is fast.
 * The CoLA model (~100 MB) is downloaded and cached by the browser on first use.
 */
export function warmUp() {
  getPipeline().catch(() => {
    // Silently swallow warm-up errors — offline at startup is fine.
  });
}
