# Consciousness Module Full Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Full LCARS visual redesign of the Consciousness module — ARCHIE's brain — consolidating 9 tabs to 7, splitting routes into focused files, adding cross-module integration, and completing i18n translations.

**Architecture:** Split the monolithic 9,844-line `routes.py` into 7 focused route files registered via the existing Blueprint. Rebuild the 1,980-line template with LCARS gold-standard patterns (framed header, icon nav, stat cards, responsive grids). Create external `consciousness.js` following the `devhq.js` pattern (api helper, tab switching, lazy loading). Add new Integration tab for cross-module health monitoring and ADR-013 pipeline verification.

**Tech Stack:** Flask/Jinja2, PostgreSQL (psycopg2 RealDictCursor), Lucide icons, Chart.js, vanilla JS, Playwright for testing.

**Design Doc:** `docs/plans/2026-02-23-consciousness-redesign-design.md`

**XSS Safety:** All DOM rendering uses the `setHtml()` + `escHtml()` pattern from devhq.js. All user content is escaped via `escHtml()` before rendering. This is the established gold-standard pattern.

---

## Critical DB Naming Gotchas

These were confirmed via live DB inspection. **Do NOT guess table/column names:**

| Expected | Actual |
|----------|--------|
| `agent_emotional_states` | `agent_emotional_state` (SINGULAR) |
| `station_agents` | `station_assignments` |
| `agent_personalities` | Does NOT exist — use `agent_identity` |
| `agent_ethics_constraints` | Does NOT exist |
| `github_indexed_files` | Does NOT exist — files are in `knowledge_base` by `knowledge_type` |
| `agent_activity_log` | `agent_activity_events` |
| `agent_emotional_state.created_at` | `agent_emotional_state.timestamp` |
| `agent_rest_cycles.timestamp` | `agent_rest_cycles.started_at` |

**Row counts:** 10 agents, 85 skills, 9 emotional states, 1 voice profile, 12,766 active KB entries, 2,238 translations, 24 stations, 10 assignments, 13 GitHub repos.

---

## Current State Reference

**Blueprint:** `consciousness_bp` in `/mnt/archie_brain/platform_v2/tools/consciousness/__init__.py`
- `url_prefix="/tools/consciousness"`
- `template_folder="templates"`
- Nested `processing_bp` sub-blueprint

**Current route file:** `/mnt/archie_brain/platform_v2/tools/consciousness/routes.py` (9,844 lines, ~51 endpoints)

**Current template:** `/mnt/archie_brain/platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (1,980 lines)

**Current tabs (9):** overview, chat, emotional, processing, github, brain, feed, voice, languages

**Target tabs (7):** dashboard, knowledge, team, insights, languages, github, integration

---

### Task 1: Split Routes — Extract Knowledge Endpoints

**Files:**
- Create: `platform_v2/tools/consciousness/knowledge_routes.py`
- Modify: `platform_v2/tools/consciousness/routes.py`
- Modify: `platform_v2/tools/consciousness/__init__.py`

**Context:** The current routes.py has all 51 endpoints in one file. We split without changing functionality. Knowledge endpoints handle KB CRUD, search, categories, ingestion, and unified search.

**Step 1: Create `knowledge_routes.py` with knowledge endpoints**

Extract these routes from `routes.py` into a new file:
- `/knowledge/create` (POST)
- `/knowledge/<int:knowledge_id>` (GET)
- `/knowledge/list` (GET)
- `/knowledge/categories` (GET)
- `/search` (POST)
- `/unified/search` (POST)
- `/unified/stats` (GET)
- `/unified/agent-context` (POST)
- `/unified/check-mistakes` (POST)
- `/ingest-text` (POST)
- `/ingest-directory` (POST)
- `/browse-files` (POST)
- `/view-file` (POST)
- `/ingest-all-docs` (POST)

Structure:
```python
"""Knowledge Routes — KB CRUD, search, ingestion"""
from flask import jsonify, request
from flask_login import login_required
from psycopg2.extras import RealDictCursor
from database import get_db_connection

