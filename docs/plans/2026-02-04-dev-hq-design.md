# Dev HQ — Unified Development Command Center

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Mission Control with a header-level admin page that unifies project tracking, knowledge, and technical reference into one always-accessible view.

**Architecture:** Standalone Flask route (`/dev-hq`) with its own template, accessed via a compass icon in the base template header. Not a module — not in any category. Admin-only, Hub-only. Pulls from existing unified_projects, unified_tasks, knowledge_base, and project_decisions tables. Reuses DB Schema and API Docs logic from Blueprint.

**Tech Stack:** Flask route, Jinja2 template, vanilla JS (fetch API), existing ARCHIE CSS variables, Lucide icons, Orbitron + IBM Plex Mono fonts.

---

## What Changes

| Before | After |
|--------|-------|
| Mission Control (Blueprint) in AI Command category, 14+ tabs | **Removed from module grid entirely** |
| Health tab in Mission Control | **Moved to System Operations** module in Admin Ops |
| No header-level access to project tracking | **Compass icon in header** → full-page Dev HQ |
| Projects/tasks managed via MCP tools only | **Full CRUD in Dev HQ** Projects & Tasks tab |

## Page Access

- **Route:** `/dev-hq`
- **Access:** Admin role + Hub deployment mode only
- **Header icon:** Compass (Lucide `compass`) in top-right area of `base.html`, next to theme toggle
- **Tooltip:** "Dev HQ"
- **Visibility:** Conditionally rendered — hidden for non-admins and business nodes

## Tab Structure (6 tabs, horizontal top navigation)

### Tab 1: Overview
**Purpose:** At-a-glance dashboard — "how's the project doing?"

**Data sources:**
- `unified_projects` — count by status (active, completed, on_hold, archived)
- `unified_tasks` — open vs completed counts, overdue count
- `project_activity` — most recent 20 entries

**Layout:**
- **Stats row:** 4 stat cards (Active Projects, Open Tasks, Completed This Week, Overdue)
- **Recent Activity feed:** Timeline of last 20 project_activity entries (created, updated, completed, commented, assigned)
- **Project Health grid:** Small cards for each active project showing name, progress %, task completion ratio

**Actions:** Read-only. Clicking a project navigates to Projects & Tasks tab filtered to that project.

---

### Tab 2: Projects & Tasks
**Purpose:** Primary project management interface — "what are we working on?"

**Data sources:**
- `unified_projects` — all projects with metadata
- `unified_tasks` — tasks within each project
- `project_team` — team assignments
- Phase roadmap data from `phase_manager`

**Layout:**
- **Roadmap timeline** (top): Horizontal phase progress bar showing planned phases, current phase highlighted
- **Project list** (main): Card-based list of projects. Each card shows:
  - Project name, status badge, priority
  - Progress bar (tasks completed / total)
  - Assignees (avatars/initials)
  - Target date
  - Expandable task list underneath
- **Task list** (expanded): Table within each project card showing tasks with status, priority, assignee, due date
- **Filters bar:** Status, priority, type, assignee dropdowns

**Actions (Full CRUD):**
- Create new project (modal form: name, description, type, priority, target date)
- Edit project details (inline or modal)
- Change project status
- Create new task within a project (modal form: title, description, type, priority, assignee, due date)
- Edit task details
- Mark task complete / change status
- Assign/reassign team members
- Delete project or task (with confirmation)

---

### Tab 3: Knowledge
**Purpose:** All documented knowledge and decisions — "what do we know?"

**Data sources:**
- `knowledge_base` — all entries (3,390+)
- `project_decisions` — ADR records
- `project_documents` — versioned project docs

**Layout:**
- **Search bar** (top): Full-text search across all knowledge
- **Filter chips:** Category, tags, type (knowledge / decision / document), date range
- **Results list:** Cards showing title, category, tags, snippet, date, source
- **Detail view:** Clicking an entry shows full content in a right panel or expanded view
- **Decisions sub-section:** ADRs shown with status (proposed/accepted/deprecated), context, decision text, alternatives considered

**Actions:**
- Search and filter (read)
- View full entries (read)
- Link to source files where applicable (read)
- No create/edit — knowledge is managed through MCP tools and platform automation

---

### Tab 4: DB Schema
**Purpose:** Database reference — "what tables exist?"

**Data sources:** Live PostgreSQL introspection (reuse existing Blueprint `get_database_schema()` logic)

**Layout:**
- **Table list** (left): All tables with row counts, sorted alphabetically
- **Table detail** (right): Columns, types, nullable, defaults, indexes, foreign keys
- Same layout as current Mission Control DB tab

**Actions:** Read-only reference.

---

### Tab 5: API Docs
**Purpose:** REST endpoint reference — "what APIs exist?"

**Data sources:** Flask route introspection (reuse existing Blueprint `get_api_docs()` logic)

**Layout:**
- **Endpoint list** grouped by module/blueprint
- Each endpoint shows: method (GET/POST/PUT/DELETE), path, description, parameters
- Same layout as current Mission Control API Docs tab

**Actions:** Read-only reference.

---

### Tab 6: Integrations
**Purpose:** MCP server status, Claude configuration, and tool registry — "what's connected and how?"

**Data sources:**
- MCP server config (`.mcp.json`)
- `mcp_tool_definitions` table — registered tools
- `mcp_tool_usage` table — tool usage stats
- Claude config files (`.claude/settings.json`, `.claude/settings.local.json`)
- Custom commands directory (`platform_v2/.claude/commands/`)
- Hook scripts (`platform_v2/scripts/hooks/`)

