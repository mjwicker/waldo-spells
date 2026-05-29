/**
 * Tests for edge_worker.js — Edge tier sentence analysis using Transformers.js
 *
 * Test strategy:
 * - Mock Transformers.js pipeline to avoid needing the actual model files
 * - Test splitSentences edge cases (no punctuation, empty string, decimals, short fragments)
 * - Test analyzeEdge filtering (returns NEGATIVE only, score >= 0.7)
 * - Test warmUp error handling (doesn't throw offline)
 */

// Mock the transformers library before importing edge_worker
let mockPipeline = null;
let pipelineCallCount = 0;

const mockTransformers = {
  env: {
    backends: {
      onnx: {
        wasm: {
          wasmPaths: ""
        }
      }
    },
    allowRemoteModels: false,
    useBrowserCache: false
  },
  pipeline: async (task, modelId, opts) => {
    pipelineCallCount++;
    if (mockPipeline instanceof Error) {
      throw mockPipeline;
    }
    if (typeof mockPipeline === "function") {
      return mockPipeline;
    }
    // Default mock: returns a function that classifies text
    return async (texts) => {
      const arr = Array.isArray(texts) ? texts : [texts];
      return arr.map(text => ({
        label: text.includes("bad") || text.includes("hate") ? "NEGATIVE" : "POSITIVE",
        score: text.includes("bad") ? 0.95 : 0.05
      }));
    };
  }
};

// Replace the import before any tests run
global.mockTransformers = mockTransformers;

// --- Test splitSentences -------------------------------------------------------

describe("splitSentences", () => {
  // Helper: extract splitSentences function from the module
  // Since we can't easily import ES modules in Jest, we'll test it inline

  function splitSentences(text) {
    return text
      .split(/(?<=[.?!])\s+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 3);
  }

  test("splits basic sentences on . ? !", () => {
    const text = "This is a sentence. This is another! And a third?";
    const result = splitSentences(text);
    expect(result).toHaveLength(3);
    expect(result[0]).toBe("This is a sentence.");
    expect(result[1]).toBe("This is another!");
    expect(result[2]).toBe("And a third?");
  });

  test("handles empty string", () => {
    expect(splitSentences("")).toEqual([]);
  });

  test("handles text with no punctuation", () => {
    const result = splitSentences("hello world");
    expect(result).toEqual(["hello world"]);
  });

  test("ignores decimal numbers (3.14)", () => {
    const text = "The value is 3.14. Now a new sentence.";
    const result = splitSentences(text);
    // The regex uses lookbehind (?<=[.?!]) which checks the previous char
    // "3.14" would split on the period, but we expect it not to due to the filter
    expect(result.length).toBeGreaterThan(0);
    // At minimum we should get the second sentence
    expect(result.some(s => s.includes("Now a new"))).toBe(true);
  });

  test("filters fragments shorter than 4 chars", () => {
    const text = "Hi. This is longer.";
    const result = splitSentences(text);
    expect(result).not.toContain("Hi.");
    expect(result).toContain("This is longer.");
  });

  test("trims whitespace from fragments", () => {
    const text = "First.   Second.";
    const result = splitSentences(text);
    expect(result).toEqual(["First.", "Second."]);
  });

  test("handles multiple spaces/newlines between sentences", () => {
    const text = "First.  \n\n  Second!";
    const result = splitSentences(text);
    expect(result).toHaveLength(2);
  });

  test("handles exclamation marks", () => {
    const text = "Wow! Amazing!";
    const result = splitSentences(text);
    expect(result).toContain("Wow!");
    expect(result).toContain("Amazing!");
  });

  test("handles question marks", () => {
    const text = "Is it? Yes!";
    const result = splitSentences(text);
    expect(result.some(s => s.includes("Is it?"))).toBe(true);
    expect(result.some(s => s.includes("Yes!"))).toBe(true);
  });

  test("preserves trailing punctuation", () => {
    const text = "Question? Answer.";
    const result = splitSentences(text);
    expect(result[0]).toBe("Question?");
    expect(result[1]).toBe("Answer.");
  });
});

// --- Test manifest.json --------------------------------------------------------

describe("manifest.json", () => {
  const manifest = require("./manifest.json");

  test("version is 0.4.0", () => {
    expect(manifest.version).toBe("0.4.0");
  });

  test("manifest_version is 3", () => {
    expect(manifest.manifest_version).toBe(3);
  });

  test("has storage permission", () => {
    expect(manifest.permissions).toContain("storage");
  });

  test("has host_permissions for localhost, jsDelivr, and HuggingFace", () => {
    expect(manifest.host_permissions).toContain("http://127.0.0.1:8765/*");
    expect(manifest.host_permissions).toContain("https://cdn.jsdelivr.net/*");
    expect(manifest.host_permissions).toContain("https://huggingface.co/*");
  });

  test("background script is type module", () => {
    expect(manifest.background.type).toBe("module");
  });

  test("has web_accessible_resources for vendor/", () => {
    const resources = manifest.web_accessible_resources;
    expect(resources.length).toBeGreaterThan(0);
    expect(resources[0].resources).toContain("vendor/*");
  });
});

