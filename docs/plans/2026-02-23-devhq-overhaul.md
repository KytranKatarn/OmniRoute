# Dev HQ Overhaul — Project-Centric Documentation Hub Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform Dev HQ from a 7-tab admin panel into a 6-tab documentation hub where Projects are the organizing unit, Ideas have a dedicated board, Decisions (ADRs) are visible, Knowledge supports markdown, and Schema/API/Integrations merge into System.

**Architecture:** Project-centric model where clicking a project opens a detail sub-view with 4 sub-tabs (Tasks, Decisions, Docs, Activity). New `project_ideas` table for lightweight idea tracking with promote-to-project workflow. Client-side markdown rendering via marked.js + DOMPurify. Existing `project_documents` table (empty, versioned) finally gets used.

**Tech Stack:** Flask/Python backend, vanilla JS frontend (IIFE pattern), PostgreSQL, marked.js + DOMPurify for markdown, LCARS design system (orange accent).

**Design doc:** `docs/plans/2026-02-23-devhq-overhaul-design.md`

**Security note:** All user-generated markdown content is sanitized with DOMPurify before DOM insertion. The `renderMd()` helper always wraps `marked.parse()` output through `DOMPurify.sanitize()`.

---

## Task 1: DB Migration — Ideas Table

**Files:**
- Create: `database/migrations/119_project_ideas.sql`

**Step 1: Write the migration**

```sql
-- 119_project_ideas.sql
-- Dev HQ Ideas Board — lightweight idea tracking with promote-to-project

BEGIN;

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

COMMIT;
```

**Step 2: Run migration**

Run: `docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/119_project_ideas.sql`

Note: The migrations directory is mounted at `/docker-entrypoint-initdb.d/migrations/` inside the container. Check `docker-compose.yml` for the exact volume mount path. If not mounted, copy file first:
`docker cp database/migrations/119_project_ideas.sql archie_database:/tmp/ && docker exec archie_database psql -U archie -d archie -f /tmp/119_project_ideas.sql`

Expected: `CREATE TABLE`, `CREATE INDEX` x2

**Step 3: Verify**

Run: `docker exec archie_database psql -U archie -d archie -c "\d project_ideas"`
Expected: Table with 12 columns

**Step 4: Commit**

```bash
git add database/migrations/119_project_ideas.sql
git commit -m "feat(db): migration 119 — project_ideas table for Dev HQ ideas board"
```

---

## Task 2: Backend — Ideas CRUD Endpoints

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py` (append after line 1049)

**Step 1: Add Ideas API endpoints**

Append to `routes.py` after the last endpoint. Follow existing patterns exactly (admin_hub_only decorator, get_db_connection context manager, RealDictCursor, try/except/finally with cur.close).

Add these endpoints:
- `GET /api/ideas` — List with filters (status, category, search, limit, offset). Returns `{success, ideas, total}`.
- `POST /api/ideas` — Create idea. Requires `title`. Optional: description, category, priority, tags. Sets `created_by_user_id = current_user.id`.
- `PUT /api/ideas/<id>` — Update idea. Accepts: title, description, category, priority, status, tags. Sets `updated_at = NOW()`.
- `DELETE /api/ideas/<id>` — Delete idea. Returns 404 if not found.
- `POST /api/ideas/<id>/promote` — Promote to project. Creates `unified_project` from idea fields, sets `promoted_to_project_id` on idea, changes idea status to `promoted`. Returns 400 if already promoted.

Follow the existing CRUD patterns in the same file (see `api_create_project`, `api_update_project`, etc.) for code style.

**Step 2: Verify syntax**

Run: `docker exec archie_platform python3 -c "from tools.dev_hq.routes import *; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "feat(dev-hq): ideas CRUD + promote-to-project API endpoints"
```

---

## Task 3: Backend — Enhanced Decisions + Project Docs Endpoints

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

**Step 1: Enhance existing `/api/decisions` endpoint**

Replace the existing `api_decisions()` function with a version that supports query params: `project_id`, `status`, `search`, `limit`, `offset`. Returns `{success, decisions, total}`.

**Step 2: Add new decisions endpoints**

- `GET /api/decisions/<id>` — Detail view. Joins with `unified_projects` for project_name.
- `POST /api/decisions` — Create decision. Auto-increments `decision_number` per project. Requires `title`. Optional: project_id, context, decision, alternatives, consequences, status, tags. Sets `decided_by_user_id`, `decided_at = NOW()`.

**Step 3: Add project document CRUD**

Uses existing `project_documents` table (15 columns, versioned, `content_format` defaults to `markdown`).

- `GET /api/projects/<id>/docs` — List current versions (`is_current = true`). Returns snippet (first 200 chars).
- `GET /api/projects/<id>/docs/<doc_id>` — Full document detail.
- `POST /api/projects/<id>/docs` — Create document. Requires `content`. Optional: doc_type, title, tags. Version starts at 1.
- `PUT /api/projects/<id>/docs/<doc_id>` — Update creates new version: marks old as `is_current = false`, inserts new row with `version + 1, is_current = true`.
- `DELETE /api/projects/<id>/docs/<doc_id>` — Delete document.

**Step 4: Verify syntax**

Run: `docker exec archie_platform python3 -c "from tools.dev_hq.routes import *; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "feat(dev-hq): enhanced decisions API + project documents CRUD endpoints"
```

---

## Task 4: Frontend — Vendor Libraries (marked.js + DOMPurify)

**Files:**
- Create: `platform_v2/static/js/vendor/marked.min.js`
- Create: `platform_v2/static/js/vendor/purify.min.js`

**Step 1: Download marked.js**

Run: `mkdir -p /mnt/archie_brain/platform_v2/static/js/vendor && curl -L https://cdn.jsdelivr.net/npm/marked@14.1.0/marked.min.js -o /mnt/archie_brain/platform_v2/static/js/vendor/marked.min.js`

