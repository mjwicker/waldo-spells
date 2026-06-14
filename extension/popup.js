const toggle                  = document.getElementById("toggle");
const browserSpellcheckToggle = document.getElementById("browser-spellcheck-toggle");
const serverStatus            = document.getElementById("server-status");
const smartStatus             = document.getElementById("smart-status");
const smartBtn                = document.getElementById("smart-btn");

// Restore saved toggle states
browser.storage.local.get(["enabled", "suppressBrowserSpellcheck"]).then((stored) => {
  toggle.checked = stored.enabled !== false;
  // suppressBrowserSpellcheck defaults ON (browser checker hidden when Waldo is active)
  const suppress = stored.suppressBrowserSpellcheck !== false;
  browserSpellcheckToggle.checked = !suppress; // toggle shows "browser spellcheck ON/OFF"
});

toggle.addEventListener("change", () => {
  browser.storage.local.set({ enabled: toggle.checked });
});

// "Browser spellcheck" toggle: checked = browser checker visible, unchecked = hidden
browserSpellcheckToggle.addEventListener("change", () => {
  const suppress = !browserSpellcheckToggle.checked;
  browser.storage.local.set({ suppressBrowserSpellcheck: suppress });
  // Notify all content scripts in the active tab to apply immediately
  browser.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
    if (!tabs.length) return;
    browser.tabs.sendMessage(tabs[0].id, {
      action: "set_browser_spellcheck",
      suppress,
    }).catch(() => {});
  });
});

// Check server health on open
browser.runtime.sendMessage({ action: "health" })
  .then(({ ok }) => {
    serverStatus.textContent = ok ? "connected" : "not running";
    serverStatus.className   = "status " + (ok ? "ok" : "err");
  })
  .catch(() => {
    serverStatus.textContent = "not running";
    serverStatus.className   = "status err";
  });

// Check Smart tier status on open
browser.runtime.sendMessage({ action: "smart_status" })
  .then((status) => {
    if (!status) { smartStatus.textContent = "unknown"; return; }
    if (status.available) {
      smartStatus.textContent = "ready";
      smartStatus.className   = "status ok";
    } else {
      // Show a short version of the message that fits the popup width
      const msg = status.message || "unavailable";
      smartStatus.textContent = status.hardware_ok ? "offline" : "needs RAM";
      smartStatus.className   = "status err";
      smartStatus.title       = msg; // full message on hover
    }
  })
  .catch(() => {
    smartStatus.textContent = "unknown";
    smartStatus.className   = "status";
  });

// On-demand Smart analysis — relay to the active tab's content script
smartBtn.addEventListener("click", () => {
  browser.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
    if (!tabs.length) return;
    browser.tabs.sendMessage(tabs[0].id, { action: "smart_demand" }).catch(() => {
      // Content script not injected on this page — ignore silently
    });
  });
});
