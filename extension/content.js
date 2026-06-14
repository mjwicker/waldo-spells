(() => {
  const DEBOUNCE_MS       = 600;
  const EDGE_DEBOUNCE_MS  = 600;
  const SMART_DEBOUNCE_MS = 800;

  // WeakMap keeps overlay/badge refs without preventing GC of removed inputs
  const fastOverlayMap  = new WeakMap(); // per-word red underlines (Fast/spelling tier)
  const edgeOverlayMap  = new WeakMap(); // per-sentence yellow underlines (Edge/grammar tier)
  const smartOverlayMap = new WeakMap(); // Smart tier correction badge
  const toneBadgeMap    = new WeakMap(); // tone indicator (bottom-right of element)
  const correctionsCache = new WeakMap(); // el → [{start,end,original,suggestions}] for context menu + click-replace

  let debounceTimer      = null;
  let edgeDebounceTimer  = null;
  let smartDebounceTimer = null;

  let _smartAvailable = null; // null=unknown; true/false=known

  // ── Injected stylesheet ───────────────────────────────────────────────────

  (function injectStyles() {
    if (document.getElementById("waldo-styles")) return;
    const style = document.createElement("style");
    style.id = "waldo-styles";
    style.textContent = `
      /* Fast tier: flat red underline — spelling errors.
         Flat (not wavy) like Grammarly, thin 1.5px, tight 2px offset.
         Distinct from browser's native wavy red squiggle on the same word.
         pointer-events:auto overrides the parent overlay's pointer-events:none
         so hover tooltips work even though the overlay is passthrough. */
      .waldo-fast-flag {
        text-decoration: underline;
        text-decoration-color: #ef4444;
        text-decoration-thickness: 1.5px;
        text-underline-offset: 2px;
        cursor: help;
        position: relative;
        pointer-events: auto;
      }
      .waldo-fast-flag::after {
        content: attr(data-waldo-suggestions);
        display: none;
        position: absolute;
        left: 0;
        top: 1.4em;
        background: #1a1a2e;
        color: #fca5a5;
        border: 1px solid #ef4444;
        border-radius: 5px;
        padding: 5px 10px;
        font: 12px/1.4 system-ui, sans-serif;
        white-space: nowrap;
        z-index: 2147483647;
        pointer-events: none;
      }
      .waldo-fast-flag:hover::after {
        display: block;
      }

      /* Edge tier: flat yellow/amber underline — grammar and tone issues.
         Matches Grammarly's convention for grammar-level suggestions.
         pointer-events:auto so hover tooltip works. */
      .waldo-edge-flag {
        text-decoration: underline;
        text-decoration-color: #f59e0b;
        text-decoration-thickness: 1.5px;
        text-underline-offset: 2px;
        cursor: help;
        position: relative;
        pointer-events: auto;
      }
      .waldo-edge-flag::after {
        content: attr(data-waldo-reason);
        display: none;
        position: absolute;
        left: 0;
        top: 1.4em;
        background: #1a1a2e;
        color: #fde68a;
        border: 1px solid #f59e0b;
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

      /* Custom right-click context menu for flagged words */
      .waldo-ctx-menu {
        position: fixed;
        z-index: 2147483647;
        background: #1e1e2e;
        border: 1px solid #4a4a8a;
        border-radius: 7px;
        padding: 4px 0;
        min-width: 190px;
        box-shadow: 0 6px 24px rgba(0,0,0,.65);
        font: 13px/1.4 system-ui, sans-serif;
        user-select: none;
      }
      .waldo-ctx-menu-header {
        padding: 5px 12px 6px;
        color: #ef4444;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .05em;
        border-bottom: 1px solid #2d2d4e;
      }
      .waldo-ctx-menu-item {
        padding: 6px 14px;
        color: #e0e0e0;
        cursor: pointer;
        white-space: nowrap;
      }
      .waldo-ctx-menu-item:hover {
        background: #2d2d4e;
        color: #fff;
      }
      .waldo-ctx-menu-item.primary {
        color: #a5f3fc;
        font-weight: 600;
        border-bottom: 1px solid #2d2d4e;
        margin-bottom: 2px;
      }
      .waldo-ctx-menu-item.primary:hover {
        background: #1a3a4c;
      }
      .waldo-ctx-menu-label {
        padding: 4px 14px 2px;
        color: #6b7280;
        font-size: 11px;
        letter-spacing: .04em;
        text-transform: uppercase;
      }

      /* Tone indicator badge — anchored bottom-right of textarea.
         Mirrors Grammarly's ambient tone signal. */
      .waldo-tone-badge {
        position: absolute;
        z-index: 2147483646;
        background: rgba(26, 26, 46, 0.92);
        border: 1px solid #4a4a8a;
        border-radius: 10px;
        padding: 2px 8px;
        font: 11px/1.6 system-ui, sans-serif;
        color: #e0e0e0;
        pointer-events: none;
        white-space: nowrap;
        letter-spacing: .02em;
      }
    `;
    document.head.appendChild(style);
  })();

  // ── Context detection ─────────────────────────────────────────────────────

  function shouldSkip(el) {
    if (el.type === "password") return true;
    // Skip spellcheck=false only if the site set it — not if Waldo's own suppression toggle did
    if (el.getAttribute("spellcheck") === "false" && !el.hasAttribute("data-waldo-orig-spellcheck")) return true;
    if (el.getAttribute("data-gramm") === "false") return true;
    if (el.getAttribute("data-gramm_editor") === "false") return true;
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

  // ── Fast tier overlay (per-word red underlines) ───────────────────────────
  //
  // Plain <textarea>/<input> can't contain inline HTML, so we mirror the
  // element's geometry in an absolutely-positioned overlay div.  The overlay
  // is transparent except for the wavy underline decorations on flagged words.
  // pointer-events:none on the overlay div passes clicks through to the real
  // textarea; pointer-events:auto on each .waldo-fast-flag span enables hover.

  function removeFastOverlay(el) {
    const overlay = fastOverlayMap.get(el);
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    fastOverlayMap.delete(el);
  }

  function buildFastOverlayText(text, corrections) {
    if (!corrections.length) return document.createTextNode(text);

    const fragment = document.createDocumentFragment();
    let cursor = 0;

    // Sort by start position to walk the string left-to-right
    const sorted = [...corrections].sort((a, b) => a.start - b.start);

    for (const c of sorted) {
      if (c.start < cursor) continue; // overlapping — skip (shouldn't happen)

      // Plain text before this word
      if (c.start > cursor) {
        fragment.appendChild(document.createTextNode(text.slice(cursor, c.start)));
      }

      // Flagged word span — tooltip + position attrs for click-to-replace
      const span = document.createElement("span");
      span.className = "waldo-fast-flag";
      const sugs = (c.suggestions ?? []).slice(0, 3).join(", ");
      span.setAttribute("data-waldo-suggestions", sugs || "no suggestions");
      span.setAttribute("data-waldo-start", String(c.start));
      span.setAttribute("data-waldo-end",   String(c.end));
      span.setAttribute("data-waldo-top",   (c.suggestions ?? [])[0] ?? "");
      span.textContent = text.slice(c.start, c.end);
      fragment.appendChild(span);

      cursor = c.end;
    }

    // Remaining text
    if (cursor < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(cursor)));
    }

    return fragment;
  }

  function syncFastOverlay(el, corrections) {
    removeFastOverlay(el);
    if (!corrections.length) return;

    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) return;

    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const scrollTop  = window.scrollY || document.documentElement.scrollTop;
    const scrollLeft = window.scrollX || document.documentElement.scrollLeft;

    const overlay = document.createElement("div");
    overlay.setAttribute("data-waldo-fast-overlay", "1");
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
      `z-index:2147483646`,
      `pointer-events:none`,
      `box-sizing:${cs.boxSizing}`,
      `color:transparent`,
    ].join(";");

    overlay.appendChild(buildFastOverlayText(text, corrections));
    document.body.appendChild(overlay);
    fastOverlayMap.set(el, overlay);
  }

  // ── Edge tier overlay (per-sentence yellow underlines) ────────────────────

  function removeEdgeOverlay(el) {
    const overlay = edgeOverlayMap.get(el);
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    edgeOverlayMap.delete(el);
  }

  function buildEdgeOverlayText(text, flaggedSentences) {
    if (!flaggedSentences.length) return document.createTextNode(text);

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
      const pct = Math.round(score * 100);
      span.setAttribute("data-waldo-reason", `Grammar issue (${pct}% confidence)`);
      span.textContent = sentence;
      fragment.appendChild(span);

      cursor = idx + sentence.length;
    }

    if (cursor < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(cursor)));
    }

    return fragment;
  }

  function syncEdgeOverlay(el, flaggedSentences) {
    removeEdgeOverlay(el);
    if (!flaggedSentences.length) return;

    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) return;

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
      `z-index:2147483646`,
      `pointer-events:none`,
      `box-sizing:${cs.boxSizing}`,
      `color:transparent`,
    ].join(";");

    overlay.appendChild(buildEdgeOverlayText(text, flaggedSentences));
    document.body.appendChild(overlay);
    edgeOverlayMap.set(el, overlay);
  }

  // ── Tone badge (bottom-right corner of textarea) ──────────────────────────
  //
  // Grammarly-style ambient tone signal.  Driven by Edge tier sentiment scores.
  // Maps aggregate negativity confidence to a human-readable emoji + label.

  function removeToneBadge(el) {
    const badge = toneBadgeMap.get(el);
    if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
    toneBadgeMap.delete(el);
  }

  // Grammar quality badge — driven by Edge tier (CoLA grammar acceptability scores).
  // CoLA does NOT detect emotional tone/sentiment; calling it "tone" was misleading.
  // Badge shows count of flagged sentences and avg grammar-issue confidence.
  // A real sentiment model is needed for actual tone detection (post-v1.0).

  function updateToneBadge(el, sentences) {
    removeToneBadge(el);
    if (!sentences || !sentences.length) return;

    const count    = sentences.length;
    const avgScore = sentences.reduce((s, x) => s + x.score, 0) / sentences.length;
    const pct      = Math.round(avgScore * 100);
    const emoji    = pct >= 80 ? "⚠️" : "📝";

    const badge = document.createElement("div");
    badge.setAttribute("data-waldo-tone", "1");
    badge.className = "waldo-tone-badge";
    badge.title = `Edge tier: ${count} sentence(s) flagged, avg ${pct}% grammar issue confidence`;
    badge.textContent = `${emoji} ${count} grammar issue${count !== 1 ? "s" : ""}`;
    document.body.appendChild(badge);
    toneBadgeMap.set(el, badge);

    // Anchor to bottom-right corner of the element, just inside the border
    const rect = el.getBoundingClientRect();
    const scrollTop  = window.scrollY || document.documentElement.scrollTop;
    const scrollLeft = window.scrollX || document.documentElement.scrollLeft;
    // offsetWidth/Height available after append; fall back to estimate if 0
    const bw = badge.offsetWidth  || 80;
    const bh = badge.offsetHeight || 20;
    badge.style.top  = `${rect.bottom + scrollTop  - bh - 6}px`;
    badge.style.left = `${rect.right  + scrollLeft - bw - 8}px`;
  }

  // ── Smart tier badge ──────────────────────────────────────────────────────

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
      "border:1px solid #8b5cf6",
      "border-radius:6px",
      "padding:8px 12px",
      "font:13px/1.5 system-ui,sans-serif",
      "max-width:380px",
      "box-shadow:0 4px 14px rgba(0,0,0,.5)",
      "pointer-events:none",
    ].join(";");

    if (!result.available) {
      const labelSpan = document.createElement("span");
      labelSpan.style.cssText = "color:#c4b5fd;font-weight:600";
      labelSpan.textContent = "Waldo Smart:";
      const msgSpan = document.createElement("span");
      msgSpan.style.color = "#9ca3af";
      msgSpan.textContent = " " + (result.message || "Smart tier unavailable");
      badge.append(labelSpan, msgSpan);
    } else {
      const corrections = result.corrections ?? [];
      if (!corrections.length) return;

      const headerSpan = document.createElement("span");
      headerSpan.style.cssText = "color:#c4b5fd;font-weight:600;display:block;margin-bottom:4px";
      headerSpan.textContent = "Waldo Smart suggestions";
      badge.appendChild(headerSpan);
      for (const [i, c] of corrections.slice(0, 5).entries()) {
        if (i > 0) badge.appendChild(document.createElement("br"));
        const origSpan = document.createElement("span");
        origSpan.style.cssText = "color:#f9a8d4;font-weight:600";
        origSpan.textContent = `«${c.original}»`;
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

    const rect = el.getBoundingClientRect();
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const scrollX = window.scrollX || document.documentElement.scrollLeft;
    const badgeLeft = Math.min(
      rect.left + scrollX,
      document.documentElement.clientWidth - 384 + scrollX,
    );
    badge.style.top  = `${rect.bottom + scrollY + 6}px`;
    badge.style.left = `${Math.max(0, badgeLeft)}px`;

    setTimeout(() => removeSmartOverlay(el), 12000);
  }

  // ── Inline text replacement ───────────────────────────────────────────────

  function applyReplacement(target, start, end, suggestion) {
    if (target.tagName === "TEXTAREA" || target.tagName === "INPUT") {
      const val = target.value;
      target.value = val.slice(0, start) + suggestion + val.slice(end);
      target.setSelectionRange(start + suggestion.length, start + suggestion.length);
      target.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (target.isContentEditable) {
      target.focus();
      const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
      let charCount = 0, startNode = null, startOff = 0, endNode = null, endOff = 0;
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const len = node.textContent.length;
        if (!startNode && charCount + len > start) { startNode = node; startOff = start - charCount; }
        if (!endNode   && charCount + len >= end)  { endNode   = node; endOff   = end   - charCount; break; }
        charCount += len;
      }
      if (startNode && endNode) {
        const range = document.createRange();
        range.setStart(startNode, startOff);
        range.setEnd(endNode, endOff);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand("insertText", false, suggestion);
      }
    }
  }

  // Resolve the textarea/contenteditable that an overlay span sits above.
  function targetForSpan(span) {
    const rect = span.getBoundingClientRect();
    const probe = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.bottom + 4,
    );
    return probe?.closest("textarea, input, [contenteditable]") ?? null;
  }

  // ── Custom right-click context menu ───────────────────────────────────────

  let _ctxMenu = null;
  let _menuJustClosed = false;

  function removeCtxMenu() {
    if (_ctxMenu && _ctxMenu.parentNode) _ctxMenu.parentNode.removeChild(_ctxMenu);
    _ctxMenu = null;
  }

  // ── Unified Waldo popup menu ──────────────────────────────────────────────
  //
  // Single menu shell used by both Fast (spelling) and Edge (grammar) clicks.
  // Returns helpers so callers can populate body content, including async updates.

  function createWaldoMenu(clientX, clientY, headerText, headerColor) {
    removeCtxMenu();

    const menu = document.createElement("div");
    menu.className = "waldo-ctx-menu";
    _ctxMenu = menu;

    const header = document.createElement("div");
    header.className = "waldo-ctx-menu-header";
    header.style.color = headerColor || "#ef4444";
    header.textContent = headerText;
    menu.appendChild(header);

    const body = document.createElement("div");
    menu.appendChild(body);
    document.body.appendChild(menu);

    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    function reposition() {
      const mw = menu.offsetWidth  || 200;
      const mh = menu.offsetHeight || 80;
      menu.style.left = `${Math.min(clientX, vw - mw - 8)}px`;
      menu.style.top  = `${Math.min(clientY, vh - mh - 8)}px`;
    }
    reposition();

    const dismiss = (e) => {
      if (menu.contains(e.target)) return;
      removeCtxMenu(); unbind();
      _menuJustClosed = true;
      setTimeout(() => { _menuJustClosed = false; }, 100);
    };
    const onKey = (e) => { if (e.key === "Escape") { removeCtxMenu(); unbind(); } };
    const unbind = () => {
      document.removeEventListener("click",   dismiss, true);
      document.removeEventListener("keydown", onKey,   true);
    };
    setTimeout(() => {
      document.addEventListener("click",   dismiss, true);
      document.addEventListener("keydown", onKey,   true);
    }, 0);

    function closeAfter(action) {
      action();
      _menuJustClosed = true;
      setTimeout(() => { _menuJustClosed = false; }, 100);
      removeCtxMenu();
    }

    return {
      clearBody()       { body.innerHTML = ""; reposition(); },
      setStatus(text)   {
        body.innerHTML = "";
        const el = document.createElement("div");
        el.className = "waldo-ctx-menu-label";
        el.style.fontStyle = "italic";
        el.textContent = text;
        body.appendChild(el);
        reposition();
      },
      addLabel(text) {
        const el = document.createElement("div");
        el.className = "waldo-ctx-menu-label";
        el.textContent = text;
        body.appendChild(el);
      },
      addPrimary(label, action) {
        const el = document.createElement("div");
        el.className = "waldo-ctx-menu-item primary";
        el.textContent = label;
        el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); closeAfter(action); });
        body.appendChild(el);
        reposition();
      },
      addItem(label, action) {
        const el = document.createElement("div");
        el.className = "waldo-ctx-menu-item";
        el.textContent = label;
        el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); closeAfter(action); });
        body.appendChild(el);
        reposition();
      },
    };
  }

  // Fast tier: left-click on a red-underlined word → spelling suggestions
  function showWordCtxMenu(span, clientX, clientY) {
    const target      = targetForSpan(span);
    const top         = span.getAttribute("data-waldo-top") ?? "";
    const sugsRaw     = span.getAttribute("data-waldo-suggestions") ?? "";
    const suggestions = sugsRaw ? sugsRaw.split(", ").filter(Boolean) : [];
    const start       = parseInt(span.getAttribute("data-waldo-start"), 10);
    const end         = parseInt(span.getAttribute("data-waldo-end"),   10);

    const m = createWaldoMenu(clientX, clientY, `"${span.textContent}" — Waldo`, "#ef4444");

    if (top) {
      m.addPrimary(`Fix with Waldo → ${top}`, () => {
        if (target && !isNaN(start) && !isNaN(end)) applyReplacement(target, start, end, top);
      });
    }
    const others = suggestions.filter(s => s !== top);
    if (others.length) {
      m.addLabel("Other suggestions");
      for (const sug of others) {
        m.addItem(sug, () => {
          if (target && !isNaN(start) && !isNaN(end)) applyReplacement(target, start, end, sug);
        });
      }
    }
    if (!top && !others.length) m.setStatus("no suggestions");
  }

  // Edge tier: left-click on a yellow-underlined sentence → Smart tier rewrite
  function showEdgeMenu(span, clientX, clientY) {
    const sentence = span.textContent;
    const reason   = span.getAttribute("data-waldo-reason") ?? "Grammar / tone issue";
    const label    = sentence.length > 38 ? `"${sentence.slice(0, 36)}…"` : `"${sentence}"`;

    const m = createWaldoMenu(clientX, clientY, `${label} — Waldo`, "#f59e0b");
    m.setStatus("Checking Smart tier…");

    browser.runtime.sendMessage({ action: "smart_analyze", text: sentence })
      .then((resp) => {
        m.clearBody();
        if (!resp || !resp.available) {
          m.setStatus("Smart tier offline — start Waldo server for rewrites");
          return;
        }
        const corrections = resp.corrections ?? [];
        if (!corrections.length) {
          m.setStatus(`${reason} — no specific rewrite found`);
          return;
        }
        m.addLabel(reason);
        for (const c of corrections.slice(0, 3)) {
          for (const sug of (c.suggestions ?? []).slice(0, 2)) {
            m.addPrimary(`${c.original} → ${sug}`, () => {
              navigator.clipboard.writeText(sug).catch(() => {});
            });
          }
        }
      })
      .catch(() => {
        m.clearBody();
        m.setStatus(`${reason} — Smart tier unavailable`);
      });
  }

  // ── Analysis ──────────────────────────────────────────────────────────────

  async function analyze(el) {
    if (shouldSkip(el)) return;
    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) { removeFastOverlay(el); return; }

    try {
      const resp = await browser.runtime.sendMessage({
        action: "analyze",
        text,
        context_hint: getContextHint(el),
      });
      if (resp && Array.isArray(resp.corrections)) {
        console.log(`[WaldoSpells][fast] ${text.length}ch → ${resp.corrections.length} corrections`);
        correctionsCache.set(el, resp.corrections);
        syncFastOverlay(el, resp.corrections);
      }
    } catch (_) {
      // Background script unreachable or extension disabled — silent fail
    }
  }

  async function analyzeEdge(el) {
    if (shouldSkip(el)) return;
    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) { removeEdgeOverlay(el); removeToneBadge(el); return; }

    try {
      const ts_content_send = Date.now();
      const resp = await browser.runtime.sendMessage({ action: "edge_analyze", text, ts_content_send });
      const n = resp?.sentences?.length ?? 0;
      const latency_total = resp?.ts_content_send ? Date.now() - resp.ts_content_send : null;
      console.log(`[WaldoSpells][edge] ${text.length}ch → ${n} flagged${latency_total ? ` (${latency_total}ms)` : ""}`);
      if (resp && Array.isArray(resp.sentences)) {
        syncEdgeOverlay(el, resp.sentences);
        updateToneBadge(el, resp.sentences);
      }
    } catch (err) {
      console.error(`[WaldoSpells][edge] ✗`, err.message);
    }
  }

  async function analyzeSmartEl(el, { onDemand = false } = {}) {
    if (shouldSkip(el)) return;
    const text = el.value ?? el.innerText ?? "";
    if (!text.trim()) { removeSmartOverlay(el); return; }

    if (!onDemand && _smartAvailable === false) return;

    let paragraph = text;
    if (!onDemand) {
      const idx = text.lastIndexOf("\n\n");
      if (idx === -1) return;
      paragraph = text.slice(0, idx).trim();
      if (!paragraph) return;
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

  // ── Context menu fix suggestions ──────────────────────────────────────────

  let _activeSquiggle = null;

  function removeSuggestionPanel() {
    const existing = document.getElementById("waldo-ctx-panel");
    if (existing) existing.remove();
  }

  function showSuggestionPanel(sentence, explanation, suggestions, anchorEl) {
    removeSuggestionPanel();

    const panel = document.createElement("div");
    panel.id = "waldo-ctx-panel";
    panel.setAttribute("data-waldo-ctx", "1");
    panel.style.cssText = [
      "position:fixed",
      "z-index:2147483647",
      "background:#1a1a2e",
      "color:#e0e0e0",
      "border:1px solid #f59e0b",
      "border-radius:7px",
      "padding:10px 14px",
      "font:13px/1.5 system-ui,sans-serif",
      "max-width:380px",
      "box-shadow:0 4px 18px rgba(0,0,0,.6)",
      "pointer-events:auto",
    ].join(";");

    const header = document.createElement("div");
    header.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px";
    const title = document.createElement("span");
    title.style.cssText = "color:#f59e0b;font-weight:700;font-size:12px;letter-spacing:.04em";
    title.textContent = "WALDO FIX SUGGESTION";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.style.cssText = [
      "background:none",
      "border:none",
      "color:#9ca3af",
      "cursor:pointer",
      "font-size:14px",
      "padding:0 0 0 8px",
      "line-height:1",
    ].join(";");
    closeBtn.addEventListener("click", removeSuggestionPanel);
    header.append(title, closeBtn);
    panel.appendChild(header);

    if (explanation) {
      const expDiv = document.createElement("div");
      expDiv.style.cssText = "color:#d1d5db;margin-bottom:8px;font-size:12px";
      expDiv.textContent = explanation;
      panel.appendChild(expDiv);
    }

    const origDiv = document.createElement("div");
    origDiv.style.cssText = "margin-bottom:6px";
    const origLabel = document.createElement("span");
    origLabel.style.cssText = "color:#9ca3af;font-size:11px";
    origLabel.textContent = "Flagged: ";
    const origText = document.createElement("span");
    origText.style.cssText = "color:#f9a8d4;font-weight:600";
    origText.textContent = sentence.length > 80 ? sentence.slice(0, 77) + "…" : sentence;
    origDiv.append(origLabel, origText);
    panel.appendChild(origDiv);

    if (suggestions && suggestions.length) {
      const sugLabel = document.createElement("div");
      sugLabel.style.cssText = "color:#9ca3af;font-size:11px;margin-bottom:3px";
      sugLabel.textContent = suggestions.length === 1 ? "Suggestion:" : "Suggestions:";
      panel.appendChild(sugLabel);

      for (const sug of suggestions.slice(0, 2)) {
        const sugDiv = document.createElement("div");
        sugDiv.style.cssText = [
          "background:#0f172a",
          "border:1px solid #334155",
          "border-radius:4px",
          "padding:4px 8px",
          "margin-bottom:4px",
          "color:#a5f3fc",
          "font-size:12px",
          "cursor:pointer",
        ].join(";");
        sugDiv.textContent = sug;
        sugDiv.title = "Click to copy";
        sugDiv.addEventListener("click", () => {
          navigator.clipboard.writeText(sug).catch(() => {});
          sugDiv.style.background = "#1e3a4c";
          setTimeout(() => { sugDiv.style.background = "#0f172a"; }, 600);
        });
        panel.appendChild(sugDiv);
      }
    } else {
      const noSug = document.createElement("div");
      noSug.style.cssText = "color:#6b7280;font-size:12px;font-style:italic";
      noSug.textContent = "No specific rewrite available — see explanation above.";
      panel.appendChild(noSug);
    }

    document.body.appendChild(panel);

    const rect = anchorEl ? anchorEl.getBoundingClientRect() : { bottom: 80, left: 80 };
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const panelW = 380;
    const panelH = 200;
    let top  = rect.bottom + 6;
    let left = rect.left;
    if (left + panelW > vw) left = vw - panelW - 8;
    if (left < 4) left = 4;
    if (top + panelH > vh) top = (rect.top || 80) - panelH - 6;
    panel.style.top  = `${Math.max(4, top)}px`;
    panel.style.left = `${Math.max(4, left)}px`;

    setTimeout(removeSuggestionPanel, 20000);
  }

  // Left-click on a fast-flag span: open the Waldo suggestions menu.
  // Right-click is left alone so the native browser menu (with "Fix this with Waldo…") still works.
  document.addEventListener("click", (e) => {
    if (_menuJustClosed) return; // swallow the click that dismissed a menu
    const span = e.target.closest(".waldo-fast-flag");
    if (!span) return;
    e.preventDefault();
    e.stopPropagation();
    showWordCtxMenu(span, e.clientX, e.clientY);
  }, true);

  // Left-click on an edge-flag span → unified Waldo menu (Edge/grammar tier)
  document.addEventListener("click", (e) => {
    const span = e.target.closest(".waldo-edge-flag");
    if (!span) return;
    e.preventDefault();
    e.stopPropagation();
    showEdgeMenu(span, e.clientX, e.clientY);
  }, true);

  // Right-click: store active element's corrections in extension storage so the
  // context menu handler in background.js can use them without needing to hit a span.
  document.addEventListener("mousedown", (e) => {
    if (e.button !== 2) return; // right-click only
    const el = e.target.closest("textarea, input, [contenteditable]");
    if (el && !shouldSkip(el)) {
      const corrections = correctionsCache.get(el) ?? [];
      const text = el.value ?? el.innerText ?? "";
      browser.storage.local.set({
        waldo_ctx_data: JSON.stringify({
          text: text.slice(0, 200), // enough context for Smart tier
          corrections: corrections.map(c => ({
            original: c.original,
            suggestions: (c.suggestions ?? []).slice(0, 5),
          })),
        }),
      });
    } else {
      browser.storage.local.remove("waldo_ctx_data");
    }
  }, true);

  // ── Event handlers ────────────────────────────────────────────────────────

  function onInput(e) {
    clearTimeout(debounceTimer);
    clearTimeout(edgeDebounceTimer);
    removeFastOverlay(e.target);
    removeEdgeOverlay(e.target);
    removeToneBadge(e.target);

    debounceTimer     = setTimeout(() => analyze(e.target), DEBOUNCE_MS);
    edgeDebounceTimer = setTimeout(() => analyzeEdge(e.target), EDGE_DEBOUNCE_MS);

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
    clearTimeout(debounceTimer);
    clearTimeout(edgeDebounceTimer);
    analyze(e.target);
    analyzeEdge(e.target);
  }

  function onFocus(_e) {
    // Intentionally do NOT clear overlays on focus — they remain valid until
    // the user starts typing (onInput clears them).  Clearing here caused
    // underlines to disappear when switching windows or taking screenshots.
  }

  // ── On-demand Smart trigger ───────────────────────────────────────────────

  browser.runtime.onMessage.addListener((msg) => {
    if (msg.action === "set_browser_spellcheck") {
      _suppressBrowserSpellcheck = msg.suppress;
      applySpellcheckToAll(msg.suppress);
      return;
    }
    if (msg.action === "suggest_fix") {
      const { explanation, corrections } = msg;
      const anchorEl = document.activeElement;
      // Build a flat suggestion list from all corrections: "recieved → received, relieved"
      const allSuggestions = (corrections ?? []).flatMap(c =>
        (c.suggestions ?? []).slice(0, 2).map(s => `${c.original} → ${s}`)
      );
      showSuggestionPanel(explanation || "Spelling suggestions:", explanation, allSuggestions, anchorEl);
      return;
    }
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

  // ── Browser spellcheck suppression ───────────────────────────────────────

  let _suppressBrowserSpellcheck = true; // default: suppress when Waldo is active

  // Load saved preference on startup
  browser.storage.local.get("suppressBrowserSpellcheck").then((stored) => {
    _suppressBrowserSpellcheck = stored.suppressBrowserSpellcheck !== false;
    applySpellcheckToAll(_suppressBrowserSpellcheck);
  });

  function setElementSpellcheck(el, suppress) {
    if (suppress) {
      if (!el.hasAttribute("data-waldo-orig-spellcheck")) {
        // Save original value (or absence of attribute) before overriding
        el.setAttribute("data-waldo-orig-spellcheck",
          el.hasAttribute("spellcheck") ? el.getAttribute("spellcheck") : "__unset__");
      }
      el.setAttribute("spellcheck", "false");
    } else {
      const orig = el.getAttribute("data-waldo-orig-spellcheck");
      if (orig === "__unset__") {
        el.removeAttribute("spellcheck");
      } else if (orig !== null) {
        el.setAttribute("spellcheck", orig);
      }
    }
  }

  function applySpellcheckToAll(suppress) {
    const els = document.querySelectorAll('textarea, input[type="text"], input:not([type])');
    els.forEach(el => setElementSpellcheck(el, suppress));
  }

  // ── Attachment ────────────────────────────────────────────────────────────

  function attach(el) {
    if (el._waldoAttached) return;
    el._waldoAttached = true;
    setElementSpellcheck(el, _suppressBrowserSpellcheck);
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

  const observer = new MutationObserver(attachAll);
  observer.observe(document.body, { childList: true, subtree: true });
})();
