# KBS Code Mode (Monaco Editor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-panel Code Mode (file tree + Monaco editor + live preview) to the KBS Website Builder plugin.

**Architecture:** New migration adds `website_files` table and `editor_mode` column. New `code_mode_routes.py` handles file CRUD and preview assembly. Frontend is 6 new JS/CSS files loaded when Code Mode is active. Monaco loaded from CDN. Existing deploy pipeline extended to read from `website_files` when `editor_mode == 'code'`.

**Tech Stack:** Python/Flask (backend), Monaco Editor via CDN (editor), PostgreSQL (storage), iframe srcdoc (preview)

**Spec:** `docs/superpowers/specs/2026-03-29-kbs-code-mode-design.md`

**Security note:** File tree and editor render user-owned content from the database. All innerHTML usage is limited to hardcoded icon entities. During implementation, consider adding DOMPurify for any user-generated HTML rendering.

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `plugins/kbs_website_builder/migrations/005_code_mode.sql` | DB migration: `website_files` table + `editor_mode` column |
| `plugins/kbs_website_builder/code_mode_routes.py` | File CRUD API, preview assembly, mode switching endpoints |
| `plugins/kbs_website_builder/static/js/code-mode.js` | Main orchestrator: panel layout, resize handles, state |
| `plugins/kbs_website_builder/static/js/file-tree.js` | File tree component: render, CRUD, context menu |
| `plugins/kbs_website_builder/static/js/monaco-setup.js` | Monaco loader, editor config, tabs, keybindings |
| `plugins/kbs_website_builder/static/js/live-preview.js` | Preview iframe, hot reload, device toggles |
| `plugins/kbs_website_builder/static/js/ai-chat-overlay.js` | AI chat slide-in panel, context injection |
| `plugins/kbs_website_builder/static/css/code-mode.css` | Three-panel layout, LCARS chrome, resize handles |
| `plugins/kbs_website_builder/tests/test_code_mode.py` | Tests for file CRUD, preview, mode switching |

### Modified Files

| File | Change |
|------|--------|
| `plugins/kbs_website_builder/__init__.py` | Import and register `code_mode_routes` |
| `plugins/kbs_website_builder/templates/website_builder.html` | Add Code Mode tab button + code-mode container div |
| `core/hostinger_deploy.py` | `build_site_zip()` branch for `editor_mode == 'code'` |

---

## Task 1: Database Migration

**Files:**
- Create: `plugins/kbs_website_builder/migrations/005_code_mode.sql`

- [ ] **Step 1: Write the migration SQL**

Create `plugins/kbs_website_builder/migrations/005_code_mode.sql`:

```sql
-- Website Builder migration 005 -- Code Mode support.
-- Adds website_files table for virtual filesystem and editor_mode to projects.
-- All statements are idempotent. Run inside tenant schema.

CREATE TABLE IF NOT EXISTS website_files (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES website_projects(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    content     TEXT,
    mime_type   TEXT DEFAULT 'text/plain',
    file_size   INTEGER DEFAULT 0,
    is_directory BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, path)
);

CREATE INDEX IF NOT EXISTS idx_website_files_project ON website_files(project_id);
CREATE INDEX IF NOT EXISTS idx_website_files_path ON website_files(project_id, path);

ALTER TABLE website_projects
    ADD COLUMN IF NOT EXISTS editor_mode TEXT DEFAULT 'visual';

-- Add check constraint idempotently
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'website_projects_editor_mode_check'
    ) THEN
        ALTER TABLE website_projects
            ADD CONSTRAINT website_projects_editor_mode_check
            CHECK (editor_mode IN ('visual', 'code'));
    END IF;
END $$;
```

- [ ] **Step 2: Run migration against test tenant**

```bash
docker exec -i kbs_postgres psql -U archie -d archie -c "SET search_path TO tenant_1; \i /dev/stdin" < plugins/kbs_website_builder/migrations/005_code_mode.sql
```

Expected: tables created, column added, no errors.

- [ ] **Step 3: Verify schema**

```bash
docker exec kbs_postgres psql -U archie -d archie -c "SET search_path TO tenant_1; \d website_files; \d website_projects;" | head -40
```

Expected: `website_files` table with all columns, `website_projects` has `editor_mode` column.

- [ ] **Step 4: Commit**

```bash
git add plugins/kbs_website_builder/migrations/005_code_mode.sql
git commit -m "feat(website-builder): add website_files table and editor_mode column"
```

---

## Task 2: File CRUD API Routes + Tests

**Files:**
- Create: `plugins/kbs_website_builder/code_mode_routes.py`
- Create: `plugins/kbs_website_builder/tests/test_code_mode.py`
- Modify: `plugins/kbs_website_builder/__init__.py`

