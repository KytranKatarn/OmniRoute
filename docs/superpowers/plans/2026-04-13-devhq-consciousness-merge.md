# Dev HQ → Consciousness Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge Dev HQ into Consciousness as a "Dev HQ" tab, replacing the Intelligence tab. Single location for all platform awareness.

**Architecture:** Dev HQ routes move to `consciousness/devhq_routes.py` following the `register_*_routes(bp, admin_required)` pattern. Template content becomes `panel-devhq` inside `consciousness_dashboard.html`. Background jobs relocate to Department HQ. The standalone `/dev-hq` module is deleted entirely.

**Tech Stack:** Flask Blueprints, Jinja2 templates, vanilla JS, APScheduler, PostgreSQL

**Project:** #249 | **Decision:** #433 | **Spec:** `docs/superpowers/specs/2026-04-13-devhq-consciousness-merge-design.md`

---

## File Structure

### New Files
- `platform_v2/tools/consciousness/devhq_routes.py` — All Dev HQ API endpoints, adapted to Consciousness blueprint prefix

### Modified Files
- `platform_v2/tools/consciousness/__init__.py` — Add `register_devhq_routes` call
- `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` — Replace `panel-intelligence` with `panel-devhq`, update tab definition
- `platform_v2/static/js/consciousness.js` — Add `loadDevHQ()` to `loadTabData()`, add `devhq` to `validTabs`
- `platform_v2/static/js/devhq.js` — Adapt API base URL from `/dev-hq/api/` to `/tools/consciousness/api/devhq/`
- `platform_v2/static/js/consciousness-dashboard-v2.js` — Remove intelligence tab hook (it wraps `switchConsciousnessTab`)
- `platform_v2/tools/department_hq/jobs.py` — Create or merge, receive 6 background jobs
- `platform_v2/app.py` — Remove dev_hq_bp registration, update job imports

### Deleted Files
- `platform_v2/tools/dev_hq/__init__.py`
- `platform_v2/tools/dev_hq/routes.py`
- `platform_v2/tools/dev_hq/jobs.py`
- `platform_v2/templates/dev_hq.html`

### Reference Updates
- `CLAUDE.md` — Update Dev HQ location, remove `/dev-hq` URL
- `.claude/rules/project-knowledge.md` — Update Dev HQ entry
- `.claude/rules/session-protocol.md` — Update if referencing `/dev-hq`

---

## Task 1: Create devhq_routes.py in Consciousness

**Files:**
- Create: `platform_v2/tools/consciousness/devhq_routes.py`
- Read: `platform_v2/tools/dev_hq/routes.py` (source)
- Read: `platform_v2/tools/consciousness/code_health_routes.py` (pattern reference)

- [ ] **Step 1: Read the pattern from an existing Consciousness route file**

Read `code_health_routes.py` lines 1-30 to see the `register_code_health_routes(bp, admin_required)` pattern. All route functions are defined inside the register function, using `@bp.route()` and `@admin_required`.

- [ ] **Step 2: Read Dev HQ routes.py to understand the full API surface**

Read `platform_v2/tools/dev_hq/routes.py`. Note the `admin_hub_only` decorator (line 27) — this becomes `admin_required` in Consciousness. All routes use `/dev-hq/api/` prefix which changes to `/api/devhq/`.

- [ ] **Step 3: Create devhq_routes.py**

Copy the entire `routes.py` content into a new file `platform_v2/tools/consciousness/devhq_routes.py`. Apply these transformations:

1. Wrap all routes in `def register_devhq_routes(bp, admin_required):` function
2. Replace all `@dev_hq_bp.route(` with `@bp.route(`
3. Replace all `@admin_hub_only` with `@admin_required`
4. Replace all route prefixes from `/api/` to `/api/devhq/` (e.g., `/api/projects` → `/api/devhq/projects`)
5. Remove the `admin_hub_only` decorator definition (line 27 in source)
6. Remove the `dev_hq_bp` Blueprint import/creation
7. Keep all imports (database, services, etc.) at the top of the file, outside the register function

