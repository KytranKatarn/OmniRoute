/* consciousness.js — A.R.C.H.I.E. Consciousness Module */
/* globals: lucide */
"use strict";

var _cache = {};
var _debounceTimers = {};
var _holoSphere = null;
var _neuralCore = null;
var _prevJobState = {};
var _prevKnowledgeCounts = {};
var _knowledgePollTimer = null;
var _pixelCrew = null;
var _glassNav = null;

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

function _jobTypeToNode(jobType) {
  if (!jobType) return null;
  if (jobType.indexOf("analysis") > -1 || jobType.indexOf("embed") > -1) return "conversations";
  if (jobType.indexOf("github") > -1 || jobType.indexOf("reindex") > -1) return "code";
  if (jobType.indexOf("translate") > -1) return "sessions";
  return "vault";
}

/**
 * Build an LCARS-styled job notification bar.
 * @param {string} type - "ok"|"warn"|"err"|"info"
 * @param {string} icon - single character for the endcap (▶ ✓ ✗ ● etc.)
 * @param {string} msg  - message HTML (safe — caller must escHtml user data)
 * @returns {string} HTML string
 */
function lcarsMsg(type, icon, msg) {
  return '<div class="cs-job-msg ' + type + '">' +
    '<span class="cs-job-msg-cap">' + icon + '</span>' +
    '<span class="cs-job-msg-text">' + msg + '</span></div>';
}

function formatAge(dateStr) {
  return ArchieTime.age(dateStr);
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

/* ── Visual Event Helper ──────────────────────────── */

function _fireVisualEvent(type, data) {
  if (_neuralCore) {
    // NeuralCore.fireEvent relays to window._neuralEvents internally
    _neuralCore.fireEvent(type, data);
  } else {
    if (_holoSphere && _holoSphere.fireEvent) _holoSphere.fireEvent(type, data);
    if (window._neuralEvents) window._neuralEvents.emit(type, data);
  }
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
    var ct = resp.headers.get("content-type") || "";
    if (ct.indexOf("application/json") === -1) {
      return Promise.reject(new Error("Session expired — please refresh the page"));
    }
    return resp.json().then(function(data) {
      /* Attach HTTP status so callers can detect 409 duplicate */
      data._status = resp.status;
      return data;
    });
  });
}

/* ── Tab Switching ─────────────────────────────────── */

window.switchConsciousnessTab = function (tab) {
  // Update glass nav indicator
  if (_glassNav) _glassNav.setActive(tab);

  // Toggle panels
  document.querySelectorAll(".cs-panel").forEach(function (panel) {
    panel.classList.toggle("active", panel.id === "panel-" + tab);
  });
  history.replaceState(null, "", "#" + tab);
  loadTabData(tab);
  if (tab === "knowledge" || tab === "github") {
    checkActiveJobs();
  }
};

var _headerLoaded = false;
function loadTabData(tab) {
  // Always populate header stats on first tab load
  if (!_headerLoaded) {
    _headerLoaded = true;
    api("/api/dashboard/summary").then(function(d) {
      if (d.success) updateHeaderStats(d);
    }).catch(function() {});
  }

  if (_cache[tab]) return;

  // Destroy Neural Core when leaving dashboard to free GPU
  if (tab !== "dashboard" && _neuralCore) {
    _neuralCore.destroy();
    _neuralCore = null;
    if (_pixelCrew) { _pixelCrew.destroy(); _pixelCrew = null; }
    if (_knowledgePollTimer) { clearInterval(_knowledgePollTimer); _knowledgePollTimer = null; }
  }

  _cache[tab] = true;

  switch (tab) {
    case "dashboard":   loadDashboard(); break;
    case "knowledge":   loadKnowledge(); break;
    /* team tab merged into Bridge Command */
    case "github":      loadGitHub(); break;
    case "languages":   loadLanguages(); checkActiveJobs(); break;
    case "codehealth":  loadCodeHealth(); break;
  }
}

/* ── Dashboard Tab ─────────────────────────────────── */

function loadDashboard() {
  // Neural Core visualization
  loadNeuralCore();

  api("/api/dashboard/summary").then(function (data) {
    if (!data.success) return;

    // Header stats
    updateHeaderStats(data);

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

    // Emotional state mood indicator
    api("/emotional-state").then(function (d) {
      var mood = (d.mood || "neutral").toLowerCase();
      var moodColors = {
        focused: "#8b5cf6", curious: "#06b6d4", happy: "#22c55e",
        processing: "#f59e0b", empathetic: "#ec4899", neutral: "#8b5cf6",
        confident: "#3b82f6", relaxed: "#22c55e"
      };
      var color = moodColors[mood] || "#8b5cf6";
      var dot = document.getElementById("moodDot");
      if (dot) { dot.style.background = color; dot.style.color = color; }
      var val = document.getElementById("moodValue");
      if (val) { val.textContent = mood; val.style.color = color; }
      var mEnergy = Math.round((d.energy || 0) * 100);
      var mStress = Math.round((d.stress || 0) * 100);
      var mConf = Math.round((d.confidence || 0) * 100);
      setHtml("moodEnergy", mEnergy + "%");
      setHtml("moodStress", mStress + "%");
      setHtml("moodConfidence", mConf + "%");
    }).catch(function () {});

    // Last updated timestamp
    var ts = document.getElementById("dashboardTimestamp");
    if (ts) {
      var now = new Date();
      var h = String(now.getHours()).padStart(2, "0");
      var m = String(now.getMinutes()).padStart(2, "0");
      var s = String(now.getSeconds()).padStart(2, "0");
      ts.textContent = "Last updated " + h + ":" + m + ":" + s;
    }

    refreshIcons();

    // Load merged tab data (Insights analytics + Integration health)
    loadInsights();
    loadIntegration();
  }).catch(function (err) {
    console.error("loadDashboard error:", err);
  });
}

/* ── Neural Core — HoloSphere Integration ──────── */

function loadNeuralCore() {
  var container = document.getElementById("neuralCore");
  if (!container) return;

  // Destroy previous instance
  if (_neuralCore) { _neuralCore.destroy(); _neuralCore = null; }
  if (_holoSphere) { _holoSphere.destroy(); _holoSphere = null; }

  // Fetch data then build scene
  api("/api/dashboard/summary").then(function(data) {
    if (!data.success) return;
    var kb = data.knowledge || {};
    var agents = data.agents || {};

    var nodes = [
      { id: "conversations", label: "Conv", count: kb.conversations || 0, color: "#3b82f6", tab: "knowledge" },
      { id: "code", label: "Code", count: (kb.github_files || 0) + (kb.code_snippets || 0), color: "#22c55e", tab: "github" },
      { id: "vault", label: "Vault", count: kb.vault_notes || 0, color: "#8b5cf6", tab: "knowledge" },
      { id: "repos", label: "Repos", count: kb.repos || 0, color: "#f59e0b", tab: "github" },
      { id: "learned", label: "Learn", count: (kb.mistakes || 0) + (kb.improvements || 0), color: "#06b6d4", tab: "knowledge" },
      { id: "sessions", label: "Sessions", count: kb.sessions || 0, color: "#ec4899", tab: "knowledge" },
      { id: "translations", label: "Languages", count: kb.translations || 0, color: "#14b8a6", tab: "languages" },
      { id: "decisions", label: "Decisions", count: kb.decisions || 0, color: "#f97316", tab: "knowledge" }
    ];

    // Store counts for change detection
    _prevKnowledgeCounts = {};
    nodes.forEach(function(n) { _prevKnowledgeCounts[n.id] = n.count; });
    _prevKnowledgeCounts.total = kb.total_entries || kb.total || 0;

    // Try WebGL Neural Core, fall back to HoloSphere
    if (typeof NeuralCore !== "undefined") {
      NeuralCore.create(container, {
        nodes: nodes,
        mood: "focused",
        particleCount: 200,
        onNodeClick: function(node) {
          if (node.tab) switchConsciousnessTab(node.tab);
        }
      }).then(function(core) {
        _neuralCore = core;
        _loadAgentsIntoCore();
        _startKnowledgePolling();
        _startJobPolling();
        checkActiveJobs();
      }).catch(function(err) {
        console.warn("NeuralCore failed, falling back to HoloSphere:", err.message || err);
        _fallbackToHoloSphere(container, nodes);
      });
    } else {
      _fallbackToHoloSphere(container, nodes);
    }

    // Stats HUD (works for both WebGL and fallback) — clickable for timeline chart
    var kbEl = document.getElementById("ncTotalKnowledge");
    if (kbEl) {
      kbEl.textContent = (kb.total_entries || kb.total || 0).toLocaleString();
      kbEl.style.cursor = "pointer";
      kbEl.title = "Total intelligence: KB + translations + decisions — click for timeline";
      kbEl.onclick = function() { showKnowledgeTimeline(); };
    }
    setHtml("ncActiveAgents", (agents.active || 0) + "/" + (agents.total || 0));
  }).catch(function(err) {
    console.error("Neural core data error:", err);
    var loading = document.getElementById("ncLoading");
    if (loading) loading.classList.add("hidden");
  });

  // GitHub stats for embed coverage
  api("/github/stats").then(function(data) {
    if (data.success) {
      setHtml("ncGitHubFiles", (data.total_files || 0).toLocaleString());
      setHtml("ncEmbedPct", (data.embed_pct || 0) + "%");
    }
  }).catch(function() {});

  // Emotional state for mood
  api("/emotional-state").then(function(data) {
    var mood = (data.mood || "focused").toLowerCase();
    if (_neuralCore) _neuralCore.setMood(mood);
    else if (_holoSphere) _holoSphere.setMood(mood);
  }).catch(function() {});

  // Pixel Crew — disabled for now (Phase 2)
  // var deckEl = document.getElementById("pixelCrewDeck");
  // if (deckEl && typeof PixelCrew !== "undefined") { _pixelCrew = PixelCrew.create(deckEl); }
}

function _fallbackToHoloSphere(container, nodes) {
  var loading = document.getElementById("ncLoading");
  if (loading) loading.classList.add("hidden");
  if (typeof HoloSphere === "function") {
    _holoSphere = new HoloSphere(container, {
      nodes: nodes,
      mood: "focused",
      particleCount: 120,
      ambientDust: true,
      ambientTarget: document.querySelector(".cs-body"),
      onNodeClick: function(node) {
        if (node.tab) switchConsciousnessTab(node.tab);
      }
    });
  }
  // Load agents and start polling even when NeuralCore failed
  _loadAgentsIntoCore();
  _startKnowledgePolling();
  _startJobPolling();
  checkActiveJobs();
}

function _loadAgentsIntoCore() {
  if (!_neuralCore && !_pixelCrew) return;
  fetch("/tools/bridge/api/bridge/crew/manifest").then(function(r) { return r.json(); }).then(function(data) {
    if (!data.success) return;
    var crew = data.crew || [];
    crew.forEach(function(agent) {
      if (agent.status === "active" || agent.status === "idle" || agent.status === "paused") {
        var agentData = {
          name: agent.name,
          display_name: agent.full_name || agent.name,
          station: agent.station || "COMMAND",
          status: agent.status
        };
        if (_neuralCore) _neuralCore.addAgent(agentData);
        if (_pixelCrew) _pixelCrew.addAgent(agentData);
      }
    });
  }).catch(function() {});
}

function _startKnowledgePolling() {
  if (_knowledgePollTimer) clearInterval(_knowledgePollTimer);
  _knowledgePollTimer = setInterval(function() {
    if (!_neuralCore && !_pixelCrew) return;
    api("/api/dashboard/summary").then(function(data) {
      if (!data.success) return;
      var kb = data.knowledge || {};
      var newCounts = {
        conversations: kb.conversations || 0,
        code: (kb.github_files || 0) + (kb.code_snippets || 0),
        vault: kb.vault_notes || 0,
        repos: kb.repos || 0,
        learned: (kb.mistakes || 0) + (kb.improvements || 0),
        sessions: kb.sessions || 0,
        translations: kb.translations || 0,
        decisions: kb.decisions || 0,
        total: kb.total_entries || kb.total || 0
      };

      var nodeIds = ["conversations", "code", "vault", "repos", "learned", "sessions", "translations", "decisions"];
      nodeIds.forEach(function(id) {
        if (newCounts[id] > (_prevKnowledgeCounts[id] || 0)) {
          if (_neuralCore) _neuralCore.updateNode(id, { count: newCounts[id] });
          else if (_holoSphere) _holoSphere.updateNode(id, { count: newCounts[id] });
          _fireVisualEvent("knowledge:added", { node: id, delta: newCounts[id] - (_prevKnowledgeCounts[id] || 0) });
        }
      });

      setHtml("ncTotalKnowledge", (newCounts.total || 0).toLocaleString());
      _prevKnowledgeCounts = newCounts;
    }).catch(function() {});
  }, 20000);
}

/* ── Agent Modal ───────────────────────────────────── */

/* Agent modal removed — profiles now in Bridge Command */

/* ── Header Stats ─────────────────────────────────── */

function updateHeaderStats(data) {
  if (data.knowledge) setHtml("headerKnowledgeCount", (data.knowledge.total_entries || data.knowledge.total || "--").toLocaleString ? (data.knowledge.total_entries || data.knowledge.total || 0).toLocaleString() : "--");
  if (data.agents) setHtml("headerAgentCount", data.agents.total || "--");
  if (data.translations) setHtml("headerTranslationCount", data.translations || "--");
}

/* ── Knowledge Tab ─────────────────────────────────── */

window.switchKnowledgeSubtab = function(sub) {
  document.querySelectorAll("#panel-knowledge .cs-subtab").forEach(function(b) {
    var txt = b.textContent.trim().toLowerCase().replace(/ /g, "");
    b.classList.toggle("active", txt === sub ||
      (sub === "browser" && txt === "browser") ||
      (sub === "categories" && txt === "categories") ||
      (sub === "embeddings" && txt === "embeddings"));
  });
  document.querySelectorAll("#panel-knowledge .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "kb-" + sub);
  });
  if (sub === "categories") loadCategories();
  if (sub === "embeddings") loadEmbeddingStatus();
};

var _kbPage = 1;
var _kbPageSize = 25;
var _kbEntries = [];

/* ── Knowledge LCARS Operations Terminal ─────────── */

function renderKnowledgeOps(agentData, jobData) {
  /* Agents, jobs, and commands all rendered by shared StationOps component */
  _renderOpsAgents("kbOpsAgents", "ANALYTICS", jobData);
}

function loadKnowledge() {
  renderKnowledgeOps();
  loadKnowledgeBrowser();
  _loadTypeSummary();
}

