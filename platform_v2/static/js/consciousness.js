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

  // Load Brain Map
  loadBrainMap();

  // Load Emotional Timeline
  loadEmotionalTimeline();
}

/* ── Brain Map ────────────────────────────────────── */

var _brainMapColors = [
  "rgba(139,92,246,0.6)", "rgba(59,130,246,0.6)", "rgba(34,197,94,0.6)",
  "rgba(245,158,11,0.6)", "rgba(236,72,153,0.6)", "rgba(6,182,212,0.6)",
  "rgba(168,85,247,0.6)", "rgba(249,115,22,0.6)", "rgba(20,184,166,0.6)",
  "rgba(99,102,241,0.6)", "rgba(244,63,94,0.6)", "rgba(132,204,22,0.6)"
];

function loadBrainMap() {
  api("/brain-map/data").then(function(data) {
    if (!data.regions || !data.regions.length) {
      setHtml("brainMapContainer", '<div class="cs-empty">No brain map data</div>');
      return;
    }

    var total = 0;
    data.regions.forEach(function(r) { total += r.count || 0; });

    var html = '<div class="cs-brain-treemap">';
    data.regions.forEach(function(r, i) {
      var pct = total > 0 ? Math.max(((r.count || 0) / total) * 100, 8) : 10;
      var color = _brainMapColors[i % _brainMapColors.length];
      var growthStr = r.growth_7d ? "+" + r.growth_7d + " (7d)" : "";
      html += '<div class="cs-brain-region" style="flex:' + Math.max(pct / 10, 1).toFixed(1) + '; background:' + color + ';" title="' + escHtml(r.label || r.type) + ': ' + (r.count || 0) + ' entries">' +
        '<div class="cs-brain-region-label">' + escHtml(r.label || r.type) + '</div>' +
        '<div class="cs-brain-region-count">' + (r.count || 0) + '</div>' +
        (growthStr ? '<div class="cs-brain-region-growth">' + growthStr + '</div>' : '') +
        '</div>';
    });
    html += '</div>';

    // Connections
    if (data.connections && data.connections.length) {
      html += '<div class="cs-brain-connections">';
      data.connections.slice(0, 8).forEach(function(c) {
        html += '<span class="cs-brain-conn">' + escHtml(c.source) + ' \u2194 ' + escHtml(c.target) +
          ' (' + (c.strength ? c.strength.toFixed(2) : '?') + ')</span>';
      });
      html += '</div>';
    }

    // Summary stats
    if (data.stats) {
      html += '<div style="margin-top:10px; font-size:0.72rem; color:rgba(255,255,255,0.4);">' +
        'Total: ' + (data.stats.total || 0) + ' | Embedded: ' + (data.stats.embedded || 0) +
        ' | Types: ' + (data.stats.types || 0) +
        (data.stats.growth_7d ? ' | Growth: +' + data.stats.growth_7d + ' (7d)' : '') +
        '</div>';
    }

    setHtml("brainMapContainer", html);
  }).catch(function(err) {
    console.error("loadBrainMap error:", err);
    setHtml("brainMapContainer", '<div class="cs-empty">Brain map unavailable</div>');
  });
}

/* ── Emotional Timeline ──────────────────────────── */

var _emotionalChart = null;

