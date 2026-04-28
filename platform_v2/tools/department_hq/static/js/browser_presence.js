/**
 * Browser Persona System — Online Presence tab JS
 * Project #287 Task 13
 *
 * All user-supplied strings go through escapeHtml() before being inserted
 * into the DOM. No raw innerHTML with untrusted data.
 */

(function () {
  "use strict";

  // ── Helpers ──────────────────────────────────────────────────────────────

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function apiBase() {
    return "/api/department-hq";
  }

  async function apiFetch(path, opts) {
    const resp = await fetch(apiBase() + path, opts);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(err.error || resp.statusText);
    }
    return resp.json();
  }

  // ── State ─────────────────────────────────────────────────────────────────

  let _currentAgentId = null;

  // ── Exported functions ────────────────────────────────────────────────────

  window.bpInit = function () {
    _loadAgentDropdown();
  };

  window.bpLoadAgent = function (agentId) {
    _currentAgentId = agentId ? parseInt(agentId, 10) : null;
    const hasSel = !!_currentAgentId;
    document.getElementById("bp-sessions-panel").style.display = hasSel ? "" : "none";
    document.getElementById("bp-quick-task-panel").style.display = hasSel ? "" : "none";
    document.getElementById("bp-task-log-panel").style.display = hasSel ? "" : "none";
    if (hasSel) {
      bpRefreshSessions();
      bpRefreshTaskLog();
      _loadSkillDropdown();
    }
  };

  window.bpRefreshSessions = function () {
    if (!_currentAgentId) return;
    const list = document.getElementById("bp-sessions-list");
    list.textContent = "Loading…";
    apiFetch("/api/browser/sessions/" + _currentAgentId)
      .then(function (data) {
        _renderSessions(list, data.sessions || []);
      })
      .catch(function (err) {
        list.textContent = "Error: " + escapeHtml(err.message);
      });
  };

  window.bpRefreshTaskLog = function () {
    if (!_currentAgentId) return;
    const list = document.getElementById("bp-task-log-list");
    list.textContent = "Loading…";
    apiFetch("/api/browser/task-log?agent_id=" + _currentAgentId + "&limit=50")
      .then(function (data) {
        _renderTaskLog(list, data.tasks || []);
      })
      .catch(function (err) {
        list.textContent = "Error: " + escapeHtml(err.message);
      });
  };

  window.bpOpenSetupModal = function () {
    const modal = document.getElementById("bp-setup-modal");
    if (modal) {
      modal.style.display = "flex";
    }
  };

  window.bpCloseSetupModal = function () {
    const modal = document.getElementById("bp-setup-modal");
    if (modal) {
      modal.style.display = "none";
      // Clear sensitive fields
      const pw = document.getElementById("bp-setup-password");
      if (pw) pw.value = "";
    }
  };

  window.bpSaveSession = async function () {
    if (!_currentAgentId) return;
    const platform = document.getElementById("bp-setup-platform").value;
    const username = document.getElementById("bp-setup-username").value.trim();
    const password = document.getElementById("bp-setup-password").value;
    const errEl = document.getElementById("bp-setup-error");

    if (!platform || !username || !password) {
      errEl.textContent = "All fields required.";
      return;
    }
    errEl.textContent = "";

    try {
      await apiFetch("/api/browser/sessions/" + _currentAgentId + "/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform, username, password }),
      });
      bpCloseSetupModal();
      bpRefreshSessions();
    } catch (err) {
      errEl.textContent = "Setup failed: " + escapeHtml(err.message);
    }
  };

  window.bpRunTask = async function () {
    if (!_currentAgentId) return;
    const skill = document.getElementById("bp-skill-select").value;
    if (!skill) {
      alert("Select a skill first.");
      return;
    }
    try {
      const data = await apiFetch("/api/browser/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: _currentAgentId,
          skill: skill,
          params: {},
          triggered_by: "dhq_online_presence",
        }),
      });
      alert("Task queued — log ID " + (data.log_id || "?"));
      bpRefreshTaskLog();
    } catch (err) {
      alert("Task failed: " + escapeHtml(err.message));
    }
  };

  // ── Private helpers ───────────────────────────────────────────────────────

  function _loadAgentDropdown() {
    const sel = document.getElementById("bp-agent-select");
    if (!sel) return;
    // Fetch internal agents only (browser tasks are internal-only)
    fetch("/api/department-hq/api/roster?worker_type=internal&limit=200")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        const agents = data.agents || data || [];
        agents.forEach(function (a) {
          const opt = document.createElement("option");
          opt.value = a.id;
          opt.textContent = escapeHtml(a.display_name || a.name);
          sel.appendChild(opt);
        });
      })
      .catch(function () {
        // Non-fatal — dropdown stays empty with placeholder
      });
  }

  function _loadSkillDropdown() {
    const sel = document.getElementById("bp-skill-select");
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);

    apiFetch("/api/browser/skills")
      .then(function (data) {
        (data.skills || []).forEach(function (skill) {
          const opt = document.createElement("option");
          opt.value = escapeHtml(skill);
          opt.textContent = escapeHtml(skill);
          sel.appendChild(opt);
        });
      })
      .catch(function () {
        // Non-fatal — skill list stays empty
      });
  }

  function _renderSessions(container, sessions) {
    while (container.firstChild) container.removeChild(container.firstChild);

    if (!sessions.length) {
      const msg = document.createElement("span");
      msg.style.color = "#9ca3af";
      msg.style.fontSize = "0.8rem";
      msg.textContent = "No sessions yet.";
      container.appendChild(msg);
      return;
    }

    sessions.forEach(function (s) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #1f2937;font-size:0.8rem";

      const platform = document.createElement("span");
      platform.style.cssText = "color:#60a5fa;font-family:'Antonio',sans-serif;letter-spacing:1px;min-width:80px";
      platform.textContent = escapeHtml((s.platform || "").toUpperCase());
      row.appendChild(platform);

      const user = document.createElement("span");
      user.style.color = "#e2e8f0";
      user.textContent = escapeHtml(s.username || "—");
      row.appendChild(user);

      const status = document.createElement("span");
      status.style.cssText = "margin-left:auto;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:600";
      const st = (s.status || "unknown").toLowerCase();
      status.style.background = st === "active" ? "rgba(34,197,94,0.2)" : "rgba(156,163,175,0.2)";
      status.style.color = st === "active" ? "#4ade80" : "#9ca3af";
      status.textContent = escapeHtml(st.toUpperCase());
      row.appendChild(status);

      container.appendChild(row);
    });
  }

  function _renderTaskLog(container, tasks) {
    while (container.firstChild) container.removeChild(container.firstChild);

    if (!tasks.length) {
      const msg = document.createElement("span");
      msg.style.color = "#9ca3af";
      msg.style.fontSize = "0.8rem";
      msg.textContent = "No tasks yet.";
      container.appendChild(msg);
      return;
    }

    tasks.forEach(function (t) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #1f2937;font-size:0.75rem";

      const ts = document.createElement("span");
      ts.style.color = "#6b7280";
      ts.style.minWidth = "140px";
      ts.textContent = t.created_at ? escapeHtml(t.created_at.slice(0, 19).replace("T", " ")) : "—";
      row.appendChild(ts);

      const skill = document.createElement("span");
      skill.style.cssText = "color:#60a5fa;min-width:140px";
      skill.textContent = escapeHtml(t.skill || "—");
      row.appendChild(skill);

      const platform = document.createElement("span");
      platform.style.cssText = "color:#94a3b8;min-width:80px";
      platform.textContent = escapeHtml(t.platform || "—");
      row.appendChild(platform);

      const statusEl = document.createElement("span");
      statusEl.style.cssText = "margin-left:auto;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:600";
      const st = (t.status || "unknown").toLowerCase();
      const stColors = {
        completed: ["rgba(34,197,94,0.2)", "#4ade80"],
        running: ["rgba(251,191,36,0.2)", "#fbbf24"],
        failed: ["rgba(239,68,68,0.2)", "#f87171"],
        pending: ["rgba(156,163,175,0.15)", "#9ca3af"],
      };
      const [bg, fg] = stColors[st] || ["rgba(156,163,175,0.15)", "#9ca3af"];
      statusEl.style.background = bg;
      statusEl.style.color = fg;
      statusEl.textContent = escapeHtml(st.toUpperCase());
      row.appendChild(statusEl);

      container.appendChild(row);
    });
  }

  // ── Tab activation hook ───────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    // DHQ tab switching dispatches a custom event or calls switchDHQTab.
    // Hook into the tab click by observing panel visibility changes.
    // Also initialise immediately in case tab is already active.
    const panel = document.getElementById("panel-online-presence");
    if (!panel) return;

    // Observe when the panel gains the "active" class
    const observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        if (m.type === "attributes" && m.attributeName === "class") {
          if (panel.classList.contains("active") && !panel.dataset.bpInited) {
            panel.dataset.bpInited = "1";
            bpInit();
          }
        }
      });
    });
    observer.observe(panel, { attributes: true });

    // If already active on load
    if (panel.classList.contains("active")) {
      panel.dataset.bpInited = "1";
      bpInit();
    }
  });
})();
