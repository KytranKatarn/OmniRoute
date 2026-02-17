# Phase 4: Collaboration Mode UI Integration — Design Doc

**Date:** 2026-02-17
**Status:** Approved
**Scope:** Wire existing backend + JS into visible UI in archie_chat.html

---

## Context

The Collaboration Mode backend is 100% complete:
- `collaboration_engine.py` (1,248 lines) — Discussion + Joint Work modes
- `collaboration.js` (1,895 lines) — Full frontend logic (mode switching, templates, SSE, history, work products, voice)
- DB schema: `collaboration_sessions`, `collaboration_messages`, `collaboration_work_products`
- API routes: 12+ endpoints in consciousness/routes.py

**Problem:** `archie_chat.html` has zero collaboration UI elements. `collaboration.js` isn't even loaded. Users cannot access any collaboration features.

## Approach

**Wire existing JS into template** — Add the HTML elements that `collaboration.js` already expects, load the JS file, and add CSS. Minimal new JS needed.

## Architecture

### Mode Tab Bar
- 3 tabs in `.top-status-bar`: Solo (default), Side-by-Side, Collaboration
- Active tab highlighted with `--archie-purple`
- Calls existing `switchChatMode()` from collaboration.js

### Containers
1. **`#solo-chat-container`** — Wraps existing `.messages-container` + `.input-area`. No functional changes.
2. **`#dual-chat-container`** — 50/50 flex split. Left: chat messages. Right: ttyd iframe (port 7681). Sync Context + Clear buttons.
3. **`#collab-container`** — Two sub-views:
   - **Start View**: Topic input, max turns, mode toggle (Discussion/Joint Work), 6 template cards
   - **Active View**: Message stream with role avatars, status bar, control buttons (Pause/Resume/Stop/Interject)

### Sidebar Behavior
- Solo mode: existing sidebar (status metrics, quick actions, recent commands)
- Collaboration mode: history sidebar replaces content — filter pills (All/Active/Completed), search, session cards with resume/export

### Work Products Panel
- Collapsible right panel for Joint Work sessions
- Product cards with type badges, content preview, Approve/Save-to-KB buttons

### Thinking Panel
- Collapsible right panel showing orchestration steps
- LCARS color-coded entries (cyan=intent, gold=route, teal=agent, green=IAAE, plum=welfare)
- Shared across all modes

## Data Flow

All existing API endpoints — no new backend routes:
- Start: `POST /api/collab/start` or `/api/collab/joint/start`
- Stream: `GET /api/collab/stream/<id>` (SSE) with polling fallback
- Controls: `POST /api/collab/pause|resume|stop|interject/<id>`
- History: `GET /api/collab/sessions?search=X&status=Y`
- Work Products: `GET /api/collab/work-products/<id>`, `POST .../approve`, `POST .../save-to-kb`

## Styling

- LCARS design tokens (`--archie-*` variables)
- Collaboration messages: same `.message` pattern, role-specific colors (ARCHIE=cyan, Claude=purple, User=default)
- Template cards: `.command-item` style with hover transforms
- Responsive: collab containers stack on mobile (<900px)

## Error Handling

- SSE failure → automatic polling fallback (already in collaboration.js)
- Claude proxy down → engine handles gracefully, shows error in stream
- Session resume → `_load_session_from_db()` reconstructs state

## Not Included (YAGNI)

- No new backend routes or DB migrations
- No changes to collaboration_engine.py
- No new JS logic beyond minor glue code
- No thinking panel content generation (just DOM shell)

## Key Files

- Modify: `platform_v2/templates/tools/archie_chat.html` (HTML + CSS)
- Existing: `platform_v2/static/js/collaboration.js` (load it, may need minor fixes)
- Existing: `platform_v2/tools/consciousness/collaboration_engine.py`
- Existing: `platform_v2/tools/consciousness/routes.py` (collab API endpoints)