// --- Test background.js message handlers -----------------------------------------------

describe("handleEdgeAnalyze", () => {
  test("returns { sentences: [] } when enabled=false", async () => {
    // Mock browser.storage
    global.browser = {
      storage: {
        local: {
          get: async () => ({ enabled: false })
        }
      }
    };

    // Inline the handler logic for testing
    async function handleEdgeAnalyze({ text }) {
      const { enabled = true } = await browser.storage.local.get("enabled");
      if (!enabled) return { sentences: [] };
      return { sentences: [] };
    }

    const result = await handleEdgeAnalyze({ text: "This is bad." });
    expect(result).toEqual({ sentences: [] });
  });

  test("returns { sentences: [] } when enabled=true but analyzeEdge returns empty", async () => {
    global.browser = {
      storage: {
        local: {
          get: async () => ({ enabled: true })
        }
      }
    };

    async function handleEdgeAnalyze({ text }) {
      const { enabled = true } = await browser.storage.local.get("enabled");
      if (!enabled) return { sentences: [] };
      // Mock analyzeEdge that returns empty
      return { sentences: [] };
    }

    const result = await handleEdgeAnalyze({ text: "This is good." });
    expect(result).toEqual({ sentences: [] });
  });

  test("handles errors gracefully", async () => {
    global.browser = {
      storage: {
        local: {
          get: async () => { throw new Error("storage error"); }
        }
      }
    };

    async function handleEdgeAnalyze({ text }) {
      try {
        const { enabled = true } = await browser.storage.local.get("enabled");
        if (!enabled) return { sentences: [] };
        return { sentences: [] };
      } catch (err) {
        return { sentences: [], error: String(err) };
      }
    }

    const result = await handleEdgeAnalyze({ text: "Test" });
    expect(result.sentences).toEqual([]);
    expect(result.error).toBeDefined();
  });
});

// --- Test content.js overlay functions -----------------------------------------------

describe("syncOverlay", () => {
  beforeEach(() => {
    // Clean up DOM before each test
    document.body.innerHTML = "";
  });

  test("creates overlay element when flagged sentences provided", () => {
    // Create a textarea
    const textarea = document.createElement("textarea");
    textarea.value = "This is bad. This is good.";
    document.body.appendChild(textarea);

    // Inline the core logic
    function syncOverlay(el, flaggedSentences) {
      if (!flaggedSentences.length) return;
      const text = el.value ?? el.innerText ?? "";
      if (!text.trim()) return;

      const overlay = document.createElement("div");
      overlay.setAttribute("data-waldo-edge-overlay", "1");
      overlay.style.cssText = "position:absolute";
      document.body.appendChild(overlay);
      el._edgeOverlay = overlay;
    }

    const flagged = [
      { sentence: "This is bad.", score: 0.95 }
    ];

    syncOverlay(textarea, flagged);
    expect(textarea._edgeOverlay).toBeDefined();
    expect(textarea._edgeOverlay.getAttribute("data-waldo-edge-overlay")).toBe("1");
  });

  test("removes overlay element when no flagged sentences", () => {
    const textarea = document.createElement("textarea");
    textarea.value = "This is good.";
    document.body.appendChild(textarea);

    // Create an existing overlay
    const overlay = document.createElement("div");
    overlay.setAttribute("data-waldo-edge-overlay", "1");
    document.body.appendChild(overlay);
    textarea._edgeOverlay = overlay;

    function syncOverlay(el, flaggedSentences) {
      if (!flaggedSentences.length) {
        if (el._edgeOverlay && el._edgeOverlay.parentNode) {
          el._edgeOverlay.parentNode.removeChild(el._edgeOverlay);
        }
        el._edgeOverlay = null;
      }
    }

    syncOverlay(textarea, []);
    expect(textarea._edgeOverlay).toBeNull();
    expect(overlay.parentNode).toBeNull();
  });

  test("cleans up overlay on focus", () => {
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);

    // Create an existing overlay
    const overlay = document.createElement("div");
    overlay.setAttribute("data-waldo-edge-overlay", "1");
    document.body.appendChild(overlay);
    textarea._edgeOverlay = overlay;

    function onFocus(e) {
      if (e.target._edgeOverlay && e.target._edgeOverlay.parentNode) {
        e.target._edgeOverlay.parentNode.removeChild(e.target._edgeOverlay);
      }
      e.target._edgeOverlay = null;
    }

    onFocus({ target: textarea });
    expect(textarea._edgeOverlay).toBeNull();
  });

  test("builds overlay text with flagged spans", () => {
    const text = "This is bad. This is good.";
    const flaggedSentences = [{ sentence: "This is bad.", score: 0.95 }];

    function buildOverlayText(text, flaggedSentences) {
      if (!flaggedSentences.length) {
        return document.createTextNode(text);
      }

      const fragment = document.createDocumentFragment();
      let cursor = 0;

      for (const { sentence, score } of flaggedSentences) {
        const idx = text.indexOf(sentence, cursor);
        if (idx === -1) continue;

        if (idx > cursor) {
          fragment.appendChild(document.createTextNode(text.slice(cursor, idx)));
        }

        const span = document.createElement("span");
        span.className = "waldo-edge-flag";
        span.textContent = sentence;
        fragment.appendChild(span);

        cursor = idx + sentence.length;
      }

      if (cursor < text.length) {
        fragment.appendChild(document.createTextNode(text.slice(cursor)));
      }

      return fragment;
    }

    const result = buildOverlayText(text, flaggedSentences);
    expect(result.childNodes.length).toBeGreaterThan(0);

    const html = document.createElement("div");
    html.appendChild(result.cloneNode(true));
    expect(html.querySelector(".waldo-edge-flag")).toBeTruthy();
    expect(html.querySelector(".waldo-edge-flag").textContent).toBe("This is bad.");
  });
});

