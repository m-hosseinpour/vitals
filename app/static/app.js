(() => {
  "use strict";

  const dashboard = document.getElementById("dashboard");
  if (!dashboard) {
    return;
  }

  const INTERVAL_MS = 60000;
  const CHECK_MS = 15000;
  const refreshUrl = dashboard.dataset.refreshUrl;
  const refreshButton = document.querySelector("[data-refresh]");
  const refreshLabel = refreshButton?.querySelector(".refresh-label");

  const LABELS = {
    idle: "به‌روزرسانی",
    loading: "به‌روزرسانی…",
    success: "به‌روزرسانی شد",
    error: "ناموفق",
  };

  let busy = false;
  let lastFetch = Date.now();
  let resetTimer;

  function setButtonState(state, message = "") {
    if (!refreshButton || !refreshLabel) {
      return;
    }
    clearTimeout(resetTimer);
    refreshButton.classList.toggle("is-loading", state === "loading");
    refreshButton.classList.toggle("is-success", state === "success");
    refreshButton.classList.toggle("is-error", state === "error");
    refreshLabel.textContent = LABELS[state];
    if (state === "loading") {
      refreshButton.setAttribute("aria-busy", "true");
    } else {
      refreshButton.removeAttribute("aria-busy");
    }
    if (state === "error" && message) {
      refreshButton.title = message;
    } else {
      refreshButton.removeAttribute("title");
    }
    if (state === "success") {
      resetTimer = window.setTimeout(() => setButtonState("idle"), 2000);
    } else if (state === "error") {
      resetTimer = window.setTimeout(() => setButtonState("idle"), 4000);
    }
  }

  function updateHeaderTimestamp(container) {
    const target = document.querySelector("[data-updated-label]");
    if (!target) {
      return;
    }
    const ago = container?.dataset.updatedAgo || "—";
    const clock = container?.dataset.updatedClock || "—";
    target.textContent = clock === "—" ? ago : `${ago} (${clock})`;
  }

  async function refresh(manual) {
    if (busy || document.hidden) {
      return;
    }
    busy = true;
    if (manual) {
      setButtonState("loading");
      dashboard.classList.add("is-refreshing");
      dashboard.setAttribute("aria-busy", "true");
    }
    try {
      const response = await fetch(refreshUrl, {
        headers: { Accept: "text/html" },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, "text/html");
      const next = parsed.getElementById("dashboard-content");
      const current = document.getElementById("dashboard-content");
      if (!next || !current) {
        throw new Error("missing dashboard content");
      }
      const imported = document.importNode(next, true);
      current.replaceWith(imported);
      updateHeaderTimestamp(imported);
      if (manual) {
        setButtonState("success");
      }
    } catch (error) {
      setButtonState("error", "به‌روزرسانی ممکن نشد؛ اعداد قبلی نمایش داده می‌شوند.");
    } finally {
      busy = false;
      lastFetch = Date.now();
      if (manual) {
        dashboard.classList.remove("is-refreshing");
        dashboard.removeAttribute("aria-busy");
      }
    }
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-refresh]");
    if (!trigger) {
      return;
    }
    event.preventDefault();
    refresh(true);
  });

  window.setInterval(() => {
    if (document.hidden) {
      return;
    }
    if (Date.now() - lastFetch >= INTERVAL_MS) {
      refresh(false);
    }
  }, CHECK_MS);
})();
