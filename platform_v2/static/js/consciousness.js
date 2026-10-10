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
  // Safe: all callers pass internally-generated markup (badges, tables, chips)
  if (el) el.innerHTML = html;  // eslint-disable-line no-unsanitized/property
}

/** Animated count-up for HUD values. Counts from 0 to target over durationMs. */
function countUp(elId, target, suffix, durationMs) {
  var el = typeof elId === "string" ? document.getElementById(elId) : elId;
  if (!el) return;
  suffix = suffix || "";
  durationMs = durationMs || 1200;
  var num = typeof target === "number" ? target : parseInt(String(target).replace(/,/g, ""), 10);
  if (isNaN(num) || num === 0) { el.textContent = "0" + suffix; return; }
  var start = performance.now();
  var prev = 0;
  function step(ts) {
    var p = Math.min((ts - start) / durationMs, 1);
    var ease = 1 - Math.pow(1 - p, 3);
    var cur = Math.round(num * ease);
    if (cur !== prev) {
      el.textContent = cur.toLocaleString() + suffix;
      prev = cur;
    }
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
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
  } else if ((fetchOpts.method || "").toUpperCase() === "POST") {
    fetchOpts.headers["Content-Type"] = "application/json";
    fetchOpts.body = "{}";
  }
  return fetch(url, fetchOpts).then(function (resp) {
    var ct = resp.headers.get("content-type") || "";
    if (ct.indexOf("application/json") === -1) {
      if (resp.redirected || resp.status === 401 || resp.status === 403) {
        return Promise.reject(new Error("Not authorized — refresh the page or check admin access"));
      }
      return Promise.reject(new Error("Server error (HTTP " + resp.status + ") — check the platform logs"));
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
  // LCARS header manages its own active state

  // Toggle panels
  document.querySelectorAll(".cs-panel").forEach(function (panel) {
    panel.classList.toggle("active", panel.id === "panel-" + tab);
  });
  history.replaceState(null, "", "#" + tab);
  loadTabData(tab);
  if (tab === "knowledge" || tab === "github") {
    checkActiveJobs();
  }
  /* Job polling — only needed on dashboard/knowledge/github/languages tabs */
  if (tab !== "dashboard" && tab !== "knowledge" && tab !== "intelligence" && tab !== "github" && tab !== "languages") {
    _stopJobPolling();
  }
};

var _headerLoaded = false;
function loadTabData(tab) {
  // Always populate header stats on first tab load
  if (!_headerLoaded) {
    _headerLoaded = true;
    api("/api/dashboard/summary").then(function(d) {
      if (d.success) updateHeaderStats(d);
    }).catch(function(err) {
      console.error("API error:", err);
    });
  }

  if (_cache[tab]) return;

  // Destroy Neural Core when leaving dashboard to free GPU
  if (tab !== "dashboard" && _neuralCore) {
    _neuralCore.destroy();
    _neuralCore = null;
    if (_knowledgePollTimer) { clearInterval(_knowledgePollTimer); _knowledgePollTimer = null; }
  }

  // Set cache immediately for sync-loaded tabs to prevent double-loads
  // Code Health sets its own cache after async data loads
  if (tab !== "codehealth") _cache[tab] = true;

  switch (tab) {
    case "dashboard":   loadDashboard(); break;
    case "devhq":        if (typeof initDevHQPanel === "function") { initDevHQPanel(); } if (typeof loadDashboardV2Panels === "function") { loadDashboardV2Panels(); } break;
    case "knowledge":   loadKnowledge(); break;
    /* team tab merged into Starbase Command */
    case "github":      loadGitHub(); break;
    case "languages":   loadLanguages(); checkActiveJobs(); break;
    case "codehealth":  loadCodeHealth(); break;
    case "tokens":      loadTokenEconomy(30); break;
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

    // Fleet deployment stats (from Starbase data)
    var fleetEl = document.getElementById("fleetStats");
    if (!fleetEl) {
      // Create fleet stats row below wellness bars
      var wellnessCard = document.getElementById("wellnessMoodBar");
      if (wellnessCard) {
        var parent = wellnessCard.closest(".cs-card-body");
        if (parent) {
          fleetEl = document.createElement("div");
          fleetEl.id = "fleetStats";
          fleetEl.style.cssText = "margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06);display:flex;gap:8px;flex-wrap:wrap;";
          parent.appendChild(fleetEl);
        }
      }
    }
    if (fleetEl && data.agents.deployed !== undefined) {
      var tasks1h = data.agents.tasks_last_hour || 0;
      var rate = data.agents.success_rate_1h || 0;
      var rateColor = rate >= 90 ? "#22c55e" : rate >= 70 ? "#f59e0b" : "#ef4444";
      while (fleetEl.firstChild) fleetEl.removeChild(fleetEl.firstChild);
      var items = [
        {label: "Active", value: (data.agents.fleet_active !== undefined ? data.agents.fleet_active : data.agents.active), color: "#22c55e"},
        {label: "Deployed", value: data.agents.deployed, color: "#22d3ee"},
        {label: "Reserve", value: data.agents.barracked, color: "#8b5cf6"},
        {label: "Off Duty", value: data.agents.off_duty, color: "rgba(255,255,255,0.3)"},
        {label: "Tasks/1h", value: tasks1h, color: "#00e5ff"},
        {label: "Success", value: rate + "%", color: rateColor}
      ];
      items.forEach(function(item) {
        var el = document.createElement("div");
        el.style.cssText = "text-align:center;flex:1;min-width:50px;";
        var v = document.createElement("div");
        v.style.cssText = "font-size:0.9rem;font-weight:700;color:" + item.color + ";";
        v.textContent = item.value;
        var l = document.createElement("div");
        l.style.cssText = "font-size:0.55rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.05em;";
        l.textContent = item.label;
        el.appendChild(v);
        el.appendChild(l);
        fleetEl.appendChild(el);
      });
    }

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

    // Load merged tab data (Insights analytics + Integration health + System health)
    loadInsights();
    loadIntegration();
    loadSystemHealth();

    // Auto-refresh dashboard every 60 seconds while on this tab
    if (!window._dashboardRefreshTimer) {
      window._dashboardRefreshTimer = setInterval(function() {
        var panel = document.getElementById("panel-dashboard");
        if (panel && (panel.style.display !== "none" && panel.offsetParent !== null)) {
          loadDashboard();
        }
      }, 60000);
    }
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
      countUp(kbEl, kb.total_entries || kb.total || 0);
      kbEl.style.cursor = "pointer";
      kbEl.title = "Total intelligence: KB + translations + decisions — click for timeline";
      kbEl.onclick = function() { showKnowledgeTimeline(); };
    }
    setHtml("ncActiveAgents", (agents.active || 0) + "/" + (agents.total || 0));
    var pl = data.project_links || {};
    countUp("ncProjectLinks", pl.total_links || 0);
  }).catch(function(err) {
    console.error("Neural core data error:", err);
    var loading = document.getElementById("ncLoading");
    if (loading) loading.classList.add("hidden");
  });

  // GitHub stats for embed coverage
  api("/github/stats").then(function(data) {
    if (data.success) {
      countUp("ncGitHubFiles", data.total_files || 0);
      countUp("ncEmbedPct", data.embed_pct || 0, "%");
    }
  }).catch(function(err) {
    console.error("API error:", err);
  });

  // Intelligence stats (from knowledge-gaps endpoint)
  api("/api/dashboard/knowledge-gaps").then(function(data) {
    if (!data.success) return;
    var gaps = data.gaps || [];
    countUp("ncActiveProjects", gaps.length);
    if (gaps.length > 0) {
      var avgComp = Math.round(gaps.reduce(function(s, g) { return s + (g.completeness || 0); }, 0) / gaps.length);
      var avgQual = Math.round(gaps.reduce(function(s, g) { return s + (g.quality_score || 0); }, 0) / gaps.length);
      countUp("ncCompleteness", avgComp, "%");
      var qEl = document.getElementById("ncQualityScore");
      if (qEl) {
        countUp(qEl, avgQual);
        // Color the quality score
        qEl.style.color = avgQual >= 70 ? "#22c55e" : avgQual >= 40 ? "#f59e0b" : "#ef4444";
      }
    }
  }).catch(function() {});

  // Code Health stats (response is flat, no success/data wrapper)
  api("/api/code-health/current").then(function(d) {
    if (d.total_lines) countUp("ncCodeLines", d.total_lines);
    var gradeEl = document.getElementById("ncHealthGrade");
    if (gradeEl && d.health_score) {
      gradeEl.textContent = d.health_score.grade || "--";
      var score = d.health_score.score || 0;
      gradeEl.style.color = score >= 90 ? "#22c55e" : score >= 70 ? "#06b6d4" : score >= 50 ? "#f59e0b" : "#ef4444";
    }
  }).catch(function() {});

  // Emotional state for mood (from brain-state endpoint)
  api("/brain-state").then(function(data) {
    var emotion = data.current_emotion || {};
    var mood = (emotion.mood || "focused").toLowerCase();
    if (_neuralCore) _neuralCore.setMood(mood);
    else if (_holoSphere) _holoSphere.setMood(mood);
  }).catch(function(err) {
    console.warn("Mood fetch failed, using default:", err.message || err);
  });

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
  if (!_neuralCore) return;
  fetch("/tools/department-hq/api/crew/manifest").then(function(r) { return r.json(); }).then(function(data) {
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
      }
    });
  }).catch(function(err) {
    console.error("API error:", err);
  });
}

function _startKnowledgePolling() {
  if (_knowledgePollTimer) clearInterval(_knowledgePollTimer);
  _knowledgePollTimer = setInterval(function() {
    if (!_neuralCore) return;
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
    }).catch(function(err) {
      console.error("API error:", err);
    });
  }, 20000);
}

/* ── Agent Modal ───────────────────────────────────── */

/* Agent modal removed — profiles now in Starbase Command */

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
      (sub === "embeddings" && txt === "embeddings") ||
      (sub === "graph" && txt === "graph"));
  });
  document.querySelectorAll("#panel-knowledge .cs-subpanel").forEach(function(p) {
    p.classList.toggle("active", p.id === "kb-" + sub);
  });
  if (sub === "categories") loadCategories();
  if (sub === "embeddings") loadEmbeddingStatus();
  if (sub === "graph") loadKnowledgeGraph();
};

/* ── Dev HQ Tab ────────────────────────────────────── */

window.switchDevHQSubtab = function(sub) {
  document.querySelectorAll("#devhqSubtabs .cs-subtab").forEach(function(b) {
    b.classList.toggle("active", b.dataset.subtab === sub);
  });
  document.querySelectorAll("#panel-devhq .cs-subpanel").forEach(function(p) {
    p.style.display = (p.id === sub) ? "" : "none";
  });
};

/* ── Knowledge Graph (D3 force-directed) ──────────── */
var _graphLoaded = false;