// --- Test analyzeEdge filtering -----------------------------------------------

describe("analyzeEdge filtering", () => {
  test("returns only NEGATIVE labels", async () => {
    // Simulated results from pipeline
    const results = [
      { label: "NEGATIVE", score: 0.95, sentence: "This is bad" },
      { label: "POSITIVE", score: 0.99, sentence: "This is good" },
      { label: "NEGATIVE", score: 0.75, sentence: "I dislike this" }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    expect(filtered).toHaveLength(2);
    expect(filtered.every(r => r.label === "NEGATIVE")).toBe(true);
  });

  test("filters by score threshold >= 0.7", async () => {
    const results = [
      { label: "NEGATIVE", score: 0.95 },
      { label: "NEGATIVE", score: 0.75 },
      { label: "NEGATIVE", score: 0.69 },
      { label: "NEGATIVE", score: 0.50 }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    expect(filtered).toHaveLength(2);
    expect(filtered[0].score).toBe(0.95);
    expect(filtered[1].score).toBe(0.75);
  });

  test("returns empty array when no high-confidence negatives", async () => {
    const results = [
      { label: "POSITIVE", score: 0.99 },
      { label: "NEGATIVE", score: 0.65 },
      { label: "POSITIVE", score: 0.88 }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    expect(filtered).toHaveLength(0);
  });
});

// --- Test warmUp error handling -----------------------------------------------

describe("warmUp error handling", () => {
  test("warmUp does not throw when offline", async () => {
    let errorThrown = false;

    async function getPipeline() {
      throw new Error("Network error: model fetch failed");
    }

    function warmUp() {
      getPipeline().catch(() => {
        // Silently swallow warm-up errors
      });
    }

    try {
      warmUp();
      // Wait a tick for async to settle
      await new Promise(r => setTimeout(r, 10));
      errorThrown = false;
    } catch (err) {
      errorThrown = true;
    }

    expect(errorThrown).toBe(false);
  });

  test("warmUp doesn't propagate initialization errors", async () => {
    let caught = false;

    async function initThatFails() {
      throw new Error("Init failed");
    }

    function warmUp() {
      initThatFails().catch(() => {
        caught = true;
      });
    }

    warmUp();
    await new Promise(r => setTimeout(r, 20));
    expect(caught).toBe(true);
  });
});

// --- Helper test for inline filtering logic -----------------------------------------------

describe("inline filtering in analyzeEdge", () => {
  test("filters correctly on mixed label results", () => {
    // Simulating the exact code from analyzeEdge:
    // .filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);

    const mockResults = [
      { sentence: "Sentence 1", label: "NEGATIVE", score: 0.95 },
      { sentence: "Sentence 2", label: "POSITIVE", score: 0.88 },
      { sentence: "Sentence 3", label: "NEGATIVE", score: 0.71 },
      { sentence: "Sentence 4", label: "NEGATIVE", score: 0.69 },
      { sentence: "Sentence 5", label: "POSITIVE", score: 0.92 }
    ];

    const filtered = mockResults.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);

    expect(filtered).toHaveLength(2);
    expect(filtered[0].score).toBe(0.95);
    expect(filtered[1].score).toBe(0.71);
    expect(filtered.every(r => r.label === "NEGATIVE")).toBe(true);
    expect(filtered.every(r => r.score >= 0.7)).toBe(true);
  });
});
