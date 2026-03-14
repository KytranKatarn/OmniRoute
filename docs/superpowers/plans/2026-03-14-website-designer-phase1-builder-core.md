# Website Designer Phase 1: Builder Core — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Replit-style three-panel LCARS UI for Website Designer with Monaco code editor, live preview, AI inline chat, project dashboard, and template browser — transforming the module from a blank page into a functional website builder.

**Architecture:** Single-page template (`website_studio.html`) with three-panel CSS Grid layout. Monaco editor loaded from CDN. Live preview via sandboxed iframe with `srcdoc`. AI chat dispatches to existing `/api/chat` endpoint. All data from existing backend API (~40 routes already built). External JS file for editor logic, external CSS for styles.

**Tech Stack:** Flask (existing), Monaco Editor 0.45.0 (CDN), HTML5, CSS Grid, vanilla JS

**Key patterns from existing backend:**
- Blueprint: `website_studio_bp`, prefix `/tools/website-studio`
- Template: `platform_v2/templates/tools/website_studio.html` (currently empty, to be rewritten)
- No `static_folder` on blueprint — JS/CSS go in `platform_v2/static/js/` and `platform_v2/static/css/`
- Project API: `GET/POST /api/projects`, `GET/PUT/DELETE /api/projects/<id>`
- Page API: `GET /api/projects/<id>/pages`, `POST /api/projects/<id>/pages`, `PUT/DELETE /api/pages/<page_id>` (flat)
- Pages have `html_content` (text), `css_content` (text), `js_content` (text) columns
- Templates: `GET /api/templates`, `POST /api/projects/<id>/apply-template`
- AI Chat: `POST /api/chat` with `{message}`, returns `{success, message, changes, has_changes}`
- Auth: `@login_required`, projects scoped by `user_id`
- IMPORTANT: All DOM construction must use textContent/createElement — no innerHTML (security policy)

---

## Task 1: CSS File

**Files:**
- Create: `platform_v2/static/css/website-studio.css`

- [ ] **Step 1: Create the CSS file (~200 lines)**

Full LCARS-themed CSS with `ws-` prefix covering: three-panel grid layout, file tree, tabs, editor/preview containers, split handle, AI chat bar, dashboard, project/template cards, properties panel, modals, toast notifications. Blue accent (`var(--ws-accent, #4af)`) to differentiate from Media Studio. Antonio font for headers, IBM Plex Mono for code-adjacent elements.

Key classes: `.ws-layout`, `.ws-panel`, `.ws-file-tree`, `.ws-tree-item`, `.ws-tabs`, `.ws-tab`, `.ws-toolbar`, `.ws-editor-container`, `.ws-preview-container`, `.ws-split-handle`, `.ws-ai-bar`, `.ws-dashboard`, `.ws-project-card`, `.ws-template-card`, `.ws-properties`, `.ws-modal`, `.ws-toast`

See the spec CSS section for complete class list and design tokens.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/css/website-studio.css
git commit -m "feat(website-designer): add LCARS builder core CSS"
```

---

## Task 2: HTML Template

**Files:**
- Rewrite: `platform_v2/templates/tools/website_studio.html`

**Dependencies:** Task 1

- [ ] **Step 1: Read base template to confirm block names**

Read `platform_v2/templates/base.html` (first ~30 lines) to confirm: `{% block title %}`, `{% block extra_css %}`, `{% block content %}`, `{% block extra_js %}` exist.

- [ ] **Step 2: Write the full HTML template (~300 lines)**

Template extends `base.html`. Contains:
- `{% block extra_css %}` loads `website-studio.css`
- Dashboard view (`#wsDashboard`): project cards grid + template gallery
- Builder view (`#wsBuilder`): three-panel CSS Grid layout
  - Left panel: project selector dropdown + new file button + file tree container
  - Center: tab bar + toolbar (split/editor/preview/save/refresh) + editor container + split handle + preview iframe + AI chat history + AI input bar
  - Right panel: properties (file info, page settings, preview viewport controls, auto-refresh toggle)
- New Project modal + New File modal
- Toast notification div
- `{% block extra_js %}` loads Monaco CDN loader + `website-studio.js`

All DOM uses textContent/createElement patterns. No inline onclick on dynamic elements — only on static HTML buttons (which is safe since they call window functions with known arguments).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/tools/website_studio.html
git commit -m "feat(website-designer): add three-panel LCARS builder HTML template"
```

---

## Task 3: JavaScript — Core + Dashboard + File Tree

**Files:**
- Create: `platform_v2/static/js/website-studio.js`

**Dependencies:** Task 2

- [ ] **Step 1: Write core state, API helper, dashboard, project CRUD, file tree (~200 lines)**

IIFE wrapping all code. Key components:

**State variables:** `_currentProjectId`, `_pages`, `_pageMap`, `_openTabs`, `_activeTab`, `_monacoEditor`, `_models`, `_editorView`, `_viewport`, `_autoRefresh`, `_aiHistory`

**API helper:** `function api(method, path, body)` — fetch wrapper with `API_BASE = '/tools/website-studio'`

**Toast:** `function toast(msg)` — show/hide toast div

**Modal helpers:** `window.openNewProjectModal`, `window.openNewFileModal`, `window.closeModal`

**Dashboard:** `function loadDashboard()` — fetch projects + templates, render cards using createElement/textContent. Template cards call `applyTemplate(t)` which creates project then applies template.

**Project CRUD:** `window.createProject()` — reads modal inputs, POST, opens project. `function openProject(id)` — loads project + pages, renders tree, auto-opens homepage. `window.switchProject(id)` — dropdown handler.

**File tree:** `function renderFileTree()` — for each page, create folder item + 3 file items (html/css/js) using createElement. Each file item has onclick calling `openFile(pageId, fileType)`. Icons via textContent emoji (not innerHTML).

**Create file:** `window.createFile()` — reads modal, POST new page with default HTML boilerplate, reloads tree.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/website-studio.js
git commit -m "feat(website-designer): add JS core — dashboard, project CRUD, file tree"
```