function _loadTypeSummary() {
  api("/knowledge/categories").then(function(data) {
    var cats = data.categories || [];
    var typeMap = {};
    cats.forEach(function(c) {
      var name = (c.category || c.name || "").toLowerCase();
      if (name === "github") typeMap.github = (typeMap.github || 0) + (c.count || 0);
      else if (name === "conversation") typeMap.convo = (typeMap.convo || 0) + (c.count || 0);
      else if (name.indexOf("api") === 0) typeMap.api = (typeMap.api || 0) + (c.count || 0);
      else if (name === "code_scan") typeMap.code = (typeMap.code || 0) + (c.count || 0);
    });
    var el = document.getElementById("kbTypeSummary");
    if (!el) return;
    var html = '<span class="cs-type-chip github"><span class="chip-count">' + (typeMap.github || 0).toLocaleString() + '</span> GitHub</span>' +
      '<span class="cs-type-chip convo"><span class="chip-count">' + (typeMap.convo || 0).toLocaleString() + '</span> Conversations</span>' +
      '<span class="cs-type-chip api"><span class="chip-count">' + (typeMap.api || 0).toLocaleString() + '</span> API</span>' +
      '<span class="cs-type-chip code"><span class="chip-count">' + (typeMap.code || 0).toLocaleString() + '</span> Code</span>';
    setHtml(el, html);
  }).catch(function() {});
}

function loadKnowledgeBrowser() {
  var search = document.getElementById("kbSearch");
  var typeFilter = document.getElementById("kbFilterType");
  var params = "?limit=200";
  if (typeFilter && typeFilter.value) params += "&type=" + encodeURIComponent(typeFilter.value);
  if (search && search.value) params += "&search=" + encodeURIComponent(search.value);

  api("/knowledge/list" + params).then(function(data) {
    _kbEntries = data.entries || data.knowledge || [];
    _kbPage = 1;
    _renderKbPage();
  }).catch(function(err) {
    console.error("loadKnowledgeBrowser error:", err);
    setHtml("kbBrowserTable", '<div class="cs-empty">Error loading knowledge</div>');
  });
}

function _renderKbPage() {
  var el = document.getElementById("kbBrowserTable");
  if (!_kbEntries.length) {
    setHtml(el, '<div class="cs-empty">No entries found</div>');
    setHtml("kbPagination", "");
    return;
  }
  var total = _kbEntries.length;
  var pages = Math.ceil(total / _kbPageSize);
  var start = (_kbPage - 1) * _kbPageSize;
  var slice = _kbEntries.slice(start, start + _kbPageSize);

  var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr>' +
    '<th>Title</th><th>Type</th><th>Category</th><th class="center">Embedded</th><th>Created</th>' +
    '</tr></thead><tbody>';
  slice.forEach(function(e) {
    var typeClass = "";
    var kt = (e.knowledge_type || e.type || "").toLowerCase();
    if (kt.indexOf("github") >= 0) typeClass = "green";
    else if (kt.indexOf("conversation") >= 0) typeClass = "blue";
    else if (kt.indexOf("vault") >= 0) typeClass = "purple";
    else if (kt.indexOf("code") >= 0 || kt.indexOf("api") >= 0) typeClass = "amber";
    html += '<tr>' +
      '<td style="max-width:320px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml(e.title || e.file_name || "Untitled") + '</td>' +
      '<td><span class="cs-badge ' + typeClass + '">' + escHtml(e.knowledge_type || e.type || "\u2014") + '</span></td>' +
      '<td style="font-size:0.75rem; color:rgba(255,255,255,0.4);">' + escHtml(e.category || "\u2014") + '</td>' +
      '<td class="center">' + (e.has_embedding ? '<span style="color:#22c55e;">\u2713</span>' : '<span style="color:rgba(255,255,255,0.15);">\u2014</span>') + '</td>' +
      '<td style="font-size:0.75rem; white-space:nowrap;">' + formatAge(e.created_at) + '</td>' +
      '</tr>';
  });
  html += '</tbody></table></div>';
  setHtml(el, html);

  /* Pagination */
  var pHtml = '';
  if (pages > 1) {
    pHtml += '<button class="cs-page-btn" onclick="_kbPage=1;_renderKbPage()" ' + (_kbPage <= 1 ? 'disabled' : '') + '>&laquo;</button>';
    pHtml += '<button class="cs-page-btn" onclick="_kbPage--;_renderKbPage()" ' + (_kbPage <= 1 ? 'disabled' : '') + '>&lsaquo;</button>';
    pHtml += '<span class="cs-page-info">' + start + '\u2013' + Math.min(start + _kbPageSize, total) + ' of ' + total + '</span>';
    pHtml += '<button class="cs-page-btn" onclick="_kbPage++;_renderKbPage()" ' + (_kbPage >= pages ? 'disabled' : '') + '>&rsaquo;</button>';
    pHtml += '<button class="cs-page-btn" onclick="_kbPage=' + pages + ';_renderKbPage()" ' + (_kbPage >= pages ? 'disabled' : '') + '>&raquo;</button>';
  }
  setHtml("kbPagination", pHtml);
}

function loadCategories() {
  api("/knowledge/categories").then(function(data) {
    var cats = data.categories || [];
    if (!cats.length) {
      setHtml("categoryGrid", '<div class="cs-empty">No categories found</div>');
      return;
    }
    /* Sort by count descending */
    cats.sort(function(a, b) { return (b.count || 0) - (a.count || 0); });
    var maxCount = cats[0].count || 1;
    var html = '<div class="cs-cat-grid">';
    cats.forEach(function(c) {
      var cnt = c.count || 0;
      var tier = cnt >= 1000 ? "tier-1" : cnt >= 100 ? "tier-2" : cnt >= 10 ? "tier-3" : "tier-4";
      var barW = Math.max(5, Math.round(cnt / maxCount * 100));
      html += '<div class="cs-cat-card ' + tier + '" onclick="document.getElementById(\'kbFilterType\').value=\'\'; document.getElementById(\'kbSearch\').value=' + "'" + escHtml(c.category || c.name || "") + "'" + '; _cache.knowledge=false; switchKnowledgeSubtab(\'browser\'); loadKnowledgeBrowser();">' +
        '<div class="cat-name">' + escHtml(c.category || c.name || "Uncategorized") + '</div>' +
        '<div class="cat-count">' + cnt.toLocaleString() + ' entries</div>' +
        '<div class="cat-bar" style="width:' + barW + '%;"></div>' +
        '</div>';
    });
    html += '</div>';
    setHtml("categoryGrid", html);
  }).catch(function() {
    setHtml("categoryGrid", '<div class="cs-empty">Error loading categories</div>');
  });
}

function loadEmbeddingStatus() {
  api("/api/processing/embedding-coverage").then(function(data) {
    /* Backend returns { totals: { total, embedded, analyzed }, types: [...] } */
    var totals = data.totals || {};
    var total = totals.total || data.total || 0;
    var embedded = totals.embedded || data.embedded || 0;
    var pct = total > 0 ? Math.round(embedded / total * 100) : 0;
    setHtml("embedCoverage", pct + "%");
    setHtml("embedTotal", total.toLocaleString());
    var html = '<div class="cs-card"><div class="cs-card-header">Embedding Details</div><div class="cs-card-body">';
    html += '<div style="display:flex; justify-content:space-between; margin-bottom:6px;">';
    html += '<span style="color:rgba(255,255,255,0.6); font-size:0.82rem;">' + embedded.toLocaleString() + ' / ' + total.toLocaleString() + ' embedded</span>';
    html += '<span style="color:#22c55e; font-family:Orbitron,sans-serif; font-size:0.78rem; font-weight:700;">' + pct + '%</span>';
    html += '</div>';
    html += '<div class="cs-embed-bar-wrap"><div class="cs-embed-bar" style="width:' + pct + '%;"></div></div>';
    html += '<p style="color:rgba(255,255,255,0.4); font-size:0.75rem; margin-top:8px;">Model: arctic-embed-cpu (768-dim)</p>';
    /* Breakdown by source type */
    var types = data.types || [];
    if (types.length) {
      html += '<div style="margin-top:12px; border-top:1px solid rgba(255,255,255,0.06); padding-top:10px;">';
      html += '<div style="font-family:Antonio,sans-serif; font-size:0.7rem; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:1px; margin-bottom:8px;">By Source</div>';
      types.forEach(function(t) {
        if (t.source_type === "archie_v1") return;
        var tPct = t.total > 0 ? Math.round(t.embedded / t.total * 100) : 0;
        html += '<div style="display:flex; justify-content:space-between; font-size:0.78rem; color:rgba(255,255,255,0.5); margin-bottom:4px;">' +
          '<span>' + escHtml(t.source_type) + '</span>' +
          '<span style="color:rgba(255,255,255,0.3);">' + t.embedded + '/' + t.total + ' (' + tPct + '%)</span></div>';
      });
      html += '</div>';
    }
    html += '</div></div>';
    setHtml("embedStatus", html);
  }).catch(function() {
    setHtml("embedStatus", '<div class="cs-empty">Embedding status unavailable</div>');
  });
}

/* ── Processing Controls ──────────────────────────── */

/* ── Bridge Job Progress Poller ─────────────────────── */

/* _renderJobProgress removed — replaced by _renderBridgeJob (uses Bridge as source of truth) */

function _pollJobStatus(jobId, el, onComplete) {
  /* Delegate to shared StationOps component */
  var ops = _kbOps || _getOpsInstance("kbOpsAgents");
  ops.pollJob(jobId, el, onComplete);
}

/* ── Active Job Status + Station Agent Display ─────── */

var _activeJobPolls = {};
var _jobPollInterval = null;     /* periodic refresh for progress bars */

function _startJobPolling() {
  if (_jobPollInterval) return;  /* already running */
  _jobPollInterval = setInterval(function() {
    checkActiveJobs();
  }, 5000);
}

function _stopJobPolling() {
  if (_jobPollInterval) {
    clearInterval(_jobPollInterval);
    _jobPollInterval = null;
  }
}

function checkActiveJobs() {
  /* Pull from Bridge Command — single source of truth for agent/station work */
  fetch("/tools/bridge/api/bridge/jobs?status=running").then(function(resp) {
    var ct = resp.headers.get("content-type") || "";
    if (ct.indexOf("application/json") === -1) return Promise.reject("not json");
    return resp.json();
  }).then(function(data) {
    if (!data.success) { _enableProcessingBtns(); _enableGitHubBtns(); return; }

    /* Filter to consciousness module jobs (includes sub-modules like consciousness_linguistics) */
    var myJobs = (data.jobs || []).filter(function(j) {
      return j.module_source && j.module_source.indexOf("consciousness") === 0;
    });

    /* ── Event detection (Neural Core + Pixel Crew via EventBus) ── */
    var currentJobIds = {};
    (data.jobs || []).forEach(function(j) { currentJobIds[j.id] = j; });

    // Detect newly started jobs
    Object.keys(currentJobIds).forEach(function(id) {
      if (!_prevJobState[id]) {
        var j = currentJobIds[id];
        var evt = {
          agent: j.agent_name,
          station: j.station_code,
          jobType: j.job_type,
          nodeId: _jobTypeToNode(j.job_type)
        };
        _fireVisualEvent("job:started", evt);
      }
    });

    // Detect completed/removed jobs
    Object.keys(_prevJobState).forEach(function(id) {
      if (!currentJobIds[id]) {
        var j = _prevJobState[id];
        var evt = {
          agent: j.agent_name,
          station: j.station_code,
          jobType: j.job_type
        };
        _fireVisualEvent("job:completed", evt);
      }
    });

    _prevJobState = currentJobIds;

    /* Build station status from ALL running jobs */
    _renderStationStatus(data.jobs || [], myJobs);

    if (!myJobs.length) {
      _stopJobPolling();
      _enableProcessingBtns();
      _enableGitHubBtns();
      /* Clear any stale job displays */
      var procEl = document.getElementById("procResult");
      if (procEl && procEl.innerHTML.indexOf("cs-pipeline-step") > -1 && procEl.innerHTML.indexOf("\u25B6") > -1) {
        setHtml("procResult", "");
      }
      var ghEl = document.getElementById("ghIntakeResult");
      if (ghEl && ghEl.innerHTML.indexOf("cs-pipeline-step") > -1 && ghEl.innerHTML.indexOf("\u25B6") > -1) {
        setHtml("ghIntakeResult", "");
      }
      /* Still render ops terminal crews (no active jobs = no cross-station assists) */
      renderKnowledgeOps(null, null);
      renderGitHubOps(null, null);
      renderLangOps(null, null);
      return;
    }

    /* Start periodic polling so progress bars update smoothly */
    _startJobPolling();

    /* ── Knowledge tab — jobs already rendered by _renderStationStatus above ── */
    _disableProcessingBtns();
    myJobs.forEach(function(job) {
      var pollKey = "kb_" + job.id;
      if (!_activeJobPolls[pollKey]) {
        _activeJobPolls[pollKey] = true;
        _pollJobStatus(job.id, "bjob-kb-" + job.id, function(completedJob) {
          _activeJobPolls[pollKey] = false;
          loadEmbeddingStatus();
          /* Continuous loop: only restart on successful completion, not failed/reaped */
          var status = completedJob ? completedJob.status : "unknown";
          var jt = (completedJob && completedJob.job_type) || (job.job_type) || "";
          if (status === "completed" && jt.indexOf("analysis") > -1 && _continuousRun.analysis) {
            _loopNext("analysis", completedJob);
          } else if (status === "completed" && jt.indexOf("embed") > -1 && _continuousRun.embedding) {
            _loopNext("embedding", completedJob);
          } else {
            _enableProcessingBtns();
            if (status === "failed") { _loopRetry("analysis"); _loopRetry("embedding"); }
          }
          setTimeout(checkActiveJobs, 500);
        });
      }
    });

    /* ── GitHub tab — show active jobs in ops terminal ── */
    _disableGitHubBtnsByJobType(myJobs);
    myJobs.forEach(function(job) {
      var pollKey = "gh_" + job.id;
      if (!_activeJobPolls[pollKey]) {
        _activeJobPolls[pollKey] = true;
        _pollJobStatus(job.id, "bjob-gh-" + job.id, function(completedJob) {
          _activeJobPolls[pollKey] = false;
          loadGitHub();
          loadGitHubEmbedStats();
          /* Continuous loop: only restart on successful completion, not failed/reaped */
          var status = completedJob ? completedJob.status : "unknown";
          var jt = (completedJob && completedJob.job_type) || (job.job_type) || "";
          if (status === "completed" && jt.indexOf("embed") > -1 && _continuousRun.embedding) {
            _loopNext("embedding", completedJob);
          } else {
            _enableGitHubBtns();
            if (status === "failed") { _loopRetry("embedding"); }
          }
          setTimeout(checkActiveJobs, 500);
        });
      }
    });

    /* ── Languages tab — job progress rendered by StationOps, but track
     *    completion here for continuous-loop auto-restart logic ── */
    var langJobs = myJobs.filter(function(j) {
      return (j.job_type || "").indexOf("translate") > -1;
    });

    langJobs.forEach(function(job) {
      var pollKey = "lang_" + job.id;
      if (!_activeJobPolls[pollKey]) {
        _activeJobPolls[pollKey] = true;
        _pollJobStatus(job.id, null, function(completedJob) {
          _activeJobPolls[pollKey] = false;
          _cache.languages = false;
          setTimeout(function() {
            loadLanguages();
            /* Only loop-next on successful completion, not failed/reaped */
            var status = completedJob ? completedJob.status : "unknown";
            var jt = (completedJob && completedJob.job_type) || (job.job_type) || "";
            if (status === "completed" && jt.indexOf("translate") > -1) {
              if (_continuousRun.translate) { _loopNext("translate", completedJob); }
              else if (_continuousRun.fullPass) { _loopNext("fullPass", completedJob); }
            } else if (status === "failed") {
              _loopRetry("translate"); _loopRetry("fullPass");
            }
            checkActiveJobs();
          }, 1500);
        });
      }
    });
  }).catch(function() {
    /* Bridge unavailable — stop polling and unblock buttons */
    _stopJobPolling();
    _enableProcessingBtns();
    _enableGitHubBtns();
  });
}

