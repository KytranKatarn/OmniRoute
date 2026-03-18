# Starship Module Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Starship module to pull real agent/crew data from Bridge dispatcher, delete fake crew generation, split the monolithic routes file, and extract inline CSS/JS from the template.

**Architecture:** Starship becomes a consumer of Bridge's `get_dispatcher().get_crew_manifest()` singleton for all crew data. Routes split into 4 files + helpers following Bridge's ADR-045 `register_*_routes(bp, decorator)` pattern. Template restructured from 3 tabs to 2 (FLEET + OPERATIONS) with a hero Starbase section.

**Tech Stack:** Flask Blueprints, psycopg2 (DB), BridgeDispatcher (ai_bridge), LCARS CSS theme, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-18-starship-rework-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `platform_v2/tools/starship/__init__.py` | Rewrite | ADR-045 register_*_routes pattern |
| `platform_v2/tools/starship/routes.py` | Rewrite | Main page + fleet overview API only |
| `platform_v2/tools/starship/helpers.py` | Create | Shared helpers (_compute_node_status, node lookups, constants) |
| `platform_v2/tools/starship/node_routes.py` | Create | Node status, settings, setup/onboarding, installers |
| `platform_v2/tools/starship/crew_routes.py` | Create | Crew manifest, agent profiles via dispatcher |
| `platform_v2/tools/starship/ota_routes.py` | Create | OTA push, sync, model pull |
| `platform_v2/tools/starship/templates/tools/starship/starship.html` | Rewrite | Pure HTML, 2 tabs (FLEET + OPERATIONS) |
| `platform_v2/static/css/starship.css` | Create | Extracted styles |
| `platform_v2/static/js/starship.js` | Create | Extracted JS |

---

### Task 1: Create helpers.py — Extract shared utilities

**Files:**
- Create: `platform_v2/tools/starship/helpers.py`
- Read: `platform_v2/tools/starship/routes.py:297-370` (helpers to extract)

- [ ] **Step 1: Read the helper functions from current routes.py**

Read lines 297-370 of `routes.py` to get exact code for:
- `HEARTBEAT_TIMEOUT_SECONDS` (line 297)
- `_compute_node_status()` (line 300)
- `_get_user_nodes()` (line 315)
- `_get_node_for_user()` (line 335)
- `_get_node_for_user_by_int_id()` (line 356)

- [ ] **Step 2: Create helpers.py with extracted functions**

