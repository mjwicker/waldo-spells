(() => {
  const DEBOUNCE_MS       = 600;
  const EDGE_DEBOUNCE_MS  = 600;  // reduced — warmUp() ensures pipeline is hot on first keypress
  const SMART_DEBOUNCE_MS = 800;  // per-paragraph; fires after double-newline only

  // WeakMap keeps tooltip refs without preventing GC of removed inputs
  const tooltipMap       = new WeakMap();
  const edgeOverlayMap   = new WeakMap(); // sentence underline overlays
  const smartOverlayMap  = new WeakMap(); // Smart tier correction overlays
  let debounceTimer      = null;
  let edgeDebounceTimer  = null;
  let smartDebounceTimer = null;

  // Cached availability of Smart tier (updated on first /smart_status check).
  // Prevents hammering the server on every keystroke.
  let _smartAvailable    = null;  // null = unknown; true/false = known

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

    for (const [i, c] of corrections.entries()) {
      if (i > 0) tip.appendChild(document.createElement("br"));
      const origSpan = document.createElement("span");
      origSpan.style.cssText = "color:#f9a8d4;font-weight:600";
      origSpan.textContent = `«${c.original}»`;  // user text — textContent only
      tip.appendChild(origSpan);
      tip.appendChild(document.createTextNode(" → "));
      const sugs = c.suggestions.slice(0, 3).join(", ");
      if (sugs) {
        tip.appendChild(document.createTextNode(sugs));
      } else {
        const em = document.createElement("em");
        em.style.color = "#888";
        em.textContent = "no suggestions";
        tip.appendChild(em);
      }
    }

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
      // Render above page elements; pointer-events:none lets typing through
      `z-index:2147483646`,
      `pointer-events:none`,
      `box-sizing:${cs.boxSizing}`,
      `color:transparent`,     // hide text — only underline decorations visible
    ].join(";");

    overlay.appendChild(buildOverlayText(text, flaggedSentences));
    document.body.appendChild(overlay);
    edgeOverlayMap.set(el, overlay);
  }

  // ── Smart tier overlay ────────────────────────────────────────────────────
  //
  // The Smart tier surfaces inline rewrite suggestions (Grammarly-style) for
  // passive voice, tone, and grammar.  Corrections are rendered as a floating
  // badge list below the active element — not as an overlay mirror — because
  // Smart corrections may span multiple words and need space to show both the
  // original phrase and the rewrite suggestion side-by-side.
  //
  // Degradation: if the hardware gate fails the badge shows a short status
  // message instead of corrections. Edge tier continues to fire normally.

  function removeSmartOverlay(el) {
    const badge = smartOverlayMap.get(el);
    if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
    smartOverlayMap.delete(el);
  }

  function showSmartBadge(el, result) {
    removeSmartOverlay(el);

    const badge = document.createElement("div");
    badge.setAttribute("data-waldo-smart", "1");
    badge.style.cssText = [
      "position:absolute",
      "z-index:2147483647",
      "background:#1a1a2e",
      "color:#e0e0e0",
      "border:1px solid #6060c0",
      "border-radius:6px",
      "padding:8px 12px",
      "font:13px/1.5 system-ui,sans-serif",
      "max-width:380px",
      "box-shadow:0 4px 14px rgba(0,0,0,.5)",
      "pointer-events:none",
    ].join(";");

    if (!result.available) {
      // Hardware gate or server-offline message
      const labelSpan = document.createElement("span");
      labelSpan.style.cssText = "color:#facc15;font-weight:600";
      labelSpan.textContent = "Waldo Smart:";
      const msgSpan = document.createElement("span");
      msgSpan.style.color = "#9ca3af";
      msgSpan.textContent = " " + (result.message || "Smart tier unavailable");  // server text
      badge.append(labelSpan, msgSpan);
    } else {
      const corrections = result.corrections ?? [];
      if (!corrections.length) return; // nothing to show

      const headerSpan = document.createElement("span");
      headerSpan.style.cssText = "color:#818cf8;font-weight:600;display:block;margin-bottom:4px";
      headerSpan.textContent = "Waldo Smart suggestions";
      badge.appendChild(headerSpan);
      for (const [i, c] of corrections.slice(0, 5).entries()) {
        if (i > 0) badge.appendChild(document.createElement("br"));
        const origSpan = document.createElement("span");
        origSpan.style.cssText = "color:#f9a8d4;font-weight:600";
        origSpan.textContent = `«${c.original}»`;  // user text — textContent only
        badge.appendChild(origSpan);
        badge.appendChild(document.createTextNode(" → "));
        const sug = (c.suggestions ?? []).slice(0, 2).join(" / ");
        if (sug) {
          badge.appendChild(document.createTextNode(sug));
        } else {
          const em = document.createElement("em");
          em.style.color = "#888";
          em.textContent = "see context";
          badge.appendChild(em);
        }
      }
    }

    document.body.appendChild(badge);
    smartOverlayMap.set(el, badge);

    // Position directly below the element
    const rect = el.getBoundingClientRect();
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const scrollX = window.scrollX || document.documentElement.scrollLeft;
    const badgeLeft = Math.min(
      rect.left + scrollX,
      document.documentElement.clientWidth - 384 + scrollX,
    );
    badge.style.top  = `${rect.bottom + scrollY + 6}px`;
    badge.style.left = `${Math.max(0, badgeLeft)}px`;

    // Auto-dismiss after 12 s so the badge doesn't linger after the user moves on
    setTimeout(() => removeSmartOverlay(el), 12000);
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
        console.log(`[WaldoSpells][fast] ${text.length}ch → ${resp.corrections.length} corrections`);
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
      const ts_content_send = Date.now();
      const resp = await browser.runtime.sendMessage({ action: "edge_analyze", text, ts_content_send });
      const n = resp?.sentences?.length ?? 0;
      const latency_total = resp?.ts_content_send ? Date.now() - resp.ts_content_send : null;
      console.log(`[WaldoSpells][edge] ${text.length}ch → ${n} flagged${latency_total ? ` (${latency_total}ms)` : ""}`);
      if (resp && Array.isArray(resp.sentences)) {
        syncOverlay(el, resp.sentences);
      }
    } catch (err) {
      console.error(`[WaldoSpells][edge] ✗`, err.message);
    }
  }

  // Analyze the most-recently-completed paragraph through the Smart tier.
  //
  // Trigger conditions (either):
  //   1. User typed a double newline (paragraph boundary) — per-paragraph mode.
  //   2. Toolbar button pressed — on-demand for current element's full text.
  //
  // When _smartAvailable is false we still send the request once so the badge
  // can display the hardware-gate message.  After that we suppress further
  // requests until the user explicitly triggers on-demand (toolbar button).
  async function analyzeSmartEl(el, { onDemand = false } = {}) {
    if (shouldSkip(el)) return;
    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) { removeSmartOverlay(el); return; }

    // Suppress auto (non-demand) triggers once we know Smart is unavailable
    if (!onDemand && _smartAvailable === false) return;

    // For auto triggers, analyze only the most-recently-completed paragraph
    // (the text before the last double-newline boundary), not the full text.
    // This keeps the request small and latency predictable.
    let paragraph = text;
    if (!onDemand) {
      const idx = text.lastIndexOf("\n\n");
      if (idx === -1) return; // no complete paragraph yet
      paragraph = text.slice(0, idx).trim();
      if (!paragraph) return;
      // Take only the last paragraph (text after the previous \n\n)
      const prev = paragraph.lastIndexOf("\n\n");
      if (prev !== -1) paragraph = paragraph.slice(prev + 2).trim();
      if (!paragraph) return;
    }

    try {
      const resp = await browser.runtime.sendMessage({
        action: "smart_analyze",
        text: paragraph,
        context_hint: getContextHint(el),
      });
      if (resp) {
        _smartAvailable = resp.available ?? true;
        const nc = (resp.corrections ?? []).length;
        const status = resp.available ? `${nc} corrections` : `unavailable`;
        console.log(`[WaldoSpells][smart] ${paragraph.length}ch → ${status}`);
        showSmartBadge(el, resp);
      }
    } catch (_) {
      // Background script unreachable — silent fail; Edge tier continues
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

    // Smart tier: trigger on paragraph boundary (double newline).
    // We peek at the raw input event data to detect the second newline without
    // walking the full textarea value on every keystroke.
    const val = e.target.value ?? e.target.innerText ?? "";
    if (val.includes("\n\n")) {
      clearTimeout(smartDebounceTimer);
      smartDebounceTimer = setTimeout(
        () => analyzeSmartEl(e.target, { onDemand: false }),
        SMART_DEBOUNCE_MS,
      );
    }
  }

  function onBlur(e) {
    // Analyze immediately on blur (no debounce — user has finished typing)
    clearTimeout(debounceTimer);
    clearTimeout(edgeDebounceTimer);
    analyze(e.target);
    analyzeEdge(e.target);
    // Smart: don't auto-trigger on blur — paragraphs are the natural boundary
  }

  function onFocus(e) {
    removeTooltip(e.target);
    removeEdgeOverlay(e.target);
    // Leave smart overlay in place on focus — user may still be reading suggestions
  }

  // ── On-demand Smart trigger (toolbar button → message from popup) ──────────
  //
  // popup.js sends { action: "smart_demand", tabId } via runtime.sendMessage.
  // background.js relays it to the content script as { action: "smart_demand" }.
  // We listen here and call analyzeSmartEl on the currently-focused element.

  browser.runtime.onMessage.addListener((msg) => {
    if (msg.action !== "smart_demand") return;
    const el = document.activeElement;
    if (
      el &&
      !shouldSkip(el) &&
      (el.tagName === "TEXTAREA" ||
       el.tagName === "INPUT" ||
       el.isContentEditable)
    ) {
      analyzeSmartEl(el, { onDemand: true });
    }
  });

  // ── Attachment ────────────────────────────────────────────────────────────

  function attach(el) {
    if (el._waldoAttached) return;
    el._waldoAttached = true;
    el.addEventListener("input", onInput);
    el.addEventListener("blur",  onBlur);
    el.addEventListener("focus", onFocus);
  }

  function attachAll() {
    const els = document.querySelectorAll('textarea, input[type="text"], input:not([type])');
    const before = [...els].filter(e => !e._waldoAttached).length;
    els.forEach(attach);
    if (before > 0) console.log(`[WaldoSpells] attached to ${before} new input(s)`);
  }

  attachAll();

  // Watch for dynamically added inputs (SPAs, modal forms, infinite scroll)
  const observer = new MutationObserver(attachAll);
  observer.observe(document.body, { childList: true, subtree: true });
})();
