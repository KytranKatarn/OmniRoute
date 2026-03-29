/**
 * CodeMode — Main orchestrator for the full-screen code editor experience.
 * Coordinates MonacoSetup, FileTree, LivePreview, and AIChatOverlay.
 */
const CodeMode = (() => {
    let _projectId = null;
    let _container = null;

    // -------------------------------------------------------------------------
    // Public: enter
    // -------------------------------------------------------------------------
    async function enter(projectId) {
        _projectId = projectId;

        // 1. Notify server we're entering code mode
        try {
            await fetch(`/plugins/website-builder/api/projects/${projectId}/enter-code-mode`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
        } catch (e) {
            console.warn("CodeMode: enter-code-mode API call failed", e);
        }

        // 2. Load Monaco runtime
        await MonacoSetup.load();

        // 3. Grab container and show it
        _container = document.querySelector(".code-mode-container");
        if (!_container) {
            console.error("CodeMode: .code-mode-container not found in DOM");
            return;
        }
        _container.classList.add("active");

        // 4. Set project name in toolbar
        const nameEl = _container.querySelector(".cm-project-name");
        if (nameEl) {
            try {
                const r = await fetch(`/plugins/website-builder/api/projects/${projectId}`);
                const data = await r.json();
                nameEl.textContent = data.project ? data.project.name : `Project ${projectId}`;
            } catch (e) {
                nameEl.textContent = `Project ${projectId}`;
            }
        }

        // 5. Init Monaco editor
        const editorArea = _container.querySelector(".cm-editor-area");
        MonacoSetup.createEditor(editorArea);

        // 6. Init FileTree
        const treeEl = _container.querySelector(".cm-file-tree-body");
        FileTree.init(treeEl, projectId);
        await FileTree.refresh();

        // 7. Init LivePreview
        const iframe = _container.querySelector(".cm-preview-iframe");
        LivePreview.init(iframe, projectId);
        LivePreview.refreshPreview();

        // 8. Init AIChatOverlay
        const overlay = _container.querySelector(".cm-ai-overlay");
        AIChatOverlay.init(overlay, projectId);

        // 9. Wire events
        _wireEvents();

        // 10. Wire resize handles
        _wireResize();

        // 11. Auto-open index.html
        await _autoOpenIndex(projectId);
    }

    // -------------------------------------------------------------------------
    // Public: exit
    // -------------------------------------------------------------------------
    function exit() {
        if (_container) {
            _container.classList.remove("active");
        }
        MonacoSetup.dispose();
        _projectId = null;
        _container = null;
    }

    // -------------------------------------------------------------------------
    // Private: _autoOpenIndex
    // -------------------------------------------------------------------------
    async function _autoOpenIndex(projectId) {
        try {
            const r = await fetch(`/plugins/website-builder/api/projects/${projectId}/files`);
            const data = await r.json();
            const files = data.files || [];
            const indexFile = files.find(f => f.name === "index.html" || f.path === "index.html");
            if (!indexFile) return;

            const cr = await fetch(
                `/plugins/website-builder/api/projects/${projectId}/files/${encodeURIComponent(indexFile.path || indexFile.name)}`
            );
            const cd = await cr.json();
            MonacoSetup.openFile(indexFile.path || indexFile.name, cd.content || "", "html");
            _renderTabs();
        } catch (e) {
            console.warn("CodeMode: could not auto-open index.html", e);
        }
    }

    // -------------------------------------------------------------------------
    // Private: _wireEvents
    // -------------------------------------------------------------------------
    function _wireEvents() {
        if (!_container) return;

        // cm:open-file — open a file in the editor
        document.addEventListener("cm:open-file", async (e) => {
            const { path, name } = e.detail || {};
            if (!path && !name) return;
            try {
                const r = await fetch(
                    `/plugins/website-builder/api/projects/${_projectId}/files/${encodeURIComponent(path || name)}`
                );
                const data = await r.json();
                const ext = (path || name).split(".").pop().toLowerCase();
                const langMap = { html: "html", css: "css", js: "javascript", json: "json", md: "markdown" };
                MonacoSetup.openFile(path || name, data.content || "", langMap[ext] || "plaintext");
                _renderTabs();
            } catch (err) {
                console.error("CodeMode: open-file failed", err);
            }
        });

        // cm:tab-activated / cm:tab-changed / cm:tab-closed
        document.addEventListener("cm:tab-activated", () => _renderTabs());
        document.addEventListener("cm:tab-changed",   () => _renderTabs());
        document.addEventListener("cm:tab-closed",    () => _renderTabs());

        // cm:save-file — persist current editor content
        document.addEventListener("cm:save-file", async (e) => {
            const filePath = e.detail?.path || MonacoSetup.getActiveFile?.();
            if (!filePath) return;
            const content = MonacoSetup.getContent();
            try {
                await fetch(
                    `/plugins/website-builder/api/projects/${_projectId}/files/${encodeURIComponent(filePath)}`,
                    {
                        method: "PUT",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ content }),
                    }
                );
                MonacoSetup.markSaved?.(filePath);
                _renderTabs();
            } catch (err) {
                console.error("CodeMode: save-file failed", err);
            }
        });

        // cm:file-deleted — close tab if it's open
        document.addEventListener("cm:file-deleted", (e) => {
            const { path } = e.detail || {};
            if (!path) return;
            const tabs = MonacoSetup.getOpenTabs ? MonacoSetup.getOpenTabs() : [];
            if (tabs.some(t => t.path === path)) {
                MonacoSetup.closeTab?.(path);
                _renderTabs();
            }
        });

        // File tree filter input
        const filterInput = _container.querySelector(".cm-file-tree-header input");
        if (filterInput) {
            filterInput.addEventListener("input", () => FileTree.setFilter(filterInput.value));
        }

        // Device toggle buttons
        _container.querySelectorAll("[data-device]").forEach(btn => {
            btn.addEventListener("click", () => {
                _container.querySelectorAll("[data-device]").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                LivePreview.setDevice(btn.dataset.device);
            });
        });

        // Refresh preview
        const refreshBtn = _container.querySelector(".cm-refresh-btn");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", () => LivePreview.refreshPreview());
        }

        // Open in new tab
        const newTabBtn = _container.querySelector(".cm-newtab-btn");
        if (newTabBtn) {
            newTabBtn.addEventListener("click", () => LivePreview.openInNewTab());
        }

        // AI toggle
        const aiToggle = _container.querySelector(".cm-ai-toggle");
        if (aiToggle) {
            aiToggle.addEventListener("click", () => AIChatOverlay.toggle());
        }

        // Back button
        const backBtn = _container.querySelector(".cm-back-btn");
        if (backBtn) {
            backBtn.addEventListener("click", () => {
                if (confirm("Switch back to visual builder? Hand-edited code may be modified by the visual builder.")) {
                    exit();
                }
            });
        }
    }

    // -------------------------------------------------------------------------
    // Private: _renderTabs
    // -------------------------------------------------------------------------
    function _renderTabs() {
        if (!_container) return;
        const tabBar = _container.querySelector(".cm-tabs");
        if (!tabBar) return;

        const tabs = MonacoSetup.getOpenTabs ? MonacoSetup.getOpenTabs() : [];

        // Clear existing tabs safely (no innerHTML)
        while (tabBar.firstChild) {
            tabBar.removeChild(tabBar.firstChild);
        }

        tabs.forEach(tab => {
            const tabEl = document.createElement("div");
            tabEl.className = "cm-tab" + (tab.active ? " active" : "");

            const label = document.createElement("span");
            label.className = "cm-tab-label";
            // Show filename only (last segment of path)
            label.textContent = tab.path ? tab.path.split("/").pop() : tab.name || "untitled";

            if (tab.unsaved) {
                const dot = document.createElement("span");
                dot.className = "cm-tab-unsaved";
                dot.textContent = "\u25CF"; // ● bullet
                label.appendChild(dot);
            }

            const closeBtn = document.createElement("button");
            closeBtn.className = "cm-tab-close";
            closeBtn.textContent = "\u00D7"; // ×
            closeBtn.addEventListener("click", (ev) => {
                ev.stopPropagation();
                MonacoSetup.closeTab?.(tab.path);
                _renderTabs();
            });

            tabEl.appendChild(label);
            tabEl.appendChild(closeBtn);

            tabEl.addEventListener("click", () => {
                MonacoSetup.switchTab?.(tab.path);
                _renderTabs();
            });

            tabBar.appendChild(tabEl);
        });
    }

    // -------------------------------------------------------------------------
    // Private: _wireResize
    // -------------------------------------------------------------------------
    function _wireResize() {
        if (!_container) return;
        const MIN_WIDTH = 150;

        _container.querySelectorAll(".cm-resize-handle").forEach(handle => {
            handle.addEventListener("mousedown", (e) => {
                e.preventDefault();

                const resizeTarget = handle.dataset.resize;
                let panel;
                if (resizeTarget === "tree") {
                    panel = _container.querySelector(".cm-file-tree");
                } else if (resizeTarget === "preview") {
                    panel = _container.querySelector(".cm-preview-panel");
                }
                if (!panel) return;

                const startX = e.clientX;
                const startWidth = panel.getBoundingClientRect().width;

                function onMouseMove(ev) {
                    let newWidth;
                    if (resizeTarget === "tree") {
                        newWidth = startWidth + (ev.clientX - startX);
                    } else {
                        // Preview panel is on the right; drag left = wider
                        newWidth = startWidth - (ev.clientX - startX);
                    }
                    newWidth = Math.max(MIN_WIDTH, newWidth);
                    panel.style.width = newWidth + "px";
                    panel.style.flex = "none";
                }

                function onMouseUp() {
                    document.removeEventListener("mousemove", onMouseMove);
                    document.removeEventListener("mouseup", onMouseUp);
                }

                document.addEventListener("mousemove", onMouseMove);
                document.addEventListener("mouseup", onMouseUp);
            });
        });
    }

    // -------------------------------------------------------------------------
    // Expose public API
    // -------------------------------------------------------------------------
    return { enter, exit };
})();
