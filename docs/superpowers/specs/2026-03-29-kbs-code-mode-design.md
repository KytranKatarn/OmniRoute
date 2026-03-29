# KBS Website Builder — Code Mode (Monaco Editor)

**Date**: 2026-03-29
**Project**: #196 Unified Business Suite (Task #1486)
**Status**: Approved
**Location**: `plugins/kbs_website_builder/`

---

## Summary

Add a "Code Mode" tab to the KBS Website Builder plugin. Replit-style three-panel IDE layout with Monaco code editor, file tree, live preview with device toggles, and AI chat overlay. Database-backed virtual filesystem. Integrates with existing deploy pipeline and AI assistant.

## Panels

### Left — File Tree (~250px, resizable)

- Hierarchical file/folder browser
- Operations: create, rename, delete, duplicate, drag-drop reorder
- File type icons (HTML, CSS, JS, JSON, MD, YAML, images, fonts)
- Folder support with expand/collapse
- Right-click context menu for all operations
- Search/filter input at top

### Center — Monaco Editor

- Microsoft Monaco Editor (same engine as VS Code)
- Load via CDN: `https://cdn.jsdelivr.net/npm/monaco-editor@latest/min/`
- Tabbed multi-file editing with close/reorder
- Syntax highlighting: HTML, CSS, JavaScript, JSON, Markdown, YAML
- Features: auto-complete, minimap, find/replace (Ctrl+Shift+F), bracket matching, auto-indent
- Emmet support for HTML/CSS
- Keyboard shortcuts: Ctrl+S (save), Ctrl+P (quick open file), Ctrl+Shift+P (command palette)
- Unsaved changes indicator (dot on tab)
- Theme: dark theme matching KBS LCARS aesthetic

### Right — Live Preview (resizable)

- Iframe-based rendering
- Hot reload on keystroke (debounced 500ms)
- Assembly: combine all project HTML/CSS/JS into iframe srcdoc or blob URL
- CSS-only changes inject via style replacement (no full reload)
- Device toggle toolbar:
  - Mobile: 375px width
  - Tablet: 768px width
  - Desktop: 1280px width (or fill available space)
- Refresh button for manual reload
- Open in new tab button (renders full preview)

### Overlay — AI Chat (slide-in from right, ~350px)

- Toggle button on right edge of editor
- Same AI capabilities as existing visual builder:
  - suggest-design
  - generate-content
  - improve-seo
  - generate-styles
- Context-aware: sends current open file + cursor selection to AI
- AI edits apply directly into Monaco editor as a diff the user can accept/reject
- Chat history persisted per project (existing `chat_history` table)

## Data Model

### New Table: `website_files`

```sql
CREATE TABLE IF NOT EXISTS website_files (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES website_projects(id) ON DELETE CASCADE,
    path TEXT NOT NULL,              -- e.g. "css/style.css", "images/logo.png"
    filename TEXT NOT NULL,          -- e.g. "style.css"
    content TEXT,                    -- file content (NULL for directories)
    mime_type TEXT DEFAULT 'text/plain',
    file_size INTEGER DEFAULT 0,
    is_directory BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, path)
);

CREATE INDEX idx_website_files_project ON website_files(project_id);
CREATE INDEX idx_website_files_path ON website_files(project_id, path);
```

Per-tenant isolation via existing KBS tenant schema search path (`SET search_path TO tenant_{id}`).

### Asset Storage

- Images, fonts, media stored as base64-encoded TEXT in `content` column
- Size limit: 5MB per file, enforced at upload route
- Mime type detection on upload
- Asset browser panel (grid view with thumbnails) for browsing and inserting references

### Default Project Scaffold

When a project enters Code Mode for the first time, seed `website_files` from the project's existing pages:

```
index.html    — assembled from project template + page content
css/
  style.css   — extracted styles
js/
  script.js   — extracted scripts
images/       — empty directory
```

If the project already has pages in the visual builder, convert them to files. If starting fresh, use a minimal HTML5 boilerplate.

## API Endpoints

All under existing blueprint prefix `/plugins/website-builder/`.