```python
# platform_v2/tools/consciousness/devhq_routes.py
"""Dev HQ routes — merged into Consciousness module (Decision #433)."""

# ... all imports from original routes.py ...

def register_devhq_routes(bp, admin_required):
    """Register Dev HQ API routes on the Consciousness blueprint."""

    @bp.route("/api/devhq/overview")
    @admin_required
    def devhq_overview():
        # ... exact body from original get_overview() ...
```

- [ ] **Step 4: Verify the file parses**

```bash
docker exec archie_platform python3 -c "import tools.consciousness.devhq_routes; print('OK')"
```

Expected: `OK` (no import errors)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/devhq_routes.py
git commit -m "feat: create devhq_routes.py — Dev HQ API endpoints in Consciousness"
```

---

## Task 2: Register devhq_routes in Consciousness __init__.py

**Files:**
- Modify: `platform_v2/tools/consciousness/__init__.py`

- [ ] **Step 1: Add the import and registration call**

Add to `__init__.py` after the existing `register_*_routes` calls:

```python
from .devhq_routes import register_devhq_routes
register_devhq_routes(consciousness_bp, admin_required)
```

- [ ] **Step 2: Verify the blueprint loads**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | tail -20
```

Expected: No import errors, platform starts successfully.

- [ ] **Step 3: Test an API endpoint**

```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/consciousness/api/devhq/overview | python3 -m json.tool | head -20
```

Expected: JSON response with overview data (or auth redirect — either confirms route is registered).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/__init__.py
git commit -m "feat: register devhq_routes in Consciousness blueprint"
```

---

## Task 3: Build panel-devhq in consciousness_dashboard.html

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Read: `platform_v2/templates/dev_hq.html` (source template, 641 lines)

- [ ] **Step 1: Update tab definition**

Find the tab list (around line 27-32) and replace the intelligence entry:

```python
# Before:
("intelligence", "Intelligence", "brain-circuit"),

