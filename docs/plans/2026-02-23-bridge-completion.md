# Bridge Command Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the Bridge Command module — remove ~2,500 lines of dead endpoints, add real-time SSE dispatch, consolidate Ollama caching, port agent memory CRUD + performance/leaderboard from Team Management.

**Architecture:** All changes in two files: `routes.py` (backend) and `bridge.html` (frontend). Memory/performance endpoints are direct ports from team_management with identical SQL. SSE replaces polling with the existing `activity_stream()` endpoint. Ollama calls get a unified caching layer.

**Tech Stack:** Flask/Jinja2, PostgreSQL, vanilla JS, SSE (EventSource), existing ARCHIE CSS tokens

**Security Note:** All innerHTML usage must escape user-generated content via a shared `escHtml()` helper to prevent XSS. Data comes from admin-only DB, but defense-in-depth applies.

---

## Task 1: Remove dead endpoint groups from routes.py

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Remove the `LLM_CONNECTIONS` constant (lines 176-223).

**Step 2:** Remove the Connections endpoints + helpers:
- Lines 556-625: `get_llm_connections()` + `check_connection_health()`
- Lines 627-646: `check_ollama_status()` helper
- Lines 661-673: `check_api_key_status()` helper

**Step 3:** Remove the `/api/modules` orphan endpoint (lines 2735-2756): `get_module_mapping()`.

**Step 4:** Remove the Mining/Crypto section:
- Lines 5068-5095: `SCHEDULER_MODES` constant
- Lines 5098-5542: All 8 mining endpoints (`get_scheduler_status`, `update_scheduler_config`, `get_contributors`, `register_contributor`, `get_contributor_rewards`, `allocate_resource`, `release_resource`, `get_pool_integration_stats`)

**Step 5:** Remove the IDE/Development section:
- Lines 5545-6301: Entire IDE section including section header, `AI_BRIDGE_AVAILABLE` constant, `IDESession` class, `/ide` dashboard route, all 9 API endpoints, MCP protocol endpoints, and helper functions (`_detect_language`, `_search_knowledge_base`, `_static_analysis`, `_log_ide_connection`)

**Step 6:** Remove the `/api/dashboard/module-agents` orphan endpoint (lines 7427-7466): `get_module_agents()`.

**Step 7:** In `push_agent_event()` (lines 60-77), remove the fire-and-forget DB INSERT (lines 70-77 — the `try/except` block with the INSERT INTO `agent_activity_events`). Keep the in-memory `_activity_queue.appendleft(evt)` at line 68.

**Step 8:** Verify the platform still starts:
```bash
docker compose restart archie_platform && sleep 3 && docker logs --tail 20 archie_platform
```

**Step 9:** Spot-check a surviving endpoint:
```bash
docker exec archie_platform curl -s http://localhost:3000/tools/bridge/api/stations | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('success') else 'FAIL')"
```

**Step 10:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "refactor(bridge): remove ~2,500 lines of dead endpoints (mining, IDE, connections)"
```

---

## Task 2: Add cached Ollama `/api/ps` and consolidate uncached calls

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`

**Step 1:** Add `_ollama_ps_cache` dict and `_get_cached_ollama_ps()` function right after the existing `_get_cached_ollama_tags()` (line numbers will have shifted after Task 1 removals). Follow the identical pattern:

```python
_ollama_ps_cache = {"models": [], "time": 0}

def _get_cached_ollama_ps():
    """Get loaded Ollama models with 30s cache"""
    now = time.time()
    if _ollama_ps_cache["time"] and (now - _ollama_ps_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_ps_cache["models"]
    try:
        host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        resp = requests.get(f"{host}/api/ps", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_ps_cache["models"] = models
            _ollama_ps_cache["time"] = now
            return models
    except Exception:
        pass
    return _ollama_ps_cache["models"]
```

**Step 2:** Update `get_live_models()` endpoint to use cached tags:
```python
@bridge_bp.route("/api/models/live")
@login_required
def get_live_models():
    """Get actual model count from live Ollama API"""
    models, count = _get_cached_ollama_tags()
    return jsonify({"success": True, "count": count, "models": [m["name"] for m in models]})
```

**Step 3:** Update the dashboard metrics `/api/ps` call (find the `gpu_model = None` block) to use cached ps:
```python
gpu_model = None
ps_models = _get_cached_ollama_ps()
if ps_models:
    gpu_model = ps_models[0].get("name", "unknown")
```

