# Website Designer Phase 1: Builder Core — Design Spec

## Overview

Build the core Replit-style website builder UI for the Website Designer module. The module currently has ~40 backend API endpoints but an empty HTML template. This phase creates the full LCARS-themed three-panel layout with Monaco code editor, live preview, AI inline chat, project dashboard, and template browser.

**Goal:** Transform the Website Designer from a blank page into a functional website builder with VS Code-style editing, live preview, and AI-assisted code editing via Bridge — all within the LCARS sci-fi aesthetic. SaaS-scoped: each user sees only their own projects.

## Scope

Five capabilities:
1. **Three-panel layout** — file tree (left), editor+preview (center), properties (right)
2. **Monaco code editor** — tabbed files, split view, syntax highlighting for HTML/CSS/JS
3. **Live preview** — sandboxed iframe with real-time/manual refresh toggle and viewport simulation
4. **AI inline chat** — bottom chat bar for natural language code edits via Bridge dispatch
5. **Project dashboard + template browser** — project cards grid, template gallery, CRUD wiring

## Three-Panel Layout

### HTML Structure

Full-height CSS Grid layout: `grid-template-columns: 250px 1fr 280px`.

**Left Panel (250px, resizable):** File tree + project controls
- Project selector dropdown at top
- "New Project" / "New File" buttons
- Collapsible file tree with folder/file icons
- Right-click context menu: rename, delete, duplicate
- When no project selected: center panel shows dashboard instead

**Center Panel (flex):** Editor + Preview
- Tab bar for open files (unsaved dot indicator, close button)
- Monaco editor instance(s) — top portion
- Live preview iframe — bottom portion
- Draggable split handle between editor and preview
- Toolbar: split/editor-only/preview-only toggle, save, refresh
- AI inline chat bar docked at bottom

**Right Panel (280px, collapsible):** Properties + settings
- Context-sensitive based on selection
- File properties: name, type, size, last modified
- Page settings: title, meta description, SEO tags
- Project settings: name, description, template
- Preview controls: viewport buttons (desktop/tablet/mobile), auto-refresh toggle

## Monaco Editor Integration

### Loading

Monaco loaded from CDN via AMD loader:
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js"></script>
```
Configured with `require.config` pointing to CDN paths. Initialized after DOM ready.

### File Model Management

- Each open file: `monaco.editor.createModel(content, language, uri)`
- Language from extension: `.html` → `html`, `.css` → `css`, `.js` → `javascript`
- URI scheme: `file:///project/{project_id}/{filename}`
- Dirty state via `onDidChangeContent` listener

### Tab System

- Tab bar above editor
- Each tab: filename + unsaved dot (accent color) + close (x)
- Click tab → `editor.setModel(model)`
- Ctrl+S saves via `PUT /api/projects/{id}/pages/{page_id}`

### Split View

- Two `monaco.editor.create()` instances in stacked containers
- Draggable horizontal divider
- Each can show a different file (e.g., HTML top, CSS bottom)
- Toggle: split, editor-only, preview-only

### Editor Config

```javascript
{
    theme: 'vs-dark',
    fontSize: 13,
    minimap: { enabled: true },
    wordWrap: 'on',
    automaticLayout: true,
    tabSize: 2,
    formatOnPaste: true,
}
```

### File Operations

- **Open**: `GET /api/projects/{id}/pages/{page_id}` → model + tab
- **Save**: `PUT /api/projects/{id}/pages/{page_id}` with content
- **Create**: `POST /api/projects/{id}/pages` → tree + tab
- **Delete**: `DELETE /api/projects/{id}/pages/{page_id}` → close tab + tree

## Live Preview

### Content Assembly

On refresh, assemble complete HTML from open models:
1. Active HTML file content
2. Inject `style.css` content as `<style>` if not already linked
3. Inject `script.js` content as `<script>` if not already referenced
4. Set `iframe.srcdoc = assembledHTML`

### Refresh Modes

- **Real-time** (default): debounced 500ms on model content change
- **Manual**: refresh on Ctrl+S or click Refresh button
- Toggle via button in right panel

### Viewport Simulation

