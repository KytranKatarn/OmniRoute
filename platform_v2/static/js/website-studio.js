/**
 * website-studio.js
 * Website Designer — Phase 1 Builder Core
 * Tasks 3, 4, 5: Dashboard, Project CRUD + File Tree, Monaco + Tabs,
 *                Live Preview, AI Chat, Properties
 */
(function () {
  "use strict";

  // ═══════════════════════════════════════════════════════════════
  // SECTION 1: STATE + HELPERS
  // ═══════════════════════════════════════════════════════════════

  const API_BASE = "/tools/website-studio";

  // Application state
  let _currentProjectId = null;
  let _currentProject = null;
  let _pages = [];
  let _pageMap = {}; // pageId -> page object
  let _openTabs = []; // [{pageId, fileType, dirty}]
  let _activeTab = null; // {pageId, fileType}
  let _monacoEditor = null;
  let _models = {}; // "pageId_fileType" -> monaco model
  let _editorView = "editor"; // "editor" | "split" | "preview"
  let _viewport = "desktop";
  let _autoRefresh = true;
  let _aiHistory = [];
  let _refreshTimer = null;
  let _projects = [];

  // ── Utility: clear all children ─────────────────────────────
  function clearEl(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  // ── API helper ───────────────────────────────────────────────
  async function api(method, path, body) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(API_BASE + path, opts);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || res.statusText);
    }
    return res.json();
  }

  // ── Toast ────────────────────────────────────────────────────
  let _toastTimer = null;
  function toast(msg) {
    const el = document.getElementById("wsToast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("ws-toast-visible");
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => {
      el.classList.remove("ws-toast-visible");
    }, 2800);
  }

  // ── Modal helpers ────────────────────────────────────────────
  window.openNewProjectModal = function () {
    const el = document.getElementById("wsNewProjectModal");
    if (el) el.style.display = "flex";
    const nameEl = document.getElementById("wsNewProjectName");
    if (nameEl) {
      nameEl.value = "";
      nameEl.focus();
    }
    const descEl = document.getElementById("wsNewProjectDesc");
    if (descEl) descEl.value = "";
  };

  window.openNewFileModal = function () {
    if (!_currentProjectId) {
      toast("Open a project first.");
      return;
    }
    const el = document.getElementById("wsNewFileModal");
    if (el) el.style.display = "flex";
    const nameEl = document.getElementById("wsNewFileName");
    if (nameEl) {
      nameEl.value = "";
      nameEl.focus();
    }
  };

  window.closeModal = function (id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  };

  // Convenience aliases used from HTML onclick attrs
  window.closeNewProjectModal = function () {
    window.closeModal("wsNewProjectModal");
  };
  window.closeNewFileModal = function () {
    window.closeModal("wsNewFileModal");
  };

  // ── View toggle (called from toolbar) ───────────────────────
  window.setView = window.setEditorView = function (view) {
    _editorView = view;
    setEditorViewInternal(view);
  };

  // ═══════════════════════════════════════════════════════════════
  // SECTION 2: DASHBOARD
  // ═══════════════════════════════════════════════════════════════

  async function loadDashboard() {
    document.getElementById("wsDashboard").style.display = "";
    document.getElementById("wsBuilder").style.display = "none";

    // Show loading state for projects
    const projectGrid = document.getElementById("wsProjectGrid");
    if (projectGrid) {
      clearEl(projectGrid);
      const loader = document.createElement("div");
      loader.className = "ws-loading-indicator";
      loader.textContent = "Loading projects...";
      projectGrid.appendChild(loader);
    }

    // Show loading state for templates
    const templateGrid = document.getElementById("wsTemplateGrid");
    if (templateGrid) {
      clearEl(templateGrid);
      const loader = document.createElement("div");
      loader.className = "ws-loading-indicator";
      loader.textContent = "Loading templates...";
      templateGrid.appendChild(loader);
    }

    // Load projects
    try {
      const data = await api("GET", "/api/projects");
      _projects = data.projects || [];
      renderProjectCards(_projects);
    } catch (e) {
      console.error("Failed to load projects:", e);
      if (projectGrid) {
        clearEl(projectGrid);
        const err = document.createElement("div");
        err.className = "ws-error-message";
        err.textContent = "Failed to load projects. Please refresh the page.";
        projectGrid.appendChild(err);
      }
    }

    // Load templates
    try {
      const data = await api("GET", "/api/templates");
      renderTemplateCards(data);
    } catch (e) {
      console.error("Failed to load templates:", e);
      if (templateGrid) {
        clearEl(templateGrid);
        const err = document.createElement("div");
        err.className = "ws-error-message";
        err.textContent = "Failed to load templates.";
        templateGrid.appendChild(err);
      }
    }
  }

  function renderProjectCards(projects) {
    const grid = document.getElementById("wsProjectGrid");
    if (!grid) return;

    clearEl(grid);

    // Empty state when no projects exist
    if (!projects || projects.length === 0) {
      const empty = document.createElement("div");
      empty.className = "ws-empty-state";

      const icon = document.createElement("div");
      icon.className = "ws-empty-state-icon";
      icon.textContent = "\uD83C\uDF10";
      empty.appendChild(icon);

      const title = document.createElement("div");
      title.className = "ws-empty-state-title";
      title.textContent = "No websites yet";
      empty.appendChild(title);

      const text = document.createElement("div");
      text.className = "ws-empty-state-text";
      text.textContent = "Create your first website to get started with the AI-powered designer.";
      empty.appendChild(text);

      const btn = document.createElement("button");
      btn.className = "ws-toolbar-btn ws-deploy-btn ws-empty-state-btn";
      btn.textContent = "+ Create Your First Website";
      btn.addEventListener("click", window.openNewProjectModal);
      empty.appendChild(btn);

      grid.appendChild(empty);
      return;
    }

    const newCard = document.createElement("div");
    newCard.className = "ws-project-card ws-new-project-card";
    newCard.textContent = "+ New Project";
    newCard.addEventListener("click", window.openNewProjectModal);
    grid.appendChild(newCard);

    projects.forEach((proj) => {
      const card = document.createElement("div");
      card.className = "ws-project-card";

      const title = document.createElement("div");
      title.className = "ws-project-card-title";
      title.textContent = proj.name || "Untitled";
      card.appendChild(title);

      if (proj.description) {
        const desc = document.createElement("div");
        desc.className = "ws-project-card-desc";
        desc.textContent = proj.description;
        card.appendChild(desc);
      }

      const meta = document.createElement("div");
      meta.className = "ws-project-card-meta";
      const pageCount = proj.page_count !== undefined ? proj.page_count : "";
      meta.textContent = pageCount !== "" ? pageCount + " page(s)" : "";
      card.appendChild(meta);

      card.addEventListener("click", () => openProject(proj.id));
      grid.appendChild(card);
    });
  }

  function renderTemplateCards(data) {
    const grid = document.getElementById("wsTemplateGrid");
    if (!grid) return;
    clearEl(grid);

    // Handle both {templates: {category: [items]}} and {templates: [...]}
    let templates = data.templates || data;

    // Check if templates is empty
    let isEmpty = false;
    if (Array.isArray(templates)) {
      isEmpty = templates.length === 0;
    } else if (typeof templates === "object" && templates !== null) {
      isEmpty = Object.keys(templates).length === 0;
    } else {
      isEmpty = true;
    }

    if (isEmpty) {
      const empty = document.createElement("div");
      empty.className = "ws-empty-state ws-empty-state-small";
      empty.textContent = "No templates available yet. Start with a blank project.";
      grid.appendChild(empty);
      return;
    }

    if (Array.isArray(templates)) {
      templates.forEach((tpl) => {
        grid.appendChild(buildTemplateCard(tpl, null));
      });
    } else if (typeof templates === "object" && templates !== null) {
      Object.entries(templates).forEach(([category, items]) => {
        if (!Array.isArray(items)) return;
        items.forEach((tpl) => {
          grid.appendChild(buildTemplateCard(tpl, category));
        });
      });
    }
  }

  function buildTemplateCard(tpl, category) {
    const card = document.createElement("div");
    card.className = "ws-template-card";

    const title = document.createElement("div");
    title.className = "ws-template-card-title";
    title.textContent = tpl.name || tpl.id || "Template";
    card.appendChild(title);

    if (tpl.description) {
      const desc = document.createElement("div");
      desc.className = "ws-template-card-desc";
      desc.textContent = tpl.description;
      card.appendChild(desc);
    }

    if (category) {
      const cat = document.createElement("div");
      cat.className = "ws-template-card-category";
      cat.textContent = category;
      card.appendChild(cat);
    }

    const btn = document.createElement("button");
    btn.className = "ws-btn ws-btn-sm ws-btn-primary";
    btn.textContent = "Use Template";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      applyTemplate(tpl, category);
    });
    card.appendChild(btn);

    return card;
  }

  async function applyTemplate(tpl, category) {
    const name = prompt("Project name:", tpl.name || "My Website");
    if (!name) return;

    try {
      toast("Creating project...");
      const createData = await api("POST", "/api/projects", {
        name,
        description: tpl.description || "",
        template_type: tpl.id || "blank",
      });
      const projectId = createData.project.id;

      toast("Applying template...");
      await api("POST", "/api/projects/" + projectId + "/apply-template", {
        template_id: tpl.id,
        category: category || tpl.category || "",
      });

      toast("Template applied!");
      await openProject(projectId);
    } catch (e) {
      toast("Error: " + e.message);
      console.error(e);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  // SECTION 3: PROJECT CRUD + FILE TREE
  // ═══════════════════════════════════════════════════════════════

  window.createProject = async function () {
    const nameEl = document.getElementById("wsNewProjectName");
    const descEl = document.getElementById("wsNewProjectDesc");
    const name = nameEl ? nameEl.value.trim() : "";
    if (!name) {
      toast("Please enter a project name.");
      return;
    }
    const description = descEl ? descEl.value.trim() : "";

    try {
      window.closeModal("wsNewProjectModal");
      toast("Creating project...");
      const data = await api("POST", "/api/projects", { name, description });
      _projects.push(data.project);
      await openProject(data.project.id);
    } catch (e) {
      toast("Error: " + e.message);
      console.error(e);
    }
  };

  async function openProject(projectId) {
    try {
      _currentProjectId = projectId;

      // Hide dashboard, show builder
      document.getElementById("wsDashboard").style.display = "none";
      document.getElementById("wsBuilder").style.display = "";

      // Show loading overlay
      toast("Loading project...");

      // Load project details
      const projData = await api("GET", "/api/projects/" + projectId);
      _currentProject = projData.project;

      // Load pages
      const pagesData = await api("GET", "/api/projects/" + projectId + "/pages");
      _pages = pagesData.pages || [];
      _pageMap = {};
      _pages.forEach((p) => {
        _pageMap[p.id] = p;
      });

      // Clear tabs + models from previous project
      _openTabs = [];
      _activeTab = null;
      Object.values(_models).forEach((m) => {
        try { m.dispose(); } catch (_) {}
      });
      _models = {};

      // Refresh projects list in selector if needed
      if (_projects.length === 0) {
        try {
          const all = await api("GET", "/api/projects");
          _projects = all.projects || [];
        } catch (_) {}
      }
      updateProjectSelector();
      renderFileTree();
      renderTabs();

      // Auto-open first page HTML
      if (_pages.length > 0) {
        openFile(_pages[0].id, "html");
      }

      toast("Opened: " + (_currentProject.name || "Project"));
      loadChatHistory(projectId);
    } catch (e) {
      toast("Failed to open project: " + e.message);
      console.error(e);
    }
  }

  window.switchProject = async function (id) {
    if (!id) return;
    await openProject(parseInt(id, 10));
  };

  function updateProjectSelector() {
    const sel = document.getElementById("wsProjectSelect");
    if (!sel) return;
    clearEl(sel);
    _projects.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name || "Untitled";
      if (p.id === _currentProjectId) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.onchange = function () {
      window.switchProject(this.value);
    };
  }

  function renderFileTree() {
    const tree = document.getElementById("wsFileTree");
    if (!tree) return;
    clearEl(tree);

    _pages.forEach((page) => {
      // Folder item (page name)
      const folder = document.createElement("div");
      folder.className = "ws-tree-folder";

      const folderIcon = document.createElement("span");
      folderIcon.className = "ws-tree-icon";
      folderIcon.textContent = "\uD83D\uDCC1"; // folder emoji
      folder.appendChild(folderIcon);

      const folderName = document.createElement("span");
      folderName.className = "ws-tree-folder-name";
      folderName.textContent = page.name || "Untitled";
      folder.appendChild(folderName);

      tree.appendChild(folder);

      // HTML, CSS, JS file entries
      tree.appendChild(buildTreeFileItem(page, "html", "\uD83D\uDFE7", ".html"));
      tree.appendChild(buildTreeFileItem(page, "css", "\uD83D\uDFE6", ".css"));
      tree.appendChild(buildTreeFileItem(page, "js", "\uD83D\uDFE8", ".js"));
    });
  }

  function buildTreeFileItem(page, fileType, iconChar, ext) {
    const item = document.createElement("div");
    item.className = "ws-tree-file";
    item.dataset.pageId = page.id;
    item.dataset.fileType = fileType;

    const icon = document.createElement("span");
    icon.className = "ws-tree-icon";
    icon.textContent = iconChar;
    item.appendChild(icon);

    const label = document.createElement("span");
    label.className = "ws-tree-file-name";
    label.textContent = (page.slug || page.name || "page").replace(/^\//, "") + ext;
    item.appendChild(label);

    item.addEventListener("click", () => openFile(page.id, fileType));
    return item;
  }

  window.createFile = async function () {
    const nameEl = document.getElementById("wsNewFileName");
    const rawName = nameEl ? nameEl.value.trim() : "";
    if (!rawName || !_currentProjectId) {
      toast("Please enter a file name.");
      return;
    }

    const slug = rawName
      .replace(/\.(html|css|js)$/i, "")
      .replace(/\s+/g, "-")
      .toLowerCase();
    const name = slug;

    const defaultHtml =
      "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n" +
      "  <meta charset=\"UTF-8\">\n" +
      "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n" +
      "  <title>" + name + "</title>\n" +
      "  <link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n\n" +
      "  <script src=\"script.js\"><\\/script>\n</body>\n</html>";

    try {
      window.closeModal("wsNewFileModal");
      const data = await api("POST", "/api/projects/" + _currentProjectId + "/pages", {
        name,
        slug: "/" + slug,
        html_content: defaultHtml,
        css_content: "/* Styles for " + name + " */\n",
        js_content: "// Scripts for " + name + "\n",
      });
      const page = data.page;
      _pages.push(page);
      _pageMap[page.id] = page;
      renderFileTree();
      openFile(page.id, "html");
      toast("Created: " + name);
    } catch (e) {
      toast("Error: " + e.message);
      console.error(e);
    }
  };

  // ═══════════════════════════════════════════════════════════════
  // SECTION 4: MONACO INIT + TABS
  // ═══════════════════════════════════════════════════════════════

  function initMonaco(callback) {
    if (typeof require === "undefined") {
      console.error("Monaco AMD loader not found.");
      return;
    }
    require.config({
      paths: {
        vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs",
      },
    });
    require(["vs/editor/editor.main"], function () {
      const container = document.getElementById("wsEditorContainer");
      if (!container) return;

      _monacoEditor = monaco.editor.create(container, {
        value: "",
        language: "html",
        theme: "vs-dark",
        fontSize: 14,
        minimap: { enabled: false },
        automaticLayout: false,
        wordWrap: "on",
        scrollBeyondLastLine: false,
        tabSize: 2,
      });

      // Ctrl+S to save
      _monacoEditor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
        function () {
          window.saveCurrentFile();
        }
      );

      // onChange: mark dirty + debounced preview refresh
      _monacoEditor.onDidChangeModelContent(function () {
        if (_activeTab) {
          markTabDirty(_activeTab.pageId, _activeTab.fileType);
        }
        if (_autoRefresh) {
          debounceRefresh();
        }
      });

      if (callback) callback();
    });
  }

  function debounceRefresh() {
    clearTimeout(_refreshTimer);
    _refreshTimer = setTimeout(() => {
      window.refreshPreview();
    }, 500);
  }

  function openFile(pageId, fileType) {
    const page = _pageMap[pageId];
    if (!page) return;

    const key = pageId + "_" + fileType;

    // Create Monaco model if not exists
    if (!_models[key]) {
      let content = "";
      let language = fileType;
      if (fileType === "html") {
        content = page.html_content || "";
        language = "html";
      } else if (fileType === "css") {
        content = page.css_content || "";
        language = "css";
      } else if (fileType === "js") {
        content = page.js_content || "";
        language = "javascript";
      }
      _models[key] = monaco.editor.createModel(content, language);
    }

    // Add tab if not already open
    const existingTab = _openTabs.find(
      (t) => t.pageId === pageId && t.fileType === fileType
    );
    if (!existingTab) {
      _openTabs.push({ pageId, fileType, dirty: false });
    }

    // Set active tab
    _activeTab = { pageId, fileType };

    // Switch Monaco model
    if (_monacoEditor) {
      _monacoEditor.setModel(_models[key]);
    }

    renderTabs();
    updateFileTreeActive();
    updateProperties();
  }

  window.closeTab = function (pageId, fileType, event) {
    if (event) event.stopPropagation();

    const key = pageId + "_" + fileType;
    const tab = _openTabs.find(
      (t) => t.pageId === pageId && t.fileType === fileType
    );

    if (tab && tab.dirty) {
      if (!confirm("Discard unsaved changes?")) return;
    }

    // Dispose model
    if (_models[key]) {
      try { _models[key].dispose(); } catch (_) {}
      delete _models[key];
    }

    _openTabs = _openTabs.filter(
      (t) => !(t.pageId === pageId && t.fileType === fileType)
    );

    // Switch to another tab if this was the active one
    if (
      _activeTab &&
      _activeTab.pageId === pageId &&
      _activeTab.fileType === fileType
    ) {
      if (_openTabs.length > 0) {
        const next = _openTabs[_openTabs.length - 1];
        openFile(next.pageId, next.fileType);
      } else {
        _activeTab = null;
        if (_monacoEditor) {
          _monacoEditor.setModel(null);
        }
        renderTabs();
        updateFileTreeActive();
        updateProperties();
      }
    } else {
      renderTabs();
    }
  };

  function markTabDirty(pageId, fileType) {
    const tab = _openTabs.find(
      (t) => t.pageId === pageId && t.fileType === fileType
    );
    if (tab && !tab.dirty) {
      tab.dirty = true;
      renderTabs();
    }
  }

  function markTabClean(pageId, fileType) {
    const tab = _openTabs.find(
      (t) => t.pageId === pageId && t.fileType === fileType
    );
    if (tab) {
      tab.dirty = false;
      renderTabs();
    }
  }

  function renderTabs() {
    const bar = document.getElementById("wsTabs");
    if (!bar) return;
    clearEl(bar);

    _openTabs.forEach((tab) => {
      const page = _pageMap[tab.pageId];
      const pageName = page
        ? (page.slug || page.name || "page").replace(/^\//, "")
        : String(tab.pageId);
      const ext = tab.fileType === "js" ? ".js" : "." + tab.fileType;
      const isActive =
        _activeTab &&
        _activeTab.pageId === tab.pageId &&
        _activeTab.fileType === tab.fileType;

      const tabEl = document.createElement("div");
      tabEl.className = "ws-tab" + (isActive ? " ws-tab-active" : "");

      // Dirty indicator dot
      if (tab.dirty) {
        const dot = document.createElement("span");
        dot.className = "ws-tab-dirty";
        dot.textContent = "\u25CF"; // solid circle
        tabEl.appendChild(dot);
      }

      // Tab name
      const nameSpan = document.createElement("span");
      nameSpan.className = "ws-tab-name";
      nameSpan.textContent = pageName + ext;
      tabEl.appendChild(nameSpan);

      // Close button
      const closeSpan = document.createElement("span");
      closeSpan.className = "ws-tab-close";
      closeSpan.textContent = "\u00D7"; // times symbol
      closeSpan.addEventListener("click", (e) => {
        window.closeTab(tab.pageId, tab.fileType, e);
      });
      tabEl.appendChild(closeSpan);

      tabEl.addEventListener("click", () => {
        openFile(tab.pageId, tab.fileType);
      });

      bar.appendChild(tabEl);
    });
  }

  function updateFileTreeActive() {
    const allItems = document.querySelectorAll(".ws-tree-file");
    allItems.forEach((item) => {
      const pid = parseInt(item.dataset.pageId, 10);
      const ft = item.dataset.fileType;
      const isActive =
        _activeTab &&
        _activeTab.pageId === pid &&
        _activeTab.fileType === ft;
      item.classList.toggle("ws-tree-file-active", !!isActive);
    });
  }

  window.saveCurrentFile = async function () {
    if (!_activeTab) {
      toast("No file open.");
      return;
    }
    const { pageId, fileType } = _activeTab;
    const key = pageId + "_" + fileType;
    const model = _models[key];
    if (!model) return;

    const value = model.getValue();
    const body = {};
    if (fileType === "html") body.html_content = value;
    else if (fileType === "css") body.css_content = value;
    else if (fileType === "js") body.js_content = value;

    try {
      await api("PUT", "/api/pages/" + pageId, body);

      // Update local page cache
      if (_pageMap[pageId]) {
        if (fileType === "html") _pageMap[pageId].html_content = value;
        else if (fileType === "css") _pageMap[pageId].css_content = value;
        else if (fileType === "js") _pageMap[pageId].js_content = value;
      }

      markTabClean(pageId, fileType);
      toast("Saved.");
    } catch (e) {
      toast("Save failed: " + e.message);
      console.error(e);
    }
  };

  // ═══════════════════════════════════════════════════════════════
  // SECTION 5: EDITOR VIEW + SPLIT
  // ═══════════════════════════════════════════════════════════════

  function setEditorViewInternal(view) {
    _editorView = view;

    const editorContainer = document.getElementById("wsEditorContainer");
    const splitHandle = document.getElementById("wsSplitHandle");
    const previewContainer = document.getElementById("wsPreviewContainer");

    if (view === "editor") {
      if (editorContainer) {
        editorContainer.style.display = "";
        editorContainer.style.flex = "1";
        editorContainer.style.width = "";
      }
      if (splitHandle) splitHandle.style.display = "none";
      if (previewContainer) previewContainer.style.display = "none";
    } else if (view === "preview") {
      if (editorContainer) editorContainer.style.display = "none";
      if (splitHandle) splitHandle.style.display = "none";
      if (previewContainer) {
        previewContainer.style.display = "";
        previewContainer.style.flex = "1";
        previewContainer.style.width = "";
      }
      window.refreshPreview();
    } else {
      // split
      if (editorContainer) {
        editorContainer.style.display = "";
        editorContainer.style.flex = "1";
        editorContainer.style.width = "";
      }
      if (splitHandle) splitHandle.style.display = "";
      if (previewContainer) {
        previewContainer.style.display = "";
        previewContainer.style.flex = "1";
        previewContainer.style.width = "";
      }
      window.refreshPreview();
    }

    // Update active toolbar button
    document.querySelectorAll(".ws-view-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === view);
    });

    // Relayout Monaco after DOM settles
    if (_monacoEditor) {
      setTimeout(() => _monacoEditor.layout(), 50);
    }
  }

  function initSplitDrag() {
    const handle = document.getElementById("wsSplitHandle");
    const editorContainer = document.getElementById("wsEditorContainer");
    const previewContainer = document.getElementById("wsPreviewContainer");
    if (!handle || !editorContainer || !previewContainer) return;

    let dragging = false;
    let startX = 0;
    let startEditorW = 0;
    let startPreviewW = 0;

    handle.addEventListener("mousedown", (e) => {
      dragging = true;
      startX = e.clientX;
      startEditorW = editorContainer.offsetWidth;
      startPreviewW = previewContainer.offsetWidth;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const newEditorW = Math.max(100, startEditorW + dx);
      const newPreviewW = Math.max(100, startPreviewW - dx);
      editorContainer.style.flex = "none";
      editorContainer.style.width = newEditorW + "px";
      previewContainer.style.flex = "none";
      previewContainer.style.width = newPreviewW + "px";
      if (_monacoEditor) _monacoEditor.layout();
    });

    document.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    });
  }

  // ═══════════════════════════════════════════════════════════════
  // SECTION 6: LIVE PREVIEW
  // ═══════════════════════════════════════════════════════════════

  window.refreshPreview = function () {
    const iframe = document.getElementById("wsPreviewFrame");
    if (!iframe) return;

    if (!_activeTab) {
      iframe.srcdoc = "<html><body><p style='color:#888;font-family:sans-serif;padding:2rem;'>No file open.</p></body></html>";
      return;
    }

    const { pageId } = _activeTab;
    const page = _pageMap[pageId];
    if (!page) return;

    // Get content from open models first, then fall back to cached page content
    function getContent(ft) {
      const key = pageId + "_" + ft;
      if (_models[key]) return _models[key].getValue();
      if (ft === "html") return page.html_content || "";
      if (ft === "css") return page.css_content || "";
      if (ft === "js") return page.js_content || "";
      return "";
    }

    let html = getContent("html");
    const css = getContent("css");
    const js = getContent("js");

    // Inject CSS before </head>
    if (css.trim()) {
      const styleTag = "<style>\n" + css + "\n</style>";
      if (html.includes("</head>")) {
        html = html.replace("</head>", styleTag + "\n</head>");
      } else {
        html = styleTag + "\n" + html;
      }
    }

    // Inject JS before </body>
    if (js.trim()) {
      // Avoid closing the outer script tag by splitting the string literal
      const scriptTag = "<scr" + "ipt>\n" + js + "\n</" + "script>";
      if (html.includes("</body>")) {
        html = html.replace("</body>", scriptTag + "\n</body>");
      } else {
        html = html + "\n" + scriptTag;
      }
    }

    iframe.srcdoc = html;
  };

  window.setViewport = function (vp) {
    _viewport = vp;
    const container = document.getElementById("wsPreviewContainer");
    if (!container) return;
    container.classList.remove("ws-vp-desktop", "ws-vp-tablet", "ws-vp-mobile");
    container.classList.add("ws-vp-" + vp);

    document.querySelectorAll(".ws-viewport-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.vp === vp);
    });
  };

  // ═══════════════════════════════════════════════════════════════
  // SECTION 7: AI CHAT
  // ═══════════════════════════════════════════════════════════════

  // HTML uses sendAiMessage() per template onclick attrs
  window.sendAiMessage = window.sendAiChat = async function () {
    const input = document.getElementById("wsAiInput");
    const message = input ? input.value.trim() : "";
    if (!message) return;
    if (input) input.value = "";

    // Show history panel
    const historyEl = document.getElementById("wsAiHistory");
    if (historyEl) historyEl.style.display = "";

    addAiEntry("user", message);

    // Build context from current file
    let fileContent = "";
    let language = "html";
    if (_activeTab) {
      const key = _activeTab.pageId + "_" + _activeTab.fileType;
      if (_models[key]) fileContent = _models[key].getValue();
      language = _activeTab.fileType === "js" ? "javascript" : _activeTab.fileType;
    }

    try {
      const data = await api("POST", "/api/chat", {
        message,
        context: fileContent,
        language,
        project_id: _currentProjectId,
      });

      const reply = data.message || data.response || "";

      // Apply changes if backend signals them
      if (data.has_changes && data.changes && data.changes.length > 0) {
        const change = data.changes[0];
        if (change.new_content && _activeTab) {
          const key = _activeTab.pageId + "_" + _activeTab.fileType;
          if (_models[key]) {
            _models[key].setValue(change.new_content);
            toast("AI applied changes.");
          }
        }
      } else if (reply) {
        // Try to extract a code block from the reply text
        const codeMatch = reply.match(/```(?:\w+)?\n?([\s\S]*?)```/);
        if (codeMatch && _activeTab) {
          const extracted = codeMatch[1].trim();
          const key = _activeTab.pageId + "_" + _activeTab.fileType;
          if (_models[key] && extracted) {
            if (confirm("AI suggests code changes. Apply them?")) {
              _models[key].setValue(extracted);
              toast("AI changes applied.");
            }
          }
        }
      }

      addAiEntry("assistant", reply || "(No response)");
    } catch (e) {
      addAiEntry("assistant", "Error: " + e.message);
      toast("AI error: " + e.message);
      console.error(e);
    }
  };

  function addAiEntry(role, text) {
    _aiHistory.push({ role, text });

    const historyEl = document.getElementById("wsAiHistory");
    if (!historyEl) return;

    const entry = document.createElement("div");
    entry.className = "ws-ai-entry ws-ai-entry-" + role;

    const label = document.createElement("span");
    label.className = "ws-ai-label";
    label.textContent = role === "user" ? "You" : "AI";
    entry.appendChild(label);

    const content = document.createElement("div");
    content.className = "ws-ai-content";
    content.textContent = text;
    entry.appendChild(content);

    historyEl.appendChild(entry);
    historyEl.scrollTop = historyEl.scrollHeight;
  }

  // ═══════════════════════════════════════════════════════════════
  // SECTION 8: PROPERTIES + INIT
  // ═══════════════════════════════════════════════════════════════

  function updateProperties() {
    const fileContent = document.getElementById("wsPropFileContent");
    if (fileContent) {
      clearEl(fileContent);
      if (_activeTab) {
        const page = _pageMap[_activeTab.pageId];
        const ext = _activeTab.fileType === "js" ? ".js" : "." + _activeTab.fileType;
        const slug = page
          ? (page.slug || page.name || "page").replace(/^\//, "")
          : String(_activeTab.pageId);

        const nameRow = document.createElement("div");
        nameRow.className = "ws-prop-info-row";

        const nameLabel = document.createElement("span");
        nameLabel.className = "ws-prop-info-label";
        nameLabel.textContent = "File:";
        nameRow.appendChild(nameLabel);

        const nameVal = document.createElement("span");
        nameVal.className = "ws-prop-info-value";
        nameVal.textContent = slug + ext;
        nameRow.appendChild(nameVal);

        fileContent.appendChild(nameRow);

        const typeRow = document.createElement("div");
        typeRow.className = "ws-prop-info-row";

        const typeLabel = document.createElement("span");
        typeLabel.className = "ws-prop-info-label";
        typeLabel.textContent = "Type:";
        typeRow.appendChild(typeLabel);

        const typeVal = document.createElement("span");
        typeVal.className = "ws-prop-info-value";
        typeVal.textContent = _activeTab.fileType.toUpperCase();
        typeRow.appendChild(typeVal);

        fileContent.appendChild(typeRow);
      } else {
        const none = document.createElement("div");
        none.className = "ws-prop-empty";
        none.textContent = "No file open";
        fileContent.appendChild(none);
      }
    }

    // Populate page settings inputs if a tab is active
    if (_activeTab) {
      const page = _pageMap[_activeTab.pageId];
      if (page) {
        const titleEl = document.getElementById("wsPropPageTitle");
        const slugEl = document.getElementById("wsPropPageSlug");
        const descEl = document.getElementById("wsPropPageDesc");
        if (titleEl) titleEl.value = page.name || "";
        if (slugEl) slugEl.value = page.slug || "";
        if (descEl) descEl.value = page.meta_description || "";
      }
    }
  }

  window.toggleRightPanel = function () {
    const panel = document.getElementById("wsRightPanel");
    if (!panel) return;
    panel.classList.toggle("ws-right-collapsed");
    if (_monacoEditor) {
      setTimeout(() => _monacoEditor.layout(), 200);
    }
  };

  // ═══════════════════════════════════════════════════════════════
  // SECTION 9: PHASE 2 — Deploy + Hostinger + Chat Drawer
  // ═══════════════════════════════════════════════════════════════

  var _chatDrawerOpen = false;
  var _currentDomain = null;

  window.toggleChatDrawer = function () {
    _chatDrawerOpen = !_chatDrawerOpen;
    var drawer = document.getElementById("wsAiDrawer");
    if (drawer) drawer.style.display = _chatDrawerOpen ? "" : "none";
  };

  window.openDeployPanel = function () {
    document.getElementById("wsDeployPanel").style.display = "flex";
    loadDeployHistory();
    loadHostingerDomains();
  };

  window.closeDeployPanel = function () {
    document.getElementById("wsDeployPanel").style.display = "none";
  };

  window.deployToGitHub = function () {
    var status = document.getElementById("wsDeployStatus");
    status.textContent = "Deploying...";
    api("POST", "/api/projects/" + _currentProjectId + "/deploy", {
      deployment_type: "github_pages",
    }).then(function (data) {
      if (data.success || data.deployment_url) {
        status.textContent = "Deployed! " + (data.deployment_url || "");
        toast("Deployed to GitHub Pages");
        loadDeployHistory();
      } else {
        status.textContent = "Error: " + (data.error || "Deploy failed");
      }
    });
  };

  function loadDeployHistory() {
    if (!_currentProjectId) return;
    api("GET", "/api/projects/" + _currentProjectId + "/deployments").then(
      function (data) {
        var container = document.getElementById("wsDeployHistory");
        clearEl(container);
        var deps = data.deployments || data || [];
        if (!Array.isArray(deps)) return;
        deps.slice(0, 5).forEach(function (d) {
          var row = document.createElement("div");
          row.className = "ws-prop-row";
          var left = document.createElement("span");
          left.className = "ws-prop-label";
          left.textContent =
            (d.status || "?") +
            " — " +
            (d.created_at || "").split("T")[0];
          var right = document.createElement("span");
          right.className = "ws-prop-value";
          right.textContent = d.commit_hash
            ? d.commit_hash.substring(0, 7)
            : "";
          row.appendChild(left);
          row.appendChild(right);
          container.appendChild(row);
        });
      }
    );
  }

  window.loadHostingerDomains = function () {
    api("GET", "/api/hostinger/status").then(function (data) {
      if (data.error) {
        document.getElementById("wsHostingerSection").style.display = "none";
        return;
      }
      var banner = document.getElementById("wsHostingerMockBanner");
      if (banner)
        banner.style.display = data.mock || !data.configured ? "" : "none";
    });
    api("GET", "/api/hostinger/domains").then(function (data) {
      var container = document.getElementById("wsHostingerDomains");
      clearEl(container);
      var domains = data.domains || [];
      domains.forEach(function (d) {
        var row = document.createElement("div");
        row.className = "ws-tree-item";
        row.textContent = d.domain + " (" + (d.status || "active") + ")";
        row.onclick = function () {
          loadDnsRecords(d.domain);
        };
        container.appendChild(row);
      });
    });
  };

  window.loadDnsRecords = function (domain) {
    _currentDomain = domain;
    document.getElementById("wsDnsRecords").style.display = "";
    document.getElementById("wsDnsDomainTitle").textContent =
      "DNS: " + domain;
    api("GET", "/api/hostinger/domains/" + domain + "/dns").then(
      function (data) {
        var container = document.getElementById("wsDnsTable");
        clearEl(container);
        (data.records || []).forEach(function (r) {
          var row = document.createElement("div");
          row.className = "ws-prop-row";
          var left = document.createElement("span");
          left.className = "ws-prop-label";
          left.textContent = r.type + " " + r.name;
          var right = document.createElement("span");
          right.className = "ws-prop-value";
          right.textContent = r.content;
          row.appendChild(left);
          row.appendChild(right);
          container.appendChild(row);
        });
      }
    );
  };

  window.showAddDnsForm = function () {
    document.getElementById("wsAddDnsForm").style.display = "";
  };

  window.addDnsRecord = function () {
    if (!_currentDomain) return;
    api("POST", "/api/hostinger/domains/" + _currentDomain + "/dns", {
      type: document.getElementById("wsDnsType").value,
      name: document.getElementById("wsDnsName").value,
      value: document.getElementById("wsDnsContent").value,
      ttl: 3600,
    }).then(function (data) {
      if (data.error) {
        alert(data.error);
        return;
      }
      toast("DNS record added");
      document.getElementById("wsAddDnsForm").style.display = "none";
      loadDnsRecords(_currentDomain);
    });
  };

  window.applyGitHubPreset = function () {
    if (
      !_currentDomain ||
      !confirm(
        "Apply GitHub Pages DNS preset to " + _currentDomain + "?"
      )
    )
      return;
    api(
      "POST",
      "/api/hostinger/domains/" + _currentDomain + "/preset",
      { preset_type: "github_pages" }
    ).then(function (data) {
      if (data.error) {
        alert(data.error);
        return;
      }
      toast("GitHub Pages preset applied");
      loadDnsRecords(_currentDomain);
    });
  };

  window.loadChatHistory = function (projectId) {
    api("GET", "/api/chat/history/" + projectId).then(function (data) {
      var history = data.history || [];
      var container = document.getElementById("wsAiHistory");
      clearEl(container);
      history.forEach(function (entry) {
        addAiEntry(
          entry.role === "user" ? "user" : "assistant",
          entry.message
        );
      });
    });
  };

  // ── DOMContentLoaded ─────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {
    // Auto-refresh checkbox
    const arCb = document.getElementById("wsAutoRefresh");
    if (arCb) {
      _autoRefresh = arCb.checked;
      arCb.addEventListener("change", function () {
        _autoRefresh = this.checked;
      });
    }

    // Init split drag handle
    initSplitDrag();

    // Init Monaco, then load dashboard
    initMonaco(function () {
      loadDashboard();
    });
  });
})();
