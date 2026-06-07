// Stub for the "onnxruntime-common" bare specifier inside transformers.web.min.js.
// Re-exports Tensor from our locally bundled ORT so Transformers.js gets a valid
// class without a bare-specifier link error. Same instance as the ORT we inject
// via globalThis[Symbol.for("onnxruntime")], so instanceof checks are consistent.
export { Tensor } from "./ort.wasm.min.mjs";