Three preset buttons:
- Desktop (100% width)
- Tablet (768px, centered)
- Mobile (375px, centered)

Set iframe container width, iframe fills container.

### Security

`sandbox="allow-scripts allow-same-origin"` — permits JS execution, prevents navigation.

## AI Inline Chat

### Chat Bar

Persistent input bar at bottom of editor area:
```
[AI icon] [ Type a command...  ] [Send]
```

### Flow

1. User types instruction (e.g., "make the header blue")
2. JS sends to `POST /api/website-studio/api/ai/chat`:
   ```json
   {
     "message": "make the header blue",
     "project_id": 123,
     "context": {
       "current_file": "index.html",
       "current_content": "<!DOCTYPE html>...",
       "language": "html"
     }
   }
   ```
3. Backend dispatches to Bridge via `archie_bridge.chat()` with code-edit system prompt
4. Response: updated file content
5. JS applies: `model.setValue(newContent)`, shows toast, preview auto-refreshes
6. Ctrl+Z to undo (Monaco undo stack)

### Chat History

Collapsible history above input, last 5 exchanges. JS memory only (not persisted in Phase 1).

### Phase 1 Scope

- Inline bar only (full side panel is Phase 2)
- Single-file context (current file, not whole project)
- No streaming — wait for complete response
- No diff view — direct apply with undo

## Project Dashboard + Template Browser

### Dashboard (no project open)

Center panel shows:
- "Create New Project" card → modal: name, description, template selection
- Recent Projects grid — cards with name, page count, last modified
- Card actions: open, rename, delete, duplicate
- Template Gallery section — starter templates by category

### Template Browser

Cards from existing `GET /api/templates` endpoint, organized by category (business, ecommerce, application).
Click → "Use Template" → enter project name → `POST /api/projects/{id}/apply-template`.

### SaaS Scoping

All API calls scoped to `current_user.id`. Users see only their own projects. Subscription limit enforcement UI deferred to Phase 2.

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `platform_v2/tools/website_studio/static/css/website-studio.css` | Three-panel layout, file tree, tabs, editor, preview, dashboard, AI chat (~200 lines) |
| **Create** | `platform_v2/tools/website_studio/static/js/website-studio.js` | Monaco init, file tree, tabs, split view, preview, AI chat, dashboard, CRUD (~500 lines) |
| **Rewrite** | `platform_v2/templates/tools/website_studio.html` | Full LCARS template: three-panel HTML, Monaco CDN, dashboard, modals (~300 lines) |
| **Create** | `platform_v2/tools/website_studio/static/` directory | Static assets directory |

**Total:** ~1000 lines new frontend code

**No backend changes** — all existing API endpoints are sufficient.

## CSS Design

**File:** `website-studio.css` with `ws-` prefix.

LCARS theme with blue accent (`var(--ws-accent, #4af)`) to differentiate from Media Studio orange. Antonio font headers, IBM Plex Mono for editor-adjacent elements.

Key classes:
- `.ws-layout` — CSS Grid three-panel
- `.ws-panel-left/center/right` — panel containers
- `.ws-file-tree` — collapsible tree
- `.ws-tabs` — tab bar with active/unsaved states
- `.ws-editor-area`, `.ws-preview-area` — editor and iframe containers
- `.ws-split-handle` — draggable divider
- `.ws-dashboard`, `.ws-project-card`, `.ws-template-card` — dashboard views
- `.ws-ai-chat-bar`, `.ws-ai-history` — AI input and history
- `.ws-properties` — right panel
- `.ws-viewport-btn` — responsive preview toggles
- `.ws-toolbar` — editor toolbar

## Dependencies

- Monaco Editor 0.45.0 via CDN (no npm/build step)
- Existing backend API (~40 endpoints already built)

## Scope Constraints

- No Hostinger integration (Phase 2)
- No multi-agent workflows (Phase 2)
- No side panel chat conversation (Phase 2)
- No deployment UI (Phase 2)
- No subscription limit enforcement UI (Phase 2)
- No image/asset drag-drop upload
- AI chat is single-file context only
- No collaborative editing
- No Git integration UI (Phase 2)
