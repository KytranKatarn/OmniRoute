/* ============================================================================
   A.R.C.H.I.E. DEV HQ — JavaScript Controller (v2)
   Handles 6 tabs: Overview, Projects (with detail sub-view), Ideas,
   Knowledge, Decisions, System (merged Schema + API + Integrations)

   Security note: All user-content rendering uses escHtml() (DOM-based
   text escaping) or renderMd() (DOMPurify.sanitize + marked.parse).
   No raw user input is ever assigned to innerHTML without sanitization.
   ============================================================================ */
(function () {
  "use strict";

  /* --- State --- */
  var _cache = {};
  var _taskState = { page: 0, limit: 30, total: 0 };
  var _kbState = { page: 0, limit: 20, total: 0 };
  var _ideasState = { page: 0, limit: 20, total: 0 };
  var _decisionsState = { page: 0, limit: 20, total: 0 };
  var _schemaData = null;
  var _apiData = null;
  var _currentProject = null;
  var _ideasCache = [];
  var _roadmapActive = false;

  /* ========================================================================
     UTILITIES
     ======================================================================== */

  function escHtml(str) {
    if (str == null) return "";
    var div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  function formatAge(dateStr) {
    return ArchieTime.age(dateStr);
  }

  function formatDate(dateStr) {
    return ArchieTime.date(dateStr);
  }

  function api(path, opts) {
    opts = opts || {};
    var url = "/tools/consciousness" + path.replace(/^\/api\//, "/api/devhq/");
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

  function refreshIcons() {
    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  }

  function closeModal(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = "none";
  }

  function renderMd(str) {
    if (!str) return "";
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      return DOMPurify.sanitize(marked.parse(str));
    }
    return escHtml(str);
  }

  /* --- Safe innerHTML helper: wraps all innerHTML assignments --- */
  function setHtml(el, html) {
    if (typeof el === "string") el = document.getElementById(el);
    if (el) el.innerHTML = html;
  }

  /* --- Debounce helper --- */
  var _debounceTimers = {};
  function debounceReload(tabName, fn) {
    clearTimeout(_debounceTimers[tabName]);
    _debounceTimers[tabName] = setTimeout(function () {
      _cache[tabName] = false;
      fn();
    }, 300);
  }

  /* ========================================================================
     TAB SYSTEM (6 tabs)
     ======================================================================== */

  function switchDevHQTab(tab) {
    var inConsciousness = !!document.getElementById("panel-devhq");
    if (inConsciousness) {
      /* Inside Consciousness — use subtab pattern */
      document.querySelectorAll("#devhqSubtabs .cs-subtab").forEach(function (btn) {
        btn.classList.toggle("active", btn.dataset.subtab === "dh-" + tab);
      });
      document.querySelectorAll("#panel-devhq .cs-subpanel").forEach(function (panel) {
        panel.style.display = panel.id === "dh-" + tab ? "block" : "none";
      });
    } else {
      /* Standalone /dev-hq page */
      document.querySelectorAll(".devhq-tab").forEach(function (btn) {
        btn.classList.toggle("active", btn.dataset.tab === tab);
      });
      document.querySelectorAll(".devhq-panel").forEach(function (panel) {
        panel.classList.toggle("active", panel.id === "panel-" + tab);
      });
      history.replaceState(null, "", "#" + tab);
    }
    loadTabData(tab);
  }

  function loadTabData(tab) {
    // Always populate header stats
    if (!_cache._headerStats) {
      _cache._headerStats = true;
      api("/api/overview").then(function (data) {
        if (!data.success) return;
        var el;
        el = document.getElementById("hqProjectCount");
        if (el) el.textContent = data.project_stats.active || 0;
        el = document.getElementById("hqTaskCount");
        if (el) el.textContent = data.task_stats.open_tasks || 0;
      }).catch(function () {});
    }
    if (_cache[tab]) return;
    _cache[tab] = true;
    switch (tab) {
      case "overview":   loadOverview(); break;
      case "projects":   loadProjects(); break;
      case "ideas":      loadIdeas(); break;
      case "knowledge":  loadKnowledge(); break;
      case "decisions":  loadDecisions(); break;
      case "system":     loadSystem(); break;
    }
  }

  /* ========================================================================
     OVERVIEW TAB
     ======================================================================== */

  function loadOverview() {
    api("/api/overview").then(function (data) {
      if (!data.success) return;

      var activeCount = (data.project_stats.active || 0) + (data.project_stats.planning || 0);
      var openTasks = data.task_stats.open_tasks || 0;
      var _s = function(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; };
      _s("statActiveProjects", activeCount);
      _s("statOpenTasks", openTasks);
      _s("statKnowledge", data.knowledge_count || 0);
      _s("statEmbedding", (data.embedding_coverage || 0) + "%");
      _s("hqProjectCount", activeCount);
      _s("hqTaskCount", openTasks);

      // Activity feed (all content escaped via escHtml)
      var actEl = document.getElementById("overviewActivity");
      if (data.activity && data.activity.length) {
        var typeIcons = {
          project_created: "folder-plus",
          task_created: "plus-circle",
          status_change: "arrow-right-circle",
          task_completed: "check-circle",
          decision: "gavel",
        };
        setHtml(actEl, data.activity
          .map(function (a) {
            var icon = typeIcons[a.activity_type] || "activity";
            return (
              '<div class="devhq-activity-item">' +
              '<i data-lucide="' + escHtml(icon) + '" style="width:16px;height:16px;flex-shrink:0;color:var(--archie-orange);"></i>' +
              '<div style="flex:1;min-width:0;">' +
              '<div style="font-size:0.78rem;color:var(--archie-text-primary);">' + escHtml(a.description || a.activity_type) + "</div>" +
              '<div style="font-size:0.65rem;color:var(--archie-text-muted);margin-top:2px;">' + escHtml(a.project_name || "") + "</div>" +
              "</div>" +
              '<span style="font-size:0.65rem;color:var(--archie-text-muted);white-space:nowrap;">' + escHtml(formatAge(a.created_at)) + "</span>" +
              "</div>"
            );
          })
          .join(""));
      } else {
        setHtml(actEl, '<div class="devhq-empty">No recent activity</div>');
      }

      // Active projects mini-list (all content escaped via escHtml)
      var projEl = document.getElementById("overviewProjects");
      if (data.active_projects && data.active_projects.length) {
        setHtml(projEl, data.active_projects
          .slice(0, 8)
          .map(function (p) {
            var pct = p.total_tasks > 0 ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;
            return (
              '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--archie-border-default);cursor:pointer;" onclick="openProjectDetail(' + p.id + ')">' +
              '<div style="flex:1;min-width:0;">' +
              '<div style="font-size:0.78rem;color:var(--archie-text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escHtml(p.name) + "</div>" +
              '<div style="display:flex;align-items:center;gap:8px;margin-top:4px;">' +
              '<div class="devhq-progress" style="flex:1;"><div class="devhq-progress-fill" style="width:' + pct + '%;"></div></div>' +
              '<span style="font-size:0.65rem;color:var(--archie-text-muted);">' + pct + "%</span>" +
              "</div></div>" +
              '<span class="devhq-badge ' + escHtml(p.priority || "medium") + '">' + escHtml(p.priority || "medium") + "</span>" +
              "</div>"
            );
          })
          .join(""));
      } else {
        setHtml(projEl, '<div class="devhq-empty">No active projects</div>');
      }

      refreshIcons();
    }).catch(function (err) {
      console.error("loadOverview error:", err);
    });
  }

  /* ========================================================================
     PROJECTS TAB
     ======================================================================== */

  function loadProjects() {
    var status = document.getElementById("projFilterStatus").value;
    var priority = document.getElementById("projFilterPriority").value;
    var search = document.getElementById("projFilterSearch").value;
    var params = new URLSearchParams();
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    if (search) params.set("search", search);

    api("/api/projects?" + params.toString())
      .then(function (data) {
        if (!data.success || !data.projects.length) {
          setHtml("projectsGrid", '<div class="devhq-empty">No projects found</div>');
          return;
        }
        setHtml("projectsGrid", data.projects.map(createProjectCard).join(""));
        refreshIcons();
      })
      .catch(function () {
        setHtml("projectsGrid", '<div class="devhq-empty">Error loading projects</div>');
      });
  }

  function createProjectCard(p) {
    var pct = p.total_tasks > 0 ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;
    return (
      '<div class="devhq-project-card" onclick="openProjectDetail(' + p.id + ')" style="cursor:pointer;">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
      '<div style="font-size:0.85rem;font-weight:600;color:var(--archie-text-primary);">' + escHtml(p.name) + "</div>" +
      '<div style="display:flex;gap:6px;">' +
      '<span class="devhq-badge ' + escHtml(p.status || "active") + '">' + escHtml(p.status || "active") + "</span>" +
      '<span class="devhq-badge ' + escHtml(p.priority || "medium") + '">' + escHtml(p.priority || "medium") + "</span>" +
      "</div></div>" +
      (p.description
        ? '<div style="font-size:0.72rem;color:var(--archie-text-muted);margin-bottom:10px;max-height:40px;overflow:hidden;">' + escHtml(p.description.substring(0, 120)) + "</div>"
        : "") +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">' +
      '<div class="devhq-progress" style="flex:1;"><div class="devhq-progress-fill" style="width:' + pct + '%;"></div></div>' +
      '<span style="font-size:0.65rem;color:var(--archie-text-muted);">' + p.completed_tasks + "/" + p.total_tasks + " tasks</span>" +
      "</div>" +
      '<div style="display:flex;align-items:center;justify-content:space-between;">' +
      '<span style="font-size:0.65rem;color:var(--archie-text-muted);">Updated ' + escHtml(formatAge(p.updated_at)) + "</span>" +
      '<div style="display:flex;gap:6px;" onclick="event.stopPropagation();">' +
      '<button class="devhq-btn small primary" onclick="event.stopPropagation();openProjectModal(' + p.id + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
      '<button class="devhq-btn small danger" onclick="event.stopPropagation();deleteProject(' + p.id + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
      "</div></div></div>"
    );
  }

  function openProjectModal(projectId) {
    document.getElementById("projectEditId").value = "";
    document.getElementById("projectName").value = "";
    document.getElementById("projectDesc").value = "";
    document.getElementById("projectType").value = "feature";
    document.getElementById("projectPriority").value = "medium";
    document.getElementById("projectTargetDate").value = "";
    document.getElementById("projectModalTitle").textContent = "New Project";
    document.getElementById("projectSubmitBtn").textContent = "Create";

    if (projectId && typeof projectId === "number") {
      api("/api/projects").then(function (data) {
        if (!data.success) return;
        var p = data.projects.find(function (x) { return x.id === projectId; });
        if (!p) return;
        document.getElementById("projectEditId").value = p.id;
        document.getElementById("projectName").value = p.name || "";
        document.getElementById("projectDesc").value = p.description || "";
        document.getElementById("projectType").value = p.project_type || "feature";
        document.getElementById("projectPriority").value = p.priority || "medium";
        document.getElementById("projectTargetDate").value = p.target_date ? p.target_date.substring(0, 10) : "";
        document.getElementById("projectModalTitle").textContent = "Edit Project";
        document.getElementById("projectSubmitBtn").textContent = "Update";
      });
    }

    document.getElementById("projectModal").style.display = "flex";
  }

  function submitProject() {
    var editId = document.getElementById("projectEditId").value;
    var body = {
      name: document.getElementById("projectName").value.trim(),
      description: document.getElementById("projectDesc").value.trim(),
      project_type: document.getElementById("projectType").value,
      priority: document.getElementById("projectPriority").value,
      target_date: document.getElementById("projectTargetDate").value || null,
    };
    if (!body.name) { alert("Project name is required"); return; }

    var p = editId
      ? api("/api/projects/" + editId, { method: "PUT", body: body })
      : api("/api/projects", { body: body });

    p.then(function () {
      closeModal("projectModal");
      _cache.projects = false;
      _cache.overview = false;
      _cache._headerStats = false;
      loadProjects();
    }).catch(function (err) {
      alert("Error: " + err.message);
    });
  }

  function deleteProject(id) {
    if (!confirm("Delete this project and all its tasks?")) return;
    api("/api/projects/" + id, { method: "DELETE" })
      .then(function () {
        _cache.projects = false;
        _cache.overview = false;
        _cache._headerStats = false;
        loadProjects();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  /* --- Project Detail View --- */

  function openProjectDetail(projectId) {
    // Switch to projects tab if not already there
    switchDevHQTab("projects");

    api("/api/projects").then(function (data) {
      if (!data.success) return;
      var p = data.projects.find(function (x) { return x.id === projectId; });
      if (!p) return;
      _currentProject = p;

      // Hide grid, show detail
      document.getElementById("projectsView").style.display = "none";
      document.getElementById("projectDetail").style.display = "block";

      // Populate header using the dedicated elements
      var pct = p.total_tasks > 0 ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;
      document.getElementById("projDetailName").textContent = p.name;

      var statusEl = document.getElementById("projDetailStatus");
      statusEl.textContent = p.status;
      statusEl.className = "devhq-badge " + (p.status || "active");

      var prioEl = document.getElementById("projDetailPriority");
      prioEl.textContent = p.priority || "medium";
      prioEl.className = "devhq-badge " + (p.priority || "medium");

      var descEl = document.getElementById("projDetailDesc");
      descEl.textContent = p.description ? p.description.substring(0, 200) : "";

      var progEl = document.getElementById("projDetailProgress");
      progEl.style.width = pct + "%";

      // Load default sub-tab
      switchProjectSubTab("tasks");
      refreshIcons();
    });
  }

  function closeProjectDetail() {
    _currentProject = null;
    document.getElementById("projectDetail").style.display = "none";
    document.getElementById("projectsView").style.display = "block";
  }

  function switchProjectSubTab(tab) {
    document.querySelectorAll(".devhq-sub-tab").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.subtab === tab);
    });
    document.querySelectorAll(".devhq-sub-panel").forEach(function (panel) {
      panel.classList.toggle("active", panel.id === "projSub" + tab.charAt(0).toUpperCase() + tab.slice(1));
    });
    if (!_currentProject) return;
    var pid = _currentProject.id;
    switch (tab) {
      case "tasks":     loadProjectTasks(pid); break;
      case "decisions": loadProjectDecisions(pid); break;
      case "docs":      loadProjectDocs(pid); break;
      case "activity":  loadProjectActivity(pid); break;
    }
  }

  /* --- Project Sub-tab Loaders (all content sanitized via escHtml) --- */

  function loadProjectTasks(projectId) {
    setHtml("projSubTasks", '<div class="devhq-loading">Loading tasks</div>');

    api("/api/projects/" + projectId + "/tasks").then(function (data) {
      if (!data.success) {
        setHtml("projSubTasks", '<div class="devhq-empty">Error loading tasks</div>');
        return;
      }
      var tasks = data.tasks;
      if (!tasks.length) {
        setHtml("projSubTasks",
          '<div style="margin-bottom:12px;"><button class="devhq-btn primary small" onclick="openTaskModal(null,' + projectId + ')">+ New Task</button></div>' +
          '<div class="devhq-empty">No tasks yet</div>');
        refreshIcons();
        return;
      }

      var isMobile = window.innerWidth <= 768;
      var html = '<div style="margin-bottom:12px;"><button class="devhq-btn primary small" onclick="openTaskModal(null,' + projectId + ')">+ New Task</button></div>';

      if (!isMobile) {
        html += '<div class="devhq-task-table-header"><div>Status</div><div>Title</div><div>Type</div><div>Priority</div><div>Due Date</div><div>Actions</div></div>';
        html += tasks.map(function (t) {
          return (
            '<div class="devhq-task-table-row">' +
            '<div><span class="devhq-badge ' + escHtml(t.status) + '" style="cursor:pointer;" onclick="cycleTaskStatus(' + t.id + ",'" + escHtml(t.status) + "'," + projectId + ')">' + escHtml(t.status) + "</span></div>" +
            '<div style="color:var(--archie-text-primary);">' + escHtml(t.title) + "</div>" +
            '<div style="font-size:0.7rem;color:var(--archie-text-muted);">' + escHtml(t.task_type || "\u2014") + "</div>" +
            '<div><span class="devhq-badge ' + escHtml(t.priority) + '">' + escHtml(t.priority) + "</span></div>" +
            '<div style="font-size:0.7rem;color:var(--archie-text-muted);">' + escHtml(formatDate(t.due_date)) + "</div>" +
            '<div style="display:flex;gap:4px;">' +
            '<button class="devhq-btn small primary" onclick="openTaskModal(' + t.id + ',' + projectId + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
            '<button class="devhq-btn small danger" onclick="deleteTask(' + t.id + ',' + projectId + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
            "</div></div>"
          );
        }).join("");
      } else {
        html += tasks.map(function (t) {
          return (
            '<div class="devhq-task-card">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">' +
            '<span class="devhq-badge ' + escHtml(t.status) + '" style="cursor:pointer;" onclick="cycleTaskStatus(' + t.id + ",'" + escHtml(t.status) + "'," + projectId + ')">' + escHtml(t.status) + "</span>" +
            '<span class="devhq-badge ' + escHtml(t.priority) + '">' + escHtml(t.priority) + "</span>" +
            "</div>" +
            '<div style="font-size:0.78rem;color:var(--archie-text-primary);margin-bottom:4px;">' + escHtml(t.title) + "</div>" +
            '<div style="display:flex;align-items:center;justify-content:space-between;">' +
            '<span style="font-size:0.65rem;color:var(--archie-text-muted);">Due ' + escHtml(formatDate(t.due_date)) + "</span>" +
            '<div style="display:flex;gap:4px;">' +
            '<button class="devhq-btn small primary" onclick="openTaskModal(' + t.id + ',' + projectId + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
            '<button class="devhq-btn small danger" onclick="deleteTask(' + t.id + ',' + projectId + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
            "</div></div></div>"
          );
        }).join("");
      }

      setHtml("projSubTasks", html);
      refreshIcons();
    }).catch(function () {
      setHtml("projSubTasks", '<div class="devhq-empty">Error loading tasks</div>');
    });
  }

  function loadProjectDecisions(projectId) {
    setHtml("projSubDecisions", '<div class="devhq-loading">Loading decisions</div>');

    api("/api/decisions?project_id=" + projectId).then(function (data) {
      if (!data.success) {
        setHtml("projSubDecisions", '<div class="devhq-empty">Error loading decisions</div>');
        return;
      }
      if (!data.decisions.length) {
        setHtml("projSubDecisions", '<div class="devhq-empty">No decisions recorded for this project</div>');
        return;
      }
      setHtml("projSubDecisions", data.decisions.map(function (d) {
        return (
          '<div class="devhq-kb-item" onclick="toggleDecisionDetail(this,' + d.id + ')">' +
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">' +
          '<div style="font-size:0.8rem;font-weight:500;color:var(--archie-text-primary);">' +
          (d.decision_number ? '<span style="color:var(--archie-orange);margin-right:6px;">ADR-' + escHtml(String(d.decision_number).padStart(3, "0")) + '</span>' : '') +
          escHtml(d.title) + '</div>' +
          '<span class="devhq-badge ' + escHtml(d.status) + '">' + escHtml(d.status) + "</span>" +
          "</div>" +
          '<div style="font-size:0.65rem;color:var(--archie-text-muted);">' + escHtml(formatDate(d.decided_at || d.created_at)) + "</div>" +
          '<div class="kb-detail-expand" style="display:none;margin-top:10px;"></div>' +
          "</div>"
        );
      }).join(""));
      refreshIcons();
    }).catch(function () {
      setHtml("projSubDecisions", '<div class="devhq-empty">Error loading decisions</div>');
    });
  }

  function loadProjectDocs(projectId) {
    setHtml("projSubDocs", '<div class="devhq-loading">Loading documents</div>');

    api("/api/projects/" + projectId + "/docs").then(function (data) {
      if (!data.success) {
        setHtml("projSubDocs", '<div class="devhq-empty">Error loading documents</div>');
        return;
      }
      var docs = data.docs;
      var html = '<div style="margin-bottom:12px;"><button class="devhq-btn primary small" onclick="openProjectDocModal()">+ New Document</button></div>';

      if (!docs.length) {
        html += '<div class="devhq-empty">No documents yet</div>';
        setHtml("projSubDocs", html);
        refreshIcons();
        return;
      }

      html += '<div class="devhq-kb-list">' + docs.map(function (d) {
        var tagsHtml = "";
        if (d.tags && Array.isArray(d.tags)) {
          tagsHtml = d.tags.slice(0, 3).map(function (t) {
            return '<span class="devhq-tag">' + escHtml(t) + "</span>";
          }).join(" ");
        }
        return (
          '<div class="devhq-kb-item" onclick="viewProjectDoc(' + projectId + ',' + d.id + ')">' +
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">' +
          '<div style="font-size:0.8rem;font-weight:500;color:var(--archie-text-primary);">' + escHtml(d.title || "Untitled") + "</div>" +
          '<div style="display:flex;gap:6px;align-items:center;">' +
          '<span class="devhq-badge">' + escHtml(d.doc_type || "note") + "</span>" +
          '<span style="font-size:0.6rem;color:var(--archie-text-muted);">v' + (d.version || 1) + "</span>" +
          "</div></div>" +
          (d.snippet ? '<div style="font-size:0.72rem;color:var(--archie-text-muted);max-height:40px;overflow:hidden;margin-bottom:6px;">' + escHtml(d.snippet) + "</div>" : "") +
          (tagsHtml ? '<div style="margin-bottom:4px;">' + tagsHtml + "</div>" : "") +
          '<div style="display:flex;align-items:center;justify-content:space-between;">' +
          '<span style="font-size:0.65rem;color:var(--archie-text-muted);">Updated ' + escHtml(formatAge(d.updated_at)) + "</span>" +
          '<div style="display:flex;gap:4px;" onclick="event.stopPropagation();">' +
          '<button class="devhq-btn small primary" onclick="event.stopPropagation();openProjectDocModal(' + d.id + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
          '<button class="devhq-btn small danger" onclick="event.stopPropagation();deleteProjectDoc(' + d.id + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
          "</div></div></div>"
        );
      }).join("") + "</div>";

      setHtml("projSubDocs", html);
      refreshIcons();
    }).catch(function () {
      setHtml("projSubDocs", '<div class="devhq-empty">Error loading documents</div>');
    });
  }

  function viewProjectDoc(projectId, docId) {
    api("/api/projects/" + projectId + "/docs/" + docId).then(function (data) {
      if (!data.success || !data.doc) return;
      var d = data.doc;
      // Content rendered via renderMd (DOMPurify sanitized)
      setHtml("projSubDocs",
        '<div style="margin-bottom:12px;">' +
        '<button class="devhq-btn small secondary" onclick="loadProjectDocs(' + projectId + ')"><i data-lucide="arrow-left" style="width:12px;height:12px;vertical-align:middle;margin-right:4px;"></i>Back</button>' +
        '<button class="devhq-btn small primary" style="margin-left:8px;" onclick="openProjectDocModal(' + d.id + ')"><i data-lucide="pencil" style="width:12px;height:12px;vertical-align:middle;margin-right:4px;"></i>Edit</button>' +
        '</div>' +
        '<div class="devhq-card"><div class="devhq-card-header">' +
        '<span>' + escHtml(d.title || "Untitled") + '</span>' +
        '<span style="font-size:0.6rem;color:var(--archie-text-muted);">v' + (d.version || 1) + ' | ' + escHtml(d.doc_type || "note") + '</span>' +
        '</div><div class="devhq-card-body"><div class="devhq-md-content">' +
        renderMd(d.content || "") +
        '</div></div></div>');
      refreshIcons();
    });
  }

  function loadProjectActivity(projectId) {
    setHtml("projSubActivity", '<div class="devhq-loading">Loading activity</div>');

    api("/api/activity?project_id=" + projectId + "&limit=50").then(function (data) {
      if (!data.success) {
        setHtml("projSubActivity", '<div class="devhq-empty">Error loading activity</div>');
        return;
      }
      var items = data.activity;
      if (!items.length) {
        setHtml("projSubActivity", '<div class="devhq-empty">No activity recorded for this project</div>');
        return;
      }
      var typeIcons = {
        project_created: "folder-plus",
        task_created: "plus-circle",
        status_change: "arrow-right-circle",
        task_completed: "check-circle",
        decision: "scale",
        doc_created: "file-text",
        doc_updated: "file-edit",
        idea_promoted: "rocket",
        idea_created: "lightbulb",
        knowledge_added: "book-open",
      };
      setHtml("projSubActivity", '<div class="devhq-activity-list">' + items.map(function (a) {
        var icon = typeIcons[a.activity_type] || "activity";
        return (
          '<div class="devhq-activity-item">' +
          '<i data-lucide="' + escHtml(icon) + '" style="width:16px;height:16px;flex-shrink:0;color:var(--archie-orange);"></i>' +
          '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:0.78rem;color:var(--archie-text-primary);">' + escHtml(a.description || a.activity_type) + "</div>" +
          "</div>" +
          '<span style="font-size:0.65rem;color:var(--archie-text-muted);white-space:nowrap;">' + escHtml(formatAge(a.created_at)) + "</span>" +
          "</div>"
        );
      }).join("") + "</div>");
      refreshIcons();
    }).catch(function () {
      setHtml("projSubActivity", '<div class="devhq-empty">Error loading activity</div>');
    });
  }

  /* --- Task Modal (shared: cross-project and project-specific) --- */

  function openTaskModal(taskId, projectId) {
    document.getElementById("taskEditId").value = "";
    document.getElementById("taskProjectId").value = projectId || "";
    document.getElementById("taskTitle").value = "";
    document.getElementById("taskDesc").value = "";
    document.getElementById("taskType").value = "implementation";
    document.getElementById("taskPriority").value = "medium";
    document.getElementById("taskDueDate").value = "";
    document.getElementById("taskModalTitle").textContent = "New Task";
    document.getElementById("taskSubmitBtn").textContent = "Create";

    // Populate project dropdown
    var sel = document.getElementById("taskProject");
    if (sel.options.length <= 1) {
      api("/api/tasks?limit=1").then(function (data) {
        if (data.projects) {
          data.projects.forEach(function (p) {
            if (!Array.from(sel.options).some(function (o) { return o.value === String(p.id); })) {
              var opt = document.createElement("option");
              opt.value = p.id;
              opt.textContent = p.name;
              sel.appendChild(opt);
            }
          });
        }
        if (projectId) sel.value = String(projectId);
      });
    } else if (projectId) {
      sel.value = String(projectId);
    }

    if (taskId && typeof taskId === "number") {
      var fetchUrl = projectId
        ? "/api/projects/" + projectId + "/tasks"
        : "/api/tasks?limit=200";
      api(fetchUrl).then(function (data) {
        if (!data.success) return;
        var t = data.tasks.find(function (x) { return x.id === taskId; });
        if (!t) return;
        document.getElementById("taskEditId").value = t.id;
        document.getElementById("taskProjectId").value = t.project_id || "";
        document.getElementById("taskTitle").value = t.title || "";
        document.getElementById("taskDesc").value = t.description || "";
        document.getElementById("taskProject").value = t.project_id || "";
        document.getElementById("taskType").value = t.task_type || "implementation";
        document.getElementById("taskPriority").value = t.priority || "medium";
        document.getElementById("taskDueDate").value = t.due_date ? t.due_date.substring(0, 10) : "";
        document.getElementById("taskModalTitle").textContent = "Edit Task";
        document.getElementById("taskSubmitBtn").textContent = "Update";
      });
    }

    document.getElementById("taskModal").style.display = "flex";
  }

  function submitTask() {
    var editId = document.getElementById("taskEditId").value;
    var projectId = document.getElementById("taskProject").value || document.getElementById("taskProjectId").value;
    var body = {
      title: document.getElementById("taskTitle").value.trim(),
      description: document.getElementById("taskDesc").value.trim(),
      task_type: document.getElementById("taskType").value,
      priority: document.getElementById("taskPriority").value,
      due_date: document.getElementById("taskDueDate").value || null,
    };
    if (!body.title) { alert("Task title is required"); return; }

    var p;
    if (editId) {
      p = api("/api/tasks/" + editId, { method: "PUT", body: body });
    } else {
      if (!projectId) { alert("Select a project"); return; }
      p = api("/api/projects/" + projectId + "/tasks", { body: body });
    }

    p.then(function () {
      closeModal("taskModal");
      _cache.overview = false;
      _cache._headerStats = false;
      if (_currentProject) {
        loadProjectTasks(_currentProject.id);
      }
    }).catch(function (err) {
      alert("Error: " + err.message);
    });
  }

  function deleteTask(id, projectId) {
    if (!confirm("Delete this task?")) return;
    api("/api/tasks/" + id, { method: "DELETE" })
      .then(function () {
        _cache.overview = false;
        _cache._headerStats = false;
        if (_currentProject) {
          loadProjectTasks(_currentProject.id);
        }
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function cycleTaskStatus(id, currentStatus, projectId) {
    var cycle = { pending: "in_progress", in_progress: "completed", completed: "pending" };
    var next = cycle[currentStatus] || "pending";
    api("/api/tasks/" + id, { method: "PUT", body: { status: next } })
      .then(function () {
        _cache.overview = false;
        _cache._headerStats = false;
        if (_currentProject) {
          loadProjectTasks(_currentProject.id);
        }
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function taskPage(dir) {
    _taskState.page += dir;
    if (_taskState.page < 0) _taskState.page = 0;
    if (_currentProject) loadProjectTasks(_currentProject.id);
  }

  /* ========================================================================
     IDEAS TAB
     ======================================================================== */

  function loadIdeas() {
    var category = document.getElementById("ideaFilterCategory").value;
    var status = document.getElementById("ideaFilterStatus").value;
    var search = document.getElementById("ideaFilterSearch").value;
    var params = new URLSearchParams();
    if (category) params.set("category", category);
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    params.set("limit", _ideasState.limit);
    params.set("offset", _ideasState.page * _ideasState.limit);

    api("/api/ideas?" + params.toString()).then(function (data) {
      if (!data.success) {
        setHtml("ideasGrid", '<div class="devhq-empty">Error loading ideas</div>');
        return;
      }
      _ideasState.total = data.total;
      _ideasCache = data.ideas;
      renderIdeas(data.ideas, data.total);
    }).catch(function () {
      setHtml("ideasGrid", '<div class="devhq-empty">Error loading ideas</div>');
    });
  }

  function renderIdeas(ideas, total) {
    if (!ideas.length) {
      setHtml("ideasGrid", '<div class="devhq-empty">No ideas found</div>');
      document.getElementById("ideasPagination").style.display = "none";
      return;
    }

    setHtml("ideasGrid", ideas.map(function (idea) {
      var tagsHtml = "";
      if (idea.tags && Array.isArray(idea.tags)) {
        tagsHtml = idea.tags.slice(0, 4).map(function (t) {
          return '<span class="devhq-tag">' + escHtml(t) + "</span>";
        }).join(" ");
      }
      var isPromoted = idea.status === "promoted";
      return (
        '<div class="devhq-idea-card">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
        '<div style="font-size:0.85rem;font-weight:600;color:var(--archie-text-primary);">' + escHtml(idea.title) + "</div>" +
        '<div style="display:flex;gap:6px;">' +
        '<span class="devhq-badge ' + escHtml(idea.status || "new") + '">' + escHtml(idea.status || "new") + "</span>" +
        '<span class="devhq-badge ' + escHtml(idea.category || "feature") + '">' + escHtml(idea.category || "feature") + "</span>" +
        "</div></div>" +
        (idea.description
          ? '<div style="font-size:0.72rem;color:var(--archie-text-muted);margin-bottom:8px;max-height:50px;overflow:hidden;">' + escHtml(idea.description.substring(0, 200)) + "</div>"
          : "") +
        (tagsHtml ? '<div style="margin-bottom:8px;">' + tagsHtml + "</div>" : "") +
        '<div style="display:flex;align-items:center;justify-content:space-between;">' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
        '<span style="font-size:0.65rem;color:var(--archie-text-muted);">Priority: ' + (idea.priority || 5) + '/10</span>' +
        '<span style="font-size:0.65rem;color:var(--archie-text-muted);">' + escHtml(formatAge(idea.created_at)) + "</span>" +
        "</div>" +
        '<div style="display:flex;gap:6px;">' +
        (isPromoted
          ? '<button class="devhq-btn small secondary" onclick="openProjectDetail(' + (idea.promoted_to_project_id || 0) + ')">View Project</button>'
          : '<button class="devhq-btn small primary" onclick="promoteIdea(' + idea.id + ')" title="Promote to Project"><i data-lucide="rocket" style="width:12px;height:12px;"></i></button>') +
        '<button class="devhq-btn small primary" onclick="openIdeaModal(' + idea.id + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
        '<button class="devhq-btn small danger" onclick="deleteIdea(' + idea.id + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
        "</div></div></div>"
      );
    }).join(""));

    var totalPages = Math.ceil(total / _ideasState.limit);
    var pag = document.getElementById("ideasPagination");
    if (totalPages > 1) {
      pag.style.display = "flex";
      document.getElementById("ideasPageInfo").textContent = "Page " + (_ideasState.page + 1) + " of " + totalPages;
      document.getElementById("ideasPrev").disabled = _ideasState.page === 0;
      document.getElementById("ideasNext").disabled = _ideasState.page >= totalPages - 1;
    } else {
      pag.style.display = "none";
    }
    refreshIcons();
  }

  function openIdeaModal(ideaId) {
    document.getElementById("ideaEditId").value = "";
    document.getElementById("ideaTitle").value = "";
    document.getElementById("ideaDesc").value = "";
    document.getElementById("ideaCategory").value = "feature";
    document.getElementById("ideaPriority").value = "5";
    document.getElementById("ideaTags").value = "";
    document.getElementById("ideaModalTitle").textContent = "New Idea";
    document.getElementById("ideaSubmitBtn").textContent = "Create";

    if (ideaId && typeof ideaId === "number") {
      var idea = _ideasCache.find(function (x) { return x.id === ideaId; });
      if (idea) {
        document.getElementById("ideaEditId").value = idea.id;
        document.getElementById("ideaTitle").value = idea.title || "";
        document.getElementById("ideaDesc").value = idea.description || "";
        document.getElementById("ideaCategory").value = idea.category || "feature";
        document.getElementById("ideaPriority").value = String(idea.priority || 5);
        document.getElementById("ideaTags").value = (idea.tags && Array.isArray(idea.tags)) ? idea.tags.join(", ") : "";
        document.getElementById("ideaModalTitle").textContent = "Edit Idea";
        document.getElementById("ideaSubmitBtn").textContent = "Update";
      }
    }

    document.getElementById("ideaModal").style.display = "flex";
  }

  function submitIdea() {
    var editId = document.getElementById("ideaEditId").value;
    var tagsRaw = document.getElementById("ideaTags").value.trim();
    var tags = tagsRaw ? tagsRaw.split(",").map(function (t) { return t.trim(); }).filter(Boolean) : [];
    var body = {
      title: document.getElementById("ideaTitle").value.trim(),
      description: document.getElementById("ideaDesc").value.trim(),
      category: document.getElementById("ideaCategory").value,
      priority: parseInt(document.getElementById("ideaPriority").value, 10),
      tags: tags,
    };
    if (!body.title) { alert("Idea title is required"); return; }

    var p = editId
      ? api("/api/ideas/" + editId, { method: "PUT", body: body })
      : api("/api/ideas", { body: body });

    p.then(function () {
      closeModal("ideaModal");
      _cache.ideas = false;
      _cache.overview = false;
      loadIdeas();
    }).catch(function (err) {
      alert("Error: " + err.message);
    });
  }

  function deleteIdea(id) {
    if (!confirm("Delete this idea?")) return;
    api("/api/ideas/" + id, { method: "DELETE" })
      .then(function () { _cache.ideas = false; _cache.overview = false; loadIdeas(); })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function promoteIdea(id) {
    if (!confirm("Promote this idea to a new project?")) return;
    api("/api/ideas/" + id + "/promote", { method: "POST" })
      .then(function (data) {
        if (!data.success) { alert("Error: " + (data.error || "Failed")); return; }
        _cache.ideas = false;
        _cache.projects = false;
        _cache.overview = false;
        _cache._headerStats = false;
        loadIdeas();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function ideaPage(dir) {
    _ideasState.page += dir;
    if (_ideasState.page < 0) _ideasState.page = 0;
    _cache.ideas = false;
    loadIdeas();
  }

  /* ========================================================================
     KNOWLEDGE TAB (Enhanced)
     ======================================================================== */

  function loadKnowledge() {
    var search = document.getElementById("kbSearch").value;
    var kbType = document.getElementById("kbTypeFilter").value;
    var category = document.getElementById("kbCategory").value;
    var params = new URLSearchParams();
    if (search) params.set("search", search);
    if (kbType) params.set("knowledge_type", kbType);
    if (category) params.set("category", category);
    params.set("limit", _kbState.limit);
    params.set("offset", _kbState.page * _kbState.limit);

    api("/api/knowledge?" + params.toString())
      .then(function (data) {
        if (!data.success) {
          setHtml("kbResults", '<div class="devhq-empty">Error loading knowledge</div>');
          return;
        }
        _kbState.total = data.total;
        if (data.categories) {
          var sel = document.getElementById("kbCategory");
          if (sel.options.length <= 1) {
            data.categories.forEach(function (cat) {
              var opt = document.createElement("option");
              opt.value = cat;
              opt.textContent = cat;
              sel.appendChild(opt);
            });
          }
        }
        renderKnowledge(data.entries, data.total);
      })
      .catch(function () {
        setHtml("kbResults", '<div class="devhq-empty">Error loading knowledge</div>');
      });
  }

  function renderKnowledge(entries, total) {
    if (!entries.length) {
      setHtml("kbResults", '<div class="devhq-empty">No entries found</div>');
      document.getElementById("kbPagination").style.display = "none";
      return;
    }

    setHtml("kbResults", '<div class="devhq-kb-list">' +
      entries.map(function (e) {
        var tags = "";
        if (e.tags && Array.isArray(e.tags)) {
          tags = e.tags.slice(0, 3).map(function (t) {
            return '<span class="devhq-tag">' + escHtml(t) + "</span>";
          }).join(" ");
        }
        return (
          '<div class="devhq-kb-item" data-id="' + e.id + '" onclick="toggleKbDetail(this,' + e.id + ')">' +
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">' +
          '<div style="font-size:0.8rem;font-weight:500;color:var(--archie-text-primary);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(e.file_name || e.title || "Untitled") + "</div>" +
          '<div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">' +
          '<span class="devhq-badge ' + escHtml(e.knowledge_type || "code") + '">' + escHtml(e.knowledge_type || "code") + "</span>" +
          '<button class="devhq-btn small primary" onclick="event.stopPropagation();editKbEntry(' + e.id + ')" title="Edit"><i data-lucide="pencil" style="width:10px;height:10px;"></i></button>' +
          '<button class="devhq-btn small danger" onclick="event.stopPropagation();deleteKbEntry(' + e.id + ')" title="Delete"><i data-lucide="trash-2" style="width:10px;height:10px;"></i></button>' +
          "</div></div>" +
          '<div style="font-size:0.68rem;color:var(--archie-text-muted);margin-bottom:6px;">' +
          escHtml(e.primary_category || "uncategorized") + " \u00B7 Score: " + (e.importance_score || 0) + " \u00B7 " + escHtml(formatAge(e.updated_at)) +
          "</div>" +
          (tags ? '<div style="margin-bottom:6px;">' + tags + "</div>" : "") +
          (e.snippet ? '<div style="font-size:0.72rem;color:var(--archie-text-muted);max-height:50px;overflow:hidden;">' + escHtml(e.snippet.substring(0, 200)) + "</div>" : "") +
          '<div class="kb-detail-expand" style="display:none;margin-top:10px;"></div>' +
          "</div>"
        );
      }).join("") +
      "</div>");

    var totalPages = Math.ceil(total / _kbState.limit);
    var pag = document.getElementById("kbPagination");
    if (totalPages > 1) {
      pag.style.display = "flex";
      document.getElementById("kbPageInfo").textContent = "Page " + (_kbState.page + 1) + " of " + totalPages;
      document.getElementById("kbPrev").disabled = _kbState.page === 0;
      document.getElementById("kbNext").disabled = _kbState.page >= totalPages - 1;
    } else {
      pag.style.display = "none";
    }
    refreshIcons();
  }

  function toggleKbDetail(el, id) {
    var detail = el.querySelector(".kb-detail-expand");
    if (!detail) return;
    if (detail.style.display !== "none") {
      detail.style.display = "none";
      return;
    }
    detail.style.display = "block";
    setHtml(detail, '<div class="devhq-loading">Loading</div>');
    api("/api/knowledge/" + id).then(function (data) {
      if (!data.success) {
        setHtml(detail, '<div class="devhq-empty">Error loading detail</div>');
        return;
      }
      // Content rendered via renderMd (DOMPurify sanitized)
      setHtml(detail, '<div class="devhq-md-content">' + renderMd(data.entry.content || "No content") + "</div>");
    }).catch(function () {
      setHtml(detail, '<div class="devhq-empty">Error loading detail</div>');
    });
  }

  function kbPage(dir) {
    _kbState.page += dir;
    if (_kbState.page < 0) _kbState.page = 0;
    _cache.knowledge = false;
    loadKnowledge();
  }

  function openKbModal(entryId) {
    document.getElementById("kbEditId").value = "";
    document.getElementById("kbTitle").value = "";
    document.getElementById("kbCategoryInput").value = "";
    document.getElementById("kbContent").value = "";
    setHtml("kbPreview", '<div style="color:var(--archie-text-muted);font-size:0.72rem;">Preview will appear here...</div>');
    document.getElementById("kbModalTitle").textContent = "New Document";
    document.getElementById("kbSubmitBtn").textContent = "Create";

    if (entryId && typeof entryId === "number") {
      api("/api/knowledge/" + entryId).then(function (data) {
        if (!data.success || !data.entry) return;
        var e = data.entry;
        document.getElementById("kbEditId").value = e.id;
        document.getElementById("kbTitle").value = e.file_name || e.title || "";
        document.getElementById("kbCategoryInput").value = e.primary_category || "";
        document.getElementById("kbContent").value = e.content || "";
        setHtml("kbPreview", renderMd(e.content || ""));
        document.getElementById("kbModalTitle").textContent = "Edit Document";
        document.getElementById("kbSubmitBtn").textContent = "Update";
      });
    }

    document.getElementById("kbModal").style.display = "flex";
  }

  function editKbEntry(id) { openKbModal(id); }

  function deleteKbEntry(id) {
    if (!confirm("Delete this knowledge entry?")) return;
    api("/api/docs/" + id, { method: "DELETE" })
      .then(function (data) {
        if (!data.success) { alert("Error: " + (data.error || "Failed")); return; }
        _cache.knowledge = false;
        loadKnowledge();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function submitKb() {
    var editId = document.getElementById("kbEditId").value;
    var body = {
      title: document.getElementById("kbTitle").value.trim(),
      content: document.getElementById("kbContent").value.trim(),
      category: document.getElementById("kbCategoryInput").value.trim(),
    };
    if (!body.content) { alert("Content is required"); return; }

    var p;
    if (editId) {
      p = api("/api/docs/" + editId, { method: "PUT", body: body });
    } else {
      p = api("/api/docs", {
        body: {
          title: body.title || "Untitled Document",
          content: body.content,
          category: body.category,
          doc_type: "coder",
        },
      });
    }

    p.then(function () {
      closeModal("kbModal");
      _cache.knowledge = false;
      loadKnowledge();
    }).catch(function (err) {
      alert("Error: " + err.message);
    });
  }

  function toggleKbRoadmap() {
    var btn = document.getElementById("kbRoadmapBtn");
    var typeFilter = document.getElementById("kbTypeFilter");
    var searchEl = document.getElementById("kbSearch");

    _roadmapActive = !_roadmapActive;
    if (_roadmapActive) {
      btn.classList.add("active");
      typeFilter.value = "vault_note";
      searchEl.value = "roadmap";
    } else {
      btn.classList.remove("active");
      typeFilter.value = "";
      searchEl.value = "";
    }
    _kbState.page = 0;
    _cache.knowledge = false;
    loadKnowledge();
  }

  function updateKbPreview() {
    var content = document.getElementById("kbContent").value;
    setHtml("kbPreview", renderMd(content));
  }

  /* ========================================================================
     DECISIONS TAB
     ======================================================================== */

  function loadDecisions() {
    var projectId = document.getElementById("decFilterProject").value;
    var status = document.getElementById("decFilterStatus").value;
    var search = document.getElementById("decFilterSearch").value;
    var params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    params.set("limit", _decisionsState.limit);
    params.set("offset", _decisionsState.page * _decisionsState.limit);

    api("/api/decisions?" + params.toString()).then(function (data) {
      if (!data.success) {
        setHtml("decisionsContainer", '<div class="devhq-empty">Error loading decisions</div>');
        return;
      }
      _decisionsState.total = data.total;
      renderDecisions(data.decisions, data.total);
      populateDecisionProjectFilter();
    }).catch(function () {
      setHtml("decisionsContainer", '<div class="devhq-empty">Error loading decisions</div>');
    });
  }

  function populateDecisionProjectFilter() {
    var sel = document.getElementById("decFilterProject");
    if (sel.options.length > 1) return;
    api("/api/projects?status=active").then(function (data) {
      if (!data.success || !data.projects) return;
      data.projects.forEach(function (p) {
        var opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        sel.appendChild(opt);
      });
    }).catch(function () {});
  }

  function renderDecisions(decisions, total) {
    if (!decisions.length) {
      setHtml("decisionsContainer", '<div class="devhq-empty">No decisions found</div>');
      document.getElementById("decisionsPagination").style.display = "none";
      return;
    }

    setHtml("decisionsContainer", '<div class="devhq-kb-list">' + decisions.map(function (d) {
      return (
        '<div class="devhq-kb-item" onclick="toggleDecisionDetail(this,' + d.id + ')">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">' +
        '<div style="font-size:0.8rem;font-weight:500;color:var(--archie-text-primary);flex:1;min-width:0;">' +
        (d.decision_number ? '<span style="color:var(--archie-orange);margin-right:6px;font-family:Orbitron,sans-serif;font-size:0.7rem;">ADR-' + escHtml(String(d.decision_number).padStart(3, "0")) + '</span>' : '') +
        escHtml(d.title) + '</div>' +
        '<div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">' +
        (d.project_name ? '<span style="font-size:0.65rem;color:var(--archie-text-muted);">' + escHtml(d.project_name) + "</span>" : "") +
        '<span class="devhq-badge ' + escHtml(d.status) + '">' + escHtml(d.status) + "</span>" +
        "</div></div>" +
        '<div style="font-size:0.65rem;color:var(--archie-text-muted);">' + escHtml(formatDate(d.decided_at || d.created_at)) + "</div>" +
        '<div class="kb-detail-expand" style="display:none;margin-top:10px;"></div>' +
        "</div>"
      );
    }).join("") + "</div>");

    var totalPages = Math.ceil(total / _decisionsState.limit);
    var pag = document.getElementById("decisionsPagination");
    if (totalPages > 1) {
      pag.style.display = "flex";
      document.getElementById("decisionsPageInfo").textContent = "Page " + (_decisionsState.page + 1) + " of " + totalPages;
      document.getElementById("decisionsPrev").disabled = _decisionsState.page === 0;
      document.getElementById("decisionsNext").disabled = _decisionsState.page >= totalPages - 1;
    } else {
      pag.style.display = "none";
    }
    refreshIcons();
  }

  function toggleDecisionDetail(el, id) {
    var detail = el.querySelector(".kb-detail-expand");
    if (!detail) return;
    if (detail.style.display !== "none") {
      detail.style.display = "none";
      return;
    }
    detail.style.display = "block";
    if (detail.dataset.loaded === "true") return;
    setHtml(detail, '<div class="devhq-loading">Loading</div>');

    api("/api/decisions/" + id).then(function (data) {
      if (!data.success || !data.decision) {
        setHtml(detail, '<div class="devhq-empty">Error loading detail</div>');
        return;
      }
      var d = data.decision;
      // All markdown content rendered via renderMd (DOMPurify sanitized)
      var html = '<div class="devhq-md-content">';
      if (d.context) {
        html += '<div style="margin-bottom:12px;"><strong style="color:var(--archie-orange);font-size:0.72rem;text-transform:uppercase;">Context</strong>' +
          '<div style="margin-top:4px;">' + renderMd(d.context) + '</div></div>';
      }
      if (d.decision) {
        html += '<div style="margin-bottom:12px;"><strong style="color:var(--archie-orange);font-size:0.72rem;text-transform:uppercase;">Decision</strong>' +
          '<div style="margin-top:4px;">' + renderMd(d.decision) + '</div></div>';
      }
      if (d.alternatives) {
        html += '<div style="margin-bottom:12px;"><strong style="color:var(--archie-orange);font-size:0.72rem;text-transform:uppercase;">Alternatives Considered</strong>' +
          '<div style="margin-top:4px;">' + renderMd(d.alternatives) + '</div></div>';
      }
      if (d.consequences) {
        html += '<div style="margin-bottom:12px;"><strong style="color:var(--archie-orange);font-size:0.72rem;text-transform:uppercase;">Consequences</strong>' +
          '<div style="margin-top:4px;">' + renderMd(d.consequences) + '</div></div>';
      }
      if (d.tags) {
        html += '<div style="font-size:0.65rem;color:var(--archie-text-muted);margin-top:8px;">Tags: ' + escHtml(d.tags) + '</div>';
      }
      html += '</div>';
      setHtml(detail, html);
      detail.dataset.loaded = "true";
    }).catch(function () {
      setHtml(detail, '<div class="devhq-empty">Error loading detail</div>');
    });
  }

  function openDecisionModal() {
    document.getElementById("decisionEditId").value = "";
    document.getElementById("decisionTitle").value = "";
    document.getElementById("decisionContext").value = "";
    document.getElementById("decisionText").value = "";
    document.getElementById("decisionAlternatives").value = "";
    document.getElementById("decisionConsequences").value = "";
    document.getElementById("decisionStatus").value = "proposed";
    document.getElementById("decisionTags").value = "";
    document.getElementById("decisionModalTitle").textContent = "New Decision";
    document.getElementById("decisionSubmitBtn").textContent = "Create";

    var sel = document.getElementById("decisionProject");
    if (sel.options.length <= 1) {
      api("/api/projects?status=active").then(function (data) {
        if (!data.success || !data.projects) return;
        data.projects.forEach(function (p) {
          if (!Array.from(sel.options).some(function (o) { return o.value === String(p.id); })) {
            var opt = document.createElement("option");
            opt.value = p.id;
            opt.textContent = p.name;
            sel.appendChild(opt);
          }
        });
      });
    }

    document.getElementById("decisionModal").style.display = "flex";
  }

  function submitDecision() {
    var body = {
      title: document.getElementById("decisionTitle").value.trim(),
      project_id: document.getElementById("decisionProject").value || null,
      context: document.getElementById("decisionContext").value.trim(),
      decision: document.getElementById("decisionText").value.trim(),
      alternatives: document.getElementById("decisionAlternatives").value.trim(),
      consequences: document.getElementById("decisionConsequences").value.trim(),
      status: document.getElementById("decisionStatus").value,
      tags: document.getElementById("decisionTags").value.trim(),
    };
    if (!body.title) { alert("Decision title is required"); return; }

    api("/api/decisions", { body: body })
      .then(function (data) {
        if (!data.success) { alert("Error: " + (data.error || "Failed")); return; }
        closeModal("decisionModal");
        _cache.decisions = false;
        _cache.overview = false;
        loadDecisions();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function decisionPage(dir) {
    _decisionsState.page += dir;
    if (_decisionsState.page < 0) _decisionsState.page = 0;
    _cache.decisions = false;
    loadDecisions();
  }

  /* ========================================================================
     SYSTEM TAB (merged: Integrations + Schema + API Docs)
     ======================================================================== */

  function loadSystem() {
    loadIntegrations();
    loadSchema();
    loadApiDocs();
    loadModuleDocs();
  }

  function toggleSystemSection(bodyId) {
    var body = document.getElementById(bodyId);
    if (!body) return;
    var isHidden = body.style.display === "none";
    body.style.display = isHidden ? "block" : "none";
    var chevronId = bodyId.replace("Body", "Chevron");
    var chevron = document.getElementById(chevronId);
    if (chevron) {
      chevron.style.transform = isHidden ? "" : "rotate(-90deg)";
    }
  }

  function loadIntegrations() {
    Promise.all([
      api("/api/integrations/health").catch(function () { return { success: false }; }),
      api("/api/integrations/mcp").catch(function () { return { success: false }; }),
      api("/api/integrations/claude").catch(function () { return { success: false }; }),
    ]).then(function (results) {
      var healthData = results[0];
      var mcpData = results[1];
      var claudeData = results[2];

      // Health cards (all content escaped via escHtml)
      if (healthData.success && healthData.services) {
        setHtml("integrationsGrid", Object.keys(healthData.services).map(function (key) {
          var s = healthData.services[key];
          var dotClass = s.status === "online" ? "online" : s.status === "warning" ? "warning" : "error";
          return (
            '<div class="devhq-integration-card">' +
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">' +
            '<i data-lucide="' + escHtml(s.icon || "box") + '" style="width:24px;height:24px;color:var(--archie-orange);"></i>' +
            "<div>" +
            '<div style="font-size:0.8rem;font-weight:600;color:var(--archie-text-primary);">' + escHtml(s.name) + "</div>" +
            '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;">' +
            '<span class="status-dot ' + dotClass + '" style="width:8px;height:8px;border-radius:50%;display:inline-block;"></span>' +
            '<span style="font-size:0.68rem;color:var(--archie-text-muted);text-transform:uppercase;">' + escHtml(s.status) + "</span>" +
            "</div></div></div>" +
            '<div style="font-size:0.72rem;color:var(--archie-text-muted);">' + escHtml(s.detail) + "</div>" +
            "</div>"
          );
        }).join(""));
      } else {
        setHtml("integrationsGrid", '<div class="devhq-empty">Could not load health status</div>');
      }

      // MCP Servers (from .mcp.json config)
      if (mcpData.success && mcpData.mcp_config && mcpData.mcp_config.mcpServers) {
        var servers = mcpData.mcp_config.mcpServers;
        var serverNames = Object.keys(servers);
        var sHtml = '<div class="devhq-integrations-grid">';
        serverNames.forEach(function (name) {
          var srv = servers[name];
          var cmd = escHtml(srv.command || "unknown");
          var args = (srv.args || []).map(function (a) { return escHtml(String(a)); }).join(" ");
          var envKeys = Object.keys(srv.env || {});
          sHtml +=
            '<div class="devhq-integration-card">' +
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">' +
            '<i data-lucide="server" style="width:20px;height:20px;color:var(--archie-orange);"></i>' +
            '<div><div style="font-size:0.8rem;font-weight:600;color:var(--archie-text-primary);">' + escHtml(name) + '</div>' +
            '<div style="font-size:0.65rem;color:var(--archie-text-muted);">' + cmd + '</div></div></div>' +
            '<div style="font-size:0.68rem;color:var(--archie-text-muted);">' +
            (args ? '<div style="margin-bottom:4px;"><span style="color:var(--archie-orange);">args:</span> ' + args + '</div>' : '') +
            (envKeys.length ? '<div><span style="color:var(--archie-orange);">env:</span> ' + envKeys.map(function (k) { return escHtml(k); }).join(", ") + '</div>' : '') +
            '</div></div>';
        });
        sHtml += '</div>';
        setHtml("mcpServersPanel", sHtml);
      } else {
        setHtml("mcpServersPanel", '<div class="devhq-empty">No MCP servers configured</div>');
      }

      // MCP Tool Registry (from DB)
      if (mcpData.success && mcpData.mcp_tools_db && mcpData.mcp_tools_db.length) {
        var toolsByCat = {};
        mcpData.mcp_tools_db.forEach(function (tool) {
          var cat = tool.category || "uncategorized";
          if (!toolsByCat[cat]) toolsByCat[cat] = [];
          toolsByCat[cat].push(tool);
        });
        var totalTools = mcpData.mcp_tools_db.length;
        var countEl = document.getElementById("mcpToolCount");
        if (countEl) countEl.textContent = "(" + totalTools + " tools)";
        var mcpHtml = "";
        Object.keys(toolsByCat).sort().forEach(function (cat) {
          var tools = toolsByCat[cat];
          mcpHtml +=
            '<div style="margin-bottom:12px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:var(--archie-orange);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;cursor:pointer;" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">' +
            '<i data-lucide="chevron-down" style="width:12px;height:12px;vertical-align:middle;margin-right:4px;"></i>' +
            escHtml(cat) + " (" + tools.length + ")</div><div>";
          tools.forEach(function (t) {
            mcpHtml +=
              '<div style="display:flex;align-items:center;gap:8px;padding:5px 10px;font-size:0.72rem;border-left:2px solid ' + (t.enabled ? 'var(--archie-green)' : 'var(--archie-text-muted)') + ';margin-bottom:2px;">' +
              '<span style="color:var(--archie-text-primary);font-weight:500;">' + escHtml(t.name) + "</span>" +
              '<span style="font-size:0.65rem;color:var(--archie-text-muted);margin-left:auto;max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml((t.description || "").substring(0, 80)) + "</span>" +
              "</div>";
          });
          mcpHtml += "</div></div>";
        });

        // Add tool usage stats if available
        if (mcpData.tool_usage && mcpData.tool_usage.length) {
          mcpHtml += '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--archie-border);">' +
            '<div style="font-size:0.72rem;font-weight:600;color:var(--archie-orange);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;">Recent Usage</div>';
          mcpData.tool_usage.slice(0, 10).forEach(function (u) {
            mcpHtml +=
              '<div style="display:flex;align-items:center;gap:8px;padding:3px 10px;font-size:0.68rem;">' +
              '<span style="color:var(--archie-text-primary);">' + escHtml(u.tool_name) + '</span>' +
              '<span style="margin-left:auto;color:var(--archie-orange);font-weight:600;">' + u.usage_count + 'x</span>' +
              '</div>';
          });
          mcpHtml += '</div>';
        }

        setHtml("mcpToolRegistry", mcpHtml);
      } else {
        setHtml("mcpToolRegistry", '<div class="devhq-empty">No MCP tools registered in database</div>');
        var countEl = document.getElementById("mcpToolCount");
        if (countEl) countEl.textContent = "";
      }

      // Claude Config (all content escaped via escHtml)
      var claudeEl = document.getElementById("claudeConfigPanel");
      if (claudeData.success) {
        var cHtml = "";
        if (claudeData.claude_md_root) {
          cHtml +=
            '<div style="margin-bottom:16px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:var(--archie-orange);margin-bottom:6px;">CLAUDE.md (Root)</div>' +
            '<div class="devhq-pre">' + escHtml(claudeData.claude_md_root.substring(0, 800)) +
            (claudeData.claude_md_root.length > 800 ? "\n..." : "") + "</div></div>";
        }
        if (claudeData.custom_commands && claudeData.custom_commands.length) {
          cHtml += '<div style="margin-bottom:16px;"><div style="font-size:0.72rem;font-weight:600;color:var(--archie-orange);margin-bottom:6px;">Custom Commands</div>';
          claudeData.custom_commands.forEach(function (cmd) {
            cHtml +=
              '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:0.72rem;">' +
              '<span style="color:var(--archie-cyan);">/' + escHtml(cmd.name) + "</span>" +
              '<span style="color:var(--archie-text-muted);">' + escHtml(cmd.description) + "</span></div>";
          });
          cHtml += "</div>";
        }
        if (claudeData.hooks && claudeData.hooks.length) {
          cHtml += '<div><div style="font-size:0.72rem;font-weight:600;color:var(--archie-orange);margin-bottom:6px;">Hooks</div>';
          claudeData.hooks.forEach(function (h) {
            cHtml += '<div style="padding:2px 0;font-size:0.72rem;color:var(--archie-text-muted);">' + escHtml(h) + "</div>";
          });
          cHtml += "</div>";
        }
        setHtml(claudeEl, cHtml || '<div class="devhq-empty">No Claude config found</div>');
      } else {
        setHtml(claudeEl, '<div class="devhq-empty">Could not load Claude config</div>');
      }

      refreshIcons();

      // Load supplementary data
      loadHealthHistory();
      loadMcpUsage();
    });
  }

  function loadHealthHistory() {
    api("/api/integrations/health/history").then(function (data) {
      var history = data.history || {};
      var container = document.getElementById("healthSparklines");
      if (!container || Object.keys(history).length === 0) return;

      var html = "";
      document.getElementById("healthHistoryRow").style.display = "block";

      Object.keys(history).sort().forEach(function (svc) {
        var checks = history[svc];
        var recent = checks.slice(-24);
        var dots = recent.map(function (c) {
          var color = c.status === "online" ? "var(--archie-green, #22c55e)"
                    : c.status === "warning" ? "var(--archie-orange, #ffa500)"
                    : "var(--archie-red, #ef4444)";
          var ts = c.checked_at ? ArchieTime.time(c.checked_at) : "";
          var title = escHtml(c.status + " - " + (c.detail || "") + " (" + ts + ")");
          return '<span title="' + title + '" style="display:inline-block;width:6px;height:14px;background:' + color + ';border-radius:1px;margin:0 1px;"></span>';
        }).join("");

        html +=
          '<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;background:var(--archie-bg-secondary);border-radius:6px;">' +
          '<span style="font-size:0.68rem;color:var(--archie-text-muted);min-width:70px;">' + escHtml(svc) + '</span>' +
          '<div style="display:flex;align-items:center;">' + dots + '</div>' +
          '</div>';
      });

      setHtml(container, html);
      refreshIcons();
    }).catch(function () {});
  }

  function loadMcpUsage() {
    api("/api/integrations/mcp/usage").then(function (data) {
      var panel = document.getElementById("mcpUsagePanel");
      if (!panel) return;

      var stats = data.tool_stats || [];
      var errors = data.errors || [];

      if (stats.length === 0 && errors.length === 0) {
        setHtml(panel, '<div class="devhq-empty">No usage data yet</div>');
        return;
      }

      var html = "";

      if (stats.length > 0) {
        html += '<div style="display:flex;flex-direction:column;gap:4px;">';
        var maxCalls = stats[0].total_calls || 1;
        stats.slice(0, 10).forEach(function (tool) {
          var pct = Math.round((tool.total_calls / maxCalls) * 100);
          var errorRate = tool.total_calls > 0
            ? Math.round(((tool.total_calls - tool.successful_calls) / tool.total_calls) * 100)
            : 0;
          var barColor = errorRate > 20 ? "var(--archie-red, #ef4444)" : errorRate > 5 ? "var(--archie-orange)" : "var(--archie-green, #22c55e)";

          html +=
            '<div style="display:flex;align-items:center;gap:8px;font-size:0.72rem;">' +
            '<span style="min-width:130px;color:var(--archie-text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escHtml(tool.tool_name) + '">' + escHtml(tool.tool_name) + '</span>' +
            '<div style="flex:1;height:8px;background:var(--archie-bg-primary);border-radius:4px;overflow:hidden;">' +
            '<div style="width:' + pct + '%;height:100%;background:' + barColor + ';border-radius:4px;"></div></div>' +
            '<span style="min-width:35px;text-align:right;color:var(--archie-text-primary);font-weight:600;">' + tool.total_calls + '</span>' +
            '<span style="min-width:45px;text-align:right;color:var(--archie-text-muted);font-size:0.65rem;">' + (tool.avg_response_ms || 0) + 'ms</span>' +
            (errorRate > 0 ? '<span style="min-width:30px;color:var(--archie-red, #ef4444);font-size:0.65rem;">' + errorRate + '%</span>' : '') +
            '</div>';
        });
        html += '</div>';
      }

      if (errors.length > 0) {
        html +=
          '<div style="margin-top:12px;padding:8px;background:rgba(239,68,68,0.05);border-radius:6px;border:1px solid rgba(239,68,68,0.1);">' +
          '<div style="font-size:0.72rem;font-weight:600;color:var(--archie-red, #ef4444);margin-bottom:4px;">Recent Errors</div>';
        errors.slice(0, 5).forEach(function (err) {
          html +=
            '<div style="font-size:0.68rem;color:var(--archie-text-muted);padding:2px 0;">' +
            escHtml(err.tool_name) + ': ' + escHtml(err.error_message || err.error_code || "unknown") +
            ' (' + err.count + 'x)</div>';
        });
        html += '</div>';
      }

      setHtml(panel, html);
    }).catch(function () {
      var panel = document.getElementById("mcpUsagePanel");
      if (panel) setHtml(panel, '<div class="devhq-empty">Could not load usage data</div>');
    });
  }

  window.runQuickAction = function (action) {
    var resultDiv = document.getElementById("quickActionResult");
    if (resultDiv) {
      resultDiv.style.display = "block";
      setHtml(resultDiv, '<span style="color:var(--archie-orange);">Running...</span>');
    }

    var path;
    if (action === "health-check") {
      path = "/api/integrations/health/check";
    } else if (action === "sync-mcp-tools") {
      path = "/api/system/actions/sync-mcp-tools";
    } else {
      path = "/api/system/actions/" + action;
    }

    api(path, { method: "POST" })
      .then(function (data) {
        if (resultDiv) {
          if (data.success !== false) {
            setHtml(resultDiv, '<span style="color:var(--archie-green, #22c55e);">&#10003; ' + escHtml(data.message || "Done") + '</span>');
            if (action === "health-check") {
              setTimeout(function () { loadIntegrations(); }, 1000);
            }
          } else {
            setHtml(resultDiv, '<span style="color:var(--archie-red, #ef4444);">Error: ' + escHtml(data.error || "Unknown") + '</span>');
          }
        }
      })
      .catch(function (e) {
        if (resultDiv) {
          setHtml(resultDiv, '<span style="color:var(--archie-red, #ef4444);">Failed: ' + escHtml(e.message || "Network error") + '</span>');
        }
      });

    // Auto-hide after 6s
    setTimeout(function () {
      if (resultDiv) resultDiv.style.display = "none";
    }, 6000);
  };

  function loadSchema() {
    api("/api/schema")
      .then(function (data) {
        if (!data.tables) {
          setHtml("schemaTableList", '<div class="devhq-empty">No schema data available</div>');
          return;
        }
        _schemaData = data.tables;
        renderSchemaList(_schemaData);
      })
      .catch(function () {
        setHtml("schemaTableList", '<div class="devhq-empty">Error loading schema</div>');
      });
  }

  function renderSchemaList(tables) {
    if (!tables || !tables.length) {
      setHtml("schemaTableList", '<div class="devhq-empty">No tables</div>');
      return;
    }
    setHtml("schemaTableList", tables.map(function (t) {
      var name = typeof t === "string" ? t : (t.table_name || t.name);
      var count = t.row_count != null ? t.row_count : "";
      return (
        '<div class="devhq-table-item" onclick="showTableColumns(\'' + escHtml(name) + '\')">' +
        '<span style="font-family:var(--archie-font-mono);">' + escHtml(name) + "</span>" +
        (count !== "" ? '<span style="font-size:0.65rem;color:var(--archie-text-muted);">' + count + " rows</span>" : "") +
        "</div>"
      );
    }).join(""));
  }

  function showTableColumns(tableName) {
    document.getElementById("schemaDetailHeader").textContent = tableName;
    document.querySelectorAll(".devhq-table-item").forEach(function (el) {
      el.classList.toggle("selected", el.textContent.trim().startsWith(tableName));
    });

    var table = _schemaData ? _schemaData.find(function (t) { return (t.table_name || t.name) === tableName; }) : null;
    if (!table || !table.columns) {
      setHtml("schemaDetail", '<div class="devhq-empty">No column info available</div>');
      return;
    }

    var html = '<table class="devhq-table"><thead><tr><th>Column</th><th>Type</th><th>Nullable</th><th>Default</th></tr></thead><tbody>';
    table.columns.forEach(function (col) {
      html +=
        "<tr>" +
        "<td><strong>" + escHtml(col.column_name || col.name) + "</strong></td>" +
        "<td>" + escHtml(col.data_type || col.type || "") + "</td>" +
        "<td>" + ((col.is_nullable === "YES" || col.nullable) ? "Yes" : "No") + "</td>" +
        '<td style="font-size:0.7rem;color:var(--archie-text-muted);">' + escHtml(col.column_default || col.default_value || "\u2014") + "</td>" +
        "</tr>";
    });
    html += "</tbody></table>";

    if (table.foreign_keys && table.foreign_keys.length) {
      html += '<div style="margin-top:16px;font-size:0.72rem;"><strong style="color:var(--archie-orange);">Foreign Keys</strong>';
      table.foreign_keys.forEach(function (fk) {
        html += '<div style="padding:4px 0;color:var(--archie-text-muted);">' +
          escHtml(fk.column || fk.column_name) + " \u2192 " +
          escHtml(fk.foreign_table || fk.references_table) + "." +
          escHtml(fk.foreign_column || fk.references_column) + "</div>";
      });
      html += "</div>";
    }

    if (table.indexes && table.indexes.length) {
      html += '<div style="margin-top:12px;font-size:0.72rem;"><strong style="color:var(--archie-orange);">Indexes</strong>';
      table.indexes.forEach(function (idx) {
        html += '<div style="padding:4px 0;color:var(--archie-text-muted);">' +
          escHtml(idx.index_name || idx.name) +
          (idx.is_unique ? " (unique)" : "") + "</div>";
      });
      html += "</div>";
    }

    setHtml("schemaDetail", html);
  }

  function loadApiDocs() {
    api("/api/docs")
      .then(function (data) {
        if (!data.endpoints && !data.blueprints) {
          setHtml("apiDocsContainer", '<div class="devhq-empty">No API documentation available</div>');
          return;
        }
        _apiData = data;
        renderApiDocs(data);
      })
      .catch(function () {
        setHtml("apiDocsContainer", '<div class="devhq-empty">Error loading API docs</div>');
      });
  }

  function renderApiDocs(data) {
    var groups = {};
    var endpoints = data.endpoints || [];
    endpoints.forEach(function (ep) {
      var bp = ep.blueprint || ep.module || "Unknown";
      if (!groups[bp]) groups[bp] = [];
      groups[bp].push(ep);
    });

    var search = (document.getElementById("apiSearch").value || "").toLowerCase();
    var html = "";

    Object.keys(groups).sort().forEach(function (bp) {
      var epList = groups[bp];
      if (search) {
        epList = epList.filter(function (ep) {
          return (ep.rule || ep.path || "").toLowerCase().indexOf(search) !== -1 ||
                 (ep.endpoint || ep.name || "").toLowerCase().indexOf(search) !== -1;
        });
        if (!epList.length) return;
      }
      html +=
        '<div class="devhq-endpoint-group">' +
        '<div class="devhq-endpoint-group-title" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">' +
        '<i data-lucide="chevron-down" style="width:14px;height:14px;"></i> ' +
        escHtml(bp) + " (" + epList.length + ")" +
        "</div>" +
        '<div style="display:block;">';
      epList.forEach(function (ep) {
        var methods = ep.methods
          ? ep.methods.filter(function (m) { return m !== "OPTIONS" && m !== "HEAD"; })
          : [ep.method || "GET"];
        methods.forEach(function (m) {
          html +=
            '<div class="devhq-endpoint-row">' +
            '<span class="devhq-method ' + m.toLowerCase() + '">' + escHtml(m) + "</span>" +
            '<span style="color:var(--archie-text-primary);font-family:var(--archie-font-mono);">' + escHtml(ep.rule || ep.path || "") + "</span>" +
            '<span style="font-size:0.68rem;color:var(--archie-text-muted);margin-left:auto;">' + escHtml(ep.endpoint || ep.name || "") + "</span>" +
            "</div>";
        });
      });
      html += "</div></div>";
    });

    setHtml("apiDocsContainer", html || '<div class="devhq-empty">No endpoints match your search</div>');
    refreshIcons();
  }

  /* ========================================================================
     MODULE DOCS (System sub-section)
     ======================================================================== */

  var _moduleDocsState = { page: 0, limit: 30, total: 0, modulesLoaded: false };

  function loadModuleDocs() {
    // Populate module dropdown on first load
    if (!_moduleDocsState.modulesLoaded) {
      api("/api/docs/modules").then(function (data) {
        if (!data.success || !data.modules) return;
        var sel = document.getElementById("moduleDocsModule");
        var moduleNames = Object.keys(data.modules).sort();
        var totalDocs = 0;
        moduleNames.forEach(function (mod) {
          var counts = data.modules[mod];
          var ct = (counts.user || 0) + (counts.coder || 0);
          totalDocs += ct;
          var opt = document.createElement("option");
          opt.value = mod;
          opt.textContent = mod + " (" + ct + ")";
          sel.appendChild(opt);
        });
        var countEl = document.getElementById("moduleDocsCount");
        if (countEl) countEl.textContent = "(" + totalDocs + " docs)";
        _moduleDocsState.modulesLoaded = true;
      }).catch(function () {});
    }
    // Fetch docs list
    var module = document.getElementById("moduleDocsModule").value;
    var docType = document.getElementById("moduleDocsType").value;
    var search = document.getElementById("moduleDocsSearch").value;
    var params = new URLSearchParams();
    if (module) params.set("module", module);
    if (docType) params.set("doc_type", docType);
    if (search) params.set("search", search);
    params.set("limit", _moduleDocsState.limit);
    params.set("offset", _moduleDocsState.page * _moduleDocsState.limit);

    api("/api/docs/list?" + params.toString()).then(function (data) {
      if (!data.success) {
        setHtml("moduleDocsContainer", '<div class="devhq-empty">Error loading module docs</div>');
        return;
      }
      _moduleDocsState.total = data.total;
      renderModuleDocs(data.entries, data.total);
    }).catch(function () {
      setHtml("moduleDocsContainer", '<div class="devhq-empty">Error loading module docs</div>');
    });
  }

  function renderModuleDocs(entries, total) {
    if (!entries.length) {
      setHtml("moduleDocsContainer", '<div class="devhq-empty">No module docs found</div>');
      return;
    }
    var html = '<div class="devhq-kb-list">';
    entries.forEach(function (e) {
      var meta = e.memory_metadata || {};
      var docType = meta.doc_type || "note";
      var moduleName = meta.module || "unknown";
      var badgeClass = docType === "user" ? "green" : docType === "coder" ? "cyan" : "";
      var tags = "";
      if (e.tags && Array.isArray(e.tags)) {
        tags = e.tags.slice(0, 3).map(function (t) {
          return '<span class="devhq-tag">' + escHtml(t) + "</span>";
        }).join(" ");
      }
      html +=
        '<div class="devhq-kb-item" onclick="toggleModuleDocDetail(this,' + e.id + ')">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">' +
        '<div style="font-size:0.8rem;font-weight:500;color:var(--archie-text-primary);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
        escHtml(e.file_name || e.title || "Untitled") + "</div>" +
        '<div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">' +
        '<span class="devhq-badge ' + escHtml(badgeClass) + '">' + escHtml(docType) + "</span>" +
        '<span style="font-size:0.62rem;color:var(--archie-text-muted);background:var(--archie-bg-primary);padding:2px 6px;border-radius:4px;">' + escHtml(moduleName) + "</span>" +
        "</div></div>" +
        '<div style="font-size:0.68rem;color:var(--archie-text-muted);margin-bottom:4px;">' +
        escHtml(e.primary_category || "uncategorized") + " \u00B7 Score: " + (e.importance_score || 0) + " \u00B7 " + escHtml(formatAge(e.updated_at)) +
        "</div>" +
        (tags ? '<div style="margin-bottom:4px;">' + tags + "</div>" : "") +
        (e.snippet ? '<div style="font-size:0.72rem;color:var(--archie-text-muted);max-height:40px;overflow:hidden;">' + escHtml(e.snippet.substring(0, 200)) + "</div>" : "") +
        '<div class="kb-detail-expand" style="display:none;margin-top:10px;"></div>' +
        "</div>";
    });
    html += "</div>";

    var totalPages = Math.ceil(total / _moduleDocsState.limit);
    if (totalPages > 1) {
      html += '<div style="display:flex;align-items:center;justify-content:center;gap:12px;padding:12px 0;">' +
        '<button class="devhq-btn small secondary" onclick="moduleDocsPage(-1)"' + (_moduleDocsState.page === 0 ? " disabled" : "") + '>Prev</button>' +
        '<span style="font-size:0.72rem;color:var(--archie-text-muted);">Page ' + (_moduleDocsState.page + 1) + ' of ' + totalPages + '</span>' +
        '<button class="devhq-btn small secondary" onclick="moduleDocsPage(1)"' + (_moduleDocsState.page >= totalPages - 1 ? " disabled" : "") + '>Next</button>' +
        '</div>';
    }

    setHtml("moduleDocsContainer", html);
    refreshIcons();
  }

  function toggleModuleDocDetail(el, id) {
    var detail = el.querySelector(".kb-detail-expand");
    if (!detail) return;
    if (detail.style.display !== "none") {
      detail.style.display = "none";
      return;
    }
    detail.style.display = "block";
    if (detail.dataset.loaded === "true") return;
    setHtml(detail, '<div class="devhq-loading">Loading</div>');
    api("/api/docs/" + id).then(function (data) {
      if (!data.success || !data.entry) {
        setHtml(detail, '<div class="devhq-empty">Error loading detail</div>');
        return;
      }
      detail.dataset.loaded = "true";
      setHtml(detail, '<div class="devhq-md-content">' + renderMd(data.entry.content || "No content") + "</div>");
    }).catch(function () {
      setHtml(detail, '<div class="devhq-empty">Error loading detail</div>');
    });
  }

  function moduleDocsPage(dir) {
    _moduleDocsState.page += dir;
    if (_moduleDocsState.page < 0) _moduleDocsState.page = 0;
    loadModuleDocs();
  }

  /* ========================================================================
     PROJECT DOC MODAL
     ======================================================================== */

  var _editingProjectDocId = null;

  function openProjectDocModal(docId) {
    _editingProjectDocId = docId || null;
    document.getElementById("projectDocTitle").value = "";
    document.getElementById("projectDocType").value = "design";
    document.getElementById("projectDocContent").value = "";
    document.getElementById("projectDocTags").value = "";
    setHtml("projectDocPreview", '<div style="color:var(--archie-text-muted);font-size:0.72rem;">Preview will appear here...</div>');
    document.getElementById("projectDocModalTitle").textContent = "New Document";
    document.getElementById("projectDocSubmitBtn").textContent = "Create";

    if (docId && _currentProject) {
      api("/api/projects/" + _currentProject.id + "/docs/" + docId).then(function (data) {
        if (!data.success || !data.doc) return;
        var d = data.doc;
        document.getElementById("projectDocTitle").value = d.title || "";
        document.getElementById("projectDocType").value = d.doc_type || "design";
        document.getElementById("projectDocContent").value = d.content || "";
        document.getElementById("projectDocTags").value = (d.tags && Array.isArray(d.tags)) ? d.tags.join(", ") : "";
        setHtml("projectDocPreview", renderMd(d.content || ""));
        document.getElementById("projectDocModalTitle").textContent = "Edit Document";
        document.getElementById("projectDocSubmitBtn").textContent = "Update";
      });
    }

    document.getElementById("projectDocModal").style.display = "flex";
  }

  function submitProjectDoc() {
    if (!_currentProject) { alert("No project selected"); return; }
    var tagsRaw = document.getElementById("projectDocTags").value.trim();
    var tags = tagsRaw ? tagsRaw.split(",").map(function (t) { return t.trim(); }).filter(Boolean) : null;
    var body = {
      title: document.getElementById("projectDocTitle").value.trim(),
      doc_type: document.getElementById("projectDocType").value,
      content: document.getElementById("projectDocContent").value.trim(),
      tags: tags,
    };
    if (!body.content) { alert("Content is required"); return; }
    if (!body.title) body.title = "Untitled";

    var p;
    if (_editingProjectDocId) {
      p = api("/api/projects/" + _currentProject.id + "/docs/" + _editingProjectDocId, { method: "PUT", body: body });
    } else {
      p = api("/api/projects/" + _currentProject.id + "/docs", { body: body });
    }

    p.then(function (data) {
      if (!data.success) { alert("Error: " + (data.error || "Failed")); return; }
      closeModal("projectDocModal");
      _editingProjectDocId = null;
      loadProjectDocs(_currentProject.id);
    }).catch(function (err) {
      alert("Error: " + err.message);
    });
  }

  function deleteProjectDoc(docId) {
    if (!confirm("Delete this document?")) return;
    if (!_currentProject) return;
    api("/api/projects/" + _currentProject.id + "/docs/" + docId, { method: "DELETE" })
      .then(function (data) {
        if (!data.success) { alert("Error: " + (data.error || "Failed")); return; }
        loadProjectDocs(_currentProject.id);
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function updateProjectDocPreview() {
    var content = document.getElementById("projectDocContent").value;
    setHtml("projectDocPreview", renderMd(content));
  }

  /* ========================================================================
     CLOCK
     ======================================================================== */

  function updateClock() {
    var now = new Date();
    var el = document.getElementById("hqClock");
    if (el) {
      el.textContent =
        String(now.getHours()).padStart(2, "0") + ":" +
        String(now.getMinutes()).padStart(2, "0") + ":" +
        String(now.getSeconds()).padStart(2, "0");
    }
  }

  /* ========================================================================
     EXPOSE GLOBALS (onclick/oninput handlers referenced in HTML)
     ======================================================================== */
  window.switchDevHQTab = switchDevHQTab;
  window.openProjectModal = openProjectModal;
  window.submitProject = submitProject;
  window.deleteProject = deleteProject;
  window.closeModal = closeModal;
  window.openProjectDetail = openProjectDetail;
  window.closeProjectDetail = closeProjectDetail;
  window.switchProjectSubTab = switchProjectSubTab;
  window.openTaskModal = openTaskModal;
  window.submitTask = submitTask;
  window.deleteTask = deleteTask;
  window.cycleTaskStatus = cycleTaskStatus;
  window.taskPage = taskPage;
  window.openIdeaModal = openIdeaModal;
  window.submitIdea = submitIdea;
  window.deleteIdea = deleteIdea;
  window.promoteIdea = promoteIdea;
  window.ideaPage = ideaPage;
  window.openKbModal = openKbModal;
  window.submitKb = submitKb;
  window.kbPage = kbPage;
  window.editKbEntry = editKbEntry;
  window.deleteKbEntry = deleteKbEntry;
  window.toggleKbDetail = toggleKbDetail;
  window.toggleKbRoadmap = toggleKbRoadmap;
  window.updateKbPreview = updateKbPreview;
  window.openDecisionModal = openDecisionModal;
  window.submitDecision = submitDecision;
  window.toggleDecisionDetail = toggleDecisionDetail;
  window.decisionPage = decisionPage;
  window.showTableColumns = showTableColumns;
  window.toggleSystemSection = toggleSystemSection;
  window.toggleModuleDocDetail = toggleModuleDocDetail;
  window.moduleDocsPage = moduleDocsPage;
  window.openProjectDocModal = openProjectDocModal;
  window.submitProjectDoc = submitProjectDoc;
  window.deleteProjectDoc = deleteProjectDoc;
  window.updateProjectDocPreview = updateProjectDocPreview;
  window.viewProjectDoc = viewProjectDoc;
  window.loadProjectDocs = loadProjectDocs;
  window.loadProjectTasks = loadProjectTasks;

  /* ========================================================================
     INIT
     ======================================================================== */

  /* Expose init for Consciousness tab integration */
  window.initDevHQPanel = function () {
    refreshIcons();
    loadTabData("overview");
  };

  document.addEventListener("DOMContentLoaded", function () {
    /* Only self-initialize on the standalone /dev-hq page */
    if (!document.getElementById("panel-devhq")) {
      refreshIcons();
      updateClock();
      setInterval(updateClock, 1000);

      var hash = window.location.hash.replace("#", "");
      var validTabs = ["overview", "projects", "ideas", "knowledge", "decisions", "system"];
      if (hash && validTabs.indexOf(hash) !== -1) {
        switchDevHQTab(hash);
      } else {
        switchDevHQTab("overview");
      }
      // Projects filters
      var el;
      el = document.getElementById("projFilterStatus"); if (el) el.addEventListener("change", function () { _cache.projects = false; loadProjects(); });
      el = document.getElementById("projFilterPriority"); if (el) el.addEventListener("change", function () { _cache.projects = false; loadProjects(); });
      el = document.getElementById("projFilterSearch"); if (el) el.addEventListener("input", function () { debounceReload("projects", loadProjects); });

      // Ideas filters
      el = document.getElementById("ideaFilterCategory"); if (el) el.addEventListener("change", function () { _ideasState.page = 0; _cache.ideas = false; loadIdeas(); });
      el = document.getElementById("ideaFilterStatus"); if (el) el.addEventListener("change", function () { _ideasState.page = 0; _cache.ideas = false; loadIdeas(); });
      el = document.getElementById("ideaFilterSearch"); if (el) el.addEventListener("input", function () { _ideasState.page = 0; debounceReload("ideas", loadIdeas); });

      // Knowledge filters
      el = document.getElementById("kbSearch"); if (el) el.addEventListener("input", function () { _kbState.page = 0; debounceReload("knowledge", loadKnowledge); });
      el = document.getElementById("kbTypeFilter"); if (el) el.addEventListener("change", function () { _kbState.page = 0; _cache.knowledge = false; loadKnowledge(); });
      el = document.getElementById("kbCategory"); if (el) el.addEventListener("change", function () { _kbState.page = 0; _cache.knowledge = false; loadKnowledge(); });

      // Decisions filters
      el = document.getElementById("decFilterProject"); if (el) el.addEventListener("change", function () { _decisionsState.page = 0; _cache.decisions = false; loadDecisions(); });
      el = document.getElementById("decFilterStatus"); if (el) el.addEventListener("change", function () { _decisionsState.page = 0; _cache.decisions = false; loadDecisions(); });
      el = document.getElementById("decFilterSearch"); if (el) el.addEventListener("input", function () { _decisionsState.page = 0; debounceReload("decisions", loadDecisions); });

      // Schema search
      el = document.getElementById("schemaSearch"); if (el) el.addEventListener("input", function () {
        if (!_schemaData) return;
        var q = this.value.toLowerCase();
        var filtered = q
          ? _schemaData.filter(function (t) { return (t.table_name || t.name || "").toLowerCase().indexOf(q) !== -1; })
          : _schemaData;
        renderSchemaList(filtered);
      });

      // API search
      el = document.getElementById("apiSearch"); if (el) el.addEventListener("input", function () {
        if (!_apiData) return;
        renderApiDocs(_apiData);
      });

      // Module docs filters
      el = document.getElementById("moduleDocsModule"); if (el) el.addEventListener("change", function () { _moduleDocsState.page = 0; loadModuleDocs(); });
      el = document.getElementById("moduleDocsType"); if (el) el.addEventListener("change", function () { _moduleDocsState.page = 0; loadModuleDocs(); });
      el = document.getElementById("moduleDocsSearch"); if (el) el.addEventListener("input", function () { _moduleDocsState.page = 0; debounceReload("moduleDocs", loadModuleDocs); });
    }
  });
})();
