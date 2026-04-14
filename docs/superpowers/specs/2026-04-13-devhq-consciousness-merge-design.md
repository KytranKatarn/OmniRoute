# Dev HQ → Consciousness Merge — Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Decision:** Merge Dev HQ into Consciousness module as "Dev HQ" tab, replacing Intelligence tab.

---

## Motivation

Consolidate all platform awareness tools into a single Consciousness module. Currently Dev HQ (`/dev-hq`) and Consciousness (`/tools/consciousness/`) serve overlapping purposes — projects, knowledge, analytics. Merging them gives ARCHIE and Claude one location for full platform intelligence: knowledge base, projects, decisions, code health, translations, GitHub, and dev tools.

## Tab Layout (6 tabs, unchanged count)

| # | Tab | Icon | Content |
|---|-----|------|---------|
| 1 | Dashboard | `brain-cog` | Neural Core, HoloSphere, stats (existing) |
| 2 | **Dev HQ** | `terminal` | Projects, Ideas, Decisions, System, Intelligence analytics |
| 3 | Knowledge | `book-open` | Browser, Categories, Embeddings, Graph (existing) |
| 4 | GitHub | `git-branch` | Intake, Repos, Skills, Discovery (existing) |
| 5 | Languages | `languages` | Translation status, coverage, browser (existing) |
| 6 | Code Health | `activity` | System health, codebase, attention, repair bay (existing) |

## Dev HQ Tab — 5 Subtabs

### 1. Overview
- Platform stats dashboard (project count, task count, knowledge count, agent count)
- Quick-action buttons (New Project, New Idea, System)
- **Intelligence analytics (merged from Intelligence tab):**
  - Project-Knowledge Map — which projects have docs, mistakes, snippets
  - Knowledge Gaps — areas lacking documentation
  - Agent Contributions — which agents contributed to which projects (with time filter)
  - Agent Expertise — agent skill/knowledge matrix
  - Knowledge Graph — visual graph of knowledge relationships

### 2. Projects
- Project list with search/filter
- Project detail sub-view with 4 sub-tabs:
  - Tasks (CRUD, status tracking)
  - Decisions (per-project decisions)
  - Docs (per-project documentation)
  - Activity (recent activity feed)

### 3. Ideas
- Idea backlog list
- Create new ideas
- Promote idea to project

### 4. Decisions
- Architectural decision log (all decisions, not project-scoped)
- Create/view decisions with context

### 5. System
- MCP Integrations (servers, tools, usage stats)
- Database Schema (filterable table list)
- System Actions:
  - Clear cache
  - Warmup models
  - Reindex embeddings
  - Sync MCP tools

## Migration Plan

### What Moves Where

| Source | Destination |
|--------|-------------|
| `tools/dev_hq/routes.py` (API endpoints) | `tools/consciousness/devhq_routes.py` (new file, `register_devhq_routes(bp, admin_required)` pattern) |
| `templates/dev_hq.html` (template) | Inline into `consciousness_dashboard.html` as `panel-devhq` |
| `static/js/devhq.js` (JS) | Keep as separate JS file, loaded by Consciousness template |
| `tools/dev_hq/jobs.py` (6 background jobs) | `tools/department_hq/jobs.py` (new or merged) |
| Intelligence tab content (`panel-intelligence`) | Merged into Dev HQ Overview subtab |
| Intelligence JS (`consciousness-dashboard-v2.js`) | Merged into devhq.js or kept as-is, loaded when Dev HQ Overview active |

### What Gets Deleted

| Item | Reason |
|------|--------|
| `tools/dev_hq/__init__.py` | Module removed |
| `tools/dev_hq/routes.py` | Routes moved to Consciousness |
| `tools/dev_hq/jobs.py` | Jobs moved to Department HQ |
| `templates/dev_hq.html` | Template merged into Consciousness |
| `panel-intelligence` in `consciousness_dashboard.html` | Replaced by `panel-devhq` |
| Dev HQ entry in `module_registry.py` | Module no longer exists |
| Dev HQ entry in `rbac.py` | Module no longer exists |
| `/dev-hq` route | Clean removal, no redirect |

### What Gets Updated (Reference Audit)

All references to `/dev-hq` must be updated across:

- **CLAUDE.md** — Dev HQ quick reference URL, module list
- **Rules files** — `project-knowledge.md`, `session-protocol.md`, any mentioning Dev HQ
- **Skills** — `/archie-project`, `/archie-work`, `/checkpoint`, any skill referencing Dev HQ
- **Memory files** — `MEMORY.md`, any memory referencing Dev HQ workflows
- **MCP tool responses** — tools that return `/dev-hq` URLs in tips/links
- **Knowledge base entries** — vault notes referencing `/dev-hq`
- **`app.py`** — remove Dev HQ blueprint registration

### Dev HQ Knowledge Subtab — Dropped

Consciousness already has a full Knowledge tab with:
- Browser (search, filter by type)
- Categories grid
- Embedding coverage stats
- Knowledge graph visualization

Dev HQ's Knowledge subtab was a simpler duplicate. No features lost by dropping it.

## LCARS Frames

All Dev HQ subtab sections use the dashboard-style LCARS frame pattern (inline `!important` overrides). Color scheme:

| Section | Color | Hex |
|---------|-------|-----|
| Overview / Intelligence Analytics | Cyan | #22d3ee |
| Projects | Purple | #8b5cf6 |
| Ideas | Amber | #f59e0b |
| Decisions | Green | #10b981 |
| System | Cyan | #22d3ee |

## Route Pattern

New routes follow the Consciousness ADR-045 pattern:

```python
# tools/consciousness/devhq_routes.py
def register_devhq_routes(bp, admin_required):
    @bp.route("/api/devhq/overview")
    @admin_required
    def devhq_overview():
        ...

    @bp.route("/api/devhq/projects")
    @admin_required
    def devhq_projects():
        ...
```

API prefix changes from `/dev-hq/api/` to `/tools/consciousness/api/devhq/`.

## Background Jobs — Department HQ

6 jobs move to `tools/department_hq/jobs.py`:

| Job | Schedule | Why Dept HQ |
|-----|----------|-------------|
| Daily Code Health Scan | 2:00 AM | Operational platform maintenance |
| Daily Code Metrics Scan | 3:00 AM | Operational platform maintenance |
| Automated Module Audit + Repair Bay | 3:30 AM | Dispatch-driven (Bridge) |
| Pattern Compliance Check (ADR-013) | 4:00 AM | Compliance enforcement |
| Daily Code Health Digest (Telegram) | 8:00 AM | Notification pipeline |
| Competitor Landscape Scan | 14 days | Strategic ops |

## Success Criteria

1. All Dev HQ features accessible via Consciousness → Dev HQ tab
2. All 6 background jobs running from Department HQ
3. `/dev-hq` returns 404 (clean removal)
4. No broken references in skills, rules, memory, CLAUDE.md
5. All subtab sections have dashboard-style LCARS frames
6. `module_registry.py` and `rbac.py` updated (Dev HQ removed)
7. Intelligence analytics visible in Dev HQ Overview