function loadKnowledgeGraph() {
  if (_graphLoaded) return;
  var container = document.getElementById("knowledgeGraphContainer");
  var svg = d3.select("#knowledgeGraphSvg");
  if (!svg.node()) return;

  var width = container.clientWidth || 800;
  var height = container.clientHeight || 500;

  api("/api/knowledge/graph?limit=500").then(function(data) {
    if (!data.success || !data.nodes || !data.nodes.length) {
      setHtml("graphLoading", '<span style="color:rgba(255,255,255,0.4);">No graph data available. Add knowledge relationships to see connections.</span>');
      return;
    }
    document.getElementById("graphLoading").style.display = "none";
    var totalEntries = data.total_kb_entries ? data.total_kb_entries.toLocaleString() : "?";
    var totalRels = data.total_relationships ? data.total_relationships.toLocaleString() : "?";
    var semCount = data.semantic_edge_count || 0;
    setHtml("graphNodeCount", data.node_count + " / " + totalEntries);
    setHtml("graphEdgeCount", data.edge_count + "+" + semCount + " / " + totalRels);
    _graphLoaded = true;

    var typeColors = {
      // knowledge_base types
      vault_note: "#8b5cf6", conversation_memory: "#3b82f6", github_file: "#22d3ee",
      code_snippet: "#f97316", api_endpoint: "#10b981", mistake_learned: "#ef4444",
      improvement: "#a3e635", knowledge_card_concept: "#f472b6", upgrade_suggestion: "#fbbf24",
      // cross-table types (Dev HQ + Languages)
      decision: "#fb923c", project: "#fbbf24", translation: "#10b981",
    };
    function nodeColor(d) { return typeColors[d.type] || "#6b7280"; }

    svg.selectAll("*").remove();
    svg.attr("viewBox", [0, 0, width, height]);

    var g = svg.append("g");

    svg.call(d3.zoom().scaleExtent([0.1, 6]).on("zoom", function(e) {
      g.attr("transform", e.transform);
    }));

    var nodes = data.nodes.map(function(n) { return Object.assign({}, n); });
    var nodeMap = {};
    nodes.forEach(function(n) { nodeMap[n.id] = true; });

    // Split explicit relationships (solid purple) from semantic similarity (dashed teal)
    var explicitEdges = data.edges.filter(function(e) {
      return e.kind === "explicit" && nodeMap[e.source] && nodeMap[e.target];
    });
    var semanticEdges = data.edges.filter(function(e) {
      return e.kind === "semantic" && nodeMap[e.source] && nodeMap[e.target];
    });

    // Two link forces: explicit pulls nodes close (strong), semantic creates
    // cross-cluster web at larger distance (weak) — gives the interconnected look
    var simulation = d3.forceSimulation(nodes)
      .force("explicit", d3.forceLink(explicitEdges).id(function(d) { return d.id; }).distance(60).strength(0.5))
      .force("semantic", d3.forceLink(semanticEdges).id(function(d) { return d.id; }).distance(140).strength(0.06))
      .force("charge", d3.forceManyBody().strength(-80))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(function(d) { return 5 + d.importance * 12; }));

    // Semantic similarity edges — drawn first so explicit renders on top
    var semLink = g.append("g").attr("class", "graph-semantic-links")
      .selectAll("line").data(semanticEdges).join("line")
      .attr("stroke", "rgba(34,211,238,0.13)")
      .attr("stroke-width", 0.6)
      .attr("stroke-dasharray", "3,5");

    // Explicit relationship edges — solid, width scaled to strength
    var link = g.append("g").attr("class", "graph-links")
      .selectAll("line").data(explicitEdges).join("line")
      .attr("stroke", "rgba(139,92,246,0.35)")
      .attr("stroke-width", function(d) { return 1 + (d.strength || 0.5) * 2.5; });

    // Nodes rendered on top of all edges
    var node = g.append("g").attr("class", "graph-nodes")
      .selectAll("circle").data(nodes).join("circle")
      .attr("r", function(d) { return 4 + d.importance * 12; })
      .attr("fill", nodeColor)
      .attr("stroke", "#000").attr("stroke-width", 0.5)
      .style("cursor", "pointer")
      .call(d3.drag()
        .on("start", function(e, d) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", function(e, d) { d.fx = e.x; d.fy = e.y; })
        .on("end", function(e, d) { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    node.append("title").text(function(d) { return d.title; });

    node.on("click", function(e, d) {
      var detail = document.getElementById("graphNodeDetail");
      detail.style.display = "block";
      setHtml("graphNodeTitle", escHtml(d.title));
      var src = d.source_table ? " [" + escHtml(d.source_table) + "]" : "";
      setHtml("graphNodeMeta", "Type: " + escHtml(d.type) + src + " | Category: " + escHtml(d.category) + " | Importance: " + d.importance.toFixed(2));
    });

    g.append("g").attr("class", "graph-labels")
      .selectAll("text").data(nodes.filter(function(d) { return d.importance >= 0.8; })).join("text")
      .text(function(d) { return d.title.length > 25 ? d.title.substring(0, 22) + "..." : d.title; })
      .attr("font-size", "9px").attr("fill", "rgba(255,255,255,0.6)")
      .attr("font-family", "'IBM Plex Mono', monospace")
      .attr("dx", 12).attr("dy", 4);

    simulation.on("tick", function() {
      semLink.attr("x1", function(d) { return d.source.x; }).attr("y1", function(d) { return d.source.y; })
             .attr("x2", function(d) { return d.target.x; }).attr("y2", function(d) { return d.target.y; });
      link.attr("x1", function(d) { return d.source.x; }).attr("y1", function(d) { return d.source.y; })
          .attr("x2", function(d) { return d.target.x; }).attr("y2", function(d) { return d.target.y; });
      node.attr("cx", function(d) { return d.x; }).attr("cy", function(d) { return d.y; });
      g.selectAll(".graph-labels text").attr("x", function(d) { return d.x; }).attr("y", function(d) { return d.y; });
    });
  }).catch(function(err) {
    setHtml("graphLoading", '<span style="color:#ef4444;">Failed to load graph: ' + err + '</span>');
  });
}

var _kbPage = 1;
var _kbPageSize = 25;
var _kbEntries = [];

/* ── Knowledge LCARS Operations Terminal ─────────── */

function renderKnowledgeOps(agentData, jobData) {
  /* Agents, jobs, and commands all rendered by shared DepartmentOps component */
  _renderOpsAgents("kbOpsAgents", "ANALYTICS", jobData);
}

function loadKnowledge() {
  renderKnowledgeOps();
  loadKnowledgeBrowser();
  _loadTypeSummary();
}

/* Chip click: toggle filter on/off, update active state, reload browser */
window._kbChipClick = function(filterType) {
  var sel = document.getElementById("kbFilterType");
  if (sel) sel.value = (sel.value === filterType) ? "" : filterType;
  _cache.knowledge = false;
  document.querySelectorAll("#kbTypeSummary .cs-type-chip").forEach(function(c) {
    c.classList.toggle("active", c.dataset.filter === (sel ? sel.value : ""));
  });
  loadKnowledgeBrowser();
};

function _loadTypeSummary() {
  var CHIPS = [
    { group: "github_file",         filter: "github_file",         cls: "github",  label: "GitHub" },
    { group: "conversation_memory", filter: "conversation_memory", cls: "convo",   label: "Conversations" },
    { group: "vault_note",          filter: "vault_note",          cls: "vault",   label: "Vault Notes" },
    { group: "knowledge_card",      filter: "knowledge_card",      cls: "cards",   label: "Knowledge Cards" },
    { group: "mistake_learned",     filter: "mistake_learned",     cls: "mistake", label: "Mistakes" },
    { group: "api_endpoint",        filter: "api_endpoint",        cls: "api",     label: "API" },
    { group: "code_snippet",        filter: "code_snippet",        cls: "code",    label: "Code" },
    { group: "upgrade_suggestion",  filter: "upgrade_suggestion",  cls: "upgrade", label: "Upgrades" },
  ];
  api("/knowledge/type-stats").then(function(data) {
    var countMap = {};
    (data.types || []).forEach(function(t) { countMap[t.type_group] = t.count; });
    var el = document.getElementById("kbTypeSummary");
    if (!el) return;
    var html = "";
    CHIPS.forEach(function(chip) {
      var cnt = countMap[chip.group] || 0;
      if (!cnt) return;
      html += '<span class="cs-type-chip ' + chip.cls + '" data-filter="' + chip.filter + '" ' +
        'onclick="_kbChipClick(\'' + chip.filter + '\')" title="Filter: ' + chip.label + '">' +
        '<span class="chip-count">' + cnt.toLocaleString() + "</span> " + chip.label + "</span>";
    });
    setHtml(el, html);
  }).catch(function(err) {
    console.error("[TypeSummary]", err);
  });
}

function loadKnowledgeBrowser() {
  var search = document.getElementById("kbSearch");
  var typeFilter = document.getElementById("kbFilterType");
  var hasFilter = (typeFilter && typeFilter.value) || (search && search.value.trim());
  var params = "?limit=" + (hasFilter ? 500 : 200);
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

  var html = '<div class="cs-table-wrap" style="overflow-x:auto;"><table class="cs-table" style="min-width:640px;"><thead><tr>' +
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
    // Separate virtual cross-table entries (project_decisions, translations)
    // from regular knowledge_base categories
    var virtual = cats.filter(function(c) { return c.virtual; });
    var regular = cats.filter(function(c) { return !c.virtual; });
    regular.sort(function(a, b) { return (b.count || 0) - (a.count || 0); });
    var maxCount = regular.length ? (regular[0].count || 1) : 1;
    var html = '<div class="cs-cat-grid">';

    // Virtual categories at top — link to their own tabs, not browser filter
    virtual.forEach(function(c) {
      var cnt = c.count || 0;
      html += '<div class="cs-cat-card tier-1" style="border-color:rgba(251,146,60,0.35);cursor:pointer;" onclick="switchConsciousnessTab(\'' + escHtml(c.link_tab || "knowledge") + '\')">' +
        '<div class="cat-name" style="color:#fb923c;">' + escHtml(c.category) + ' ↗</div>' +
        '<div class="cat-count">' + cnt.toLocaleString() + ' entries</div>' +
        (c.description ? '<div style="font-size:0.7rem;color:rgba(255,255,255,0.35);margin-top:2px;">' + escHtml(c.description) + '</div>' : '') +
        '</div>';
    });

    // Regular knowledge_base categories — click filters the browser
    regular.forEach(function(c) {
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
  /* Delegate to shared DepartmentOps component */
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
  /* Pull from Department HQ — single source of truth for agent/station work */
  fetch("/tools/department-hq/api/bridge/jobs?status=running").then(function(resp) {
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
          _enableProcessingBtns();
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
          _enableGitHubBtns();
          setTimeout(checkActiveJobs, 500);
        });
      }
    });

    /* ── Languages tab — job progress rendered by DepartmentOps, but track
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
}

function _buildJobHtml(job) {
  /* Delegate to shared DepartmentOps component */
  var ops = _kbOps || _getOpsInstance("kbOpsAgents");
  return ops.buildJobHtml(job);
}

function _renderBridgeJob(job, el) {
  /* Delegate to shared DepartmentOps component */
  var ops = _kbOps || _getOpsInstance("kbOpsAgents");
  ops.renderJob(job, el);
}

function _renderBridgeJobs(jobs, el, prefix) {
  /* Delegate to shared DepartmentOps component */
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
  _setBtnDisabled("btnStartAnalysis", false);
  _setBtnDisabled("btnGenerateEmbed", false);
}

function _disableGitHubBtns() {
  _setBtnDisabled("btnReindexAll", true);
  _setBtnDisabled("btnStartAnalysis", true);
  _setBtnDisabled("btnGenerateEmbed", true);
}

function _enableGitHubBtns() {
  _setBtnDisabled("btnReindexAll", false);
  _setBtnDisabled("btnStartAnalysis", false);
  _setBtnDisabled("btnGenerateEmbed", false);
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
  if (hasAnalysis) _setBtnDisabled("btnStartAnalysis", true);
  if (hasEmbed) _setBtnDisabled("btnGenerateEmbed", true);
}

/* ── Loop controls removed — moved to Autonomy module ── */

function _procFeedback(html) {
  setHtml("procResult", html);
  setHtml("ghIntakeResult", html);
}

window.startAnalysis = function() {
  _disableProcessingBtns();
  _procFeedback(lcarsMsg("info", "\u25CF", "Assigning agent for analysis\u2026"));

  api("/api/processing/start", {
    method: "POST",
    body: { category: "conversations", batch_size: 10 }
  }).then(function(data) {
    if (data.duplicate || data._status === 409) {
      _procFeedback(lcarsMsg("warn", "\u25B6", escHtml(data.error || "Job already running")));
      checkActiveJobs();
      return;
    }
    if (data.success && data.job_id) {
      _procFeedback(lcarsMsg("ok", "\u25B6", "Job #" + data.job_id + " started \u2014 " + (data.total || 0) + " items queued"));
      setTimeout(checkActiveJobs, 1000);
    } else if (data.success) {
      _procFeedback(lcarsMsg("ok", "\u2713", escHtml(data.message || "No items to analyze")));
      _enableProcessingBtns();
    } else {
      _procFeedback(lcarsMsg("err", "\u2717", escHtml(data.error || "Processing failed")));
      _enableProcessingBtns();
    }
  }).catch(function(err) {
    _procFeedback(lcarsMsg("err", "\u2717", "Error: " + escHtml(err.message || "Request failed")));
    _enableProcessingBtns();
  });
};

window.generateEmbeddings = function() {
  _disableProcessingBtns();
  _procFeedback(lcarsMsg("info", "\u25CF", "Assigning agent for embeddings\u2026"));

  api("/api/processing/generate-embeddings", {
    method: "POST",
    body: { batch_size: 50 }
  }).then(function(data) {
    if (data.duplicate || data._status === 409) {
      _procFeedback(lcarsMsg("warn", "\u25B6", escHtml(data.error || "Embedding job already running")));
      checkActiveJobs();
      return;
    }
    if (data.success && data.job_id) {
      _procFeedback(lcarsMsg("ok", "\u25B6", "Job #" + data.job_id + " started \u2014 " + (data.total || 0) + " entries queued"));
      setTimeout(checkActiveJobs, 1000);
    } else if (data.success) {
      _procFeedback(lcarsMsg("ok", "\u2713", escHtml(data.message || "All entries already embedded")));
      _enableProcessingBtns();
    } else {
      _procFeedback(lcarsMsg("err", "\u2717", escHtml(data.error || "Embedding generation failed")));
      _enableProcessingBtns();
    }
  }).catch(function(err) {
    _procFeedback(lcarsMsg("err", "\u2717", "Error: " + escHtml(err.message || "Request failed")));
    _enableProcessingBtns();
  });
};

/* ── Team Tab — merged into Starbase Command → Crew → Manifest ── */

/* ── Team Sub-tabs — merged into Starbase Command ──── */

/* emotionalDetailChart removed — was Team sub-tab only */

/* ── Insights Tab ──────────────────────────────────── */

/* switchInsightsSubtab removed — Insights sub-tabs (sessions, improvements) no longer in UI */

function loadInsights() {
  api("/api/insights/summary").then(function(data) {
    if (!data.success) return;
    countUp("insightsBridgeTotal", data.bridge_stats.total || 0);
    var avgSec = Math.round((data.bridge_stats.avg_time_ms || 0) / 1000);
    var avgEl = document.getElementById("insightsAvgTime");
    if (avgEl) { avgEl.textContent = avgSec + "s"; }
    countUp("insightsTokens", data.bridge_stats.total_tokens || 0);
    countUp("insightsModels", data.bridge_stats.models_used || 0);
    countUp("insightsGrowth", data.knowledge_growth || 0);
    refreshIcons();
  }).catch(function(err) {
    console.error("loadInsights error:", err);
  });
}

function loadSystemHealth() {
  // Dev HQ — count active projects
  api("/api/dashboard/knowledge-gaps").then(function(d) {
    var el = document.getElementById("intDevhqStatus");
    if (el && d.success) {
      var count = (d.gaps || []).length;
      el.textContent = count;
      el.style.color = "#22c55e";
    }
  }).catch(function() {
    var el = document.getElementById("intDevhqStatus");
    if (el) { el.textContent = "Offline"; el.style.color = "#ef4444"; }
  });

  // Bridge — count loaded models via DHQ fleet queue-status (ADR-013: no direct Ollama from browser)
  fetch("/tools/department-hq/api/fleet/queue-status").then(function(r) {
    return r.ok ? r.json() : null;
  }).then(function(d) {
    var elBridge = document.getElementById("intBridgeStatus");
    var elOllama = document.getElementById("intOllamaStatus");
    if (d && d.loaded !== undefined) {
      if (elBridge) { elBridge.textContent = d.loaded.length; elBridge.style.color = "#3b82f6"; }
      if (elOllama) { elOllama.textContent = "Online"; elOllama.style.color = "#22c55e"; }
    } else {
      if (elBridge) { elBridge.textContent = "0"; elBridge.style.color = "#3b82f6"; }
      if (elOllama) { elOllama.textContent = "Online"; elOllama.style.color = "#22c55e"; }
    }
  }).catch(function() {
    var elBridge = document.getElementById("intBridgeStatus");
    var elOllama = document.getElementById("intOllamaStatus");
    if (elBridge) { elBridge.textContent = "Offline"; elBridge.style.color = "#ef4444"; }
    if (elOllama) { elOllama.textContent = "Offline"; elOllama.style.color = "#ef4444"; }
  });

  // GitHub — repos indexed count from knowledge base
  api("/github/stats").then(function(d) {
    var el = document.getElementById("intGithubStatus");
    if (el && d.success) {
      el.textContent = d.total_repos || d.total_files || 0;
      el.style.color = "#f59e0b";
    }
  }).catch(function() {});

  // Overall health — use code health grade
  api("/api/code-health/current").then(function(d) {
    var el = document.getElementById("intHealthStatus");
    if (el && d.health_score) {
      var score = d.health_score.score || 0;
      el.textContent = d.health_score.grade || "--";
      el.style.color = score >= 90 ? "#22c55e" : score >= 70 ? "#06b6d4" : score >= 50 ? "#f59e0b" : "#ef4444";
    }
  }).catch(function() {});
}

/* loadSessions / loadImprovements removed — no longer in UI */

/* ── Languages Tab ─────────────────────────────────── */

/* switchLangSubtab removed — Languages tab is now single-page LCARS layout */

var _langGenQueue = [];
var _langGenRunning = false;

/* ── Languages LCARS Operations Terminal ───────────── */

function renderLangOps(agentData, jobData) {
  /* Agents, jobs, and commands all rendered by shared DepartmentOps component */
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
  }).catch(function(err) {
    console.error("API error:", err);
  });

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
  _showLangJob("Queuing all 7 languages...");

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
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
      return;
    }
    _showLangJob("Job #" + data.job_id + " started \u2014 " + data.total + " keys across 7 languages");
    checkActiveJobs();
    _startLangJobPoll(data.job_id, function() {
      if (btn) { btn.disabled = false; btn.style.opacity = "1"; }
    });
  }).catch(function(err) {
    _showLangJob("Failed: " + err);
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
  /* Progress rendered by DepartmentOps — just track completion for refresh + loop */
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

var _ghRepos = []; // cached for filtering
var _ghFilter = 'all';
var _ghView = 'list'; // 'list' or 'cards'

function toggleRepoView() {
  _ghView = _ghView === 'list' ? 'cards' : 'list';
  var btn = document.getElementById('ghViewToggle');
  if (btn) btn.textContent = _ghView === 'list' ? 'Cards' : 'List';
  renderRepoView(_ghRepos);
}

function renderRepoView(repos) {
  if (_ghView === 'list') renderRepoList(repos);
  else renderRepoCards(repos);
}

function filterRepos(status, btn) {
  _ghFilter = status;
  // Update active button. Was `event.target.closest('.gh-filter-btn')`, which
  // relied on the deprecated implicit global `event` (absent in Firefox and
  // Safari) and broke on the count <span> inside the button. The caller now
  // passes the element explicitly.
  document.querySelectorAll('.gh-filter-btn').forEach(function(b) { b.classList.remove('active'); });
  var active = btn || document.querySelector('.gh-filter-btn[data-gh-filter="' + status + '"]');
  if (active) active.classList.add('active');
  renderRepoView(_ghRepos);
}

function renderRepoList(repos) {
  var filtered = _ghFilter === 'all' ? repos : repos.filter(function(r) { return (r.review_status || 'pending') === _ghFilter; });

  if (!filtered.length) {
    setHtml("ghRepoGrid", '<div style="grid-column:1/-1; text-align:center; padding:40px 20px; color:rgba(255,255,255,0.3);"><div style="font-size:0.82rem;">No repositories match this filter</div></div>');
    return;
  }

  var html = '<table class="gh-repo-table"><thead><tr>' +
    '<th>Repository</th><th>Files</th><th>Type</th><th>Status</th><th>Tags</th><th>Actions</th>' +
    '</tr></thead><tbody>';

  filtered.forEach(function(r) {
    var rs = r.review_status || 'pending';
    var rsLabel = rs === 'under_review' ? 'REVIEW' : rs.toUpperCase();
    var tags = (r.relevance_tags || []).map(function(t) { return '<span class="gh-review-tag">' + escHtml(t) + '</span>'; }).join(' ');
    var safeName = escHtml(r.repo_name).replace(/'/g, "\\'");

    html += '<tr data-repo-id="' + r.id + '">' +
      '<td>' +
        '<div class="gh-list-name">' + escHtml(r.repo_name) + '</div>' +
        (r.review_notes ? '<div class="gh-list-notes" title="' + escHtml(r.review_notes).replace(/"/g, '&quot;') + '">' + escHtml(r.review_notes.substring(0, 80)) + (r.review_notes.length > 80 ? '...' : '') + '</div>' : '') +
      '</td>' +
      '<td class="gh-list-files">' + (r.indexed_files || 0) + '</td>' +
      '<td class="gh-list-type">' + escHtml(r.repo_type || '') + '</td>' +
      '<td><span class="gh-review-badge ' + rs + '">' + rsLabel + '</span></td>' +
      '<td><div class="gh-review-tags" style="margin:0;">' + (tags || '-') + '</div></td>' +
      '<td class="gh-list-actions">' +
        (rs !== 'approved' ? '<button class="review-approve" onclick="updateRepoReview(' + r.id + ', \'approved\', \'' + safeName + '\')">&#10003;</button>' : '') +
        (rs !== 'rejected' ? '<button class="review-reject" onclick="updateRepoReview(' + r.id + ', \'rejected\', \'' + safeName + '\')">&#10007;</button>' : '') +
        '<a href="https://github.com/' + escHtml(r.repo_name) + '" target="_blank">Open</a>' +
      '</td>' +
    '</tr>';
  });

  html += '</tbody></table>';
  setHtml("ghRepoGrid", html);
}

function updateRepoReview(repoId, status, repoName) {
  if (status === 'rejected' && !confirm('Reject "' + repoName + '"? This marks it as not relevant.')) return;
  var notes = prompt(status === 'approved' ? 'Approval reason for "' + repoName + '":' : 'Rejection reason for "' + repoName + '" (optional):') || '';
  api("/api/github/repositories/" + repoId + "/review", {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({review_status: status, review_notes: notes || undefined})
  }).then(function(data) {
    if (data.success) loadGitHub();
  });
}

function toggleReviewNotes(el) {
  el.closest('.gh-repo-card').querySelector('.gh-review-notes').classList.toggle('open');
}

function renderRepoCards(repos) {
  var filtered = _ghFilter === 'all' ? repos : repos.filter(function(r) { return (r.review_status || 'pending') === _ghFilter; });

  if (!filtered.length) {
    setHtml("ghRepoGrid",
      '<div style="grid-column:1/-1; text-align:center; padding:40px 20px; color:rgba(255,255,255,0.3);">' +
      '<div style="font-size:1.5rem; margin-bottom:8px;">&#x1f50d;</div>' +
      '<div style="font-size:0.82rem;">No repositories match this filter</div></div>');
    return;
  }

  var html = '';
  filtered.forEach(function(r) {
    var coverageCls = 'coverage-low';
    if (r.indexed && r.indexed_files > 0) coverageCls = 'coverage-mid';

    var circumference = 2 * Math.PI * 18;
    var dashoffset = circumference;
    var descSnippet = r.description ? escHtml(r.description.substring(0, 120)) + (r.description.length > 120 ? '...' : '') : '';
    var rs = r.review_status || 'pending';
    var rsLabel = rs === 'under_review' ? 'REVIEW' : rs.toUpperCase();
    var hasNotes = r.review_notes && r.review_notes.length > 0;
    var tags = r.relevance_tags || [];

    html += '<div class="gh-repo-card ' + coverageCls + '" data-repo-id="' + r.id + '" data-review="' + rs + '">' +
      '<div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">' +
        '<div class="gh-repo-card-name" style="flex:1; margin-bottom:0;" title="' + escHtml(r.repo_name) + '">' + escHtml(r.repo_name) + '</div>' +
        '<span class="gh-review-badge ' + rs + '">' + rsLabel + '</span>' +
      '</div>' +
      (descSnippet ? '<div style="font-size:0.68rem; color:rgba(255,255,255,0.35); margin:0 0 6px; line-height:1.3; overflow:hidden; max-height:2.6em;">' + descSnippet + '</div>' : '') +
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
      (tags.length ? '<div class="gh-review-tags">' + tags.map(function(t) { return '<span class="gh-review-tag">' + escHtml(t) + '</span>'; }).join('') + '</div>' : '') +
      '<div class="gh-repo-card-meta">' +
        (r.repo_type ? '<span>' + escHtml(r.repo_type) + '</span>' : '') +
        (r.status ? '<span>' + escHtml(r.status) + '</span>' : '') +
        (hasNotes ? '<span style="cursor:pointer; color:var(--cat-accent);" onclick="event.stopPropagation(); toggleReviewNotes(this);">Notes &#9660;</span>' : '') +
      '</div>' +
      (hasNotes ? '<div class="gh-review-notes">' + escHtml(r.review_notes).replace(/\\n/g, '<br>') + '</div>' : '') +
      '<div class="gh-repo-card-actions">' +
        (rs !== 'approved' ? '<button class="review-approve" onclick="event.stopPropagation(); updateRepoReview(' + r.id + ', \'approved\', \'' + escHtml(r.repo_name).replace(/'/g, "\\'") + '\')">Approve</button>' : '') +
        (rs !== 'rejected' ? '<button class="review-reject" onclick="event.stopPropagation(); updateRepoReview(' + r.id + ', \'rejected\', \'' + escHtml(r.repo_name).replace(/'/g, "\\'") + '\')">Reject</button>' : '') +
        '<button onclick="event.stopPropagation(); reindexRepo(' + r.id + ')">Re-index</button>' +
        '<button class="danger" onclick="event.stopPropagation(); deleteRepo(' + r.id + ', \'' + escHtml(r.repo_name).replace(/'/g, "\\'") + '\')">Delete</button>' +
        '<a href="https://github.com/' + escHtml(r.repo_name) + '" target="_blank" onclick="event.stopPropagation();">Open</a>' +
        (r.local_path ? '<button onclick="event.stopPropagation(); openRepoExplorer(' + r.id + ', \'' + escHtml(r.repo_name).replace(/'/g, "\\'") + '\')" style="background:rgba(139,92,246,0.2); border-color:rgba(139,92,246,0.4); color:#c4b5fd;">Explore</button>' : '') +
      '</div>' +
    '</div>';
  });
  setHtml("ghRepoGrid", html);
  refreshIcons();
}

function loadGitHub() {
  renderGitHubOps();
  api("/api/github/repos").then(function(data) {
    if (!data.success) return;
    var repos = data.repos || [];
    _ghRepos = repos;
    setHtml("ghRepoCount", repos.length);

    // Update filter counts
    var counts = {all: repos.length, approved: 0, under_review: 0, pending: 0, rejected: 0};
    repos.forEach(function(r) { var s = r.review_status || 'pending'; if (counts[s] !== undefined) counts[s]++; });
    setHtml("ghFilterAll", counts.all);
    setHtml("ghFilterApproved", counts.approved);
    setHtml("ghFilterReview", counts.under_review);
    setHtml("ghFilterPending", counts.pending);
    setHtml("ghFilterRejected", counts.rejected);

    if (!repos.length) {
      setHtml("ghRepoGrid",
        '<div style="grid-column:1/-1; text-align:center; padding:40px 20px; color:rgba(255,255,255,0.3);">' +
        '<div style="font-size:2rem; margin-bottom:8px;">&#x1f4e1;</div>' +
        '<div style="font-family:Antonio,sans-serif; font-size:0.85rem; letter-spacing:1px; text-transform:uppercase;">No repositories indexed</div>' +
        '<div style="font-size:0.75rem; margin-top:4px;">Paste a GitHub URL above to begin learning</div>' +
        '</div>');
      return;
    }

    renderRepoView(repos);
    loadGitHubEmbedStats();
    loadSkillPipeline();
    loadSkillPipelineStats();
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
  }).catch(function(err) {
    console.error("API error:", err);
  });
}

function adaptSkill(skillId) {
  if (!confirm('Adapt this skill for A.R.C.H.I.E.? This sends it to Bridge for rewriting.')) return;
  api("/github/skills/" + skillId + "/adapt", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({})
  }).then(function(data) {
    if (data.success) {
      alert("Skill adapted successfully! ID: " + (data.new_skill_id || 'created'));
      loadSkillPipeline();
    } else {
      alert("Adaptation failed: " + (data.error || 'unknown error'));
    }
  }).catch(function(err) {
    alert("Error: " + err);
  });
}

function loadSkillPipeline() {
  api("/github/skills/stats").then(function(data) {
    if (!data.success) return;
    var p = data.pipeline || {};
    setHtml("ghSkillTotal", data.total_skills || 0);
    setHtml("ghSkillDiscovered", p.discovered || 0);
    setHtml("ghSkillAnalyzed", (p.analyzed || 0) + (p.analyzing || 0));
    setHtml("ghSkillRegistered", p.registered || 0);
    setHtml("ghSkillAdapted", p.adapted || 0);

    var ac = data.agent_coverage || {};
    setHtml("ghSkillAgents", ac.agents || 0);

    // Render recently analyzed skill cards
    var recent = data.recent_analyzed || [];
    if (!recent.length) {
      setHtml("ghSkillCards",
        '<div style="grid-column:1/-1; text-align:center; padding:24px; color:rgba(255,255,255,0.25);">' +
        '<div style="font-size:0.75rem; text-transform:uppercase; letter-spacing:1px;">Skills will appear here after analysis (Job #56, every 6h)</div></div>');
      return;
    }

    var html = '';
    recent.forEach(function(s) {
      var caps = s.capabilities || [];
      var capHtml = caps.slice(0, 4).map(function(c) {
        return '<span style="display:inline-block; padding:1px 6px; border-radius:3px; font-size:0.6rem; ' +
          'background:rgba(139,92,246,0.15); border:1px solid rgba(139,92,246,0.3); color:#c4b5fd; margin:2px 2px 0 0;">' +
          escHtml(c) + '</span>';
      }).join('');

      var qualityColor = '#ef4444';
      if (s.quality_score >= 4) qualityColor = '#22c55e';
      else if (s.quality_score >= 3) qualityColor = '#fbbf24';
      else if (s.quality_score >= 2) qualityColor = '#f97316';

      var statusColor = '#22d3ee';
      if (s.status === 'registered') statusColor = '#22c55e';
      else if (s.status === 'adapted') statusColor = '#8b5cf6';

      html += '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); ' +
        'border-radius:8px; padding:12px; transition:border-color 0.2s;" ' +
        'onmouseover="this.style.borderColor=\'rgba(139,92,246,0.4)\'" ' +
        'onmouseout="this.style.borderColor=\'rgba(255,255,255,0.08)\'">' +
        '<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">' +
          '<div style="font-family:Antonio,sans-serif; font-size:0.8rem; color:#e2e8f0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:70%;" title="' + escHtml(s.skill_name || '') + '">' +
            escHtml((s.skill_name || '').split('/').pop()) + '</div>' +
          '<div style="display:flex; gap:6px; align-items:center;">' +
            '<span style="font-family:Orbitron,sans-serif; font-size:0.75rem; color:' + qualityColor + ';">' + (s.quality_score || '?') + '/5</span>' +
            '<span style="font-size:0.6rem; padding:1px 5px; border-radius:3px; text-transform:uppercase; letter-spacing:0.5px; ' +
              'background:rgba(255,255,255,0.05); border:1px solid ' + statusColor + '; color:' + statusColor + ';">' + escHtml(s.status || '') + '</span>' +
          '</div>' +
        '</div>' +
        '<div style="font-size:0.65rem; color:rgba(255,255,255,0.3); margin-bottom:6px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="' + escHtml(s.repo_name || '') + '">' +
          escHtml(s.repo_name || '') + '</div>' +
        '<div>' + capHtml + '</div>' +
        (s.status === 'registered' && s.quality_score >= 4 ?
          '<div style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.06);">' +
            '<button onclick="adaptSkill(' + s.id + ')" style="padding:3px 10px; border-radius:4px; font-size:0.65rem; ' +
              'font-family:Antonio,sans-serif; letter-spacing:0.5px; text-transform:uppercase; cursor:pointer; ' +
              'background:rgba(139,92,246,0.15); border:1px solid rgba(139,92,246,0.3); color:#c4b5fd; transition:all 0.15s;" ' +
              'onmouseover="this.style.background=\'rgba(139,92,246,0.3)\'" onmouseout="this.style.background=\'rgba(139,92,246,0.15)\'">' +
              'Adapt for A.R.C.H.I.E.</button>' +
          '</div>' : '') +
        (s.status === 'adapted' ?
          '<div style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.06);">' +
            '<span style="font-size:0.62rem; color:#8b5cf6; text-transform:uppercase; letter-spacing:0.5px;">&#10003; Adapted</span>' +
          '</div>' : '') +
      '</div>';
    });
    setHtml("ghSkillCards", html);
  }).catch(function(err) {
    console.error("loadSkillPipeline error:", err);
  });
}

/* ── Pipeline Stats Bar (v2) ──────────────────────────────── */
async function loadSkillPipelineStats() {
  try {
    var data = await api("/api/github/skills/pipeline-stats");
    if (!data || !data.success) return;

    var p = data.pipeline;
    var statsHtml =
      '<div class="cs-pipeline-stats" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;padding:12px;background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.2);border-radius:8px;">' +
        '<span style="color:#a78bfa">Discovered: <b>' + (p.discovered || 0) + '</b></span>' +
        '<span style="color:#8b5cf6">Registered: <b>' + (p.registered || 0) + '</b></span>' +
        '<span style="color:#22d3ee">Installed: <b>' + (p.installed || 0) + '</b></span>' +
        '<span style="color:' + ((p.passed || 0) > 0 ? '#10b981' : '#6b7280') + '">Tested: <b>' + (p.passed || 0) + '</b> pass</span>' +
        ((p.failed || 0) > 0 ? '<span style="color:#ef4444">Failed: <b>' + (p.failed || 0) + '</b></span>' : '') +
        '<span style="color:#fbbf24">Adapted: <b>' + (p.adapted || 0) + '</b></span>' +
        (p.cli_synced > 0 ? '<span style="color:#818cf8">CLI Synced: <b>' + p.cli_synced + '</b></span>' : '') +
        (p.cluster_pushed > 0 ? '<span style="color:#f97316">Fleet: <b>' + p.cluster_pushed + '</b></span>' : '') +
      '</div>';

    var repoList = document.getElementById("ghRepoGrid");
    if (repoList) {
      var existing = document.querySelector(".cs-pipeline-stats");
      if (existing) existing.remove();
      repoList.insertAdjacentHTML("beforebegin", statsHtml);
    }
  } catch (e) {
    console.warn("[PipelineStats] Failed to load:", e);
  }
}

/* ── Shared: Render station crew + cross-station assists ─── */
/* Delegates to shared DepartmentOps component (department-ops.js) */

/* Track station capacity — updated by DepartmentOps onCapacityChange */
var _stationAtCapacity = false;

/* Per-tab DepartmentOps instances — all point to ANALYTICS station,
   each rendering into its own ops terminal element IDs */
var _kbOps = null;
var _ghOps = null;
var _langOps = null;

function _getOpsInstance(elId) {
  /* Return (or create) the DepartmentOps instance for the given agents element */
  if (elId === "kbOpsAgents") {
    if (!_kbOps) {
      _kbOps = new DepartmentOps({
        stationCode: "ANALYTICS",
        moduleSource: "consciousness",
        agentsElId: "kbOpsAgents",
        jobsElId: "kbOpsJobs",
        commandsElId: "kbOpsCommands",
        statusElId: "kbOpsOnline",
        commands: [
          { label: "ANALYZE", cls: "purple", fn: "startAnalysis()", id: "btnStartAnalysis" },
          { label: "EMBED", cls: "green", fn: "generateEmbeddings()", id: "btnGenerateEmbed" }
        ],
        onCapacityChange: function(atCap) { _stationAtCapacity = atCap; _applyStationCapacity(atCap); }
      });
    }
    return _kbOps;
  }
  if (elId === "ghOpsAgents") {
    if (!_ghOps) {
      _ghOps = new DepartmentOps({
        stationCode: "ANALYTICS",
        moduleSource: "consciousness",
        agentsElId: "ghOpsAgents",
        jobsElId: "ghOpsJobs",
        commandsElId: "ghOpsCommands",
        statusElId: "ghOpsOnline",
        commands: [
          { label: "REINDEX ALL", cls: "amber", fn: "reindexAllRepos()", id: "btnReindexAll" },
          { label: "ANALYZE", cls: "purple", fn: "startAnalysis()", id: "btnStartAnalysis2" },
          { label: "EMBED", cls: "green", fn: "generateEmbeddings()", id: "btnGenerateEmbed2" },
          { label: "VERIFY", cls: "cyan", fn: "verifyGitHubData()" }
        ],
        onCapacityChange: function(atCap) { _stationAtCapacity = atCap; _applyStationCapacity(atCap); }
      });
    }
    return _ghOps;
  }
  if (elId === "langOpsAgents") {
    if (!_langOps) {
      _langOps = new DepartmentOps({
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
          { label: "FULL PASS", cls: "cyan", fn: "langFullPass()", id: "langFullPassBtn" }
        ],
        onCapacityChange: function(atCap) { _stationAtCapacity = atCap; _applyStationCapacity(atCap); }
      });
    }
    return _langOps;
  }
  return null;
}

function _renderOpsAgents(elId, homeStationCode, jobData) {
  /* Delegate to shared DepartmentOps component — renders agents + jobs + commands */
  var ops = _getOpsInstance(elId);
  if (ops) {
    ops.render(jobData);
  }
}

function _applyStationCapacity(atCapacity) {
  /* Disable/enable ALL command buttons across all tabs when station is full */
  var allBtnIds = [
    "btnStartAnalysis", "btnStartAnalysis2", "btnEmbedKB",
    "btnReindexAll", "btnEmbedGH",
    "btnGenerateEmbed", "btnGenerateEmbed2",
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
  /* Agents, jobs, and commands all rendered by shared DepartmentOps component */
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
      var jobId = data.job_id;
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", "Indexing job #" + (jobId || "?") + " started \u2014 " + escHtml(data.message || "processing")));
      document.getElementById("ghIntakeUrl").value = "";
      /* Keep progress bar active and poll until job completes */
      if (btn) { btn.disabled = true; btn.textContent = "INDEXING..."; }
      setHtml("ghIntakeStatus", "Indexing in progress\u2026");
      checkActiveJobs();
      if (jobId) {
        var pollKey = "gh_intake_" + jobId;
        if (!_activeJobPolls[pollKey]) {
          _activeJobPolls[pollKey] = true;
          _pollJobStatus(jobId, "bjob-gh-" + jobId, function(completedJob) {
            _activeJobPolls[pollKey] = false;
            var meta = (completedJob && completedJob.metadata) || {};
            var indexed = meta.indexed || "?";
            var errCount = (completedJob && completedJob.errors) || 0;
            if (errCount > 0) {
              setHtml("ghIntakeResult", lcarsMsg("warn", "\u26A0", "Job #" + jobId + " completed with errors \u2014 " + indexed + " files indexed"));
            } else {
              setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", "Job #" + jobId + " complete \u2014 " + indexed + " files indexed"));
            }
            setHtml("ghIntakeStatus", "");
            if (prog) prog.classList.remove("active");
            if (btn) { btn.disabled = false; btn.textContent = "INGEST"; }
            _cache.github = false;
            loadGitHub();
            loadGitHubEmbedStats();
          });
        }
      }
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Failed to start indexing")));
      if (btn) { btn.disabled = false; btn.textContent = "INGEST"; }
      if (prog) prog.classList.remove("active");
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Network error")));
    if (btn) { btn.disabled = false; btn.textContent = "INGEST"; }
    if (prog) prog.classList.remove("active");
  }).finally(function() {
    _cache.github = false;
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
  }).catch(function(err) {
    console.error("API error:", err);
  });

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

  /* Agent modal overlay removed — profiles now in Starbase Command */
  // Wire LCARS header tab switching
  window.onLcarsTabSwitch = function(tab) {
    switchConsciousnessTab(tab);
  };

  // Resize handler for HoloSphere
  window.addEventListener("resize", function() {
    if (_holoSphere) _holoSphere.resize();
  });

  var hash = window.location.hash.replace("#", "");
  var validTabs = ["dashboard", "devhq", "knowledge", "github", "languages", "codehealth", "tokens"];
  if (hash && validTabs.indexOf(hash) !== -1) {
    lcarsHeaderSwitchTab(hash);
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
var _chTokenChart = null;

function loadCodeHealth() {
  // Show loading indicator
  var panel = document.getElementById("panel-codehealth");
  if (panel) {
    var loader = document.getElementById("chLoadingBar");
    if (!loader) {
      loader = document.createElement("div");
      loader.id = "chLoadingBar";
      loader.style.cssText = "position:fixed;top:0;left:0;width:100%;height:3px;background:linear-gradient(90deg,transparent,#00e5ff,transparent);animation:chSlide 1.2s infinite;z-index:9999;";
      var style = document.createElement("style");
      style.textContent = "@keyframes chSlide{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}";
      document.head.appendChild(style);
      document.body.appendChild(loader);
    }
    loader.style.display = "block";
  }
  // Load audit log + module status so table can show colored badges
  // module-status is optional — don't let it break the whole tab
  Promise.all([
    api("/api/code-health/current"),
    api("/api/code-health/audit-log"),
    api("/api/code-health/module-status").catch(function() { return {modules: [], summary: {}}; }),
    api("/api/code-health/standalone-status").catch(function() { return {standalones: []}; }),
    api("/api/code-health/repair-pipeline").catch(function() { return {success: false, queue: {}, proposals: {}, governance: []}; }),
    api("/api/code-health/orchestration").catch(function() { return {success: false, departments: []}; })
  ]).then(function(results) {
    // Hide loading bar and mark as cached
    var loader = document.getElementById("chLoadingBar");
    if (loader) loader.style.display = "none";
    _cache["codehealth"] = true;
    var d = results[0];
    var auditData = results[1];
    var statusData = results[2];
    var standaloneStatusData = results[3];
    var repairData = results[4];
    var orchData = results[5] || {departments: []};
    var entries = auditData.entries || [];
    window._chAuditEntries = entries;

    // Build set of audited module names and their statuses
    var auditedModules = {};
    entries.forEach(function(e) {
      auditedModules[e.module_name] = e.status;
    });

    // Build module status + display name + proposal count + audit date lookups
    var moduleStatusMap = {};
    var moduleDisplayNames = {};
    var moduleProposalCounts = {};
    var moduleAuditDates = {};
    (statusData.modules || []).forEach(function(m) {
      moduleStatusMap[m.module_name] = m.status;
      if (m.display_name) moduleDisplayNames[m.module_name] = m.display_name;
      if (m.pending_proposals) moduleProposalCounts[m.module_name] = m.pending_proposals;
      if (m.last_audit_date) moduleAuditDates[m.module_name] = m.last_audit_date;
    });
    window._chProposalCounts = moduleProposalCounts;
    window._chAuditDates = moduleAuditDates;
    window._chStatusMap = moduleStatusMap;

    window._chDisplayNames = moduleDisplayNames;
    var allMods = d.modules || {};
    var modCount = Object.keys(allMods).length;
    var standaloneCount = Object.keys(allMods).filter(function(k) { return k.startsWith('standalone_'); }).length;
    var websiteKeysAll = ['website_kytranempowerment_current', 'website_kytranempowerment', 'website_creed_ai', 'website_kytran_news', 'website_what_the_fact'];
    var websiteCount = Object.keys(allMods).filter(function(k) { return websiteKeysAll.indexOf(k) !== -1; }).length;
    var platformCount = modCount - standaloneCount - websiteCount;
    _renderCodeHealthSummaryBar(statusData.summary || {}, {platform: platformCount, standalone: standaloneCount, websites: websiteCount});
    _renderCodeHealthStats(d);
    // Show "last scanned" timestamp after stats render
    if (d.snapshot_age) {
      var scanEl = document.getElementById("chLastScanned");
      if (!scanEl) {
        scanEl = document.createElement("div");
        scanEl.id = "chLastScanned";
        scanEl.style.cssText = "text-align:center;font-size:0.65rem;color:rgba(0,229,255,0.5);padding:4px 12px;margin-top:4px;background:rgba(0,229,255,0.06);border:1px solid rgba(0,229,255,0.15);border-radius:4px;";
        var healthScore = document.getElementById("chHealthScore");
        if (healthScore) healthScore.parentNode.appendChild(scanEl);
      }
      var scanDate = new Date(d.snapshot_age);
      var ago = Math.round((Date.now() - scanDate.getTime()) / 60000);
      var agoText = ago < 1 ? "just now" : ago < 60 ? ago + "m ago" : Math.round(ago / 60) + "h ago";
      scanEl.textContent = "Last scanned: " + scanDate.toLocaleTimeString() + " (" + agoText + ")";
    }
    // Separate standalone products from platform modules
    var allModules = d.modules || {};
    var standaloneModules = {};
    var websiteModules = {};
    var platformModules = {};
    // Website keys from registered products (avoid false matches like website_studio)
    var websiteKeys = ['website_kytranempowerment_current', 'website_kytranempowerment', 'website_creed_ai', 'website_kytran_news', 'website_what_the_fact'];
    Object.keys(allModules).forEach(function(key) {
        if (key.startsWith('standalone_')) {
            standaloneModules[key] = allModules[key];
            if (!moduleDisplayNames[key]) {
                var cleanName = key.replace('standalone_', '').replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                moduleDisplayNames[key] = '\u25C6 ' + cleanName;
            }
        } else if (websiteKeys.indexOf(key) !== -1) {
            websiteModules[key] = allModules[key];
            if (!moduleDisplayNames[key]) {
                var cleanName = key.replace('website_', '').replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                moduleDisplayNames[key] = '\u25C7 ' + cleanName;
            }
        } else {
            platformModules[key] = allModules[key];
        }
    });

    _renderModuleChart(allModules, moduleDisplayNames);
    _renderModuleTable(platformModules, auditedModules, moduleStatusMap, moduleDisplayNames);
    // tier_progress lookup removed 2026-09-15 — standalone-status never returned
    // the field and the tier map was never read by the renderer below.
    _renderStandaloneTable(standaloneModules, moduleStatusMap);
    _renderWebsiteTable(websiteModules, moduleStatusMap);
    _renderOrphanTable(d.orphans || {});
    _renderAttentionItems(statusData.summary || {}, d.orphans || {}, d);
    _renderStructuralAudit(d, statusData.summary || {});
    _renderAuditTable(entries);
    _renderRepairBayPipeline(repairData);
    _renderOrchestration(orchData);

    // Audit button handlers — async (one job that scans once + audits all modules,
    // server-side). Replaces the old client loop that re-scanned the tree per module.
    var auditAllBtn = document.getElementById("chAuditAllBtn");
    if (auditAllBtn && !auditAllBtn._bound) {
      auditAllBtn._bound = true;
      auditAllBtn.addEventListener("click", function() {
        auditAllBtn.disabled = true;
        auditAllBtn.style.opacity = "0.6";
        auditAllBtn.textContent = "Auditing…";
        api("/api/code-health/audit", {method: "POST"}).then(function(d) {
          // 409 already_running still returns the live job_id so we can attach to it.
          if (d && (d.job_id || d.already_running)) {
            _chPollJob(d.job_id, "code_health_audit", auditAllBtn, "Auditing", "Audit All Modules");
          } else {
            auditAllBtn.disabled = false; auditAllBtn.style.opacity = "1";
            auditAllBtn.textContent = "Audit All Modules";
          }
        }).catch(function() {
          auditAllBtn.disabled = false; auditAllBtn.style.opacity = "1";
          auditAllBtn.textContent = "Audit All Modules";
        });
      });
    }

    var refreshBtn = document.getElementById("chRefreshScanBtn");
    if (refreshBtn && !refreshBtn._bound) {
      refreshBtn._bound = true;
      refreshBtn.addEventListener("click", function() {
        refreshBtn.disabled = true;
        refreshBtn.style.opacity = "0.6";
        refreshBtn.textContent = "Scanning…";
        api("/api/code-health/scan", {method: "POST"}).then(function(d) {
          if (d && (d.job_id || d.already_running)) {
            _chPollJob(d.job_id, "code_health_scan", refreshBtn, "Scanning", "Refresh Scan");
          } else {
            refreshBtn.disabled = false; refreshBtn.style.opacity = "1";
            refreshBtn.textContent = "Refresh Scan";
          }
        }).catch(function() {
          refreshBtn.disabled = false; refreshBtn.style.opacity = "1";
          refreshBtn.textContent = "Refresh Scan";
        });
      });
    }
  }).catch(function(err) {
    console.error("Code health load error:", err);
  });

  chLoadHistory();
}

// Poll an async Code-Health job (scan/audit/backfill) to completion, updating the
// button label with live progress, then reload the dashboard. Reused by both the
// Refresh-Scan and Audit-All buttons. Polls /api/code-health/job-status/<id> @2s.
function _chPollJob(jobId, jobType, btn, busyLabel, idleLabel) {
  function restore() {
    if (btn) { btn.disabled = false; btn.style.opacity = "1"; btn.textContent = idleLabel; }
  }
  function finish() {
    if (btn) btn.textContent = "Reloading…";
    setTimeout(function() { restore(); _cache = {}; loadCodeHealth(); }, 800);
  }
  if (!jobId) { finish(); return; }
  var tries = 0;
  (function tick() {
    tries++;
    api("/api/code-health/job-status/" + jobId).then(function(j) {
      if (!j || !j.success) { finish(); return; }
      if (j.status === "running") {
        if (btn) btn.textContent = busyLabel + " " + (j.completed || 0) + (j.total ? "/" + j.total : "") + "…";
        if (tries < 600) setTimeout(tick, 2000); else finish();
        return;
      }
      finish(); // completed / failed / cancelled
    }).catch(function() { if (tries < 600) setTimeout(tick, 2000); else finish(); });
  })();
}

// B3 — Department Orchestration panel: who (which LLM/director) owns each Code-Health
// finding (issue -> capability -> department) and the loop status (✓ fixed / ⚠ still-open).
function _renderOrchestration(data) {
  var el = document.getElementById("chOrchestration");
  if (!el) return;
  var depts = (data && data.departments) || [];
  var deptColor = {
    "Security & Compliance": "#ef4444", "Engineering & Technology": "#22d3ee",
    "Documentation & Knowledge": "#8b5cf6", "Analytics & Intelligence": "#f59e0b",
    "Research & Development": "#10b981"
  };
  var cards = depts.map(function(a) {
    var c = deptColor[a.department] || "#94a3b8";
    var dir = a.director ? '<span style="color:' + c + ';font-weight:700">' + escHtml(a.director) + '</span> ' : "";
    return '<div style="border:1px solid ' + c + '33;border-left:3px solid ' + c + ';border-radius:6px;padding:8px 10px;background:rgba(255,255,255,0.02);min-width:158px;">' +
      '<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.5px;">' + dir + '<span style="color:rgba(255,255,255,0.45)">' + escHtml(a.department) + '</span></div>' +
      '<div style="font-size:0.58rem;color:rgba(255,255,255,0.3);margin:3px 0 6px;">' + (a.capabilities || []).join(" · ") + '</div>' +
      '<div style="display:flex;gap:9px;font-size:0.72rem;flex-wrap:wrap;">' +
        '<span title="open / pending">◷ ' + (a.open || 0) + '</span>' +
        '<span title="deployed, awaiting re-verify" style="color:#22d3ee">▲ ' + (a.deployed || 0) + '</span>' +
        '<span title="re-verified fixed" style="color:#10b981">✓ ' + (a.fixed || 0) + '</span>' +
        '<span title="still flagged after deploy (regression)" style="color:#ef4444">⚠ ' + (a.still_open || 0) + '</span>' +
      '</div></div>';
  }).join("");
  el.innerHTML =
    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">' +
      '<span style="font-size:0.8rem;color:#a78bfa;font-weight:600;text-transform:uppercase;letter-spacing:1px;">Department Orchestration</span>' +
      '<button id="chReverifyBtn" style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.4);padding:5px 12px;border-radius:4px;font-size:0.7rem;cursor:pointer;text-transform:uppercase;letter-spacing:1px;">Re-verify Fixes</button>' +
    '</div>' +
    '<div style="font-size:0.6rem;color:rgba(255,255,255,0.3);margin-bottom:8px;">Which LLM owns each finding (issue → capability → department) · ✓ re-verified fixed / ⚠ still-open after deploy</div>' +
    '<div style="display:flex;gap:10px;flex-wrap:wrap;">' + (cards || '<span style="color:rgba(255,255,255,0.3);font-size:0.75rem;">No code-health findings routed yet.</span>') + '</div>';
  var rb = document.getElementById("chReverifyBtn");
  if (rb && !rb._bound) {
    rb._bound = true;
    rb.addEventListener("click", function() {
      rb.disabled = true; rb.style.opacity = "0.6"; rb.textContent = "Re-verifying…";
      api("/api/code-health/reverify", {method: "POST"}).then(function(d) {
        if (d && (d.job_id || d.already_running)) {
          _chPollJob(d.job_id, "code_health_reverify", rb, "Re-verifying", "Re-verify Fixes");
        } else { rb.disabled = false; rb.style.opacity = "1"; rb.textContent = "Re-verify Fixes"; }
      }).catch(function() { rb.disabled = false; rb.style.opacity = "1"; rb.textContent = "Re-verify Fixes"; });
    });
  }
}

function _renderCodeHealthSummaryBar(summary, counts) {
  var el = document.getElementById("chStatusSummary");
  if (!el) {
    // Insert summary bar before the stats grid if container doesn't exist yet
    var statsEl = document.getElementById("chTotalFiles");
    if (statsEl) {
      var parent = statsEl.closest(".cs-grid, .cs-stats-grid");
      if (parent && parent.parentNode) {
        el = document.createElement("div");
        el.id = "chStatusSummary";
        parent.parentNode.insertBefore(el, parent);
      }
    }
  }
  if (!el) return;

  var g = summary.green || 0;
  var p = summary.purple || 0;
  var o = summary.orange || 0;
  var y = summary.yellow || 0;
  var r = summary.red || 0;
  window._chUnauditedCount = r;
  var total = g + p + o + y + r;

  // Build summary bar using safe DOM methods
  el.style.cssText = "display:flex;gap:1rem;align-items:center;justify-content:center;padding:0.6rem 1rem;margin-bottom:1rem;border-radius:8px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);flex-wrap:wrap;text-align:center;";
  while (el.firstChild) el.removeChild(el.firstChild);

  var label = document.createElement("span");
  label.style.cssText = "font-size:0.8rem;color:rgba(255,255,255,0.5);margin-right:0.5rem;";
  label.textContent = "System Health";
  el.appendChild(label);

  var items = [
    {color: "#22c55e", count: g, text: "clean"},
    {color: "#a78bfa", count: p, text: "in repair"},
    {color: "#f59e0b", count: o, text: "issues"},
    {color: "#eab308", count: y, text: "stale"},
    {color: "#ef4444", count: r, text: "unaudited"}
  ];
  items.forEach(function(item) {
    var wrap = document.createElement("span");
    wrap.style.cssText = "display:inline-flex;align-items:center;gap:0.3rem;";
    var dot = document.createElement("span");
    dot.style.cssText = "width:8px;height:8px;border-radius:50%;display:inline-block;background:" + item.color + ";";
    var txt = document.createElement("span");
    txt.style.cssText = "color:" + item.color + ";font-weight:600;font-size:0.85rem;";
    txt.textContent = item.count + " " + item.text;
    wrap.appendChild(dot);
    wrap.appendChild(txt);
    el.appendChild(wrap);
  });

  counts = counts || {};
  var parts = [];
  if (counts.platform) parts.push(counts.platform + " modules");
  if (counts.standalone) parts.push(counts.standalone + " standalone");
  if (counts.websites) parts.push(counts.websites + " websites");
  var trackingText = parts.length ? parts.join(" \u00b7 ") : (total + " modules");

  var totalSpan = document.createElement("span");
  totalSpan.style.cssText = "font-size:0.7rem;color:rgba(255,255,255,0.3);width:100%;text-align:center;margin-top:2px;";
  totalSpan.textContent = trackingText;
  el.appendChild(totalSpan);
}

function _renderCodeHealthStats(d) {
  var fmt = function(n) { return (n || 0).toLocaleString(); };
  setHtml("chTotalFiles", fmt(d.total_files));
  setHtml("chTotalLines", fmt(d.total_lines));
  // Health score badge (safe DOM construction — data from our own scanner)
  var hs = d.health_score || {};
  var scoreEl = document.getElementById("chHealthScore");
  if (scoreEl) {
    scoreEl.textContent = "";
    var score = hs.score || 0;
    var grade = hs.grade || "?";
    var color = score >= 90 ? "#10b981" : score >= 70 ? "#3b82f6" : score >= 50 ? "#f59e0b" : "#ef4444";
    var numSpan = document.createElement("span");
    numSpan.style.cssText = "font-size:2rem;font-weight:700;color:" + color;
    numSpan.textContent = score;
    var maxSpan = document.createElement("span");
    maxSpan.style.cssText = "font-size:0.9rem;color:rgba(255,255,255,0.5);margin-left:4px";
    maxSpan.textContent = "/100";
    var gradeDiv = document.createElement("div");
    gradeDiv.style.cssText = "font-size:1.2rem;font-weight:600;color:" + color + ";margin-top:2px";
    gradeDiv.textContent = "Grade: " + grade;
    scoreEl.appendChild(numSpan);
    scoreEl.appendChild(maxSpan);
    scoreEl.appendChild(gradeDiv);
    // Show unaudited warning if applicable
    var deductions = hs.deductions || [];
    var unaudited = window._chUnauditedCount || 0;
    if (unaudited > 0 || deductions.length > 0) {
      var warnDiv = document.createElement("div");
      warnDiv.style.cssText = "font-size:0.6rem;color:#f59e0b;margin-top:4px;opacity:0.8;";
      warnDiv.textContent = unaudited > 0 ? unaudited + " modules not audited" : deductions.length + " deduction(s)";
      scoreEl.appendChild(warnDiv);
    }
  }
  var langs = [
    {id: "chPythonLines", key: "python"},
    {id: "chJsLines", key: "js"},
    {id: "chHtmlLines", key: "html"},
    {id: "chCssLines", key: "css"},
    {id: "chSqlLines", key: "sql"},
    {id: "chShellLines", key: "shell"},
    {id: "chJsonLines", key: "json"},
    {id: "chYamlLines", key: "yaml"},
    {id: "chMarkdownLines", key: "markdown"},
    {id: "chGoLines", key: "go"},
    {id: "chSvgLines", key: "svg"},
    {id: "chConfigLines", key: "config"},
    {id: "chTextLines", key: "text"}
  ];
  langs.forEach(function(l) {
    var data = d[l.key] || {files: 0, lines: 0};
    var el = document.getElementById(l.id);
    if (el) {
      el.textContent = fmt(data.lines);
      var sub = el.parentNode.querySelector(".ch-stat-files");
      if (!sub) {
        sub = document.createElement("div");
        sub.className = "ch-stat-files";
        sub.style.cssText = "font-size:0.6rem;color:rgba(255,255,255,0.35);margin-top:2px;";
        el.parentNode.insertBefore(sub, el.nextSibling);
      }
      sub.textContent = fmt(data.files) + " files";
    }
  });
}

function _renderAttentionItems(summary, orphans, d) {
  var el = document.getElementById("chAttentionItems");
  if (!el) return;
  while (el.firstChild) el.removeChild(el.firstChild);

  var items = [];
  var r = summary.red || 0;
  var o = summary.orange || 0;
  var y = summary.yellow || 0;

  // Hardcoded safe icon names — no user input in data-lucide attributes
  if (r > 0) items.push({label: "Unaudited modules", count: r, color: "#ef4444", icon: "alert-triangle", severity: "critical", action: "Audit Now", actionFn: function() {
    var btn = document.getElementById("chAuditAllBtn");
    if (btn) btn.click();
  }, repairType: null});
  if (o > 0) items.push({label: "Modules with issues", count: o, color: "#f59e0b", icon: "alert-circle", severity: "warning", action: "View Repairs", actionFn: function() {
    window.location.href = "/tools/repair-bay";
  }, repairType: "modules_with_issues"});
  if (y > 0) items.push({label: "Stale audits (needs re-scan)", count: y, color: "#eab308", icon: "clock", severity: "info", action: "Re-audit", actionFn: function() {
    var btn = document.getElementById("chAuditAllBtn");
    if (btn) btn.click();
  }, repairType: null});

  // Modules changed since last audit
  var changed = d.modules_changed || [];
  if (changed.length > 0) items.push({label: "Modules changed since last audit", count: changed.length, color: "#3b82f6", icon: "git-commit", severity: "info", action: "Audit Changed", actionFn: function() {
    var btn = document.getElementById("chAuditAllBtn");
    if (btn) btn.click();
  }, repairType: null});

  // Orphan files
  var orphanTotal = 0;
  if (orphans) {
    Object.keys(orphans).forEach(function(k) {
      var v = orphans[k];
      orphanTotal += Array.isArray(v) ? v.length : (typeof v === "number" ? v : 0);
    });
  }
  if (orphanTotal > 0) items.push({label: "Orphan files (unmapped)", count: orphanTotal, color: "#f97316", icon: "file-question", severity: "warning", action: null, actionFn: null, repairType: "orphan_files"});

  // Deductions removed — they appear in the Structural Audit Score Deductions card

  if (items.length === 0) {
    var allGood = document.createElement("div");
    allGood.className = "ch-attn-all-clear";
    var checkIcon = document.createElement("i");
    checkIcon.setAttribute("data-lucide", "check-circle-2");
    checkIcon.style.cssText = "width:20px;height:20px;color:#10b981;";
    allGood.appendChild(checkIcon);
    allGood.appendChild(document.createTextNode(" All clear \u2014 no issues detected"));
    el.appendChild(allGood);
    if (typeof lucide !== "undefined") lucide.createIcons();
    var orphSec = document.getElementById("chOrphanSection");
    if (orphSec && orphanTotal === 0) orphSec.style.display = "none";
    return;
  }

  items.forEach(function(item) {
    var card = document.createElement("div");
    card.className = "ch-attention-card ch-attn-" + item.severity;

    // Severity icon with glow
    var iconWrap = document.createElement("div");
    iconWrap.className = "ch-attn-icon";
    iconWrap.style.color = item.color;
    var iconEl = document.createElement("i");
    iconEl.setAttribute("data-lucide", item.icon);
    iconWrap.appendChild(iconEl);
    card.appendChild(iconWrap);

    // Label
    var info = document.createElement("div");
    info.className = "ch-attn-info";
    var label = document.createElement("span");
    label.className = "ch-attn-label";
    label.textContent = item.label;
    info.appendChild(label);
    card.appendChild(info);

    // Count badge
    var count = document.createElement("span");
    count.className = "ch-attn-count";
    count.style.color = item.color;
    count.style.borderColor = item.color + "40";
    count.style.background = item.color + "15";
    count.textContent = item.count;
    card.appendChild(count);

    // Action button
    if (item.action && item.actionFn) {
      var btn = document.createElement("button");
      btn.className = "ch-attn-action";
      btn.style.color = item.color;
      btn.style.borderColor = item.color + "50";
      btn.textContent = item.action;
      btn.onclick = item.actionFn;
      card.appendChild(btn);
    }

    // Submit to Repair Bay button
    if (item.repairType) {
      var repairBtn = document.createElement("button");
      repairBtn.className = "ch-attn-action ch-attn-repair";
      repairBtn.textContent = "Repair Bay";
      repairBtn.onclick = (function(type, lbl, btnEl) {
        return function() {
          btnEl.disabled = true;
          btnEl.textContent = "Submitting...";
          api("/api/code-health/submit-attention", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({type: type, label: lbl})
          }).then(function(r) {
            if (r.success) {
              btnEl.textContent = r.proposals_created + " submitted";
              btnEl.style.color = "#10b981";
              btnEl.style.borderColor = "rgba(16,185,129,0.5)";
            } else {
              btnEl.textContent = "Failed";
              btnEl.style.color = "#ef4444";
              btnEl.disabled = false;
            }
          }).catch(function() {
            btnEl.textContent = "Error";
            btnEl.style.color = "#ef4444";
            btnEl.disabled = false;
          });
        };
      })(item.repairType, item.label, repairBtn);
      card.appendChild(repairBtn);
    }

    el.appendChild(card);
  });

  if (typeof lucide !== "undefined") lucide.createIcons();

  var orphSec = document.getElementById("chOrphanSection");
  if (orphSec && orphanTotal === 0) orphSec.style.display = "none";
}

function _renderRepairBayPipeline(data) {
  var el = document.getElementById("chRepairBayPipeline");
  if (!el) return;
  while (el.firstChild) el.removeChild(el.firstChild);

  if (!data || !data.success) {
    var msg = document.createElement("div");
    msg.style.cssText = "padding:1.5rem;text-align:center;color:rgba(255,255,255,0.3);font-size:0.85rem;";
    msg.textContent = "Repair Bay data unavailable";
    el.appendChild(msg);
    return;
  }

  var qStatus = data.queue && data.queue.by_status ? data.queue.by_status : {};
  var qSeverity = data.queue && data.queue.by_severity ? data.queue.by_severity : {};
  var pStatus = data.proposals && data.proposals.by_status ? data.proposals.by_status : {};
  var pTotal = data.proposals ? data.proposals.total || 0 : 0;
  var qTotal = data.queue ? data.queue.total || 0 : 0;

  // Quick summary bar
  var summaryBar = document.createElement("div");
  summaryBar.style.cssText = "display:flex;justify-content:center;gap:20px;padding:10px;margin-bottom:12px;background:rgba(255,255,255,0.02);border-radius:6px;flex-wrap:wrap;";

  var summaryItems = [
    {label: "Repair Queue", value: qTotal, color: qTotal > 0 ? "#f59e0b" : "#22c55e"},
    {label: "Proposals", value: pTotal, color: pTotal > 0 ? "#3b82f6" : "#22c55e"},
    {label: "Deployed", value: pStatus.deployed || 0, color: "#10b981"},
    {label: "Pending Review", value: (pStatus.pending || 0) + (pStatus.pending_approval || 0), color: (pStatus.pending || 0) > 0 ? "#f59e0b" : "#22c55e"}
  ];
  summaryItems.forEach(function(item) {
    var wrap = document.createElement("div");
    wrap.style.cssText = "text-align:center;";
    var val = document.createElement("div");
    val.style.cssText = "font-size:1.2rem;font-weight:700;color:" + item.color + ";";
    val.textContent = item.value;
    var lbl = document.createElement("div");
    lbl.style.cssText = "font-size:0.6rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.5px;";
    lbl.textContent = item.label;
    wrap.appendChild(val);
    wrap.appendChild(lbl);
    summaryBar.appendChild(wrap);
  });
  el.appendChild(summaryBar);

  var auditFlow = data.code_health;
  if (auditFlow) {
    var nextSteps = document.createElement("div");
    nextSteps.className = "ch-pipeline-detail";
    nextSteps.textContent = "Code Health: " + auditFlow.active + " active repair records; " +
      auditFlow.manual_review + " approved refactor/security findings need manual review; " +
      auditFlow.ready_for_review + " fixes ready for review; " +
      auditFlow.pending_approval + " pending proposals/approvals; " +
      auditFlow.dispatch_attempted + " attempted dispatches need outcome review. " +
      "Queue and proposal totals below cover all Repair Bay work. Approval permits work; " +
      "completion requires a reviewed PR, deployment, and re-verification.";
    el.appendChild(nextSteps);
  }

  // Pipeline flow cards
  var flow = document.createElement("div");
  flow.className = "ch-pipeline-flow";

  var stages = [
    {label: "PENDING", count: (qStatus.pending || 0) + (pStatus.pending || 0), color: "#f59e0b", detail: _severityDetail(qSeverity)},
    {label: "IN REVIEW", count: (pStatus.pending_approval || 0) + (pStatus.ready_for_review || 0), color: "#3b82f6", detail: ""},
    {label: "APPROVED", count: pStatus.approved || 0, color: "#8b5cf6", detail: ""},
    {label: "DEPLOYED", count: pStatus.deployed || 0, color: "#10b981", detail: ""}
  ];

  stages.forEach(function(s) {
    var card = document.createElement("div");
    card.className = "ch-pipeline-card";

    var num = document.createElement("div");
    num.className = "ch-pipeline-count";
    num.style.color = s.color;
    num.textContent = s.count;
    card.appendChild(num);

    var lbl = document.createElement("div");
    lbl.className = "ch-pipeline-label";
    lbl.textContent = s.label;
    card.appendChild(lbl);

    if (s.detail) {
      var det = document.createElement("div");
      det.className = "ch-pipeline-detail";
      det.textContent = s.detail;
      card.appendChild(det);
    }

    flow.appendChild(card);
  });
  el.appendChild(flow);

  // Status breakdown (compact chips)
  if (Object.keys(pStatus).length > 0) {
    var chipRow = document.createElement("div");
    chipRow.style.cssText = "display:flex;gap:6px;flex-wrap:wrap;margin-bottom:1rem;justify-content:center;";
    var statusColors = {pending:"#f59e0b",pending_approval:"#f59e0b",ready_for_review:"#3b82f6",approved:"#8b5cf6",deployed:"#10b981",archived:"#64748b",fix_requested:"#ef4444",failed:"#ef4444"};
    Object.keys(pStatus).forEach(function(k) {
      if (pStatus[k] === 0) return;
      var chip = document.createElement("span");
      var c = statusColors[k] || "#999";
      chip.style.cssText = "font-size:0.6rem;padding:2px 8px;border-radius:3px;background:" + c + "15;color:" + c + ";border:1px solid " + c + "33;";
      chip.textContent = pStatus[k] + " " + k.replace(/_/g, " ");
      chipRow.appendChild(chip);
    });
    el.appendChild(chipRow);
  }

  // Governance actions table
  var govActions = data.governance || [];
  if (govActions.length > 0) {
    var tableWrap = document.createElement("div");
    tableWrap.style.cssText = "overflow-x:auto;";

    var table = document.createElement("table");
    table.className = "ch-governance-table";

    var thead = document.createElement("thead");
    var hrow = document.createElement("tr");
    ["Action", "Details", "When"].forEach(function(h) {
      var th = document.createElement("th");
      th.textContent = h;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    govActions.forEach(function(g) {
      var row = document.createElement("tr");

      var tdAction = document.createElement("td");
      tdAction.style.cssText = "color:#f59e0b;font-weight:600;font-size:0.75rem;white-space:nowrap;";
      tdAction.textContent = (g.event || "").replace(/_/g, " ");
      row.appendChild(tdAction);

      var tdDetails = document.createElement("td");
      var details = g.details || "";
      if (typeof details === "object") details = JSON.stringify(details);
      tdDetails.textContent = details.length > 80 ? details.substring(0, 80) + "..." : details;
      row.appendChild(tdDetails);

      var tdWhen = document.createElement("td");
      tdWhen.style.cssText = "white-space:nowrap;color:rgba(255,255,255,0.35);font-size:0.75rem;";
      tdWhen.textContent = g.timestamp ? _timeAgo(new Date(g.timestamp)) : "—";
      row.appendChild(tdWhen);

      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    el.appendChild(tableWrap);
  } else {
    var noGov = document.createElement("div");
    noGov.style.cssText = "padding:1rem;text-align:center;color:rgba(255,255,255,0.25);font-size:0.8rem;";
    noGov.textContent = "No self-healing actions recorded yet";
    el.appendChild(noGov);
  }
}

function _severityDetail(sev) {
  if (!sev) return "";
  var parts = [];
  if (sev.critical) parts.push(sev.critical + " crit");
  if (sev.high) parts.push(sev.high + " high");
  if (sev.medium) parts.push(sev.medium + " med");
  if (sev.low) parts.push(sev.low + " low");
  return parts.join(", ");
}

function _timeAgo(date) {
  var secs = Math.floor((Date.now() - date.getTime()) / 1000);
  if (secs < 60) return secs + "s ago";
  var mins = Math.floor(secs / 60);
  if (mins < 60) return mins + "m ago";
  var hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + "h ago";
  var days = Math.floor(hrs / 24);
  return days + "d ago";
}

// Store chart data globally for re-sorting
var _chModuleData = null;
var _chModuleDisplayNames = null;

function _addOption(sel, value, text) {
  var opt = document.createElement("option");
  opt.value = value;
  opt.textContent = text;
  sel.appendChild(opt);
}

function _buildChartControls(canvas) {
  if (document.getElementById("chChartControls")) return;
  var wrapper = canvas.parentElement;
  var controls = document.createElement("div");
  controls.id = "chChartControls";
  controls.style.cssText = "display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap;";

  var sortLabel = document.createElement("span");
  sortLabel.style.cssText = "color:rgba(255,255,255,0.5);font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;";
  sortLabel.textContent = "Sort:";

  var sortSel = document.createElement("select");
  sortSel.id = "chSortMode";
  sortSel.style.cssText = "background:#0a1628;color:#00e5ff;border:1px solid rgba(0,229,255,0.3);padding:4px 8px;border-radius:4px;font-size:0.75rem;cursor:pointer;";
  _addOption(sortSel, "lines-desc", "Lines (High \u2192 Low)");
  _addOption(sortSel, "lines-asc", "Lines (Low \u2192 High)");
  _addOption(sortSel, "files-desc", "Files (High \u2192 Low)");
  _addOption(sortSel, "name-asc", "Name (A \u2192 Z)");
  sortSel.onchange = function() { _renderModuleChart(_chModuleData, _chModuleDisplayNames); };

  var filterLabel = document.createElement("span");
  filterLabel.style.cssText = "color:rgba(255,255,255,0.5);font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;margin-left:10px;";
  filterLabel.textContent = "Show:";

  var filterSel = document.createElement("select");
  filterSel.id = "chFilterMode";
  filterSel.style.cssText = "background:#0a1628;color:#00e5ff;border:1px solid rgba(0,229,255,0.3);padding:4px 8px;border-radius:4px;font-size:0.75rem;cursor:pointer;";
  _addOption(filterSel, "all", "All Modules");
  _addOption(filterSel, "platform", "Platform Only");
  _addOption(filterSel, "standalone", "Standalone Only");
  _addOption(filterSel, "website", "Websites Only");
  filterSel.onchange = function() { _renderModuleChart(_chModuleData, _chModuleDisplayNames); };

  controls.appendChild(sortLabel);
  controls.appendChild(sortSel);
  controls.appendChild(filterLabel);
  controls.appendChild(filterSel);
  wrapper.insertBefore(controls, canvas);
}

function _renderModuleChart(modules, displayNames) {
  var canvas = document.getElementById("chModuleChart");
  if (!canvas) return;
  displayNames = displayNames || {};
  _chModuleData = modules;
  _chModuleDisplayNames = displayNames;

  // Build sort/filter controls if not present
  _buildChartControls(canvas);

  var sortMode = (document.getElementById("chSortMode") || {}).value || "lines-desc";
  var filterMode = (document.getElementById("chFilterMode") || {}).value || "all";

  // Responsive: show fewer modules on mobile, all on desktop
  var maxBars = window.innerWidth < 480 ? 15 : window.innerWidth < 768 ? 25 : 60;

  var allKeys = Object.keys(modules);

  // Apply filter
  if (filterMode === "platform") {
    allKeys = allKeys.filter(function(k) { return !k.startsWith("standalone_") && !k.startsWith("website_"); });
  } else if (filterMode === "standalone") {
    allKeys = allKeys.filter(function(k) { return k.startsWith("standalone_"); });
  } else if (filterMode === "website") {
    allKeys = allKeys.filter(function(k) { return k.startsWith("website_"); });
  }

  // Apply sort
  if (sortMode === "lines-desc") {
    allKeys.sort(function(a, b) { return (modules[b].lines || 0) - (modules[a].lines || 0); });
  } else if (sortMode === "lines-asc") {
    allKeys.sort(function(a, b) { return (modules[a].lines || 0) - (modules[b].lines || 0); });
  } else if (sortMode === "name-asc") {
    allKeys.sort(function(a, b) { return (displayNames[a] || a).localeCompare(displayNames[b] || b); });
  } else if (sortMode === "files-desc") {
    allKeys.sort(function(a, b) { return (modules[b].files || 0) - (modules[a].files || 0); });
  }

  var names = allKeys.slice(0, maxBars);

  var pyData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.python ? bt.python.lines : 0; });
  var jsData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.js ? bt.js.lines : 0; });
  var htmlData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.html ? bt.html.lines : 0; });
  var cssData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.css ? bt.css.lines : 0; });
  var sqlData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.sql ? bt.sql.lines : 0; });
  var shellData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.shell ? bt.shell.lines : 0; });
  var jsonData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.json ? bt.json.lines : 0; });
  var yamlData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.yaml ? bt.yaml.lines : 0; });
  var mdData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.markdown ? bt.markdown.lines : 0; });
  var goData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.go ? bt.go.lines : 0; });
  var svgData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.svg ? bt.svg.lines : 0; });
  var configData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.config ? bt.config.lines : 0; });
  var textData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.text ? bt.text.lines : 0; });
  var otherData = names.map(function(n) { var bt = modules[n].by_type || {}; return bt.other ? bt.other.lines : 0; });

  var rowH = window.innerWidth < 480 ? 24 : 28;
  var barHeight = Math.max(names.length * rowH, 300);
  canvas.style.height = barHeight + "px";
  canvas.height = barHeight;
  // Let container scroll — don't override max-height, just ensure min-height
  var container = canvas.parentElement;
  if (container) container.style.minHeight = Math.min(barHeight + 30, 600) + "px";

  if (_chModuleChart) _chModuleChart.destroy();
  _chModuleChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: names.map(function(n) { return displayNames[n] || n; }),
      datasets: [
        { label: "Python", data: pyData, backgroundColor: "rgba(139, 92, 246, 0.7)", borderWidth: 0 },
        { label: "HTML", data: htmlData, backgroundColor: "rgba(245, 158, 11, 0.7)", borderWidth: 0 },
        { label: "JavaScript", data: jsData, backgroundColor: "rgba(0, 204, 255, 0.7)", borderWidth: 0 },
        { label: "CSS", data: cssData, backgroundColor: "rgba(34, 197, 94, 0.7)", borderWidth: 0 },
        { label: "SQL", data: sqlData, backgroundColor: "rgba(253, 224, 71, 0.7)", borderWidth: 0 },
        { label: "JSON", data: jsonData, backgroundColor: "rgba(45, 212, 191, 0.7)", borderWidth: 0 },
        { label: "Shell", data: shellData, backgroundColor: "rgba(239, 68, 68, 0.7)", borderWidth: 0 },
        { label: "YAML", data: yamlData, backgroundColor: "rgba(6, 182, 212, 0.7)", borderWidth: 0 },
        { label: "Markdown", data: mdData, backgroundColor: "rgba(167, 139, 250, 0.7)", borderWidth: 0 },
        { label: "Go", data: goData, backgroundColor: "rgba(56, 189, 248, 0.7)", borderWidth: 0 },
        { label: "SVG", data: svgData, backgroundColor: "rgba(251, 146, 60, 0.7)", borderWidth: 0 },
        { label: "Config", data: configData, backgroundColor: "rgba(148, 163, 184, 0.7)", borderWidth: 0 },
        { label: "Text", data: textData, backgroundColor: "rgba(100, 116, 139, 0.7)", borderWidth: 0 },
        { label: "Other", data: otherData, backgroundColor: "rgba(168, 162, 255, 0.7)", borderWidth: 0 }
      ]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      plugins: {
        legend: {
          labels: {
            color: "rgba(255,255,255,0.6)",
            boxWidth: window.innerWidth < 480 ? 8 : 12,
            padding: window.innerWidth < 480 ? 6 : 10,
            font: { size: window.innerWidth < 480 ? 9 : 11 }
          }
        }
      },
      scales: {
        x: { stacked: true, ticks: { color: "rgba(255,255,255,0.5)", font: { size: window.innerWidth < 480 ? 8 : 11 } }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { stacked: true, ticks: { color: "rgba(255,255,255,0.7)", font: { size: window.innerWidth < 480 ? 9 : 11 }, padding: 4 }, grid: { color: "rgba(255,255,255,0.06)", drawTicks: false } }
      }
    }
  });
}

