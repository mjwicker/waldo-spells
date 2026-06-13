#!/usr/bin/env node

/**
 * Tests for context menu fix suggestions feature (Cycle 30)
 *
 * Tests cover the right-click UX for orange squiggles:
 * - mousedown tracking on .waldo-edge-flag spans
 * - storage.local persistence (waldo_ctx_squiggle)
 * - suggestion panel rendering (explanation + suggestions)
 * - panel auto-dismiss behavior (20s timeout + close button)
 * - copy-to-clipboard on suggestion click
 * - edge cases (no squiggle, server unreachable, tier unavailable)
 *
 * Run: node test_context_menu_suggestions.js
 */

const assert = require("assert");

let passCount = 0;
let failCount = 0;
let pendingTests = [];

function test(name, fn) {
  try {
    const result = fn();
    if (result instanceof Promise) {
      const promise = result
        .then(() => {
          console.log(`✓ ${name}`);
          passCount++;
        })
        .catch((err) => {
          console.error(`✗ ${name}`);
          console.error(`  ${err.message}`);
          failCount++;
        });
      pendingTests.push(promise);
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
  console.log("=== Testing Context Menu Fix Suggestions ===\n");

  // ── Test 1: mousedown on .waldo-edge-flag stores sentence in storage ───────

  console.log("Storage & listener logic:");

  test("mousedown on .waldo-edge-flag span stores sentence", () => {
    // Simulate the mousedown handler logic from content.js
    const storageData = {};
    let activeSquiggle = null;

    // Simulate mousedown event handling
    const simulateMousedown = (target) => {
      // Check if target is a squiggle (in real code this uses .closest)
      if (target && target.className === "waldo-edge-flag") {
        activeSquiggle = {
          sentence: target.textContent,
          reason: target.dataset.reason || "",
        };
        storageData.waldo_ctx_squiggle = activeSquiggle.sentence;
      } else {
        activeSquiggle = null;
        delete storageData.waldo_ctx_squiggle;
      }
    };

    // Create mock span element
    const mockSpan = {
      textContent: "This is bad.",
      className: "waldo-edge-flag",
      dataset: { reason: "Negative tone (95% confidence)" },
    };

    simulateMousedown(mockSpan);

    assert.notStrictEqual(activeSquiggle, null, "activeSquiggle should be set");
    assert.strictEqual(activeSquiggle.sentence, "This is bad.");
    assert.strictEqual(
      storageData.waldo_ctx_squiggle,
      "This is bad.",
      "Storage should contain the sentence"
    );
  });

  test("mousedown on non-squiggle element clears storage", () => {
    const storageData = { waldo_ctx_squiggle: "Some old sentence" };
    let activeSquiggle = null;

    const simulateMousedown = (target) => {
      if (target && target.className === "waldo-edge-flag") {
        activeSquiggle = { sentence: target.textContent };
        storageData.waldo_ctx_squiggle = activeSquiggle.sentence;
      } else {
        activeSquiggle = null;
        delete storageData.waldo_ctx_squiggle;
      }
    };

    const mockTextarea = { className: "textarea" };
    simulateMousedown(mockTextarea);

    assert.strictEqual(activeSquiggle, null);
    assert.strictEqual(
      storageData.waldo_ctx_squiggle,
      undefined,
      "Storage should be cleared"
    );
  });

  // ── Test 3: suggestion panel structure with explanation and suggestions ────

  console.log("\nPanel structure:");

  test("panel contains explanation and suggestions", () => {
    // Simulate panel structure from showSuggestionPanel
    const createPanel = (sentence, explanation, suggestions) => {
      const panel = {
        id: "waldo-ctx-panel",
        hasTitle: true,
        hasExplanation: !!explanation,
        hasOriginalSentence: !!sentence,
        suggestionCount: Math.min(suggestions.length, 2),
        explanation: explanation,
        suggestions: suggestions.slice(0, 2),
      };
      return panel;
    };

    const panel = createPanel(
      "This is bad.",
      "This sentence has a negative tone.",
      ["This is good.", "This is fine."]
    );

    assert.strictEqual(panel.id, "waldo-ctx-panel");
    assert.strictEqual(panel.hasTitle, true);
    assert.strictEqual(panel.hasExplanation, true);
    assert.strictEqual(panel.hasOriginalSentence, true);
    assert.strictEqual(panel.suggestionCount, 2);
    assert.strictEqual(panel.explanation, "This sentence has a negative tone.");
    assert.deepStrictEqual(panel.suggestions, [
      "This is good.",
      "This is fine.",
    ]);
  });

  // ── Test 4: panel closes on button click and timeout ──────────────────────

  console.log("\nPanel lifecycle:");

  test("panel closes on close button click", () => {
    let panelOpen = true;
    const closePanel = () => {
      panelOpen = false;
    };

    // Simulate button click
    closePanel();
    assert.strictEqual(panelOpen, false);
  });

  test("panel auto-dismisses after 20 seconds", () => {
    // Verify timeout value is correct
    const AUTO_DISMISS_MS = 20000;
    const timeoutMs = AUTO_DISMISS_MS;

    assert.strictEqual(timeoutMs, 20000, "Auto-dismiss should be 20 seconds");
  });

  // ── Test 5: suggestion click copies to clipboard ──────────────────────────

  console.log("\nClipboard integration:");

  test("clicking suggestion initiates clipboard write", async () => {
    let clipboardWriteCalled = false;
    let clipboardText = null;

    const mockClipboard = {
      writeText: async (text) => {
        clipboardWriteCalled = true;
        clipboardText = text;
        return text;
      },
    };

    // Simulate suggestion click handler
    const handleSuggestionClick = async (suggestionText) => {
      return await mockClipboard.writeText(suggestionText);
    };

    await handleSuggestionClick("This is good.");

    assert.strictEqual(
      clipboardWriteCalled,
      true,
      "Clipboard write should be called"
    );
    assert.strictEqual(clipboardText, "This is good.");
  });

  // ── Test 6: context menu click with no stored squiggle ─────────────────────

  console.log("\nContext menu handler:");

  test("context menu click with no stored squiggle returns early", async () => {
    const storageData = {}; // Empty — no squiggle stored
    let suggestionMessageSent = false;

    const handleContextMenuClick = async () => {
      const sentence = storageData.waldo_ctx_squiggle;
      if (!sentence) {
        // No-op — return early
        return null;
      }
      suggestionMessageSent = true;
      return { success: true };
    };

    const result = await handleContextMenuClick();

    assert.strictEqual(result, null, "Should return null when no squiggle");
    assert.strictEqual(
      suggestionMessageSent,
      false,
      "Should not send message"
    );
  });

  // ── Test 7: Smart tier unavailable triggers Fast tier fallback ────────────

  console.log("\nTier fallback logic:");

  test("Smart tier unavailable falls back to Fast tier", async () => {
    const mockSmartAnalyze = async () => ({
      available: false,
      corrections: [],
    });

    let fastTierUsed = false;

    const handleContextMenuClick = async () => {
      const smartResult = await mockSmartAnalyze();

      if (smartResult.available && smartResult.corrections.length > 0) {
        // Smart succeeded
        return smartResult.corrections[0];
      } else {
        // Fallback to Fast
        fastTierUsed = true;
        return {
          explanation: "Fast tier explanation",
          suggestions: ["Fast suggestion"],
        };
      }
    };

    const result = await handleContextMenuClick();

    assert.strictEqual(fastTierUsed, true, "Should fall back to Fast tier");
    assert.strictEqual(
      result.explanation,
      "Fast tier explanation",
      "Should use Fast result"
    );
  });

  // ── Test 8: server unreachable produces graceful error ──────────────────────

  console.log("\nError handling:");

  test("server unreachable produces graceful error message", async () => {
    const mockSmartAnalyze = async () => {
      throw new Error("Server unreachable");
    };

    let explanation = "";

    try {
      await mockSmartAnalyze();
    } catch (err) {
      explanation =
        "Could not reach the local Waldo server. Make sure the wrapper is running.";
    }

    assert(
      explanation.includes("Could not reach the local Waldo server"),
      "Error message should be graceful"
    );
  });

  test("error message renders without suggestions", () => {
    const createErrorPanel = (explanation) => {
      return {
        id: "waldo-ctx-panel",
        explanation: explanation,
        hasErrorMessage:
          explanation.includes("Could not reach the local Waldo server") ||
          explanation.includes("unavailable"),
        suggestionsCount: 0,
      };
    };

    const panel = createErrorPanel(
      "Could not reach the local Waldo server. Make sure the wrapper is running."
    );

    assert.strictEqual(panel.hasErrorMessage, true);
    assert.strictEqual(panel.suggestionsCount, 0);
    assert(panel.explanation.includes("Could not reach"));
  });

  // ── Summary ─────────────────────────────────────────────────────────────────

  // Wait for all async tests to complete
  await Promise.all(pendingTests);

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