If curl fails, fall back to CDN in the template:
```html
<script src="https://cdn.jsdelivr.net/npm/marked@14.1.0/marked.min.js"></script>
```

**Step 2: Download DOMPurify**

Run: `curl -L https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js -o /mnt/archie_brain/platform_v2/static/js/vendor/purify.min.js`

**Step 3: Verify files exist**

Run: `ls -la /mnt/archie_brain/platform_v2/static/js/vendor/`
Expected: Both files present, non-zero size

**Step 4: Commit**

```bash
git add platform_v2/static/js/vendor/
git commit -m "feat(dev-hq): vendor marked.js + DOMPurify for markdown rendering"
```

---

## Task 5: Frontend — HTML Template Restructure (6 Tabs)

**Files:**
- Modify: `platform_v2/templates/dev_hq.html` (rewrite content within `{% block content %}`)

This is a large task. Rewrite the HTML structure to support 6 tabs, the project detail sub-view, ideas board, and updated modals.

**Key structural changes:**

1. **Tab nav**: 6 tabs: overview, projects, ideas, knowledge, decisions, system
2. **Projects panel**: Contains both `#projectsView` (grid, visible by default) and `#projectDetail` (hidden, shown on project click). Detail has header + 4 sub-tabs (tasks, decisions, docs, activity).
3. **Ideas panel**: Filters + card grid + pagination
4. **Knowledge panel**: Same structure but knowledge modal upgraded to split-pane (textarea left, preview div right)
5. **Decisions panel**: Filters (project select, status, search) + list of decision cards
6. **System panel**: 3 collapsible sections wrapping existing integrations/schema/api content

**New CSS to add** (append to existing `<style>` block):
- `.devhq-split-editor` — `display: flex; gap: 16px;` left/right split for markdown editing
- `.devhq-split-editor .editor-pane, .devhq-split-editor .preview-pane` — `flex: 1; min-width: 0;`
- `.devhq-detail-header` — Project detail header with back button
- `.devhq-sub-tabs` — Smaller sub-tab navigation within project detail
- `.devhq-sub-panel` — Sub-panels within project detail
- `.devhq-idea-card` — Idea card styling (similar to project-card)
- `.devhq-decision-item` — Decision list item (similar to kb-item)
- `.devhq-collapsible-header` — Collapsible section header for System tab
- `.devhq-md-content` — Container for rendered markdown content

**New modals to add:**
- `#ideaModal` — Title, description (textarea), category (select), priority (1-10 select), tags (text input)
- `#decisionModal` — Title, project (select), context (textarea), decision (textarea), alternatives (textarea), consequences (textarea), status (select), tags
- `#projectDocModal` — Split-pane: title, doc_type (select), content textarea (left) + live preview (right), tags

**Script tags at bottom** (before `devhq.js`):
```html
<script src="/static/js/vendor/marked.min.js"></script>
<script src="/static/js/vendor/purify.min.js"></script>
<script src="/static/js/devhq.js"></script>
```

**Important patterns to preserve:**
- All inline `style=""` attributes (existing pattern)
- `data-i18n` attributes on visible text
- `onclick=""` handlers calling global functions
- Lucide icons via `<i data-lucide="icon-name">`
- Modal overlay pattern with backdrop click to close
- Responsive: `@media (max-width: 768px)` and `@media (max-width: 374px)`

**Step 1: Rewrite the template**

Preserve Jinja2 blocks, admin_ops_nav include. Update CSS, update HTML panels, add modals, add vendor scripts.

