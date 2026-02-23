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

    // Header stats
    updateHeaderStats(data);

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

/* ── Agent Modal ───────────────────────────────────── */

window.closeAgentModal = function () {
  var overlay = document.getElementById("agentModalOverlay");
  if (overlay) overlay.classList.remove("open");
};

window.openAgentModal = function () {
  var overlay = document.getElementById("agentModalOverlay");
  if (overlay) overlay.classList.add("open");
};

/* ── Header Stats ─────────────────────────────────── */

function updateHeaderStats(data) {
  if (data.knowledge) setHtml("headerKnowledgeCount", data.knowledge.total || "--");
  if (data.agents) setHtml("headerAgentCount", data.agents.total || "--");
  if (data.translations) setHtml("headerTranslationCount", data.translations || "--");
}

/* ── Knowledge Tab ─────────────────────────────────── */

window.switchKnowledgeSubtab = function(sub) {
  document.querySelectorAll("#panel-knowledge .cs-subtab").forEach(function(b) {
    b.classList.toggle("active", b.textContent.toLowerCase().replace(/ /g, "") === sub ||
      (sub === "browser" && b.textContent === "Browser") ||
      (sub === "processing" && b.textContent === "Processing") ||
      (sub === "categories" && b.textContent === "Categories") ||
      (sub === "embeddings" && b.textContent === "Embeddings"));
  });
  document.querySelectorAll("#panel-knowledge .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "kb-" + sub);
  });
  if (sub === "processing") loadProcessingStatus();
  if (sub === "categories") loadCategories();
  if (sub === "embeddings") loadEmbeddingStatus();
};

function loadKnowledge() {
  loadKnowledgeBrowser();
}