**Step 4:** Update the health check `/api/ps` call (find `loaded_models = []` block in `get_bridge_stats`) to use cached ps:
```python
loaded_models = []
for m in _get_cached_ollama_ps():
    loaded_models.append({
        "name": m.get("name", "unknown"),
        "size": m.get("size", 0),
        "vram": m.get("size_vram", 0),
        "expires": m.get("expires_at", ""),
    })
```

**Step 5:** Verify:
```bash
docker compose restart archie_platform && sleep 3
docker exec archie_platform curl -s http://localhost:3000/tools/bridge/api/models/live | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Models: {d.get(\"count\", 0)}')"
```

**Step 6:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "perf(bridge): consolidate Ollama API calls behind 30s cache"
```

---

## Task 3: Replace console dispatch polling with SSE

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Add `_consoleEventSource` to the global console state variables (near `_consoleDispatchTimer` around line 7723):
```javascript
let _consoleEventSource = null;
```

**Step 2:** In `closeStationConsole()` (around line 7762), add SSE cleanup alongside the existing timer cleanup:
```javascript
if (_consoleEventSource) {
    _consoleEventSource.close();
    _consoleEventSource = null;
}
```

**Step 3:** In `loadConsoleDispatch()`, replace the `setInterval(fetchAndRender, 15000)` line at the end with SSE + polling fallback:

```javascript
// Initial load via fetch (immediate data)
await fetchAndRender();

// Real-time updates via SSE
try {
    if (_consoleEventSource) _consoleEventSource.close();
    _consoleEventSource = new EventSource('/tools/bridge/api/dispatch/stream');
    _consoleEventSource.onmessage = function(e) {
        try {
            var evt = JSON.parse(e.data);
            // Check if event belongs to our station
            var stationMatch = stationCodes.some(function(code) {
                return evt.data && evt.data.station_code === code;
            });
            if (stationMatch || !evt.data || !evt.data.station_code) {
                fetchAndRender();
            }
        } catch(err) { /* ignore parse errors */ }
    };
    _consoleEventSource.onerror = function() {
        // Fallback to polling on SSE failure
        if (_consoleEventSource) _consoleEventSource.close();
        _consoleEventSource = null;
        _consoleDispatchTimer = setInterval(fetchAndRender, 15000);
    };
} catch(sseErr) {
    // SSE not supported, fallback to polling
    _consoleDispatchTimer = setInterval(fetchAndRender, 15000);
}
```

**Step 4:** Verify in browser — open Bridge, click a station, switch to DSPCH tab. Check browser DevTools Network tab for `dispatch/stream` (EventStream type).

**Step 5:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "perf(bridge): replace 15s dispatch polling with SSE in LCARS console"
```

---

## Task 4: Port agent memory CRUD endpoints to bridge routes

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Reference: `/mnt/archie_brain/platform_v2/tools/team_management/routes.py` (lines 4203-4563)

**Step 1:** Add a new section comment `# --- Agent Memory CRUD ---` in routes.py, after the existing agent welfare endpoints.

**Step 2:** Port all 6 memory endpoints from team_management. Replace `@team_management_bp` with `@bridge_bp`. Keep all governance_audit_log logging. Keep identical SQL queries and response formats. The 6 endpoints are:

- `GET /api/agents/<int:agent_id>/memory` — List memories with pagination (page, per_page), filtering (memory_type, include_deleted, search). Query: `SELECT ... FROM agent_memory WHERE agent_id = %s` with dynamic WHERE. Response: `{success, data, count, total, page, per_page}`.

- `POST /api/agents/<int:agent_id>/memory` — Create memory. Required: memory_key, memory_value. Optional: memory_type (default "general"), importance (default 0.5), context. Logs `memory_created` to governance_audit_log. Response: `{success, data, message}`.

- `GET /api/agents/<int:agent_id>/memory/<int:memory_id>` — Get specific memory. Query: `SELECT * FROM agent_memory WHERE id = %s AND agent_id = %s`. Response: `{success, data}`.

- `PUT /api/agents/<int:agent_id>/memory/<int:memory_id>` — Update memory. Updatable: memory_value, importance, context, memory_type. Captures old value for audit diff. Logs `memory_updated` to governance_audit_log. Response: `{success, data, message}`.

- `DELETE /api/agents/<int:agent_id>/memory/<int:memory_id>` — Soft delete. Optional body: reason (default "Manual deletion by admin"). Uses DB function `soft_delete_agent_memory(memory_id, user_id, reason)`. Response: `{success, message}`.

