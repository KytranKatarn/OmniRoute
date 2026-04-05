# Dev HQ + Consciousness Integration — Design Spec

**Date:** 2026-04-05
**Project:** #220 — Business Launch Readiness
**Task:** #1633 — Brainstorm: Dev HQ + Consciousness Module Integration
**Status:** Approved design, pending implementation

---

## Problem

Dev HQ (projects/tasks) and Consciousness (knowledge/analytics) are separate modules with minimal cross-referencing. Users and agents must switch between them to correlate project progress with knowledge state. There is no way to see which knowledge entries relate to which project, what knowledge gaps a project has, or which agents contributed to a project.

## Goals

1. **Unified dashboard** — Consciousness Dashboard tab becomes the single command center showing both project progress and knowledge/code health.
2. **Project-Knowledge linking** — Bidirectional, fully automatic linking between projects and knowledge entries via embeddings.
3. **Knowledge gap analysis** — Per-project completeness scoring highlighting missing docs, decisions, mistakes, and agent activity.
4. **Agent work mapping** — Bridge dispatch jobs and task assignments tied to specific projects with contribution tracking.

## Audience

- **Admin (human)** — Browser-based unified view during work sessions.
- **AI agents** — Same data via API endpoints for autonomous planning and dispatch decisions.

---

## Data Model

### New Table: `project_knowledge_links`

Junction table for many-to-many project ↔ knowledge relationships.

```sql
CREATE TABLE IF NOT EXISTS project_knowledge_links (
    id SERIAL PRIMARY KEY,
    project_id INT NOT NULL REFERENCES unified_projects(id) ON DELETE CASCADE,
    knowledge_id INT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    link_type VARCHAR(20) NOT NULL DEFAULT 'auto',  -- 'auto' | 'manual'
    confidence DECIMAL(3,2),                         -- 0.00-1.00 for auto-links
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, knowledge_id)
);

CREATE INDEX idx_pkl_project ON project_knowledge_links(project_id);
CREATE INDEX idx_pkl_knowledge ON project_knowledge_links(knowledge_id);
CREATE INDEX idx_pkl_link_type ON project_knowledge_links(link_type);
```

### Column Additions

**`unified_projects`:**
```sql
ALTER TABLE unified_projects ADD COLUMN IF NOT EXISTS embedding vector(768);
```

**`bridge_jobs`:**
```sql
ALTER TABLE bridge_jobs ADD COLUMN IF NOT EXISTS project_id INT REFERENCES unified_projects(id);
CREATE INDEX idx_bridge_jobs_project ON bridge_jobs(project_id);
```

**`unified_tasks`:**
```sql
ALTER TABLE unified_tasks ADD COLUMN IF NOT EXISTS assigned_agent INT REFERENCES agents(id);
CREATE INDEX idx_unified_tasks_agent ON unified_tasks(assigned_agent);
```

### Design Rationale

- **Junction table for knowledge:** A knowledge entry (shared utility doc, cross-cutting mistake) can relate to multiple projects.
- **Column for bridge_jobs:** A dispatch job belongs to exactly one project (or none).
- **Column for unified_tasks:** A task is assigned to exactly one agent (or none).

---

## Auto-Linker Job

### Registration

- **Job name:** `auto_link_knowledge_to_projects`
- **Location:** `agent_loop.py` (Autonomy module)
- **Interval:** Every 30 minutes (matches embedding loop cadence)
- **Tier:** 1 (no human approval needed)
- **Batch size:** 200 entries per run

### Algorithm