**Step 2: Verify template renders**

Check `docker logs --tail 20 archie_platform` for template errors after loading `/dev-hq`.

**Step 3: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): restructure HTML — 6 tabs, project detail, ideas, decisions, system"
```

---

## Task 6: Frontend — JavaScript Rewrite (All Controllers)

**Files:**
- Modify: `platform_v2/static/js/devhq.js` (full rewrite)

Rewrite the IIFE to handle 6 tabs plus the project detail sub-view. This is the largest task.

**Key sections to implement:**

### Utilities (preserve existing)
- `escHtml()`, `formatAge()`, `formatDate()`, `api()`, `refreshIcons()`, `closeModal()` — keep as-is

### New utility
- `renderMd(str)` — If marked.js and DOMPurify are available, returns `DOMPurify.sanitize(marked.parse(str))`. Otherwise falls back to `escHtml(str)`.

### State (update)
- Keep: `_cache`, `_taskState`, `_kbState`, `_schemaData`, `_apiData`
- Add: `_currentProject` (null or project object), `_ideasState` (page/limit/total), `_decisionsState` (page/limit/total)

### Tab system (update)
- `switchDevHQTab(tab)` — Handle 6 tabs: overview, projects, ideas, knowledge, decisions, system
- `loadTabData(tab)` — Map to: loadOverview, loadProjects, loadIdeas, loadKnowledge, loadDecisions, loadSystem

### Overview tab (minor update)
- Mostly unchanged. Add "All Tasks" in quick actions that triggers a modal or navigates

### Projects tab (major update)
- `loadProjects()` — Unchanged grid loader
- `openProjectDetail(projectId)` — Fetch project data, hide grid, show detail view, load default sub-tab (tasks)
- `closeProjectDetail()` — Hide detail, show grid
- `switchProjectSubTab(tab)` — Switch between tasks/decisions/docs/activity sub-tabs
- `loadProjectTasks(projectId)` — Tasks for this project (reuse task rendering logic)
- `loadProjectDecisions(projectId)` — Decisions from `/api/decisions?project_id=X`
- `loadProjectDocs(projectId)` — Documents from `/api/projects/X/docs`
- `loadProjectActivity(projectId)` — Activity from `/api/activity?project_id=X`  (note: may need to add project_id filter to the activity endpoint)
- Project card onclick should call `openProjectDetail(id)` instead of nothing
- `openProjectDocModal()`, `submitProjectDoc()` — Split-pane editor with live markdown preview

### Ideas tab (new)
- `loadIdeas()` — Fetch from `/api/ideas` with filters
- `renderIdeas(ideas, total)` — Card grid rendering
- `openIdeaModal(ideaId)` — Create/edit modal
- `submitIdea()` — POST or PUT
- `deleteIdea(id)` — DELETE with confirm
- `promoteIdea(id)` — POST `/api/ideas/id/promote` with confirm

### Knowledge tab (enhanced)
- `loadKnowledge()` — Unchanged
- `renderKnowledge()` — Add edit/delete buttons to each entry
- `toggleKbDetail()` — Use `renderMd()` instead of `escHtml()` for content display
- `openKbModal(entryId)` — If entryId provided, fetch and populate for editing. Modal now has split-pane layout with live preview.
- `submitKb()` — Handle both create and update
- `deleteKbEntry(id)` — DELETE `/api/docs/id` with confirm
- Add roadmap quick-filter button handler

### Decisions tab (new)
- `loadDecisions()` — Fetch from `/api/decisions` with filters (project, status, search)
- `renderDecisions(decisions, total)` — List with expand-to-detail
- `toggleDecisionDetail(el, id)` — Expand showing markdown-rendered context/decision/alternatives/consequences
- `openDecisionModal()` — Create decision with project selector
- `submitDecision()` — POST `/api/decisions`

### System tab (merged)
- `loadSystem()` — Calls `loadIntegrations()`, `loadSchema()`, `loadApiDocs()` (existing functions, but their target containers are now inside collapsible sections)
- `toggleSystemSection(sectionId)` — Toggle collapse/expand

### Init (update)
- DOMContentLoaded: set up all event listeners for 6 tabs
- Add filter listeners for Ideas (category, status, search)
- Add filter listeners for Decisions (project, status, search)
- Add split-pane preview listeners for knowledge modal and project doc modal
- Hash deep-linking: support `#projects/94` format for project detail

### Expose globals (update)
Add all new functions to `window.*`: `openProjectDetail`, `closeProjectDetail`, `switchProjectSubTab`, `openIdeaModal`, `submitIdea`, `deleteIdea`, `promoteIdea`, `openDecisionModal`, `submitDecision`, `toggleDecisionDetail`, `deleteKbEntry`, `openProjectDocModal`, `submitProjectDoc`, `toggleSystemSection`, etc.