- [ ] **Step 1: Write failing tests for file CRUD**

Create `plugins/kbs_website_builder/tests/test_code_mode.py` with 12 tests covering: get mode (default visual), enter code mode, list files, create file, create directory, get file content, update file, rename file, delete file, duplicate path fails (409), file size limit (413), preview assembly.

Test fixture pattern: create tenant 9905, run all 5 migrations, create test project, yield setup dict, teardown schema.

Each test hits the API via `authed_client` fixture (Flask test client with session login).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain/kytran-business-suite && python -m pytest plugins/kbs_website_builder/tests/test_code_mode.py -v --tb=short 2>&1 | tail -20
```

Expected: ImportError or 404 errors (routes don't exist yet).

- [ ] **Step 3: Write code_mode_routes.py**

Create `plugins/kbs_website_builder/code_mode_routes.py` with `register_code_mode_routes(bp)` function containing:

Endpoints:
- `GET /api/projects/<id>/mode` - returns current editor_mode
- `POST /api/projects/<id>/enter-code-mode` - converts pages to files, sets mode to 'code'
- `GET /api/projects/<id>/files` - list all files in project
- `GET /api/projects/<id>/files/<file_id>` - get file content
- `POST /api/projects/<id>/files` - create file/directory (auto-creates parent dirs, 5MB limit, 409 on duplicate)
- `PUT /api/projects/<id>/files/<file_id>` - update file content
- `PATCH /api/projects/<id>/files/<file_id>` - rename/move file
- `DELETE /api/projects/<id>/files/<file_id>` - delete file (reverts to visual mode if no files left)
- `POST /api/projects/<id>/files/upload` - multipart upload, base64 encode, 5MB limit
- `GET /api/projects/<id>/preview` - assemble all files into single HTML (inline CSS links, JS scripts, base64 images)

All routes use `@login_required`, `@require_module(MODULE)`, KBS tenant search path pattern.

Enter code mode: if project has existing pages, convert each page to `{slug}.html`. If no pages, seed boilerplate (index.html, css/style.css, js/script.js, images/ directory).

Preview assembly: find index.html, regex-replace `<link href="...css">` with inlined `<style>`, `<script src="...js">` with inlined `<script>`, image src with base64 data URIs.

- [ ] **Step 4: Register routes in __init__.py**

Add `from plugins.kbs_website_builder.code_mode_routes import register_code_mode_routes` and call `register_code_mode_routes(bp)` after existing `register_routes(bp)`.

- [ ] **Step 5: Run tests**

```bash
cd /mnt/archie_brain/kytran-business-suite && python -m pytest plugins/kbs_website_builder/tests/test_code_mode.py -v --tb=short 2>&1 | tail -30
```

Expected: All 12 tests pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/kbs_website_builder/code_mode_routes.py plugins/kbs_website_builder/tests/test_code_mode.py plugins/kbs_website_builder/__init__.py
git commit -m "feat(website-builder): add Code Mode file CRUD API + tests"
```

---

## Task 3: Deploy Pipeline Integration

**Files:**
- Modify: `core/hostinger_deploy.py`

- [ ] **Step 1: Modify build_site_zip to support Code Mode**

Add optional `code_mode_files` parameter to `build_site_zip()`. When provided (list of dicts with path/content/is_directory), use those instead of pages. Skip directories. Write each file at its path in the ZIP.

Backward compatible: defaults to None, existing behavior unchanged.

- [ ] **Step 2: Verify existing deploy tests still pass**

```bash
cd /mnt/archie_brain/kytran-business-suite && python -m pytest plugins/kbs_website_builder/tests/test_website_builder.py -v --tb=short 2>&1 | tail -20
```

Expected: All existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add core/hostinger_deploy.py
git commit -m "feat(deploy): extend build_site_zip for Code Mode files"
```

---

## Task 4: Code Mode CSS

**Files:**
- Create: `plugins/kbs_website_builder/static/css/code-mode.css`

- [ ] **Step 1: Write the three-panel layout CSS**

Full LCARS-themed CSS covering:
- `.code-mode-container` (fixed fullscreen overlay, flex column)
- `.cm-toolbar` (top bar with project name, device toggles, back/refresh/newtab buttons)
- `.cm-panels` (flex row: file tree + resize handle + editor + resize handle + preview)
- `.cm-file-tree` (250px width, header with filter input, scrollable body, tree items with depth indentation)
- `.cm-tree-item` (hover/selected states, file type icon colors: orange=HTML, pink=CSS, yellow=JS, cyan=JSON, green=MD, purple=folders)
- `.cm-editor-panel` (flex grow, tab bar with active/unsaved indicators, editor area)
- `.cm-preview-panel` (40% width, header, iframe)
- `.cm-resize-handle` (4px cursor:col-resize, cyan on hover/drag)
- `.cm-ai-overlay` (absolute positioned right panel, 350px, slide-in transform, purple accent)
- `.cm-ai-toggle` (vertical text button on right edge)
- `.cm-context-menu` (fixed positioned, LCARS border, hover states)

Font families: Orbitron (titles), Antonio (nav/labels), IBM Plex Mono (code/content).

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/static/css/code-mode.css
git commit -m "feat(website-builder): add Code Mode LCARS-themed CSS layout"
```

