# Browser Context Detection — Waldo Spells Research

**Project**: Waldo Spells (Grammar Checker, Firefox Extension)  
**Date**: April 2026  
**Focus**: Context detection signals for routing text inputs to Fast/Mid/Smart/Skip tiers  
**Audience**: Task 2 artifact; feeds Task 3 (llama.cpp wrapper) and Task 4 (test harness)

---

## 1. Overview — Why Context Detection Matters

Waldo Spells must route incoming text fields through three tiers with vastly different latency targets (Nuspell <5ms, Unbabel gec-t5_small 25–40ms, Qwen2.5-3B 400–550ms). Routing decisions cannot rely on user input alone—they depend on detecting *where* the user is typing, *what kind* of field it is, and *whether* grammar checking is appropriate at all.

Key challenge: A single webpage can host multiple input types (password fields, search boxes, email bodies, code editors). The Firefox content script runs per-frame, can read the DOM, and must make routing decisions on a per-element basis, respecting:
1. **Grammarly's de facto standards** for opting out (data attributes we MUST honor)
2. **HTML5 native signals** (type=password, spellcheck, autocomplete, inputmode, aria-* roles)
3. **Editor-specific patterns** (CodeMirror, ProseMirror, Quill, Monaco classes)
4. **Cross-origin iframe boundaries** (Stripe, reCAPTCHA, OAuth popups—skip entirely)
5. **SPA route changes** (ChatGPT, Claude.ai load content dynamically—need re-detection)

This document enumerates all signals and produces a tier-routing decision tree usable by the content script.

---

## 2. DOM Signals Table

| Signal | HTML Syntax | Meaning | Action |
|--------|-------------|---------|--------|
| **Password field** | `input[type="password"]` | Sensitive credential input | **SKIP** (PII) |
| **Hidden input** | `input[type="hidden"]` | Not user-visible, form metadata | **SKIP** |
| **File upload** | `input[type="file"]` | File path, not prose | **SKIP** |
| **Email field** | `input[type="email"]` | May have validation constraints | **FAST** (Nuspell only) |
| **Search field** | `input[type="search"]` or `input[type="text"]` + `role="searchbox"` | Query intent; often short | **FAST** (Nuspell only) |
| **URL field** | `input[type="url"]` | URL/URI, not prose | **SKIP** |
| **Number/tel field** | `input[type="number"]` or `input[type="tel"]` | Numeric, not text | **SKIP** |
| **Text field (short)** | `input[type="text"]` + `size<50` or `maxlength<50` | Single-line, likely short | **FAST** (Nuspell) |
| **Text field (long)** | `input[type="text"]` + `size>=50` or `maxlength>=50` | Multi-word input possible | **MID** (Unbabel gec-t5) |
| **Textarea** | `<textarea>` | Multi-line prose common | **MID** to **SMART** (depends on length) |
| **Contenteditable div/span** | `[contenteditable="true"]` | Rich text editor, custom framework | **Depends on wrapper** (see editor patterns) |
| **Contenteditable false** | `[contenteditable="false"]` | Read-only or special UI | **SKIP** |
| **Spellcheck disabled** | `spellcheck="false"` | Author explicitly disabled checking | **SKIP** (respect author intent) |
| **Spellcheck enabled** | `spellcheck="true"` | Author explicitly enabled checking | **MID** to **SMART** (depends on scope) |
| **Autocomplete password** | `autocomplete="current-password"` or `autocomplete="new-password"` | Password manager field | **SKIP** (PII) |
| **Autocomplete payment** | `autocomplete="cc-number"` or `autocomplete="cc-csc"` | Credit card data | **SKIP** (PII) |
| **Autocomplete OTP** | `autocomplete="one-time-code"` | One-time passcode | **SKIP** (PII) |
| **Inputmode numeric** | `inputmode="numeric"` | PIN or numeric password | **SKIP** (likely credential) |
| **ARIA textbox** | `role="textbox"` | Semantic: this element is a textbox | **Depends on parent context** |
| **ARIA combobox** | `role="combobox"` | Semantic: dropdown with text input (autocomplete) | **FAST** (Nuspell)—value is querying, not prose |
| **ARIA searchbox** | `role="searchbox"` | Semantic: search input | **FAST** (Nuspell) |
| **ARIA log/status** | `role="log"` or `role="status"` | Output-only, not editable | **SKIP** |