**Step 1: Rewrite devhq.js**

Complete rewrite preserving IIFE wrapper and utility functions.

**Step 2: Verify no JS errors**

Open browser console at `/dev-hq`, verify all 6 tabs load without errors.

**Step 3: Commit**

```bash
git add platform_v2/static/js/devhq.js
git commit -m "feat(dev-hq): JS rewrite — 6 tabs, project detail, ideas, decisions, markdown"
```

---

## Task 7: Integration Testing — Ideas Board

**Step 1: Create an idea**

Open `/dev-hq#ideas`. Click "+ New Idea". Fill: title="Voice Assistant v2", description="Multi-language voice with emotion", category="feature", priority=8. Submit. Verify card appears.

**Step 2: Edit idea**

Click the idea. Verify detail. Change status to "exploring". Save. Verify badge updates.

**Step 3: Promote to project**

Click "Promote" on the idea. Confirm dialog. Verify:
- Idea status → "promoted" with link
- New project in Projects tab
- DB check: `SELECT id, title, status, promoted_to_project_id FROM project_ideas ORDER BY id DESC LIMIT 3;`

**Step 4: Fix any issues, commit**

---

## Task 8: Integration Testing — Project Detail + Docs

**Step 1: Open project detail**

Click any project card. Verify detail view loads with 4 sub-tabs.

**Step 2: Create a project document**

Switch to Docs sub-tab. Click "+ New Doc". Use split-pane editor:
- Title: "Architecture Overview"
- Doc type: "design"
- Content: Write some markdown with headings, code blocks, lists
- Verify live preview on right

Submit. Verify doc appears in list.

**Step 3: Edit document (version test)**

Edit the doc. Change content. Submit. Verify:
- New version created (version 2)
- Old version marked `is_current = false`
- DB: `SELECT id, title, version, is_current FROM project_documents ORDER BY id DESC LIMIT 5;`

**Step 4: Test decisions within project**

Switch to Decisions sub-tab. Create a decision. Verify it appears both here AND in the global Decisions tab.

**Step 5: Fix any issues, commit**

---

## Task 9: Integration Testing — Knowledge + Decisions + System

**Step 1: Knowledge markdown**

Open Knowledge tab. Click any entry. Verify content renders with markdown formatting (headings, bold, code blocks).

**Step 2: Knowledge edit/delete**

Click edit on an entry. Verify modal populates. Make a change, save. Verify update persists. Test delete on a test entry.

**Step 3: Roadmap filter**

Click "Roadmaps" button. Verify list filters to vault_notes with roadmap tags.

**Step 4: Global Decisions**

Open Decisions tab. Verify all 92+ decisions load. Filter by project. Filter by search. Expand a decision — verify markdown rendering.

**Step 5: System tab**

Open System tab. Verify 3 sections visible. Toggle collapse. Verify Schema table detail still works. Verify API search still works.

**Step 6: Fix any issues, commit**

---

## Task 10: Responsive Verification + Final Polish

**Step 1: Test at 374px (Fold closed)**

Check all 6 tabs. Key items:
- Tab nav shows icons only (text hidden)
- Stat cards 2-column grid
- Project cards stack to 1 column
- Idea cards stack to 1 column
- Split-pane editor stacks vertically
- System sections are collapsible

**Step 2: Test at 717px (Fold open)**

Verify intermediate layout works.

**Step 3: Test at 1280px (Desktop)**

Verify full layout with side-by-side grids, split-pane editor, etc.

**Step 4: Fix responsive issues**

Add/update CSS media queries as needed.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat(dev-hq): complete overhaul — project-centric hub with ideas, decisions, markdown editor

6-tab restructure: Overview, Projects (detail sub-view), Ideas board,
Knowledge (markdown + split-pane editor), Decisions (global ADR browser),
System (merged Schema + API + Integrations).

New: project_ideas table, project_documents CRUD, enhanced decisions API,
marked.js + DOMPurify for markdown, split-pane editor, promote-to-project.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Push + Dev HQ Tracking Updates

**Step 1: Push**

Run: `git push`

**Step 2: Complete task #638**

MCP: `complete_task(task_id=638, notes="Full overhaul: 6-tab project-centric hub with ideas board, decisions browser, markdown editor, project detail sub-view, system merge")`

**Step 3: Log decision**

MCP: `log_decision(project_id=94, title="ADR-032: Dev HQ Project-Centric Architecture")`

**Step 4: Update project understanding**

MCP: `update_project_understanding(project_id=94)`

**Step 5: Update MEMORY.md**

Add Dev HQ overhaul patterns and gotchas.