# After:
("devhq", "Dev HQ", "terminal"),
```

- [ ] **Step 2: Remove panel-intelligence entirely**

Delete everything between `<div class="cs-panel" id="panel-intelligence">` and its closing `</div>` (the 5 old LCARS-framed sections: Project-Knowledge Map, Agent Contributions, Knowledge Gaps, Agent Expertise, Knowledge Graph).

- [ ] **Step 3: Build panel-devhq skeleton with subtabs**

Insert the new panel where `panel-intelligence` was. Structure:

```html
<div class="cs-panel" id="panel-devhq">

    <!-- Dev HQ Subtabs -->
    <div class="cs-subtabs" id="devhqSubtabs">
        <button class="cs-subtab active" data-subtab="dh-overview" onclick="switchDevHQSubtab('dh-overview')">Overview</button>
        <button class="cs-subtab" data-subtab="dh-projects" onclick="switchDevHQSubtab('dh-projects')">Projects</button>
        <button class="cs-subtab" data-subtab="dh-ideas" onclick="switchDevHQSubtab('dh-ideas')">Ideas</button>
        <button class="cs-subtab" data-subtab="dh-decisions" onclick="switchDevHQSubtab('dh-decisions')">Decisions</button>
        <button class="cs-subtab" data-subtab="dh-system" onclick="switchDevHQSubtab('dh-system')">System</button>
    </div>

    <!-- ═══ OVERVIEW SUBTAB ═══ -->
    <div class="cs-subpanel active" id="dh-overview">
        <div style="--frame-color:#22d3ee; --frame-rgb:34,211,238; margin-bottom:20px;">
            <!-- Dashboard-style LCARS frame (use saved pattern from feedback_lcars-frame-pattern.md) -->
            <!-- TITLE: PLATFORM OVERVIEW | SUBTITLE: STATS -->
            <div class="lcars-frame" style="display: flex !important; align-items: stretch !important;">
                <!-- ... full inline frame pattern ... -->
                <div class="lcars-body" style="flex: 1 !important; padding: 12px !important; position: relative !important;">
                    <div id="dhOverviewStats">
                        <p style="color:#94a3b8">Loading overview...</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Intelligence Analytics (merged from Intelligence tab) -->
        <div style="--frame-color:#8b5cf6; --frame-rgb:139,92,246; margin-bottom:20px;">
            <!-- TITLE: INTELLIGENCE ANALYTICS | SUBTITLE: ANALYSIS -->
            <!-- ... full inline frame pattern ... -->
            <div id="dhIntelligence">
                <div id="cs-project-knowledge-map"><p style="color:#94a3b8">Loading project-knowledge map...</p></div>
                <div id="cs-knowledge-gaps-body"><p style="color:#94a3b8">Loading knowledge gaps...</p></div>
                <div id="cs-agent-contributions-body"><p style="color:#94a3b8">Loading contributions...</p></div>
            </div>
        </div>
    </div>

    <!-- ═══ PROJECTS SUBTAB ═══ -->
    <div class="cs-subpanel" id="dh-projects" style="display:none;">
        <div style="--frame-color:#8b5cf6; --frame-rgb:139,92,246; margin-bottom:20px;">
            <!-- TITLE: PROJECTS | SUBTITLE: TRACKING -->
            <!-- ... full inline frame pattern ... -->
            <div id="dhProjectList"><p style="color:#94a3b8">Loading projects...</p></div>
            <div id="dhProjectDetail" style="display:none;"></div>
        </div>
    </div>

    <!-- ═══ IDEAS SUBTAB ═══ -->
    <div class="cs-subpanel" id="dh-ideas" style="display:none;">
        <div style="--frame-color:#f59e0b; --frame-rgb:245,158,11; margin-bottom:20px;">
            <!-- TITLE: IDEAS | SUBTITLE: BACKLOG -->
            <!-- ... full inline frame pattern ... -->
            <div id="dhIdeaList"><p style="color:#94a3b8">Loading ideas...</p></div>
        </div>
    </div>

    <!-- ═══ DECISIONS SUBTAB ═══ -->
    <div class="cs-subpanel" id="dh-decisions" style="display:none;">
        <div style="--frame-color:#10b981; --frame-rgb:16,185,129; margin-bottom:20px;">
            <!-- TITLE: DECISIONS | SUBTITLE: ADR LOG -->
            <!-- ... full inline frame pattern ... -->
            <div id="dhDecisionList"><p style="color:#94a3b8">Loading decisions...</p></div>
        </div>
    </div>

    <!-- ═══ SYSTEM SUBTAB ═══ -->
    <div class="cs-subpanel" id="dh-system" style="display:none;">
        <div style="--frame-color:#22d3ee; --frame-rgb:34,211,238; margin-bottom:20px;">
            <!-- TITLE: SYSTEM | SUBTITLE: INTEGRATIONS -->
            <!-- ... full inline frame pattern ... -->
            <div id="dhSystemPanel"><p style="color:#94a3b8">Loading system...</p></div>
        </div>
    </div>

</div>
```

Each frame wrapper uses the exact dashboard-style inline `!important` pattern from `feedback_lcars-frame-pattern.md`. Apply the full template for each — do NOT use CSS-only classes.

- [ ] **Step 4: Deploy and verify panel renders**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/tools/consciousness/#devhq` and verify the Dev HQ tab appears with subtab buttons.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat: panel-devhq replaces panel-intelligence in Consciousness"
```

---

## Task 4: Wire JS — tab switching + API calls

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`
- Modify: `platform_v2/static/js/devhq.js`
- Modify: `platform_v2/static/js/consciousness-dashboard-v2.js`

- [ ] **Step 1: Update consciousness.js — add devhq to tab system**

In `consciousness.js`, make these changes:

1. In `validTabs` array (search for `"codehealth"`), replace `"intelligence"` with `"devhq"`:
```javascript
var validTabs = ["dashboard", "devhq", "knowledge", "github", "languages", "codehealth"];
```

2. In `loadTabData()` switch statement, replace the `intelligence` case:
```javascript
// Before:
case "intelligence": if (typeof loadDashboardV2Panels === "function") { loadDashboardV2Panels(); } break;

// After:
case "devhq": loadDevHQ(); break;
```

3. Add the `loadDevHQ()` function (minimal — delegates to devhq.js):
```javascript
function loadDevHQ() {
    if (typeof initDevHQPanel === "function") {
        initDevHQPanel();
    }
}
```

- [ ] **Step 2: Update devhq.js — change API base URL**