def register_knowledge_routes(bp, admin_required):
    """Register all knowledge-related routes on the consciousness blueprint."""

    @bp.route("/knowledge/create", methods=["POST"])
    @login_required
    @admin_required
    def knowledge_create():
        # ... existing implementation moved here ...
```

**Step 2: Register in `__init__.py`**

Add after `from . import routes`:
```python
from .knowledge_routes import register_knowledge_routes
register_knowledge_routes(consciousness_bp, admin_required)
```

Where `admin_required` is imported from routes.py or defined in a shared utils file.

**Step 3: Remove extracted routes from `routes.py`**

Delete the functions that were moved to `knowledge_routes.py`. Leave a comment: `# Knowledge routes moved to knowledge_routes.py`

**Step 4: Test endpoints still work**

```bash
docker compose restart archie_platform
# Wait 10s for startup
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/knowledge/list | python3 -m json.tool | head -5
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/knowledge/categories | python3 -m json.tool | head -5
```

Expected: JSON responses with `knowledge_base` data (not 404 or 500).

**Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/knowledge_routes.py platform_v2/tools/consciousness/routes.py platform_v2/tools/consciousness/__init__.py
git commit -m "refactor(consciousness): extract knowledge routes to knowledge_routes.py"
```

---

### Task 2: Split Routes — Extract Team, Insights, GitHub, Integration Endpoints

**Files:**
- Create: `platform_v2/tools/consciousness/team_routes.py`
- Create: `platform_v2/tools/consciousness/insights_routes.py`
- Create: `platform_v2/tools/consciousness/github_routes.py`
- Create: `platform_v2/tools/consciousness/integration_routes.py`
- Modify: `platform_v2/tools/consciousness/routes.py`
- Modify: `platform_v2/tools/consciousness/__init__.py`

**Step 1: Create `team_routes.py`**

Extract agent/team endpoints:
- `/team` (GET)
- `/team/agents` (GET)
- `/team/agents/<int:agent_id>` (GET)
- `/team/agents/<int:agent_id>/performance` (GET)
- `/team/leaderboard` (GET)
- `/team-awareness-data` (GET)
- `/emotions/timeline` (GET)
- `/emotional-state` (GET)

Same pattern as Task 1: `register_team_routes(bp, admin_required)`.

**Step 2: Create `insights_routes.py`**

Extract analytics/sessions/improvements endpoints:
- `/analytics` (GET)
- `/analytics/knowledge-growth` (GET)
- `/improvements` (GET)
- `/sessions` (GET)
- `/sessions/<int:session_id>` (GET)
- `/learning-patterns` (GET)
- `/experiences` (GET)
- `/work-context` (GET)

**Step 3: Create `github_routes.py`**

Extract GitHub-related endpoints. If minimal in main routes.py, create with placeholder and any existing GitHub endpoints.

**Step 4: Create `integration_routes.py`**

This is the NEW Integration tab. Create with initial endpoints:
```python
def register_integration_routes(bp, admin_required):

    @bp.route("/api/integration/health")
    @login_required
    @admin_required
    def integration_health():
        """Cross-module health status"""
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # Check Dev HQ: active projects count
            cur.execute("SELECT count(*) as cnt FROM unified_projects WHERE status = 'active'")
            devhq = cur.fetchone()
            # Check Bridge: active stations
            cur.execute("SELECT count(*) as cnt FROM bridge_stations WHERE is_active = true")
            bridge = cur.fetchone()
            # Check Ollama
            ollama_ok = False
            try:
                import urllib.request
                ollama_host = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
                if not ollama_host.startswith("http"):
                    ollama_host = "http://" + ollama_host
                req = urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=3)
                ollama_ok = req.status == 200
            except Exception:
                pass
            # Check GitHub repos
            cur.execute("SELECT count(*) as cnt FROM github_repositories WHERE indexed = true")
            github = cur.fetchone()
            return jsonify({
                "success": True,
                "systems": {
                    "devhq": {"status": "online", "projects": devhq["cnt"]},
                    "bridge": {"status": "online", "stations": bridge["cnt"]},
                    "ollama": {"status": "online" if ollama_ok else "offline"},
                    "github": {"status": "online", "repos": github["cnt"]},
                }
            })