function _renderStationStatus(allJobs, myJobs) {
  var jobData = myJobs.length ? myJobs : null;

  /* Pass ALL consciousness jobs to every tab so agents show as busy
     regardless of which tab the job belongs to.
     Each tab filters its own job display section. */
  renderKnowledgeOps(null, jobData);
  renderGitHubOps(null, jobData);
  renderLangOps(null, jobData);

  /* Re-sync loop button states — rendering may have created buttons just now */
  Object.keys(_continuousRun).forEach(function(opKey) {
    _updateLoopBtn(opKey);
  });
}

function _buildJobHtml(job) {
  /* Delegate to shared StationOps component */
  var ops = _kbOps || _getOpsInstance("kbOpsAgents");
  return ops.buildJobHtml(job);
}

function _renderBridgeJob(job, el) {
  /* Delegate to shared StationOps component */
  var ops = _kbOps || _getOpsInstance("kbOpsAgents");
  ops.renderJob(job, el);
}

function _renderBridgeJobs(jobs, el, prefix) {
  /* Delegate to shared StationOps component */
  var ops = _kbOps || _getOpsInstance("kbOpsAgents");
  ops.renderBridgeJobs(jobs, el, prefix);
}

/* Disable/enable action buttons by ID (handles duplicates across tabs via "2" suffix) */
function _setBtnDisabled(baseId, disabled) {
  [baseId, baseId + "2"].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
}

function _disableProcessingBtns() {
  _setBtnDisabled("btnStartAnalysis", true);
  _setBtnDisabled("btnGenerateEmbed", true);
}

function _enableProcessingBtns() {
  /* Only re-enable buttons whose loop is NOT running */
  if (!_continuousRun.analysis) _setBtnDisabled("btnStartAnalysis", false);
  if (!_continuousRun.embedding) _setBtnDisabled("btnGenerateEmbed", false);
}

function _disableGitHubBtns() {
  _setBtnDisabled("btnReindexAll", true);
  _setBtnDisabled("btnStartAnalysis", true);
  _setBtnDisabled("btnGenerateEmbed", true);
}

function _enableGitHubBtns() {
  _setBtnDisabled("btnReindexAll", false);
  if (!_continuousRun.analysis) _setBtnDisabled("btnStartAnalysis", false);
  if (!_continuousRun.embedding) _setBtnDisabled("btnGenerateEmbed", false);
}

function _disableGitHubBtnsByJobType(jobs) {
  var hasReindex = false, hasAnalysis = false, hasEmbed = false;
  jobs.forEach(function(j) {
    var jt = j.job_type || "";
    if (jt.indexOf("reindex") !== -1 || jt.indexOf("github_index") !== -1) hasReindex = true;
    if (jt.indexOf("analysis") !== -1) hasAnalysis = true;
    if (jt.indexOf("embed") !== -1) hasEmbed = true;
  });
  if (hasReindex) _setBtnDisabled("btnReindexAll", true);
  if (hasAnalysis || _continuousRun.analysis) _setBtnDisabled("btnStartAnalysis", true);
  if (hasEmbed || _continuousRun.embedding) _setBtnDisabled("btnGenerateEmbed", true);
}

/* Sync button disabled state when a loop starts/stops */
function _syncLoopBtnState(opKey, running) {
  var btnMap = { analysis: "btnStartAnalysis", embedding: "btnGenerateEmbed" };
  var btnId = btnMap[opKey];
  if (btnId) _setBtnDisabled(btnId, running);
}

/* ── Continuous Run (Loop) Mode ─────────────────────────── */
var _continuousRun = {};       /* { analysis: true, reindex: true, ... } */
var _continuousBatch = {};     /* { analysis: 3, ... } — batch counter */
var _serverLoops = {};         /* Server-side loop state — browser defers retrigger when active */
var _LOOP_STORAGE_KEY = "archie_consciousness_loops";

function _saveLoopState() {
  try {
    var active = {};
    Object.keys(_continuousRun).forEach(function(k) {
      if (_continuousRun[k]) active[k] = true;
    });
    localStorage.setItem(_LOOP_STORAGE_KEY, JSON.stringify(active));
  } catch (e) { /* localStorage unavailable */ }
}

function _loadLoopState() {
  try {
    var raw = localStorage.getItem(_LOOP_STORAGE_KEY);
    if (raw) {
      var saved = JSON.parse(raw);
      Object.keys(saved).forEach(function(k) {
        /* Only restore keys that exist in _loopOps — skip removed ops like ghEmbed */
        if (saved[k] && _loopOps[k]) {
          _continuousRun[k] = true;
          _continuousBatch[k] = 0;
        }
      });
    }
  } catch (e) { /* localStorage unavailable */ }
}

/* Map opKey → { startFn, btnId, idleLabel } */
var _loopOps = {
  analysis:  { start: function() { startAnalysis(); },      btnId: "btnStartAnalysis", idle: "\u221E ANALYZE" },
  embedding: { start: function() { generateEmbeddings(); }, btnId: "btnGenerateEmbed", idle: "\u221E EMBED" },
  translate: { start: function() { langGenerateAll(); },    btnId: "langGenAllBtn",    idle: "\u221E TRANSLATE" },
  fullPass:  { start: function() { langFullPass(); },       btnId: "langFullPassBtn",  idle: "\u221E FULL PASS" }
};

var MAX_STATION_LOOPS = 3;

function _activeLoopCount() {
  var count = 0;
  Object.keys(_loopOps).forEach(function(k) {
    if (_continuousRun[k]) count++;
  });
  return count;
}

window.toggleLoop = function(opKey) {
  if (_continuousRun[opKey]) {
    /* Stop */
    _continuousRun[opKey] = false;
    _continuousBatch[opKey] = 0;
    _updateLoopBtn(opKey);
    _syncServerLoop(opKey, false);
    _syncLoopBtnState(opKey, false);
  } else {
    /* Guard: max 3 loops at this station (matches 3-slot model) */
    if (_activeLoopCount() >= MAX_STATION_LOOPS) {
      console.warn("[Loop] Cannot start " + opKey + " — station at max " + MAX_STATION_LOOPS + " loops");
      return;
    }
    /* Start — kick off first batch */
    _continuousRun[opKey] = true;
    _syncLoopBtnState(opKey, true);
    _continuousBatch[opKey] = 0;
    _updateLoopBtn(opKey);
    _syncServerLoop(opKey, true);
    var op = _loopOps[opKey];
    if (op) op.start();
  }
  _saveLoopState();
};

/* Sync loop state to server so it persists without the browser */
function _syncServerLoop(opKey, enabled) {
  _serverLoops[opKey] = enabled;
  api("/api/processing/server-loop/toggle", {
    method: "POST",
    body: { op: opKey, enabled: enabled }
  }).catch(function() {});
}

function _updateLoopBtn(opKey) {
  /* Update all loop buttons for this op (may exist on multiple tabs) */
  var ids = ["loopBtn-" + opKey, "loopBtn-" + opKey + "2"];
  var op = _loopOps[opKey];
  ids.forEach(function(id) {
    var btn = document.getElementById(id);
    if (!btn) return;
    if (_continuousRun[opKey]) {
      btn.textContent = "\u25A0 STOP";
      btn.className = "cs-ops-cmd cs-loop-active";
    } else {
      btn.textContent = (op && op.idle) || ("\u221E " + opKey.toUpperCase());
      btn.className = "cs-ops-cmd cs-loop-idle";
    }
  });
}

function _isCloudJob(job) {
  if (!job || !job.metadata) return false;
  var meta = (typeof job.metadata === "string") ? JSON.parse(job.metadata) : job.metadata;
  return meta.is_cloud === "true" || meta.is_cloud === true;
}

function _loopNext(opKey, completedJob) {
  /* Called when a job completes — start next batch if still looping */
  if (!_continuousRun[opKey]) return;
  /* Never loop on cloud jobs — cloud requires Telegram approval each time */
  if (_isCloudJob(completedJob)) {
    console.warn("[Loop] " + opKey + " completed via cloud — stopping loop (no cloud loops)");
    _loopExhausted(opKey);
    return;
  }
  _loopFailures[opKey] = 0; /* reset failures on success */
  _continuousBatch[opKey] = (_continuousBatch[opKey] || 0) + 1;
  /* If server loop is active for this op, let the server retrigger —
     avoids race where browser and server both create jobs */
  if (_serverLoops[opKey]) {
    console.log("[Loop] " + opKey + " — server loop active, deferring to server");
    return;
  }
  var op = _loopOps[opKey];
  if (op) setTimeout(op.start, 2000); /* 2s pause between batches */
}

function _loopExhausted(opKey) {
  /* Called when API says "no items left" — stop loop gracefully */
  _continuousRun[opKey] = false;
  _continuousBatch[opKey] = 0;
  _loopFailures[opKey] = 0;
  _syncServerLoop(opKey, false);
  _saveLoopState();
  _updateLoopBtn(opKey);
}

var _loopFailures = {};
var LOOP_MAX_RETRIES = 3;

function _loopRetry(opKey) {
  /* Called when a job fails (reaped, timeout, transient error).
     Retry up to LOOP_MAX_RETRIES times, then exhaust. */
  if (!_continuousRun[opKey]) return;
  _loopFailures[opKey] = (_loopFailures[opKey] || 0) + 1;
  if (_loopFailures[opKey] >= LOOP_MAX_RETRIES) {
    console.warn("[Loop] " + opKey + " failed " + _loopFailures[opKey] + " times — stopping");
    _loopFailures[opKey] = 0;
    _loopExhausted(opKey);
    return;
  }
  console.log("[Loop] " + opKey + " failed, retrying (" + _loopFailures[opKey] + "/" + LOOP_MAX_RETRIES + ")");
  var op = _loopOps[opKey];
  if (op) setTimeout(op.start, 5000); /* 5s pause before retry */
}

window.startAnalysis = function() {
  _disableProcessingBtns();
  var batchNum = _continuousRun.analysis ? " [batch " + ((_continuousBatch.analysis || 0) + 1) + "]" : "";
  setHtml("procResult", lcarsMsg("info", "\u25CF", "Assigning agent for analysis\u2026" + batchNum));

  api("/api/processing/start", {
    method: "POST",
    body: { category: "conversations", batch_size: 10 }
  }).then(function(data) {
    if (data.duplicate || data._status === 409) {
      setHtml("procResult", lcarsMsg("warn", "\u25B6", escHtml(data.error || "Job already running")));
      checkActiveJobs();
      return;
    }
    if (data.success && data.job_id) {
      setHtml("procResult", lcarsMsg("ok", "\u25B6", "Job #" + data.job_id + " started \u2014 " + (data.total || 0) + " items queued" + batchNum));
      setTimeout(checkActiveJobs, 1000);
    } else if (data.success) {
      setHtml("procResult", lcarsMsg("ok", "\u2713", escHtml(data.message || "No items to analyze")));
      _loopExhausted("analysis");
      _enableProcessingBtns();
    } else {
      setHtml("procResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Processing failed")));
      _loopExhausted("analysis");
      _enableProcessingBtns();
    }
  }).catch(function(err) {
    setHtml("procResult", lcarsMsg("err", "\u2717", "Error: " + escHtml(err.message || "Request failed")));
    _loopExhausted("analysis");
    _enableProcessingBtns();
  });
};

window.generateEmbeddings = function() {
  _disableProcessingBtns();
  var batchNum = _continuousRun.embedding ? " [batch " + ((_continuousBatch.embedding || 0) + 1) + "]" : "";
  setHtml("procResult", lcarsMsg("info", "\u25CF", "Assigning agent for embeddings\u2026" + batchNum));

  api("/api/processing/generate-embeddings", {
    method: "POST",
    body: { batch_size: 50 }
  }).then(function(data) {
    if (data.duplicate || data._status === 409) {
      setHtml("procResult", lcarsMsg("warn", "\u25B6", escHtml(data.error || "Embedding job already running")));
      checkActiveJobs();
      return;
    }
    if (data.success && data.job_id) {
      setHtml("procResult", lcarsMsg("ok", "\u25B6", "Job #" + data.job_id + " started \u2014 " + (data.total || 0) + " entries queued" + batchNum));
      setTimeout(checkActiveJobs, 1000);
    } else if (data.success) {
      setHtml("procResult", lcarsMsg("ok", "\u2713", escHtml(data.message || "All entries already embedded")));
      _loopExhausted("embedding");
      _enableProcessingBtns();
    } else {
      setHtml("procResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Embedding generation failed")));
      _loopExhausted("embedding");
      _enableProcessingBtns();
    }
  }).catch(function(err) {
    setHtml("procResult", lcarsMsg("err", "\u2717", "Error: " + escHtml(err.message || "Request failed")));
    _loopExhausted("embedding");
    _enableProcessingBtns();
  });
};

/* ── Team Tab — merged into Bridge Command → Crew → Manifest ── */

/* ── Team Sub-tabs — merged into Bridge Command ──── */

/* emotionalDetailChart removed — was Team sub-tab only */

/* ── Insights Tab ──────────────────────────────────── */

/* switchInsightsSubtab removed — Insights sub-tabs (sessions, improvements) no longer in UI */

function loadInsights() {
  api("/api/insights/summary").then(function(data) {
    if (!data.success) return;
    setHtml("insightsBridgeTotal", data.bridge_stats.total || 0);
    setHtml("insightsAvgTime", data.bridge_stats.avg_time_ms || 0);
    setHtml("insightsTokens", data.bridge_stats.total_tokens || 0);
    setHtml("insightsGrowth", data.knowledge_growth || 0);
    refreshIcons();
  }).catch(function(err) {
    console.error("loadInsights error:", err);
  });
}

/* loadSessions / loadImprovements removed — no longer in UI */

/* ── Languages Tab ─────────────────────────────────── */

/* switchLangSubtab removed — Languages tab is now single-page LCARS layout */

var _langGenQueue = [];
var _langGenRunning = false;

/* ── Languages LCARS Operations Terminal ───────────── */

function renderLangOps(agentData, jobData) {
  /* Agents, jobs, and commands all rendered by shared StationOps component */
  _renderOpsAgents("langOpsAgents", "ANALYTICS", jobData);
}

