/* consciousness-dashboard-v2.js -- Project-Knowledge Integration Panels
   Depends on: consciousness.js (api() and escHtml() helpers)
   Security: All dynamic content uses safe DOM methods (createElement/textContent).
*/

(function () {
  "use strict";

  var _contribDays = null;
  var _contribProjectId = null;
  var _expertiseData = null;

  function renderCompletenessRing(pct) {
    var r = 20, circ = 2 * Math.PI * r;
    var offset = circ - (pct / 100) * circ;
    var el = document.createElement("div");
    el.className = "cs-completeness-ring";

    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 48 48");

    var bg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    bg.setAttribute("class", "ring-bg");
    bg.setAttribute("cx", "24");
    bg.setAttribute("cy", "24");
    bg.setAttribute("r", String(r));
    svg.appendChild(bg);

    var fill = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    fill.setAttribute("class", "ring-fill");
    fill.setAttribute("cx", "24");
    fill.setAttribute("cy", "24");
    fill.setAttribute("r", String(r));
    fill.setAttribute("stroke-dasharray", String(circ));
    fill.setAttribute("stroke-dashoffset", String(offset));
    svg.appendChild(fill);

    el.appendChild(svg);

    var txt = document.createElement("div");
    txt.className = "ring-text";
    txt.textContent = pct + "%";
    el.appendChild(txt);

    return el;
  }

  function renderExpertiseScoreBar(score) {
    var wrap = document.createElement("span");
    wrap.style.display = "inline-flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "4px";

    var bar = document.createElement("span");
    bar.className = "cs-expertise-score-bar";
    var fill = document.createElement("span");
    fill.className = "cs-expertise-score-fill " + (score >= 70 ? "high" : score >= 40 ? "mid" : "low");
    fill.style.width = Math.min(score, 100) + "%";
    bar.appendChild(fill);
    wrap.appendChild(bar);

    var num = document.createElement("span");
    num.className = "cs-expertise-score-num";
    num.textContent = String(score);
    wrap.appendChild(num);

    return wrap;
  }

  function renderPhaseProgress(phases) {
    if (!phases || phases.length === 0) return null;

    var wrap = document.createElement("div");
    wrap.className = "cs-phase-progress";

    phases.forEach(function (p) {
      var row = document.createElement("div");
      row.className = "cs-phase-row";

      var label = document.createElement("span");
      label.className = "cs-phase-label";
      label.textContent = p.phase;
      row.appendChild(label);

      var barWrap = document.createElement("div");
      barWrap.className = "cs-phase-bar-wrap";

      var bar = document.createElement("div");
      bar.className = "cs-phase-bar";
      bar.style.width = Math.min(p.pct, 100) + "%";
      if (p.pct >= 100) bar.classList.add("complete");
      else if (p.pct >= 50) bar.classList.add("mid");
      barWrap.appendChild(bar);
      row.appendChild(barWrap);

      var stat = document.createElement("span");
      stat.className = "cs-phase-stat";
      stat.textContent = p.completed + "/" + p.total + " (" + p.pct + "%)";
      row.appendChild(stat);

      wrap.appendChild(row);
    });

    return wrap;
  }

  function renderExpertisePanel(data) {
    if (!data || !data.success) return;

    _expertiseData = data.projects || [];

    var tabsEl = document.getElementById("cs-expertise-project-tabs");
    if (!tabsEl) return;

    tabsEl.textContent = "";

    if (_expertiseData.length === 0) {
      var body = document.getElementById("cs-agent-expertise-body");
      if (body) {
        body.textContent = "";
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No active projects found.";
        body.appendChild(p);
      }
      return;
    }

    _expertiseData.forEach(function (proj, idx) {
      var tab = document.createElement("button");
      tab.className = "cs-expertise-tab" + (idx === 0 ? " active" : "");
      tab.textContent = proj.name.length > 25 ? proj.name.substring(0, 25) + "..." : proj.name;
      tab.title = proj.name;
      tab.addEventListener("click", function () {
        tabsEl.querySelectorAll(".cs-expertise-tab").forEach(function (t) {
          t.classList.remove("active");
        });
        tab.classList.add("active");
        renderExpertiseProject(proj);
      });
      tabsEl.appendChild(tab);
    });

    renderExpertiseProject(_expertiseData[0]);
  }

  function renderExpertiseProject(proj) {
    var container = document.getElementById("cs-agent-expertise-body");
    if (!container) return;

    container.textContent = "";

    var contributors = proj.contributors || [];
    var recommended = proj.recommended || [];

    if (contributors.length === 0 && recommended.length === 0) {
      var p = document.createElement("p");
      p.style.color = "#94a3b8";
      p.textContent = "No expertise data yet \u2014 scores will build as agents work on this project.";
      container.appendChild(p);
      return;
    }

    // Active Contributors
    if (contributors.length > 0) {
      var title1 = document.createElement("div");
      title1.className = "cs-expertise-section-title";
      title1.textContent = "Active Contributors";
      container.appendChild(title1);

      var table = document.createElement("table");
      table.className = "cs-expertise-table";

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      ["Agent", "Department", "Dispatches", "Success", "Score"].forEach(function (h) {
        var th = document.createElement("th");
        th.textContent = h;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      contributors.forEach(function (c) {
        var tr = document.createElement("tr");

        var tdName = document.createElement("td");
        tdName.textContent = c.display_name;
        if (c.is_director) {
          var badge = document.createElement("span");
          badge.className = "cs-director-badge";
          badge.textContent = "DIR";
          tdName.appendChild(badge);
        }
        tr.appendChild(tdName);

        var tdDept = document.createElement("td");
        tdDept.textContent = c.department;
        tdDept.style.fontSize = "0.8rem";
        tr.appendChild(tdDept);

        var tdDisp = document.createElement("td");
        tdDisp.textContent = String(c.dispatches);
        tr.appendChild(tdDisp);

        var tdSucc = document.createElement("td");
        var rate = c.dispatches > 0 ? Math.round(c.successes / c.dispatches * 100) : 0;
        tdSucc.textContent = rate + "%";
        tdSucc.style.color = rate >= 80 ? "#10b981" : rate >= 50 ? "#fbbf24" : "#ef4444";
        tr.appendChild(tdSucc);

        var tdScore = document.createElement("td");
        tdScore.appendChild(renderExpertiseScoreBar(c.expertise_score));
        tr.appendChild(tdScore);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      container.appendChild(table);
    }

    // Recommended Agents
    if (recommended.length > 0) {
      var title2 = document.createElement("div");
      title2.className = "cs-expertise-section-title";
      title2.textContent = "Recommended Agents";
      container.appendChild(title2);

      recommended.forEach(function (r) {
        var card = document.createElement("div");
        card.className = "cs-recommended-card";

        var info = document.createElement("div");
        info.className = "cs-recommended-info";

        var nameEl = document.createElement("div");
        nameEl.className = "cs-recommended-name";
        nameEl.textContent = r.display_name;
        if (r.is_director) {
          var dirBadge = document.createElement("span");
          dirBadge.className = "cs-director-badge";
          dirBadge.textContent = "DIR";
          nameEl.appendChild(dirBadge);
        }
        info.appendChild(nameEl);

        var deptEl = document.createElement("div");
        deptEl.className = "cs-recommended-dept";
        deptEl.textContent = r.department + (r.dept_match ? " \u2022 Department Match" : "");
        info.appendChild(deptEl);

        card.appendChild(info);

        if (r.matching_skills && r.matching_skills.length > 0) {
          var chips = document.createElement("div");
          chips.className = "cs-skill-chips";
          r.matching_skills.forEach(function (sk) {
            var chip = document.createElement("span");
            chip.className = "cs-skill-chip";
            chip.textContent = sk;
            chips.appendChild(chip);
          });
          card.appendChild(chips);
        }

        card.appendChild(renderExpertiseScoreBar(r.expertise_score));
        container.appendChild(card);
      });
    }
  }

  function renderProjectKnowledgeMap(data) {
      if (!data || !data.success) return;
      var container = document.getElementById("cs-project-knowledge-map");
      if (!container) return;

      container.textContent = "";

      if (!data.gaps || data.gaps.length === 0) {
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No active projects found.";
        container.appendChild(p);
        return;
      }

      data.gaps.forEach(function (proj) {
        var card = document.createElement("div");
        card.className = "cs-project-card";
        card.addEventListener("click", function () {
          toggleProjectCard(card, proj.project_id);
        });

        var header = document.createElement("div");
        header.className = "cs-project-card-header";

        var title = document.createElement("span");
        title.className = "cs-project-card-title";
        title.textContent = proj.name;
        header.appendChild(title);

        var stats = document.createElement("div");
        stats.className = "cs-project-card-stats";
        stats.appendChild(renderCompletenessRing(proj.completeness));

        var labels = [
          (proj.counts.vault_note || 0) + " docs",
          (proj.counts.mistake_learned || 0) + " mistakes",
          (proj.counts.code_snippet || 0) + " snippets"
        ];
        labels.forEach(function (lbl) {
          var sp = document.createElement("span");
          sp.textContent = lbl;
          stats.appendChild(sp);
        });
        header.appendChild(stats);
        card.appendChild(header);

        var expanded = document.createElement("div");
        expanded.className = "cs-project-card-expanded";
        expanded.id = "cs-proj-expand-" + proj.project_id;
        card.appendChild(expanded);

        container.appendChild(card);
      });
  }

  function toggleProjectCard(el, projectId) {
    var isExpanded = el.classList.contains("expanded");
    document.querySelectorAll(".cs-project-card.expanded").forEach(function (c) {
      c.classList.remove("expanded");
    });
    if (isExpanded) return;

    el.classList.add("expanded");
    var expandEl = document.getElementById("cs-proj-expand-" + projectId);
    if (!expandEl) return;

    expandEl.textContent = "";
    var loading = document.createElement("p");
    loading.style.color = "#94a3b8";
    loading.textContent = "Loading...";
    expandEl.appendChild(loading);

    loadAgentContributions(projectId, _contribDays);

    api("/api/dashboard/project-knowledge/" + projectId).then(function (data) {
      expandEl.textContent = "";
      if (!data || !data.success) {
        var err = document.createElement("p");
        err.style.color = "#ef4444";
        err.textContent = "Failed to load.";
        expandEl.appendChild(err);
        return;
      }
      var kb = data.knowledge || [];
      if (kb.length === 0) {
        var empty = document.createElement("p");
        empty.style.color = "#94a3b8";
        empty.textContent = "No linked knowledge entries yet.";
        expandEl.appendChild(empty);
        return;
      }
      kb.forEach(function (entry) {
        var row = document.createElement("div");
        row.className = "cs-kb-entry";

        var badge = document.createElement("span");
        var isDraft = (entry.title || "").indexOf("Project Report:") === 0;
        badge.className = "cs-link-badge " + (isDraft ? "draft" : entry.link_type);
        badge.textContent = isDraft ? "DRAFT" : entry.link_type;
        row.appendChild(badge);

        var titleSpan = document.createElement("span");
        titleSpan.textContent = entry.title || "Untitled";
        row.appendChild(titleSpan);

        var typeSpan = document.createElement("span");
        typeSpan.style.color = "#64748b";
        typeSpan.style.marginLeft = "auto";
        typeSpan.textContent = entry.knowledge_type || "";
        row.appendChild(typeSpan);

        expandEl.appendChild(row);
      });
    });
  }

  function loadAgentContributions(projectId, days) {
    _contribProjectId = projectId;
    _contribDays = days;

    var url = "/api/dashboard/agent-contributions/" + projectId;
    if (days) url += "?days=" + days;

    api(url).then(function (data) {
      if (!data || !data.success) return;
      var container = document.getElementById("cs-agent-contributions-body");
      if (!container) return;

      container.textContent = "";

      var contribs = data.contributions || [];
      if (contribs.length === 0) {
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No agent contributions recorded for this project.";
        container.appendChild(p);
        return;
      }

      var table = document.createElement("table");
      table.className = "cs-contrib-table";

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      ["Agent", "Dispatches", "Tasks", "Total"].forEach(function (h) {
        var th = document.createElement("th");
        th.textContent = h;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      contribs.forEach(function (c) {
        var tr = document.createElement("tr");
        var vals = [c.agent_name, c.dispatch_count, c.tasks_completed, c.total_actions];
        vals.forEach(function (v) {
          var td = document.createElement("td");
          td.textContent = String(v);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      container.appendChild(table);
    });
  }

  window.setContribFilter = function (days) {
    document.querySelectorAll(".cs-contrib-filter-btn").forEach(function (b) {
      b.classList.toggle("active", parseInt(b.dataset.days || "0") === (days || 0));
    });
    if (_contribProjectId) {
      loadAgentContributions(_contribProjectId, days);
    }
  };

  function renderKnowledgeGaps(data) {
      if (!data || !data.success) return;
      var container = document.getElementById("cs-knowledge-gaps-body");
      if (!container) return;

      container.textContent = "";

      var gaps = data.gaps || [];
      if (gaps.length === 0) {
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No active projects.";
        container.appendChild(p);
        return;
      }

      var gapChipMap = {
        vault_note: { cls: "docs", label: "DOCS" },
        mistake_learned: { cls: "mistakes", label: "MISTAKES" },
        code_snippet: { cls: "snippets", label: "SNIPPETS" },
        decisions: { cls: "decisions", label: "DECISIONS" },
        agent_activity: { cls: "activity", label: "AGENTS" }
      };

      gaps.forEach(function (proj) {
        var row = document.createElement("div");
        row.className = "cs-gap-row";

        row.appendChild(renderCompletenessRing(proj.completeness));

        // Quality score indicator
        if (typeof proj.quality_score === "number") {
          var qBadge = document.createElement("span");
          qBadge.className = "cs-quality-badge";
          var qVal = proj.quality_score;
          qBadge.classList.add(qVal >= 70 ? "high" : qVal >= 40 ? "mid" : "low");
          qBadge.textContent = "Q" + qVal;
          qBadge.title = "Quality: Content " + (proj.quality_breakdown ? proj.quality_breakdown.content : 0)
            + "/40, Coverage " + (proj.quality_breakdown ? proj.quality_breakdown.coverage : 0)
            + "/30, Freshness " + (proj.quality_breakdown ? proj.quality_breakdown.freshness : 0) + "/30";
          row.appendChild(qBadge);
        }

        var nameSpan = document.createElement("span");
        nameSpan.className = "cs-gap-name";
        nameSpan.textContent = proj.name;
        row.appendChild(nameSpan);

        var chips = document.createElement("div");
        chips.className = "cs-gap-chips";
        Object.keys(proj.gaps || {}).forEach(function (key) {
          var info = gapChipMap[key];
          if (info) {
            var chip = document.createElement("span");
            var gapText = proj.gaps[key];
            var isDraftOnly = gapText && gapText.indexOf("Drafts only") === 0;
            chip.className = "cs-gap-chip " + (isDraftOnly ? "drafts" : info.cls);
            chip.textContent = isDraftOnly ? "DRAFTS ONLY" : info.label;
            chips.appendChild(chip);
          }
        });
        row.appendChild(chips);

        var actions = document.createElement("div");
        actions.className = "cs-gap-actions";

        var btnDecision = document.createElement("button");
        btnDecision.className = "cs-gap-action-btn";
        btnDecision.textContent = "+ Decision";
        btnDecision.addEventListener("click", function (e) {
          e.stopPropagation();
          window.location.href = "/dev-hq";
        });
        actions.appendChild(btnDecision);

        var btnDocs = document.createElement("button");
        btnDocs.className = "cs-gap-action-btn";
        btnDocs.textContent = "+ Docs";
        btnDocs.addEventListener("click", function (e) {
          e.stopPropagation();
          if (typeof switchConsciousnessTab === "function") {
            switchConsciousnessTab("knowledge");
          }
        });
        actions.appendChild(btnDocs);

        var btnReport = document.createElement("button");
        btnReport.className = "cs-gap-action-btn cs-generate-report-btn";
        btnReport.textContent = proj.has_draft_docs ? "Report Pending" : "Generate Report";
        btnReport.disabled = proj.has_draft_docs;
        btnReport.addEventListener("click", function (e) {
          e.stopPropagation();
          btnReport.textContent = "Generating...";
          btnReport.disabled = true;
          api("/api/dashboard/generate-docs", {
            method: "POST",
            body: { project_id: proj.project_id },
          }).then(function (data) {
            if (data && data.success) {
              btnReport.textContent = "Report Generated";
              loadDashboardV2Panels();
            } else {
              btnReport.textContent = "Failed";
              btnReport.disabled = false;
            }
          });
        });
        actions.appendChild(btnReport);

        row.appendChild(actions);

        // Phase progress (expandable)
        if (proj.phases && proj.phases.length > 0) {
          var phaseToggle = document.createElement("div");
          phaseToggle.className = "cs-phase-toggle";
          phaseToggle.textContent = "▶ " + proj.phases.length + " phases";
          phaseToggle.style.cursor = "pointer";

          var phaseDetail = renderPhaseProgress(proj.phases);
          if (phaseDetail) {
            phaseDetail.style.display = "none";
            phaseToggle.addEventListener("click", function (e) {
              e.stopPropagation();
              var showing = phaseDetail.style.display !== "none";
              phaseDetail.style.display = showing ? "none" : "block";
              phaseToggle.textContent = (showing ? "▶ " : "▼ ") + proj.phases.length + " phases";
            });
          }

          row.appendChild(phaseToggle);
          if (phaseDetail) row.appendChild(phaseDetail);
        }

        container.appendChild(row);
      });
  }

  function renderKnowledgeGraph(data) {
    if (!data || !data.success) return;
    var canvas = document.getElementById("cs-knowledge-graph-canvas");
    if (!canvas) return;
    var _accentRgb = getComputedStyle(document.documentElement).getPropertyValue('--cat-accent-rgb').trim() || '0,229,255';

    var nodes = data.nodes || [];
    var edges = data.edges || [];
    if (nodes.length === 0) {
      canvas.parentElement.querySelector("p") && (canvas.style.display = "none");
      return;
    }

    var width = canvas.parentElement.offsetWidth || 600;
    var height = 320;
    canvas.width = width;
    canvas.height = height;
    canvas.style.display = "block";

    // Hide loading text
    var loadingP = canvas.parentElement.querySelector("p");
    if (loadingP) loadingP.style.display = "none";

    var ctx = canvas.getContext("2d");

    // Initialize node positions in a circle
    var cx = width / 2, cy = height / 2, radius = Math.min(width, height) * 0.32;
    nodes.forEach(function (n, i) {
      var angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
      n.x = cx + radius * Math.cos(angle);
      n.y = cy + radius * Math.sin(angle);
      n.vx = 0;
      n.vy = 0;
      n.radius = Math.max(8, Math.min(22, 6 + Math.sqrt(n.links_count) * 2));
    });

    // Build edge lookup for quick source/target access
    var nodeMap = {};
    nodes.forEach(function (n) { nodeMap[n.id] = n; });

    var maxShared = 1;
    edges.forEach(function (e) {
      if (e.shared > maxShared) maxShared = e.shared;
    });

    // Simple force simulation (80 iterations, no animation needed)
    for (var iter = 0; iter < 80; iter++) {
      // Repulsion between all nodes
      for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
          var dx = nodes[j].x - nodes[i].x;
          var dy = nodes[j].y - nodes[i].y;
          var dist = Math.sqrt(dx * dx + dy * dy) || 1;
          var force = 2000 / (dist * dist);
          var fx = (dx / dist) * force;
          var fy = (dy / dist) * force;
          nodes[i].vx -= fx;
          nodes[i].vy -= fy;
          nodes[j].vx += fx;
          nodes[j].vy += fy;
        }
      }

      // Attraction along edges
      edges.forEach(function (e) {
        var s = nodeMap[e.source], t = nodeMap[e.target];
        if (!s || !t) return;
        var dx = t.x - s.x;
        var dy = t.y - s.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var strength = 0.01 * e.shared;
        var fx = dx * strength;
        var fy = dy * strength;
        s.vx += fx;
        s.vy += fy;
        t.vx -= fx;
        t.vy -= fy;
      });

      // Center gravity
      nodes.forEach(function (n) {
        n.vx += (cx - n.x) * 0.005;
        n.vy += (cy - n.y) * 0.005;
      });

      // Apply velocity with damping
      var damping = 0.85;
      nodes.forEach(function (n) {
        n.vx *= damping;
        n.vy *= damping;
        n.x += n.vx;
        n.y += n.vy;
        // Bounds
        n.x = Math.max(n.radius + 5, Math.min(width - n.radius - 5, n.x));
        n.y = Math.max(n.radius + 5, Math.min(height - n.radius - 5, n.y));
      });
    }

    // Draw
    ctx.clearRect(0, 0, width, height);

    // Edges with neon glow
    edges.forEach(function (e) {
      var s = nodeMap[e.source], t = nodeMap[e.target];
      if (!s || !t) return;
      var lineWidth = 1 + (e.shared / maxShared) * 4;
      var alpha = 0.2 + (e.shared / maxShared) * 0.5;
      ctx.save();
      ctx.shadowColor = "rgba(0, 229, 255, " + (alpha * 0.6) + ")";
      ctx.shadowBlur = 8 + (e.shared / maxShared) * 8;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.strokeStyle = "rgba(0, 229, 255, " + alpha + ")";
      ctx.lineWidth = lineWidth;
      ctx.stroke();
      ctx.restore();

      // Edge label (shared count)
      if (e.shared >= 3) {
        var mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
        ctx.font = "bold 10px 'IBM Plex Mono', monospace";
        ctx.fillStyle = "rgba(0, 229, 255, 0.85)";
        ctx.textAlign = "center";
        ctx.fillText(String(e.shared), mx, my - 4);
      }
    });

    // Nodes with neon glow
    nodes.forEach(function (n) {
      // Outer glow halo
      ctx.save();
      ctx.shadowColor = "rgba(" + _accentRgb + ", 0.6)";
      ctx.shadowBlur = 20;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius + 4, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(" + _accentRgb + ", 0.08)";
      ctx.fill();
      ctx.restore();

      // Inner glow ring
      ctx.save();
      ctx.shadowColor = "rgba(" + _accentRgb + ", 0.8)";
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, 2 * Math.PI);
      var grad = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.radius);
      grad.addColorStop(0, "rgba(" + _accentRgb + ", 0.8)");
      grad.addColorStop(0.7, "rgba(" + _accentRgb + ", 0.5)");
      grad.addColorStop(1, "rgba(" + _accentRgb + ", 0.3)");
      ctx.fillStyle = grad;
      ctx.strokeStyle = "rgba(" + _accentRgb + ", 0.7)";
      ctx.lineWidth = 2;
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      // Label with shadow
      var shortName = n.name.length > 20 ? n.name.substring(0, 20) + "..." : n.name;
      ctx.save();
      ctx.shadowColor = "rgba(0, 0, 0, 0.8)";
      ctx.shadowBlur = 4;
      ctx.font = "11px 'Antonio', sans-serif";
      ctx.fillStyle = "#e2e8f0";
      ctx.textAlign = "center";
      ctx.fillText(shortName, n.x, n.y + n.radius + 15);
      ctx.restore();

      // Link count inside node
      ctx.font = "bold 11px 'IBM Plex Mono', monospace";
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "center";
      ctx.fillText(String(n.links_count), n.x, n.y + 4);
    });
  }

  window.loadDashboardV2Panels = function () {
    api("/api/dashboard/knowledge-gaps").then(function (data) {
      renderProjectKnowledgeMap(data);
      renderKnowledgeGaps(data);
    });
    api("/api/dashboard/agent-expertise").then(function (data) {
      renderExpertisePanel(data);
    });
    api("/api/dashboard/knowledge-graph").then(function (data) {
      renderKnowledgeGraph(data);
    });
  };

  if (typeof window._dashboardV2Loaded === "undefined") {
    window._dashboardV2Loaded = true;
    var _origSwitch = window.switchConsciousnessTab;
    if (_origSwitch) {
      window.switchConsciousnessTab = function (tab) {
        _origSwitch(tab);
        if (tab === "intelligence") {
          loadDashboardV2Panels();
        }
      };
    }
  }
})();