---

## Task 5: Monaco Setup (JS)

**Files:**
- Create: `plugins/kbs_website_builder/static/js/monaco-setup.js`

- [ ] **Step 1: Write the Monaco loader and editor manager**

IIFE module `MonacoSetup` with:
- `load()` - loads Monaco from CDN (jsdelivr, v0.52.2), returns promise
- `_defineTheme()` - creates "lcars-dark" theme (dark bg, cyan keywords, green strings, orange tags, purple attributes)
- `createEditor(containerEl)` - creates editor instance with LCARS theme, IBM Plex Mono font, minimap, auto-layout
- `openFile(fileId, path, content)` - creates model with correct language, manages tabs Map
- `closeTab(fileId)` - disposes model, switches to next tab
- `getContent(fileId)` - returns model value
- `markSaved(fileId)` - clears unsaved flag
- `getActiveFileId()` / `getOpenTabs()` / `getEditor()` - accessors
- `dispose()` - cleanup all models and editor

Language detection via extension map (html, css, js, json, md, yaml, xml, txt).
Emits custom events: `cm:tab-changed`, `cm:tab-activated`, `cm:tab-closed`, `cm:content-changed`, `cm:save-file` (on Ctrl+S).

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/static/js/monaco-setup.js
git commit -m "feat(website-builder): add Monaco editor setup with LCARS theme"
```

---

## Task 6: File Tree (JS)

**Files:**
- Create: `plugins/kbs_website_builder/static/js/file-tree.js`

- [ ] **Step 1: Write the file tree component**

IIFE module `FileTree` with:
- `init(containerEl, projectId)` - stores references
- `refresh()` - fetches files from API, calls render
- `render()` - builds tree from flat file list, renders into `.cm-file-tree-body`
- `_buildTree(flatFiles)` - converts flat paths to nested object
- `_renderNode(parentEl, node, depth)` - recursive DOM render, folders first then alpha sort
- `setFilter(text)` - filters tree by path substring

File type icons: HTML (diamond, orange), CSS (filled diamond, pink), JS (play, yellow), JSON (brace, cyan), MD (pilcrow, green), images (square, purple), folders (triangle, purple).

Collapsible folders tracked in Set. Click file dispatches `cm:open-file` event. Right-click shows context menu.

Context menu actions:
- Folders: New File, New Folder, Delete Folder
- Files: Rename, Duplicate, Delete

All operations hit the Code Mode API and refresh the tree.

**Security:** Use `textContent` for file names (not innerHTML). Icon entities rendered via safe DOM methods.

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/static/js/file-tree.js
git commit -m "feat(website-builder): add file tree component with context menu"
```

---

## Task 7: Live Preview (JS)

**Files:**
- Create: `plugins/kbs_website_builder/static/js/live-preview.js`

- [ ] **Step 1: Write the live preview component**

IIFE module `LivePreview` with:
- `init(iframeEl, projectId)` - stores refs, listens for `cm:content-changed` events
- `refreshPreview()` - fetches `/api/projects/{id}/preview`, sets `iframe.srcdoc`
- `setDevice(device)` - sets iframe width (mobile 375px, tablet 768px, desktop 100%)
- `openInNewTab()` - opens srcdoc as blob URL in new window

Debounce: 500ms after last `cm:content-changed` event before refreshing.

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/static/js/live-preview.js
git commit -m "feat(website-builder): add live preview with device toggles"
```

---

## Task 8: AI Chat Overlay (JS)

**Files:**
- Create: `plugins/kbs_website_builder/static/js/ai-chat-overlay.js`

- [ ] **Step 1: Write the AI chat overlay**

IIFE module `AIChatOverlay` with:
- `init(overlayEl, projectId)` - stores refs, wires Enter key to send
- `toggle()` / `open()` / `close()` - slide panel in/out via CSS class
- `sendMessage()` - reads input, gets current file context from MonacoSetup, POSTs to existing `/api/projects/{id}/ai/chat` endpoint, appends response to chat, applies code_update to editor if returned

Messages rendered with `textContent` (not innerHTML) for security. AI responses get a light purple background.

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/static/js/ai-chat-overlay.js
git commit -m "feat(website-builder): add AI chat overlay for code editing"
```