Global find-and-replace in `devhq.js`:
- Replace all `"/dev-hq/api/` with `"/tools/consciousness/api/devhq/`
- Replace `switchDevHQTab` function name to `switchDevHQSubtab` (avoid collision with Consciousness tab switching)
- Wrap the initialization in an `initDevHQPanel()` function that consciousness.js can call
- Ensure the subtab switching function targets `#panel-devhq .cs-subpanel` elements

```javascript
// At the top of devhq.js, expose init function:
window.initDevHQPanel = function() {
    // Load overview data
    loadDevHQOverview();
    // Load intelligence analytics (from consciousness-dashboard-v2.js)
    if (typeof loadDashboardV2Panels === "function") {
        loadDashboardV2Panels();
    }
};

window.switchDevHQSubtab = function(subtab) {
    document.querySelectorAll("#panel-devhq .cs-subpanel").forEach(function(p) {
        p.style.display = p.id === subtab ? "" : "none";
    });
    document.querySelectorAll("#devhqSubtabs .cs-subtab").forEach(function(b) {
        b.classList.toggle("active", b.dataset.subtab === subtab);
    });
    // Load data for subtab on first visit
    if (!_dhCache[subtab]) {
        _dhCache[subtab] = true;
        switch(subtab) {
            case "dh-overview": loadDevHQOverview(); break;
            case "dh-projects": loadDevHQProjects(); break;
            case "dh-ideas": loadDevHQIdeas(); break;
            case "dh-decisions": loadDevHQDecisions(); break;
            case "dh-system": loadDevHQSystem(); break;
        }
    }
};
var _dhCache = {};
```

- [ ] **Step 3: Update consciousness-dashboard-v2.js — remove intelligence hook**

In `consciousness-dashboard-v2.js` (around line 881-891), the intelligence tab wrapper overrides `switchConsciousnessTab`. Update it to hook into `devhq` instead:

```javascript
// Before:
if (tab === "intelligence") {
    loadDashboardV2Panels();
}

// After:
if (tab === "devhq") {
    loadDashboardV2Panels();
}
```

- [ ] **Step 4: Add devhq.js script tag to consciousness_dashboard.html**

At the bottom of the template where JS files are loaded (after consciousness.js), add:

```html
<script src="{{ url_for('static', filename='js/devhq.js') }}"></script>
```

- [ ] **Step 5: Deploy and test all subtabs**

```bash
docker compose restart archie_platform
```

Navigate to each subtab: Overview, Projects, Ideas, Decisions, System. Verify data loads.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/static/js/consciousness.js platform_v2/static/js/devhq.js platform_v2/static/js/consciousness-dashboard-v2.js platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat: wire Dev HQ JS — tab switching, API calls, subtab navigation"
```

---

## Task 5: Move background jobs to Department HQ

**Files:**
- Read: `platform_v2/tools/dev_hq/jobs.py` (source, 622 lines)
- Create or modify: `platform_v2/tools/department_hq/jobs.py`
- Modify: `platform_v2/app.py` (scheduler registration)

- [ ] **Step 1: Check if Department HQ already has a jobs.py**

```bash
ls -la platform_v2/tools/department_hq/jobs.py 2>/dev/null || echo "NOT FOUND"
```

- [ ] **Step 2: Create/merge Department HQ jobs.py**

If no existing file, copy `dev_hq/jobs.py` to `department_hq/jobs.py` and rename the registration function:

```python
# platform_v2/tools/department_hq/jobs.py
"""Background jobs — operational platform maintenance (moved from Dev HQ, Decision #433)."""

def register_department_hq_jobs(scheduler, app):
    # ... all 6 jobs from dev_hq/jobs.py ...
```

If file exists, merge the 6 job functions into it.

- [ ] **Step 3: Update app.py scheduler registration**

Find the Dev HQ job registration in `app.py` (around line 2301) and replace:

```python
# Before:
from tools.dev_hq.routes import sync_mcp_tool_registry, _run_and_store_health_check
# ... devhq job scheduling ...

# After:
from tools.department_hq.jobs import register_department_hq_jobs
register_department_hq_jobs(scheduler, app)
```

Also update the `sync_mcp_tool_registry` and `_run_and_store_health_check` imports to point to the new location (either in devhq_routes.py or department_hq/jobs.py depending on where they live).

- [ ] **Step 4: Deploy and verify jobs are scheduled**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | grep -i "job\|schedule\|apscheduler" | tail -20
```

