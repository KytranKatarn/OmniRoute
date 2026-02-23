/* consciousness.js — A.R.C.H.I.E. Consciousness Module */
/* globals: lucide */
"use strict";

var _cache = {};
var _debounceTimers = {};

/* ── Utilities ─────────────────────────────────────── */

function escHtml(str) {
  if (str == null) return "";
  var div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

function setHtml(el, html) {
  if (typeof el === "string") el = document.getElementById(el);
  if (el) el.innerHTML = html;
}

function formatAge(dateStr) {
  if (!dateStr) return "\u2014";
  var d = new Date(dateStr);
  var diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
}

function refreshIcons() {
  if (typeof lucide !== "undefined" && lucide.createIcons) {
    lucide.createIcons();
  }
}

function debounceReload(tabName, fn) {
  clearTimeout(_debounceTimers[tabName]);
  _debounceTimers[tabName] = setTimeout(function () {
    _cache[tabName] = false;
    fn();
  }, 300);
}

/* ── API Helper ────────────────────────────────────── */

function api(path, opts) {
  opts = opts || {};
  var url = "/tools/consciousness" + path;
  var fetchOpts = { headers: {} };
  if (opts.method) fetchOpts.method = opts.method;
  if (opts.body) {
    fetchOpts.method = fetchOpts.method || "POST";
    fetchOpts.headers["Content-Type"] = "application/json";
    fetchOpts.body = JSON.stringify(opts.body);
  }
  return fetch(url, fetchOpts).then(function (resp) {
    return resp.json();
  });
}

/* ── Tab Switching ─────────────────────────────────── */

window.switchConsciousnessTab = function (tab) {
  document.querySelectorAll(".cs-tab").forEach(function (btn) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".cs-panel").forEach(function (panel) {
    panel.classList.toggle("active", panel.id === "panel-" + tab);
  });
  history.replaceState(null, "", "#" + tab);
  loadTabData(tab);
};

function loadTabData(tab) {
  if (_cache[tab]) return;
  _cache[tab] = true;

  switch (tab) {
    case "dashboard":   loadDashboard(); break;
    case "knowledge":   loadKnowledge(); break;
    case "team":        loadTeam(); break;
    case "insights":    loadInsights(); break;
    case "languages":   loadLanguages(); break;
    case "github":      loadGitHub(); break;
    case "integration": loadIntegration(); break;
  }
}

/* ── Dashboard Tab ─────────────────────────────────── */

function loadDashboard() {
  api("/api/dashboard/summary").then(function (data) {
    if (!data.success) return;

    // Stat cards
    setHtml("statKnowledgeTotal", data.knowledge.total);
    setHtml("statEmbedPct", data.knowledge.embed_pct + "%");
    setHtml("statCategories", data.knowledge.categories);
    setHtml("statAgentTotal", data.agents.total);
    setHtml("statAgentActive", data.agents.active);
    setHtml("statProjectsActive", data.projects.active);
    setHtml("statTasksInProgress", data.projects.tasks_in_progress);
    setHtml("statStationsActive", data.stations_active);

    // Activity feed
    var actEl = document.getElementById("dashboardActivity");
    if (data.activity && data.activity.length) {
      setHtml(actEl, data.activity.map(function (a) {
        return '<div class="cs-activity-item">' +
          '<i data-lucide="' + escHtml(a.icon) + '"></i>' +
          '<div class="cs-activity-text">' + escHtml(a.description || "\u2014") + '</div>' +
          '<span class="cs-activity-time">' + formatAge(a.created_at) + '</span>' +
          '</div>';
      }).join(""));
    } else {
      setHtml(actEl, '<div class="cs-empty">No recent activity</div>');
    }

    // Wellness bars
    var energy = Math.round((data.agents.avg_energy || 0) * 100);
    var stress = Math.round((data.agents.avg_stress || 0) * 100);
    var mood = Math.round((data.agents.avg_mood || 0) * 100);
    setHtml("wellnessEnergy", energy + "%");
    setHtml("wellnessStress", stress + "%");
    setHtml("wellnessMood", mood + "%");
    var energyBar = document.getElementById("wellnessEnergyBar");
    if (energyBar) energyBar.style.width = energy + "%";
    var stressBar = document.getElementById("wellnessStressBar");
    if (stressBar) stressBar.style.width = stress + "%";
    var moodBar = document.getElementById("wellnessMoodBar");
    if (moodBar) moodBar.style.width = mood + "%";

    // Integration health
    api("/api/integration/health").then(function (d) {
      if (!d.success) return;
      var sys = d.systems;
      var html = Object.keys(sys).map(function (key) {
        var s = sys[key];
        var dot = s.status === "online" ? "online" : "offline";
        var info = s.projects || s.stations || s.repos || "";
        return '<div class="cs-integration-item">' +
          '<span class="status-dot ' + dot + '"></span>' +
          '<span class="cs-integration-name">' + escHtml(key.toUpperCase()) + '</span>' +
          (info ? '<span class="cs-integration-count">' + info + '</span>' : '') +
          '</div>';
      }).join("");
      setHtml("dashboardIntegration", html);
    }).catch(function () {});

    refreshIcons();
  }).catch(function (err) {
    console.error("loadDashboard error:", err);
  });
}

/* ── Stub Tab Loaders (implemented in subsequent tasks) ── */

function loadKnowledge() { setHtml("panel-knowledge", '<div class="cs-loading">Knowledge tab \u2014 coming soon</div>'); }
function loadTeam() { setHtml("panel-team", '<div class="cs-loading">Team tab \u2014 coming soon</div>'); }
function loadInsights() { setHtml("panel-insights", '<div class="cs-loading">Insights tab \u2014 coming soon</div>'); }
function loadLanguages() { setHtml("panel-languages", '<div class="cs-loading">Languages tab \u2014 coming soon</div>'); }
function loadGitHub() { setHtml("panel-github", '<div class="cs-loading">GitHub tab \u2014 coming soon</div>'); }
function loadIntegration() { setHtml("panel-integration", '<div class="cs-loading">Integration tab \u2014 coming soon</div>'); }

/* ── Init ──────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", function () {
  refreshIcons();
  var hash = window.location.hash.replace("#", "");
  var validTabs = ["dashboard", "knowledge", "team", "insights", "languages", "github", "integration"];
  if (hash && validTabs.indexOf(hash) !== -1) {
    switchConsciousnessTab(hash);
  } else {
    switchConsciousnessTab("dashboard");
  }
});