---

## Task 9: Main Orchestrator (JS)

**Files:**
- Create: `plugins/kbs_website_builder/static/js/code-mode.js`

- [ ] **Step 1: Write the main Code Mode orchestrator**

IIFE module `CodeMode` with:
- `enter(projectId)` - POST enter-code-mode, load Monaco, show container, init all components, wire events, wire resize handles, auto-open index.html
- `exit()` - hide container, dispose Monaco

Event wiring:
- `cm:open-file` -> fetch content, open in Monaco, re-render tabs
- `cm:tab-activated/changed/closed` -> re-render tab bar
- `cm:save-file` -> PUT content to API, mark saved
- `cm:file-deleted` -> close tab if open
- Filter input -> FileTree.setFilter
- Device toggle buttons -> LivePreview.setDevice
- Refresh/NewTab buttons -> LivePreview methods
- AI toggle -> AIChatOverlay.toggle
- Back button -> confirm dialog + exit

Tab bar rendering: iterate MonacoSetup.getOpenTabs(), show filename + unsaved dot + close button.

Resize handles: mousedown tracks startX/startWidth, mousemove adjusts target panel width, mouseup removes listeners.

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/static/js/code-mode.js
git commit -m "feat(website-builder): add Code Mode orchestrator with resize and event wiring"
```

---

## Task 10: Template Integration

**Files:**
- Modify: `plugins/kbs_website_builder/templates/website_builder.html`

- [ ] **Step 1: Add Code Mode button and container to the template**

Add to template:
1. A "Code Mode" button in the project detail view that calls `CodeMode.enter(projectId)`
2. The `.code-mode-container` div with toolbar (back, project name, device toggles, refresh, new tab), three panels (file tree with filter input, editor with tab bar + editor area, preview with iframe), resize handles, AI overlay with messages area + input, AI toggle button
3. CSS link to `code-mode.css` and script tags for all 5 JS files (monaco-setup, file-tree, live-preview, ai-chat-overlay, code-mode)

Preview iframe uses `sandbox="allow-scripts allow-same-origin"` for security.

- [ ] **Step 2: Commit**

```bash
git add plugins/kbs_website_builder/templates/website_builder.html
git commit -m "feat(website-builder): integrate Code Mode UI into template"
```

---

## Task 11: Deploy + Restart + Browser Test

- [ ] **Step 1: Restart KBS container**

```bash
cd /mnt/archie_brain/kytran-business-suite && docker compose restart kbs_app
```

- [ ] **Step 2: Run the migration on all active tenants**

Query tenant schemas and run 005_code_mode.sql against each.

- [ ] **Step 3: Run all tests**

```bash
cd /mnt/archie_brain/kytran-business-suite && python -m pytest plugins/kbs_website_builder/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass (existing + new code mode tests).

- [ ] **Step 4: Browser test at http://192.168.1.200:8091**

Verify:
1. Navigate to Website Builder plugin
2. Open or create a project
3. Click "Code Mode" button
4. Three-panel layout appears (file tree, editor, preview)
5. Files are listed in tree (index.html, css/, js/ at minimum)
6. Click a file - opens in Monaco editor with syntax highlighting
7. Edit code - preview updates after ~500ms
8. Device toggles work (mobile/tablet/desktop resize preview)
9. Create/rename/delete files via right-click context menu
10. AI chat overlay opens and closes
11. Back button returns to visual builder with warning dialog
12. Ctrl+S saves file without page reload

- [ ] **Step 5: Commit any fixes**

```bash
git add -A && git commit -m "fix(website-builder): browser test fixes for Code Mode"
```

---

## Summary

| Task | What | Commit |
|------|------|--------|
| 1 | Database migration (website_files + editor_mode) | `feat: add website_files table` |
| 2 | File CRUD API + tests (12 tests) | `feat: add Code Mode file CRUD API` |
| 3 | Deploy pipeline integration | `feat: extend build_site_zip` |
| 4 | Code Mode CSS (LCARS themed) | `feat: add Code Mode CSS` |
| 5 | Monaco setup (loader, theme, tabs) | `feat: add Monaco editor setup` |
| 6 | File tree (render, CRUD, context menu) | `feat: add file tree component` |
| 7 | Live preview (hot reload, device toggles) | `feat: add live preview` |
| 8 | AI chat overlay (context-aware) | `feat: add AI chat overlay` |
| 9 | Main orchestrator (wiring, resize) | `feat: add Code Mode orchestrator` |
| 10 | Template integration | `feat: integrate Code Mode UI` |
| 11 | Deploy, migrate, browser test | `fix: browser test fixes` |
