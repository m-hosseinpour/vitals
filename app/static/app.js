(() => {
  "use strict";

  const dashboard = document.getElementById("dashboard");
  if (!dashboard) {
    return;
  }

  const INTERVAL_MS = 60000;
  const CHECK_MS = 15000;
  const refreshUrl = dashboard.dataset.refreshUrl;
  let busy = false;
  let lastFetch = Date.now();

  function setStatus(text, isError) {
    const status = document.getElementById("refresh-status");
    if (!status) {
      return;
    }
    status.textContent = text;
    status.classList.toggle("is-error", Boolean(isError));
  }

  async function refresh() {
    if (busy || document.hidden) {
      return;
    }
    busy = true;
    dashboard.classList.add("is-refreshing");
    dashboard.setAttribute("aria-busy", "true");
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
      current.replaceWith(document.importNode(next, true));
      lastFetch = Date.now();
      setStatus("به‌روزرسانی شد.", false);
      window.setTimeout(() => {
        const status = document.getElementById("refresh-status");
        if (status && status.textContent === "به‌روزرسانی شد.") {
          status.textContent = "";
        }
      }, 2500);
    } catch (error) {
      setStatus("به‌روزرسانی ممکن نشد؛ اعداد قبلی نمایش داده می‌شوند.", true);
    } finally {
      busy = false;
      dashboard.classList.remove("is-refreshing");
      dashboard.removeAttribute("aria-busy");
    }
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-refresh]");
    if (!trigger) {
      return;
    }
    event.preventDefault();
    setStatus("در حال به‌روزرسانی…", false);
    refresh();
  });

  window.setInterval(() => {
    if (document.hidden) {
      return;
    }
    if (Date.now() - lastFetch >= INTERVAL_MS) {
      refresh();
    }
  }, CHECK_MS);
})();
