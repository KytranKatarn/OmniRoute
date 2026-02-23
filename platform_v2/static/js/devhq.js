/* ============================================================================
   A.R.C.H.I.E. DEV HQ — JavaScript Controller
   Handles all 7 tabs: Overview, Projects, Tasks, Knowledge, Schema, API, Integrations
   ============================================================================ */
(function () {
  "use strict";

  /* --- State --- */
  var _cache = {};
  var _taskState = { page: 0, limit: 30, total: 0 };
  var _kbState = { page: 0, limit: 20, total: 0 };
  var _schemaData = null;
  var _apiData = null;

  /* --- Utility: HTML-safe escaping via DOM --- */
  function escHtml(str) {
    if (str == null) return "";
    var div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  /* --- Utility: Relative time --- */
  function formatAge(dateStr) {
    if (!dateStr) return "\u2014";
    var d = new Date(dateStr);
    var diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    if (diff < 604800) return Math.floor(diff / 86400) + "d ago";
    return d.toLocaleDateString();
  }

  /* --- Utility: Format date --- */
  function formatDate(dateStr) {
    if (!dateStr) return "\u2014";
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  /* --- Utility: API helper --- */
  function api(path, opts) {
    opts = opts || {};
    var url = "/dev-hq" + path;
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

  /* --- Utility: Refresh Lucide icons --- */
  function refreshIcons() {
    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  }

  /* --- Modal helpers --- */
  function closeModal(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = "none";
  }

  /* ========================================================================
     TAB SYSTEM
     ======================================================================== */
  function switchDevHQTab(tab) {
    document.querySelectorAll(".devhq-tab").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".devhq-panel").forEach(function (panel) {
      panel.classList.toggle("active", panel.id === "panel-" + tab);
    });
    history.replaceState(null, "", "#" + tab);
    loadTabData(tab);
  }

  function loadTabData(tab) {
    if (_cache[tab]) return;
    _cache[tab] = true;
    switch (tab) {
      case "overview":     loadOverview(); break;
      case "projects":     loadProjects(); break;
      case "tasks":        loadAllTasks(); break;
      case "knowledge":    loadKnowledge(); break;
      case "schema":       loadSchema(); break;
      case "api":          loadApiDocs(); break;
      case "integrations": loadIntegrations(); break;
    }
  }

  /* ========================================================================
     OVERVIEW TAB
     ======================================================================== */
  function loadOverview() {
    api("/api/overview").then(function (data) {
      if (!data.success) return;

      var activeCount = data.project_stats.active || 0;
      var openTasks = data.task_stats.open_tasks || 0;
      document.getElementById("statActiveProjects").textContent = activeCount;
      document.getElementById("statOpenTasks").textContent = openTasks;
      document.getElementById("statKnowledge").textContent = data.knowledge_count || 0;
      document.getElementById("statEmbedding").textContent = (data.embedding_coverage || 0) + "%";
      document.getElementById("hqProjectCount").textContent = activeCount;
      document.getElementById("hqTaskCount").textContent = openTasks;

      // Activity feed
      var actEl = document.getElementById("overviewActivity");
      if (data.activity && data.activity.length) {
        var typeIcons = {
          project_created: "folder-plus",
          task_created: "plus-circle",
          status_change: "arrow-right-circle",
          task_completed: "check-circle",
          decision: "gavel",
        };
        actEl.innerHTML = data.activity
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
          .join("");
      } else {
        actEl.innerHTML = '<div class="devhq-empty">No recent activity</div>';
      }

      // Active projects mini-list
      var projEl = document.getElementById("overviewProjects");
      if (data.active_projects && data.active_projects.length) {
        projEl.innerHTML = data.active_projects
          .slice(0, 8)
          .map(function (p) {
            var pct = p.total_tasks > 0 ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;
            return (
              '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--archie-border-default);cursor:pointer;" onclick="switchDevHQTab(\'projects\')">' +
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
          .join("");
      } else {
        projEl.innerHTML = '<div class="devhq-empty">No active projects</div>';
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
    var grid = document.getElementById("projectsGrid");

    api("/api/projects?" + params.toString())
      .then(function (data) {
        if (!data.success || !data.projects.length) {
          grid.innerHTML = '<div class="devhq-empty">No projects found</div>';
          return;
        }
        grid.innerHTML = data.projects.map(createProjectCard).join("");
        refreshIcons();
      })
      .catch(function () {
        grid.innerHTML = '<div class="devhq-empty">Error loading projects</div>';
      });
  }

  function createProjectCard(p) {
    var pct = p.total_tasks > 0 ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;
    return (
      '<div class="devhq-project-card">' +
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
      '<div style="display:flex;gap:6px;">' +
      '<button class="devhq-btn small primary" onclick="openProjectModal(' + p.id + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
      '<button class="devhq-btn small danger" onclick="deleteProject(' + p.id + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
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
        loadProjects();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  /* ========================================================================
     TASKS TAB
     ======================================================================== */
  function loadAllTasks() {
    var status = document.getElementById("taskFilterStatus").value;
    var priority = document.getElementById("taskFilterPriority").value;
    var projectId = document.getElementById("taskFilterProject").value;
    var search = document.getElementById("taskFilterSearch").value;
    var params = new URLSearchParams();
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    if (projectId) params.set("project_id", projectId);
    if (search) params.set("search", search);
    params.set("limit", _taskState.limit);
    params.set("offset", _taskState.page * _taskState.limit);

    api("/api/tasks?" + params.toString())
      .then(function (data) {
        if (!data.success) {
          document.getElementById("tasksContainer").innerHTML = '<div class="devhq-empty">Error loading tasks</div>';
          return;
        }
        _taskState.total = data.total;

        // Populate project filter dropdown (once)
        if (data.projects) {
          var sel = document.getElementById("taskFilterProject");
          if (sel.options.length <= 1) {
            data.projects.forEach(function (p) {
              var opt = document.createElement("option");
              opt.value = p.id;
              opt.textContent = p.name;
              sel.appendChild(opt);
            });
          }
        }
        renderTasks(data.tasks, data.total);
      })
      .catch(function () {
        document.getElementById("tasksContainer").innerHTML = '<div class="devhq-empty">Error loading tasks</div>';
      });
  }

  function renderTasks(tasks, total) {
    var container = document.getElementById("tasksContainer");
    if (!tasks.length) {
      container.innerHTML = '<div class="devhq-empty">No tasks found</div>';
      document.getElementById("tasksPagination").style.display = "none";
      return;
    }

    var isMobile = window.innerWidth <= 768;
    var html = "";

    if (!isMobile) {
      html += '<div class="devhq-task-table-header"><div>Status</div><div>Title</div><div>Project</div><div>Priority</div><div>Due Date</div><div>Actions</div></div>';
      html += tasks.map(function (t) {
        return (
          '<div class="devhq-task-table-row">' +
          '<div><span class="devhq-badge ' + escHtml(t.status) + '" style="cursor:pointer;" onclick="cycleTaskStatus(' + t.id + ",'" + escHtml(t.status) + "')\">" + escHtml(t.status) + "</span></div>" +
          '<div style="color:var(--archie-text-primary);">' + escHtml(t.title) + "</div>" +
          '<div style="font-size:0.7rem;color:var(--archie-text-muted);">' + escHtml(t.project_name || "\u2014") + "</div>" +
          '<div><span class="devhq-badge ' + escHtml(t.priority) + '">' + escHtml(t.priority) + "</span></div>" +
          '<div style="font-size:0.7rem;color:var(--archie-text-muted);">' + escHtml(formatDate(t.due_date)) + "</div>" +
          '<div style="display:flex;gap:4px;">' +
          '<button class="devhq-btn small primary" onclick="openTaskModal(' + t.id + ')"><i data-lucide="pencil" style="width:12px;height:12px;"></i></button>' +
          '<button class="devhq-btn small danger" onclick="deleteTask(' + t.id + ')"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>' +
          "</div></div>"
        );
      }).join("");
    } else {
      html += tasks.map(function (t) {
        return (
          '<div class="devhq-task-card" onclick="openTaskModal(' + t.id + ')">' +
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">' +
          '<span class="devhq-badge ' + escHtml(t.status) + '">' + escHtml(t.status) + "</span>" +
          '<span class="devhq-badge ' + escHtml(t.priority) + '">' + escHtml(t.priority) + "</span>" +
          "</div>" +
          '<div style="font-size:0.78rem;color:var(--archie-text-primary);margin-bottom:4px;">' + escHtml(t.title) + "</div>" +
          '<div style="font-size:0.65rem;color:var(--archie-text-muted);">' + escHtml(t.project_name || "No project") + " \u00B7 Due " + escHtml(formatDate(t.due_date)) + "</div>" +
          "</div>"
        );
      }).join("");
    }

    container.innerHTML = html;

    var totalPages = Math.ceil(total / _taskState.limit);
    var pag = document.getElementById("tasksPagination");
    if (totalPages > 1) {
      pag.style.display = "flex";
      document.getElementById("tasksPageInfo").textContent = "Page " + (_taskState.page + 1) + " of " + totalPages;
      document.getElementById("tasksPrev").disabled = _taskState.page === 0;
      document.getElementById("tasksNext").disabled = _taskState.page >= totalPages - 1;
    } else {
      pag.style.display = "none";
    }
    refreshIcons();
  }

  function taskPage(dir) {
    _taskState.page += dir;
    if (_taskState.page < 0) _taskState.page = 0;
    _cache.tasks = false;
    loadAllTasks();
  }

  function cycleTaskStatus(id, currentStatus) {
    var cycle = { pending: "in_progress", in_progress: "completed", completed: "pending" };
    var next = cycle[currentStatus] || "pending";
    api("/api/tasks/" + id, { method: "PUT", body: { status: next } })
      .then(function () {
        _cache.tasks = false;
        _cache.overview = false;
        loadAllTasks();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  function openTaskModal(taskId) {
    document.getElementById("taskEditId").value = "";
    document.getElementById("taskProjectId").value = "";
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
      });
    }

    if (taskId && typeof taskId === "number") {
      api("/api/tasks?limit=200").then(function (data) {
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
      _cache.tasks = false;
      _cache.overview = false;
      loadAllTasks();
    }).catch(function (err) {
      alert("Error: " + err.message);
    });
  }

  function deleteTask(id) {
    if (!confirm("Delete this task?")) return;
    api("/api/tasks/" + id, { method: "DELETE" })
      .then(function () {
        _cache.tasks = false;
        _cache.overview = false;
        loadAllTasks();
      })
      .catch(function (err) { alert("Error: " + err.message); });
  }

  /* ========================================================================
     KNOWLEDGE TAB
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
          document.getElementById("kbResults").innerHTML = '<div class="devhq-empty">Error loading knowledge</div>';
          return;
        }
        _kbState.total = data.total;

        // Populate category dropdown (once)
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
        document.getElementById("kbResults").innerHTML = '<div class="devhq-empty">Error loading knowledge</div>';
      });
  }

  function renderKnowledge(entries, total) {
    var container = document.getElementById("kbResults");
    if (!entries.length) {
      container.innerHTML = '<div class="devhq-empty">No entries found</div>';
      document.getElementById("kbPagination").style.display = "none";
      return;
    }

    container.innerHTML = '<div class="devhq-kb-list">' +
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
          '<div style="font-size:0.8rem;font-weight:500;color:var(--archie-text-primary);">' + escHtml(e.file_name || e.title || "Untitled") + "</div>" +
          '<span class="devhq-badge ' + escHtml(e.knowledge_type || "code") + '">' + escHtml(e.knowledge_type || "code") + "</span>" +
          "</div>" +
          '<div style="font-size:0.68rem;color:var(--archie-text-muted);margin-bottom:6px;">' +
          escHtml(e.primary_category || "uncategorized") + " \u00B7 Score: " + (e.importance_score || 0) + " \u00B7 " + escHtml(formatAge(e.updated_at)) +
          "</div>" +
          (tags ? '<div style="margin-bottom:6px;">' + tags + "</div>" : "") +
          (e.snippet ? '<div style="font-size:0.72rem;color:var(--archie-text-muted);max-height:50px;overflow:hidden;">' + escHtml(e.snippet.substring(0, 200)) + "</div>" : "") +
          '<div class="kb-detail-expand" style="display:none;margin-top:10px;"></div>' +
          "</div>"
        );
      }).join("") +
      "</div>";

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
    detail.innerHTML = '<div class="devhq-loading">Loading</div>';
    api("/api/knowledge/" + id).then(function (data) {
      if (!data.success) {
        detail.innerHTML = '<div class="devhq-empty">Error loading detail</div>';
        return;
      }
      detail.innerHTML = '<div class="devhq-pre">' + escHtml(data.entry.content || "No content") + "</div>";
    }).catch(function () {
      detail.innerHTML = '<div class="devhq-empty">Error loading detail</div>';
    });
  }

  function kbPage(dir) {
    _kbState.page += dir;
    if (_kbState.page < 0) _kbState.page = 0;
    _cache.knowledge = false;
    loadKnowledge();
  }

  function openKbModal() {
    document.getElementById("kbEditId").value = "";
    document.getElementById("kbTitle").value = "";
    document.getElementById("kbCategoryInput").value = "";
    document.getElementById("kbContent").value = "";
    document.getElementById("kbModalTitle").textContent = "New Document";
    document.getElementById("kbSubmitBtn").textContent = "Create";
    document.getElementById("kbModal").style.display = "flex";
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

  /* ========================================================================
     SCHEMA TAB
     ======================================================================== */
  function loadSchema() {
    api("/api/schema")
      .then(function (data) {
        if (!data.tables) {
          document.getElementById("schemaTableList").innerHTML = '<div class="devhq-empty">No schema data available</div>';
          return;
        }
        _schemaData = data.tables;
        renderSchemaList(_schemaData);
      })
      .catch(function () {
        document.getElementById("schemaTableList").innerHTML = '<div class="devhq-empty">Error loading schema</div>';
      });
  }

  function renderSchemaList(tables) {
    var list = document.getElementById("schemaTableList");
    if (!tables || !tables.length) {
      list.innerHTML = '<div class="devhq-empty">No tables</div>';
      return;
    }
    list.innerHTML = tables.map(function (t) {
      var name = typeof t === "string" ? t : (t.table_name || t.name);
      var count = t.row_count != null ? t.row_count : "";
      return (
        '<div class="devhq-table-item" onclick="showTableColumns(\'' + escHtml(name) + '\')">' +
        '<span style="font-family:var(--archie-font-mono);">' + escHtml(name) + "</span>" +
        (count !== "" ? '<span style="font-size:0.65rem;color:var(--archie-text-muted);">' + count + " rows</span>" : "") +
        "</div>"
      );
    }).join("");
  }

  function showTableColumns(tableName) {
    document.getElementById("schemaDetailHeader").textContent = tableName;
    document.querySelectorAll(".devhq-table-item").forEach(function (el) {
      el.classList.toggle("selected", el.textContent.trim().startsWith(tableName));
    });

    var table = _schemaData ? _schemaData.find(function (t) { return (t.table_name || t.name) === tableName; }) : null;
    var detail = document.getElementById("schemaDetail");
    if (!table || !table.columns) {
      detail.innerHTML = '<div class="devhq-empty">No column info available</div>';
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

    detail.innerHTML = html;
  }

  /* ========================================================================
     API DOCS TAB
     ======================================================================== */
  function loadApiDocs() {
    api("/api/docs")
      .then(function (data) {
        if (!data.endpoints && !data.blueprints) {
          document.getElementById("apiDocsContainer").innerHTML = '<div class="devhq-empty">No API documentation available</div>';
          return;
        }
        _apiData = data;
        renderApiDocs(data);
      })
      .catch(function () {
        document.getElementById("apiDocsContainer").innerHTML = '<div class="devhq-empty">Error loading API docs</div>';
      });
  }

  function renderApiDocs(data) {
    var container = document.getElementById("apiDocsContainer");
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

    container.innerHTML = html || '<div class="devhq-empty">No endpoints match your search</div>';
    refreshIcons();
  }

  /* ========================================================================
     INTEGRATIONS TAB
     ======================================================================== */
  function loadIntegrations() {
    Promise.all([
      api("/api/integrations/health").catch(function () { return { success: false }; }),
      api("/api/integrations/mcp").catch(function () { return { success: false }; }),
      api("/api/integrations/claude").catch(function () { return { success: false }; }),
    ]).then(function (results) {
      var healthData = results[0];
      var mcpData = results[1];
      var claudeData = results[2];

      // Health cards
      var grid = document.getElementById("integrationsGrid");
      if (healthData.success && healthData.services) {
        grid.innerHTML = Object.keys(healthData.services).map(function (key) {
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
        }).join("");
      } else {
        grid.innerHTML = '<div class="devhq-empty">Could not load health status</div>';
      }

      // MCP Tool Registry
      var mcpEl = document.getElementById("mcpToolRegistry");
      if (mcpData.success && mcpData.mcp_tools_db && mcpData.mcp_tools_db.length) {
        var toolsByCat = {};
        mcpData.mcp_tools_db.forEach(function (tool) {
          var cat = tool.category || "uncategorized";
          if (!toolsByCat[cat]) toolsByCat[cat] = [];
          toolsByCat[cat].push(tool);
        });
        var mcpHtml = "";
        Object.keys(toolsByCat).sort().forEach(function (cat) {
          var tools = toolsByCat[cat];
          mcpHtml +=
            '<div style="margin-bottom:12px;">' +
            '<div style="font-size:0.72rem;font-weight:600;color:var(--archie-orange);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;cursor:pointer;" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">' +
            escHtml(cat) + " (" + tools.length + ")</div><div>";
          tools.forEach(function (t) {
            mcpHtml +=
              '<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;font-size:0.72rem;">' +
              '<span style="color:' + (t.enabled ? "var(--archie-green)" : "var(--archie-text-muted)") + ';">\u25CF</span>' +
              '<span style="color:var(--archie-text-primary);">' + escHtml(t.name) + "</span>" +
              '<span style="font-size:0.65rem;color:var(--archie-text-muted);margin-left:auto;">' + escHtml((t.description || "").substring(0, 60)) + "</span>" +
              "</div>";
          });
          mcpHtml += "</div></div>";
        });
        mcpEl.innerHTML = mcpHtml;
      } else {
        mcpEl.innerHTML = '<div class="devhq-empty">No MCP tools registered</div>';
      }

      // Claude Config
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
        claudeEl.innerHTML = cHtml || '<div class="devhq-empty">No Claude config found</div>';
      } else {
        claudeEl.innerHTML = '<div class="devhq-empty">Could not load Claude config</div>';
      }

      refreshIcons();
    });
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
     EXPOSE GLOBALS (onclick handlers referenced in HTML)
     ======================================================================== */
  window.switchDevHQTab = switchDevHQTab;
  window.openProjectModal = openProjectModal;
  window.submitProject = submitProject;
  window.deleteProject = deleteProject;
  window.closeModal = closeModal;
  window.openTaskModal = openTaskModal;
  window.submitTask = submitTask;
  window.deleteTask = deleteTask;
  window.cycleTaskStatus = cycleTaskStatus;
  window.taskPage = taskPage;
  window.openKbModal = openKbModal;
  window.submitKb = submitKb;
  window.kbPage = kbPage;
  window.showTableColumns = showTableColumns;
  window.toggleKbDetail = toggleKbDetail;

  /* ========================================================================
     INIT
     ======================================================================== */
  document.addEventListener("DOMContentLoaded", function () {
    refreshIcons();
    updateClock();
    setInterval(updateClock, 1000);

    // Hash deep-linking
    var hash = window.location.hash.replace("#", "");
    var validTabs = ["overview", "projects", "tasks", "knowledge", "schema", "api", "integrations"];
    if (hash && validTabs.indexOf(hash) !== -1) {
      switchDevHQTab(hash);
    } else {
      loadTabData("overview");
    }

    // Filter event listeners
    var debounceTimer;
    function debounceReload(tabName, fn) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        _cache[tabName] = false;
        fn();
      }, 300);
    }

    // Projects filters
    document.getElementById("projFilterStatus").addEventListener("change", function () { _cache.projects = false; loadProjects(); });
    document.getElementById("projFilterPriority").addEventListener("change", function () { _cache.projects = false; loadProjects(); });
    document.getElementById("projFilterSearch").addEventListener("input", function () { debounceReload("projects", loadProjects); });

    // Tasks filters
    document.getElementById("taskFilterStatus").addEventListener("change", function () { _taskState.page = 0; _cache.tasks = false; loadAllTasks(); });
    document.getElementById("taskFilterPriority").addEventListener("change", function () { _taskState.page = 0; _cache.tasks = false; loadAllTasks(); });
    document.getElementById("taskFilterProject").addEventListener("change", function () { _taskState.page = 0; _cache.tasks = false; loadAllTasks(); });
    document.getElementById("taskFilterSearch").addEventListener("input", function () { _taskState.page = 0; debounceReload("tasks", loadAllTasks); });

    // Knowledge filters
    document.getElementById("kbSearch").addEventListener("input", function () { _kbState.page = 0; debounceReload("knowledge", loadKnowledge); });
    document.getElementById("kbTypeFilter").addEventListener("change", function () { _kbState.page = 0; _cache.knowledge = false; loadKnowledge(); });
    document.getElementById("kbCategory").addEventListener("change", function () { _kbState.page = 0; _cache.knowledge = false; loadKnowledge(); });

    // Schema search
    document.getElementById("schemaSearch").addEventListener("input", function () {
      if (!_schemaData) return;
      var q = this.value.toLowerCase();
      var filtered = q
        ? _schemaData.filter(function (t) { return (t.table_name || t.name || "").toLowerCase().indexOf(q) !== -1; })
        : _schemaData;
      renderSchemaList(filtered);
    });

    // API search
    document.getElementById("apiSearch").addEventListener("input", function () {
      if (!_apiData) return;
      renderApiDocs(_apiData);
    });
  });
})();
