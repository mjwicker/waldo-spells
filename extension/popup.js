const toggle       = document.getElementById("toggle");
const serverStatus = document.getElementById("server-status");

// Restore saved toggle state
browser.storage.local.get("enabled").then(({ enabled = true }) => {
  toggle.checked = enabled;
});

toggle.addEventListener("change", () => {
  browser.storage.local.set({ enabled: toggle.checked });
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