// ── Token Economy (Code Health tab) ──────────────────────────────
function _fmtTok(n) {
  n = n || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return "" + n;
}

// Blend cloud-orange (0% local) ↔ local-purple (100% local) by an agent's local%,
// so the agent name's COLOR represents where its models actually ran (mix = midpoint).
function _mixLocalCloudColor(pct) {
  var t = Math.max(0, Math.min(1, (pct == null ? 100 : pct) / 100));
  var orange = [245, 158, 11];   // cloud
  var purple = [167, 139, 250];  // local
  var r = Math.round(orange[0] + (purple[0] - orange[0]) * t);
  var g = Math.round(orange[1] + (purple[1] - orange[1]) * t);
  var b = Math.round(orange[2] + (purple[2] - orange[2]) * t);
  return "rgb(" + r + "," + g + "," + b + ")";
}

var _teCache = {};            // {range: {t: epoch_ms, d: payload}}
var _teClientTTL = 300000;    // 5 min — instant in-session tab re-opens

// --- Token Buckets: accounting-integrity view (WHERE every token goes). Loaded
// alongside loadTokenEconomy so the same range buttons drive both panels. ---
var _tbCache = {};
var _tbClientTTL = 300000;
var _TB_COLORS = { agent: "#34d399", cloud: "#f59e0b", infra: "#60a5fa", markers: "#64748b", other: "#f43f5e", estimated: "#a78bfa" };
var _chBucketChart = null;
function _tbFmt(n) { n = +n || 0; if (n >= 1e6) return (n / 1e6).toFixed(2) + "M"; if (n >= 1e3) return (n / 1e3).toFixed(1) + "k"; return String(n); }
function _renderTokenBuckets(d) {
  var el = document.getElementById("teBuckets");
  if (!el || !d || !d.buckets) return;
  var total = d.total_tokens || 0;
  var html = '<div class="tb-flow">';
  d.buckets.forEach(function(b) {
    var pct = total ? (100 * b.tokens / total) : 0;
    if (pct > 0) html += '<div style="width:' + pct.toFixed(2) + "%;background:" + (_TB_COLORS[b.key] || "#888") + '" title="' + escHtml(b.label) + '"></div>';
  });
  html += '</div><div class="tb-legend">';
  d.buckets.forEach(function(b) {
    html += '<div class="tb-row"><span class="tb-sw" style="background:' + (_TB_COLORS[b.key] || "#888") + '"></span>'
      + '<span class="tb-nm">' + escHtml(b.label) + "<span>" + escHtml(b.desc || "") + "</span></span>"
      + '<span class="tb-tk">' + _tbFmt(b.tokens) + "</span>"
      + '<span class="tb-rw">' + (b.rows || 0).toLocaleString() + " rows</span></div>";
  });
  html += "</div>";
  el.innerHTML = html;

  // Buckets over time — stacked area (mirrors chTokenChart). Markers omitted (0-token).
  var cv = document.getElementById("chBucketChart");
  if (cv && window.Chart && d.series) {
    var labels = d.series.map(function(s) { return s.label || s.day; });
    var mk = function(k) { return d.series.map(function(s) { return s[k] || 0; }); };
    if (_chBucketChart) _chBucketChart.destroy();
    _chBucketChart = new Chart(cv, {
      type: "line",
      data: { labels: labels, datasets: [
        { label: "Agent · local", data: mk("agent"), stack: "b", borderColor: _TB_COLORS.agent, backgroundColor: "rgba(52,211,153,0.30)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
        { label: "Cloud / CLI", data: mk("cloud"), stack: "b", borderColor: _TB_COLORS.cloud, backgroundColor: "rgba(245,158,11,0.28)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
        { label: "Infrastructure", data: mk("infra"), stack: "b", borderColor: _TB_COLORS.infra, backgroundColor: "rgba(96,165,250,0.30)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
        { label: "Stray", data: mk("other"), stack: "b", borderColor: _TB_COLORS.other, backgroundColor: "rgba(244,63,94,0.30)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
        { label: "Estimated · backfill", data: mk("estimated"), stack: "b", borderColor: _TB_COLORS.estimated, backgroundColor: "rgba(167,139,250,0.25)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 }
      ]},
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 0 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "rgba(255,255,255,0.6)", boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: function(c) { return c.dataset.label + ": " + _tbFmt(c.parsed.y); } } }
        },
        scales: {
          x: { ticks: { color: "rgba(255,255,255,0.5)", maxTicksLimit: 8, font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.05)" } },
          y: { stacked: true, ticks: { color: "rgba(255,255,255,0.5)", font: { size: 10 }, callback: function(v) { return _tbFmt(v); } }, grid: { color: "rgba(255,255,255,0.06)" } }
        }
      }
    });
  }
}
function loadTokenBuckets(rng, force) {
  rng = String(rng || 30);
  var c = _tbCache[rng];
  if (!force && c && (Date.now() - c.t) < _tbClientTTL) { _renderTokenBuckets(c.d); return; }
  api("/api/code-health/token-buckets?range=" + encodeURIComponent(rng) + (force ? "&refresh=1" : ""))
    .then(function(d) { _tbCache[rng] = { t: Date.now(), d: d }; _renderTokenBuckets(d); })
    .catch(function() { /* non-critical — never break the tab */ });
}

// rng is a range token: "1h" | "24h" | 7 | 30 | 90 | 365. Numbers keep the old
// callers working (loadTokenEconomy(30)); they map to the same daily windows.
function loadTokenEconomy(rng, force) {
  rng = String(rng || 30);
  try { loadTokenBuckets(rng, force); } catch (e) {}
  var btns = document.querySelectorAll(".te-range");
  for (var i = 0; i < btns.length; i++) {
    btns[i].classList.toggle("active", String(btns[i].getAttribute("data-te")) === rng);
  }
  // Render instantly from client cache when fresh — no server round-trip.
  var c = _teCache[rng];
  if (!force && c && (Date.now() - c.t) < _teClientTTL) {
    _renderTokenEconomy(c.d);
    _tePrewarm();
    return;
  }
  api("/api/code-health/token-usage?range=" + encodeURIComponent(rng) + (force ? "&refresh=1" : ""))
    .then(function(d) { _teCache[rng] = { t: Date.now(), d: d }; _renderTokenEconomy(d); _tePrewarm(); })
    .catch(function() { /* token economy is non-critical — never break the tab */ });
}

// Background-prefetch every window once so clicking 1H/24H/7D/30D/90D/ALL is instant
// (no stutter). Runs after the first render; staggered so we don't hammer the DB.
var _tePrewarmed = false;
function _tePrewarm() {
  if (_tePrewarmed) return;
  _tePrewarmed = true;
  var windows = ["1h", "24h", 7, 30, 90, 365];
  windows.forEach(function(w, i) {
    var k = String(w);
    if (_teCache[k]) return;
    setTimeout(function() {
      if (_teCache[k]) return;
      api("/api/code-health/token-usage?range=" + encodeURIComponent(k))
        .then(function(j) { _teCache[k] = { t: Date.now(), d: j }; })
        .catch(function() {});
    }, 400 * (i + 1));
  });
}

function _renderTokenEconomy(d) {
  if (!d || !d.totals) return;
  var t = d.totals;
  var sum = document.getElementById("teSummary");
  if (sum) {
    sum.innerHTML =
      '<div class="te-cell"><div class="v" style="color:#22c55e">' + _fmtTok(t.local_tokens) + '</div><div class="l">Local tokens</div><div class="l" style="color:rgba(255,255,255,0.3)">' + (t.local_disp || 0).toLocaleString() + ' dispatches</div></div>' +
      '<div class="te-cell"><div class="v" style="color:#f59e0b">' + _fmtTok(t.external_tokens) + '</div><div class="l">External (cloud)</div><div class="l" style="color:rgba(255,255,255,0.3)">' + (t.external_disp || 0).toLocaleString() + ' dispatches</div></div>' +
      '<div class="te-cell"><div class="v" style="color:#22d3ee">' + (t.pct_local != null ? t.pct_local : 100) + '%</div><div class="l">Run locally</div></div>' +
      '<div class="te-cell"><div class="v" style="color:rgba(148,163,184,0.9)">' + _fmtTok(t.estimated_tokens) + '</div><div class="l">Estimated (backfill)</div></div>';
  }
  var ag = document.getElementById("teAgents");
  if (ag) {
    var rows = (d.agents || []).map(function(a) {
      // Models column: token count next to each model; CLOUD models (name + count) in orange.
      var models = (a.models || []).map(function(m) {
        var nameCol = m.cloud ? "#f59e0b" : "rgba(255,255,255,0.6)";
        var tokCol = m.cloud ? "#f59e0b" : "rgba(167,139,250,0.6)";
        return '<span style="color:' + nameCol + '">' + escHtml(m.model || "?") + '</span> <span style="color:' + tokCol + '">' + _fmtTok(m.tokens) + '</span>';
      }).join(", ");
      var ext = a.external_tokens > 0 ? ' <span title="uses cloud" style="color:#f59e0b">☁</span>' : "";
      // Tokens column = agent total only (per-model breakdown lives in the Models column).
      var tokCell = '<span style="color:#a78bfa">' + _fmtTok(a.tokens) + '</span>';
      // Agent name color = BLEND of cloud-orange↔local-purple by its local%, so a
      // 50/50 agent sits exactly in the middle (not a hard cutoff).
      var pct = a.local_pct != null ? a.local_pct : 100;
      var agentCol = _mixLocalCloudColor(pct);
      return '<tr><td style="color:' + agentCol + '">' + escHtml(a.agent || "") + ext + '</td><td>' + models + '</td><td style="text-align:right">' + (a.dispatches || 0).toLocaleString() + '</td><td style="text-align:right">' + tokCell + '</td><td style="text-align:right">' + pct + '%</td></tr>';
    }).join("");
    ag.innerHTML = '<table><thead><tr><th>Agent</th><th>Model(s)</th><th style="text-align:right">Disp.</th><th style="text-align:right">Tokens</th><th style="text-align:right">Local%</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="5" style="text-align:center;color:rgba(255,255,255,0.3)">No token data in range</td></tr>') + '</tbody></table>';
  }
  var canvas = document.getElementById("chTokenChart");
  if (canvas && window.Chart) {
    // Sub-day ranges (1h/24h) carry a server-rendered Toronto-local label (HH:MM);
    // daily ranges fall back to the ISO date in `day`.
    var labels = (d.series || []).map(function(s) { return s.label || s.day; });
    var local = (d.series || []).map(function(s) { return s.local; });
    var ext = (d.series || []).map(function(s) { return s.external; });
    var est = (d.series || []).map(function(s) { return s.estimated; });
    if (_chTokenChart) _chTokenChart.destroy();
    _chTokenChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          { label: "Local", data: local, stack: "real", borderColor: "#22c55e", backgroundColor: "rgba(34,197,94,0.25)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
          { label: "External (cloud)", data: ext, stack: "real", borderColor: "#f59e0b", backgroundColor: "rgba(245,158,11,0.3)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
          { label: "Estimated (backfill)", data: est, stack: "est", borderColor: "rgba(148,163,184,0.8)", backgroundColor: "transparent", borderDash: [5, 4], fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1.5 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 0 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "rgba(255,255,255,0.6)", boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: function(c) { return c.dataset.label + ": " + _fmtTok(c.parsed.y); } } }
        },
        scales: {
          x: { ticks: { color: "rgba(255,255,255,0.5)", maxTicksLimit: 8, font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.05)" } },
          y: { stacked: true, ticks: { color: "rgba(255,255,255,0.5)", font: { size: 10 }, callback: function(v) { return _fmtTok(v); } }, grid: { color: "rgba(255,255,255,0.06)" } }
        }
      }
    });
  }
  _renderCloudImpact(d.impact);
}