function loadEmotionalTimeline() {
  api("/emotions/timeline?days=30").then(function(data) {
    if (!data.timeline || !data.timeline.length) {
      var canvas = document.getElementById("emotionalChart");
      if (canvas) canvas.parentElement.innerHTML = '<div class="cs-empty" style="padding-top:80px;">No emotional data available</div>';
      return;
    }

    var labels = [];
    var moodScores = [];
    var energyScores = [];
    var stressScores = [];

    data.timeline.forEach(function(entry) {
      labels.push(entry.date || "");
      moodScores.push(parseFloat(entry.avg_mood_score || 0).toFixed(2));
      energyScores.push(parseFloat(entry.avg_energy || 0).toFixed(2));
      stressScores.push(parseFloat(entry.avg_stress || 0).toFixed(2));
    });

    var ctx = document.getElementById("emotionalChart");
    if (!ctx) return;

    if (_emotionalChart) _emotionalChart.destroy();
    _emotionalChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Mood",
            data: moodScores,
            borderColor: "#8b5cf6",
            backgroundColor: "rgba(139,92,246,0.1)",
            fill: true,
            tension: 0.3,
            pointRadius: 2
          },
          {
            label: "Energy",
            data: energyScores,
            borderColor: "#22c55e",
            backgroundColor: "rgba(34,197,94,0.05)",
            fill: false,
            tension: 0.3,
            pointRadius: 2
          },
          {
            label: "Stress",
            data: stressScores,
            borderColor: "#ef4444",
            backgroundColor: "rgba(239,68,68,0.05)",
            fill: false,
            tension: 0.3,
            pointRadius: 2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "rgba(255,255,255,0.6)", font: { size: 11 } } }
        },
        scales: {
          x: {
            ticks: { color: "rgba(255,255,255,0.3)", font: { size: 10 }, maxTicksLimit: 8 },
            grid: { color: "rgba(255,255,255,0.04)" }
          },
          y: {
            min: 0, max: 1,
            ticks: { color: "rgba(255,255,255,0.3)", font: { size: 10 } },
            grid: { color: "rgba(255,255,255,0.04)" }
          }
        }
      }
    });
  }).catch(function(err) {
    console.error("loadEmotionalTimeline error:", err);
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
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr>' +
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
    html += '</tbody></table></div>';
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

/* ── Processing Controls ──────────────────────────── */

/* ── Bridge Job Progress Poller ─────────────────────── */

function _renderJobProgress(data, el) {
  var job = data.job;
  var pct = job.total_steps > 0 ? Math.round((job.completed_steps / job.total_steps) * 100) : 0;
  var barColor = job.status === "completed" ? "#22c55e" : job.status === "failed" ? "#ef4444" : "#8b5cf6";
  var statusIcon = job.status === "completed" ? "\u2713" : job.status === "failed" ? "\u2717" : "\u25B6";
  var agentLabel = job.agent_display || job.agent_name || "Unassigned";

  var html = '<div class="cs-pipeline-step" style="flex-direction:column;align-items:stretch;gap:8px">' +
    '<div style="display:flex;justify-content:space-between;align-items:center">' +
      '<span><span class="cs-pipeline-icon" style="color:' + barColor + '">' + statusIcon + '</span> ' +
        escHtml(job.description) + '</span>' +
      '<span class="cs-badge blue">' + escHtml(agentLabel) + '</span>' +
    '</div>' +
    '<div style="background:rgba(255,255,255,0.08);border-radius:6px;height:8px;overflow:hidden">' +
      '<div style="width:' + pct + '%;height:100%;background:' + barColor + ';transition:width 0.5s ease"></div>' +
    '</div>' +
    '<div style="display:flex;justify-content:space-between;font-size:0.82rem;opacity:0.7">' +
      '<span>' + job.completed_steps + ' / ' + job.total_steps + ' steps' +
        (job.failed_steps > 0 ? ' (' + job.failed_steps + ' failed)' : '') + '</span>' +
      '<span>' + pct + '%</span>' +
    '</div>' +
  '</div>';
  setHtml(el, html);
}

function _pollJobStatus(jobId, el, onComplete) {
  var poll = setInterval(function() {
    api("/api/processing/job-status/" + jobId).then(function(data) {
      if (!data.success) { clearInterval(poll); return; }
      _renderJobProgress(data, el);
      if (data.job.status === "completed" || data.job.status === "failed" || data.job.status === "cancelled") {
        clearInterval(poll);
        if (onComplete) onComplete(data.job);
      }
    }).catch(function() { clearInterval(poll); });
  }, 2000);
}

window.startAnalysis = function() {
  var btn = document.getElementById("btnStartAnalysis");
  var btn2 = document.getElementById("btnGenerateEmbed");
  if (btn) btn.disabled = true;
  if (btn2) btn2.disabled = true;
  var cat = document.getElementById("procCategory");
  var batch = document.getElementById("procBatchSize");
  setHtml("procResult", '<div class="cs-loading">Creating Bridge job\u2026</div>');

  api("/api/processing/start", {
    method: "POST",
    body: {
      category: cat ? cat.value : "conversations",
      batch_size: batch ? parseInt(batch.value) : 10
    }
  }).then(function(data) {
    if (data.success && data.job_id) {
      /* Job created — poll for progress */
      _pollJobStatus(data.job_id, "procResult", function() {
        if (btn) btn.disabled = false;
        if (btn2) btn2.disabled = false;
        loadProcessingStatus();
      });
    } else if (data.success) {
      /* Completed synchronously (e.g. no items to process) */
      var html = '<div class="cs-pipeline-step green">' +
        '<span class="cs-pipeline-icon">\u2713</span>' +
        '<span>' + escHtml(data.message || "Processed " + (data.processed || 0) + " items") + '</span>' +
        '</div>';
      setHtml("procResult", html);
      if (btn) btn.disabled = false;
      if (btn2) btn2.disabled = false;
      loadProcessingStatus();
    } else {
      setHtml("procResult", '<div class="cs-pipeline-step red"><span class="cs-pipeline-icon">\u2717</span><span>' + escHtml(data.error || "Processing failed") + '</span></div>');
      if (btn) btn.disabled = false;
      if (btn2) btn2.disabled = false;
    }
  }).catch(function(err) {
    setHtml("procResult", '<div class="cs-pipeline-step red"><span class="cs-pipeline-icon">\u2717</span><span>Error: ' + escHtml(err.message || "Request failed") + '</span></div>');
    if (btn) btn.disabled = false;
    if (btn2) btn2.disabled = false;
  });
};

window.generateEmbeddings = function() {
  var btn = document.getElementById("btnGenerateEmbed");
  var btn2 = document.getElementById("btnStartAnalysis");
  if (btn) btn.disabled = true;
  if (btn2) btn2.disabled = true;
  var batch = document.getElementById("procBatchSize");
  setHtml("procResult", '<div class="cs-loading">Creating Bridge job\u2026</div>');

  api("/api/processing/generate-embeddings", {
    method: "POST",
    body: { batch_size: batch ? parseInt(batch.value) : 50 }
  }).then(function(data) {
    if (data.success && data.job_id) {
      /* Job created — poll for progress */
      _pollJobStatus(data.job_id, "procResult", function() {
        if (btn) btn.disabled = false;
        if (btn2) btn2.disabled = false;
        loadEmbeddingStatus();
      });
    } else if (data.success) {
      var html = '<div class="cs-pipeline-step green">' +
        '<span class="cs-pipeline-icon">\u2713</span>' +
        '<span>' + escHtml(data.message || "Generated " + (data.processed || 0) + " / " + (data.total || 0) + " embeddings") + '</span>' +
        '</div>';
      setHtml("procResult", html);
      if (btn) btn.disabled = false;
      if (btn2) btn2.disabled = false;
      loadEmbeddingStatus();
    } else {
      setHtml("procResult", '<div class="cs-pipeline-step red"><span class="cs-pipeline-icon">\u2717</span><span>' + escHtml(data.error || "Embedding generation failed") + '</span></div>');
      if (btn) btn.disabled = false;
      if (btn2) btn2.disabled = false;
    }
  }).catch(function(err) {
    setHtml("procResult", '<div class="cs-pipeline-step red"><span class="cs-pipeline-icon">\u2717</span><span>Error: ' + escHtml(err.message || "Request failed") + '</span></div>');
    if (btn) btn.disabled = false;
    if (btn2) btn2.disabled = false;
  });
};

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
      html += '<a href="/tools/bridge#stations" class="cs-link">View in Bridge Command \u2192</a>';
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

/* ── Team Sub-tabs ────────────────────────────────── */

window.switchTeamSubtab = function(sub) {
  document.querySelectorAll("#panel-team .cs-subtab").forEach(function(b) {
    b.classList.toggle("active", b.textContent.toLowerCase().replace(/ /g, "") === sub ||
      (sub === "roster" && b.textContent === "Roster") ||
      (sub === "voice" && b.textContent === "Voice Profiles") ||
      (sub === "emotions" && b.textContent === "Emotional State"));
  });
  document.querySelectorAll("#panel-team .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "team-" + sub);
  });
  if (sub === "voice") loadVoiceProfiles();
  if (sub === "emotions") loadEmotionalDetail();
};

function loadVoiceProfiles() {
  api("/api/voice/profiles").then(function(data) {
    if (!data.success || !data.profiles || !data.profiles.length) {
      setHtml("voiceProfileGrid", '<div class="cs-empty">No voice profiles configured</div>');
      return;
    }
    var html = '<div class="cs-voice-grid">';
    data.profiles.forEach(function(p) {
      html += '<div class="cs-voice-card">' +
        '<div class="cs-voice-header">' +
          '<div class="cs-agent-avatar" style="width:36px;height:36px;font-size:0.85rem;">' + escHtml((p.agent_first_name || p.agent_name || "?")[0]) + '</div>' +
          '<div>' +
            '<div class="cs-agent-name" style="font-size:0.85rem;">' + escHtml(p.agent_name || p.agent_first_name || "Agent #" + p.agent_id) + '</div>' +
            '<div class="cs-voice-engine">' + escHtml(p.engine || "xtts_v2") + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="cs-voice-detail">Language: ' + escHtml(p.language || "en") + '</div>' +
        '<div class="cs-voice-detail">Profile: ' + escHtml(p.profile_name || "Default") + '</div>' +
        '<div class="cs-voice-detail">Speaker: ' + escHtml(p.speaker_id || "\u2014") + '</div>' +
        '<div style="display:flex; gap:8px; margin-top:8px;">' +
          '<span class="cs-badge blue">' + (p.cached_words || 0) + ' cached</span>' +
          '<span class="cs-badge purple">' + (p.locked_words || 0) + ' locked</span>' +
        '</div>' +
        (p.speed ? '<div class="cs-voice-detail" style="margin-top:6px;">Speed: ' + p.speed + 'x | Pitch: ' + (p.pitch_shift || 0) + '</div>' : '') +
        '</div>';
    });
    html += '</div>';
    setHtml("voiceProfileGrid", html);
  }).catch(function(err) {
    console.error("loadVoiceProfiles error:", err);
    setHtml("voiceProfileGrid", '<div class="cs-empty">Error loading voice profiles</div>');
  });
}

var _emotionalDetailChart = null;

function loadEmotionalDetail() {
  api("/emotions/timeline?days=30").then(function(data) {
    // Update current mood badge
    if (data.current_state) {
      var badge = document.getElementById("currentMoodBadge");
      if (badge) {
        badge.textContent = data.current_state.mood || "unknown";
        badge.className = "cs-badge purple";
      }
    }

    if (!data.timeline || !data.timeline.length) {
      var canvas = document.getElementById("emotionalDetailChart");
      if (canvas) canvas.parentElement.innerHTML = '<div class="cs-empty" style="padding-top:100px;">No emotional data available</div>';
      return;
    }

    var labels = [];
    var moodScores = [];
    var energyScores = [];
    var stressScores = [];
    var moodLabels = [];

    data.timeline.forEach(function(entry) {
      labels.push(entry.date || "");
      moodScores.push(parseFloat(entry.avg_mood_score || 0).toFixed(2));
      energyScores.push(parseFloat(entry.avg_energy || 0).toFixed(2));
      stressScores.push(parseFloat(entry.avg_stress || 0).toFixed(2));
      moodLabels.push(entry.dominant_mood || "");
    });

    var ctx = document.getElementById("emotionalDetailChart");
    if (!ctx) return;

    if (_emotionalDetailChart) _emotionalDetailChart.destroy();
    _emotionalDetailChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Mood Score",
            data: moodScores,
            borderColor: "#8b5cf6",
            backgroundColor: "rgba(139,92,246,0.15)",
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointHoverRadius: 6
          },
          {
            label: "Energy",
            data: energyScores,
            borderColor: "#22c55e",
            backgroundColor: "rgba(34,197,94,0.05)",
            fill: false,
            tension: 0.4,
            pointRadius: 2
          },
          {
            label: "Stress",
            data: stressScores,
            borderColor: "#ef4444",
            backgroundColor: "rgba(239,68,68,0.05)",
            fill: false,
            tension: 0.4,
            pointRadius: 2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "rgba(255,255,255,0.6)", font: { size: 11 } } },
          tooltip: {
            callbacks: {
              afterLabel: function(ctx) {
                return ctx.datasetIndex === 0 ? "Mood: " + (moodLabels[ctx.dataIndex] || "") : "";
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { color: "rgba(255,255,255,0.3)", font: { size: 10 }, maxTicksLimit: 10 },
            grid: { color: "rgba(255,255,255,0.04)" }
          },
          y: {
            min: 0, max: 1,
            ticks: { color: "rgba(255,255,255,0.3)", font: { size: 10 } },
            grid: { color: "rgba(255,255,255,0.04)" }
          }
        }
      }
    });
  }).catch(function(err) {
    console.error("loadEmotionalDetail error:", err);
  });
}