function loadLanguages() {
  // Render ops terminal (always available, even before data loads)
  renderLangOps();

  // Load dashboard stats — aggregate across all languages → readout strips
  api("/api/translations/stats").then(function(data) {
    if (!data.success || !data.stats) return;
    var totalKeys = 0;
    var totalApproved = 0;
    var totalPending = 0;
    Object.keys(data.stats).forEach(function(lang) {
      var s = data.stats[lang];
      totalKeys += s.total || 0;
      totalApproved += s.approved || 0;
      totalPending += s.pending || 0;
    });
    setHtml("langTotalKeys", totalKeys.toLocaleString());
    setHtml("langApproved", totalApproved.toLocaleString());
    setHtml("langPending", totalPending.toLocaleString());
  }).catch(function() {});

  // Per-language coverage → compact LCARS rows
  var flags = {fr:"\ud83c\uddeb\ud83c\uddf7",es:"\ud83c\uddea\ud83c\uddf8",pt:"\ud83c\udde7\ud83c\uddf7",de:"\ud83c\udde9\ud83c\uddea",zh:"\ud83c\udde8\ud83c\uddf3",ar:"\ud83c\uddf8\ud83c\udde6",he:"\ud83c\uddee\ud83c\uddf1"};
  api("/api/translations/language-coverage").then(function(data) {
    if (!data.success) return;
    var langs = data.languages || [];
    var html = '';
    langs.forEach(function(l) {
      var pct = l.coverage_pct || 0;
      var barColor = pct >= 100 ? "#22c55e" : pct >= 80 ? "#f59e0b" : "#f87171";
      var rowCls = pct >= 100 ? "complete" : pct >= 80 ? "warning" : "critical";
      var flag = flags[l.code] || "\ud83c\udf10";
      var safeCode = escHtml(l.code);
      html += '<div class="cs-lang-row ' + rowCls + '" id="langCard-' + safeCode + '">' +
        '<span class="cs-lang-flag">' + flag + '</span>' +
        '<span class="cs-lang-name">' + escHtml(l.name) + '</span>' +
        '<div class="cs-lang-bar"><div class="cs-lang-bar-fill" style="width:' + pct + '%; background:' + barColor + ';"></div></div>' +
        '<span class="cs-lang-stats">' + l.translated + '/' + l.total_keys + ' (' + pct + '%)</span>';
      if (l.missing > 0) {
        html += '<span class="cs-lang-badge miss">' + l.missing + ' MISSING</span>' +
          '<div class="cs-lang-actions"><button class="gen" onclick="langGenerateOne(\'' + safeCode + '\')" ' +
          'id="langGenBtn-' + safeCode + '">Generate</button></div>';
      } else {
        html += '<span class="cs-lang-badge ok">\u2713 COMPLETE</span>';
      }
      html += '</div>';
    });
    setHtml("langCoverageByLang", html || '<div class="cs-empty">No language data</div>');
  }).catch(function() {
    setHtml("langCoverageByLang", '<div class="cs-empty">Coverage data unavailable</div>');
  });

  // Module coverage → compact LCARS rows
  api("/api/translations/module-coverage").then(function(data) {
    var modules = data.modules || data.coverage || [];
    if (!modules.length) {
      setHtml("langCoverageGrid", '<div class="cs-empty">No coverage data</div>');
      return;
    }
    var html = '';
    modules.forEach(function(m) {
      var pct = m.coverage_pct || m.percentage || 0;
      var barColor = pct >= 90 ? "#22c55e" : pct >= 50 ? "#f59e0b" : "#f87171";
      var rowCls = pct >= 90 ? "complete" : pct >= 50 ? "warning" : "critical";
      html += '<div class="cs-lang-row ' + rowCls + '" id="modCard-' + escHtml(m.id) + '">' +
        '<span class="cs-lang-name" style="min-width:120px;">' + escHtml(m.module || m.name) + '</span>' +
        '<div class="cs-lang-bar"><div class="cs-lang-bar-fill" style="width:' + pct + '%; background:' + barColor + ';"></div></div>' +
        '<span class="cs-lang-stats">' + (m.translated || 0) + '/' + (m.total || 0) + ' (' + pct + '%)</span>' +
        '<div class="cs-lang-actions">';
      if ((m.hardcoded || 0) > 0) {
        html += '<button class="tag" onclick="langTagModule(\'' + escHtml(m.id) + '\')" ' +
          'id="tagBtn-' + escHtml(m.id) + '">' + m.hardcoded + ' Tag</button>';
      }
      if (pct < 100) {
        html += '<button class="gen" onclick="langGenerateModule(\'' + escHtml(m.id) + '\')" ' +
          'id="genModBtn-' + escHtml(m.id) + '">Gen</button>';
      }
      html += '</div></div>';
    });
    setHtml("langCoverageGrid", html);
  }).catch(function() {
    setHtml("langCoverageGrid", '<div class="cs-empty">Coverage data unavailable</div>');
  });

  // Auto-load browser, review, glossary (no more subtab switching)
  loadLangBrowser();
  loadLangReview();
  loadLangGlossary();
}

/* ── Scan & Generate Actions ───────────────────── */

window.langScanKeys = function() {
  var btn = document.getElementById("langScanBtn");
  if (btn) { btn.disabled = true; btn.style.opacity = "0.5"; }
  _showLangJob("Scanning templates, modules, JS...");

  api("/api/translations/scan-and-seed", { method: "POST" }).then(function(data) {
    var msg = "Scanned " + (data.total || 0) + " keys \u2014 " + (data.seeded || 0) + " new, " + (data.skipped || 0) + " existing.";
    _showLangJob(msg);
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
    // Always reload stats to keep totals fresh
    _cache.languages = false;
    loadLanguages();
  }).catch(function(err) {
    _showLangJob("Scan failed: " + err);
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
  });
};

window.langGenerateOne = function(langCode) {
  var btn = document.getElementById("langGenBtn-" + langCode);
  if (btn) { btn.disabled = true; btn.textContent = "Queuing..."; }
  _showLangJob("Starting translation for " + langCode.toUpperCase() + "...");

  api("/api/translations/generate-async", { method: "POST", body: { languages: [langCode] } }).then(function(data) {
    if (!data.success) {
      var msg = data.duplicate ? "Translation job already running" : (data.error || "Failed");
      _showLangJob(msg, data.duplicate ? "warn" : "err");
      if (btn) { btn.disabled = false; btn.textContent = "Retry"; }
      return;
    }
    if (!data.job_id) {
      _showLangJob("No missing translations for " + langCode.toUpperCase());
      if (btn) { btn.disabled = false; btn.textContent = "Done"; btn.style.color = "#4ade80"; }
      return;
    }
    _showLangJob("Job #" + data.job_id + " started \u2014 " + data.total + " keys to " + langCode.toUpperCase());
    checkActiveJobs();
    _startLangJobPoll(data.job_id, function() {
      if (btn) { btn.disabled = false; btn.textContent = "Done!"; btn.style.color = "#4ade80"; }
    });
  }).catch(function(err) {
    _showLangJob("Failed: " + err);
    if (btn) { btn.disabled = false; btn.textContent = "Retry"; btn.style.color = "#f87171"; }
  });
};

window.langGenerateAll = function() {
  var btn = document.getElementById("langGenAllBtn");
  if (btn) { btn.disabled = true; btn.style.opacity = "0.5"; }
  var batchNum = _continuousRun.translate ? " [batch " + ((_continuousBatch.translate || 0) + 1) + "]" : "";
  _showLangJob("Queuing all 7 languages..." + batchNum);

  api("/api/translations/generate-async", {
    method: "POST",
    body: { languages: ["fr", "es", "pt", "de", "zh", "ar", "he"] }
  }).then(function(data) {
    if (!data.success) {
      var msg = data.duplicate ? "Translation job already running" : (data.error || "Failed");
      _showLangJob(msg, data.duplicate ? "warn" : "err");
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
      return;
    }
    if (!data.job_id) {
      _showLangJob("No missing translations found");
      _loopExhausted("translate");
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
      return;
    }
    _showLangJob("Job #" + data.job_id + " started \u2014 " + data.total + " keys across 7 languages" + batchNum);
    checkActiveJobs();
    _startLangJobPoll(data.job_id, function() {
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
    });
  }).catch(function(err) {
    _showLangJob("Failed: " + err);
    _loopExhausted("translate");
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
  });
};

/* Generate translations for a specific module only */
window.langGenerateModule = function(moduleId) {
  var btn = document.getElementById("genModBtn-" + moduleId);
  if (btn) { btn.disabled = true; btn.textContent = "..."; }
  _showLangJob("Queuing translations for " + moduleId + "...");

  api("/api/translations/generate-async", {
    method: "POST",
    body: { module_id: moduleId, languages: ["fr", "es", "pt", "de", "zh", "ar", "he"] }
  }).then(function(data) {
    if (!data.success) {
      var msg = data.duplicate ? "Job already running" : (data.error || "Failed");
      _showLangJob(msg, data.duplicate ? "warn" : "err");
      if (btn) { btn.disabled = false; btn.textContent = "Gen"; }
      return;
    }
    if (!data.job_id) {
      _showLangJob(moduleId + ": fully translated!");
      if (btn) { btn.disabled = false; btn.textContent = "Done"; btn.style.color = "#4ade80"; }
      return;
    }
    _showLangJob("Job #" + data.job_id + " \u2014 " + data.total + " keys for " + moduleId);
    checkActiveJobs();
    _startLangJobPoll(data.job_id, function() {
      if (btn) { btn.disabled = false; btn.textContent = "Done!"; btn.style.color = "#4ade80"; }
    });
  }).catch(function(err) {
    _showLangJob("Failed: " + err);
    if (btn) { btn.disabled = false; btn.textContent = "Gen"; btn.style.color = "#f87171"; }
  });
};

/* Poll a translation bridge job — reuses existing _pollJobStatus + _buildJobHtml */
function _startLangJobPoll(jobId, onDone) {
  var pollKey = "lang_" + jobId;
  if (_activeJobPolls[pollKey]) return;
  _activeJobPolls[pollKey] = true;
  /* Progress rendered by StationOps — just track completion for refresh + loop */
  _pollJobStatus(jobId, null, function(completedJob) {
    _activeJobPolls[pollKey] = false;
    _cache.languages = false;
    setTimeout(function() { loadLanguages(); checkActiveJobs(); }, 1500);
    if (onDone) onDone();
  });
}

function _showLangJob(msg, type) {
  var el = document.getElementById("langScanStatus");
  if (el) {
    el.style.display = "block";
    var t = type || "ok";
    var icon = t === "err" ? "\u2717" : t === "warn" ? "\u25B6" : "\u25B6";
    setHtml(el, lcarsMsg(t, icon, escHtml(msg)));
  }
}

/* ----------  Template Audit (modal popup)  ---------- */
window.langAuditTemplates = function() {
  var btn = document.getElementById("langAuditBtn");
  if (btn) { btn.disabled = true; btn.style.opacity = "0.5"; }
  _showLangJob("Auditing templates for hardcoded text...");

  /* Show modal immediately with loading state */
  setHtml("langAuditModalBody", '<span class="cs-loading" style="padding:0;">Scanning templates\u2026</span>');
  var overlay = document.getElementById("langAuditOverlay");
  if (overlay) overlay.classList.add("open");

  api("/api/translations/audit-templates", { method: "POST" }).then(function(data) {
    var html = '<div style="margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">' +
      '<span style="font-size:0.95rem; font-weight:600; color:#fb923c;">' +
        escHtml(data.total_hardcoded) + ' hardcoded strings</span>' +
      '<span style="font-size:0.82rem; color:rgba(255,255,255,0.5);">' +
        escHtml(data.files) + ' files scanned</span></div>';

    if (!data.results || !data.results.length) {
      html += '<div class="cs-empty" style="color:#4ade80; padding:20px; text-align:center;">All templates are i18n-ready!</div>';
    } else {
      html += '<div style="max-height:55vh; overflow-y:auto;">';
      data.results.forEach(function(r) {
        html += '<div style="margin-bottom:12px; padding:10px; background:rgba(251,146,60,0.06); border:1px solid rgba(251,146,60,0.15); border-radius:6px;">';
        html += '<div style="display:flex; justify-content:space-between; margin-bottom:6px;">';
        html += '<span style="color:#fb923c; font-weight:600;">' + escHtml(r.module) + '/' + escHtml(r.file) + '</span>';
        html += '<span style="color:rgba(255,255,255,0.5); font-size:0.78rem;">' + r.count + ' strings</span>';
        html += '</div>';
        html += '<div style="font-size:0.78rem; color:rgba(255,255,255,0.5);">';
        (r.samples || []).slice(0, 5).forEach(function(s) {
          html += '<div style="margin-bottom:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">L' + s.line + ': ' + escHtml(s.text) + '</div>';
        });
        if (r.count > 5) html += '<div style="color:rgba(255,255,255,0.3);">...and ' + (r.count - 5) + ' more</div>';
        html += '</div></div>';
      });
      html += '</div>';
    }
    setHtml("langAuditModalBody", html);
    _showLangJob("Audit complete \u2014 " + data.total_hardcoded + " hardcoded strings found");
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
  }).catch(function(err) {
    setHtml("langAuditModalBody", '<div class="cs-empty" style="color:#f87171;">Audit failed: ' + escHtml(String(err)) + '</div>');
    _showLangJob("Audit failed: " + err);
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
  });
};

window.closeLangAuditModal = function() {
  var overlay = document.getElementById("langAuditOverlay");
  if (overlay) overlay.classList.remove("open");
};

/* ----------  Full i18n Pass  ---------- */
window.langFullPass = function() {
  var btn = document.getElementById("langFullPassBtn");
  if (btn) { btn.disabled = true; btn.style.opacity = "0.5"; }

  // Step 1: Audit templates
  _showLangJob("Full i18n Pass \u2014 Step 1/3: Auditing templates...");
  api("/api/translations/audit-templates", { method: "POST" }).then(function(auditData) {
    _showLangJob("Full i18n Pass \u2014 Step 1/3 done: " + auditData.total_hardcoded + " hardcoded strings. Step 2/3: Scanning keys...");

    // Step 2: Scan and seed new keys
    return api("/api/translations/scan-and-seed", { method: "POST" });
  }).then(function(scanData) {
    var seeded = scanData.seeded || 0;
    var total = scanData.total || 0;
    _showLangJob("Full i18n Pass \u2014 Step 2/3 done: " + total + " keys (" + seeded + " new). Step 3/3: Generating translations...");
    // Refresh stats to pick up any newly seeded keys
    _cache.languages = false;
    loadLanguages();

    // Step 3: Launch async background job for all 7 languages
    return api("/api/translations/generate-async", {
      method: "POST",
      body: { languages: ["fr", "es", "pt", "de", "zh", "ar", "he"] }
    });
  }).then(function(data) {
    if (!data.success) {
      var msg = data.duplicate ? "Translation job already running" : (data.error || "Failed");
      _showLangJob("Full i18n Pass \u2014 " + msg, data.duplicate ? "warn" : "err");
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
      return;
    }
    if (!data.job_id) {
      _showLangJob("Full i18n Pass complete \u2014 no missing translations!");
      _loopExhausted("fullPass");
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
      return;
    }
    _showLangJob("Full i18n Pass \u2014 Job #" + data.job_id + " running (" + data.total + " keys, 7 languages)");
    /* Immediately refresh ops terminal to show the new job */
    checkActiveJobs();
    _startLangJobPoll(data.job_id, function() {
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
    });
  }).catch(function(err) {
    _showLangJob("Full i18n Pass failed: " + err);
    _loopExhausted("fullPass");
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
  });
};