function _renderCloudImpact(imp) {
  var el = document.getElementById("teImpact");
  if (!el) return;
  if (!imp) { el.innerHTML = ""; return; }
  var agents = imp.agents_by_month || [];
  var peak = agents.reduce(function(mx, a) { return Math.max(mx, a.cumulative || 0); }, 1);
  var bars = agents.map(function(a) {
    var h = Math.round(((a.cumulative || 0) / peak) * 60) + 3;
    var label = (a.month || "").slice(5); // MM
    return '<div class="imp-bar" style="height:' + h + 'px" title="' + escHtml(a.month) + ': ' + a.cumulative + ' agents (+' + a.created + ')"><b>' + a.cumulative + '</b><span>' + label + '</span></div>';
  }).join("");
  var phases = (imp.capacity_phases || []).map(function(p) {
    return '<div style="display:flex;gap:10px;padding:3px 8px;border-bottom:1px solid rgba(255,255,255,0.04);">' +
             '<span style="color:#f59e0b;font-family:\'Orbitron\',sans-serif;font-size:0.58rem;min-width:96px;">' + escHtml(p.period) + '</span>' +
             '<span style="font-size:0.62rem;color:rgba(255,255,255,0.6);">' + escHtml(p.detail) + '</span>' +
           '</div>';
  }).join("");
  el.innerHTML =
    '<div class="imp-wrap">' +
      '<div style="text-align:center;font-family:\'Orbitron\',sans-serif;font-size:0.72rem;letter-spacing:2px;text-transform:uppercase;color:#f59e0b;margin-bottom:8px;">☁ Cloud Impact — Built From Here</div>' +
      '<div class="imp-cells">' +
        '<div class="imp-cell"><div class="v" style="color:#f59e0b">~' + _fmtTok(imp.est_historical_tokens) + '</div><div class="l">Est. AI-assisted tokens (Jan–Apr)</div></div>' +
        '<div class="imp-cell"><div class="v" style="color:#a78bfa">' + (imp.lines_built_est_period || 0).toLocaleString() + '</div><div class="l">Lines built (est period)</div></div>' +
        '<div class="imp-cell"><div class="v" style="color:#22d3ee">' + (agents.length ? agents[agents.length - 1].cumulative : 0) + '</div><div class="l">Agents built</div></div>' +
        '<div class="imp-cell"><div class="v" style="color:rgba(255,255,255,0.7)">' + escHtml(imp.origin || "") + '</div><div class="l">Project origin</div></div>' +
      '</div>' +
      (bars ? '<div style="font-size:0.55rem;color:rgba(255,255,255,0.4);text-align:center;margin:2px 0 18px;">Agent fleet growth (cumulative)</div><div class="imp-bars">' + bars + '</div>' : '') +
      (phases ? '<div style="margin-top:14px;font-family:\'Orbitron\',sans-serif;font-size:0.58rem;letter-spacing:1px;text-transform:uppercase;color:rgba(245,158,11,0.7);text-align:center;margin-bottom:4px;">Capacity &amp; authorship</div>' + phases : '') +
      '<div style="font-size:0.52rem;color:rgba(255,255,255,0.35);text-align:center;margin-top:12px;font-style:italic;">' + escHtml(imp.note || "") + '</div>' +
    '</div>';
}