/* ── Insights Tab ──────────────────────────────────── */

window.switchInsightsSubtab = function(sub) {
  document.querySelectorAll("#panel-insights .cs-subtab").forEach(function(b) {
    b.classList.toggle("active", b.textContent.toLowerCase() === sub);
  });
  document.querySelectorAll("#panel-insights .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "insights-" + sub);
  });
  if (sub === "sessions") loadSessions();
  if (sub === "improvements") loadImprovements();
};

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

function loadSessions() {
  api("/sessions").then(function(data) {
    var sessions = data.sessions || [];
    if (!sessions.length) {
      setHtml("sessionsList", '<div class="cs-empty">No sessions found</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr><th>Session</th><th>Topic</th><th>Status</th><th>Started</th></tr></thead><tbody>';
    sessions.slice(0, 20).forEach(function(s) {
      html += '<tr><td>' + escHtml(s.session_name || s.primary_topic || "Session #" + s.id) + '</td>' +
        '<td>' + escHtml(s.primary_topic || "\u2014") + '</td>' +
        '<td><span class="cs-badge">' + escHtml(s.processing_status || "\u2014") + '</span></td>' +
        '<td>' + formatAge(s.started_at || s.compact_triggered_at) + '</td></tr>';
    });
    html += '</tbody></table></div>';
    setHtml("sessionsList", html);
  }).catch(function() {
    setHtml("sessionsList", '<div class="cs-empty">Sessions unavailable</div>');
  });
}

function loadImprovements() {
  api("/improvements").then(function(data) {
    var items = data.improvements || data.proposals || [];
    if (!items.length) {
      setHtml("improvementsList", '<div class="cs-empty">No improvement proposals</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr><th>Title</th><th>Type</th><th>Importance</th><th>Created</th></tr></thead><tbody>';
    items.slice(0, 20).forEach(function(p) {
      html += '<tr><td>' + escHtml(p.title || p.description || "Proposal") + '</td>' +
        '<td><span class="cs-badge">' + escHtml(p.knowledge_type || "\u2014") + '</span></td>' +
        '<td>' + (p.importance_score ? p.importance_score.toFixed(2) : "\u2014") + '</td>' +
        '<td>' + formatAge(p.created_at) + '</td></tr>';
    });
    html += '</tbody></table></div>';
    setHtml("improvementsList", html);
  }).catch(function() {
    setHtml("improvementsList", '<div class="cs-empty">Improvements unavailable</div>');
  });
}

/* ── Languages Tab ─────────────────────────────────── */

window.switchLangSubtab = function(sub) {
  document.querySelectorAll("#panel-languages .cs-subtab").forEach(function(b) {
    b.classList.toggle("active", b.textContent.toLowerCase() === sub);
  });
  document.querySelectorAll("#panel-languages .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "lang-" + sub);
  });
  if (sub === "browser") loadLangBrowser();
  if (sub === "review") loadLangReview();
  if (sub === "glossary") loadLangGlossary();
};

function loadLanguages() {
  // Load dashboard stats — aggregate across all languages
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
    setHtml("langTotalKeys", totalKeys);
    setHtml("langApproved", totalApproved);
    setHtml("langPending", totalPending);
  }).catch(function() {});

  // Module coverage
  api("/api/translations/module-coverage").then(function(data) {
    var modules = data.modules || data.coverage || [];
    if (!modules.length) {
      setHtml("langCoverageGrid", '<div class="cs-empty">No coverage data</div>');
      return;
    }
    var html = '<div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap:12px;">';
    modules.forEach(function(m) {
      var pct = m.coverage_pct || m.percentage || 0;
      var color = pct >= 90 ? "green" : pct >= 50 ? "amber" : "red";
      html += '<div class="cs-card" style="padding:12px;">' +
        '<div style="font-weight:600; color:#fff; font-size:0.85rem;">' + escHtml(m.module || m.name) + '</div>' +
        '<div style="font-size:0.78rem; color:rgba(255,255,255,0.4);">' +
          '<span class="cs-badge ' + color + '">' + pct + '%</span> ' +
          (m.translated || 0) + '/' + (m.total || 0) +
        '</div></div>';
    });
    html += '</div>';
    setHtml("langCoverageGrid", html);
  }).catch(function() {
    setHtml("langCoverageGrid", '<div class="cs-empty">Coverage data unavailable</div>');
  });
}

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
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr><th>Key</th><th>English</th><th>Translation</th><th>Status</th></tr></thead><tbody>';
    items.slice(0, 50).forEach(function(t) {
      html += '<tr><td>' + escHtml(t.key) + '</td>' +
        '<td style="max-width:200px; overflow:hidden; text-overflow:ellipsis;">' + escHtml(t.english || "\u2014") + '</td>' +
        '<td style="max-width:200px; overflow:hidden; text-overflow:ellipsis;">' + escHtml(t.target || "\u2014") + '</td>' +
        '<td><span class="cs-badge">' + escHtml(t.status || "\u2014") + '</span></td></tr>';
    });
    html += '</tbody></table></div>';
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
      setHtml("langReviewList", '<div class="cs-empty">No pending reviews</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr><th>Key</th><th>Language</th><th>Text</th><th>Generated By</th></tr></thead><tbody>';
    items.slice(0, 30).forEach(function(t) {
      html += '<tr><td>' + escHtml(t.key) + '</td>' +
        '<td>' + escHtml(t.language) + '</td>' +
        '<td style="max-width:300px; overflow:hidden; text-overflow:ellipsis;">' + escHtml(t.text || "\u2014") + '</td>' +
        '<td>' + escHtml(t.generated_by || "\u2014") + '</td></tr>';
    });
    html += '</tbody></table></div>';
    setHtml("langReviewList", html);
  }).catch(function() {
    setHtml("langReviewList", '<div class="cs-empty">Review data unavailable</div>');
  });
}