```

**Step 5: Register all new route files in `__init__.py`**

```python
from .knowledge_routes import register_knowledge_routes
from .team_routes import register_team_routes
from .insights_routes import register_insights_routes
from .github_routes import register_github_routes
from .integration_routes import register_integration_routes

register_knowledge_routes(consciousness_bp, admin_required)
register_team_routes(consciousness_bp, admin_required)
register_insights_routes(consciousness_bp, admin_required)
register_github_routes(consciousness_bp, admin_required)
register_integration_routes(consciousness_bp, admin_required)
```

**Step 6: Remove extracted routes from `routes.py`, test, commit**

```bash
docker compose restart archie_platform
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/team/agents | python3 -m json.tool | head -5
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/api/integration/health | python3 -m json.tool
```

```bash
git add platform_v2/tools/consciousness/
git commit -m "refactor(consciousness): extract team, insights, github, integration routes"
```

---

### Task 3: Slim Down Main routes.py — Dashboard API Endpoints

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py`

**Context:** After Tasks 1-2, `routes.py` should only contain: the main page route (`/`), the `admin_required` decorator, shared helpers, and remaining endpoints (stats, charts-data, brain-state, memory CRUD, backup). Now add new Dashboard API endpoint.

**Step 1: Add Dashboard summary API endpoint**

This is ARCHIE's self-portrait data. Add to `routes.py`:

```python
@consciousness_bp.route("/api/dashboard/summary")
@login_required
@admin_required
def api_dashboard_summary():
    """ARCHIE's self-portrait — aggregated stats for dashboard."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Knowledge stats
        cur.execute("""
            SELECT
                count(*) as total,
                count(*) FILTER (WHERE embedding IS NOT NULL) as embedded,
                count(DISTINCT category) as categories
            FROM knowledge_base
            WHERE knowledge_type != 'archie_v1'
        """)
        knowledge = cur.fetchone()

        # Agent fleet
        cur.execute("""
            SELECT count(*) as total,
                   count(*) FILTER (WHERE status = 'active') as active
            FROM agent_profiles
        """)
        agents = cur.fetchone()

        # Agent wellness (avg mood/energy/stress)
        cur.execute("""
            SELECT
                avg(energy_level) as avg_energy,
                avg(stress_level) as avg_stress,
                avg(mood_intensity) as avg_mood
            FROM agent_emotional_state
        """)
        wellness = cur.fetchone()

        # Projects (from Dev HQ)
        cur.execute("""
            SELECT
                count(*) FILTER (WHERE status = 'active') as active,
                count(*) FILTER (WHERE status = 'completed') as completed
            FROM unified_projects
        """)
        projects = cur.fetchone()

        # Tasks
        cur.execute("""
            SELECT
                count(*) FILTER (WHERE status = 'in_progress') as in_progress,
                count(*) FILTER (WHERE status = 'completed') as done,
                count(*) as total
            FROM unified_tasks
        """)
        tasks = cur.fetchone()

        # Recent activity (blended feed — last 24h)
        cur.execute("""
            (SELECT 'knowledge' as source, title as description,
                    created_at, 'book-open' as icon
             FROM knowledge_base
             WHERE knowledge_type != 'archie_v1'
             ORDER BY created_at DESC LIMIT 5)
            UNION ALL
            (SELECT 'bridge' as source, prompt_summary as description,
                    created_at, 'radio' as icon
             FROM bridge_interaction_log
             ORDER BY created_at DESC LIMIT 5)
            UNION ALL
            (SELECT 'project' as source, title as description,
                    created_at, 'folder-kanban' as icon
             FROM unified_tasks
             WHERE status = 'completed'
             ORDER BY created_at DESC LIMIT 5)
            ORDER BY created_at DESC LIMIT 15
        """)
        activity = cur.fetchall()

        # Integration health (quick check)
        cur.execute("SELECT count(*) as cnt FROM bridge_stations WHERE is_active = true")
        stations = cur.fetchone()

        embed_pct = 0
        if knowledge["total"] > 0:
            embed_pct = round(100.0 * knowledge["embedded"] / knowledge["total"], 1)

        return jsonify({
            "success": True,
            "knowledge": {
                "total": knowledge["total"],
                "embedded": knowledge["embedded"],
                "embed_pct": embed_pct,
                "categories": knowledge["categories"],
            },
            "agents": {
                "total": agents["total"],
                "active": agents["active"],
                "avg_energy": float(wellness["avg_energy"] or 0),
                "avg_stress": float(wellness["avg_stress"] or 0),
                "avg_mood": float(wellness["avg_mood"] or 0),
            },
            "projects": {
                "active": projects["active"],
                "completed": projects["completed"],
                "tasks_in_progress": tasks["in_progress"],
                "tasks_done": tasks["done"],
                "tasks_total": tasks["total"],
            },
            "activity": [dict(r) for r in activity],
            "stations_active": stations["cnt"],
        })
```