function _auditBtnCell(moduleKey) {
  var pCount = (window._chProposalCounts || {})[moduleKey] || 0;
  var auditDate = (window._chAuditDates || {})[moduleKey];
  var status = (window._chStatusMap || {})[moduleKey] || "red";

  // Freshness stamp for clean/passed modules
  var freshStamp = "";
  if (auditDate && (status === "green" || status === "purple")) {
    var ageMs = Date.now() - new Date(auditDate).getTime();
    var ageHours = ageMs / 3600000;
    if (ageHours < 24) {
      freshStamp = '<span style="font-size:0.5rem;color:#22c55e;margin-right:3px;" title="Audited within 24h">\u2713 today</span>';
    } else if (ageHours < 168) {
      freshStamp = '<span style="font-size:0.5rem;color:#3b82f6;margin-right:3px;" title="Audited within 7 days">\u2713 this week</span>';
    } else {
      freshStamp = '<span style="font-size:0.5rem;color:rgba(255,255,255,0.3);margin-right:3px;" title="Audit older than 7 days">\u231B old</span>';
    }
  }

  if (pCount > 0) {
    return '<td class="center">' + freshStamp + '<span style="font-size:0.55rem;color:#a78bfa;margin-right:4px;" title="' + pCount + ' proposals in Repair Bay pipeline">' + pCount + ' in repair</span>' +
      '<button class="ch-audit-row-btn" data-module="' + escHtml(moduleKey) + '" style="background:rgba(245,158,11,0.1);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;text-transform:uppercase;letter-spacing:0.5px;">Re-audit</button></td>';
  }
  return '<td class="center">' + freshStamp + '<button class="ch-audit-row-btn" data-module="' + escHtml(moduleKey) + '" style="background:rgba(0,229,255,0.1);color:#00e5ff;border:1px solid rgba(0,229,255,0.3);padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;text-transform:uppercase;letter-spacing:0.5px;">Audit</button></td>';
}