/* ----------  Tag Module (auto-add data-i18n to templates)  ---------- */
window.langTagModule = function(moduleId) {
  var btn = document.getElementById("tagBtn-" + moduleId);
  if (btn) { btn.disabled = true; btn.textContent = "..."; }
  _showLangJob("Tagging " + moduleId + " templates...");

  api("/api/translations/tag-module", { method: "POST", body: { module_id: moduleId } }).then(function(data) {
    if (!data.success) {
      if (btn) { btn.textContent = "Error"; btn.style.color = "#f87171"; btn.disabled = false; }
      _showLangJob("Tag failed: " + (data.error || "unknown"));
      return;
    }
    _showLangJob(moduleId + ": " + data.tagged + " tagged, " + data.keys_seeded + " seeded. Queuing translations...");
    if (btn) { btn.textContent = data.tagged + " tagged"; btn.style.color = "#4ade80"; }

    // Launch async background translation for this module's keys
    return api("/api/translations/generate-async", {
      method: "POST",
      body: { module_id: moduleId, languages: ["fr", "es", "pt", "de", "zh", "ar", "he"] }
    });
  }).then(function(data) {
    if (!data || !data.success) {
      var msg = (data && data.duplicate) ? "Translation job already running" : ((data && data.error) || "");
      if (msg) _showLangJob(moduleId + ": tagged. " + msg, (data && data.duplicate) ? "warn" : "err");
      if (btn) btn.disabled = false;
      return;
    }
    if (!data.job_id) {
      _showLangJob(moduleId + ": tagged and fully translated!");
      if (btn) btn.disabled = false;
      _cache.languages = false;
      setTimeout(function() { loadLanguages(); }, 1000);
      return;
    }
    _showLangJob(moduleId + ": Job #" + data.job_id + " \u2014 translating " + data.total + " keys");
    checkActiveJobs();
    _startLangJobPoll(data.job_id, function() {
      if (btn) btn.disabled = false;
    });
  }).catch(function(err) {
    _showLangJob("Tag failed: " + err);
    if (btn) { btn.textContent = "Error"; btn.style.color = "#f87171"; btn.disabled = false; }
  });
};