**Step 2: Test the endpoint**

```bash
docker compose restart archie_platform
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/api/dashboard/summary | python3 -m json.tool
```

Expected: JSON with knowledge, agents, projects, activity data.

**Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "feat(consciousness): add dashboard summary API — ARCHIE's self-portrait"
```

---

### Task 4: Create External JavaScript — `consciousness.js`

**Files:**
- Create: `platform_v2/static/js/consciousness.js`

**Context:** Follow the `devhq.js` gold-standard pattern exactly. This JS file handles all tab switching, API calls, and DOM rendering. All user content is escaped via `escHtml()` before rendering.

**Step 1: Create the JS file with core infrastructure**

Create `consciousness.js` with:
- `escHtml(str)` — DOM-based text escaping (prevents XSS)
- `setHtml(el, html)` — safe DOM update wrapper (only used with pre-escaped content)
- `formatAge(dateStr)` — human-readable timestamps
- `refreshIcons()` — Lucide icon refresh after DOM updates
- `debounceReload(tabName, fn)` — debounced tab reload
- `api(path, opts)` — fetch wrapper that prepends `/tools/consciousness`
- `switchConsciousnessTab(tab)` — tab switching with URL hash + lazy loading
- `loadTabData(tab)` — dispatcher with cache check
- `loadDashboard()` — populates stat cards, activity feed, wellness bars
- Stub functions for other tabs (filled in subsequent tasks)
- DOMContentLoaded handler with hash-based deep linking

The `api()` helper prepends `/tools/consciousness` to all paths:
```javascript
function api(path, opts) {
  opts = opts || {};
  var url = "/tools/consciousness" + path;
  // ... fetch with JSON content-type ...
}
```

**Step 2: Commit**

```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): create external consciousness.js with tab system + dashboard loader"
```

---

### Task 5: Rebuild HTML Template — LCARS Structure + Dashboard Tab

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Context:** Replace the entire 1,980-line template with a new LCARS gold-standard layout. Start with the header, tab nav, and Dashboard tab content. Other tabs get placeholder panels.

**Step 1: Write the new template**

The template must include:
- Base template extension or existing pattern (check current template's extends/block)
- Admin nav include: `{% include 'includes/admin_ops_nav.html' %}`
- Full CSS block with LCARS styling (prefix `cs-` for consciousness)
- Accent color: `#8b5cf6` (violet/purple) — differentiates from Dev HQ orange and Bridge blue
- LCARS framed header with brain icon, title "CONSCIOUSNESS", subtitle "A.R.C.H.I.E. Neural Core"
- Header status bar: Knowledge count, Agent count, Translation count
- 7-tab navigation with Lucide icons and `data-i18n` attributes
- Dashboard panel with: 4 stat cards (Knowledge, Agent Fleet, Projects, Stations), Activity feed, Fleet Wellness bars, Integration Health
- Placeholder panels for other 6 tabs
- Script includes: Chart.js CDN + consciousness.js