function _detectProfile(mod) {
  var bt = mod.by_type || {};
  var total = 0;
  Object.values(bt).forEach(function(v) { total += (v.lines || 0); });
  if (total === 0) return "python";
  var web = ((bt.js||{}).lines||0) + ((bt.html||{}).lines||0) + ((bt.css||{}).lines||0) + ((bt.svg||{}).lines||0);
  var cfg = ((bt.yaml||{}).lines||0) + ((bt.config||{}).lines||0);
  if (cfg / total >= 0.6) return "config";
  if (web / total >= 0.6) return "web";
  return "python";
}

function _renderModuleTable(modules, auditedModules, moduleStatusMap, moduleDisplayNames) {
  var el = document.getElementById("chModuleTable");
  if (!el) return;
  auditedModules = auditedModules || {};
  moduleStatusMap = moduleStatusMap || {};
  moduleDisplayNames = moduleDisplayNames || {};

  // Build issues map from latest audit per module
  var issuesMap = {};
  (window._chAuditEntries || []).forEach(function(e) {
    if (!issuesMap[e.module_name]) issuesMap[e.module_name] = e.issues_found || 0;
  });

  // Sort: tool modules by lines desc, then infra modules at the bottom (matching chart order)
  var infraKeys = {"[SHARED]":1, "[APP_CORE]":1, "[AI_BRIDGE]":1, "[MIGRATIONS]":1};
  var toolKeys = Object.keys(modules).filter(function(k) { return !infraKeys[k]; }).sort(function(a, b) {
    return (modules[b].lines || 0) - (modules[a].lines || 0);
  });
  var infraSorted = Object.keys(modules).filter(function(k) { return infraKeys[k]; }).sort(function(a, b) {
    return (modules[b].lines || 0) - (modules[a].lines || 0);
  });
  var sorted = toolKeys.concat(infraSorted);

  // Search filter
  var searchHtml = '<div style="display:flex;justify-content:center;margin-bottom:8px;">'
    + '<input id="chModuleSearch" type="text" placeholder="Search modules..." '
    + 'style="background:rgba(255,255,255,0.05);border:1px solid rgba(0,229,255,0.2);color:#fff;padding:6px 12px;border-radius:4px;font-size:0.75rem;width:250px;outline:none;" />'
    + '</div>';

  var langColors = {python:"#8b5cf6",js:"#00ccff",html:"#f59e0b",css:"#22c55e",sql:"#fde047",json:"#2dd4bf",shell:"#ef4444",yaml:"#06b6d4",markdown:"#a78bfa",go:"#38bdf8",svg:"#fb923c",config:"#94a3b8",text:"#64748b"};

  var html = '<table class="ch-table"><thead><tr>' +
    '<th>Module</th><th class="center">Profile</th><th class="center">Status</th><th class="center">Issues</th><th class="center">Files</th><th class="center">Lines</th>' +
    '<th>Top Languages</th><th class="center"></th>' +
    '</tr></thead><tbody>';

  var profileColors = {python: "#8b5cf6", web: "#f59e0b", config: "#94a3b8"};

  sorted.forEach(function(name) {
    var m = modules[name];
    var bt = m.by_type || {};
    var status = auditedModules[name];
    var isCompleted = status === "completed";
    var isAudited = !!status;

    // Profile badge
    var profile = _detectProfile(m);
    var profileBadge = '<span style="font-size:0.55rem;padding:1px 5px;border-radius:3px;background:' +
      profileColors[profile] + '22;color:' + profileColors[profile] + ';border:1px solid ' +
      profileColors[profile] + '44;text-transform:uppercase;">' + profile + '</span>';

    // Status badge from module-status endpoint
    var healthStatus = moduleStatusMap[name] || "red";
    var badgeClass, badgeLabel;
    if (healthStatus === "green") {
      badgeClass = "ch-badge-green"; badgeLabel = "CLEAN";
    } else if (healthStatus === "purple") {
      badgeClass = "ch-badge-purple"; badgeLabel = "IN REPAIR";
    } else if (healthStatus === "orange") {
      badgeClass = "ch-badge-amber"; badgeLabel = "ISSUES";
    } else if (healthStatus === "yellow") {
      badgeClass = "ch-badge-amber"; badgeLabel = "STALE";
    } else {
      badgeClass = "ch-badge-red"; badgeLabel = "UNAUDITED";
    }
    var badgeHtml = '<span class="ch-badge ' + badgeClass + '">' +
      '<span class="ch-badge-dot"></span>' + badgeLabel + '</span>';

    // Issues count
    var issueCount = issuesMap[name] || 0;
    var issueColor = issueCount === 0 ? "#22c55e" : issueCount <= 5 ? "#f59e0b" : "#ef4444";

    // Top 3 languages by lines
    var langEntries = [];
    Object.keys(bt).forEach(function(lang) {
      if (bt[lang].lines > 0) langEntries.push({lang: lang, lines: bt[lang].lines});
    });
    langEntries.sort(function(a, b) { return b.lines - a.lines; });
    var topLangs = langEntries.slice(0, 3).map(function(l) {
      return '<span style="font-size:0.6rem;padding:1px 4px;border-radius:3px;background:' + (langColors[l.lang] || '#666') + '22;color:' + (langColors[l.lang] || '#999') + ';margin-right:2px;">' + escHtml(l.lang) + ' ' + l.lines.toLocaleString() + '</span>';
    }).join('');

    // Module name color: green=clean, purple=in repair, orange=issues, yellow=stale, red=unaudited
    var nameColor = healthStatus === "green" ? "#22c55e" : healthStatus === "purple" ? "#a78bfa" : healthStatus === "orange" ? "#f59e0b" : healthStatus === "yellow" ? "#f59e0b" : "#ef4444";
    var nameStyle = "color:" + nameColor + ";font-weight:600;";

    html += '<tr>' +
      '<td><span style="' + nameStyle + '">' + escHtml(moduleDisplayNames[name] || name) + '</span>' + (healthStatus === "green" ? ' <span style="font-size:0.6rem;opacity:0.5;">&#x2713;</span>' : '') + '</td>' +
      '<td class="center">' + profileBadge + '</td>' +
      '<td class="center">' + badgeHtml + '</td>' +
      '<td class="center" style="color:' + issueColor + ';font-weight:600;">' + issueCount + '</td>' +
      '<td class="center">' + (m.files || 0) + '</td>' +
      '<td class="center"><strong>' + (m.lines || 0).toLocaleString() + '</strong></td>' +
      '<td>' + (topLangs || '<span style="color:rgba(255,255,255,0.2);">\u2014</span>') + '</td>' +
      _auditBtnCell(name) +
      '</tr>';
  });

  html += '</tbody></table>';
  setHtml(el, searchHtml + html);

  // Search handler
  var searchInput = document.getElementById("chModuleSearch");
  if (searchInput) {
    searchInput.addEventListener("input", function() {
      var q = searchInput.value.toLowerCase();
      el.querySelectorAll("tbody tr").forEach(function(row) {
        var name = (row.cells[0] || {}).textContent || "";
        row.style.display = name.toLowerCase().indexOf(q) !== -1 ? "" : "none";
      });
    });
  }

  // Audit buttons in each row
  el.querySelectorAll(".ch-audit-row-btn").forEach(function(btn) {
    btn.addEventListener("click", function(evt) {
      evt.stopPropagation();
      var mod = btn.getAttribute("data-module");
      var row = btn.closest("tr");
      btn.disabled = true;
      btn.textContent = "...";
      api("/api/code-health/audit", {body: {module: mod}}).then(function(d) {
        if (d.success && d.results && d.results[0]) {
          var r = d.results[0];
          if (r.status === "completed") {
            btn.textContent = r.pending_repairs == null ? "Audit clean; repairs unverified" :
              r.pending_repairs > 0 ? "Audit clean; " + r.pending_repairs + " repairs pending" : "\u2713 clean";
            btn.style.background = "rgba(34,197,94,0.2)";
            btn.style.color = "#22c55e";
            btn.style.borderColor = "#22c55e";
          } else {
            var msg = r.issues + " issues";
            if (r.issues_informational > 0) msg += " (" + r.issues_informational + " informational)";
            if (r.proposals_created > 0) msg += "; " + r.proposals_created + " new repairs";
            if (r.pending_repairs != null) msg += "; " + r.pending_repairs + " repair records pending";
            else msg += "; repairs unverified";
            btn.textContent = msg;
            btn.style.background = "rgba(167,139,250,0.2)";
            btn.style.color = "#a78bfa";
            btn.style.borderColor = "#a78bfa";
          }
          setTimeout(function() { _cache = {}; loadCodeHealth(); }, 2000);
        }
      }).catch(function() { btn.disabled = false; btn.textContent = "Audit"; });
    });
  });
}

function _renderStandaloneTable(modules, moduleStatusMap, tierMap) {
    var el = document.getElementById("chStandaloneTable");
    if (!el) return;
    moduleStatusMap = moduleStatusMap || {};
    tierMap = tierMap || {};
    var keys = Object.keys(modules);
    if (keys.length === 0) {
        setHtml(el, '<div class="ch-empty">No standalone products registered.</div>');
        return;
    }
    // Build issues map from latest audit per module
    var issuesMap = {};
    (window._chAuditEntries || []).forEach(function(e) {
        if (!issuesMap[e.module_name]) issuesMap[e.module_name] = e.issues_found || 0;
    });
    var langColors = {python:"#8b5cf6",js:"#00ccff",html:"#f59e0b",css:"#22c55e",sql:"#fde047",json:"#2dd4bf",shell:"#ef4444",yaml:"#06b6d4",markdown:"#a78bfa",go:"#38bdf8",svg:"#fb923c",config:"#94a3b8",text:"#64748b"};
    var profileColors = {python: "#8b5cf6", web: "#f59e0b", config: "#94a3b8"};
    var rows = keys.map(function(key) {
        var m = modules[key];
        var displayName = key.replace('standalone_', '').replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
        var bt = m.by_type || {};
        // Profile badge
        var profile = _detectProfile(m);
        var profileBadge = '<span style="font-size:0.55rem;padding:1px 5px;border-radius:3px;background:' + profileColors[profile] + '22;color:' + profileColors[profile] + ';border:1px solid ' + profileColors[profile] + '44;text-transform:uppercase;">' + profile + '</span>';
        // Audit status badge
        var healthStatus = moduleStatusMap[key] || "red";
        var badgeClass, badgeLabel;
        if (healthStatus === "green") {
            badgeClass = "ch-badge-green"; badgeLabel = "CLEAN";
        } else if (healthStatus === "purple") {
            badgeClass = "ch-badge-purple"; badgeLabel = "IN REPAIR";
        } else if (healthStatus === "orange") {
            badgeClass = "ch-badge-amber"; badgeLabel = "ISSUES";
        } else if (healthStatus === "yellow") {
            badgeClass = "ch-badge-amber"; badgeLabel = "STALE";
        } else {
            badgeClass = "ch-badge-red"; badgeLabel = "UNAUDITED";
        }
        var badgeHtml = '<span class="ch-badge ' + badgeClass + '"><span class="ch-badge-dot"></span>' + badgeLabel + '</span>';
        var nameColor = healthStatus === "green" ? "#22c55e" : healthStatus === "purple" ? "#a78bfa" : healthStatus === "orange" ? "#f59e0b" : healthStatus === "yellow" ? "#f59e0b" : "#ef4444";
        // Issues count
        var issueCount = issuesMap[key] || 0;
        var issueColor = issueCount === 0 ? "#22c55e" : issueCount <= 5 ? "#f59e0b" : "#ef4444";
        // Top 3 languages by lines
        var langEntries = [];
        Object.keys(bt).forEach(function(lang) {
            if (bt[lang].lines > 0) langEntries.push({lang: lang, lines: bt[lang].lines});
        });
        langEntries.sort(function(a, b) { return b.lines - a.lines; });
        var topLangs = langEntries.slice(0, 3).map(function(l) {
            return '<span style="font-size:0.6rem;padding:1px 4px;border-radius:3px;background:' + (langColors[l.lang] || '#666') + '22;color:' + (langColors[l.lang] || '#999') + ';margin-right:2px;">' + escHtml(l.lang) + ' ' + l.lines.toLocaleString() + '</span>';
        }).join('');
        return '<tr>'
            + '<td><span style="color:' + nameColor + ';font-weight:600;">' + escHtml(displayName) + '</span></td>'
            + '<td class="center">' + profileBadge + '</td>'
            + '<td class="center">' + badgeHtml + '</td>'
            + '<td class="center" style="color:' + issueColor + ';font-weight:600;">' + issueCount + '</td>'
            + '<td class="center">' + (m.files || 0) + '</td>'
            + '<td class="center"><strong>' + (m.lines || 0).toLocaleString() + '</strong></td>'
            + '<td>' + (topLangs || '<span style="color:rgba(255,255,255,0.2);">\u2014</span>') + '</td>'
            + _auditBtnCell(key)
            + '</tr>';
    });
    var html = '<table class="ch-table">'
        + '<thead><tr>'
        + '<th>Standalone Product</th>'
        + '<th class="center">Profile</th>'
        + '<th class="center">Status</th>'
        + '<th class="center">Issues</th>'
        + '<th class="center">Files</th>'
        + '<th class="center">Lines</th>'
        + '<th>Top Languages</th>'
        + '<th class="center"></th>'
        + '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';
    setHtml(el, html);
    // Audit buttons
    el.querySelectorAll(".ch-audit-row-btn").forEach(function(btn) {
      btn.addEventListener("click", function(evt) {
        evt.stopPropagation();
        var mod = btn.getAttribute("data-module");
        btn.disabled = true; btn.textContent = "...";
        api("/api/code-health/audit", {body: {module: mod}}).then(function(d) {
          if (d.success && d.results && d.results[0]) {
            var r = d.results[0];
            btn.textContent = r.status === "completed" ? "\u2713" : r.issues + "";
            btn.style.background = r.status === "completed" ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)";
            btn.style.color = r.status === "completed" ? "#22c55e" : "#ef4444";
            btn.style.borderColor = r.status === "completed" ? "#22c55e" : "#ef4444";
            setTimeout(function() { _cache = {}; loadCodeHealth(); }, 2000);
          }
        }).catch(function() { btn.disabled = false; btn.textContent = "Audit"; });
      });
    });
}

function _renderWebsiteTable(modules, moduleStatusMap) {
    var el = document.getElementById("chWebsiteTable");
    if (!el) return;
    moduleStatusMap = moduleStatusMap || {};
    var keys = Object.keys(modules);
    if (keys.length === 0) {
        setHtml(el, '<div class="ch-empty">No website products registered.</div>');
        return;
    }
    // Build issues map from latest audit per module
    var issuesMap = {};
    (window._chAuditEntries || []).forEach(function(e) {
        if (!issuesMap[e.module_name]) issuesMap[e.module_name] = e.issues_found || 0;
    });
    var langColors = {python:"#8b5cf6",js:"#00ccff",html:"#f59e0b",css:"#22c55e",sql:"#fde047",json:"#2dd4bf",shell:"#ef4444",yaml:"#06b6d4",markdown:"#a78bfa",go:"#38bdf8",svg:"#fb923c",config:"#94a3b8",text:"#64748b"};
    var profileColors = {python: "#8b5cf6", web: "#f59e0b", config: "#94a3b8"};
    var rows = keys.map(function(key) {
        var m = modules[key];
        var displayName = key.replace('website_', '').replace(/_/g, '.').replace(/\b\w/g, function(c) { return c; });
        var dn = (window._chDisplayNames || {})[key] || displayName;
        var bt = m.by_type || {};
        // Profile badge
        var profile = _detectProfile(m);
        var profileBadge = '<span style="font-size:0.55rem;padding:1px 5px;border-radius:3px;background:' + profileColors[profile] + '22;color:' + profileColors[profile] + ';border:1px solid ' + profileColors[profile] + '44;text-transform:uppercase;">' + profile + '</span>';
        // Status badge + name color
        var healthStatus = moduleStatusMap[key] || "red";
        var badgeClass, badgeLabel;
        if (healthStatus === "green") { badgeClass = "ch-badge-green"; badgeLabel = "CLEAN"; }
        else if (healthStatus === "purple") { badgeClass = "ch-badge-purple"; badgeLabel = "IN REPAIR"; }
        else if (healthStatus === "orange") { badgeClass = "ch-badge-amber"; badgeLabel = "ISSUES"; }
        else if (healthStatus === "yellow") { badgeClass = "ch-badge-amber"; badgeLabel = "STALE"; }
        else { badgeClass = "ch-badge-red"; badgeLabel = "UNAUDITED"; }
        var badgeHtml = '<span class="ch-badge ' + badgeClass + '"><span class="ch-badge-dot"></span>' + badgeLabel + '</span>';
        var nameColor = healthStatus === "green" ? "#22c55e" : healthStatus === "purple" ? "#a78bfa" : healthStatus === "orange" ? "#f59e0b" : healthStatus === "yellow" ? "#f59e0b" : "#ef4444";
        // Issues count
        var issueCount = issuesMap[key] || 0;
        var issueColor = issueCount === 0 ? "#22c55e" : issueCount <= 5 ? "#f59e0b" : "#ef4444";
        // Top 3 languages by lines
        var langEntries = [];
        Object.keys(bt).forEach(function(lang) {
            if (bt[lang].lines > 0) langEntries.push({lang: lang, lines: bt[lang].lines});
        });
        langEntries.sort(function(a, b) { return b.lines - a.lines; });
        var topLangs = langEntries.slice(0, 3).map(function(l) {
            return '<span style="font-size:0.6rem;padding:1px 4px;border-radius:3px;background:' + (langColors[l.lang] || '#666') + '22;color:' + (langColors[l.lang] || '#999') + ';margin-right:2px;">' + escHtml(l.lang) + ' ' + l.lines.toLocaleString() + '</span>';
        }).join('');
        return '<tr>'
            + '<td><span style="color:' + nameColor + ';font-weight:600;">' + escHtml(dn) + '</span></td>'
            + '<td class="center">' + profileBadge + '</td>'
            + '<td class="center">' + badgeHtml + '</td>'
            + '<td class="center" style="color:' + issueColor + ';font-weight:600;">' + issueCount + '</td>'
            + '<td class="center">' + (m.files || 0) + '</td>'
            + '<td class="center"><strong>' + (m.lines || 0).toLocaleString() + '</strong></td>'
            + '<td>' + (topLangs || '<span style="color:rgba(255,255,255,0.2);">\u2014</span>') + '</td>'
            + _auditBtnCell(key)
            + '</tr>';
    });
    var html = '<table class="ch-table">'
        + '<thead><tr>'
        + '<th>Website</th>'
        + '<th class="center">Profile</th>'
        + '<th class="center">Status</th>'
        + '<th class="center">Issues</th>'
        + '<th class="center">Files</th>'
        + '<th class="center">Lines</th>'
        + '<th>Top Languages</th>'
        + '<th class="center"></th>'
        + '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';
    setHtml(el, html);
    // Audit buttons
    el.querySelectorAll(".ch-audit-row-btn").forEach(function(btn) {
      btn.addEventListener("click", function(evt) {
        evt.stopPropagation();
        var mod = btn.getAttribute("data-module");
        btn.disabled = true; btn.textContent = "...";
        api("/api/code-health/audit", {body: {module: mod}}).then(function(d) {
          if (d.success && d.results && d.results[0]) {
            var r = d.results[0];
            btn.textContent = r.status === "completed" ? "\u2713" : r.issues + "";
            btn.style.background = r.status === "completed" ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)";
            btn.style.color = r.status === "completed" ? "#22c55e" : "#ef4444";
            btn.style.borderColor = r.status === "completed" ? "#22c55e" : "#ef4444";
            setTimeout(function() { _cache = {}; loadCodeHealth(); }, 2000);
          }
        }).catch(function() { btn.disabled = false; btn.textContent = "Audit"; });
      });
    });
}