function loadLangBrowser() {
  var search = document.getElementById("langSearch");
  var lang = document.getElementById("langFilterLang");
  var params = "?language=" + (lang ? lang.value : "fr");
  if (search && search.value) params += "&search=" + encodeURIComponent(search.value);

  api("/api/translations/browser" + params).then(function(data) {
    var items = data.translations || [];
    if (!items.length) {
      setHtml("langBrowserTable", '<div class="cs-empty">No translations found</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr>' +
      '<th style="width:30%;">Key</th><th style="width:30%;">English</th>' +
      '<th style="width:30%;">Translation</th><th style="width:10%;">Status</th></tr></thead><tbody>';
    items.slice(0, 50).forEach(function(t) {
      var statusCls = (t.status === "approved") ? "ok" : (t.status === "pending_review") ? "miss" : "";
      html += '<tr><td style="font-family:\'IBM Plex Mono\',monospace; font-size:0.72rem; opacity:0.7;">' + escHtml(t.key) + '</td>' +
        '<td style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml(t.english || "\u2014") + '</td>' +
        '<td style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml(t.target || "\u2014") + '</td>' +
        '<td><span class="cs-lang-badge ' + statusCls + '">' + escHtml(t.status || "\u2014") + '</span></td></tr>';
    });
    html += '</tbody></table></div>';
    if (items.length > 50) html += '<div style="text-align:center; padding:8px; font-size:0.72rem; color:rgba(255,255,255,0.3);">Showing 50 of ' + items.length + '</div>';
    setHtml("langBrowserTable", html);
  }).catch(function() {
    setHtml("langBrowserTable", '<div class="cs-empty">Error loading translations</div>');
  });
}

function loadLangReview() {
  var lang = document.getElementById("langReviewLang");
  var params = "?language=" + (lang ? lang.value : "fr") + "&status=pending_review";

  api("/api/translations/review" + params).then(function(data) {
    var items = data.translations || [];
    if (!items.length) {
      setHtml("langReviewList", '<div class="cs-empty" style="padding:12px;">No pending reviews for ' + ((lang && lang.value) || "fr").toUpperCase() + '</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr>' +
      '<th style="width:35%;">Key</th><th style="width:10%;">Lang</th>' +
      '<th style="width:40%;">Text</th><th style="width:15%;">Source</th></tr></thead><tbody>';
    items.slice(0, 30).forEach(function(t) {
      html += '<tr><td style="font-family:\'IBM Plex Mono\',monospace; font-size:0.72rem; opacity:0.7;">' + escHtml(t.key) + '</td>' +
        '<td><span class="cs-lang-badge miss">' + escHtml(t.language).toUpperCase() + '</span></td>' +
        '<td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml(t.text || "\u2014") + '</td>' +
        '<td style="font-size:0.72rem; opacity:0.5;">' + escHtml(t.generated_by || "\u2014") + '</td></tr>';
    });
    html += '</tbody></table></div>';
    if (items.length > 30) html += '<div style="text-align:center; padding:8px; font-size:0.72rem; color:rgba(255,255,255,0.3);">Showing 30 of ' + items.length + '</div>';
    setHtml("langReviewList", html);
  }).catch(function() {
    setHtml("langReviewList", '<div class="cs-empty">Review data unavailable</div>');
  });
}

function loadLangGlossary() {
  var langSel = document.getElementById("langGlossaryLang");
  var lang = langSel ? langSel.value : "fr";
  api("/api/translation-memory?language=" + lang).then(function(data) {
    var items = data.entries || data.glossary || [];
    if (!items.length) {
      setHtml("langGlossaryList", '<div class="cs-empty" style="padding:12px;">No glossary entries for ' + lang.toUpperCase() + '</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr>' +
      '<th style="width:30%;">Source</th><th style="width:35%;">Translation</th>' +
      '<th style="width:10%;">Lang</th><th style="width:25%;">Category</th></tr></thead><tbody>';
    items.forEach(function(g) {
      html += '<tr><td style="font-weight:600;">' + escHtml(g.source_text) + '</td>' +
        '<td>' + escHtml(g.translated_text) + '</td>' +
        '<td><span class="cs-lang-badge ok">' + escHtml(g.language).toUpperCase() + '</span></td>' +
        '<td style="font-size:0.72rem; opacity:0.5;">' + escHtml(g.category || "\u2014") + '</td></tr>';
    });
    html += '</tbody></table></div>';
    setHtml("langGlossaryList", html);
  }).catch(function() {
    setHtml("langGlossaryList", '<div class="cs-empty">Glossary unavailable</div>');
  });
}

/* ── GitHub Tab ────────────────────────────────────── */

function loadGitHub() {
  renderGitHubOps();
  api("/api/github/repos").then(function(data) {
    if (!data.success) return;
    var repos = data.repos || [];
    setHtml("ghRepoCount", repos.length);

    if (!repos.length) {
      setHtml("ghRepoGrid",
        '<div style="grid-column:1/-1; text-align:center; padding:40px 20px; color:rgba(255,255,255,0.3);">' +
        '<div style="font-size:2rem; margin-bottom:8px;">&#x1f4e1;</div>' +
        '<div style="font-family:Antonio,sans-serif; font-size:0.85rem; letter-spacing:1px; text-transform:uppercase;">No repositories indexed</div>' +
        '<div style="font-size:0.75rem; margin-top:4px;">Paste a GitHub URL above to begin learning</div>' +
        '</div>');
      return;
    }

    var html = '';
    repos.forEach(function(r) {
      var coverageCls = 'coverage-low';
      if (r.indexed && r.indexed_files > 0) {
        coverageCls = 'coverage-mid';
      }

      var circumference = 2 * Math.PI * 18;
      var dashoffset = circumference; // 0% default, updated by embed stats

      var descSnippet = r.description ? escHtml(r.description.substring(0, 120)) + (r.description.length > 120 ? '...' : '') : '';

      html += '<div class="gh-repo-card ' + coverageCls + '" data-repo-id="' + r.id + '">' +
        '<div class="gh-repo-card-name" title="' + escHtml(r.repo_name) + '">' + escHtml(r.repo_name) + '</div>' +
        (descSnippet ? '<div style="font-size:0.68rem; color:rgba(255,255,255,0.35); margin:-4px 0 6px; line-height:1.3; overflow:hidden; max-height:2.6em;">' + descSnippet + '</div>' : '') +
        '<div class="gh-repo-card-row">' +
          '<svg class="gh-progress-ring" viewBox="0 0 44 44">' +
            '<circle class="gh-progress-ring-bg" cx="22" cy="22" r="18" />' +
            '<circle class="gh-progress-ring-fill" cx="22" cy="22" r="18"' +
              ' stroke="#22c55e" stroke-dasharray="' + circumference + '"' +
              ' stroke-dashoffset="' + dashoffset + '"' +
              ' transform="rotate(-90 22 22)" data-repo="' + r.id + '" />' +
          '</svg>' +
          '<div style="flex:1; padding-left:12px;">' +
            '<div style="font-family:Orbitron,sans-serif; font-size:0.9rem; font-weight:700; color:' +
              (r.indexed ? '#22c55e' : '#f59e0b') + ';">' + (r.indexed_files || 0) + ' <span style="font-size:0.65rem; color:rgba(255,255,255,0.4);">files</span></div>' +
            '<div style="font-size:0.7rem; color:rgba(255,255,255,0.35);">' +
              (r.indexed ? 'Indexed ' + formatAge(r.indexed_at) : 'Pending') + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="gh-repo-card-meta">' +
          (r.repo_type ? '<span>' + escHtml(r.repo_type) + '</span>' : '') +
          (r.status ? '<span>' + escHtml(r.status) + '</span>' : '') +
        '</div>' +
        '<div class="gh-repo-card-actions">' +
          '<button onclick="event.stopPropagation(); reindexRepo(' + r.id + ')">Re-index</button>' +
          '<button class="danger" onclick="event.stopPropagation(); deleteRepo(' + r.id + ', \'' + escHtml(r.repo_name).replace(/'/g, "\\'") + '\')">Delete</button>' +
          '<a href="https://github.com/' + escHtml(r.repo_name) + '" target="_blank" onclick="event.stopPropagation();">Open</a>' +
          (r.local_path ? '<button onclick="event.stopPropagation(); openRepoExplorer(' + r.id + ', \'' + escHtml(r.repo_name).replace(/'/g, "\\'") + '\')" style="background:rgba(139,92,246,0.2); border-color:rgba(139,92,246,0.4); color:#c4b5fd;">Explore</button>' : '') +
        '</div>' +
      '</div>';
    });
    setHtml("ghRepoGrid", html);
    refreshIcons();
    loadGitHubEmbedStats();
  }).catch(function(err) {
    console.error("loadGitHub error:", err);
    setHtml("ghRepoGrid", '<div class="cs-empty">Error loading repos</div>');
  });
}

function loadGitHubEmbedStats() {
  api("/github/stats").then(function(data) {
    if (data.success) {
      setHtml("ghEmbedPct", (data.embed_pct || 0) + "%");
      setHtml("ghSearchable", (data.embedded_files || 0).toLocaleString());
      // Also update file count from actual KB data
      setHtml("ghFileCount", (data.total_files || 0).toLocaleString());
    }
  }).catch(function() {});
}

/* ── Shared: Render station crew + cross-station assists ─── */
/* Delegates to shared StationOps component (station-ops.js) */

/* Track station capacity — updated by StationOps onCapacityChange */
var _stationAtCapacity = false;

/* Per-tab StationOps instances — all point to ANALYTICS station,
   each rendering into its own ops terminal element IDs */
var _kbOps = null;
var _ghOps = null;
var _langOps = null;

function _getOpsInstance(elId) {
  /* Return (or create) the StationOps instance for the given agents element */
  if (elId === "kbOpsAgents") {
    if (!_kbOps) {
      _kbOps = new StationOps({
        stationCode: "ANALYTICS",
        moduleSource: "consciousness",
        agentsElId: "kbOpsAgents",
        jobsElId: "kbOpsJobs",
        commandsElId: "kbOpsCommands",
        statusElId: "kbOpsOnline",
        commands: [
          { label: "ANALYZE", cls: "purple", fn: "startAnalysis()", id: "btnStartAnalysis" },
          { label: "\u221E ANALYZE", cls: "cs-loop-idle", fn: "toggleLoop('analysis')", id: "loopBtn-analysis" },
          { label: "EMBED", cls: "green", fn: "generateEmbeddings()", id: "btnGenerateEmbed" },
          { label: "\u221E EMBED", cls: "cs-loop-idle", fn: "toggleLoop('embedding')", id: "loopBtn-embedding" }
        ],
        onCapacityChange: function(atCap) { _stationAtCapacity = atCap; _applyStationCapacity(atCap); }
      });
    }
    return _kbOps;
  }
  if (elId === "ghOpsAgents") {
    if (!_ghOps) {
      _ghOps = new StationOps({
        stationCode: "ANALYTICS",
        moduleSource: "consciousness",
        agentsElId: "ghOpsAgents",
        jobsElId: "ghOpsJobs",
        commandsElId: "ghOpsCommands",
        statusElId: "ghOpsOnline",
        commands: [
          { label: "REINDEX ALL", cls: "amber", fn: "reindexAllRepos()", id: "btnReindexAll" },
          { label: "ANALYZE", cls: "purple", fn: "startAnalysis()", id: "btnStartAnalysis2" },
          { label: "\u221E ANALYZE", cls: "cs-loop-idle", fn: "toggleLoop('analysis')", id: "loopBtn-analysis2" },
          { label: "EMBED", cls: "green", fn: "generateEmbeddings()", id: "btnGenerateEmbed2" },
          { label: "\u221E EMBED", cls: "cs-loop-idle", fn: "toggleLoop('embedding')", id: "loopBtn-embedding2" },
          { label: "VERIFY", cls: "cyan", fn: "verifyGitHubData()" }
        ],
        onCapacityChange: function(atCap) { _stationAtCapacity = atCap; _applyStationCapacity(atCap); }
      });
    }
    return _ghOps;
  }
  if (elId === "langOpsAgents") {
    if (!_langOps) {
      _langOps = new StationOps({
        stationCode: "ANALYTICS",
        moduleSource: "consciousness",
        agentsElId: "langOpsAgents",
        jobsElId: "langOpsJobs",
        commandsElId: "langOpsCommands",
        statusElId: "langOpsOnline",
        commands: [
          { label: "AUDIT", cls: "amber", fn: "langAuditTemplates()", id: "langAuditBtn" },
          { label: "SCAN KEYS", cls: "purple", fn: "langScanKeys()", id: "langScanBtn" },
          { label: "GENERATE ALL", cls: "green", fn: "langGenerateAll()", id: "langGenAllBtn" },
          { label: "\u221E TRANSLATE", cls: "cs-loop-idle", fn: "toggleLoop('translate')", id: "loopBtn-translate" },
          { label: "FULL PASS", cls: "cyan", fn: "langFullPass()", id: "langFullPassBtn" },
          { label: "\u221E FULL PASS", cls: "cs-loop-idle", fn: "toggleLoop('fullPass')", id: "loopBtn-fullPass" }
        ],
        onCapacityChange: function(atCap) { _stationAtCapacity = atCap; _applyStationCapacity(atCap); }
      });
    }
    return _langOps;
  }
  return null;
}

function _renderOpsAgents(elId, homeStationCode, jobData) {
  /* Delegate to shared StationOps component — renders agents + jobs + commands */
  var ops = _getOpsInstance(elId);
  if (ops) {
    ops.render(jobData);
  }
}

function _applyStationCapacity(atCapacity) {
  /* Disable/enable ALL command buttons across all tabs when station is full */
  var allBtnIds = [
    "btnStartAnalysis", "btnEmbedKB",
    "btnReindexAll", "btnEmbedGH",
    "langAuditBtn", "langScanBtn", "langGenAllBtn", "langFullPassBtn"
  ];
  allBtnIds.forEach(function(id) {
    var btn = document.getElementById(id);
    if (btn) {
      btn.disabled = atCapacity;
      btn.title = atCapacity ? "Station at capacity \u2014 all agents busy" : "";
    }
  });
  /* Update ops terminal status indicators */
  ["kbOpsOnline", "ghOpsOnline", "langOpsOnline"].forEach(function(id) {
    var el = document.getElementById(id);
    if (!el) return;
    var dot = el.querySelector(".cs-ops-dot");
    var textNode = el.childNodes[el.childNodes.length - 1];
    if (atCapacity) {
      if (dot) { dot.style.background = "#f59e0b"; dot.style.boxShadow = "0 0 4px #f59e0b"; }
      if (textNode && textNode.nodeType === 3) textNode.textContent = " AT CAPACITY";
      el.style.color = "#f59e0b";
    } else {
      if (dot) { dot.style.background = ""; dot.style.boxShadow = ""; }
      if (textNode && textNode.nodeType === 3) textNode.textContent = " ONLINE";
      el.style.color = "";
    }
  });
}

/* ── GitHub LCARS Operations Terminal ─────────────── */

function renderGitHubOps(agentData, jobData) {
  /* Agents, jobs, and commands all rendered by shared StationOps component */
  _renderOpsAgents("ghOpsAgents", "ANALYTICS", jobData);
}

/* ── Verify/Audit GitHub Data ────────────────────── */

window.verifyGitHubData = function() {
  /* Show results in modal so they don't get stomped by active job display */
  setHtml("verifyModalBody", '<span class="cs-loading" style="padding:0;">Verifying GitHub data integrity\u2026</span>');
  var overlay = document.getElementById("verifyOverlay");
  if (overlay) overlay.classList.add("open");

  api("/github/stats").then(function(data) {
    if (!data.success) {
      setHtml("verifyModalBody", '<span style="color:#f87171;">\u2717 ' + escHtml(data.error || "Verification failed") + '</span>');
      return;
    }

    var repos = data.repos || [];
    var mismatches = data.mismatches || [];
    var needEmbed = 0;
    var totalFiles = 0;
    var totalEmbedded = 0;

    var html = '';

    /* Summary stats */
    repos.forEach(function(r) {
      totalFiles += (r.actual || 0);
      totalEmbedded += (r.embedded || 0);
      var unembedded = (r.actual || 0) - (r.embedded || 0);
      if (unembedded > 0) needEmbed += unembedded;
    });
    var embedPct = totalFiles > 0 ? Math.round((totalEmbedded / totalFiles) * 100) : 0;

    html += '<div style="display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;">';
    html += '<div style="flex:1; min-width:100px; padding:10px 14px; background:rgba(0,255,255,0.06); border:1px solid rgba(0,255,255,0.15); border-radius:8px; text-align:center;">';
    html += '<div style="font-size:1.4rem; font-weight:700; color:#00ffff;">' + repos.length + '</div>';
    html += '<div style="font-size:0.72rem; color:rgba(255,255,255,0.5);">Repos</div></div>';
    html += '<div style="flex:1; min-width:100px; padding:10px 14px; background:rgba(34,197,94,0.06); border:1px solid rgba(34,197,94,0.15); border-radius:8px; text-align:center;">';
    html += '<div style="font-size:1.4rem; font-weight:700; color:#22c55e;">' + totalFiles + '</div>';
    html += '<div style="font-size:0.72rem; color:rgba(255,255,255,0.5);">KB Files</div></div>';
    html += '<div style="flex:1; min-width:100px; padding:10px 14px; background:rgba(139,92,246,0.06); border:1px solid rgba(139,92,246,0.15); border-radius:8px; text-align:center;">';
    html += '<div style="font-size:1.4rem; font-weight:700; color:#8b5cf6;">' + embedPct + '%</div>';
    html += '<div style="font-size:0.72rem; color:rgba(255,255,255,0.5);">Embedded</div></div>';
    if (mismatches.length) {
      html += '<div style="flex:1; min-width:100px; padding:10px 14px; background:rgba(245,158,11,0.06); border:1px solid rgba(245,158,11,0.15); border-radius:8px; text-align:center;">';
      html += '<div style="font-size:1.4rem; font-weight:700; color:#f59e0b;">' + mismatches.length + '</div>';
      html += '<div style="font-size:0.72rem; color:rgba(255,255,255,0.5);">Mismatches</div></div>';
    }
    html += '</div>';

    /* Per-repo table */
    if (repos.length) {
      html += '<div style="max-height:350px; overflow-y:auto; border:1px solid rgba(255,255,255,0.08); border-radius:8px;">';
      html += '<div style="display:grid; grid-template-columns:1fr 60px 60px 70px; gap:0; font-size:0.72rem; color:rgba(255,255,255,0.4); padding:6px 10px; border-bottom:1px solid rgba(255,255,255,0.08); position:sticky; top:0; background:rgba(15,15,25,0.95);">';
      html += '<span>Repository</span><span>DB</span><span>KB</span><span>Embedded</span></div>';
      repos.forEach(function(r) {
        var expected = r.expected || 0;
        var actual = r.actual || 0;
        var embedded = r.embedded || 0;
        var match = expected === actual;
        var rowBg = match ? 'transparent' : 'rgba(245,158,11,0.04)';
        var icon = match ? '<span style="color:#22c55e;">\u2713</span>' : '<span style="color:#f59e0b;">\u26A0</span>';
        html += '<div style="display:grid; grid-template-columns:1fr 60px 60px 70px; gap:0; font-size:0.78rem; padding:5px 10px; border-bottom:1px solid rgba(255,255,255,0.04); background:' + rowBg + ';">';
        html += '<span style="color:rgba(255,255,255,0.8); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + icon + ' ' + escHtml(r.repo_name) + '</span>';
        html += '<span style="color:rgba(255,255,255,0.5);">' + expected + '</span>';
        html += '<span style="color:rgba(255,255,255,0.5);">' + actual + '</span>';
        html += '<span style="color:' + (embedded === actual ? '#22c55e' : 'rgba(255,255,255,0.4)') + ';">' + embedded + '/' + actual + '</span>';
        html += '</div>';
      });
      html += '</div>';
    }

    if (needEmbed > 0) {
      html += '<div style="margin-top:12px; font-size:0.8rem; color:#8b5cf6;">' + needEmbed + ' files need embedding — use EMBED FILES to generate</div>';
    }

    setHtml("verifyModalBody", html);
  }).catch(function(err) {
    setHtml("verifyModalBody", '<span style="color:#f87171;">\u2717 ' + escHtml(err.message || "Verification error") + '</span>');
  });
};

window.closeVerifyModal = function() {
  var overlay = document.getElementById("verifyOverlay");
  if (overlay) overlay.classList.remove("open");
};

/* ── GitHub Repo Management ──────────────────────── */

/* Inline Intake (replaces modal) */
window.toggleIntakeOptions = function() {
  var el = document.getElementById("ghIntakeOptions");
  if (el) el.classList.toggle("open");
};

window.ingestRepo = function() {
  var url = (document.getElementById("ghIntakeUrl").value || "").trim();
  if (!url) return;

  var repoType = document.getElementById("ghIntakeType").value || "";
  var maxFiles = parseInt(document.getElementById("ghIntakeMax").value) || 2000;

  var btn = document.getElementById("ghIntakeBtn");
  if (btn) { btn.disabled = true; btn.textContent = "INGESTING..."; }

  var prog = document.getElementById("ghIntakeProgress");
  if (prog) prog.classList.add("active");
  setHtml("ghIntakeStatus", "Starting indexing...");
  setHtml("ghIntakeResult", "");

  var body = { repo_url: url, max_files: maxFiles };
  if (repoType) body.repo_type = repoType;

  api("/github/index-selective", { method: "POST", body: body }).then(function(data) {
    if (data.success) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", "Indexing job started \u2014 " + escHtml(data.message || "processing")));
      document.getElementById("ghIntakeUrl").value = "";
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Failed to start indexing")));
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Network error")));
  }).finally(function() {
    if (btn) { btn.disabled = false; btn.textContent = "INGEST"; }
    if (prog) prog.classList.remove("active");
    _cache.github = false;
    loadGitHub();
  });
};

/* Delete Repo */
window.deleteRepo = function(repoId, repoName) {
  if (!confirm("Delete repository '" + repoName + "' and all indexed files?\n\nThis cannot be undone.")) return;

  api("/github/repositories/" + repoId, { method: "DELETE" }).then(function(data) {
    if (data.success) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", escHtml(repoName) + " removed"));
      _cache.github = false;
      loadGitHub();
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Delete failed")));
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Delete error")));
  });
};

window.reindexRepo = function(repoId) {
  setHtml("ghIntakeResult", lcarsMsg("info", "\u25CF", "Assigning agent to re-index repo\u2026"));
  api("/github/reindex/" + repoId, { method: "POST" }).then(function(data) {
    if (data.success) {
      var msg = 'Re-indexed ' + (data.indexed || 0) + ' files from ' + escHtml(data.repo || '#' + repoId);
      if (data.job_id) msg += ' \u2014 Job #' + data.job_id;
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", msg));
      _cache.github = false;
      loadGitHub();
      setTimeout(checkActiveJobs, 1000);
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Failed")));
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Error")));
  });
};

window.reindexAllRepos = function() {
  _disableGitHubBtns();
  setHtml("ghIntakeResult", lcarsMsg("info", "\u25CF", "Assigning agent to re-index all repos\u2026"));
  api("/github/reindex-all", { method: "POST" }).then(function(data) {
    if (data.duplicate || data._status === 409) {
      setHtml("ghIntakeResult", lcarsMsg("warn", "\u25B6", escHtml(data.error || "Reindex job already running")));
      checkActiveJobs();
      return;
    }
    if (data.success && data.job_id) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u25B6", "Job #" + data.job_id + " started \u2014 " + (data.total_repos || 0) + " stale repos queued"));
      setTimeout(checkActiveJobs, 1000);
    } else if (data.success && data.skipped) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", escHtml(data.message || "All repos up to date")));
      _enableGitHubBtns();
    } else if (data.success) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", "No repos to re-index"));
      _enableGitHubBtns();
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Failed")));
      _enableGitHubBtns();
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Error")));
    _enableGitHubBtns();
  });
};

/* embedGitHubFiles removed — unified into generateEmbeddings() which
   handles all unembedded knowledge_base entries (both KB and GitHub sourced).
   Both tabs now use the same "embedding" loop op. */

/* Semantic Search (Discovery Console) */
window.searchGithubSemantic = function() {
  var query = (document.getElementById("ghDiscoveryInput").value || "").trim();
  if (!query) return;

  setHtml("ghDiscoveryResults", '<div class="cs-loading">Searching...</div>');

  api("/github/search-semantic", { method: "POST", body: { query: query, limit: 20 } }).then(function(data) {
    if (!data.success || !data.results || !data.results.length) {
      setHtml("ghDiscoveryResults",
        '<div style="text-align:center; padding:20px; color:rgba(255,255,255,0.3); font-size:0.8rem;">' +
        'No matches found. Try different terms or index more repos.</div>');
      return;
    }

    var html = '<div style="font-size:0.72rem; color:rgba(255,255,255,0.3); margin-bottom:8px;">' +
      data.results.length + ' matches</div>';
    data.results.forEach(function(r) {
      var score = r.similarity ? Math.round(r.similarity * 100) + "%" : "";
      html += '<div class="gh-discovery-result">' +
        '<span class="gh-discovery-result-path">' + escHtml(r.file_path || r.title || "Unknown") + '</span>' +
        (r.repo_name ? '<span class="gh-discovery-result-repo">' + escHtml(r.repo_name) + '</span>' : '') +
        (score ? '<span class="gh-discovery-result-score">' + score + '</span>' : '') +
        (r.snippet ? '<div class="gh-discovery-result-snippet">' + escHtml(r.snippet) + '</div>' : '') +
        '</div>';
    });
    setHtml("ghDiscoveryResults", html);
  }).catch(function(err) {
    setHtml("ghDiscoveryResults", lcarsMsg("err", "\u2717", escHtml(err.message || "Search error")));
  });
};

/* ── Integration Tab ──────────────────────────────── */

function loadIntegration() {
  // System health
  api("/api/integration/health").then(function(data) {
    if (!data.success) return;
    var sys = data.systems;
    Object.keys(sys).forEach(function(key) {
      var s = sys[key];
      var statusEl = document.getElementById("int" + key.charAt(0).toUpperCase() + key.slice(1) + "Status");
      if (statusEl) statusEl.textContent = s.status === "online" ? (s.projects || s.stations || s.repos || "Online") : "Offline";
    });
    refreshIcons();
  }).catch(function() {});

  // Dev HQ summary
  api("/api/integration/devhq-summary").then(function(data) {
    if (!data.success) return;
    var html = '';
    if (data.projects && data.projects.length) {
      html += '<div style="margin-bottom:12px; font-size:0.78rem; color:rgba(255,255,255,0.4);">Recent Projects</div>';
      data.projects.forEach(function(p) {
        html += '<div class="cs-activity-item">' +
          '<i data-lucide="folder"></i>' +
          '<div class="cs-activity-text">' + escHtml(p.name || p.title) + '</div>' +
          '<span class="cs-badge">' + escHtml(p.status) + '</span>' +
          '</div>';
      });
    }
    if (data.decisions && data.decisions.length) {
      html += '<div style="margin-top:12px; margin-bottom:8px; font-size:0.78rem; color:rgba(255,255,255,0.4);">Recent Decisions</div>';
      data.decisions.slice(0, 3).forEach(function(d) {
        html += '<div class="cs-activity-item">' +
          '<i data-lucide="landmark"></i>' +
          '<div class="cs-activity-text">' + escHtml(d.title) + '</div>' +
          '<span class="cs-activity-time">' + formatAge(d.created_at) + '</span>' +
          '</div>';
      });
    }
    if (!html) html = '<div class="cs-empty">No recent Dev HQ activity</div>';
    setHtml("intDevhqActivity", html);
    refreshIcons();
  }).catch(function() {
    setHtml("intDevhqActivity", '<div class="cs-empty">Dev HQ data unavailable</div>');
  });
}

window.togglePipelineTest = function() {
  var body = document.getElementById("pipelineBody");
  var btn = document.getElementById("pipelineToggleBtn");
  if (!body) return;
  var open = body.style.display !== "none";
  body.style.display = open ? "none" : "block";
  if (btn) btn.classList.toggle("open", !open);
  refreshIcons();
};

/* ── Init ──────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", function () {
  refreshIcons();

  // Populate LCARS stardate readouts in modal headers
  (function() {
    var now = new Date();
    var sd = (now.getFullYear() - 2000) + "" +
             String(Math.floor((now.getMonth() * 30 + now.getDate()) / 3.65)).padStart(3, "0") + "." +
             String(now.getHours() * 60 + now.getMinutes()).padStart(4, "0");
    document.querySelectorAll(".cs-modal-header-stardate").forEach(function(el) {
      el.textContent = "SD " + sd;
    });
  })();

  /* Agent modal overlay removed — profiles now in Bridge Command */
  // Initialize Glass Nav
  var navEl = document.getElementById("csNav");
  if (navEl) {
    _glassNav = new GlassNav(navEl, {
      onSwitch: function(tab) { switchConsciousnessTab(tab); }
    });
  }

  // Resize handler for HoloSphere
  window.addEventListener("resize", function() {
    if (_holoSphere) _holoSphere.resize();
  });

  /* Restore loop button states from localStorage + server state.
     Server state takes priority — if server has a loop active, enable it locally too. */
  _loadLoopState();
  api("/api/processing/server-loop/status").then(function(data) {
    if (!data.success) return;
    var serverLoops = data.loops || {};
    _serverLoops = serverLoops;
    Object.keys(serverLoops).forEach(function(opKey) {
      if (serverLoops[opKey] && !_continuousRun[opKey]) {
        _continuousRun[opKey] = true;
        _continuousBatch[opKey] = 0;
      } else if (!serverLoops[opKey] && _continuousRun[opKey]) {
        /* Server stopped this loop (e.g. backlog cleared) — sync locally */
        _continuousRun[opKey] = false;
        _continuousBatch[opKey] = 0;
      }
    });
    _saveLoopState();
    Object.keys(_continuousRun).forEach(function(opKey) {
      _updateLoopBtn(opKey);
      _syncLoopBtnState(opKey, !!_continuousRun[opKey]);
    });
  }).catch(function() {});
  Object.keys(_continuousRun).forEach(function(opKey) {
    _updateLoopBtn(opKey);
    _syncLoopBtnState(opKey, !!_continuousRun[opKey]);
  });
  /* Deferred auto-resume: wait for checkActiveJobs to load, then
     kick any loop that has no running job */
  setTimeout(function() {
    Object.keys(_continuousRun).forEach(function(opKey) {
      if (!_continuousRun[opKey]) return;
      var op = _loopOps[opKey];
      if (op) {
        console.log("[Loop] Auto-resuming " + opKey + " after page load");
        op.start();
      }
    });
  }, 3000);

  var hash = window.location.hash.replace("#", "");
  var validTabs = ["dashboard", "knowledge", "github", "languages"];
  if (hash && validTabs.indexOf(hash) !== -1) {
    switchConsciousnessTab(hash);
  } else {
    switchConsciousnessTab("dashboard");
  }
});

/* ── Knowledge Timeline Chart Popup ──────────────────────── */
window.showKnowledgeTimeline = function() {
  /* Remove existing popup if any */
  var existing = document.getElementById("kbTimelineOverlay");
  if (existing) { existing.remove(); return; }

  var overlay = document.createElement("div");
  overlay.id = "kbTimelineOverlay";
  overlay.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;";
  overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

  var panel = document.createElement("div");
  panel.style.cssText = "background:#0a0a1a;border:2px solid #8b5cf6;border-radius:12px;padding:24px;width:90%;max-width:700px;position:relative;";

  var title = document.createElement("div");
  title.style.cssText = "font-family:'Orbitron',sans-serif;color:#8b5cf6;font-size:16px;margin-bottom:16px;text-align:center;";
  title.textContent = "KNOWLEDGE TIMELINE — 48H";

  var close = document.createElement("span");
  close.style.cssText = "position:absolute;top:12px;right:16px;color:#666;font-size:20px;cursor:pointer;";
  close.textContent = "\u2715";
  close.onclick = function() { overlay.remove(); };

  var canvas = document.createElement("canvas");
  canvas.width = 650;
  canvas.height = 300;
  canvas.style.cssText = "width:100%;height:auto;";

  var legend = document.createElement("div");
  legend.style.cssText = "display:flex;justify-content:center;gap:24px;margin-top:12px;font-family:'IBM Plex Mono',monospace;font-size:12px;";
  legend.innerHTML = '<span style="color:#8b5cf6">\u25CF Total</span><span style="color:#22c55e">\u25CF Embedded</span><span style="color:#f59e0b">\u25CF Unembedded</span>';

  panel.appendChild(close);
  panel.appendChild(title);
  panel.appendChild(canvas);
  panel.appendChild(legend);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  /* Fetch data and draw */
  api("/api/processing/knowledge-timeline").then(function(data) {
    if (!data.success || !data.points || !data.points.length) {
      title.textContent = "No data available";
      return;
    }
    _drawTimelineChart(canvas, data.points);
  }).catch(function() {
    title.textContent = "Failed to load data";
  });
};

function _drawTimelineChart(canvas, points) {
  var ctx = canvas.getContext("2d");
  var W = canvas.width, H = canvas.height;
  var pad = { top: 20, right: 20, bottom: 40, left: 60 };
  var cW = W - pad.left - pad.right;
  var cH = H - pad.top - pad.bottom;

  /* Find ranges */
  var maxVal = 0;
  points.forEach(function(p) {
    if (p.total > maxVal) maxVal = p.total;
  });
  maxVal = Math.ceil(maxVal / 100) * 100 || 100;

  /* Clear */
  ctx.fillStyle = "#0a0a1a";
  ctx.fillRect(0, 0, W, H);

  /* Grid lines */
  ctx.strokeStyle = "#1a1a2e";
  ctx.lineWidth = 1;
  for (var g = 0; g <= 4; g++) {
    var gy = pad.top + cH - (g / 4) * cH;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(W - pad.right, gy);
    ctx.stroke();

    ctx.fillStyle = "#555";
    ctx.font = "11px 'IBM Plex Mono', monospace";
    ctx.textAlign = "right";
    ctx.fillText(Math.round(maxVal * g / 4).toLocaleString(), pad.left - 8, gy + 4);
  }

  /* Time labels */
  ctx.fillStyle = "#555";
  ctx.textAlign = "center";
  ctx.font = "10px 'IBM Plex Mono', monospace";
  var labelStep = Math.max(1, Math.floor(points.length / 6));
  for (var li = 0; li < points.length; li += labelStep) {
    var lx = pad.left + (li / (points.length - 1)) * cW;
    var d = new Date(points[li].t);
    var lbl = d.getHours() + ":00";
    if (li === 0 || d.getHours() === 0) lbl = (d.getMonth() + 1) + "/" + d.getDate() + " " + lbl;
    ctx.fillText(lbl, lx, H - pad.bottom + 20);
  }

  /* Draw lines */
  var series = [
    { key: "total", label: "Intelligence", color: "#8b5cf6" },
    { key: "kb", label: "Knowledge", color: "#3b82f6" },
    { key: "embedded", label: "Embedded", color: "#22c55e" },
    { key: "translations", label: "Languages", color: "#14b8a6" },
    { key: "decisions", label: "Decisions", color: "#f97316" }
  ];

  series.forEach(function(s) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.key === "total" ? 2.5 : 1.5;
    ctx.beginPath();
    points.forEach(function(p, i) {
      var val = p[s.key] || 0;
      var x = pad.left + (i / (points.length - 1)) * cW;
      var y = pad.top + cH - (val / maxVal) * cH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    /* Subtle fill only for total line */
    if (s.key === "total") {
      ctx.globalAlpha = 0.06;
      ctx.fillStyle = s.color;
      ctx.lineTo(pad.left + cW, pad.top + cH);
      ctx.lineTo(pad.left, pad.top + cH);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 1.0;
    }
  });

  /* Legend with latest values */
  var last = points[points.length - 1];
  ctx.font = "bold 11px 'IBM Plex Mono', monospace";
  ctx.textAlign = "right";
  var valX = W - pad.right;
  series.forEach(function(s, i) {
    var val = last[s.key] || 0;
    ctx.fillStyle = s.color;
    ctx.fillText(s.label + ": " + val.toLocaleString(), valX, pad.top + 14 + i * 15);
  });
}

/* ══════════════════════════════════════════════════════════════
   GITHUB REPOSITORY EXPLORER
   ══════════════════════════════════════════════════════════════ */

var _explorerRepoId = null;
var _explorerRepoName = "";

function openRepoExplorer(repoId, repoName) {
  _explorerRepoId = repoId;
  _explorerRepoName = repoName;

  // Hide repo list sections, show explorer
  var sections = ["ghOpsTerminal", "ghRepoGrid", "ghDiscoveryResults",
    document.querySelector(".gh-intake"),
    document.querySelector(".cs-gh-readouts"),
    document.querySelector(".gh-cards-header"),
    document.querySelector(".gh-discovery")];

  sections.forEach(function(el) {
    if (typeof el === "string") el = document.getElementById(el);
    if (el) el.style.display = "none";
  });

  var explorer = document.getElementById("ghRepoExplorer");
  if (explorer) explorer.style.display = "block";

  // Load tree and landing page
  loadRepoTree(repoId, "", document.getElementById("ghTreeRoot"));
  loadRepoLanding(repoId);
  updateBreadcrumbs(repoName, "");

  if (typeof lucide !== "undefined") lucide.createIcons();
}

function closeRepoExplorer() {
  var explorer = document.getElementById("ghRepoExplorer");
  if (explorer) explorer.style.display = "none";

  // Show all hidden sections
  var ids = ["ghOpsTerminal", "ghRepoGrid"];
  ids.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = "";
  });
  var selectors = [".gh-intake", ".cs-gh-readouts", ".gh-cards-header", ".gh-discovery"];
  selectors.forEach(function(sel) {
    var el = document.querySelector("#panel-github " + sel);
    if (el) el.style.display = "";
  });

  _explorerRepoId = null;
  _explorerRepoName = "";
}

function _formatFileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function loadRepoTree(repoId, path, parentEl) {
  if (!parentEl) return;
  parentEl.textContent = "";
  var loading = document.createElement("div");
  loading.className = "gh-tree-item";
  loading.style.color = "rgba(255,255,255,0.3)";
  loading.textContent = "Loading...";
  parentEl.appendChild(loading);

  api("/github/repo/" + repoId + "/tree?path=" + encodeURIComponent(path))
    .then(function(data) {
      parentEl.textContent = "";
      if (!data.success || !data.entries) {
        var errEl = document.createElement("div");
        errEl.className = "gh-tree-item";
        errEl.style.color = "#f87171";
        errEl.textContent = data.error || "Failed to load";
        parentEl.appendChild(errEl);
        return;
      }

      data.entries.forEach(function(entry) {
        var fullPath = path ? path + "/" + entry.name : entry.name;
        var item = document.createElement("div");
        item.className = "gh-tree-item " + entry.type;
        item.dataset.path = fullPath;

        var icon = document.createElement("span");
        icon.className = "gh-tree-icon";
        icon.textContent = entry.type === "dir" ? "\u25B8" : "\u00B7";
        item.appendChild(icon);

        var label = document.createElement("span");
        label.textContent = entry.name;
        item.appendChild(label);

        if (entry.type === "file" && entry.size != null) {
          var sz = document.createElement("span");
          sz.className = "gh-tree-size";
          sz.textContent = _formatFileSize(entry.size);
          item.appendChild(sz);
        }

        parentEl.appendChild(item);

        if (entry.type === "dir") {
          var children = document.createElement("div");
          children.className = "gh-tree-children";
          parentEl.appendChild(children);

          item.addEventListener("click", function(e) {
            e.stopPropagation();
            var expanded = children.classList.contains("expanded");
            if (expanded) {
              children.classList.remove("expanded");
              icon.textContent = "\u25B8";
            } else {
              children.classList.add("expanded");
              icon.textContent = "\u25BE";
              if (children.childElementCount === 0) {
                loadRepoTree(repoId, fullPath, children);
              }
            }
          });
        } else {
          item.addEventListener("click", function(e) {
            e.stopPropagation();
            // Highlight active
            var prev = document.querySelector(".gh-tree-item.active");
            if (prev) prev.classList.remove("active");
            item.classList.add("active");
            loadRepoFile(repoId, fullPath);
          });
        }
      });
    })
    .catch(function(err) {
      parentEl.textContent = "";
      var errEl = document.createElement("div");
      errEl.className = "gh-tree-item";
      errEl.style.color = "#f87171";
      errEl.textContent = "Error: " + err;
      parentEl.appendChild(errEl);
    });
}

function loadRepoFile(repoId, path) {
  var viewer = document.getElementById("ghFileViewer");
  var landing = document.getElementById("ghLanding");
  if (landing) landing.style.display = "none";
  if (viewer) viewer.style.display = "block";

  var header = document.getElementById("ghFileHeader");
  var codeEl = document.getElementById("ghFileCode");
  if (header) header.textContent = path;
  if (codeEl) codeEl.textContent = "Loading...";

  updateBreadcrumbs(_explorerRepoName, path);

  api("/github/repo/" + repoId + "/file?path=" + encodeURIComponent(path))
    .then(function(data) {
      if (!data.success) {
        if (codeEl) codeEl.textContent = data.error || "Failed to load file";
        return;
      }

      if (data.binary) {
        if (viewer) {
          var pre = viewer.querySelector(".gh-file-content");
          if (pre) pre.style.display = "none";
          var existing = viewer.querySelector(".gh-binary-msg");
          if (existing) existing.remove();
          var msg = document.createElement("div");
          msg.className = "gh-binary-msg";
          msg.textContent = "Binary file (" + _formatFileSize(data.size) + ")";
          viewer.appendChild(msg);
        }
        return;
      }

      // Remove binary message if present
      var binMsg = viewer ? viewer.querySelector(".gh-binary-msg") : null;
      if (binMsg) binMsg.remove();
      var pre = viewer ? viewer.querySelector(".gh-file-content") : null;
      if (pre) pre.style.display = "";

      var ext = path.split(".").pop().toLowerCase();
      if ((ext === "md" || ext === "markdown") && typeof marked !== "undefined") {
        // Render markdown in viewer pane instead of code block
        if (pre) pre.style.display = "none";
        var existing = viewer.querySelector(".gh-readme-rendered");
        if (existing) existing.remove();
        var mdDiv = document.createElement("div");
        mdDiv.className = "gh-readme-rendered gh-landing-readme";
        var body = document.createElement("div");
        body.className = "gh-readme-body";
        body.innerHTML = marked.parse(data.content);
        mdDiv.appendChild(body);
        viewer.appendChild(mdDiv);
        return;
      }

      // Remove rendered markdown if switching to code file
      var mdRender = viewer ? viewer.querySelector(".gh-readme-rendered") : null;
      if (mdRender) mdRender.remove();

      if (codeEl) {
        codeEl.textContent = data.content;
        codeEl.className = data.language ? "language-" + data.language : "";
        if (typeof hljs !== "undefined") {
          hljs.highlightElement(codeEl);
        }
      }

      if (data.truncated && header) {
        header.textContent = path + " (truncated — " + _formatFileSize(data.size) + ")";
      }
    })
    .catch(function(err) {
      if (codeEl) codeEl.textContent = "Error loading file: " + err;
    });
}

function loadRepoLanding(repoId) {
  var landing = document.getElementById("ghLanding");
  var viewer = document.getElementById("ghFileViewer");
  if (viewer) viewer.style.display = "none";
  if (!landing) return;
  landing.style.display = "block";
  landing.textContent = "";

  var loadingEl = document.createElement("div");
  loadingEl.style.cssText = "text-align:center; padding:40px; color:rgba(255,255,255,0.3);";
  loadingEl.textContent = "Loading repository...";
  landing.appendChild(loadingEl);

  api("/github/repo/" + repoId + "/readme")
    .then(function(data) {
      landing.textContent = "";
      if (!data.success) {
        landing.textContent = data.error || "Failed to load";
        return;
      }

      // Header
      var hdr = document.createElement("div");
      hdr.className = "gh-landing-header";
      var h2 = document.createElement("h2");
      h2.textContent = data.repo_name;
      hdr.appendChild(h2);
      if (data.repo_type) {
        var tag = document.createElement("span");
        tag.className = "gh-landing-type";
        tag.textContent = data.repo_type;
        hdr.appendChild(tag);
      }
      if (data.github_url) {
        var ghLink = document.createElement("a");
        ghLink.href = data.github_url;
        ghLink.target = "_blank";
        ghLink.textContent = "GitHub";
        ghLink.style.cssText = "margin-left:auto; font-size:0.75rem; color:#a78bfa; text-decoration:none; border:1px solid rgba(139,92,246,0.3); padding:4px 10px; border-radius:4px;";
        hdr.appendChild(ghLink);
      }
      landing.appendChild(hdr);

      // Description
      if (data.description) {
        var descEl = document.createElement("div");
        descEl.style.cssText = "font-size:0.82rem; color:rgba(255,255,255,0.6); margin-bottom:16px; line-height:1.5;";
        descEl.textContent = data.description;
        landing.appendChild(descEl);
      }

      // Stats
      if (data.stats) {
        var statsGrid = document.createElement("div");
        statsGrid.className = "gh-landing-stats";
        var statItems = [
          { value: (data.stats.files || 0).toLocaleString(), label: "Files" },
          { value: (data.stats.directories || 0).toLocaleString(), label: "Directories" },
          { value: _formatFileSize(data.stats.total_size || 0), label: "Total Size" }
        ];
        statItems.forEach(function(s) {
          var box = document.createElement("div");
          box.className = "gh-landing-stat";
          var val = document.createElement("div");
          val.className = "gh-landing-stat-value";
          val.textContent = s.value;
          box.appendChild(val);
          var lbl = document.createElement("div");
          lbl.className = "gh-landing-stat-label";
          lbl.textContent = s.label;
          box.appendChild(lbl);
          statsGrid.appendChild(box);
        });
        landing.appendChild(statsGrid);
      }

      // README
      if (data.readme) {
        var readmeBox = document.createElement("div");
        readmeBox.className = "gh-landing-readme";
        var readmeTitle = document.createElement("h3");
        readmeTitle.textContent = data.readme_file || "README";
        readmeBox.appendChild(readmeTitle);
        var readmeBody = document.createElement("div");
        readmeBody.className = "gh-readme-body";
        if (typeof marked !== "undefined") {
          readmeBody.innerHTML = marked.parse(data.readme);
        } else {
          readmeBody.textContent = data.readme;
        }
        readmeBox.appendChild(readmeBody);
        landing.appendChild(readmeBox);
      } else {
        var noReadme = document.createElement("div");
        noReadme.style.cssText = "text-align:center; padding:40px; color:rgba(255,255,255,0.25); font-size:0.85rem;";
        noReadme.textContent = "No README found in this repository";
        landing.appendChild(noReadme);
      }
    })
    .catch(function(err) {
      landing.textContent = "";
      var errEl = document.createElement("div");
      errEl.style.cssText = "text-align:center; padding:40px; color:#f87171;";
      errEl.textContent = "Error: " + err;
      landing.appendChild(errEl);
    });
}

function updateBreadcrumbs(repoName, path) {
  var bc = document.getElementById("ghBreadcrumbs");
  if (!bc) return;
  bc.textContent = "";

  // Repo name as root
  var root = document.createElement("span");
  root.className = "gh-bc-link";
  root.textContent = repoName.split("/").pop();
  root.addEventListener("click", function() {
    loadRepoLanding(_explorerRepoId);
    updateBreadcrumbs(repoName, "");
    var active = document.querySelector(".gh-tree-item.active");
    if (active) active.classList.remove("active");
  });
  bc.appendChild(root);

  if (!path) return;

  var parts = path.split("/");
  parts.forEach(function(part, i) {
    var sep = document.createElement("span");
    sep.className = "gh-bc-sep";
    sep.textContent = "/";
    bc.appendChild(sep);

    if (i === parts.length - 1) {
      var current = document.createElement("span");
      current.className = "gh-bc-current";
      current.textContent = part;
      bc.appendChild(current);
    } else {
      var link = document.createElement("span");
      link.className = "gh-bc-link";
      link.textContent = part;
      var dirPath = parts.slice(0, i + 1).join("/");
      link.addEventListener("click", (function(dp) {
        return function() {
          loadRepoTree(_explorerRepoId, dp, document.getElementById("ghTreeRoot"));
          updateBreadcrumbs(repoName, dp);
        };
      })(dirPath));
      bc.appendChild(link);
    }
  });
}


/* ══════════════════════════════════════════════════════════════
   CODE HEALTH TAB
   ══════════════════════════════════════════════════════════════ */

var _chModuleChart = null;
var _chHistoryChart = null;

function loadCodeHealth() {
  api("/api/code-health/current").then(function(d) {
    _renderCodeHealthStats(d);
    _renderModuleChart(d.modules || {});
    _renderModuleTable(d.modules || {});
    _renderOrphanTable(d.orphans || {});
  }).catch(function(err) {
    console.error("Code health load error:", err);
  });

  chLoadHistory();
  _loadAuditLog();
}

function _renderCodeHealthStats(d) {
  var fmt = function(n) { return (n || 0).toLocaleString(); };
  setHtml("chTotalFiles", fmt(d.total_files));
  setHtml("chTotalLines", fmt(d.total_lines));
  setHtml("chPythonLines", fmt(d.python ? d.python.lines : 0));
  setHtml("chJsLines", fmt(d.js ? d.js.lines : 0));
  setHtml("chHtmlLines", fmt(d.html ? d.html.lines : 0));
  setHtml("chCssLines", fmt(d.css ? d.css.lines : 0));
}

function _renderModuleChart(modules) {
  var canvas = document.getElementById("chModuleChart");
  if (!canvas) return;

  var names = Object.keys(modules).sort(function(a, b) {
    return (modules[b].lines || 0) - (modules[a].lines || 0);
  }).slice(0, 20);

  var pyData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.python ? bt.python.lines : 0; });
  var jsData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.js ? bt.js.lines : 0; });
  var htmlData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.html ? bt.html.lines : 0; });
  var cssData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.css ? bt.css.lines : 0; });

  var barHeight = Math.max(names.length * 26, 300);
  canvas.style.height = barHeight + "px";
  canvas.height = barHeight;

  if (_chModuleChart) _chModuleChart.destroy();
  _chModuleChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: names,
      datasets: [
        { label: "Python", data: pyData, backgroundColor: "rgba(139, 92, 246, 0.7)", borderWidth: 0, barThickness: 16 },
        { label: "HTML", data: htmlData, backgroundColor: "rgba(245, 158, 11, 0.7)", borderWidth: 0, barThickness: 16 },
        { label: "JavaScript", data: jsData, backgroundColor: "rgba(0, 204, 255, 0.7)", borderWidth: 0, barThickness: 16 },
        { label: "CSS", data: cssData, backgroundColor: "rgba(34, 197, 94, 0.7)", borderWidth: 0, barThickness: 16 }
      ]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      plugins: {
        legend: { labels: { color: "rgba(255,255,255,0.6)", boxWidth: 12, padding: 10 } }
      },
      scales: {
        x: { stacked: true, ticks: { color: "rgba(255,255,255,0.5)" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { stacked: true, ticks: { color: "rgba(255,255,255,0.7)", font: { size: 10 } }, grid: { display: false } }
      }
    }
  });
}