CSS classes follow `cs-` prefix pattern (matching `devhq-` convention):
- `.cs-header` — LCARS framed header
- `.cs-tabs` / `.cs-tab` — Tab navigation
- `.cs-panel` — Tab content panels
- `.cs-stats` / `.cs-stat` — Stat card grid (4 columns, colored top border)
- `.cs-card` — Content cards
- `.cs-agent-card` — Agent roster cards
- `.cs-modal-overlay` / `.cs-modal` — Modal dialogs
- `.cs-table` — Data tables
- `.cs-badge` — Status badges
- `.cs-wellness-row` / `.cs-wellness-bar` — Wellness indicator bars

Responsive: Mobile-first with breakpoints at 480px, 768px, 1280px.
Full i18n: All user-facing strings have `data-i18n` attributes.

**Step 2: Verify the page loads**

```bash
docker compose restart archie_platform
```

Navigate to http://192.168.1.200:3000/tools/consciousness — should show LCARS header, 7 tabs, Dashboard with stat cards loading data.

**Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): rebuild template with LCARS header, 7-tab nav, dashboard panel"
```

---

### Task 6: Dashboard Tab — Wellness Bars + Integration Health Cards

**Files:**
- Modify: `platform_v2/static/js/consciousness.js` (enhance `loadDashboard`)
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (add integration health section)

**Step 1: Add integration health cards to Dashboard panel HTML**

After the activity + wellness grid, add a third card section for integration health badges.

**Step 2: Update `loadDashboard()` in consciousness.js**

Add wellness bar width updates (set style.width based on percentage) and load integration health via the `/api/integration/health` endpoint. Render status badges with green/red dots.

**Step 3: Test and commit**

```bash
docker compose restart archie_platform
git add platform_v2/static/js/consciousness.js platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): dashboard wellness bars + integration health cards"
```

---

### Task 7: Team Tab — Agent API Endpoints

**Files:**
- Modify: `platform_v2/tools/consciousness/team_routes.py`

**Context:** The Team tab needs rich agent data. Add new API endpoints that return personnel-file-level data including skills, emotions, voice, and station assignments.

**Step 1: Add comprehensive agent roster endpoint `/api/team/roster`**

Query `agent_profiles` LEFT JOIN `agent_emotional_state` ON agent_id, LEFT JOIN `agent_voice_profiles` ON agent_id (where is_active=true), LEFT JOIN `station_assignments` ON agent_id (where is_active=true), LEFT JOIN `bridge_stations` ON station_id. Also query `agent_skills` grouped by agent_id and attach as nested array.

**Step 2: Add agent detail endpoint `/api/team/agents/<id>/profile`**

Full personnel file: base profile, identity traits (from `agent_identity`), skills with proficiency, emotional history (last 30 from `agent_emotional_state`), voice profile, learning log, rest cycles, station assignment.

**Step 3: Test endpoints**

```bash
docker compose restart archie_platform
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/api/team/roster | python3 -m json.tool | head -20
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/consciousness/api/team/agents/1/profile | python3 -m json.tool | head -20
```

**Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/team_routes.py
git commit -m "feat(consciousness): team roster + agent profile detail API endpoints"
```

---

### Task 8: Knowledge Tab — HTML + JS

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (Knowledge panel HTML)
- Modify: `platform_v2/static/js/consciousness.js` (loadKnowledge)

**Step 1: Add Knowledge panel HTML**

Replace the placeholder `panel-knowledge` div with sub-tabs: Browser, Processing, Categories, Embeddings.

Include:
- Sub-tab buttons (`.cs-subtab`)
- Browser: search input + filter selects (type, category) + table container
- Processing: queue status card + progress bar
- Categories: category grid
- Embeddings: coverage stat + batch action buttons

**Step 2: Implement `loadKnowledge()` in consciousness.js**

- `loadKnowledgeBrowser()`: fetches `/knowledge/list?limit=50` with type/search filters, renders table rows with title, type badge, category, embedding status, created date. Each row clickable.
- `loadProcessingStatus()`: fetches `/processing/status` and `/processing/embedding-coverage`
- `loadCategories()`: fetches `/knowledge/categories`, renders category cards with counts