Create `platform_v2/tools/starship/helpers.py` containing:
- `HEARTBEAT_TIMEOUT_SECONDS = 120`
- All 4 helper functions, preserving exact signatures and logic
- Required imports: `from database import get_db_cursor` and any others these functions use
- `LATEST_NODE_VERSION = "1.0.0"` (line 440 in routes.py — note: it's LATEST not CURRENT)

- [ ] **Step 3: Verify helpers.py has no syntax errors**

Run: `docker exec archie_platform python3 -c "from tools.starship.helpers import _compute_node_status, _get_user_nodes, _get_node_for_user, _get_node_for_user_by_int_id, HEARTBEAT_TIMEOUT_SECONDS, LATEST_NODE_VERSION"`
Expected: No output (clean import)

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/helpers.py
git commit -m "refactor(starship): extract shared helpers from routes.py"
```

---

### Task 2: Create crew_routes.py — Real crew data via dispatcher

**Files:**
- Create: `platform_v2/tools/starship/crew_routes.py`
- Read: `platform_v2/tools/starship/routes.py:710-960` (crew endpoints to rewrite)
- Read: `platform_v2/tools/bridge/crew_routes.py:830-840` (dispatcher import pattern)
- Read: `ai_bridge/bridge_dispatcher.py:4911-4960` (get_crew_manifest structure)

- [ ] **Step 1: Read current crew endpoints and dispatcher pattern**

Read these line ranges to understand:
- `api_node_crew_manifest()` (routes.py:708-788, decorator at 708, def at 710) — currently builds fake crew, needs to use dispatcher
- `api_node_agent_profile()` (routes.py:789-955, decorator at 789, def at 791) — agent detail, rewrite to use real data
- `api_node_agent_form_context()` (routes.py:956-986, decorator at 956, def at 958) — form context for editing
- `api_update_node_agent()` (routes.py:987-1115, decorator at 987, def at 989) — update agent config
- Bridge `crew_routes.py:830-840` for how it imports dispatcher
- `bridge_dispatcher.py:4911+` for manifest return structure

- [ ] **Step 2: Create crew_routes.py with register pattern**

Create `platform_v2/tools/starship/crew_routes.py` with:

```python
def register_crew_routes(bp, auth_decorator):
```

Containing rewritten endpoints:
- `api_node_crew_manifest(node_id)` — query `node_agents JOIN agents ON hub_agent_id = agents.id WHERE node_id = %s`, enrich with dispatcher manifest wellness/job data
- `api_node_agent_profile(node_id, agent_id)` — real agent data from `agents` table + `node_agents` config
- `api_node_agent_form_context(node_id)` — real available models from Ollama tags cache
- `api_update_node_agent(node_id, agent_id)` — keep update logic but remove fake crew references
- `api_add_agent_to_node(node_id)` — simplified: just INSERT into node_agents with real hub_agent_id (rewrite of `_add_single_agent_to_node` fake logic). Use `check_fleet_model_unique` from database.py.
- `api_remove_agent_from_node(node_id, agent_id)` — keep as-is (already works with real DB)

Import dispatcher using the singleton pattern (not `BridgeDispatcher()` directly):
```python
from ai_bridge.bridge_dispatcher import get_dispatcher
# Usage: dispatcher = get_dispatcher(); manifest = dispatcher.get_crew_manifest()
```

Use node ownership check from helpers:
```python
from .helpers import _get_node_for_user_by_int_id
```

- [ ] **Step 3: Verify crew_routes.py imports cleanly**

Run: `docker exec archie_platform python3 -c "from tools.starship.crew_routes import register_crew_routes; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/crew_routes.py
git commit -m "feat(starship): add crew_routes.py — real crew data via Bridge dispatcher"
```

---

### Task 3: Create node_routes.py — Node status, settings, setup/onboarding

**Files:**
- Create: `platform_v2/tools/starship/node_routes.py`
- Read: `platform_v2/tools/starship/routes.py:443-690` (node status + settings)
- Read: `platform_v2/tools/starship/routes.py:1116-1365` (setup/onboarding/installers)
- Read: `platform_v2/tools/starship/routes.py:1967-2039` (station commands)

- [ ] **Step 1: Read current node endpoints**

Read these line ranges:
- `api_node_status(node_id)` (lines 443-642) — big endpoint, keep but remove fake crew calls
- `api_update_node_settings(node_id)` (lines 643-688) — keep as-is
- `api_model_catalog()` (lines 689-707) — keep as-is
- `NODE_CLIENT_DIR` constant (lines 1116-1125) — needed by installer functions, include in this file
- `api_request_node()` (lines 1126-1193) — keep as-is. **NOTE:** uses `user_id` column on INSERT but `_get_user_nodes` queries `registered_by` — verify these are the same column or reconcile during move
- `api_setup_instructions(node_id)` (lines 1194-1217) — keep as-is
- `starship_install_script()` (lines 1218-1253) — keep as-is
- `_generate_bash_installer()` (lines 1254-1294) — keep as-is (private helper)
- `_generate_powershell_installer()` (lines 1295-1327) — keep as-is (private helper)
- `api_request_update(node_id)` (lines 1328-1350) — keep as-is
- `download_node_package()` (lines 1351-1365) — keep as-is
- `api_get_station_commands()` (lines 1967-2001) — keep as-is (station command listing)
- `api_execute_station_command()` (lines 2002-2039) — keep as-is (station command execution)

- [ ] **Step 2: Create node_routes.py**

Create `platform_v2/tools/starship/node_routes.py` with:

```python
def register_node_routes(bp, auth_decorator):
```

Move all node endpoints listed above into this file. Key change in `api_node_status`:
- Remove the call to `_generate_node_crew()` (it's fake)
- Instead, query `node_agents` count for the real agent count
- Remove references to `MODULE_STATION_MAP` and `MODEL_SIZE_HINTS`
- Keep all hardware/heartbeat/version logic as-is

Import helpers:
```python
from .helpers import _get_node_for_user, _get_node_for_user_by_int_id, _get_user_nodes, _compute_node_status, HEARTBEAT_TIMEOUT_SECONDS, LATEST_NODE_VERSION
```

- [ ] **Step 3: Verify node_routes.py imports cleanly**

Run: `docker exec archie_platform python3 -c "from tools.starship.node_routes import register_node_routes; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/node_routes.py
git commit -m "refactor(starship): add node_routes.py — node status, settings, setup/onboarding"
```

---

### Task 4: Create ota_routes.py — OTA push, sync, installers

**Files:**
- Create: `platform_v2/tools/starship/ota_routes.py`
- Read: `platform_v2/tools/starship/routes.py:1692-1940` (OTA + sync endpoints)

- [ ] **Step 1: Read current OTA/sync endpoints**

Read lines 1692-1940:
- `api_push_agent_config(node_id)` (line 1699) — keep as-is
- `api_pull_model(node_id)` (line 1766) — keep as-is
- `api_push_code_update(node_id)` (line 1798) — keep as-is
- `api_get_sync_log(node_id)` (line 1860) — keep as-is
- `api_node_sync_status(node_id)` (line 1907) — keep as-is

- [ ] **Step 2: Create ota_routes.py**

Create `platform_v2/tools/starship/ota_routes.py` with:

```python
def register_ota_routes(bp, auth_decorator):
```

Move all 5 OTA/sync endpoints verbatim. These work correctly today — no logic changes needed, just relocation.

Import helpers for node ownership checks:
```python
from .helpers import _get_node_for_user_by_int_id
```

- [ ] **Step 3: Verify ota_routes.py imports cleanly**

Run: `docker exec archie_platform python3 -c "from tools.starship.ota_routes import register_ota_routes; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/ota_routes.py
git commit -m "refactor(starship): add ota_routes.py — OTA push, sync endpoints (no logic changes)"
```

---

### Task 5: Rewrite routes.py — Main page + fleet overview API only

**Files:**
- Rewrite: `platform_v2/tools/starship/routes.py`
- Read: `platform_v2/tools/starship/routes.py:373-440` (dashboard + list_nodes to keep)

- [ ] **Step 1: Read the dashboard and list_nodes endpoints**

Read lines 373-440:
- `starship_dashboard()` (line 380) — renders template, keep
- `api_list_nodes()` (line 406) — lists fleet nodes, keep

- [ ] **Step 2: Rewrite routes.py**

Replace the entire 2,039-line file with a focused ~150-line file containing:
- Blueprint definition: `starship_bp = Blueprint("starship", __name__, ...)`
- `starship_dashboard()` — renders the template
- `api_list_nodes()` — lists fleet nodes with real data
- NEW `api_starbase_stats()` — hero Starbase stats endpoint:
  - Import `get_dispatcher` from `ai_bridge.bridge_dispatcher`, call `get_dispatcher().get_crew_manifest()`
  - Return: total active agents, loaded models count, active jobs, VRAM/RAM from Ollama ps
  - Count of connected nodes from `remote_nodes WHERE is_active = true`

No fake crew code. No MODULE_STATION_MAP. No MODEL_SIZE_HINTS. No _generate_node_crew.

- [ ] **Step 3: Verify routes.py imports and blueprint works**

Run: `docker exec archie_platform python3 -c "from tools.starship.routes import starship_bp; print(starship_bp.name)"`
Expected: `starship`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "refactor(starship): rewrite routes.py — fleet overview only, no fake crew"
```

---

### Task 6: Rewrite __init__.py — ADR-045 registration pattern

**Files:**
- Rewrite: `platform_v2/tools/starship/__init__.py`

- [ ] **Step 1: Rewrite __init__.py**

Replace with the ADR-045 pattern matching Bridge's `__init__.py`:

```python
"""
A.R.C.H.I.E. STARSHIP Module
==============================
Fleet node management — Starbase hub + remote starship nodes.
"""

from flask_login import login_required

from .routes import starship_bp
from .node_routes import register_node_routes
from .crew_routes import register_crew_routes
from .ota_routes import register_ota_routes

register_node_routes(starship_bp, login_required)
register_crew_routes(starship_bp, login_required)
register_ota_routes(starship_bp, login_required)

__all__ = ["starship_bp"]
```

- [ ] **Step 2: Verify full module imports**

Run: `docker exec archie_platform python3 -c "from tools.starship import starship_bp; print('Routes:', len(list(starship_bp.deferred_functions)))"`
Expected: No errors, shows count of registered route functions

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/starship/__init__.py
git commit -m "refactor(starship): rewrite __init__.py — ADR-045 register_*_routes pattern"
```

---

### Task 7: Extract CSS from template to starship.css

**Files:**
- Create: `platform_v2/static/css/starship.css`
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html:8-371`

- [ ] **Step 1: Read the inline styles from template**

Read `starship.html` lines 8-371 (between `<style>` and `</style>` tags).

- [ ] **Step 2: Create starship.css**

Create `platform_v2/static/css/starship.css` with:
- All CSS from the `<style>` block (lines 9-370)
- Clean up any template-specific Jinja2 references in CSS (there shouldn't be any, but check)
- Add a header comment: `/* Starship Command — Teal accent theme */`

- [ ] **Step 3: Replace inline style block in template with link tag**

In `starship.html`, replace the entire `<style>...</style>` block (lines 8-371) with:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/starship.css') }}">
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/css/starship.css platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "refactor(starship): extract inline CSS to static/css/starship.css"
```

---

### Task 8: Extract JS from template to starship.js

**Files:**
- Create: `platform_v2/static/js/starship.js`
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html:862-2333`

- [ ] **Step 1: Read the inline script from template**

Read `starship.html` lines 862-2333 (between `<script>` and `</script>` tags).

- [ ] **Step 2: Create starship.js**

Create `platform_v2/static/js/starship.js` with:
- All JS from the `<script>` block (lines 863-2332)
- Remove any JS functions that reference fake crew generation (they'll break without the deleted Python endpoints)
- Update any API endpoint URLs that changed (e.g., remove calls to `/api/nodes/<id>/recommendations`)
- Keep all OTA, sync, node status, and modal JS intact
- Add header comment: `/* Starship Command — Fleet management JS */`

- [ ] **Step 3: Replace inline script block in template with script tag**

In `starship.html`, replace the entire `<script>...</script>` block (lines 862-2333) with:
```html
<script src="{{ url_for('static', filename='js/starship.js') }}"></script>
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/starship.js platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "refactor(starship): extract inline JS to static/js/starship.js"
```

---

### Task 9: Restructure template — 2 tabs (FLEET + OPERATIONS) with hero Starbase

**Files:**
- Rewrite: `platform_v2/tools/starship/templates/tools/starship/starship.html`
- Modify: `platform_v2/static/js/starship.js` (update tab switching + add hero/modal JS)
- Modify: `platform_v2/static/css/starship.css` (add hero + node card styles)

- [ ] **Step 1: Read current template HTML structure**

Read `starship.html` lines 372-861 (the HTML between style and script). Understand current tab layout (STATUS, OTA/SYNC, CREW).

- [ ] **Step 2: Rewrite template HTML**

Rewrite the template to have:

**Header area:**
- Page title "Starship Command"
- 2 tab buttons: FLEET, OPERATIONS

**FLEET tab:**
- Hero Starbase section (id=`starbase-hero`):
  - Large teal-accented card for Archie Starbase
  - Stats row: total agents, loaded models, VRAM usage, active jobs, connected nodes
  - Populated via JS fetch to `/tools/starship/api/starbase-stats`
- Fleet node grid (id=`fleet-grid`):
  - Cards populated via JS fetch to `/tools/starship/api/nodes`
  - Each card: node name, status badge, agent count, hardware, heartbeat
  - Onclick → opens LCARS tablet modal

**LCARS tablet modal** (id=`node-detail-modal`):
- Uses `bm-` CSS classes (LCARS tablet design from Bridge)
- 3 sub-tabs: STATUS, CREW, STATIONS
- STATUS: hardware specs, loaded models
- CREW: agent cards from `/tools/starship/api/nodes/<id>/crew-manifest`
- STATIONS: station assignments

**OPERATIONS tab:**
- 3 sections: OTA Push, Sync Status, Node Setup/Onboarding
- Preserve existing form inputs and buttons for push-config, pull-model, push-update
- Preserve node request form and installer download links

- [ ] **Step 3: Update starship.js for new tab structure**

Update JS to:
- `switchTab('fleet')` / `switchTab('operations')` (was status/ota/crew)
- Add `loadStarbaseStats()` — fetch `/api/starbase-stats`, populate hero
- Add `loadFleetNodes()` — fetch `/api/nodes`, render node cards
- Add `openNodeModal(nodeId)` — fetch node detail, show LCARS tablet modal
- Add `switchNodeTab(tab)` — sub-tab switching inside modal (status/crew/stations)
- Keep all OTA/sync JS functions intact
- Remove any JS referencing fake crew or recommendations endpoint

- [ ] **Step 4: Update starship.css for hero + node cards**

Add CSS for:
- `.starbase-hero` — large card, teal accent, distinct from fleet cards
- `.fleet-grid` — CSS grid for node cards
- `.node-card` — compact card with status badge
- `.node-card:hover` — hover effect
- LCARS tablet modal styles (reuse `bm-` classes from Bridge, or add starship-specific variants)

- [ ] **Step 5: Verify the page loads without errors**

Run: `docker exec archie_platform python3 -c "from tools.starship import starship_bp; print('Module loaded OK')"`
Then open `http://192.168.1.200:3000/tools/starship` in browser and verify:
- Hero Starbase section renders with real stats
- Fleet node cards appear for each `remote_nodes` entry
- Clicking a node card opens the LCARS tablet modal
- OPERATIONS tab shows OTA/sync/onboarding forms

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html platform_v2/static/js/starship.js platform_v2/static/css/starship.css
git commit -m "feat(starship): restructure to 2 tabs — FLEET hero + OPERATIONS, LCARS node modals"
```

---

### Task 10: Integration test — verify all endpoints work

**Files:**
- Read: All new route files for endpoint verification

- [ ] **Step 1: Restart the platform**

```bash
docker compose restart archie_platform
```

Wait 10 seconds for startup.

- [ ] **Step 2: Test fleet overview endpoints**

```bash
# Starbase stats
docker exec archie_platform python3 -c "
from tools.starship.routes import starship_bp
from tools.starship.helpers import _get_user_nodes
nodes = _get_user_nodes(2)
print(f'Nodes found: {len(nodes) if nodes else 0}')
"

# Verify dispatcher integration
docker exec archie_platform python3 -c "
from ai_bridge.bridge_dispatcher import BridgeDispatcher
d = BridgeDispatcher()
m = d.get_crew_manifest()
print(f'Manifest agents: {len(m)}')
"
```

- [ ] **Step 3: Test crew endpoints**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute('SELECT na.id, na.name, a.display_name, a.model FROM node_agents na JOIN agents a ON na.hub_agent_id = a.id LIMIT 5')
    rows = cur.fetchall()
    for r in rows:
        print(f'  {r[1]}: {r[2]} ({r[3]})')
    print(f'Total node agents with real data: {len(rows)}')
"
```

- [ ] **Step 4: Test OTA endpoints haven't regressed**

```bash
# Verify sync status endpoint works
docker exec archie_platform python3 -c "
from tools.starship.ota_routes import register_ota_routes
print('OTA routes module loads OK')
"
```

- [ ] **Step 5: Test full page load**

Open `http://192.168.1.200:3000/tools/starship` in browser.
Verify:
1. Hero Starbase shows real agent count and stats
2. Node cards show real connected nodes
3. Click node card → modal opens with real crew data
4. OPERATIONS tab → OTA push forms work
5. No JS console errors
6. No 404/500 on API calls

- [ ] **Step 6: Commit any fixes found during testing**

```bash
git add -u
git commit -m "fix(starship): integration test fixes after rework"
```

---

### Task 11: Clean up — remove old __pycache__ and update Dev HQ

- [ ] **Step 1: Remove stale pycache**

```bash
rm -rf platform_v2/tools/starship/__pycache__
```

- [ ] **Step 2: Update Dev HQ task**

Use MCP tools:
- `mcp complete_task` task #1023 with notes summarizing what was done
- `mcp log_decision` — "Starship rework: dispatcher import pattern for crew data, ADR-045 route split"
- `mcp update_project_understanding` for the Platform Audit project

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore(starship): clean up pycache after route split"
```
