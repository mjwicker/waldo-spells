// Replaces the bare "onnxruntime-web/webgpu" import inside transformers.web.min.js.
// Transformers.js uses this module as `cA` — the ORT instance it runs inference with.
// We must NOT set globalThis[Symbol.for("onnxruntime")] in edge_worker.js:
// if that symbol is present, Transformers.js skips device setup entirely (et/op stay
// empty → no valid devices → "Unsupported device" error). By leaving globalThis clean,
// Transformers.js takes its browser else-branch: Ls=cA, et.push("wasm"), op=["wasm"].
// Re-exporting everything from our local ORT bundle gives Ls.InferenceSession etc.
export * from "./ort.wasm.min.mjs";