Use existing endpoints from the extracted knowledge_routes.py.

**Step 3: Wire sub-tab switching**

Add sub-tab click handlers that show/hide sub-panels within the Knowledge tab.

**Step 4: Test and commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): knowledge tab — browser, processing, categories, embeddings"
```

---

### Task 9: Team Tab — HTML + JS

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (Team panel)
- Modify: `platform_v2/static/js/consciousness.js` (loadTeam)

**Step 1: Add Team panel HTML**

Replace placeholder with:
- Agent roster grid container (`.cs-agent-grid`)
- Agent profile modal (hidden by default) with overlay, header, scrollable body

**Step 2: Implement `loadTeam()` in consciousness.js**

Fetch `/api/team/roster`, render agent cards with: avatar initial, full name, title, station badge (links to Bridge), mood badge (color-coded), skill count, voice engine indicator, mini energy/stress bars.

**Step 3: Implement `showAgentProfile(agentId)` function**

Fetch `/api/team/agents/{id}/profile`, populate modal with: identity section, skills grid (dot-based proficiency), station assignment with Bridge cross-link, voice DNA info. Show modal overlay.

**Step 4: Add `closeAgentModal()` function**

Hides the modal overlay.

**Step 5: Test and commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): team tab — agent roster grid + profile modal with Bridge cross-links"
```

---

### Task 10: Insights Tab — HTML + JS + API

**Files:**
- Modify: `platform_v2/tools/consciousness/insights_routes.py`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add insights summary API endpoint**

In `insights_routes.py`, add `/api/insights/summary` that returns:
- Bridge interaction stats (last 7 days): count, avg time, total tokens, models used
- Knowledge growth (new entries last 7 days)
- Improvement proposals grouped by status (from `improvement_proposals` table)

**Step 2: Add Insights panel HTML with sub-tabs**

Analytics | Sessions | Improvements sub-tabs. Analytics shows stat cards + trend info. Sessions shows a list. Improvements shows proposal cards.

**Step 3: Implement `loadInsights()` in consciousness.js**

Fetch summary data, populate stat cards and lists.

**Step 4: Test and commit**

```bash
git add platform_v2/tools/consciousness/insights_routes.py platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): insights tab — analytics, sessions, improvements"
```

---

### Task 11: Languages Tab — HTML + JS

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

**Context:** The Languages tab already has extensive functionality. We rebuild it with LCARS styling while preserving the 4 sub-tabs: Dashboard, Browser, Review, Glossary.

**Step 1: Add Languages panel HTML**

Sub-tabs: Dashboard | Browser | Review | Glossary. Include:
- Dashboard: coverage cards per module, overall stats, "Generate Missing" buttons
- Browser: translation table with filters (language, module, status, search)
- Review: pending review queue with approve/reject buttons
- Glossary: translation memory list

**Step 2: Implement `loadLanguages()` in consciousness.js**

Use existing translation API endpoints. The Languages tab should query:
- Translation stats/coverage
- Translation list with filters
- Module coverage breakdown

Port key features from old template: language selector dropdown, inline editing, bulk generation.

