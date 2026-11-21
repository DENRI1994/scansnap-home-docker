(() => {
  "use strict";

  const API_BASE = "scansnap-api";
  const POLL_MS = 2000;
  let pollTimer = null;
  let busy = false;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  async function apiGetStatus() {
    const res = await fetch(`${API_BASE}/status`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function apiAction(body) {
    const res = await fetch(`${API_BASE}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function isSidebarVisible() {
    const anchor = document.getElementById("noVNC_control_bar_anchor");
    const collapse = document.getElementById("scansnapSidebarCollapse");
    return Boolean(
      anchor &&
      !anchor.classList.contains("noVNC_hidden") &&
      collapse &&
      collapse.classList.contains("show")
    );
  }

  function renderWindows(container, windows) {
    container.replaceChildren();
    if (!windows || windows.length === 0) {
      container.appendChild(el("div", "text-muted small py-1", "No open windows found."));
      return;
    }

    for (const w of windows) {
      const btn = el(
        "button",
        `btn btn-sm w-100 text-start d-flex align-items-center justify-content-between mb-1 ${
          w.active ? "btn-primary" : "btn-outline-secondary"
        }`
      );
      btn.type = "button";
      btn.title = `${w.title} (${w.wm_class}, ${w.width}x${w.height})`;

      const left = el("span", "text-truncate me-1");
      const icon = el("i", `fas ${w.is_dialog ? "fa-window-restore" : "fa-window-maximize"} fa-fw me-1`);
      left.appendChild(icon);
      left.appendChild(document.createTextNode(w.title));

      const right = el("span", "d-flex align-items-center flex-shrink-0");
      if (w.minimized) {
        right.appendChild(el("span", "badge bg-warning text-dark me-1", "min"));
      } else if (w.is_dialog) {
        right.appendChild(el("span", "badge bg-info text-dark me-1", "Dialog"));
      }
      right.appendChild(el("small", "opacity-75", `${w.width}x${w.height}`));

      btn.appendChild(left);
      btn.appendChild(right);
      btn.addEventListener("click", async () => {
        try {
          await apiAction({ action: "focus_window", id: w.id });
          setTimeout(refresh, 250);
        } catch (err) {
          console.error("[scansnap-sidebar]", err);
        }
      });
      container.appendChild(btn);
    }
  }

  function renderServices(container, services) {
    container.replaceChildren();
    if (!services || services.length === 0) {
      container.appendChild(el("div", "text-muted small py-1", "No services reported."));
      return;
    }

    for (const s of services) {
      const row = el("div", "d-flex align-items-center justify-content-between py-1 border-bottom border-opacity-10");
      const info = el("div", "d-flex align-items-center text-truncate me-1");
      const dot = el(
        "span",
        `badge rounded-pill me-2 ${s.running ? "bg-success" : "bg-secondary"}`,
        s.running ? "on" : "off"
      );
      dot.style.minWidth = "2.1rem";
      info.appendChild(dot);
      info.appendChild(el("span", "small text-truncate", s.label));

      const grp = el("div", "btn-group btn-group-sm flex-shrink-0");
      if (s.running) {
        const restartBtn = el("button", "btn btn-outline-secondary py-0 px-2");
        restartBtn.type = "button";
        restartBtn.title = `Restart ${s.label}`;
        restartBtn.appendChild(el("i", "fas fa-redo fa-xs"));
        restartBtn.addEventListener("click", async () => {
          restartBtn.disabled = true;
          try {
            await apiAction({ action: "service", target: s.key, op: "restart" });
            setTimeout(refresh, 700);
          } finally {
            restartBtn.disabled = false;
          }
        });

        const stopBtn = el("button", "btn btn-outline-danger py-0 px-2");
        stopBtn.type = "button";
        stopBtn.title = `Stop ${s.label}`;
        stopBtn.appendChild(el("i", "fas fa-stop fa-xs"));
        stopBtn.addEventListener("click", async () => {
          stopBtn.disabled = true;
          try {
            await apiAction({ action: "service", target: s.key, op: "stop" });
            setTimeout(refresh, 400);
          } finally {
            stopBtn.disabled = false;
          }
        });

        grp.appendChild(restartBtn);
        grp.appendChild(stopBtn);
      } else {
        const startBtn = el("button", "btn btn-outline-success py-0 px-2");
        startBtn.type = "button";
        startBtn.title = `Start ${s.label}`;
        startBtn.appendChild(el("i", "fas fa-play fa-xs"));
        startBtn.addEventListener("click", async () => {
          startBtn.disabled = true;
          try {
            await apiAction({ action: "service", target: s.key, op: "start" });
            setTimeout(refresh, 700);
          } finally {
            startBtn.disabled = false;
          }
        });
        grp.appendChild(startBtn);
      }

      row.appendChild(info);
      row.appendChild(grp);
      container.appendChild(row);
    }
  }

  async function refresh() {
    if (busy) return;
    const winBox = document.getElementById("scansnap_windows_list");
    const svcBox = document.getElementById("scansnap_services_list");
    const errBox = document.getElementById("scansnap_api_error");
    if (!winBox || !svcBox) return;

    busy = true;
    try {
      const data = await apiGetStatus();
      if (errBox) errBox.classList.add("d-none");
      renderWindows(winBox, data.windows);
      renderServices(svcBox, data.services);
    } catch (err) {
      if (errBox) {
        errBox.textContent = `Service unavailable (${err.message})`;
        errBox.classList.remove("d-none");
      }
    } finally {
      busy = false;
    }
  }

  function syncPolling() {
    if (isSidebarVisible()) {
      if (!pollTimer) {
        refresh();
        pollTimer = setInterval(refresh, POLL_MS);
      }
    } else if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function initSidebar() {
    if (document.getElementById("noVNC_scansnap_section")) return;
    const listGroup = document.querySelector("#noVNC_control_bar ul.list-group");
    const actionIcons = document.getElementById("noVNC_action_icons_section");
    if (!listGroup || !actionIcons) return;

    const li = el("li", "list-group-item");
    li.id = "noVNC_scansnap_section";

    const label = el("label", "custom-accordion-button text-nowrap", "Windows & Services");
    label.setAttribute("data-bs-toggle", "collapse");
    label.setAttribute("data-bs-target", "#scansnapSidebarCollapse");

    const collapse = el("div", "collapse show");
    collapse.id = "scansnapSidebarCollapse";

    const errBox = el("div", "alert alert-warning py-1 px-2 small d-none mb-2");
    errBox.id = "scansnap_api_error";

    const topBtns = el("div", "d-flex gap-1 mb-2");
    const raiseBtn = el("button", "btn btn-sm btn-outline-primary flex-grow-1");
    raiseBtn.type = "button";
    raiseBtn.appendChild(el("i", "fas fa-layer-group fa-fw me-1"));
    raiseBtn.appendChild(document.createTextNode("Bring dialogs to front"));
    raiseBtn.addEventListener("click", async () => {
      raiseBtn.disabled = true;
      try {
        await apiAction({ action: "raise_dialogs" });
        setTimeout(refresh, 250);
      } finally {
        raiseBtn.disabled = false;
      }
    });

    const refBtn = el("button", "btn btn-sm btn-outline-secondary");
    refBtn.type = "button";
    refBtn.title = "Refresh";
    refBtn.appendChild(el("i", "fas fa-sync fa-fw"));
    refBtn.addEventListener("click", refresh);

    topBtns.appendChild(raiseBtn);
    topBtns.appendChild(refBtn);

    const winHeader = el("div", "small fw-semibold text-uppercase opacity-75 mb-1", "Open Windows");
    const winBox = el("div", "mb-2");
    winBox.id = "scansnap_windows_list";

    const svcHeader = el("div", "small fw-semibold text-uppercase opacity-75 mb-1", "Background Services");
    const svcBox = el("div", "");
    svcBox.id = "scansnap_services_list";

    collapse.appendChild(errBox);
    collapse.appendChild(topBtns);
    collapse.appendChild(winHeader);
    collapse.appendChild(winBox);
    collapse.appendChild(svcHeader);
    collapse.appendChild(svcBox);

    li.appendChild(label);
    li.appendChild(collapse);
    actionIcons.insertAdjacentElement("afterend", li);

    const anchor = document.getElementById("noVNC_control_bar_anchor");
    if (anchor) {
      new MutationObserver(syncPolling).observe(anchor, {
        attributes: true,
        attributeFilter: ["class"],
      });
    }
    collapse.addEventListener("shown.bs.collapse", syncPolling);
    collapse.addEventListener("hidden.bs.collapse", syncPolling);
    syncPolling();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSidebar);
  } else {
    initSidebar();
  }
})();