function _renderModuleTable(modules) {
  var el = document.getElementById("chModuleTable");
  if (!el) return;

  var sorted = Object.keys(modules).sort(function(a, b) {
    return (modules[b].lines || 0) - (modules[a].lines || 0);
  });

  var html = '<table class="cs-table"><thead><tr>' +
    '<th>Module</th><th class="center">Files</th><th class="center">Lines</th>' +
    '<th class="center">Python</th><th class="center">JS</th><th class="center">HTML</th><th class="center">CSS</th>' +
    '</tr></thead><tbody>';

  sorted.forEach(function(name) {
    var m = modules[name];
    var bt = m.by_type || {};
    html += '<tr>' +
      '<td>' + escHtml(name) + '</td>' +
      '<td class="center">' + (m.files || 0) + '</td>' +
      '<td class="center"><strong>' + (m.lines || 0).toLocaleString() + '</strong></td>' +
      '<td class="center">' + (bt.python ? bt.python.lines : 0).toLocaleString() + '</td>' +
      '<td class="center">' + (bt.js ? bt.js.lines : 0).toLocaleString() + '</td>' +
      '<td class="center">' + (bt.html ? bt.html.lines : 0).toLocaleString() + '</td>' +
      '<td class="center">' + (bt.css ? bt.css.lines : 0).toLocaleString() + '</td>' +
      '</tr>';
  });

  html += '</tbody></table>';
  setHtml(el, html);
}