**Step 3: Test and commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): languages tab — LCARS rebuild with 4 sub-tabs"
```

---

### Task 12: GitHub Tab — HTML + JS + API

**Files:**
- Modify: `platform_v2/tools/consciousness/github_routes.py`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add GitHub API endpoints**

`/api/github/repos` — returns list from `github_repositories` table with id, name, type, path, status, indexed count, indexed_at.

**Step 2: Add GitHub panel HTML**

Sub-tabs: Repos | Search. Repo cards with indexed count, status badge, re-index button. Search input with results.

**Step 3: Implement `loadGitHub()` in consciousness.js**

Fetch repo list, render cards. Port search functionality from existing template.

**Step 4: Test and commit**

```bash
git add platform_v2/tools/consciousness/github_routes.py platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): github tab — repo list, search, re-index"
```

---

### Task 13: Integration Tab — HTML + JS + Pipeline Monitor

**Files:**
- Modify: `platform_v2/tools/consciousness/integration_routes.py`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add pipeline test endpoint**

`/api/integration/test-pipeline` (POST) — calls `translate_text("Hello, how are you?", "fr")` from translation_service, then checks `bridge_interaction_log` for a matching log entry. Returns step-by-step results with status, latency, model used.

**Step 2: Add Dev HQ summary endpoint**

`/api/integration/devhq-summary` — returns last 5 projects and last 5 decisions from `unified_projects` and `project_decisions`.

**Step 3: Add Integration panel HTML**

Three sections:
- System Health: status badges for each connected system (uses `/api/integration/health`)
- Translation Pipeline Monitor: visual pipeline diagram + "Test Pipeline" button + results area
- Cross-Module Activity: Dev HQ projects/decisions, Bridge stats

**Step 4: Implement `loadIntegration()` in consciousness.js**

Load health data and Dev HQ summary. Add `testPipeline()` function that POSTs to test endpoint, renders step-by-step results with status icons (checkmark/warning/error) and timing.

**Step 5: Test and commit**

```bash
docker compose restart archie_platform
curl -s -b /tmp/archie_cookies.txt -X POST http://192.168.1.200:3000/tools/consciousness/api/integration/test-pipeline | python3 -m json.tool

git add platform_v2/tools/consciousness/integration_routes.py platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): integration tab — system health, pipeline monitor, cross-module links"
```

---

### Task 14: Cross-Module Links — Bridge to Consciousness

**Files:**
- Modify: Bridge module template (find via `grep -r "agent" platform_v2/templates/bridge*.html`)

**Context:** Add navigation links from Bridge Command to Consciousness:
- In Bridge agent roster: add "View Personnel File" icon/link pointing to `/tools/consciousness#team`

The reverse link (Consciousness to Bridge) was already added in Task 9 via the agent profile modal.

**Step 1: Find Bridge agent rendering code**

Search the Bridge template for where agents are rendered in station views.

**Step 2: Add link to Consciousness**

Add a small icon link (brain icon) next to each agent name in Bridge that links to `/tools/consciousness#team`.

**Step 3: Test both directions**

Navigate Bridge → click agent link → lands on Consciousness Team tab.
Navigate Consciousness Team → open agent → click "View in Bridge Command" → lands on Bridge.

**Step 4: Commit**

```bash
git add platform_v2/templates/bridge*.html
git commit -m "feat(consciousness): cross-module links between Bridge and Consciousness"
```

---

### Task 15: Complete Translations — Audit + Generate Missing

**Files:** No code file changes — uses existing translation infrastructure + DB operations.

**Step 1: Audit current translation coverage**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT
  split_part(key, '.', 1) as module,
  count(DISTINCT key) as keys,
  count(*) FILTER (WHERE language != 'en') as non_en,
  count(*) FILTER (WHERE status = 'approved') as approved
FROM translations
GROUP BY split_part(key, '.', 1)
ORDER BY module;
"
```

**Step 2: Identify missing translations for Bridge and Dev HQ**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT t1.key, array_agg(t1.language) as has_translations
FROM translations t1
WHERE t1.key LIKE 'bridge.%' OR t1.key LIKE 'devhq.%'
GROUP BY t1.key
HAVING count(*) < 8
ORDER BY t1.key;
"
```

**Step 3: Seed consciousness i18n keys**

The new template uses `data-i18n` attributes with `consciousness.*` prefix. Trigger the key scanner to discover and seed English entries. Then generate translations for all 7 non-English languages.

**Step 4: Generate missing translations via Languages tab**

Use the "Generate Missing" functionality. Verify each translation request creates a `bridge_interaction_log` entry (ADR-013 compliance).

**Step 5: Commit any code changes needed**

```bash
git add -A  # Only if code changes were needed for translation generation
git commit -m "feat(consciousness): complete i18n translations for Bridge, Dev HQ, Consciousness"
```