### 2.1 Grammarly Opt-Out Attributes (MUST Honor)

These are de facto standards Grammarly respects. Waldo Spells **must** check these first, before running any analysis:

| Attribute | Value | Meaning | Precedence |
|-----------|-------|---------|-----------|
| `data-gramm` | `"false"` | Classic Grammarly disable signal | **Highest** — skip immediately |
| `data-gramm_editor` | `"false"` | Older Grammarly disable variant | **High** — skip immediately |
| `data-enable-grammarly` | `"false"` | Newest Grammarly standard (as of 2025) | **Highest** — skip immediately |
| `data-gramm` | `"true"` | Grammarly explicitly enabled | Does not override type=password or spellcheck=false |
| `data-slate-editor` | `"true"` | Slate.js editor (custom framework) | **May interfere** with Grammarly; treat as editor-specific |

**Special note**: These attributes can be set on the input element itself or inherited from a parent container (wrapper div, form). Always check parent chain up to 3 levels.

---

## 3. Known App Patterns — DOM Signatures

### 3.1 ChatGPT

**Detected by**: 
- Element ID `#prompt-textarea` (primary)
- Wrapper class `.col-12 .mt-auto`
- Input is `contenteditable="true"` div, not a native textarea
- ProseMirror instance (check window structure for `__prosemirror` properties)

**Grammarly behavior**: **Grammarly SKIPS ChatGPT inputs.** The extension likely uses a hostname blocklist or detects the ProseMirror class and opts out.

**Waldo decision**: **SKIP for now.** ChatGPT is an AI chat interface; checking grammar on AI-generated text is out of scope. If users explicitly invoke Waldo for refinement, route to **SMART** tier with explicit user consent.

**DOM class chain**: `.input_container > #prompt-textarea[contenteditable][data-id="root"]`

---

### 3.2 Claude.ai

**Detected by**:
- Wrapper class `.ProseMirror` (Claude uses ProseMirror v1.7+)
- Element is `contenteditable="true"` div
- Global object `window.__CLAUDE_EDITOR__` or similar (TBD via DOM inspection in Task 4)
- Hostname `claude.ai` (exact match or regex)

**Grammarly behavior**: **Grammarly SKIPS Claude.ai inputs.** The extension's blocklist likely includes `claude.ai` hostname.

**Waldo decision**: **SKIP by hostname blocklist.** Like ChatGPT, Claude.ai is an AI interface. Do not offer grammar checking on outputs of an AI service.

**DOM class chain**: `.editor-wrapper > .ProseMirror[contenteditable="true"][data-placeholder="Type..."]`

---

### 3.3 Gmail (Compose)

