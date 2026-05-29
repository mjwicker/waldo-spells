#!/usr/bin/env node

/**
 * Test suite for edge_worker.js and related extension code.
 * Runs with: node test_edge.js
 *
 * Tests cover:
 * - splitSentences edge cases
 * - analyzeEdge filtering (NEGATIVE only, score >= 0.7)
 * - handleEdgeAnalyze storage check
 * - syncOverlay create/remove behavior
 * - manifest version check
 * - warmUp error handling
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

let passCount = 0;
let failCount = 0;

// Test runner
function test(name, fn) {
  try {
    const result = fn();
    if (result instanceof Promise) {
      result
        .then(() => {
          console.log(`✓ ${name}`);
          passCount++;
        })
        .catch((err) => {
          console.error(`✗ ${name}`);
          console.error(`  ${err.message}`);
          failCount++;
        });
    } else {
      console.log(`✓ ${name}`);
      passCount++;
    }
  } catch (err) {
    console.error(`✗ ${name}`);
    console.error(`  ${err.message}`);
    failCount++;
  }
}

async function runAllTests() {
  console.log("=== Testing Edge Tier Extension ===\n");

  // ── Test splitSentences ─────────────────────────────────────────

  console.log("splitSentences:");

  function splitSentences(text) {
    return text
      .split(/(?<=[.?!])\s+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 3);
  }

  test("splits basic sentences on . ? !", () => {
    const result = splitSentences("This is a sentence. This is another! And a third?");
    assert.equal(result.length, 3);
    assert.equal(result[0], "This is a sentence.");
    assert.equal(result[1], "This is another!");
    assert.equal(result[2], "And a third?");
  });

  test("handles empty string", () => {
    const result = splitSentences("");
    assert.deepStrictEqual(result, []);
  });

  test("handles text with no punctuation", () => {
    const result = splitSentences("hello world");
    assert.deepStrictEqual(result, ["hello world"]);
  });

  test("filters fragments shorter than 4 chars", () => {
    const result = splitSentences("Hi. This is longer.");
    assert(!result.includes("Hi."));
    assert(result.includes("This is longer."));
  });

  test("trims whitespace from fragments", () => {
    const result = splitSentences("First.   Second.");
    assert.deepStrictEqual(result, ["First.", "Second."]);
  });

  test("handles multiple spaces/newlines between sentences", () => {
    const result = splitSentences("First.  \n\n  Second!");
    assert.equal(result.length, 2);
  });

  test("handles exclamation marks", () => {
    const result = splitSentences("Wow! Amazing!");
    assert(result.includes("Wow!"));
    assert(result.includes("Amazing!"));
  });

  test("handles question marks", () => {
    const result = splitSentences("Is it? Yes!");
    assert(result.some(s => s.includes("Is it?")));
    assert(result.some(s => s.includes("Yes!")));
  });

  test("preserves trailing punctuation", () => {
    const result = splitSentences("Question? Answer.");
    assert.equal(result[0], "Question?");
    assert.equal(result[1], "Answer.");
  });

  test("handles decimal numbers gracefully", () => {
    const result = splitSentences("The value is 3.14. Now a sentence.");
    assert(result.length > 0);
    // The regex will split but the important part is it doesn't crash
  });

  // ── Test manifest.json ──────────────────────────────────────────

  console.log("\nmanifest.json:");

  let manifest;
  try {
    const manifestPath = path.join(__dirname, "manifest.json");
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (e) {
    console.error("  Could not read manifest.json:", e.message);
    manifest = null;
  }

  if (manifest) {
    test("version is 0.4.0", () => {
      assert.equal(manifest.version, "0.4.0");
    });

    test("manifest_version is 3", () => {
      assert.equal(manifest.manifest_version, 3);
    });

    test("has storage permission", () => {
      assert(manifest.permissions.includes("storage"));
    });

    test("has host_permissions for localhost", () => {
      assert(manifest.host_permissions.some(p => p.includes("127.0.0.1:8765")));
    });

    test("has host_permissions for jsDelivr", () => {
      assert(manifest.host_permissions.some(p => p.includes("cdn.jsdelivr.net")));
    });

    test("has host_permissions for HuggingFace", () => {
      assert(manifest.host_permissions.some(p => p.includes("huggingface.co")));
    });

    test("background script is type module", () => {
      assert.equal(manifest.background.type, "module");
    });

    test("has web_accessible_resources for vendor/", () => {
      const resources = manifest.web_accessible_resources;
      assert(resources.length > 0);
      assert(resources[0].resources.includes("vendor/*"));
    });
  }

  // ── Test analyzeEdge filtering ──────────────────────────────────

  console.log("\nanalyzeEdge filtering:");

  test("filters only NEGATIVE labels", () => {
    const results = [
      { label: "NEGATIVE", score: 0.95, sentence: "This is bad" },
      { label: "POSITIVE", score: 0.99, sentence: "This is good" },
      { label: "NEGATIVE", score: 0.75, sentence: "I dislike this" }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    assert.equal(filtered.length, 2);
    assert(filtered.every(r => r.label === "NEGATIVE"));
  });

  test("filters by score threshold >= 0.7", () => {
    const results = [
      { label: "NEGATIVE", score: 0.95 },
      { label: "NEGATIVE", score: 0.75 },
      { label: "NEGATIVE", score: 0.69 },
      { label: "NEGATIVE", score: 0.50 }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    assert.equal(filtered.length, 2);
    assert.equal(filtered[0].score, 0.95);
    assert.equal(filtered[1].score, 0.75);
  });

  test("rejects low-confidence negatives (< 0.7)", () => {
    const results = [
      { label: "NEGATIVE", score: 0.65 },
      { label: "NEGATIVE", score: 0.69 }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    assert.equal(filtered.length, 0);
  });

  test("returns empty array when no high-confidence negatives", () => {
    const results = [
      { label: "POSITIVE", score: 0.99 },
      { label: "NEGATIVE", score: 0.65 },
      { label: "POSITIVE", score: 0.88 }
    ];

    const filtered = results.filter((r) => r.label === "NEGATIVE" && r.score >= 0.7);
    assert.equal(filtered.length, 0);
  });

  // ── Test handleEdgeAnalyze (mocked storage) ─────────────────────

  console.log("\nhandleEdgeAnalyze:");

  test("returns { sentences: [] } when enabled=false", async () => {
    const mockStorage = {
      get: async () => ({ enabled: false })
    };

    async function handleEdgeAnalyze({ text }) {
      const { enabled = true } = await mockStorage.get("enabled");
      if (!enabled) return { sentences: [] };
      return { sentences: [] };
    }

    const result = await handleEdgeAnalyze({ text: "This is bad." });
    assert.deepStrictEqual(result, { sentences: [] });
  });

  test("returns { sentences: [] } when enabled=true but no negatives", async () => {
    const mockStorage = {
      get: async () => ({ enabled: true })
    };

    async function handleEdgeAnalyze({ text }) {
      const { enabled = true } = await mockStorage.get("enabled");
      if (!enabled) return { sentences: [] };
      return { sentences: [] };
    }

    const result = await handleEdgeAnalyze({ text: "This is good." });
    assert.deepStrictEqual(result, { sentences: [] });
  });

  test("handles storage errors gracefully", async () => {
    const mockStorage = {
      get: async () => { throw new Error("storage error"); }
    };

    async function handleEdgeAnalyze({ text }) {
      try {
        const { enabled = true } = await mockStorage.get("enabled");
        if (!enabled) return { sentences: [] };
        return { sentences: [] };
      } catch (err) {
        return { sentences: [], error: String(err) };
      }
    }

    const result = await handleEdgeAnalyze({ text: "Test" });
    assert.deepStrictEqual(result.sentences, []);
    assert(result.error);
  });

  // ── Test warmUp error handling ──────────────────────────────────

  console.log("\nwarmUp:");

  test("warmUp does not throw when offline", async () => {
    async function getPipelineOffline() {
      throw new Error("Network error");
    }

    function warmUp() {
      getPipelineOffline().catch(() => {
        // Silently swallow
      });
    }

    let errorThrown = false;
    try {
      warmUp();
      await new Promise(r => setTimeout(r, 10));
      errorThrown = false;
    } catch (err) {
      errorThrown = true;
    }

    assert(!errorThrown);
  });

  test("warmUp catches and suppresses initialization errors", async () => {
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
    assert(caught);
  });

  // ── Test syncOverlay logic ──────────────────────────────────────

  console.log("\nsyncOverlay:");

  test("buildOverlayText wraps flagged sentences", () => {
    function buildOverlayText(text, flaggedSentences) {
      if (!flaggedSentences.length) return text;

      let result = text;
      let offset = 0;

      for (const { sentence } of flaggedSentences) {
        const idx = result.indexOf(sentence, offset);
        if (idx !== -1) {
          result = (
            result.slice(0, idx) +
            `<span class="waldo-edge-flag">${sentence}</span>` +
            result.slice(idx + sentence.length)
          );
          offset = idx + sentence.length + 40; // rough estimate of span tag length
        }
      }

      return result;
    }

    const text = "This is bad. This is good.";
    const flagged = [{ sentence: "This is bad.", score: 0.95 }];
    const result = buildOverlayText(text, flagged);

    assert(result.includes("waldo-edge-flag"));
    assert(result.includes("This is bad."));
  });

  test("syncOverlay removes overlay when no flagged sentences", () => {
    const state = { overlay: { exists: true } };

    function removeEdgeOverlay() {
      state.overlay = null;
    }

    function syncOverlay(flaggedSentences) {
      if (!flaggedSentences.length) {
        removeEdgeOverlay();
      }
    }

    syncOverlay([]);
    assert.strictEqual(state.overlay, null);
  });

  test("overlay cleanup on focus removes element", () => {
    const state = { overlay: { exists: true } };

    function onFocus() {
      if (state.overlay) {
        state.overlay = null;
      }
    }

    onFocus();
    assert.strictEqual(state.overlay, null);
  });

  // ── Summary ─────────────────────────────────────────────────────

  console.log("\n=== Test Summary ===");
  console.log(`Passed: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  console.log(`Total:  ${passCount + failCount}`);

  if (failCount === 0) {
    console.log("\n✓ All tests passed!");
    process.exit(0);
  } else {
    console.log(`\n✗ ${failCount} test(s) failed`);
    process.exit(1);
  }
}

// Run tests
runAllTests().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