---

### Task 16: Visual QA — Playwright Screenshots at 3 Breakpoints

**Files:**
- Create: `platform_v2/tests/test-consciousness-redesign.mjs`

**Step 1: Write the Playwright test**

Create a test file that:
- Logs in as admin
- Navigates to `/tools/consciousness`
- Dismisses boot overlay
- Runs 7 integration tests:
  1. LCARS header visible (`.cs-header`)
  2. 7 tabs visible (`.cs-tab` count === 7)
  3. Dashboard stats populated (`#statKnowledgeTotal` not `--`)
  4. Team tab loads agents (`.cs-agent-card` count > 0)
  5. Integration health API returns 200
  6. Dashboard summary API returns 200
  7. Team roster API returns 200
- Takes screenshots at 3 breakpoints (374, 717, 1280) for all 7 tabs = 21 screenshots
- Saves to `/mnt/archie_brain/screenshots/consciousness-{tab}-{width}.png`

**Step 2: Run the tests**

```bash
cd /mnt/archie_brain && node platform_v2/tests/test-consciousness-redesign.mjs
```

Expected: 7 integration tests pass + 21 screenshots.

**Step 3: Review screenshots for layout issues**

Check: header renders, tabs legible, stat cards don't overflow on mobile, agent grid stacks, no clipped text.

**Step 4: Commit test file**

```bash
git add platform_v2/tests/test-consciousness-redesign.mjs
git commit -m "test(consciousness): visual QA + integration tests — 7 tabs x 3 breakpoints"
```

---

### Task 17: Responsive CSS Polish

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (CSS section)

**Step 1: Add responsive breakpoints if not already present**

Ensure media queries handle:
- Mobile (max-width 480px): 2-column stats, icons-only tabs, single-column agent grid
- Tablet (max-width 768px): 2-column stats, 2-column agents, stacked card grids
- Desktop (min-width 769px): 4-column stats, 3-column agents

**Step 2: Re-run visual QA**

```bash
node platform_v2/tests/test-consciousness-redesign.mjs
```

**Step 3: Fix any layout issues, commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "fix(consciousness): responsive CSS — mobile/tablet/desktop breakpoints"
```

---

### Task 18: Final Push + Dev HQ Checkpoint

**Files:** None (git + MCP operations)

**Step 1: Push all changes**

```bash
git push origin main
```

**Step 2: Update Dev HQ via MCP**

- Complete relevant tasks in project #94
- Log decisions:
  - ADR: Route splitting pattern for large modules
  - ADR: Bridge = Operations, Consciousness = Identity separation
  - ADR: Integration tab for cross-module health monitoring
- Store roadmap update (vault_note) for consciousness redesign completion
- Update project understanding

**Step 3: Update MEMORY.md with consciousness patterns and gotchas**

---

## Task Summary

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1 | Split routes — knowledge endpoints | 3 files |
| 2 | Split routes — team, insights, github, integration | 5 files |
| 3 | Dashboard summary API | 1 file |
| 4 | External consciousness.js | 1 file |
| 5 | Template rebuild — LCARS + Dashboard tab | 1 file |
| 6 | Dashboard — wellness bars + integration health | 2 files |
| 7 | Team API endpoints (roster + profile) | 1 file |
| 8 | Knowledge tab HTML + JS | 2 files |
| 9 | Team tab HTML + JS | 2 files |
| 10 | Insights tab HTML + JS + API | 3 files |
| 11 | Languages tab HTML + JS | 2 files |
| 12 | GitHub tab HTML + JS + API | 3 files |
| 13 | Integration tab — pipeline monitor | 3 files |
| 14 | Cross-module links (Bridge to Consciousness) | 1 file |
| 15 | Translation completion (Bridge + Dev HQ + Consciousness) | DB operations |
| 16 | Visual QA — Playwright tests | 1 file |
| 17 | Responsive CSS polish | 1 file |
| 18 | Final push + Dev HQ checkpoint | MCP operations |

**Estimated:** 18 tasks, ~18 commits, touching ~15 files.
