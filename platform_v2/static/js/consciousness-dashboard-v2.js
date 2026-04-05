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
        container.appendChild(row);
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
  };

  if (typeof window._dashboardV2Loaded === "undefined") {
    window._dashboardV2Loaded = true;
    var _origSwitch = window.switchConsciousnessTab;
    if (_origSwitch) {
      window.switchConsciousnessTab = function (tab) {
        _origSwitch(tab);
        if (tab === "dashboard") {
          loadDashboardV2Panels();
        }
      };
    }
  }
})();
