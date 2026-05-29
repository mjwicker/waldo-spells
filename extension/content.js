(() => {
  const DEBOUNCE_MS      = 600;
  const EDGE_DEBOUNCE_MS = 1200; // longer — model load can be slow on first call

  // WeakMap keeps tooltip refs without preventing GC of removed inputs
  const tooltipMap      = new WeakMap();
  const edgeOverlayMap  = new WeakMap(); // sentence underline overlays
  let debounceTimer     = null;
  let edgeDebounceTimer = null;

  // ── Injected stylesheet for Edge tier underlines ──────────────────────────

  (function injectEdgeStyles() {
    if (document.getElementById("waldo-edge-styles")) return;
    const style = document.createElement("style");
    style.id = "waldo-edge-styles";
    // .waldo-edge-flag: orange wavy underline — distinct from browser spell-check
    // (which uses red) and Grammarly (blue).  Inline-block keeps it positioned
    // relative to the text span rather than the containing block.
    style.textContent = `
      .waldo-edge-flag {
        text-decoration: underline wavy #f97316;
        text-decoration-thickness: 2px;
        text-underline-offset: 3px;
        cursor: help;
        position: relative;
      }
      .waldo-edge-flag::after {
        content: attr(data-waldo-reason);
        display: none;
        position: absolute;
        left: 0;
        top: 100%;
        margin-top: 4px;
        background: #1a1a2e;
        color: #fed7aa;
        border: 1px solid #f97316;
        border-radius: 5px;
        padding: 5px 10px;
        font: 12px/1.4 system-ui, sans-serif;
        white-space: nowrap;
        z-index: 2147483647;
        pointer-events: none;
      }
      .waldo-edge-flag:hover::after {
        display: block;
      }
    `;
    document.head.appendChild(style);
  })();

  // ── Context detection (per research/context_detection.md) ─────────────────

  function shouldSkip(el) {
    if (el.type === "password") return true;
    if (el.getAttribute("spellcheck") === "false") return true;
    if (el.getAttribute("data-gramm") === "false") return true;
    // Respect Grammarly opt-out attr — we use the same convention
    if (el.getAttribute("data-gramm_editor") === "false") return true;
    // Skip code editors by parent class
    if (el.closest(".CodeMirror, .monaco-editor, .cm-content")) return true;
    return false;
  }

  function getContextHint(el) {
    if (window.location.hostname === "github.com") return "github";
    if (el.matches("#new_comment_field, .js-comment-field, .comment-form-textarea")) {
      return "github";
    }
    return "general";
  }

  // ── Tooltip overlay (fast tier) ───────────────────────────────────────────

  function removeTooltip(el) {
    const tip = tooltipMap.get(el);
    if (tip && tip.parentNode) tip.parentNode.removeChild(tip);
    tooltipMap.delete(el);
  }

  function showTooltip(el, corrections) {
    removeTooltip(el);
    if (!corrections.length) return;

    const tip = document.createElement("div");
    tip.setAttribute("data-waldo-tip", "1");
    tip.style.cssText = [
      "position:absolute",
      "z-index:2147483647",
      "background:#1a1a2e",
      "color:#e0e0e0",
      "border:1px solid #4a4a8a",
      "border-radius:6px",
      "padding:8px 12px",
      "font:13px/1.5 system-ui,sans-serif",
      "max-width:340px",
      "box-shadow:0 4px 14px rgba(0,0,0,.5)",
      "pointer-events:none",
    ].join(";");

    const lines = corrections.map(c => {
      const sugs = c.suggestions.slice(0, 3).join(", ");
      return `<span style="color:#f9a8d4;font-weight:600">«${c.original}»</span>`
           + `&nbsp;→&nbsp;${sugs || "<em style='color:#888'>no suggestions</em>"}`;
    });
    tip.innerHTML = lines.join("<br>");

    document.body.appendChild(tip);
    tooltipMap.set(el, tip);

    // Position below the element, clamped to viewport width
    const rect = el.getBoundingClientRect();
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const scrollX = window.scrollX || document.documentElement.scrollLeft;
    const tipLeft = Math.min(
      rect.left + scrollX,
      document.documentElement.clientWidth - 344 + scrollX,
    );
    tip.style.top  = `${rect.bottom + scrollY + 4}px`;
    tip.style.left = `${Math.max(0, tipLeft)}px`;
  }

  // ── Edge tier underline overlay ───────────────────────────────────────────
  //
  // For plain <textarea>/<input> elements we cannot wrap individual words/sentences
  // with HTML spans — the content is plain text. Instead we render an overlay
  // <div> that mirrors the textarea geometry and contains reconstructed text with
  // flagged sentences wrapped in <span class="waldo-edge-flag">.
  //
  // The overlay sits beneath the textarea (z-index lower) with pointer-events:none
  // so it doesn't interfere with typing. Wavy underlines from the spans show
  // through the (transparent-background) textarea.
  //
  // Limitation: only works when the textarea uses a standard monospace or system
  // font. Custom webfonts may cause slight misalignment. This is acceptable for
  // the v0.4.0 Edge tier milestone.

  function removeEdgeOverlay(el) {
    const overlay = edgeOverlayMap.get(el);
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    edgeOverlayMap.delete(el);
  }

  function buildOverlayText(text, flaggedSentences) {
    if (!flaggedSentences.length) return document.createTextNode(text);

    const fragment = document.createDocumentFragment();
    let cursor = 0;

    for (const { sentence, score } of flaggedSentences) {
      const idx = text.indexOf(sentence, cursor);
      if (idx === -1) continue;

      // Plain text before this sentence
      if (idx > cursor) {
        fragment.appendChild(document.createTextNode(text.slice(cursor, idx)));
      }

      // Flagged sentence span
      const span = document.createElement("span");
      span.className = "waldo-edge-flag";
      const pct = Math.round(score * 100);
      span.setAttribute("data-waldo-reason", `Negative tone (${pct}% confidence)`);
      span.textContent = sentence;
      fragment.appendChild(span);

      cursor = idx + sentence.length;
    }

    // Remaining text
    if (cursor < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(cursor)));
    }

    return fragment;
  }

  function syncOverlay(el, flaggedSentences) {
    removeEdgeOverlay(el);
    if (!flaggedSentences.length) return;

    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) return;

    // Compute computed style once to mirror the textarea faithfully
    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const scrollTop  = window.scrollY || document.documentElement.scrollTop;
    const scrollLeft = window.scrollX || document.documentElement.scrollLeft;

    const overlay = document.createElement("div");
    overlay.setAttribute("data-waldo-edge-overlay", "1");
    overlay.style.cssText = [
      `position:absolute`,
      `top:${rect.top + scrollTop}px`,
      `left:${rect.left + scrollLeft}px`,
      `width:${rect.width}px`,
      `height:${rect.height}px`,
      `padding:${cs.padding}`,
      `border:${cs.border}`,
      `font:${cs.font}`,
      `line-height:${cs.lineHeight}`,
      `letter-spacing:${cs.letterSpacing}`,
      `word-spacing:${cs.wordSpacing}`,
      `white-space:pre-wrap`,
      `overflow:hidden`,
      `background:transparent`,
      // Render behind the textarea so the overlay underlines show through
      `z-index:${parseInt(cs.zIndex || "0", 10) - 1}`,
      `pointer-events:none`,
      `box-sizing:${cs.boxSizing}`,
      `color:transparent`,     // hide text — only underline decorations visible
    ].join(";");

    overlay.appendChild(buildOverlayText(text, flaggedSentences));
    document.body.appendChild(overlay);
    edgeOverlayMap.set(el, overlay);
  }

  // ── Analysis ──────────────────────────────────────────────────────────────

  async function analyze(el) {
    if (shouldSkip(el)) return;
    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) { removeTooltip(el); return; }

    try {
      const resp = await browser.runtime.sendMessage({
        action: "analyze",
        text,
        context_hint: getContextHint(el),
      });
      if (resp && Array.isArray(resp.corrections)) {
        showTooltip(el, resp.corrections);
      }
    } catch (_) {
      // Background script unreachable or extension disabled — silent fail
    }
  }

  async function analyzeEdge(el) {
    if (shouldSkip(el)) return;
    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) { removeEdgeOverlay(el); return; }

    try {
      const resp = await browser.runtime.sendMessage({
        action: "edge_analyze",
        text,
      });
      if (resp && Array.isArray(resp.sentences)) {
        syncOverlay(el, resp.sentences);
      }
    } catch (_) {
      // Edge worker unavailable — silent fail, degraded gracefully
    }
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  function onInput(e) {
    clearTimeout(debounceTimer);
    clearTimeout(edgeDebounceTimer);
    removeTooltip(e.target);
    removeEdgeOverlay(e.target);

    debounceTimer     = setTimeout(() => analyze(e.target), DEBOUNCE_MS);
    edgeDebounceTimer = setTimeout(() => analyzeEdge(e.target), EDGE_DEBOUNCE_MS);
  }

  function onBlur(e) {
    // Analyze immediately on blur (no debounce — user has finished typing)
    clearTimeout(debounceTimer);
    clearTimeout(edgeDebounceTimer);
    analyze(e.target);
    analyzeEdge(e.target);
  }

  function onFocus(e) {
    removeTooltip(e.target);
    removeEdgeOverlay(e.target);
  }

  // ── Attachment ────────────────────────────────────────────────────────────

  function attach(el) {
    if (el._waldoAttached) return;
    el._waldoAttached = true;
    el.addEventListener("input", onInput);
    el.addEventListener("blur",  onBlur);
    el.addEventListener("focus", onFocus);
  }

  function attachAll() {
    document.querySelectorAll(
      'textarea, input[type="text"], input:not([type])',
    ).forEach(attach);
  }

  attachAll();

  // Watch for dynamically added inputs (SPAs, modal forms, infinite scroll)
  const observer = new MutationObserver(attachAll);
  observer.observe(document.body, { childList: true, subtree: true });
})();