function _renderOrphanTable(orphans) {
  var el = document.getElementById("chOrphanTable");
  if (!el) return;

  var all = [];
  (orphans.templates || []).forEach(function(o) { all.push({type: "HTML", file: o.file, lines: o.lines}); });
  (orphans.js || []).forEach(function(o) { all.push({type: "JS", file: o.file, lines: o.lines}); });
  (orphans.css || []).forEach(function(o) { all.push({type: "CSS", file: o.file, lines: o.lines}); });

  if (!all.length) {
    setHtml(el, '<div class="ch-empty ch-empty-success">All files mapped to modules — no orphans found.</div>');
    return;
  }

  var html = '<table class="ch-table"><thead><tr>' +
    '<th>Type</th><th>File</th><th class="center">Lines</th>' +
    '</tr></thead><tbody>';
  all.forEach(function(o) {
    var typeClass = o.type === "HTML" ? "ch-badge-red" : o.type === "JS" ? "ch-badge-amber" : "ch-badge-cyan";
    html += '<tr>' +
      '<td><span class="ch-badge ' + typeClass + '"><span class="ch-badge-dot"></span>' + o.type + '</span></td>' +
      '<td style="font-size:0.75rem;">' + escHtml(o.file) + '</td>' +
      '<td class="center">' + (o.lines || 0).toLocaleString() + '</td>' +
      '</tr>';
  });
  html += '</tbody></table>';
  setHtml(el, html);
}

function _renderStructuralAudit(d, statusSummary) {
  var el = document.getElementById("chStructuralAudit");
  if (!el) return;

  var kbs = d.kbs_audit || {};
  var sa = d.standalone_audit || {};
  var retired = d.retired_modules || [];
  var hs = d.health_score || {};

  var sections = [];

  // Health Score summary card — radial ring + score breakdown bar
  var score = hs.score || 0;
  var grade = hs.grade || "?";
  var scoreColor = score >= 90 ? "#10b981" : score >= 70 ? "#3b82f6" : score >= 50 ? "#f59e0b" : "#ef4444";
  var circumference = 2 * Math.PI * 42;
  var dashOffset = circumference * (1 - score / 100);

  // Build score breakdown bar segments
  var deductions = hs.deductions || [];
  var barSegments = '';
  var legendItems = '';
  var dedColors = ["#ef4444", "#f59e0b", "#f97316", "#a78bfa"];
  var remaining = score;
  barSegments += '<div class="ch-score-bar-fill" style="width:' + score + '%;background:' + scoreColor + ';"></div>';
  deductions.forEach(function(ded, i) {
    var dedText = typeof ded === 'string' ? ded : (ded.reason || '');
    var penaltyMatch = dedText.match(/^-(\d+):/);
    var pts = penaltyMatch ? parseInt(penaltyMatch[1]) : 0;
    var col = dedColors[i % dedColors.length];
    if (pts > 0) {
      barSegments += '<div class="ch-score-bar-fill" style="width:' + pts + '%;background:' + col + ';"></div>';
      var desc = penaltyMatch ? dedText.substring(penaltyMatch[0].length).trim() : dedText;
      legendItems += '<div class="ch-score-legend-item"><span class="ch-score-legend-dot" style="background:' + col + ';"></span>' + escHtml(desc) + ' (-' + pts + ')</div>';
    }
  });

  sections.push(
    '<div class="ch-audit-card ch-audit-hero" style="text-align:center;">' +
    '<div class="ch-audit-title">Health Score</div>' +
    '<div class="ch-score-ring">' +
    '<svg width="100" height="100" viewBox="0 0 100 100">' +
    '<circle class="ch-score-ring-bg" cx="50" cy="50" r="42"/>' +
    '<circle class="ch-score-ring-fg" cx="50" cy="50" r="42" stroke="' + scoreColor + '" stroke-dasharray="' + circumference.toFixed(1) + '" stroke-dashoffset="' + dashOffset.toFixed(1) + '"/>' +
    '</svg>' +
    '<div class="ch-score-ring-label">' +
    '<div class="ch-score-ring-value" style="color:' + scoreColor + ';">' + score + '</div>' +
    '<div class="ch-score-ring-sub">/ 100</div>' +
    '</div></div>' +
    '<div style="font-family:Antonio,sans-serif;font-size:1rem;font-weight:600;color:' + scoreColor + ';letter-spacing:2px;">GRADE: ' + escHtml(grade) + '</div>' +
    (deductions.length > 0 ? '<div class="ch-score-bar">' + barSegments + '</div><div class="ch-score-legend">' + legendItems + '</div>' : '') +
    '</div>'
  );

  // Audit Summary — breakdown by status
  statusSummary = statusSummary || {};
  var totalMods = (statusSummary.green || 0) + (statusSummary.orange || 0) + (statusSummary.yellow || 0) + (statusSummary.red || 0);
  if (totalMods > 0) {
    var auditedTotal = totalMods - (statusSummary.red || 0);
    var summaryItems = [
      { val: auditedTotal, suffix: '/' + totalMods, label: 'audited', color: '#3b82f6' },
      { val: statusSummary.green || 0, suffix: '', label: 'clean', color: '#22c55e' },
      { val: statusSummary.purple || 0, suffix: '', label: 'in repair', color: '#a78bfa' },
      { val: statusSummary.orange || 0, suffix: '', label: 'issues', color: '#f59e0b' },
      { val: statusSummary.red || 0, suffix: '', label: 'unaudited', color: '#ef4444' }
    ];
    var summaryHtml = summaryItems.map(function(item) {
      return '<div style="text-align:center;flex:1;min-width:50px;">' +
        '<div style="width:8px;height:8px;border-radius:50%;background:' + item.color + ';box-shadow:0 0 6px ' + item.color + '40;margin:0 auto 6px;"></div>' +
        '<div style="font-family:Orbitron,monospace;font-size:1.3rem;font-weight:700;color:' + item.color + ';line-height:1;">' + item.val + '<span style="font-size:0.55rem;color:rgba(255,255,255,0.35);">' + item.suffix + '</span></div>' +
        '<div style="font-size:0.6rem;color:rgba(255,255,255,0.4);letter-spacing:0.5px;margin-top:4px;text-transform:uppercase;">' + item.label + '</div>' +
        '</div>';
    }).join('');
    sections.push(
      '<div class="ch-audit-card ch-audit-hero" style="text-align:center;">' +
      '<div class="ch-audit-title">Audit Summary</div>' +
      '<div style="display:flex;justify-content:center;gap:8px;margin-top:8px;">' + summaryHtml + '</div>' +
      '</div>'
    );
  }

  // KBS Plugins — show per-plugin checklist
  if (kbs.total > 0) {
    var kbsColor = kbs.healthy === kbs.total ? "#10b981" : "#f59e0b";
    var pluginRows = '';
    var plugins = kbs.plugins || [];
    if (plugins.length > 0) {
      pluginRows = '<div style="margin-top:8px;">';
      plugins.forEach(function(p) {
        var checks = [
          {key: "has_manifest", label: "manifest"},
          {key: "has_routes", label: "routes"},
          {key: "has_init", label: "init"},
          {key: "has_templates", label: "templates"},
          {key: "has_static", label: "static"}
        ];
        var checkHtml = checks.map(function(c) {
          var pass = p[c.key];
          return '<span class="ch-plugin-check ' + (pass ? 'pass' : 'fail') + '">' + (pass ? '\u2713' : '\u2717') + '</span>';
        }).join('');
        var healthy = !p.issues || p.issues.length === 0;
        pluginRows += '<div class="ch-plugin-row">' +
          '<span style="color:' + (healthy ? '#10b981' : '#f59e0b') + ';font-weight:600;min-width:80px;">' + escHtml(p.name) + '</span>' +
          checkHtml +
          '</div>';
      });
      pluginRows += '</div>';
    }
    sections.push(
      '<div class="ch-audit-card">' +
      '<div class="ch-audit-title">KBS Plugins</div>' +
      '<div class="ch-audit-score" style="color:' + kbsColor + '">' + (kbs.healthy || 0) + '/' + (kbs.total || 0) + ' healthy</div>' +
      pluginRows +
      '</div>'
    );
  }

  // Standalone Products
  if (sa.total > 0) {
    var saColor = sa.healthy === sa.total ? "#10b981" : sa.healthy >= sa.total - 2 ? "#3b82f6" : "#f59e0b";
    var saIssueHtml = '';
    if (sa.issues && sa.issues.length > 0) {
      saIssueHtml = '<div class="ch-audit-issues" style="margin-top:8px;">';
      sa.issues.forEach(function(issue) {
        var issueColor = issue.indexOf("missing") !== -1 ? "#f59e0b" : "#ef4444";
        saIssueHtml += '<div class="ch-audit-issue" style="display:flex;align-items:center;gap:6px;margin:3px 0;font-size:0.75rem;">' +
          '<span style="width:6px;height:6px;border-radius:50%;background:' + issueColor + ';flex-shrink:0;"></span>' +
          '<span style="color:rgba(255,255,255,0.6);">' + escHtml(issue) + '</span></div>';
      });
      saIssueHtml += '</div>';
    }
    sections.push(
      '<div class="ch-audit-card">' +
      '<div class="ch-audit-title">Standalone Products</div>' +
      '<div class="ch-audit-score" style="color:' + saColor + '">' + (sa.healthy || 0) + '/' + (sa.total || 0) + ' passing Tier 1</div>' +
      saIssueHtml +
      '</div>'
    );
  }

  // Retired Modules
  if (retired.length > 0) {
    var retiredRows = retired.map(function(m) {
      var badge = m.status === 'retired' ? 'ch-badge-cyan' : 'ch-badge-amber';
      var target = m.redirect_target ? ' \u2192 ' + escHtml(String(m.redirect_target)) : '';
      var linesInfo = m.functional_lines ? ' (' + m.functional_lines.toLocaleString() + ' lines)' : '';
      return '<div class="ch-audit-retired-row" style="display:flex;align-items:center;gap:8px;margin:4px 0;">' +
        '<span class="ch-badge ' + badge + '"><span class="ch-badge-dot"></span>' + escHtml(m.status).toUpperCase() + '</span>' +
        '<span>' + escHtml(m.module) + '</span>' +
        '<span style="color:rgba(255,255,255,0.3);font-size:0.7rem;">' + linesInfo + target + '</span>' +
        '</div>';
    }).join('');
    sections.push(
      '<div class="ch-audit-card">' +
      '<div class="ch-audit-title">Retired Modules (' + retired.length + ')</div>' +
      retiredRows +
      '</div>'
    );
  }

  // Score Deductions — severity-colored with penalty badges
  var deductions = hs.deductions || [];
  if (deductions.length > 0) {
    var dedHtml = '<div style="margin-top:4px;">';
    deductions.forEach(function(ded) {
      var dedText = typeof ded === 'string' ? ded : (ded.reason || JSON.stringify(ded));
      var penaltyMatch = dedText.match(/^(-\d+):/);
      var penalty = penaltyMatch ? parseInt(penaltyMatch[1]) : 0;
      var dedColor = penalty <= -20 ? '#ef4444' : penalty <= -10 ? '#f59e0b' : '#3b82f6';
      var badgeText = penaltyMatch ? penaltyMatch[1] : '';
      var descText = penaltyMatch ? dedText.substring(penaltyMatch[0].length).trim() : dedText;
      dedHtml += '<div style="display:flex;align-items:center;gap:8px;margin:5px 0;font-size:0.8rem;">';
      if (badgeText) {
        dedHtml += '<span style="font-family:Orbitron,monospace;font-size:0.65rem;font-weight:700;color:' + dedColor + ';background:' + dedColor + '15;border:1px solid ' + dedColor + '30;border-radius:4px;padding:2px 6px;min-width:32px;text-align:center;">' + badgeText + '</span>';
      } else {
        dedHtml += '<span style="width:6px;height:6px;border-radius:50%;background:' + dedColor + ';flex-shrink:0;"></span>';
      }
      dedHtml += '<span style="color:rgba(255,255,255,0.6);">' + escHtml(descText) + '</span></div>';
    });
    dedHtml += '</div>';
    sections.push(
      '<div class="ch-audit-card">' +
      '<div class="ch-audit-title">Score Deductions</div>' +
      dedHtml +
      '</div>'
    );
  }

  // Last Scanned timestamp — full-width
  var snapAge = d.snapshot_age || null;
  if (snapAge) {
    var scanDate = new Date(snapAge);
    var now = new Date();
    var diffMs = now - scanDate;
    var diffMins = Math.floor(diffMs / 60000);
    var agoText = '';
    if (diffMins < 1) agoText = 'just now';
    else if (diffMins < 60) agoText = diffMins + 'm ago';
    else if (diffMins < 1440) agoText = Math.floor(diffMins / 60) + 'h ago';
    else agoText = Math.floor(diffMins / 1440) + 'd ago';
    sections.push(
      '<div class="ch-audit-card ch-audit-full" style="text-align:center;">' +
      '<div class="ch-last-scanned">Last scanned: <strong>' + scanDate.toLocaleString() + '</strong> (' + agoText + ')</div>' +
      '</div>'
    );
  }

  if (sections.length === 0) {
    setHtml(el, '<div class="ch-empty ch-empty-success">Structural audit clean \u2014 no issues.</div>');
  } else {
    setHtml(el, sections.join(''));
  }
}

window.chRunScan = function() {
  api("/api/code-health/scan", { method: "POST" }).then(function(d) {
    if (d.success) {
      _renderCodeHealthStats(d.metrics);
      _renderModuleChart(d.metrics.modules || {}, {});
      // Re-fetch module status after scan to get fresh badges
      api("/api/code-health/module-status").then(function(statusData) {
        var moduleStatusMap = {};
        var moduleDisplayNames = {};
        (statusData.modules || []).forEach(function(m) {
          moduleStatusMap[m.module_name] = m.status;
          if (m.display_name) moduleDisplayNames[m.module_name] = m.display_name;
        });
        _renderCodeHealthSummaryBar(statusData.summary || {});
        _renderModuleTable(d.metrics.modules || {}, {}, moduleStatusMap, moduleDisplayNames);
      }).catch(function() {
        _renderModuleTable(d.metrics.modules || {});
      });
      chLoadHistory();
    }
  }).catch(function(err) {
    console.error("Scan failed:", err);
  });
};

window.chBackfillGit = function() {
  if (typeof toast !== "undefined") toast("Building lifetime tracker...");
  api("/api/code-health/backfill-git", { method: "POST" }).then(function(d) {
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
  }).catch(function(err) {
    console.error("API error:", err);
  });
};

var _chAllSnapshots = [];
var _chShowMilestones = false;
var _chCurrentFiltered = [];

// Milestone thresholds — lines and files
var CH_LINE_MILESTONES = [1000, 10000, 50000, 100000, 200000, 300000, 400000, 500000];
var CH_FILE_MILESTONES = [50, 100, 200, 500, 1000];

function _computeMilestones(snapshots) {
  var annotations = {};
  var lineHit = {};
  var fileHit = {};
  var colors = {
    lines: "rgba(139, 92, 246, 0.6)",
    files: "rgba(0, 204, 255, 0.5)"
  };

  for (var i = 0; i < snapshots.length; i++) {
    var s = snapshots[i];
    // Line milestones
    for (var j = 0; j < CH_LINE_MILESTONES.length; j++) {
      var m = CH_LINE_MILESTONES[j];
      if (!lineHit[m] && s.total_lines >= m) {
        lineHit[m] = true;
        var label = m >= 1000 ? (m / 1000) + "K" : m;
        annotations["line_" + m] = {
          type: "line",
          xMin: i, xMax: i,
          borderColor: colors.lines,
          borderWidth: 1,
          borderDash: [4, 3],
          label: {
            display: true,
            content: label + " lines",
            position: "start",
            backgroundColor: "rgba(139, 92, 246, 0.85)",
            color: "#fff",
            font: { size: 9, weight: "bold" },
            padding: { top: 2, bottom: 2, left: 4, right: 4 },
            borderRadius: 3
          }
        };
      }
    }
    // File milestones
    for (var k = 0; k < CH_FILE_MILESTONES.length; k++) {
      var fm = CH_FILE_MILESTONES[k];
      if (!fileHit[fm] && s.total_files >= fm) {
        fileHit[fm] = true;
        annotations["file_" + fm] = {
          type: "line",
          xMin: i, xMax: i,
          borderColor: colors.files,
          borderWidth: 1,
          borderDash: [2, 4],
          label: {
            display: true,
            content: fm + " files",
            position: "end",
            backgroundColor: "rgba(0, 204, 255, 0.85)",
            color: "#000",
            font: { size: 9, weight: "bold" },
            padding: { top: 2, bottom: 2, left: 4, right: 4 },
            borderRadius: 3
          }
        };
      }
    }
  }
  return annotations;
}

function _renderHistoryChart(snapshots) {
  var canvas = document.getElementById("chHistoryChart");
  if (!canvas || !snapshots.length) return;

  _chAllSnapshots = snapshots;
  _chCurrentFiltered = snapshots;
  _drawHistoryChart(snapshots);
}

function _drawHistoryChart(snapshots) {
  var canvas = document.getElementById("chHistoryChart");
  if (!canvas || !snapshots.length) return;

  var labels = snapshots.map(function(s) {
    var d = new Date(s.scanned_at);
    return d.toLocaleDateString([], { month: "short", day: "numeric", year: "2-digit" });
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
          borderWidth: 2,
          pointRadius: snapshots.length > 50 ? 0 : 3,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.3
        },
        {
          label: "Total Files",
          data: snapshots.map(function(s) { return s.total_files; }),
          borderColor: "#0cf",
          backgroundColor: "rgba(0, 204, 255, 0.1)",
          borderWidth: 2,
          pointRadius: snapshots.length > 50 ? 0 : 3,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.3,
          yAxisID: "y1"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "rgba(255,255,255,0.6)" } },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              return ctx.dataset.label + ": " + ctx.parsed.y.toLocaleString();
            }
          }
        },
        annotation: {
          annotations: _chShowMilestones ? _computeMilestones(snapshots) : {}
        },
        zoom: {
          pan: {
            enabled: true,
            mode: "x",
            modifierKey: null
          },
          zoom: {
            drag: { enabled: true, backgroundColor: "rgba(139,92,246,0.15)", borderColor: "#8b5cf6", borderWidth: 1 },
            mode: "x",
            onZoomComplete: function() {
              var el = document.querySelector(".ch-range-btn.active");
              if (el) { el.classList.remove("active"); el.style.background = "transparent"; }
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: "rgba(255,255,255,0.5)", maxRotation: 45, maxTicksLimit: 20 },
          grid: { color: "rgba(255,255,255,0.05)" }
        },
        y: {
          position: "left",
          ticks: { color: "#8b5cf6", callback: function(v) { return v >= 1000 ? (v / 1000).toFixed(0) + "k" : v; } },
          grid: { color: "rgba(255,255,255,0.05)" }
        },
        y1: {
          position: "right",
          ticks: { color: "#0cf" },
          grid: { display: false }
        }
      }
    }
  });
}

window.chFilterHistory = function(range) {
  var now = new Date();
  var cutoff = null;
  if (range === "1w") cutoff = new Date(now - 7 * 86400000);
  else if (range === "1m") cutoff = new Date(now - 30 * 86400000);
  else if (range === "3m") cutoff = new Date(now - 90 * 86400000);

  var filtered = _chAllSnapshots;
  if (cutoff) {
    filtered = _chAllSnapshots.filter(function(s) {
      return new Date(s.scanned_at) >= cutoff;
    });
  }
  if (filtered.length === 0) filtered = _chAllSnapshots;
  _chCurrentFiltered = filtered;
  _drawHistoryChart(filtered);

  // Update active button
  document.querySelectorAll(".ch-range-btn").forEach(function(btn) {
    btn.classList.remove("active");
    btn.style.background = "transparent";
  });
  var active = document.querySelector('.ch-range-btn[data-range="' + range + '"]');
  if (active) {
    active.classList.add("active");
    active.style.background = "rgba(139,92,246,0.2)";
  }
};

window.chResetZoom = function() {
  if (_chHistoryChart) _chHistoryChart.resetZoom();
};

window.chToggleMilestones = function() {
  _chShowMilestones = !_chShowMilestones;
  var btn = document.getElementById("chMilestoneToggle");
  if (btn) {
    if (_chShowMilestones) {
      btn.style.background = "rgba(245,158,11,0.2)";
      btn.style.borderColor = "#f59e0b";
    } else {
      btn.style.background = "transparent";
      btn.style.borderColor = "rgba(245,158,11,0.4)";
    }
  }
  _drawHistoryChart(_chCurrentFiltered.length ? _chCurrentFiltered : _chAllSnapshots);
};