- `POST /api/agents/<int:agent_id>/memory/<int:memory_id>/restore` — Restore. Updates `is_deleted=FALSE`, clears deletion fields. Logs `memory_restored` to governance_audit_log. Response: `{success, data, message}`.

**Step 3:** Verify endpoints:
```bash
docker compose restart archie_platform && sleep 3
docker exec archie_platform curl -s http://localhost:3000/tools/bridge/api/agents/1/memory | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {d.get(\"total\", 0)} memories' if d.get('success') else d)"
```

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): port agent memory CRUD endpoints from team management"
```

---

## Task 5: Add MEMORY tab to LCARS console

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Security:** All dynamic content must be escaped via `escHtml()` helper before insertion into DOM.

**Step 1:** Add an `escHtml()` utility function near the top of the JS section (if not already present):
```javascript
function escHtml(s) {
    if (typeof s !== 'string') s = String(s == null ? '' : s);
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```

**Step 2:** Add MEM tab pill after the STATS pill (after the `data-console-tab="metrics"` button, around line 6258):
```html
<button class="lcars-tab-pill" data-console-tab="memory">MEM</button>
```

**Step 3:** Add memory panel div after the metrics panel (after `id="lcarsMetricsPanel"`, around line 6264):
```html
<div class="lcars-tab-panel" data-console-panel="memory" id="lcarsMemoryPanel"></div>
```

**Step 4:** In the console tab switching logic (where `data-console-tab` click handlers fire), add:
```javascript
if (tabName === 'memory') loadConsoleMemory();
```

**Step 5:** Add `loadConsoleMemory()` function. This fetches memories for all agents in the station, renders them with filter/search/CRUD controls. Use `escHtml()` for all DB-sourced strings (memory_key, memory_value, agent names). Use `textContent` where possible, `innerHTML` only for structured layouts with escaped content.

Key behaviors:
- Fetches `/tools/bridge/api/agents/{id}/memory?per_page=50` for each agent in the station
- Sorts all memories by importance DESC
- Renders: memory key (bold), value (truncated to 120 chars), type badge (color-coded: general=green, skill=blue, preference=purple, interaction=red), importance bar (0-1 scale), agent name
- Edit/delete icon buttons per card
- Filter dropdown by memory_type + search input (client-side filter)
- "+ ADD" button opens modal form

**Step 6:** Add helper functions:
- `filterConsoleMemories()` — client-side filter by type dropdown + search input
- `showAddMemoryForm()` — creates modal with agent selector, key input, value textarea, type dropdown
- `submitNewMemory()` — POSTs to `/api/agents/{id}/memory`, refreshes list
- `editMemory(memoryId, agentId)` — GETs memory, opens edit modal with current values + importance slider
- `submitEditMemory(memoryId, agentId)` — PUTs update, refreshes list
- `deleteMemory(memoryId, agentId)` — confirm dialog, DELETEs with reason, refreshes list

**Step 7:** Verify in browser — open Bridge, click a station, click MEM tab. Should see memories with filter and CRUD controls.

**Step 8:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add MEMORY tab to LCARS station console with full CRUD"
```

---

## Task 6: Port performance + leaderboard endpoints to bridge routes

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`
- Reference: `/mnt/archie_brain/platform_v2/tools/team_management/routes.py` (lines 519-598, 1171-1299)

**Step 1:** Add the performance tracker import at the top of routes.py with graceful fallback:
```python
try:
    from ai_bridge.agent_performance_tracker import (
        get_agent_performance, update_agent_performance,
        get_top_performers, log_agent_action
    )
    _HAS_PERFORMANCE_TRACKER = True
except ImportError:
    _HAS_PERFORMANCE_TRACKER = False
```

**Step 2:** Add 4 endpoints in a new `# --- Agent Performance ---` section:

- `GET /api/agents/<int:agent_id>/performance` — Calls `get_agent_performance(agent_id)`, returns `{success, performance}` or 404 if no data. Guard with `_HAS_PERFORMANCE_TRACKER`.

- `POST /api/agents/<int:agent_id>/performance/update` — Calls `update_agent_performance(agent_id)`, returns `{success, message}`. Guard with `_HAS_PERFORMANCE_TRACKER`.

- `GET /api/agents/performance/leaderboard` — Accepts `limit` param (default 10). Calls `get_top_performers(limit=limit)`, returns `{success, leaderboard}`. Guard with `_HAS_PERFORMANCE_TRACKER`.

- `GET /api/agents/<int:agent_id>/work-history` — Direct SQL queries (no external module):
  - Proposals: `SELECT ... FROM improvement_proposals WHERE assigned_agent_id = %s OR contractor_agent_id = %s ORDER BY proposed_at DESC LIMIT 20`
  - Discussions: `SELECT DISTINCT d.id, d.topic, d.status, d.created_at, (subquery for message_count) FROM agent_discussions d JOIN agent_discussion_messages m ... WHERE m.agent_id = %s LIMIT 10`
  - Stats: `SELECT COUNT(*) FILTER (...) FROM improvement_proposals`
  - Returns: `{success, proposals, discussions, stats}`

**Step 3:** Verify:
```bash
docker compose restart archie_platform && sleep 3
docker exec archie_platform curl -s http://localhost:3000/tools/bridge/api/agents/performance/leaderboard | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('success') or 'tracker' in str(d) else d)"
```

**Step 4:** Commit.
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): port performance, leaderboard, and work-history endpoints"
```

---

## Task 7: Add Leaderboard sub-tab and work history in agent profile

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/bridge.html`