1. Query knowledge entries with no row in `project_knowledge_links` (unlinked).
2. Ensure all active projects have cached embeddings in `unified_projects.embedding`. Recompute from `name + description + tags` if stale or missing.
3. For each unlinked entry, compute cosine similarity between its embedding and all project embeddings.
4. If similarity > **0.70** threshold → insert link with `link_type='auto'` and `confidence=similarity_score`.
5. Boost confidence by +0.15 if explicit signals match: `knowledge_base.category` contains project slug, or tag overlap exists. Cap at 1.00.
6. Skip entries with no embedding (they'll be linked after the embedding loop processes them).

### Backfill (One-Time)

On first run, process all existing knowledge entries and bridge jobs. The job detects this automatically: if `project_knowledge_links` is empty and `knowledge_base` has entries, run full backfill in larger batches (500).

### Bridge Job Backfill

Also runs in the same job: scan `bridge_jobs` where `project_id IS NULL`, match job description/context against project names and tags. Lower threshold (0.60) since job descriptions are shorter.

---

## Knowledge Gap Analysis

### Per-Project Completeness Score

| Gap Type | Check | Weight |
|----------|-------|--------|
| No documentation | 0 linked `vault_note` entries | 30% |
| No mistakes logged | 0 linked `mistake_learned` entries | 20% |
| No code snippets | 0 linked `code_snippet` entries | 15% |
| No decisions | 0 rows in `project_decisions` for project | 20% |
| No agent activity | 0 `bridge_jobs` with this `project_id` | 15% |

**Scoring:** Each gap type contributes its weight when satisfied (has at least 1 entry). Total = sum of satisfied weights. Result: 0-100%.

**Threshold:** Projects below 50% flagged as "needs attention."

**Storage:** Computed on-demand via `get_project_knowledge_gaps(project_id)`. No new table — lightweight query across junction table + existing tables. Results are not cached (query is fast, data changes frequently).

---

## Consciousness Dashboard Expansion

### Panel 1: Project-Knowledge Map

- List of active projects showing: linked knowledge count, top 3 related KB entries, completeness ring.
- Click to expand: all linked knowledge grouped by type (docs, mistakes, snippets, github files).
- Badge indicators: auto-linked (teal) vs manually-linked (gold).
- Sorted by most recently active project first.

### Panel 2: Agent Contributions

- Per-project breakdown: which agents worked on it, dispatch job count, tasks completed.
- Sortable by project or by agent.
- Timeframe filter: last 7 days / 30 days / all time.
- "Top contributors" mini-leaderboard per project.

### Panel 3: Knowledge Gaps

- All active projects ranked by completeness score (lowest first — worst gaps on top).
- Each row: project name, completeness ring, missing gap types as colored chips.
- Quick-action buttons: "Add docs" (→ Knowledge tab), "Log decision" (→ Dev HQ), "Record mistake" (→ Knowledge tab).

### LCARS Styling

- Purple accent `#8b5cf6`, `cs-` CSS class prefix (matches existing Consciousness module).
- Completeness rings: use existing HoloSphere gradient style.
- Panels follow the existing Dashboard card layout pattern.
- Responsive breakpoints: 480px / 768px / 1024px.

---

## API Endpoints

For both browser and agent consumption. All require `@admin_required`.

### New Routes (in `consciousness/dashboard_routes.py`)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/dashboard/project-knowledge/<project_id>` | Linked knowledge entries + gap analysis for one project |
| GET | `/api/dashboard/agent-contributions/<project_id>` | Agent work stats (dispatch count, tasks completed) with optional `?days=7` filter |
| GET | `/api/dashboard/knowledge-gaps` | All active projects ranked by completeness score |
| POST | `/api/dashboard/link-knowledge` | Manual link: `{project_id, knowledge_id}` |
| DELETE | `/api/dashboard/unlink-knowledge/<link_id>` | Remove a link |

---

## Service Layer

### New: `services/knowledge_link_service.py`

| Function | Description |
|----------|-------------|
| `auto_link_knowledge(batch_size=200)` | Called by Autonomy job. Links unlinked entries. |
| `link_knowledge_to_project(knowledge_id, project_id, link_type='manual')` | Manual linking. |
| `unlink_knowledge(knowledge_id, project_id)` | Remove a link. |
| `get_project_knowledge(project_id, type_filter=None)` | All linked entries for a project. |
| `get_knowledge_projects(knowledge_id)` | Which projects a KB entry belongs to. |
| `get_project_knowledge_gaps(project_id)` | Gap analysis for one project. |
| `get_all_gaps(status='active')` | Ranked gap list for dashboard panel. |

### Modified: `services/project_service.py`

| Function | Description |
|----------|-------------|
| `get_project_embedding(project_id)` | Compute/cache embedding from name + description + tags. |
| `get_agent_contributions(project_id, days=None)` | Query `bridge_jobs` + `unified_tasks` for agent stats. |

### Modified: `ai_bridge/bridge_dispatcher.py`

- `dispatch()` and `dispatch_json()` accept optional `project_id` kwarg.
- When provided, written to `bridge_jobs.project_id`.
- No behavioral change if omitted (backward compatible).

---

## Autonomy Job Registration

```python
# In agent_loop.py, register with existing job pattern:
{
    'id': 'auto_link_knowledge_to_projects',
    'func': '_auto_link_knowledge_to_projects',
    'trigger': 'interval',
    'minutes': 30,
    'description': 'Auto-link knowledge entries to projects via embeddings',
    'tier': 1,
    'enabled': True
}
```

The job function lives in `agent_loop.py` and calls `knowledge_link_service.auto_link_knowledge()`.

---

## What Stays Unchanged

- **Knowledge creation flow** — Entries still created the same way. Auto-linker picks them up asynchronously.
- **Dev HQ project/task CRUD** — Unchanged. Reads benefit from new linked data.
- **Existing Consciousness tabs** — Knowledge, Team, GitHub, Languages all untouched. Only Dashboard tab expanded.
- **Existing embedding/analysis loops** — Continue running independently. Auto-linker depends on embeddings existing but doesn't modify them.
- **MCP tools** — Existing `search_knowledge`, `create_task`, etc. unchanged. New data available through existing query patterns.

---

## Migration Plan

Single idempotent migration file: `database/migrations/NNN_project_knowledge_links.sql`

1. Create `project_knowledge_links` table with indexes.
2. Add `embedding` column to `unified_projects`.
3. Add `project_id` column to `bridge_jobs` with index.
4. Add `assigned_agent` column to `unified_tasks` with index.
5. All statements use `IF NOT EXISTS` / `IF NOT EXISTS` for idempotency.

---

## File Summary

| Action | File |
|--------|------|
| Create | `database/migrations/NNN_project_knowledge_links.sql` |
| Create | `services/knowledge_link_service.py` |
| Create | `static/css/consciousness-dashboard-v2.css` |
| Create | `static/js/consciousness-dashboard-v2.js` |
| Modify | `tools/consciousness/dashboard_routes.py` (5 new endpoints) |
| Modify | `tools/consciousness/templates/consciousness.html` (3 new dashboard panels) |
| Modify | `services/project_service.py` (2 new functions) |
| Modify | `ai_bridge/bridge_dispatcher.py` (project_id kwarg) |
| Modify | `agent_loop.py` (register new job) |