Expected: All 6 jobs appear in scheduler output.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/jobs.py platform_v2/app.py
git commit -m "feat: move Dev HQ background jobs to Department HQ"
```

---

## Task 6: Delete standalone Dev HQ module

**Files:**
- Delete: `platform_v2/tools/dev_hq/__init__.py`
- Delete: `platform_v2/tools/dev_hq/routes.py`
- Delete: `platform_v2/tools/dev_hq/jobs.py`
- Delete: `platform_v2/templates/dev_hq.html`
- Modify: `platform_v2/app.py` — remove dev_hq_bp import and registration

- [ ] **Step 1: Remove blueprint registration from app.py**

Find and remove these lines:
```python
# Line ~1915:
from tools.dev_hq import dev_hq_bp
# Line ~1917:
app.register_blueprint(dev_hq_bp)
```

- [ ] **Step 2: Delete the module files**

```bash
rm platform_v2/tools/dev_hq/__init__.py
rm platform_v2/tools/dev_hq/routes.py
rm platform_v2/tools/dev_hq/jobs.py
rm platform_v2/templates/dev_hq.html
rmdir platform_v2/tools/dev_hq/
```

- [ ] **Step 3: Deploy and verify**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | tail -20
```

Expected: Platform starts with no import errors. `/dev-hq` returns 404.

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/dev-hq
```

Expected: `404`

- [ ] **Step 4: Commit**

```bash
git add -A platform_v2/tools/dev_hq/ platform_v2/templates/dev_hq.html platform_v2/app.py
git commit -m "chore: delete standalone Dev HQ module (moved to Consciousness, Decision #433)"
```

---

## Task 7: Reference audit — update all /dev-hq references

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/rules/project-knowledge.md`
- Modify: any other files found by grep

- [ ] **Step 1: Find all references**

```bash
grep -r "/dev-hq\|dev_hq\|Dev HQ" --include="*.md" CLAUDE.md .claude/rules/ .claude/projects/*/memory/ platform_v2/CLAUDE.md 2>/dev/null
```

- [ ] **Step 2: Update CLAUDE.md**

Change Dev HQ references:
```markdown
# Before:
| Dev HQ | http://192.168.1.200:3000/dev-hq |

# After:
| Dev HQ | http://192.168.1.200:3000/tools/consciousness/#devhq (tab inside Consciousness) |
```

- [ ] **Step 3: Update .claude/rules/project-knowledge.md**

```markdown
# Before:
- **Dev HQ** — `/dev-hq`, development command center

# After:
- **Dev HQ** — Consciousness module → Dev HQ tab (`/tools/consciousness/#devhq`)
```

- [ ] **Step 4: Update memory files if needed**

Check and update any memory files referencing `/dev-hq`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .claude/rules/project-knowledge.md
git commit -m "docs: update all /dev-hq references to Consciousness Dev HQ tab"
```

---

## Task 8: Browser verification + QA

- [ ] **Step 1: Test all 6 Consciousness tabs**

Navigate to each tab and verify content loads:
1. Dashboard — Neural Core renders
2. Dev HQ — Overview loads stats + intelligence analytics, Projects loads list, Ideas shows backlog, Decisions shows log, System shows integrations
3. Knowledge — Browser loads entries
4. GitHub — Intake form works, repos show
5. Languages — Translation stats load
6. Code Health — Health score, module table, charts

- [ ] **Step 2: Verify LCARS frames on Dev HQ subtabs**

Each Dev HQ subtab section should have dashboard-style LCARS frames with sidebar, elbows, lights, header bar, pips.

- [ ] **Step 3: Verify /dev-hq is gone**

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/dev-hq
```

Expected: `404`

- [ ] **Step 4: Run P.R.O.B.E. QA suite**

```bash
# Via MCP:
mcp__archie__run_qa_suite with suite_name="platform"
```

- [ ] **Step 5: Complete project tasks**

Mark all tasks in Project #249 as complete via MCP.

- [ ] **Step 6: Final commit + push**

```bash
git push origin feat/agent-card-acronym-expansion
```