**Layout:**
- **MCP Server Status panel:** Server name, transport type (stdio), entry point, environment vars (masked passwords), connection status
- **Tool Registry table:** All 71 MCP tools grouped by category (knowledge, creation, business, admin, advanced, claude_tools, project_tools). Each shows: name, category, description, usage count, last used
- **Claude Configuration panel:** Active plugins list, enabled MCP servers, permission summary, custom commands list with descriptions
- **Hooks panel:** Registered hooks (SessionStart, PreCompact, Stop) with script paths and what they do
- **CLAUDE.md Reference panel:** Shows what instructions Claude Code receives (read-only view of CLAUDE.md content), so the human can see exactly what Claude sees

**Actions:**
- Read-only for MCP and Claude config (changes happen in config files)
- View tool usage statistics
- View CLAUDE.md content as rendered markdown

---

## Header Integration

In `base.html`, add to the top-right header area (near theme toggle):

```html
{% if current_user and current_user.role == 'admin' and deployment_mode != 'business_node' %}
<a href="/dev-hq" class="header-dev-hq" title="Dev HQ">
    <i data-lucide="compass"></i>
</a>
{% endif %}
```

Styled as a small icon button matching the theme toggle size and style.

## Blueprint Module Disposition

1. **Remove `blueprint` from `module_registry.py`** — no longer appears in module grid
2. **Keep `blueprint/routes.py`** — API endpoints still serve DB Schema and API Docs data for Dev HQ to consume
3. **Move Health endpoints** — migrate health check logic to System Operations module
4. **Remove Blueprint template** (`templates/tools/blueprint.html`) — replaced by Dev HQ template
5. **Keep utility files** — `phase_manager.py`, `inventory_scanner.py`, `blueprint_intelligence.py` remain as library code consumed by Dev HQ routes

## File Plan

| File | Action |
|------|--------|
| `platform_v2/templates/dev_hq.html` | **CREATE** — New full-page template (6 tabs) |
| `platform_v2/tools/dev_hq/__init__.py` | **CREATE** — Flask Blueprint for `/dev-hq` route |
| `platform_v2/tools/dev_hq/routes.py` | **CREATE** — Routes for page + CRUD API endpoints |
| `platform_v2/templates/base.html` | **MODIFY** — Add compass icon to header |
| `platform_v2/app.py` | **MODIFY** — Register dev_hq blueprint |
| `platform_v2/module_registry.py` | **MODIFY** — Remove `blueprint` from AI_COMMAND |
| `platform_v2/rbac.py` | **MODIFY** — Remove blueprint permission, add dev_hq |
| `platform_v2/tools/blueprint/routes.py` | **MODIFY** — Keep DB Schema + API Docs endpoints, remove page route |
| `platform_v2/tools/system_operations/` | **MODIFY** — Add health check endpoints (moved from Blueprint) |
| `CLAUDE.md` | **MODIFY** — Update references from Mission Control to Dev HQ |
| `platform_v2/.claude/CLAUDE.md` | **MODIFY** — Update references from Mission Control to Dev HQ |

## API Endpoints (Dev HQ)

### Page
- `GET /dev-hq` — Render Dev HQ page

### Projects
- `GET /dev-hq/api/projects` — List all projects (with filters)
- `POST /dev-hq/api/projects` — Create project
- `GET /dev-hq/api/projects/<id>` — Get project detail
- `PUT /dev-hq/api/projects/<id>` — Update project
- `DELETE /dev-hq/api/projects/<id>` — Delete project

### Tasks
- `GET /dev-hq/api/projects/<id>/tasks` — List tasks for project
- `POST /dev-hq/api/projects/<id>/tasks` — Create task
- `PUT /dev-hq/api/tasks/<id>` — Update task
- `DELETE /dev-hq/api/tasks/<id>` — Delete task

### Knowledge
- `GET /dev-hq/api/knowledge` — Search/list knowledge entries
- `GET /dev-hq/api/decisions` — List project decisions

### Activity
- `GET /dev-hq/api/activity` — Recent activity feed

### Schema & Docs (proxied from Blueprint)
- `GET /dev-hq/api/schema` — Database schema
- `GET /dev-hq/api/docs` — API documentation

### Integrations
- `GET /dev-hq/api/mcp/status` — MCP server config and status
- `GET /dev-hq/api/mcp/tools` — All registered MCP tools with usage stats
- `GET /dev-hq/api/claude/config` — Claude configuration (plugins, settings, commands)
- `GET /dev-hq/api/claude/instructions` — CLAUDE.md content (rendered)

## Access Control

- All routes require `@login_required` + admin role check
- Template rendering checks `DEPLOYMENT_MODE` — returns 404 for business nodes
- Header icon uses Jinja2 conditional rendering
- API endpoints return 403 for non-admin users

## Design System

- Uses existing ARCHIE CSS variables (no new color palette)
- Orbitron font for headers, IBM Plex Mono for data
- Lucide icons throughout
- Dark/light mode via existing theme system
- Responsive: works on desktop and Fold5 (tabs scroll horizontally on mobile)
- Tab icons: layout-dashboard (Overview), folder-kanban (Projects & Tasks), book-open (Knowledge), database (DB Schema), file-code-2 (API Docs), plug (Integrations)

## Claude Configuration Updates

When Dev HQ replaces Mission Control, the following Claude-facing references must be updated:

### CLAUDE.md (both root and platform_v2)
- Architecture section: "Mission Control" → "Dev HQ" with new route `/dev-hq`
- Quick Reference: Blueprint URL → Dev HQ URL
- Source of Truth table: reference Dev HQ for project/knowledge access
- Skills list: remove `/archie-phase` if phase tracking moves to Dev HQ

### MCP Tool References
- MCP tools (`get_projects`, `create_task`, etc.) continue to work unchanged — they hit the database directly, not the UI
- No MCP tool changes needed — Dev HQ is a UI layer, MCP tools are the API layer
- Both Claude and human access the same underlying data through different interfaces