function loadKnowledgeBrowser() {
  var search = document.getElementById("kbSearch");
  var typeFilter = document.getElementById("kbFilterType");
  var params = "?limit=50";
  if (typeFilter && typeFilter.value) params += "&type=" + encodeURIComponent(typeFilter.value);
  if (search && search.value) params += "&search=" + encodeURIComponent(search.value);

  api("/knowledge/list" + params).then(function(data) {
    var entries = data.entries || data.knowledge || [];
    var el = document.getElementById("kbBrowserTable");
    if (!entries.length) {
      setHtml(el, '<div class="cs-empty">No entries found</div>');
      return;
    }
    var html = '<table class="cs-table"><thead><tr>' +
      '<th>Title</th><th>Type</th><th>Category</th><th class="center">Embedded</th><th>Created</th>' +
      '</tr></thead><tbody>';
    entries.forEach(function(e) {
      html += '<tr>' +
        '<td>' + escHtml(e.title || e.file_name || "Untitled") + '</td>' +
        '<td><span class="cs-badge">' + escHtml(e.knowledge_type || e.type || "\u2014") + '</span></td>' +
        '<td>' + escHtml(e.category || "\u2014") + '</td>' +
        '<td class="center">' + (e.has_embedding ? '\u2713' : '\u2014') + '</td>' +
        '<td>' + formatAge(e.created_at) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    setHtml(el, html);
  }).catch(function(err) {
    console.error("loadKnowledgeBrowser error:", err);
    setHtml("kbBrowserTable", '<div class="cs-empty">Error loading knowledge</div>');
  });
}

function loadProcessingStatus() {
  api("/processing/status").then(function(data) {
    if (data.queue_size !== undefined) setHtml("procQueueCount", data.queue_size);
    if (data.processed !== undefined) setHtml("procCompleted", data.processed);
    var html = '<div class="cs-card"><div class="cs-card-header">Processing Status</div><div class="cs-card-body">';
    html += '<p style="color:rgba(255,255,255,0.7); font-size:0.85rem;">Status: ' + escHtml(data.status || "idle") + '</p>';
    if (data.last_run) html += '<p style="color:rgba(255,255,255,0.5); font-size:0.82rem;">Last run: ' + formatAge(data.last_run) + '</p>';
    html += '</div></div>';
    setHtml("procStatus", html);
  }).catch(function() {
    setHtml("procStatus", '<div class="cs-empty">Processing status unavailable</div>');
  });
}

function loadCategories() {
  api("/knowledge/categories").then(function(data) {
    var cats = data.categories || [];
    if (!cats.length) {
      setHtml("categoryGrid", '<div class="cs-empty">No categories found</div>');
      return;
    }
    var html = '<div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap:12px;">';
    cats.forEach(function(c) {
      html += '<div class="cs-card" style="padding:12px;">' +
        '<div style="font-weight:600; color:#fff; font-size:0.85rem;">' + escHtml(c.category || c.name || "Uncategorized") + '</div>' +
        '<div style="font-size:0.78rem; color:rgba(255,255,255,0.4);">' + (c.count || 0) + ' entries</div>' +
        '</div>';
    });
    html += '</div>';
    setHtml("categoryGrid", html);
  }).catch(function() {
    setHtml("categoryGrid", '<div class="cs-empty">Error loading categories</div>');
  });
}

function loadEmbeddingStatus() {
  api("/processing/embedding-coverage").then(function(data) {
    if (data.coverage_pct !== undefined) setHtml("embedCoverage", data.coverage_pct + "%");
    if (data.total !== undefined) setHtml("embedTotal", data.total);
    var html = '<div class="cs-card"><div class="cs-card-header">Embedding Details</div><div class="cs-card-body">';
    html += '<p style="color:rgba(255,255,255,0.7); font-size:0.85rem;">Embedded: ' + (data.embedded || 0) + ' / ' + (data.total || 0) + '</p>';
    html += '<p style="color:rgba(255,255,255,0.5); font-size:0.82rem;">Model: arctic-embed-cpu (768-dim)</p>';
    html += '</div></div>';
    setHtml("embedStatus", html);
  }).catch(function() {
    setHtml("embedStatus", '<div class="cs-empty">Embedding status unavailable</div>');
  });
}

/* ── Team Tab ──────────────────────────────────────── */

function loadTeam() {
  api("/api/team/roster").then(function(data) {
    if (!data.success) return;
    var el = document.getElementById("agentRoster");
    if (!data.agents || !data.agents.length) {
      setHtml(el, '<div class="cs-empty">No agents found</div>');
      return;
    }
    var html = data.agents.map(function(a) {
      var moodColor = (a.stress_level || 0) > 0.7 ? "red" : (a.energy_level || 0) > 0.5 ? "green" : "amber";
      var stationBadge = a.station_name
        ? '<span class="cs-badge blue">' + escHtml(a.station_name) + '</span>'
        : '<span class="cs-badge gray">Unassigned</span>';
      return '<div class="cs-agent-card" onclick="showAgentProfile(' + a.id + ')">' +
        '<div class="cs-agent-header">' +
          '<div class="cs-agent-avatar">' + escHtml((a.first_name || "?")[0]) + '</div>' +
          '<div>' +
            '<div class="cs-agent-name">' + escHtml(a.full_name || a.first_name) + '</div>' +
            '<div class="cs-agent-role">' + escHtml(a.title || a.agent_type || "Agent") + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="cs-agent-meta">' +
          stationBadge +
          '<span class="cs-badge ' + moodColor + '">' + escHtml(a.current_mood || 'neutral') + '</span>' +
        '</div>' +
        '<div class="cs-agent-stats">' +
          '<span>' + (a.skill_count || 0) + ' skills</span>' +
          (a.voice_engine ? '<span>' + escHtml(a.voice_engine) + '</span>' : '') +
        '</div>' +
        '<div class="cs-agent-bars">' +
          '<div class="cs-mini-bar"><div class="cs-mini-fill green" style="width:' + Math.round((a.energy_level || 0) * 100) + '%"></div></div>' +
          '<div class="cs-mini-bar"><div class="cs-mini-fill red" style="width:' + Math.round((a.stress_level || 0) * 100) + '%"></div></div>' +
        '</div>' +
        '</div>';
    }).join("");
    setHtml(el, html);
    refreshIcons();
  }).catch(function(err) {
    console.error("loadTeam error:", err);
    setHtml("agentRoster", '<div class="cs-empty">Error loading agents</div>');
  });
}

window.showAgentProfile = function(agentId) {
  api("/api/team/agents/" + agentId + "/profile").then(function(data) {
    if (!data.success) return;
    var a = data.agent;
    var html = '<div class="cs-profile-grid">';

    // Identity
    html += '<div class="cs-profile-section"><h3>Identity</h3>';
    html += '<p><strong>Name:</strong> ' + escHtml(a.full_name) + '</p>';
    html += '<p><strong>Role:</strong> ' + escHtml(a.title || a.agent_type) + '</p>';
    html += '<p><strong>Department:</strong> ' + escHtml(a.department || "\u2014") + '</p>';
    if (a.bio) html += '<p><strong>Bio:</strong> ' + escHtml(a.bio) + '</p>';
    if (data.identity && data.identity.length) {
      data.identity.forEach(function(t) {
        html += '<p><strong>' + escHtml(t.identity_key) + ':</strong> ' + escHtml(t.identity_value) + '</p>';
      });
    }
    html += '</div>';

    // Skills
    if (data.skills && data.skills.length) {
      html += '<div class="cs-profile-section"><h3>Skills (' + data.skills.length + ')</h3>';
      html += '<div class="cs-skill-grid">';
      data.skills.forEach(function(s) {
        var level = s.proficiency_level || 0;
        var dots = '';
        for (var i = 0; i < 5; i++) dots += i < level ? '\u25CF' : '\u25CB';
        html += '<div class="cs-skill-item">' +
          '<span>' + escHtml(s.skill_name) + '</span>' +
          '<span class="cs-skill-level">' + dots + '</span>' +
          '</div>';
      });
      html += '</div></div>';
    }

    // Station
    if (data.station) {
      html += '<div class="cs-profile-section"><h3>Station Assignment</h3>';
      html += '<p>' + escHtml(data.station.station_name) + ' (' + escHtml(data.station.station_code) + ')</p>';
      html += '<a href="/bridge#stations" class="cs-link">View in Bridge Command \u2192</a>';
      html += '</div>';
    }

    // Voice
    if (data.voice) {
      html += '<div class="cs-profile-section"><h3>Voice DNA</h3>';
      html += '<p><strong>Engine:</strong> ' + escHtml(data.voice.engine || "\u2014") + '</p>';
      html += '<p><strong>Language:</strong> ' + escHtml(data.voice.language || "en") + '</p>';
      if (data.voice.profile_name) html += '<p><strong>Profile:</strong> ' + escHtml(data.voice.profile_name) + '</p>';
      html += '</div>';
    }

    // Emotional history
    if (data.emotions && data.emotions.length) {
      html += '<div class="cs-profile-section"><h3>Recent Emotional States</h3>';
      html += '<div style="max-height:200px; overflow-y:auto;">';
      data.emotions.slice(0, 10).forEach(function(e) {
        html += '<div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:0.82rem;">' +
          '<span style="color:rgba(255,255,255,0.7);">' + escHtml(e.current_mood) + '</span>' +
          '<span style="color:rgba(255,255,255,0.4);">' + formatAge(e.timestamp) + '</span>' +
          '</div>';
      });
      html += '</div></div>';
    }

    html += '</div>';
    setHtml("agentModalBody", html);
    document.getElementById("agentModalTitle").textContent = (a.full_name || "Agent") + " \u2014 Personnel File";
    openAgentModal();
  }).catch(function(err) {
    console.error("showAgentProfile error:", err);
  });
};
function loadInsights() { setHtml("panel-insights", '<div class="cs-loading">Insights tab \u2014 coming soon</div>'); }
function loadLanguages() { setHtml("panel-languages", '<div class="cs-loading">Languages tab \u2014 coming soon</div>'); }
function loadGitHub() { setHtml("panel-github", '<div class="cs-loading">GitHub tab \u2014 coming soon</div>'); }
function loadIntegration() { setHtml("panel-integration", '<div class="cs-loading">Integration tab \u2014 coming soon</div>'); }

/* ── Init ──────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", function () {
  refreshIcons();

  // Close modal on overlay click
  var overlay = document.getElementById("agentModalOverlay");
  if (overlay) {
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeAgentModal();
    });
  }

  var hash = window.location.hash.replace("#", "");
  var validTabs = ["dashboard", "knowledge", "team", "insights", "languages", "github", "integration"];
  if (hash && validTabs.indexOf(hash) !== -1) {
    switchConsciousnessTab(hash);
  } else {
    switchConsciousnessTab("dashboard");
  }
});