function _renderOrphanTable(orphans) {
  var el = document.getElementById("chOrphanTable");
  if (!el) return;

  var all = [];
  (orphans.templates || []).forEach(function(o) { all.push({type: "HTML", file: o.file, lines: o.lines}); });
  (orphans.js || []).forEach(function(o) { all.push({type: "JS", file: o.file, lines: o.lines}); });
  (orphans.css || []).forEach(function(o) { all.push({type: "CSS", file: o.file, lines: o.lines}); });

  if (!all.length) {
    setHtml(el, '<div class="cs-empty" style="color:#22c55e;">All files mapped to modules — no orphans found.</div>');
    return;
  }

  var html = '<table class="cs-table"><thead><tr>' +
    '<th>Type</th><th>File</th><th class="center">Lines</th>' +
    '</tr></thead><tbody>';
  all.forEach(function(o) {
    html += '<tr>' +
      '<td><span class="cs-badge amber">' + o.type + '</span></td>' +
      '<td>' + escHtml(o.file) + '</td>' +
      '<td class="center">' + (o.lines || 0).toLocaleString() + '</td>' +
      '</tr>';
  });
  html += '</tbody></table>';
  setHtml(el, html);
}

window.chRunScan = function() {
  api("/api/code-health/scan", "POST").then(function(d) {
    if (d.success) {
      _renderCodeHealthStats(d.metrics);
      _renderModuleChart(d.metrics.modules || {});
      _renderModuleTable(d.metrics.modules || {});
      chLoadHistory();
    }
  }).catch(function(err) {
    console.error("Scan failed:", err);
  });
};

window.chBackfillGit = function() {
  if (typeof toast !== "undefined") toast("Building lifetime tracker...");
  api("/api/code-health/backfill-git", "POST", {}).then(function(d) {
    if (d.success) {
      if (typeof toast !== "undefined") toast("Tracked " + (d.days || 0) + " days of history");
      _cache.codehealth = false;
      loadCodeHealth();
    } else {
      if (typeof toast !== "undefined") toast("Failed: " + (d.error || ""), true);
    }
  }).catch(function(err) {
    if (typeof toast !== "undefined") toast("Error: " + err.message, true);
  });
};

window.chLoadHistory = function() {
  api("/api/code-health/snapshots").then(function(d) {
    var snaps = (d.snapshots || []).reverse();
    _renderHistoryChart(snaps);
  }).catch(function() {});
};

function _renderHistoryChart(snapshots) {
  var canvas = document.getElementById("chHistoryChart");
  if (!canvas || !snapshots.length) return;

  var labels = snapshots.map(function(s) {
    var d = new Date(s.scanned_at);
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  });

  canvas.style.height = "380px";
  canvas.height = 380;

  if (_chHistoryChart) _chHistoryChart.destroy();
  _chHistoryChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Total Lines",
          data: snapshots.map(function(s) { return s.total_lines; }),
          borderColor: "#8b5cf6",
          backgroundColor: "rgba(139, 92, 246, 0.1)",
          fill: true,
          tension: 0.3
        },
        {
          label: "Total Files",
          data: snapshots.map(function(s) { return s.total_files; }),
          borderColor: "#0cf",
          backgroundColor: "rgba(0, 204, 255, 0.1)",
          fill: true,
          tension: 0.3,
          yAxisID: "y1"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      plugins: { legend: { labels: { color: "rgba(255,255,255,0.6)" } } },
      scales: {
        x: { ticks: { color: "rgba(255,255,255,0.5)", maxRotation: 45 }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { position: "left", ticks: { color: "#8b5cf6" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y1: { position: "right", ticks: { color: "#0cf" }, grid: { display: false } }
      }
    }
  });
}

function _loadAuditLog() {
  api("/api/code-health/audit-log").then(function(d) {
    var entries = d.entries || [];
    var el = document.getElementById("chAuditTable");
    if (!el) return;

    if (!entries.length) {
      setHtml(el, '<div class="cs-empty">No audit entries yet. Start auditing modules to see progress here.</div>');
      return;
    }

    var html = '<table class="cs-table"><thead><tr>' +
      '<th>Module</th><th>Category</th><th class="center">Files</th>' +
      '<th class="center">Before</th><th class="center">After</th><th class="center">\u0394</th>' +
      '<th class="center">Issues</th><th class="center">Fixed</th><th>Status</th><th>Date</th>' +
      '</tr></thead><tbody>';

    entries.forEach(function(e) {
      var delta = (e.lines_after || 0) - (e.lines_before || 0);
      var deltaClass = delta > 0 ? "color:#22c55e" : delta < 0 ? "color:#ef4444" : "";
      var statusClass = e.status === "completed" ? "green" : e.status === "in_progress" ? "amber" : "";
      html += '<tr>' +
        '<td>' + escHtml(e.module_name) + '</td>' +
        '<td style="font-size:0.75rem; color:rgba(255,255,255,0.4);">' + escHtml(e.category || "") + '</td>' +
        '<td class="center">' + (e.files_reviewed || 0) + '</td>' +
        '<td class="center">' + (e.lines_before || 0).toLocaleString() + '</td>' +
        '<td class="center">' + (e.lines_after || 0).toLocaleString() + '</td>' +
        '<td class="center" style="' + deltaClass + ';">' + (delta > 0 ? "+" : "") + delta.toLocaleString() + '</td>' +
        '<td class="center">' + (e.issues_found || 0) + '</td>' +
        '<td class="center">' + (e.issues_fixed || 0) + '</td>' +
        '<td><span class="cs-badge ' + statusClass + '">' + escHtml(e.status || "pending") + '</span></td>' +
        '<td style="font-size:0.75rem; white-space:nowrap;">' + formatAge(e.audited_at) + '</td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    setHtml(el, html);
  }).catch(function() {});
}