**Detected by**:
- Wrapper div has class `.aO.T-I-J-K` (Gmail's internal class, may change)
- Input element: `div[role="textbox"][contenteditable="true"][aria-label="Message Body"]`
- Container div has attribute `data-Gmail-api-id="..."` (Gmail's metadata)
- MutationObserver detects compose box appearance (inserted into DOM on "Compose" click)

**Grammarly behavior**: **Grammarly ACTIVELY CHECKS Gmail compose bodies.** The extension injects underlines and suggestions into the contenteditable div.

**Waldo decision**: **MID tier (Unbabel gec-t5_small)** for email body text. Email prose is medium-length, semi-formal, and benefits from grammar checking. Signal: presence of `role="textbox"` + `aria-label` containing "Message" or "Body".

**Detection heuristic**: 
```javascript
// Check for Gmail compose body
const isGmailCompose = 
  element.getAttribute('role') === 'textbox' &&
  (element.getAttribute('aria-label') || '').includes('Message') &&
  window.location.hostname.includes('gmail.com');
```

---

### 3.4 Slack (Message Input)

**Detected by**:
- Wrapper class `.c-textwrapper_input__input__container`
- Input element: `div.ql-editor[contenteditable="true"][data-qa="virtual_list_item"]`
- Quill.js editor instance (detect by checking `window.Quill` and `.ql-editor` class)

**Grammarly behavior**: **Grammarly ACTIVELY CHECKS Slack messages.** The extension works well with Quill-based editors.

**Waldo decision**: **MID tier (Unbabel gec-t5_small)** for message body. Chat messages are typically short to medium prose, informal, and users appreciate real-time corrections. Latency target 25–40ms on RTX 3060 is acceptable for message input.

**Detection heuristic**:
```javascript
// Check for Slack message input
const isSlackMessage = 
  element.classList.contains('ql-editor') &&
  element.getAttribute('contenteditable') === 'true' &&
  window.location.hostname.includes('slack.com');
```

---

### 3.5 GitHub (PR/Issue Body)

**Detected by**:
- Wrapper div has class `.comment-body` or `.js-body`
- Input element: `textarea#issue_body` or `div.markdown-body[contenteditable="true"]`
- CodeMirror instance present in PR/diff contexts (check for `.CodeMirror` class)

**Grammaly behavior**: **Grammarly CHECKS issue bodies but SKIPS code blocks.** Grammarly respects markdown-based code fences (\`\`\` blocks) and skips them.

**Waldo decision**: 
- **MID tier** for issue body/PR description text (prose)
- **SKIP** for code blocks (detect by class `.CodeMirror` or wrapper containing `data-lang="javascript"` etc.)

**Detection strategy**: 
- For plain `<textarea>`, check `id` (issue_body, pull_body)
- For CodeMirror, check parent for `.CodeMirror` class and skip
- For markdown prose, use MID tier

---

### 3.6 Discord (Message Input)

**Detected by**:
- Wrapper div has class `.slateTextArea-1FLlqt` or `.scrollbar-3AqfIe`
- Input element: `div[role="textbox"][contenteditable="true"][data-slate-editor="true"]`
- Slate.js editor instance

**Grammarly behavior**: **Grammarly CHECKS Discord messages**, though the Slate framework can interfere with DOM injection. Grammarly may detect `data-slate-editor` and use special handling.

**Waldo decision**: **MID tier** for Discord messages. Short to medium prose, informal, real-time feedback acceptable.

**Detection heuristic**:
```javascript
// Check for Discord message input
const isDiscordMessage = 
  element.getAttribute('data-slate-editor') === 'true' &&
  element.getAttribute('contenteditable') === 'true' &&
  window.location.hostname.includes('discord.com');
```

---

### 3.7 Notion (Rich Text Editor)

**Detected by**:
- Wrapper div has class `.notion-editor` or `.notion-selectable`
- Input element: `div[contenteditable="true"][data-block-id="..."]`
- Notion's custom framework (not ProseMirror, not Slate, not Quill)

**Grammarly behavior**: **Grammarly poorly supports Notion.** The combination of virtual DOM, custom block rendering, and Notion's complex editor model causes Grammarly to:
- Fail to insert underlines correctly
- Miss spans across block boundaries
- Interfere with Notion's formatting tools

**Waldo decision**: **SKIP for now, or FAST tier with caveat.** Notion's custom architecture makes reliable grammar checking difficult. Can use Nuspell (FAST, spell-check only) as a limited alternative. Avoid MID/SMART until Notion's DOM model is better understood.

**Detection heuristic**:
```javascript
// Detect Notion but skip for grammar (use FAST only as fallback)
const isNotion = window.location.hostname.includes('notion.so') &&
                element.getAttribute('contenteditable') === 'true';
```

---

### 3.8 Google Docs (Rich Editor)

**Detected by**:
- **CRITICAL**: Google Docs has migrated to **Canvas-based rendering** (not DOM-based)
- Old DOM approach: `div[role="textbox"][contenteditable="true"]` with complex span structure
- New Canvas approach: Content is rendered to Canvas; no DOM text exists to analyze

**Grammarly behavior**: **Grammarly struggles with Google Docs Canvas mode.** The extension has limited capability to detect and underline canvas-rendered text.

**Waldo decision**: **SKIP for now.** Canvas-based rendering is fundamentally incompatible with DOM-reading content scripts. A solution would require:
- Optical character recognition (OCR) on canvas output, OR
- Grammarly-like deep integration with Google's rendering pipeline (not feasible for a browser extension)

**Detection heuristic**:
```javascript
// Detect Google Docs (Canvas mode)
const isGoogleDocs = 
  window.location.hostname.includes('docs.google.com') &&
  document.querySelector('canvas[data-type="canvas"]') !== null;
  // If canvas present, skip grammar checking
```

---

### 3.9 Banking Sites (Payment Forms)

**Detected by**:
- **Input[type="password"]** — all password fields must be skipped
- **Input[type="number"]** with autocomplete=cc-number — credit card field
- **Input with aria-label containing "CVV", "CVC", "Security Code"** — card security
- **Stripe Elements iframe** — embedded payment processor (cross-origin, skip automatically)
- **PayPal iframe** — embedded payment processor (cross-origin, skip automatically)

**Grammarly behavior**: **Grammarly SKIPS password and payment fields.** Built-in exclusion based on input type.

**Waldo decision**: **SKIP entirely.** Do not attempt grammar checking on:
- `input[type="password"]`
- `input[autocomplete*="cc-"]`
- `input[aria-label*="CVV"]` or `input[aria-label*="Card"]`
- `input[autocomplete="one-time-code"]` (OTP fields)
- Cross-origin iframes (Stripe, PayPal, reCAPTCHA)

**Detection heuristic**:
```javascript
// Skip payment and credential fields
const shouldSkipPayment = 
  element.type === 'password' ||
  element.autocomplete?.includes('cc-') ||
  element.autocomplete?.includes('current-password') ||
  element.autocomplete?.includes('one-time-code') ||
  (element.inputmode === 'numeric' && element.placeholder?.toLowerCase().includes('pin')) ||
  element.aria?.label?.match(/cvv|cvc|security|card|expir/i);
```

---

## 4. iframe and Cross-Origin Handling

### 4.1 Content Script Execution in iframes

Firefox WebExtensions content scripts run in:
- ✓ Top-level window (`window.top === window.self`)
- ✓ Same-origin child iframes (if `all_frames: true` in manifest)
- ✗ Cross-origin iframes (BLOCKED by same-origin policy)
- ✗ Sandboxed iframes (e.g., `<iframe sandbox="allow-scripts">`)

**Practical consequence**: Gmail's compose uses a same-origin iframe; the content script **will** run. Stripe Elements uses a cross-origin iframe; the content script **will not** run (automatically safe).

### 4.2 Detection: window.top !== window.self

```javascript
// Content script can check:
const isInCrossOriginFrame = window.top !== window.self && 
                              window.top.location.origin !== window.location.origin;
if (isInCrossOriginFrame) {
  // Skip all analysis — content script cannot interact with top-level DOM anyway
  return;
}
```

**Decision**: Skip any text input detected inside a cross-origin iframe (which shouldn't happen if content script doesn't run, but check anyway for safety).

### 4.3 Shadow DOM

Some web applications (Slack, Discord, modern AWS services) use Shadow DOM to encapsulate components. Firefox content scripts **cannot pierce Shadow DOM** by default—`element.querySelector()` will not find elements inside a Shadow Root.

**Practical workaround**: 
- Detect Shadow DOM presence: `element.shadowRoot !== null`
- Skip elements in Shadow DOM, OR
- Use MutationObserver on the host element to detect slot-projected content (exposed to light DOM)

---

## 5. WebExtension API Approach — Implementation Notes

### 5.1 Content Script Initialization (manifest.json)

```json
{
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "exclude_matches": [
        "*://localhost/*",
        "*://127.0.0.1/*",
        "*://accounts.google.com/*",
        "*://login.live.com/*",
        "*://accounts.facebook.com/*"
      ],
      "all_frames": true,
      "match_origin_as_fallback": false,
      "js": ["content-script.js"],
      "run_at": "document_idle"
    }
  ]
}
```

**Rationale**:
- `<all_urls>` — catch all sites (both allowlist and blocklist in script, not manifest)
- `exclude_matches` — block known auth pages (avoid credential leakage)
- `all_frames: true` — run in same-origin iframes (Gmail compose, etc.)
- `match_origin_as_fallback: false` — skip data: and blob: pages (generated content, not user input)
- `run_at: document_idle` — avoid blocking page load; allows dynamic editors to load first

### 5.2 Detecting Dynamic Editors (MutationObserver)

Gmail, Slack, Discord, and many SPAs load compose/message editors dynamically (on button click, on route change). Use MutationObserver to detect new inputs:

```javascript
const observerConfig = {
  childList: true,      // Watch for added/removed nodes
  subtree: true,        // Watch entire subtree
  attributes: true,     // Watch attribute changes (class, data-*)
  attributeFilter: ['contenteditable', 'role', 'type']  // Limit to relevant attrs
};

const observer = new MutationObserver((mutations) => {
  mutations.forEach((mutation) => {
    if (mutation.type === 'childList') {
      // New nodes added; check if any are text inputs
      mutation.addedNodes.forEach((node) => {
        const textInputs = node.querySelectorAll(
          'input[type="text"], textarea, [contenteditable="true"][role="textbox"]'
        );
        textInputs.forEach((input) => analyzeInput(input));
      });
    }
  });
});

observer.observe(document.body, observerConfig);
```

**Cost control**: Start with `subtree: true` but monitor performance. If page responsiveness degrades, switch to observing specific containers (`.compose-area`, `.messages-container`) detected via hostname + class heuristics.

### 5.3 Lazy Detection (IntersectionObserver)

For pages with many text inputs (forums, comment threads), use IntersectionObserver to only analyze inputs currently visible:

```javascript
const intersectionConfig = {
  threshold: [0, 0.1, 1.0]  // Fire at 10% visibility
};

const visibilityObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      // Input became visible; queue for analysis
      queueAnalysis(entry.target);
    } else {
      // Input left viewport; can cancel any pending analysis
      cancelAnalysis(entry.target);
    }
  });
}, intersectionConfig);

