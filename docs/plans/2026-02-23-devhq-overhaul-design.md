# Dev HQ Overhaul — Project-Centric Documentation Hub

**Date**: 2026-02-23
**Project**: Platform UI Overhaul (#94), Task #638
**Status**: Design Approved

---

## Problem

Dev HQ was rebuilt with 7 tabs (Overview, Projects, Tasks, Knowledge, Schema, API, Integrations) but critical documentation features are missing:

1. **92 ADRs in `project_decisions` are invisible** — no UI to view them
2. **`project_documents` table is unused** — versioned docs exist in DB but aren't surfaced
3. **No Project Detail view** — can't see a project's tasks + decisions + docs + activity together
4. **No Ideas/Future Work tracking** — everything must be a full project
5. **No Markdown rendering** — documentation shows as plain text
6. **Knowledge CRUD is incomplete** — can create but not edit/delete from UI
7. **3 tabs (Schema/API/Integrations) could merge** — saves space for new features

## Design

### Tab Structure: 7 → 6 Tabs

| Tab | Icon | Purpose |
|-----|------|---------|
| **Overview** | `layout-dashboard` | Stats, activity, quick actions |
| **Projects** | `folder-kanban` | Grid → click opens detail sub-view |
| **Ideas** | `lightbulb` | Dedicated ideas board with promote-to-project |
| **Knowledge** | `book-open` | Full KB browser with markdown editor |
| **Decisions** | `scale` | Global ADR browser across all projects |
| **System** | `settings` | Schema + API + Integrations merged |

Tasks tab removed as top-level — lives inside Project Detail. Cross-project task view accessible from Overview quick action.

### 1. Project Detail View

Clicking a project card replaces the grid with a detail view (back button to return).

**Header**: Project name, status badge, priority, progress bar, description, target date, edit button.

**4 Sub-tabs**:

#### Tasks Sub-tab
- All tasks for this project (existing `unified_tasks` query)
- Same CRUD, status cycling, filters as current Tasks tab
- Create task modal pre-fills project_id

#### Decisions Sub-tab
- List from `project_decisions WHERE project_id = ?`
- Shows: decision_number, title, status, decided_at
- Click to expand: context, decision text, alternatives, consequences (markdown rendered)
- Create decision modal: title, context, decision, alternatives, consequences, status, tags

#### Docs Sub-tab
- Uses `project_documents` table (finally!)
- List with doc_type badge, title, version, updated_at
- Click opens full view with markdown rendering
- Create/edit uses split-pane editor (write left, preview right)
- Editing creates new version (increment `version`, set `is_current`)
- Doc types: design, spec, guide, note, reference

#### Activity Sub-tab
- Timeline from `project_activity WHERE project_id = ?`
- Filter by activity_type
- Shows icon, description, timestamp, linked entity

### 2. Ideas Board

**New table**: `project_ideas`

```sql
CREATE TABLE project_ideas (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),        -- feature, improvement, research, integration
    priority INTEGER DEFAULT 5,   -- 1-10
    status VARCHAR(50) DEFAULT 'new',  -- new, exploring, approved, rejected, promoted
    tags TEXT[] DEFAULT '{}',
    promoted_to_project_id INTEGER REFERENCES unified_projects(id),
    metadata JSONB DEFAULT '{}',
    created_by_user_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**Status flow**: `new` → `exploring` → `approved` → `promoted` (or `rejected`)

**UI**:
- Card grid with title, description snippet, category badge, priority, status badge
- Filters: category, status, search
- Create modal: title, description, category, priority, tags
- Click to expand full detail (markdown rendered)
- "Promote to Project" button: creates unified_project, links back, changes status

### 3. Knowledge Tab Enhancements

- **Markdown rendering**: All content via `marked.js` (include DOMPurify for XSS safety)
- **Split-pane editor**: Create/edit modal full-width, write (left) + live preview (right)
- **Full CRUD**: Edit and delete buttons on each entry (endpoints already exist)
- **Roadmap quick-filter**: Pill button pre-filters to vault_notes tagged "roadmap"
- **Improved expand**: Shows markdown-rendered content, not `<pre>` plain text

### 4. Global Decisions Tab

- Surfaces all 92+ entries from `project_decisions`
- Card/list view with: decision_number, title, project_name, status, decided_at
- Click to expand: full markdown-rendered context, decision, alternatives, consequences
- Filters: project, status, search, tags
- Link to parent project (opens project detail view)
- Create decision modal with project selector

**Backend enhancement**: Extend `/api/decisions` with query params: `project_id`, `search`, `status`

### 5. System Tab (Merge)

Three collapsible sections:
1. **Integrations** — Health cards + MCP registry + Claude config
2. **Database Schema** — Master-detail table browser
3. **API Endpoints** — Grouped endpoint list with search

All open by default on desktop. Collapsed on mobile (374px).

### 6. Overview Enhancements

- Add "All Tasks" quick action → opens a modal or inline section with cross-project task list
- Update stat cards if needed (ideas count?)
- Activity feed unchanged

## New Dependencies

- `marked.js` (~40KB) — Markdown to HTML
- `DOMPurify` (~15KB) — Sanitize rendered HTML

Load via CDN or vendor into `/static/js/vendor/`.

## New API Endpoints

### Ideas
- `GET /api/ideas` — List with filters (category, status, search, limit, offset)
- `POST /api/ideas` — Create idea
- `PUT /api/ideas/<id>` — Update idea
- `DELETE /api/ideas/<id>` — Delete idea
- `POST /api/ideas/<id>/promote` — Promote to project

### Decisions (enhance existing)
- `GET /api/decisions` — Add params: project_id, search, status, limit, offset
- `POST /api/decisions` — Create decision
- `GET /api/decisions/<id>` — Detail view

### Project Documents (new, uses existing table)
- `GET /api/projects/<id>/docs` — List project documents
- `POST /api/projects/<id>/docs` — Create document
- `PUT /api/projects/<id>/docs/<doc_id>` — Update (creates new version)
- `GET /api/projects/<id>/docs/<doc_id>` — Get document detail
- `DELETE /api/projects/<id>/docs/<doc_id>` — Delete document

### Project Activity
- `GET /api/projects/<id>/activity` — Already partially exists, add activity_type filter

## Migration

```sql
-- 119_project_ideas.sql
CREATE TABLE IF NOT EXISTS project_ideas (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) DEFAULT 'feature',
    priority INTEGER DEFAULT 5,
    status VARCHAR(50) DEFAULT 'new',
    tags TEXT[] DEFAULT '{}',
    promoted_to_project_id INTEGER REFERENCES unified_projects(id),
    metadata JSONB DEFAULT '{}',
    created_by_user_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ideas_status ON project_ideas(status);
CREATE INDEX IF NOT EXISTS idx_ideas_category ON project_ideas(category);
```

## File Changes

| File | Change |
|------|--------|
| `platform_v2/tools/dev_hq/routes.py` | Add ideas CRUD, decisions CRUD, project docs CRUD, enhance existing endpoints |
| `platform_v2/static/js/devhq.js` | Rewrite: 6 tabs, project detail view, ideas board, markdown editor, split-pane |
| `platform_v2/templates/dev_hq.html` | Update HTML structure: 6 panels, project detail template, ideas cards, modals |
| `database/migrations/119_project_ideas.sql` | New ideas table |

## Implementation Order

1. DB migration (ideas table)
2. Backend routes (ideas CRUD, decisions enhancement, project docs)
3. Frontend restructure (6 tabs, HTML skeleton)
4. Project detail view with sub-tabs
5. Ideas board UI
6. Knowledge markdown + split-pane editor
7. Decisions global view
8. System tab merge
9. Overview adjustments
10. Testing & responsive verification