function _renderAuditTable(entries) {
  var el = document.getElementById("chAuditTable");
  if (!el) return;

  if (!entries.length) {
    setHtml(el, '<div class="ch-empty">No audit entries yet. Run a scan and audit modules to track code quality progress.</div>');
    return;
  }

  // Track latest audit entry per module (entries come sorted desc by date)
  var latestPerModule = {};
  entries.forEach(function(e) {
    if (e.module_name !== "PATTERN_COMPLIANCE") {
      if (!latestPerModule[e.module_name]) latestPerModule[e.module_name] = e;
    }
  });

  // Count from latest-per-module only, filtered to current snapshot modules
  var currentModules = _chModuleData ? Object.keys(_chModuleData) : [];
  var totalModules = currentModules.length || Object.keys(window._chDisplayNames || {}).length;
  var auditedCount = 0;
  var cleanCount = 0;
  Object.keys(latestPerModule).forEach(function(key) {
    // Only count modules that exist in the current snapshot
    if (currentModules.length === 0 || currentModules.indexOf(key) !== -1) {
      auditedCount++;
      if (latestPerModule[key].status === "completed") cleanCount++;
    }
  });
  var auditPct = totalModules > 0 ? Math.round(auditedCount / totalModules * 100) : 0;
  var cleanPct = totalModules > 0 ? Math.round(cleanCount / totalModules * 100) : 0;
  var auditBarColor = auditPct >= 75 ? '#3b82f6' : auditPct >= 25 ? '#f59e0b' : '#ef4444';
  var cleanBarColor = cleanPct >= 75 ? '#22c55e' : cleanPct >= 25 ? '#f59e0b' : '#ef4444';

  // Centered progress bars
  var html = '<div style="display:flex;flex-wrap:wrap;gap:16px;padding:10px 16px;margin-bottom:12px;border-radius:6px;background:rgba(255,255,255,0.02);justify-content:center;align-items:center;">'
    + '<div style="display:flex;align-items:center;gap:8px;">'
    + '<span style="font-size:0.7rem;color:rgba(255,255,255,0.5);min-width:55px;">Audited</span>'
    + '<div style="width:140px;height:8px;background:rgba(255,255,255,0.08);border-radius:4px;">'
    + '<div style="height:100%;width:' + auditPct + '%;background:' + auditBarColor + ';border-radius:4px;transition:width 0.5s;"></div></div>'
    + '<span style="font-size:0.7rem;font-weight:600;color:' + auditBarColor + ';">' + auditedCount + '/' + totalModules + ' (' + auditPct + '%)</span>'
    + '</div>'
    + '<div style="display:flex;align-items:center;gap:8px;">'
    + '<span style="font-size:0.7rem;color:rgba(255,255,255,0.5);min-width:55px;" title="Latest audit has no actionable findings; separate scanners may still have repair proposals">Audit clean</span>'
    + '<div style="width:140px;height:8px;background:rgba(255,255,255,0.08);border-radius:4px;">'
    + '<div style="height:100%;width:' + cleanPct + '%;background:' + cleanBarColor + ';border-radius:4px;transition:width 0.5s;"></div></div>'
    + '<span style="font-size:0.7rem;font-weight:600;color:' + cleanBarColor + ';">' + cleanCount + '/' + totalModules + ' (' + cleanPct + '%)</span>'
    + '</div>'
    + '</div>';

  html += '<table class="ch-table"><thead><tr>' +
    '<th>Module</th><th class="center">Profile</th><th class="center">Trigger</th>' +
    '<th class="center">Files</th><th class="center">Lines</th>' +
    '<th class="center">Issues</th><th class="center">Status</th><th class="center">Proposals</th><th class="center"></th><th class="center">Date</th>' +
    '</tr></thead><tbody>';

  // Separate PATTERN_COMPLIANCE scans from real module audits
  var patternEntries = entries.filter(function(e) { return e.module_name === "PATTERN_COMPLIANCE"; });
  var moduleEntries = entries.filter(function(e) { return e.module_name !== "PATTERN_COMPLIANCE"; });

  // Show only latest audit per module by default
  var latestEntries = Object.values(latestPerModule);
  latestEntries.sort(function(a, b) { return (b.audited_at || "").localeCompare(a.audited_at || ""); });

  latestEntries.forEach(function(e) {
    var pCount = (window._chProposalCounts || {})[e.module_name] || 0;
    var hasProposals = pCount > 0;
    // 5-status: clean, in repair (purple), issues (orange), stale, unaudited
    var badgeClass, statusLabel, nameColor;
    if (e.status === "completed") {
      badgeClass = "ch-badge-green"; statusLabel = "CLEAN"; nameColor = "#22c55e";
    } else if (e.status === "violations_found" && hasProposals) {
      badgeClass = "ch-badge-purple"; statusLabel = "IN REPAIR"; nameColor = "#a78bfa";
    } else if (e.status === "violations_found") {
      badgeClass = "ch-badge-amber"; statusLabel = "ISSUES"; nameColor = "#f59e0b";
    } else if (e.status === "findings_open") {
      // #5942 — findings present, none red. MUST be handled here: this chain's final
      // else renders red "PENDING", the OPPOSITE default to the server-side summary
      // (which falls through to green). Leaving it unhandled would show the same module
      // green in the counts and red in the table.
      badgeClass = "ch-badge-amber"; statusLabel = "FINDINGS"; nameColor = "#f59e0b";
    } else {
      badgeClass = "ch-badge-red"; statusLabel = e.status || "PENDING"; nameColor = "#ef4444";
    }
    var issueColor = (e.issues_found || 0) === 0 ? "#22c55e" : (e.issues_found || 0) <= 5 ? "#f59e0b" : "#ef4444";
    var profileColors = {python: "rgba(139,92,246,0.15)", web: "rgba(245,158,11,0.15)", config: "rgba(148,163,184,0.15)"};
    var profileTextColors = {python: "#8b5cf6", web: "#f59e0b", config: "#94a3b8"};
    var prof = e.audit_profile || "python";
    var profileCell = '<span style="font-size:0.55rem;padding:1px 5px;border-radius:3px;background:' + (profileColors[prof] || profileColors.python) + ';color:' + (profileTextColors[prof] || profileTextColors.python) + ';text-transform:uppercase;">' + escHtml(prof) + '</span>';
    var triggerCell = e.trigger_reason ? '<span style="font-size:0.55rem;padding:1px 4px;border-radius:3px;background:rgba(0,229,255,0.1);color:rgba(0,229,255,0.6);">' + escHtml(e.trigger_reason) + '</span>' : '\u2014';
    // Proposals cell
    var proposalCell;
    if (pCount > 0) {
      proposalCell = '<span style="font-size:0.6rem;color:#a78bfa;font-weight:600;">' + pCount + ' in repair</span>';
    } else if (e.status === "violations_found") {
      proposalCell = '<span style="font-size:0.6rem;color:rgba(255,255,255,0.3);">not submitted</span>';
    } else {
      proposalCell = '<span style="font-size:0.6rem;color:rgba(255,255,255,0.15);">\u2014</span>';
    }
    html += '<tr data-audit-id="' + e.id + '">' +
      '<td><span style="color:' + nameColor + ';font-weight:600;">' + escHtml(window._chDisplayNames && window._chDisplayNames[e.module_name] || e.module_name) + '</span></td>' +
      '<td class="center">' + profileCell + '</td>' +
      '<td class="center">' + triggerCell + '</td>' +
      '<td class="center">' + (e.files_reviewed || 0) + '</td>' +
      '<td class="center">' + (e.lines_before || 0).toLocaleString() + '</td>' +
      '<td class="center" style="color:' + issueColor + ';font-weight:600;">' + (e.issues_found || 0) + '</td>' +
      '<td class="center"><span class="ch-badge ' + badgeClass + '"><span class="ch-badge-dot"></span>' + statusLabel + '</span></td>' +
      '<td class="center">' + proposalCell + '</td>' +
      '<td class="center"><button class="ch-report-btn" data-audit-id="' + e.id + '" style="background:rgba(139,92,246,0.1);color:#a78bfa;border:1px solid rgba(139,92,246,0.3);padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;text-transform:uppercase;">Report</button></td>' +
      '<td class="center" style="font-size:0.7rem;white-space:nowrap;color:rgba(255,255,255,0.5);">' + formatAge(e.audited_at) + '</td>' +
      '</tr>';
  });

  // Collapse PATTERN_COMPLIANCE into a single summary row
  if (patternEntries.length > 0) {
    var totalIssues = patternEntries.reduce(function(s, e) { return s + (e.issues_found || 0); }, 0);
    var latestPat = patternEntries[0];
    var patBadgeClass = latestPat.status === "completed" ? "ch-badge-green" : "ch-badge-purple";
    var patStatusLabel = latestPat.status === "completed" ? "CLEAN" : "ISSUES";
    html += '<tr data-audit-id="' + latestPat.id + '" style="border-top:1px solid rgba(255,255,255,0.08);">' +
      '<td><span style="color:rgba(255,255,255,0.4);font-weight:600;">Pattern Compliance</span>' +
      ' <span style="font-size:0.55rem;background:rgba(139,92,246,0.15);color:#a78bfa;padding:1px 5px;border-radius:3px;">' + patternEntries.length + ' scans</span></td>' +
      '<td class="center">\u2014</td>' +
      '<td class="center"><span style="font-size:0.55rem;padding:1px 4px;border-radius:3px;background:rgba(0,229,255,0.1);color:rgba(0,229,255,0.6);">scheduled</span></td>' +
      '<td class="center" colspan="2" style="font-size:0.7rem;color:rgba(255,255,255,0.35);">automated</td>' +
      '<td class="center" style="color:' + (totalIssues > 0 ? '#f59e0b' : '#22c55e') + ';font-weight:600;">' + totalIssues + '</td>' +
      '<td class="center"><span class="ch-badge ' + patBadgeClass + '"><span class="ch-badge-dot"></span>' + patStatusLabel + '</span></td>' +
      '<td class="center"><span style="font-size:0.6rem;color:rgba(255,255,255,0.15);">\u2014</span></td>' +
      '<td class="center"><button class="ch-report-btn" data-audit-id="' + latestPat.id + '" style="background:rgba(139,92,246,0.1);color:#a78bfa;border:1px solid rgba(139,92,246,0.3);padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;text-transform:uppercase;">Report</button></td>' +
      '<td class="center" style="font-size:0.7rem;color:rgba(255,255,255,0.5);">' + formatAge(latestPat.audited_at) + '</td>' +
      '</tr>';
  }

  html += '</tbody></table>';
  setHtml(el, html);

  // Report button click handler
  el.querySelectorAll(".ch-report-btn").forEach(function(btn) {
    btn.addEventListener("click", function(evt) {
      evt.stopPropagation();
      showAuditDetail(parseInt(btn.getAttribute("data-audit-id")));
    });
  });
}

window.showAuditDetail = function(auditId) {
  // Remove existing modal
  var existing = document.getElementById("chAuditModal");
  if (existing) existing.remove();

  // Create LCARS-style modal overlay
  var overlay = document.createElement("div");
  overlay.id = "chAuditModal";
  overlay.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;";
  overlay.addEventListener("click", function(e) { if (e.target === overlay) overlay.remove(); });

  var modal = document.createElement("div");
  modal.style.cssText = "background:#0a1628;border:1px solid rgba(0,229,255,0.3);border-radius:8px;max-width:700px;width:100%;max-height:80vh;overflow-y:auto;padding:24px;box-shadow:0 0 30px rgba(0,229,255,0.1);";

  // Loading state
  modal.textContent = "Loading audit report...";
  modal.style.color = "rgba(255,255,255,0.5)";
  modal.style.textAlign = "center";
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  // Fetch audit details
  api("/api/code-health/audit/" + auditId + "/details").then(function(d) {
    if (!d.success) {
      modal.textContent = "Failed to load audit: " + (d.error || "unknown error");
      return;
    }

    var a = d.audit;
    var findings = d.findings || [];

    // Build modal content using safe DOM methods
    modal.textContent = "";
    modal.style.textAlign = "";
    modal.style.color = "";

    // Header
    var header = document.createElement("div");
    header.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid rgba(0,229,255,0.15);";
    var title = document.createElement("div");
    var displayName = (window._chDisplayNames || {})[a.module_name] || a.module_name;
    title.style.cssText = "font-family:'Orbitron',sans-serif;font-size:1rem;font-weight:600;color:#00e5ff;letter-spacing:1px;";
    title.textContent = displayName;
    var closeBtn = document.createElement("button");
    closeBtn.style.cssText = "background:none;border:1px solid rgba(255,255,255,0.2);color:rgba(255,255,255,0.5);padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;";
    closeBtn.textContent = "Close";
    closeBtn.onclick = function() { overlay.remove(); };
    header.appendChild(title);
    header.appendChild(closeBtn);
    modal.appendChild(header);

    // Meta info row
    var meta = document.createElement("div");
    meta.style.cssText = "display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;";
    var metaItems = [
      {label: "Profile", value: a.audit_profile || "python", color: "#8b5cf6"},
      {label: "Trigger", value: a.trigger_reason || "unknown", color: "#00e5ff"},
      {label: "Status", value: a.status === "completed" ? "CLEAN" : "ISSUES", color: a.status === "completed" ? "#22c55e" : "#f59e0b"},
      {label: "Files", value: a.files_reviewed, color: "#fff"},
      {label: "Issues", value: a.issues_found, color: a.issues_found > 0 ? "#ef4444" : "#22c55e"}
    ];
    metaItems.forEach(function(m) {
      var chip = document.createElement("div");
      chip.style.cssText = "text-align:center;padding:6px 12px;background:rgba(255,255,255,0.03);border-radius:4px;border:1px solid rgba(255,255,255,0.06);";
      var val = document.createElement("div");
      val.style.cssText = "font-size:0.9rem;font-weight:600;color:" + m.color + ";";
      val.textContent = m.value;
      var lbl = document.createElement("div");
      lbl.style.cssText = "font-size:0.55rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;";
      lbl.textContent = m.label;
      chip.appendChild(val);
      chip.appendChild(lbl);
      meta.appendChild(chip);
    });
    if (a.dispatched_via) {
      var agentChip = document.createElement("div");
      agentChip.style.cssText = "text-align:center;padding:6px 12px;background:rgba(139,92,246,0.05);border-radius:4px;border:1px solid rgba(139,92,246,0.15);";
      var agentVal = document.createElement("div");
      agentVal.style.cssText = "font-size:0.9rem;font-weight:600;color:#a78bfa;";
      agentVal.textContent = a.dispatched_via;
      var agentLbl = document.createElement("div");
      agentLbl.style.cssText = "font-size:0.55rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;";
      agentLbl.textContent = "Audited By";
      agentChip.appendChild(agentVal);
      agentChip.appendChild(agentLbl);
      meta.appendChild(agentChip);
    }
    modal.appendChild(meta);

    // Findings section
    if (findings.length === 0) {
      var clean = document.createElement("div");
      clean.style.cssText = "text-align:center;padding:20px;color:#22c55e;font-weight:600;background:rgba(34,197,94,0.05);border:1px solid rgba(34,197,94,0.15);border-radius:6px;";
      clean.textContent = "All checks passed — no issues found";
      modal.appendChild(clean);
    } else {
      var findingsTitle = document.createElement("div");
      findingsTitle.style.cssText = "font-size:0.75rem;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-weight:600;";
      findingsTitle.textContent = "Findings (" + findings.length + ")";
      modal.appendChild(findingsTitle);

      findings.forEach(function(f) {
        var row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:flex-start;gap:8px;padding:8px 10px;margin-bottom:4px;border-radius:4px;background:rgba(255,255,255,0.02);border-left:3px solid " + (f.severity === "red" ? "#ef4444" : f.severity === "yellow" ? "#f59e0b" : "#3b82f6") + ";";
        var codeBadge = document.createElement("span");
        var sevColor = f.severity === "red" ? "#ef4444" : f.severity === "yellow" ? "#f59e0b" : "#3b82f6";
        codeBadge.style.cssText = "font-size:0.6rem;padding:2px 6px;border-radius:3px;background:" + sevColor + "22;color:" + sevColor + ";font-weight:600;flex-shrink:0;font-family:'IBM Plex Mono',monospace;";
        codeBadge.textContent = f.code;
        var detail = document.createElement("span");
        detail.style.cssText = "font-size:0.75rem;color:rgba(255,255,255,0.6);word-break:break-word;";
        detail.textContent = f.detail || "";
        row.appendChild(codeBadge);
        row.appendChild(detail);
        modal.appendChild(row);
      });
    }

    // Proposal status indicator with individual tracking
    var proposals = d.proposals || {total: 0, by_status: {}, items: []};
    if (proposals.total > 0) {
      var propBar = document.createElement("div");
      propBar.style.cssText = "padding:10px 12px;margin-top:16px;background:rgba(139,92,246,0.05);border:1px solid rgba(139,92,246,0.15);border-radius:6px;";
      var propTitle = document.createElement("div");
      propTitle.style.cssText = "font-size:0.7rem;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;text-align:center;font-weight:600;";
      propTitle.textContent = "Repair Bay Proposals (" + proposals.total + " active)";
      propBar.appendChild(propTitle);

      // Show individual proposals with IDs
      var propList = document.createElement("div");
      propList.style.cssText = "max-height:150px;overflow-y:auto;";
      var statusColors = {pending:"#f59e0b",pending_approval:"#f59e0b",approved:"#8b5cf6",deployed:"#10b981",fix_requested:"#ef4444"};
      var prioColors = {critical:"#ef4444",high:"#f59e0b",medium:"#3b82f6",low:"#22c55e"};
      (proposals.items || []).forEach(function(p) {
        var row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:6px;padding:3px 0;font-size:0.7rem;";
        var idBadge = document.createElement("span");
        idBadge.style.cssText = "color:rgba(0,229,255,0.5);font-family:'IBM Plex Mono',monospace;font-size:0.6rem;min-width:35px;";
        idBadge.textContent = "#" + p.id;
        var statusBadge = document.createElement("span");
        var sc = statusColors[p.status] || "#999";
        statusBadge.style.cssText = "font-size:0.55rem;padding:1px 5px;border-radius:3px;background:" + sc + "15;color:" + sc + ";border:1px solid " + sc + "33;min-width:55px;text-align:center;";
        statusBadge.textContent = p.status.replace(/_/g, " ");
        var prioBadge = document.createElement("span");
        var pc = prioColors[p.priority] || "#999";
        prioBadge.style.cssText = "font-size:0.55rem;padding:1px 4px;border-radius:3px;background:" + pc + "15;color:" + pc + ";";
        prioBadge.textContent = p.priority;
        var titleSpan = document.createElement("span");
        titleSpan.style.cssText = "color:rgba(255,255,255,0.5);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.65rem;";
        titleSpan.textContent = p.title;
        row.appendChild(idBadge);
        row.appendChild(statusBadge);
        row.appendChild(prioBadge);
        row.appendChild(titleSpan);
        propList.appendChild(row);
      });
      propBar.appendChild(propList);
      modal.appendChild(propBar);
    }

    // Action buttons
    var actions = document.createElement("div");
    actions.style.cssText = "display:flex;gap:10px;justify-content:center;margin-top:12px;padding-top:16px;border-top:1px solid rgba(0,229,255,0.1);";

    if (a.issues_found > 0) {
      var submitBtn = document.createElement("button");
      var alreadySubmitted = proposals.total > 0;
      submitBtn.style.cssText = alreadySubmitted
        ? "background:rgba(34,197,94,0.1);color:#22c55e;border:1px solid rgba(34,197,94,0.3);padding:8px 20px;border-radius:4px;font-size:0.75rem;cursor:pointer;text-transform:uppercase;letter-spacing:1px;font-weight:600;"
        : "background:rgba(139,92,246,0.15);color:#a78bfa;border:1px solid rgba(139,92,246,0.4);padding:8px 20px;border-radius:4px;font-size:0.75rem;cursor:pointer;text-transform:uppercase;letter-spacing:1px;font-weight:600;";
      submitBtn.textContent = alreadySubmitted ? "Re-submit to Repair Bay" : "Submit to Repair Bay";
      submitBtn.onclick = function() {
        submitBtn.disabled = true;
        submitBtn.textContent = "Submitting...";
        api("/api/code-health/audit/" + auditId + "/submit-repair", {method: "POST"}).then(function(r) {
          if (r.success) {
            var msg = r.proposals_created + " new proposals";
            if (r.skipped_duplicates > 0) msg += ", " + r.skipped_duplicates + " already in pipeline";
            submitBtn.textContent = msg;
            submitBtn.style.background = "rgba(34,197,94,0.15)";
            submitBtn.style.color = "#22c55e";
            submitBtn.style.borderColor = "#22c55e";
          } else {
            submitBtn.textContent = r.error || "Failed";
            submitBtn.style.color = "#ef4444";
            submitBtn.disabled = false;
          }
        }).catch(function() {
          submitBtn.textContent = "Failed — retry";
          submitBtn.disabled = false;
        });
      };
      actions.appendChild(submitBtn);
    }

    var closeBtn2 = document.createElement("button");
    closeBtn2.style.cssText = "background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.5);border:1px solid rgba(255,255,255,0.15);padding:8px 20px;border-radius:4px;font-size:0.75rem;cursor:pointer;text-transform:uppercase;letter-spacing:1px;";
    closeBtn2.textContent = "Close";
    closeBtn2.onclick = function() { overlay.remove(); };
    actions.appendChild(closeBtn2);

    modal.appendChild(actions);

  }).catch(function(err) {
    modal.textContent = "Error loading audit: " + err.message;
    modal.style.color = "#ef4444";
  });
};