### File Operations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects/<id>/files` | List all files in project (tree structure) |
| GET | `/api/projects/<id>/files/<file_id>` | Get file content |
| POST | `/api/projects/<id>/files` | Create file or directory |
| PUT | `/api/projects/<id>/files/<file_id>` | Update file content |
| PATCH | `/api/projects/<id>/files/<file_id>` | Rename or move file |
| DELETE | `/api/projects/<id>/files/<file_id>` | Delete file or directory |
| POST | `/api/projects/<id>/files/upload` | Upload asset (multipart, max 5MB) |

### Preview

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects/<id>/preview` | Assemble all files into previewable HTML |

### Code Mode

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects/<id>/enter-code-mode` | Convert project pages to files, set mode flag |
| GET | `/api/projects/<id>/mode` | Get current mode (visual/code) |

## Mode Switching

- Projects have a `editor_mode` field: `visual` (default) or `code`
- Entering Code Mode: POST to `/enter-code-mode` converts existing pages to files
- Switching back to visual: warning dialog — "Hand-edited code may be modified by the visual builder. Continue?"
- Visual builder reads from pages table; Code Mode reads from files table
- Deploy pipeline checks `editor_mode` and reads from the appropriate source
- If all files are deleted in Code Mode, project reverts to `visual` mode automatically

### Migration for mode field

```sql
ALTER TABLE website_projects
    ADD COLUMN IF NOT EXISTS editor_mode TEXT DEFAULT 'visual'
    CHECK (editor_mode IN ('visual', 'code'));
```

## Frontend Architecture

### Template Changes

Add to existing `website_builder.html`:
- New "Code Mode" tab/button alongside existing builder views
- Code Mode view is a full-viewport three-panel layout (hides the visual builder chrome)
- Back button returns to the visual builder dashboard

### JavaScript Modules (new files)

| File | Purpose |
|------|---------|
| `static/js/code-mode.js` | Main orchestrator: panel layout, resize handles, state management |
| `static/js/file-tree.js` | File tree component: render, CRUD operations, context menu |
| `static/js/monaco-setup.js` | Monaco loader, editor config, tab management, keybindings |
| `static/js/live-preview.js` | Preview iframe, hot reload, device toggles, file assembly |
| `static/js/ai-chat-overlay.js` | AI chat panel, context injection, diff application |
| `static/css/code-mode.css` | Three-panel layout, LCARS-themed chrome, resize handles |

### Monaco Loading

```javascript
// Load Monaco from CDN
require.config({
    paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs' }
});
require(['vs/editor/editor.main'], function() {
    // Initialize editor
});
```

### Hot Reload Assembly

```
1. Collect all project files from local state (cached after initial load)
2. Find index.html (or entry point)
3. Inline CSS <link> tags with file content from website_files
4. Inline JS <script src> tags with file content from website_files
5. Replace image src with base64 data URIs
6. Set iframe.srcdoc = assembled HTML
7. For CSS-only changes: find existing <style> in iframe and replace (skip full reload)
```

## Deploy Integration

No changes to existing deploy pipeline. When deploying a Code Mode project:

1. Read all files from `website_files` table
2. Assemble into directory structure
3. Zip and push to provider (Hostinger/GitHub/Vercel/Netlify)

The existing `build_site_zip()` in `core/hostinger_deploy.py` needs a branch:
- If `editor_mode == 'visual'`: current behavior (generate from pages)
- If `editor_mode == 'code'`: read from `website_files` table directly

## What We're NOT Building

- No Git integration or version history per project
- No server-side code execution (static sites only)
- No collaborative real-time editing (single user per project)
- No custom domain management (already exists)
- No terminal/console panel
- No package manager or npm integration

## LCARS Theme Integration

- Editor chrome (panel borders, tab bars, toolbar) uses KBS LCARS variables
- Monaco dark theme customized to match: dark background, cyan/teal accents
- File tree icons use LCARS color coding (cyan for HTML, yellow for JS, pink for CSS)
- Device toggle buttons styled as LCARS pill buttons
- AI chat overlay uses existing KBS chat component styling
- Resize handles styled as thin LCARS accent bars
