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
    var el = document.createElement("div");
    el.className = "cs-completeness-ring";
    el.style.width = "56px";
    el.style.height = "56px";

    if (typeof ApexCharts === "undefined") {
      // Fallback: simple text
      el.textContent = pct + "%";
      el.style.cssText = "width:56px;height:56px;display:flex;align-items:center;justify-content:center;color:var(--cat-accent);font-weight:bold;";
      return el;
    }

    var accentHex = getComputedStyle(document.documentElement).getPropertyValue("--cat-accent").trim() || "#00ffff";

    // Must render after DOM insertion, so use setTimeout
    setTimeout(function () {
      if (!el.parentElement) return;
      var chart = new ApexCharts(el, {
        chart: {
          type: "radialBar",
          height: 56,
          width: 56,
          sparkline: { enabled: true },
          animations: {
            enabled: true,
            easing: "easeinout",
            speed: 1200
          }
        },
        series: [pct],
        plotOptions: {
          radialBar: {
            hollow: { size: "50%" },
            track: {
              background: "rgba(148,163,184,0.15)",
              strokeWidth: "100%"
            },
            dataLabels: {
              name: { show: false },
              value: {
                show: true,
                fontSize: "11px",
                fontFamily: "IBM Plex Mono, monospace",
                fontWeight: 700,
                color: accentHex,
                offsetY: 4,
                formatter: function (val) { return Math.round(val) + "%"; }
              }
            }
          }
        },
        fill: {
          type: "gradient",
          gradient: {
            shade: "dark",
            type: "vertical",
            gradientToColors: [accentHex],
            stops: [0, 100],
            colorStops: [
              { offset: 0, color: accentHex, opacity: 1 },
              { offset: 100, color: accentHex, opacity: 0.4 }
            ]
          }
        },
        colors: [accentHex],
        stroke: { lineCap: "round" }
      });
      chart.render();
    }, 50);

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
    wrap.style.width = "100%";
    wrap.style.minHeight = (phases.length * 28 + 40) + "px";

    if (typeof ApexCharts === "undefined") {
      // Fallback to simple bars
      phases.forEach(function (p) {
        var row = document.createElement("div");
        row.className = "cs-phase-row";
        var label = document.createElement("span");
        label.className = "cs-phase-label";
        label.textContent = "P" + p.phase_num;
        row.appendChild(label);
        var barBg = document.createElement("div");
        barBg.className = "cs-phase-bar";
        var barFill = document.createElement("div");
        barFill.className = "cs-phase-bar-fill";
        barFill.style.width = p.pct + "%";
        barBg.appendChild(barFill);
        row.appendChild(barBg);
        var pctSpan = document.createElement("span");
        pctSpan.className = "cs-phase-pct";
        pctSpan.textContent = p.pct + "%";
        row.appendChild(pctSpan);
        wrap.appendChild(row);
      });
      return wrap;
    }

    var accentHex = getComputedStyle(document.documentElement).getPropertyValue("--cat-accent").trim() || "#00ffff";

    var categories = phases.map(function (p) { return "Phase " + p.phase_num; });
    var seriesData = phases.map(function (p) { return p.pct; });

    setTimeout(function () {
      if (!wrap.parentElement) return;
      var chart = new ApexCharts(wrap, {
        chart: {
          type: "bar",
          height: phases.length * 28 + 40,
          toolbar: { show: false },
          background: "transparent",
          animations: {
            enabled: true,
            easing: "easeinout",
            speed: 800,
            animateGradually: { enabled: true, delay: 150 }
          }
        },
        series: [{ name: "Complete", data: seriesData }],
        plotOptions: {
          bar: {
            horizontal: true,
            barHeight: "60%",
            borderRadius: 3,
            distributed: false
          }
        },
        xaxis: {
          categories: categories,
          max: 100,
          labels: {
            style: { colors: "#64748b", fontSize: "10px", fontFamily: "IBM Plex Mono" },
            formatter: function (val) { return val + "%"; }
          },
          axisBorder: { show: false },
          axisTicks: { show: false }
        },
        yaxis: {
          labels: {
            style: { colors: "#94a3b8", fontSize: "10px", fontFamily: "Antonio" }
          }
        },
        grid: {
          borderColor: "rgba(148,163,184,0.08)",
          xaxis: { lines: { show: true } },
          yaxis: { lines: { show: false } }
        },
        colors: [accentHex],
        fill: {
          type: "gradient",
          gradient: {
            shade: "dark",
            type: "horizontal",
            gradientToColors: [accentHex + "66"],
            stops: [0, 100]
          }
        },
        dataLabels: {
          enabled: true,
          formatter: function (val) { return val + "%"; },
          style: {
            fontSize: "10px",
            fontFamily: "IBM Plex Mono",
            colors: ["#e2e8f0"]
          },
          offsetX: 6
        },
        tooltip: { enabled: false },
        theme: { mode: "dark" }
      });
      chart.render();
    }, 80);

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

        // Quality score indicator with radar chart
        if (typeof proj.quality_score === "number") {
          var qWrap = document.createElement("div");
          qWrap.className = "cs-quality-wrap";
          qWrap.style.cssText = "display:inline-flex;align-items:center;gap:4px;position:relative;";

          var qBadge = document.createElement("span");
          qBadge.className = "cs-quality-badge";
          var qVal = proj.quality_score;
          qBadge.classList.add(qVal >= 70 ? "high" : qVal >= 40 ? "mid" : "low");
          qBadge.textContent = "Q" + qVal;
          qWrap.appendChild(qBadge);

          // Mini radar chart on hover
          if (typeof ApexCharts !== "undefined" && proj.quality_breakdown) {
            var radarEl = document.createElement("div");
            radarEl.className = "cs-quality-radar";
            radarEl.style.cssText = "display:none;position:absolute;left:100%;top:50%;transform:translateY(-50%);z-index:100;width:160px;height:140px;background:rgba(10,10,26,0.95);border:1px solid var(--cat-accent);border-radius:6px;padding:4px;";

            qWrap.addEventListener("mouseenter", function () {
              radarEl.style.display = "block";
              if (!radarEl._rendered) {
                var accentHex = getComputedStyle(document.documentElement).getPropertyValue("--cat-accent").trim() || "#00ffff";
                var bd = proj.quality_breakdown;
                var chart = new ApexCharts(radarEl, {
                  chart: {
                    type: "radar",
                    height: 130,
                    width: 152,
                    toolbar: { show: false },
                    background: "transparent",
                    animations: { enabled: true, speed: 400 }
                  },
                  series: [{
                    name: "Quality",
                    data: [
                      Math.round((bd.content || 0) / 40 * 100),
                      Math.round((bd.coverage || 0) / 30 * 100),
                      Math.round((bd.freshness || 0) / 30 * 100)
                    ]
                  }],
                  xaxis: {
                    categories: ["Content", "Coverage", "Fresh"],
                    labels: {
                      style: { colors: ["#94a3b8","#94a3b8","#94a3b8"], fontSize: "9px", fontFamily: "Antonio" }
                    }
                  },
                  yaxis: { show: false, max: 100 },
                  colors: [accentHex],
                  fill: { opacity: 0.25 },
                  stroke: { width: 2 },
                  markers: { size: 3, colors: [accentHex], strokeWidth: 0 },
                  plotOptions: { radar: { polygons: { strokeColors: "rgba(148,163,184,0.12)", connectorColors: "rgba(148,163,184,0.12)" } } },
                  theme: { mode: "dark" },
                  grid: { show: false }
                });
                chart.render();
                radarEl._rendered = true;
              }
            });
            qWrap.addEventListener("mouseleave", function () {
              radarEl.style.display = "none";
            });
            qWrap.appendChild(radarEl);
          }

          row.appendChild(qWrap);
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
    var container = document.getElementById("cs-knowledge-graph-canvas");
    if (!container) return;

    var nodes = data.nodes || [];
    var edges = data.edges || [];
    if (nodes.length === 0) return;

    // Hide loading text
    var loadingP = container.parentElement.querySelector("p");
    if (loadingP) loadingP.style.display = "none";

    // Replace canvas with a div for 3D graph
    var graphEl = document.getElementById("cs-knowledge-graph-3d");
    if (!graphEl) {
      graphEl = document.createElement("div");
      graphEl.id = "cs-knowledge-graph-3d";
      graphEl.style.cssText = "width:100%;height:360px;border-radius:6px;overflow:hidden;";
      container.parentElement.insertBefore(graphEl, container);
      container.style.display = "none";
    }

    // Check if ForceGraph3D is available (CDN loaded)
    if (typeof ForceGraph3D === "undefined") {
      // Fallback: show message
      graphEl.style.cssText += "display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,0.6);";
      graphEl.textContent = "3D graph library loading...";
      return;
    }

    // Get accent color from CSS
    var accentRgb = getComputedStyle(document.documentElement).getPropertyValue("--cat-accent-rgb").trim() || "0,255,255";
    var accentHex = getComputedStyle(document.documentElement).getPropertyValue("--cat-accent").trim() || "#00ffff";

    // Build graph data
    var graphData = {
      nodes: nodes.map(function (n) {
        return {
          id: n.id,
          name: n.name.length > 25 ? n.name.substring(0, 25) + "..." : n.name,
          fullName: n.name,
          val: Math.max(4, Math.sqrt(n.links_count) * 3),
          links_count: n.links_count
        };
      }),
      links: edges.map(function (e) {
        return {
          source: e.source,
          target: e.target,
          shared: e.shared
        };
      })
    };

    var maxShared = 1;
    edges.forEach(function (e) { if (e.shared > maxShared) maxShared = e.shared; });

    // Clear previous graph
    graphEl.textContent = "";

    var Graph = ForceGraph3D()(graphEl)
      .graphData(graphData)
      .width(graphEl.offsetWidth)
      .height(360)
      .backgroundColor("#0a0a1a")
      .showNavInfo(false)
      // Node styling
      .nodeLabel(function (node) {
        return "<div style='background:rgba(10,10,26,0.9);padding:6px 10px;border:1px solid " + accentHex + ";border-radius:4px;font-family:Antonio,sans-serif;color:#e2e8f0;font-size:12px;'>"
          + "<b>" + node.fullName + "</b><br>"
          + "<span style='color:" + accentHex + ";'>" + node.links_count + " knowledge links</span>"
          + "</div>";
      })
      .nodeColor(function () { return accentHex; })
      .nodeOpacity(0.9)
      .nodeResolution(16)
      // Link styling
      .linkWidth(function (link) { return 0.5 + (link.shared / maxShared) * 3; })
      .linkColor(function (link) {
        var alpha = 0.15 + (link.shared / maxShared) * 0.5;
        return "rgba(0, 229, 255, " + alpha + ")";
      })
      .linkOpacity(0.8)
      // Camera
      .cameraPosition({ z: 300 });

    // Slow auto-rotation
    var angle = 0;
    var rotationInterval = setInterval(function () {
      if (!document.getElementById("cs-knowledge-graph-3d")) {
        clearInterval(rotationInterval);
        return;
      }
      angle += 0.002;
      var dist = 300;
      Graph.cameraPosition({
        x: dist * Math.sin(angle),
        z: dist * Math.cos(angle)
      });
    }, 30);

    // Handle resize
    var resizeObserver = new ResizeObserver(function () {
      if (graphEl.offsetWidth > 0) {
        Graph.width(graphEl.offsetWidth);
      }
    });
    resizeObserver.observe(graphEl);
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
        if (tab === "devhq") {
          loadDashboardV2Panels();
        }
      };
    }
  }
})();