**Step 1:** Add Leaderboard sub-tab button after the Contractors sub-tab (after `data-subtab="contractors"` button, before closing `</div>` of `.crew-subtabs`, around line 5943):
```html
<button class="crew-subtab" data-subtab="leaderboard" onclick="switchCrewSubtab('leaderboard')">
    <i data-lucide="trophy"></i>
    <span data-i18n="bridge.crew.leaderboard">Leaderboard</span>
</button>
```

**Step 2:** Add Leaderboard sub-panel after the Contractors sub-panel (after `data-subpanel="contractors"` div, around line 6024):
```html
<!-- Leaderboard Sub-Panel -->
<div class="crew-subpanel" data-subpanel="leaderboard">
    <div class="briefing-card" style="--card-accent: #fbbf24; margin: 0 16px;">
        <div class="briefing-card-header">
            <i data-lucide="trophy"></i>
            <span data-i18n="bridge.crew.leaderboard">Performance Leaderboard</span>
            <button onclick="loadLeaderboard()" style="margin-left:auto;background:rgba(251,191,36,0.15);border:1px solid rgba(251,191,36,0.3);color:#fbbf24;padding:3px 8px;border-radius:4px;font-size:0.65rem;cursor:pointer;">Refresh</button>
        </div>
        <div class="briefing-card-body">
            <div id="leaderboard-container">
                <span class="briefing-muted">Loading leaderboard...</span>
            </div>
        </div>
    </div>
</div>
```

**Step 3:** Add `loadLeaderboard()` JS function:
- Fetches `/tools/bridge/api/agents/performance/leaderboard?limit=10`
- Renders ranked list: medal icon (#1 gold star, #2 silver, #3 bronze, rest numbered), agent name, tasks completed, success rate percentage, score
- Uses `escHtml()` for agent names
- Shows "No performance data available yet." if empty
- Uses DOM construction or escaped innerHTML

**Step 4:** In `switchCrewSubtab()` function, add auto-load:
```javascript
if (subtab === 'leaderboard') loadLeaderboard();
```

**Step 5:** In `openAgentProfile()` function, after the Performance (24h) section and before the Wellness section, add a Work History block:
- Fetches `/tools/bridge/api/agents/{id}/work-history`
- Shows "PROPOSALS" header with last 5 proposals (status colored + title)
- Shows aggregate stats: "X/Y proposals deployed"
- All strings escaped with `escHtml()`

**Step 6:** Verify in browser:
- Bridge → Crew → Leaderboard sub-tab (ranked agents or "No data" message)
- Click station → CREW → click agent → profile shows work history below performance stats

**Step 7:** Commit.
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add performance leaderboard sub-tab and work history in profile"
```

---

## Execution Order

| Task | Dependencies | Impact |
|------|-------------|--------|
| 1: Dead endpoint cleanup | None | ~2,500 lines removed |
| 2: Ollama caching | After Task 1 (line numbers shift) | Performance improvement |
| 3: SSE dispatch | None (HTML only) | Real-time updates |
| 4: Memory endpoints | After Task 1 (routes.py) | New API surface |
| 5: Memory UI | After Task 4 | New console tab |
| 6: Performance endpoints | After Task 1 (routes.py) | New API surface |
| 7: Leaderboard UI | After Task 6 | New crew sub-tab |

Tasks 1→2 are sequential (backend, same file, line numbers shift).
Tasks 3 and 4 can run in parallel (different files).
Tasks 5 depends on 4. Tasks 6 depends on 1. Tasks 7 depends on 6.