// Observe all candidate inputs
document.querySelectorAll('input[type="text"], textarea, [contenteditable="true"]').forEach(
  (input) => visibilityObserver.observe(input)
);
```

### 5.4 SPA Route Change Detection

For ChatGPT, Claude.ai, and other SPAs, navigation events don't trigger page reloads. Detect route changes:

```javascript
// Option A: browser.webNavigation.onCommitted (fires on full page loads, not SPA routes)
browser.webNavigation.onCommitted.addListener(({ url }) => {
  if (url.includes('claude.ai') || url.includes('chatgpt.com')) {
    // Reinitialize input detection (old inputs are now stale)
    redetectInputs();
  }
});

// Option B: History API (SPAs use this for client-side routing)
const originalPushState = history.pushState;
window.history.pushState = function(...args) {
  originalPushState.apply(this, args);
  // Route changed; reinitialize
  redetectInputs();
};

// Option C: Use modern Navigation API (future, not widely supported yet)
// navigation.addEventListener('navigate', (e) => { redetectInputs(); });
```

**Note**: For GPT and Claude.ai, both `webNavigation.onCommitted` and route change detection are overkill—the **better solution is a hostname blocklist** (see Tier Routing Decision Tree, Section 6).

---

## 6. Tier Routing Decision Tree

Use this flowchart in the content script to route each detected input to the appropriate tier:

```
Input Element Detected
│
├─ [CROSS-ORIGIN FRAME?]
│  └─ YES → SKIP (content script shouldn't run here anyway)
│
├─ [HOSTNAME BLOCKLIST?] (gmail.com, slack.com, discord.com, etc.)
│  ├─ AI Chat (chatgpt.com, claude.ai)
│  │  └─ SKIP (AI output, not user prose)
│  │
│  ├─ Auth Pages (accounts.google.com, login.live.com)
│  │  └─ SKIP (credentials, same-origin policy exclusion handles this)
│  │
│  └─ Banking/Payment (chase.com, paypal.com, stripe.com)
│     └─ SKIP (payment/credential fields)
│
├─ [GRAMMARLY OPT-OUT ATTRIBUTES?]
│  ├─ data-gramm="false" OR
│  ├─ data-gramm_editor="false" OR
│  ├─ data-enable-grammarly="false"
│  └─ YES → SKIP (respect author intent)
│
├─ [PASSWORD/CREDENTIAL FIELD?]
│  ├─ input[type="password"] OR
│  ├─ autocomplete="current-password|new-password|cc-*|one-time-code" OR
│  ├─ inputmode="numeric" + aria-label contains "PIN|Password" OR
│  ├─ aria-label contains "CVV|CVC|Card"
│  └─ YES → SKIP (PII)
│
├─ [READ-ONLY OR SPELLCHECK DISABLED?]
│  ├─ contenteditable="false" OR
│  ├─ spellcheck="false" OR
│  ├─ role="log|status|combobox"
│  └─ YES → SKIP (author intent or read-only)
│
├─ [EDITOR-SPECIFIC PATTERNS?]
│  ├─ CodeMirror detected? → SKIP code blocks, use MID for prose
│  ├─ Monaco detected? → SKIP entirely (IDE, not prose)
│  ├─ Notion detected? → FAST ONLY (canvas/custom rendering is fragile)
│  ├─ Google Docs detected? → SKIP (canvas rendering, DOM unavailable)
│  └─ Continue to next check
│
├─ [INPUT SCOPE & LENGTH HEURISTICS]
│  ├─ input[type="email|search|url|number|tel"] → FAST
│  ├─ input[type="text"] with maxlength <50 OR size<50 → FAST
│  ├─ input[type="text"] with maxlength >=50 OR size>=50 → MID
│  ├─ textarea → MID (assume user will type prose)
│  ├─ contenteditable[role="textbox"] in email/chat context → MID
│  ├─ contenteditable[role="textbox"] + [aria-label="Message"] → MID (Chat/Email)
│  └─ contenteditable[role="textbox"] (generic) → MID
│
├─ [USER CONTEXT SIGNALS]
│  ├─ contenteditable with >500 characters already present → SMART
│  ├─ Explicit user invocation (right-click, menu button) → SMART
│  └─ Default keystroke-level (MutationObserver trigger) → MID/FAST
│
└─ [DEFAULT]
   └─ MID (Unbabel gec-t5_small) — safe, reasonable latency, broad coverage
```

### 6.1 Routing Decisions Summary

| Context | Tier | Latency Target | Rationale |
|---------|------|---|----------|
| Password, payment, OTP fields | **SKIP** | N/A | PII, always skip |
| AI chat inputs (ChatGPT, Claude, Copilot) | **SKIP** | N/A | AI output, out of scope |
| Search boxes, email fields, 1-word inputs | **FAST** (Nuspell) | <5 ms | Keystroke-level feedback, spelling only |
| Email bodies, message bodies (Slack, Discord, Gmail), issue bodies | **MID** (Unbabel gec-t5) | 25–40 ms | Medium prose, user-triggered or light background check |
| Long-form prose (blog comments, forum posts, document bodies >200 words) | **SMART** (Qwen2.5-3B) | 400–550 ms | Tone, style, complex grammar; user-triggered only |
| Code editors (CodeMirror, Monaco, VS Code) | **SKIP** | N/A | Code, not prose; grammar checking nonsensical |
| Custom editors (Notion, Google Docs Canvas) | **SKIP** or **FAST** | <5 ms | Limited DOM access or canvas rendering; spell-check only as fallback |
| contenteditable with `data-gramm="false"` | **SKIP** | N/A | Grammarly standard, respect author intent |
| contenteditable with `spellcheck="false"` | **SKIP** | N/A | Native HTML signal, respect author intent |

---

## 7. Special Cases & Edge Conditions

### 7.1 Auto-Suggestions vs. Keystroke Feedback

- **Fast tier (Nuspell)**: Can run on keystroke (`input` event) without blocking UX
- **Mid tier (Unbabel)**: Suitable for keystroke, but 25–40 ms latency may feel sluggish; debounce to 200–300 ms delays
- **Smart tier (Qwen)**: Always explicit user invocation (menu button, keyboard shortcut); never keystroke-triggered

**Recommendation**: 
- FAST: Fire on every keystroke, no debounce
- MID: Debounce keystroke to 300 ms (wait until user pauses), OR fire on explicit button click
- SMART: Only explicit user action (Cmd/Ctrl+Shift+G for grammar, etc.)

### 7.2 Copy-Paste Detection

When user pastes text (e.g., from ChatGPT into an email), MutationObserver detects DOM changes. Waldo **should** offer to analyze pasted content:
- If pasted text >20 words, suggest **MID tier** immediately
- If >200 words, offer **SMART tier** option
- Tie to a "Paste hint" popup: "Check grammar?" with Dismiss / Check / Smart buttons

### 7.3 Multiple Inputs on Same Page

A blog comment form might have:
- Title field (text, <50 chars) → FAST
- Comment body (textarea) → MID
- Email field (input[type="email"]) → FAST

Waldo must detect and handle **each independently**. Use a `Map<Element, Tier>` to track routing decisions per input.

### 7.4 Frame Reload / DOM Mutations

If a content script detects an input, runs MID-tier analysis, and the input is then replaced (e.g., user clears compose window), the old Promise/worker should be cancelled to avoid stale results.

---

## 8. Open Questions for Task 4 Test Harness

These questions remain unresolved and must be tested during Task 4 (instrumented harness):

1. **T5 GGUF Conversion**: Can llama.cpp reliably serve Unbabel/gec-t5_small in GGUF format? (Blocking Task 3 wrapper build if not)

2. **ProseMirror Detection**: What is the exact class chain or global marker for Claude.ai's ProseMirror instance? (Need DOM inspection)

3. **Gmail Compose MutationObserver Timing**: How long after user clicks "Compose" before the contenteditable div is injected? (Critical for detecting dynamic editors)

4. **IntersectionObserver Overhead**: On a page with 100+ comment inputs (HackerNews, Reddit), does full IntersectionObserver + MutationObserver tracking cause noticeable CPU impact? (Need performance profiling)

5. **Grammarly Data Attribute Coverage**: Are there other Grammarly-specific data attributes beyond `data-gramm`, `data-gramm_editor`, `data-enable-grammarly`? (Scan Grammarly GitHub issues)

6. **CodeMirror Class Stability**: Does `.CodeMirror` class remain stable across CodeMirror v5, v6, and future versions? (Or should we detect by `window.CodeMirror` global?)

7. **Shadow DOM Content**: If a text input is projected into light DOM via slot (inside Shadow DOM), can MutationObserver detect it? (Or is deep inspection required?)

8. **SPA Route Detection Reliability**: For ChatGPT and Claude.ai SPAs, is `history.pushState` interception reliable across all browsers, or is there a race condition with content script initialization? (Timing test needed)

9. **Notion Canvas Rendering**: Has Notion fully migrated to canvas rendering (like Google Docs), or is the DOM-based editor still present alongside? (Current state check)

10. **Firefox vs. Chrome MV3 Quirks**: Are there known Firefox-specific behaviors in content script execution, iframe handling, or Shadow DOM that differ from Chrome? (Document for portability)

---

## 9. Recommendations for Task 3 (Wrapper Build)

### 9.1 Context Detection Module

Implement in `waldo_spells_context.py` (or equivalent):

```python
class InputContext:
    """Tier routing decision for a detected text input."""
    tier: Literal["SKIP", "FAST", "MID", "SMART"]
    reason: str  # Human-readable explanation for debugging
    hostname: str
    element_id: str
    element_type: str  # "textarea", "input", "contenteditable", etc.
    
def detect_tier(element: dict) -> InputContext:
    """
    Analyze DOM element metadata and return tier routing.
    
    Args:
        element: Dict with keys like 'type', 'role', 'aria_label', 
                 'data_gramm', 'spellcheck', 'hostname', 'length_hint'
    
    Returns:
        InputContext with tier and reason
    """
    # Implement decision tree from Section 6
    pass
```

### 9.2 Test Coverage

Validate routing on:
- 20+ real-world inputs (manual DOM inspection from GitHub, Gmail, Slack, etc.)
- Synthetic test cases (password fields, code editors, payment forms)
- Edge cases (nested contenteditable, Shadow DOM, cross-origin iframes)

### 9.3 Firefox Content Script Template

Provide `content-script.js` scaffold with:
- Input detection (querySelector + MutationObserver)
- Tier routing (call `detectTier()` from wrapper)
- Message passing to background script (send text to llama.cpp wrapper)
- Result injection (underlines, tooltips, suggestions)

---

## 10. Summary — Core Heuristic for Implementation

**The Waldo Spells context detection heuristic**:

1. **Skip first**: Check Grammaly blocklist attributes, password fields, read-only markers. If any match, SKIP immediately.

2. **Hostname allowlist**: Allow all sites except known auth/payment pages (Gmail, Slack, Discord are safe).

3. **Editor detection**: Identify CodeMirror, Monaco, Notion, Google Docs. Skip or degrade tier for unsupported editors.

4. **Input scope**: Use `type`, `role`, `maxlength`, `size`, `aria-label` to infer typical content length (short query vs. long prose).

5. **Tier assignment**:
   - **Short, single-purpose inputs** (search, email field, password attempts) → FAST
   - **Medium prose** (email body, chat message, issue comment) → MID
   - **Long-form or explicit user action** → SMART
   - **Uncertain/default** → MID (safe middle ground)

6. **Dynamic detection**: Use MutationObserver to catch async-loaded editors (Gmail, Slack), and IntersectionObserver to avoid analyzing off-screen inputs.

7. **Respect author intent**: Always honor `data-gramm="false"` and `spellcheck="false"`. The user's website designer made a deliberate choice; don't override it.

---

## Data Sources & References

- [Grammarly Contenteditable GitHub](https://github.com/grammarly/contenteditable)
- [MDN Web Docs: Content Scripts](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_scripts)
- [MDN Web Docs: webNavigation.onCommitted](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webNavigation/onCommitted)
- [W3C: HTML Global spellcheck Attribute](https://www.w3schools.com/tags/att_global_spellcheck.asp)
- [Can I Use: Spellcheck Attribute](https://caniuse.com/spellcheck-attribute)
- [MDN: HTML autocomplete Attribute](https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/autocomplete)
- [GitHub: Grammarly Disable Patterns (Slate Issue #4124)](https://github.com/ianstormtaylor/slate/issues/4124)
- [Grammarly Engineering Blog: Making Grammarly Feel Native](https://www.grammarly.com/blog/engineering/making-grammarly-feel-native-on-every-website/)
- [ProseMirror Reference Manual](https://prosemirror.net/docs/ref/)
- [The New Stack: Google Docs Canvas Rendering](https://thenewstack.io/google-docs-switches-to-canvas-rendering-sidelining-the-dom/)
- [Chrome Developers: Navigation API](https://developer.chrome.com/docs/web-platform/navigation-api)
- [MDN: Same-Origin Policy](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy)
- [Mozilla Discourse: Firefox WebExtension MV3 Content Scripts](https://discourse.mozilla.org/t/mv3-cannot-get-content-script-to-run-in-firefox-no-errors-and-no-loglines-to-be-found/99589)

---

**Document Status**: Research Complete — Ready for Task 3 wrapper implementation and Task 4 test harness validation.
