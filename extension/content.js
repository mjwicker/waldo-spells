(() => {
  const DEBOUNCE_MS = 600;

  // WeakMap keeps tooltip refs without preventing GC of removed inputs
  const tooltipMap = new WeakMap();
  let debounceTimer = null;

  // ── Context detection (per research/context_detection.md) ────────────────

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

  // ── Tooltip overlay ───────────────────────────────────────────────────────

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

  // ── Event handlers ────────────────────────────────────────────────────────

  function onInput(e) {
    clearTimeout(debounceTimer);
    removeTooltip(e.target);
    debounceTimer = setTimeout(() => analyze(e.target), DEBOUNCE_MS);
  }

  function onBlur(e) {
    // Analyze immediately on blur (no debounce — user has finished typing)
    clearTimeout(debounceTimer);
    analyze(e.target);
  }

  function onFocus(e) {
    removeTooltip(e.target);
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