---

## Task 4: JavaScript — Monaco Editor + Tabs + Split View

**Files:**
- Modify: `platform_v2/static/js/website-studio.js` (append inside IIFE)

**Dependencies:** Task 3

- [ ] **Step 1: Append editor init, tab management, save, view toggle, split drag (~200 lines)**

**Monaco init:** `function initMonaco(callback)` — `require.config` with CDN paths, `require(['vs/editor/editor.main'])`, create editor in `#wsEditorContainer` with vs-dark theme. Add Ctrl+S command. Add `onDidChangeModelContent` listener for dirty marking + auto-refresh debounce.

**File open:** `function openFile(pageId, fileType)` — create Monaco model if not exists (from page's html/css/js_content), add to tabs, set as active model on editor.

**Tab close:** `function closeTab(pageId, fileType)` — confirm if dirty, dispose model, switch to another tab.

**Tab render:** `function renderTabs()` — build tab bar using createElement. Each tab: unsaved dot span + name span (onclick opens file) + close span (onclick closes tab). Active tab highlighted.

**Save:** `window.saveCurrentFile()` — get model value, PUT to `/api/pages/<pageId>` with the right content field, mark tab clean, toast.

**View toggle:** `window.setEditorView(view)` — show/hide editor container, split handle, preview container based on 'split'/'editor'/'preview'.

**Split drag:** IIFE with mousedown/mousemove/mouseup on `#wsSplitHandle` — adjusts flex percentages of editor and preview containers.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/website-studio.js
git commit -m "feat(website-designer): add Monaco editor, tabs, split view, save"
```

---

## Task 5: JavaScript — Preview + AI Chat + Properties + Init

**Files:**
- Modify: `platform_v2/static/js/website-studio.js` (append + close IIFE)

**Dependencies:** Task 4

- [ ] **Step 1: Append preview, AI chat, properties, init, close IIFE (~150 lines)**

**Preview:** `window.refreshPreview()` — assemble HTML from active page's html/css/js models (or cached content). Inject CSS as `<style>` before `</head>`, JS as `<script>` before `</body>`. Set `iframe.srcdoc`. `function debounceRefresh()` — 500ms debounce timer.

**Viewport:** `window.setViewport(vp)` — toggle viewport class on preview container.

**AI Chat:** `window.sendAiChat()` — read input, POST to `/api/chat` with message + context (current file content + language). On response: if `has_changes` + `changes[0].new_content`, apply to model. Else try to extract code block from response text via regex. Show toast. `function addAiEntry(role, text)` — append to history div using createElement/textContent.

**Properties:** `function updateProperties()` — populate file info (name, type, page ID) and page settings inputs from `_pageMap`.

**Right panel toggle:** `window.toggleRightPanel()` — toggle `ws-right-collapsed` class on builder layout, re-layout Monaco.

**Auto-refresh:** checkbox change listener sets `_autoRefresh`.

**Init:** `DOMContentLoaded` → `initMonaco()` → `loadDashboard()`.

Close the IIFE with `})();`

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/website-studio.js
git commit -m "feat(website-designer): add live preview, AI chat, properties, init"
```

---

## Task 6: Integration Test

**Files:**
- Create: `/tmp/test_website_designer.py`

**Dependencies:** All previous tasks

- [ ] **Step 1: Write integration test**

Test coverage:
- Website routes exist (>10 routes registered)
- Template file not empty (>100 chars)
- HTML has key element IDs: wsDashboard, wsBuilder, wsEditorContainer, wsPreviewFrame, wsTabs, wsFileTree, wsAiInput, wsProjectGrid, wsNewProjectModal, wsProperties, wsPreviewContainer, wsSplitHandle
- Monaco CDN reference in HTML
- website-studio.js reference in HTML
- CSS file exists with key classes: .ws-layout, .ws-panel, .ws-file-tree, .ws-tabs, .ws-tab, .ws-editor-container, .ws-preview-container, .ws-ai-bar, .ws-dashboard, .ws-project-card, .ws-template-card, .ws-properties, .ws-modal, .ws-toast
- JS file exists with key functions: openProject, createProject, openFile, closeTab, saveCurrentFile, refreshPreview, sendAiChat, setEditorView, setViewport, loadDashboard, initMonaco, renderFileTree, renderTabs
- DB tables exist: website_builder_projects, website_builder_pages

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_website_designer.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_website_designer.py
```

Expected: All tests PASS.

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 7: Deploy + Git Push + Dev HQ Update

**Dependencies:** Task 6

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Push to remote**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

Use MCP tools:
- `complete_task` for Phase 1 task (#862)
- `store_memory` — Website Designer Phase 1 complete
- `log_decision` — Monaco from CDN, three-panel CSS Grid, iframe srcdoc preview