function loadLangGlossary() {
  api("/api/translation-memory?language=fr").then(function(data) {
    var items = data.entries || data.glossary || [];
    if (!items.length) {
      setHtml("langGlossaryList", '<div class="cs-empty">No glossary entries</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr><th>Source</th><th>Translation</th><th>Language</th><th>Category</th></tr></thead><tbody>';
    items.forEach(function(g) {
      html += '<tr><td>' + escHtml(g.source_text) + '</td>' +
        '<td>' + escHtml(g.translated_text) + '</td>' +
        '<td>' + escHtml(g.language) + '</td>' +
        '<td>' + escHtml(g.category || "\u2014") + '</td></tr>';
    });
    html += '</tbody></table></div>';
    setHtml("langGlossaryList", html);
  }).catch(function() {
    setHtml("langGlossaryList", '<div class="cs-empty">Glossary unavailable</div>');
  });
}

/* ── GitHub Tab ────────────────────────────────────── */

window.switchGithubSubtab = function(sub) {
  document.querySelectorAll("#panel-github .cs-subtab").forEach(function(b) {
    b.classList.toggle("active", b.textContent.toLowerCase() === sub);
  });
  document.querySelectorAll("#panel-github .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "gh-" + sub);
  });
};

function loadGitHub() {
  api("/api/github/repos").then(function(data) {
    if (!data.success) return;
    var repos = data.repos || [];

    // Update stats
    var totalFiles = 0;
    repos.forEach(function(r) { totalFiles += r.indexed_files || 0; });
    setHtml("ghRepoCount", repos.length);
    setHtml("ghFileCount", totalFiles);

    if (!repos.length) {
      setHtml("ghRepoGrid", '<div class="cs-empty">No repositories indexed</div>');
      return;
    }
    var html = '<div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:16px;">';
    repos.forEach(function(r) {
      var statusColor = r.indexed ? "green" : "amber";
      html += '<div class="cs-card" style="padding:16px;">' +
        '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">' +
          '<div style="font-weight:600; color:#fff; font-size:0.85rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px;" title="' + escHtml(r.repo_name) + '">' + escHtml(r.repo_name) + '</div>' +
          '<span class="cs-badge ' + statusColor + '">' + (r.indexed ? 'Indexed' : 'Pending') + '</span>' +
        '</div>' +
        '<div style="font-size:0.78rem; color:rgba(255,255,255,0.4); margin-bottom:8px;">' +
          '<div>' + (r.indexed_files || 0) + ' files indexed</div>' +
          '<div>Type: ' + escHtml(r.repo_type || "\u2014") + '</div>' +
          (r.indexed_at ? '<div>Last indexed: ' + formatAge(r.indexed_at) + '</div>' : '') +
        '</div>' +
        '<div style="display:flex; gap:6px;">' +
          '<button onclick="reindexRepo(' + r.id + ')" style="padding:4px 10px; background:rgba(139,92,246,0.15); border:1px solid rgba(139,92,246,0.3); border-radius:4px; color:#8b5cf6; cursor:pointer; font-size:0.72rem;">Re-index</button>' +
          '<a href="https://github.com/' + escHtml(r.repo_name) + '" target="_blank" style="padding:4px 10px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:4px; color:rgba(255,255,255,0.5); text-decoration:none; font-size:0.72rem;">GitHub \u2197</a>' +
        '</div>' +
        '</div>';
    });
    html += '</div>';
    setHtml("ghRepoGrid", html);

    // Fetch embedding stats
    loadGitHubEmbedStats();
  }).catch(function(err) {
    console.error("loadGitHub error:", err);
    setHtml("ghRepoGrid", '<div class="cs-empty">Error loading repos</div>');
  });
}

function loadGitHubEmbedStats() {
  api("/processing/embedding-coverage").then(function(data) {
    if (data.coverage_pct !== undefined) {
      setHtml("ghEmbedPct", data.coverage_pct + "%");
      setHtml("ghSearchable", (data.embedded || 0).toLocaleString());
    }
  }).catch(function() {});
}

/* ── GitHub Repo Management ──────────────────────── */

window.showAddRepoModal = function() {
  var overlay = document.getElementById("addRepoOverlay");
  if (overlay) overlay.classList.add("open");
};

window.closeAddRepoModal = function() {
  var overlay = document.getElementById("addRepoOverlay");
  if (overlay) overlay.classList.remove("open");
};

window.addRepo = function() {
  var url = document.getElementById("addRepoUrl").value.trim();
  var type = document.getElementById("addRepoType").value.trim();
  var maxFiles = document.getElementById("addRepoMax").value;

  if (!url) return;

  var btn = document.querySelector("#addRepoOverlay .btn-submit");
  if (btn) btn.disabled = true;
  setHtml("addRepoResult", '<div class="cs-loading">Indexing repository... This may take a minute.</div>');

  var body = { repo_url: url, priority: "high" };
  if (maxFiles) body.max_files = parseInt(maxFiles);

  api("/github/index-selective", { method: "POST", body: body }).then(function(data) {
    if (data.success) {
      setHtml("addRepoResult", '<div class="cs-pipeline-step green"><span class="cs-pipeline-icon">\u2713</span><span>Indexed ' + (data.indexed || data.count || 0) + ' files from ' + escHtml(data.repo || url) + '</span></div>');
      _cache.github = false;
      loadGitHub();
      setTimeout(closeAddRepoModal, 2000);
    } else {
      setHtml("addRepoResult", '<div class="cs-pipeline-step red"><span class="cs-pipeline-icon">\u2717</span><span>' + escHtml(data.error || "Failed to index") + '</span></div>');
    }
    if (btn) btn.disabled = false;
  }).catch(function(err) {
    setHtml("addRepoResult", '<div class="cs-pipeline-step red"><span class="cs-pipeline-icon">\u2717</span><span>' + escHtml(err.message || "Request failed") + '</span></div>');
    if (btn) btn.disabled = false;
  });
};

window.reindexRepo = function(repoId) {
  setHtml("ghActionResult", '<span class="cs-loading" style="padding:0;">Re-indexing repo #' + repoId + '...</span>');
  api("/github/reindex/" + repoId, { method: "POST" }).then(function(data) {
    if (data.success) {
      setHtml("ghActionResult", '<span style="color:#4ade80;">\u2713 Re-indexed ' + (data.indexed || 0) + ' files</span>');
      _cache.github = false;
      loadGitHub();
    } else {
      setHtml("ghActionResult", '<span style="color:#f87171;">\u2717 ' + escHtml(data.error || "Failed") + '</span>');
    }
  }).catch(function(err) {
    setHtml("ghActionResult", '<span style="color:#f87171;">\u2717 ' + escHtml(err.message || "Error") + '</span>');
  });
};

window.reindexAllRepos = function() {
  var btn = document.getElementById("btnReindexAll");
  if (btn) btn.disabled = true;
  setHtml("ghActionResult", '<span class="cs-loading" style="padding:0;">Re-indexing all repositories... This may take several minutes.</span>');
  api("/github/reindex-all", { method: "POST" }).then(function(data) {
    if (data.success) {
      setHtml("ghActionResult", '<span style="color:#4ade80;">\u2713 Re-indexed ' + (data.total_indexed || 0) + ' files across ' + (data.repos_processed || 0) + ' repos</span>');
      _cache.github = false;
      loadGitHub();
    } else {
      setHtml("ghActionResult", '<span style="color:#f87171;">\u2717 ' + escHtml(data.error || "Failed") + '</span>');
    }
    if (btn) btn.disabled = false;
  }).catch(function(err) {
    setHtml("ghActionResult", '<span style="color:#f87171;">\u2717 ' + escHtml(err.message || "Error") + '</span>');
    if (btn) btn.disabled = false;
  });
}

window.searchGithub = function() {
  var q = document.getElementById("ghSearchInput").value;
  if (!q) return;
  setHtml("ghSearchResults", '<div class="cs-loading">Searching...</div>');
  api("/github/search-semantic", { method: "POST", body: { query: q, limit: 20 } }).then(function(data) {
    var results = data.results || [];
    if (!results.length) {
      setHtml("ghSearchResults", '<div class="cs-empty">No results found</div>');
      return;
    }
    var html = '<div class="cs-table-wrap"><table class="cs-table"><thead><tr><th>File</th><th>Score</th><th>Snippet</th></tr></thead><tbody>';
    results.forEach(function(r) {
      html += '<tr><td>' + escHtml(r.file_name || r.file_path || "\u2014") + '</td>' +
        '<td>' + (r.similarity ? r.similarity.toFixed(2) : "\u2014") + '</td>' +
        '<td style="max-width:400px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escHtml((r.content || "").substring(0, 100)) + '</td></tr>';
    });
    html += '</tbody></table></div>';
    setHtml("ghSearchResults", html);
  }).catch(function() {
    setHtml("ghSearchResults", '<div class="cs-empty">Search error</div>');
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

window.testPipeline = function() {
  var btn = document.getElementById("testPipelineBtn");
  if (btn) btn.disabled = true;
  setHtml("pipelineResult", '<div class="cs-loading">Testing pipeline...</div>');
  api("/api/integration/test-pipeline", { method: "POST" }).then(function(data) {
    if (!data.success) return;
    var html = data.steps.map(function(s) {
      var icon = s.status === "ok" ? "\u2713" : s.status === "warning" ? "\u26A0" : "\u2717";
      var cls = s.status === "ok" ? "green" : s.status === "warning" ? "amber" : "red";
      return '<div class="cs-pipeline-step ' + cls + '">' +
        '<span class="cs-pipeline-icon">' + icon + '</span>' +
        '<span>' + escHtml(s.step) + '</span>' +
        (s.ms ? '<span class="cs-pipeline-ms">' + s.ms + 'ms</span>' : '') +
        (s.model ? '<span class="cs-badge">' + escHtml(s.model) + '</span>' : '') +
        (s.error ? '<span class="cs-error">' + escHtml(s.error) + '</span>' : '') +
        '</div>';
    }).join("");
    setHtml("pipelineResult", html);
    if (btn) btn.disabled = false;
  }).catch(function() {
    setHtml("pipelineResult", '<div class="cs-empty">Pipeline test failed</div>');
    if (btn) btn.disabled = false;
  });
};

/* ── Init ──────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", function () {
  refreshIcons();

  // Close modals on overlay click
  var overlay = document.getElementById("agentModalOverlay");
  if (overlay) {
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeAgentModal();
    });
  }
  var repoOverlay = document.getElementById("addRepoOverlay");
  if (repoOverlay) {
    repoOverlay.addEventListener("click", function (e) {
      if (e.target === repoOverlay) closeAddRepoModal();
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
