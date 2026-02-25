# Phase 6: Multi-Agent Orchestration UI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Mission Control tab, enhanced agent roster, and multi-agent execution log to Team Management, powered by SSE streaming and a new activity events table.

**Architecture:** Enhance existing `team_management.html` (624 lines, 6 tabs, IIFE pattern) with 2 new tabs (Mission Control, Multi-Agent Log) and expanded roster cards. Add SSE endpoint + 5 API endpoints to `bridge/routes.py`. Hook event emission into `orchestration_engine.py`. Add chat activity badge to `archie_chat.html`.

**Tech Stack:** Flask SSE (generator + `text/event-stream`), PostgreSQL, EventSource API, CSS animations, existing `apiFetch()` + `el()` helpers, `--archie-*` design tokens.

---

## Context for All Tasks

**Design spec:** `docs/plans/2026-02-18-phase6-multi-agent-ui-design.md`

**Key files:**
- `platform_v2/templates/tools/team_management.html` — 624 lines, IIFE at lines 203-621, 6 tabs, `apiFetch()` helper at line 268, `loadActiveTab()` dispatcher at line 597
- `platform_v2/tools/bridge/routes.py` — 6779 lines, `bridge_bp` Blueprint with url_prefix `/tools/bridge`, last route ends at line 6768
- `ai_bridge/orchestration_engine.py` — 2054 lines, `OrchestrationEngine.orchestrate()` at lines 205-439, success return at 406-417, error at 430-439
- `platform_v2/templates/tools/archie_chat.html` — Chat template with `.status-right` section in status bar

**Existing patterns:**
- Tab system: `tmTab(id, btn)` at line 211, panes use `pane-{id}` IDs
- Loader dispatch: `loadActiveTab()` at line 597 with `{roster: loadRoster, ...}` map
- CSS uses `.tm-*` classes and `--archie-*` design tokens (Orbitron headings, JetBrains Mono code)
- Helper `el(tag, cls, text)` at line 222 creates DOM elements
- Helper `pill(label, cls)` at line 229 creates badge pills
- Helper `statusPill(st)` at line 235 returns colored status pills
- Helper `timeAgo(ts)` at line 243 formats relative timestamps
- Helper `apiFetch(url)` at line 268 does async fetch with error handling
- All API routes prefixed with `/tools/bridge/`

**DB connection pattern** (from routes.py):
```python
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=os.environ.get("DB_PASSWORD", "archie"),
    )
```

---

### Task 1: Create Migration 110

**Files:**
- Create: `database/migrations/110_agent_activity_events.sql`

**Step 1: Write the migration file**

```sql
-- Migration 110: Agent activity events for SSE streaming
-- Part of Phase 6: Multi-Agent Orchestration UI

CREATE TABLE IF NOT EXISTS agent_activity_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    agent_id INTEGER REFERENCES agents(id),
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_agent_activity_events_created ON agent_activity_events(created_at DESC);
CREATE INDEX idx_agent_activity_events_agent ON agent_activity_events(agent_id);

COMMENT ON TABLE agent_activity_events IS 'Lightweight event store for SSE streaming. Auto-pruned to 24h.';
```

**Step 2: Run the migration**

```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/110_agent_activity_events.sql
```

If the migration file isn't mounted, copy it in first:
```bash
docker cp database/migrations/110_agent_activity_events.sql archie_database:/tmp/
docker exec -it archie_database psql -U archie -d archie -f /tmp/110_agent_activity_events.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX` x2, `COMMENT`

**Step 3: Verify**

```bash
docker exec -it archie_database psql -U archie -d archie -c "\d agent_activity_events"
```

Expected: Table with columns id, event_type, agent_id, data, created_at.

**Step 4: Commit**

```bash
git add database/migrations/110_agent_activity_events.sql
git commit -m "feat(db): migration 110 — agent_activity_events table for SSE streaming"
```

---

### Task 2: Backend — Event Queue + SSE Endpoint + Activity APIs

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (add after line 6768, before mesh imports at line 6774)

**Step 1: Add the in-memory event queue and push function**

At the module level (after the imports, around line 26), add:

```python
import json as _json
import time as _time
from collections import deque
from flask import Response, stream_with_context

# --- SSE Activity Event Queue ---
_activity_queue = deque(maxlen=200)

def push_agent_event(event_type, agent_id=None, data=None):
    """Push an event to the in-memory SSE queue and persist to DB."""
    evt = {
        "event_type": event_type,
        "agent_id": agent_id,
        "data": data or {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _activity_queue.appendleft(evt)
    # Persist to DB (fire-and-forget)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO agent_activity_events (event_type, agent_id, data) VALUES (%s, %s, %s)",
            (event_type, agent_id, _json.dumps(data or {})),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Failed to persist activity event: %s", e)
```

Note: `json` may already be imported — check first. If `import json` exists at the top, use that. If not, add `import json` (not `_json`). Similarly for `time`. The `Response`, `stream_with_context` imports need to be added to the existing Flask import line at line 17:
```python
from flask import Blueprint, render_template, jsonify, request, Response, stream_with_context
```

Also check if `collections` and `deque` are already imported. If not, add `from collections import deque` near the top.

**Step 2: Add the SSE streaming endpoint**

Add after line 6768 (after `get_module_agents()`, before the mesh imports block):

```python
# ============================================================
# Phase 6: Mission Control — SSE + Activity Endpoints
# ============================================================

@bridge_bp.route("/api/dispatch/stream")
@login_required
def activity_stream():
    """SSE endpoint for real-time agent activity events."""
    def generate():
        sent_count = 0
        while True:
            current = list(_activity_queue)
            new_count = len(current)
            if new_count > sent_count:
                # New events are at the front (appendleft)
                new_events = current[: new_count - sent_count]
                for evt in reversed(new_events):
                    yield "event: {}\ndata: {}\n\n".format(
                        evt["event_type"], _json.dumps(evt)
                    )
                sent_count = new_count
            yield ": heartbeat\n\n"
            _time.sleep(5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

**Step 3: Add activity history endpoint (for page load)**

```python
@bridge_bp.route("/api/dispatch/activity-history")
@login_required
def activity_history():
    """Return last 50 activity events for initial page load."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT e.id, e.event_type, e.agent_id, e.data, e.created_at,
                   a.codename, a.display_name
            FROM agent_activity_events e
            LEFT JOIN agents a ON a.id = e.agent_id
            ORDER BY e.created_at DESC
            LIMIT 50
        """)
        events = cur.fetchall()
        cur.close()
        conn.close()
        for ev in events:
            ev["created_at"] = ev["created_at"].isoformat() if ev["created_at"] else None
        return jsonify(events)
    except Exception as e:
        logger.error("activity_history error: %s", e)
        return jsonify([])
```

**Step 4: Add agent detail endpoints**

```python
@bridge_bp.route("/api/agents/<int:agent_id>/executions")
@login_required
def agent_executions(agent_id):
    """Recent execution history for a specific agent."""
    limit = request.args.get("limit", 10, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT os.id, os.session_uuid, os.user_message,
                   os.status, os.model_used, os.total_duration_ms,
                   os.created_at, os.completed_at,
                   (SELECT COUNT(*) FROM orchestration_steps st WHERE st.session_id = os.id) as step_count
            FROM orchestration_sessions os
            WHERE os.agent_id = %s
            ORDER BY os.created_at DESC
            LIMIT %s
        """, (agent_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for r in rows:
            r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
            r["completed_at"] = r["completed_at"].isoformat() if r.get("completed_at") else None
        return jsonify(rows)
    except Exception as e:
        logger.error("agent_executions error: %s", e)
        return jsonify([])
```

```python
@bridge_bp.route("/api/agents/<int:agent_id>/emotional-state")
@login_required
def agent_emotional_state(agent_id):
    """Current emotional state for a specific agent."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT mood, stress_level, energy_level, last_interaction,
                   context, updated_at
            FROM agent_emotional_state
            WHERE agent_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """, (agent_id,))
        state = cur.fetchone()
        # Also get last rest cycle
        cur.execute("""
            SELECT started_at, ended_at, reason
            FROM agent_rest_cycles
            WHERE agent_id = %s
            ORDER BY started_at DESC
            LIMIT 1
        """, (agent_id,))
        rest = cur.fetchone()
        cur.close()
        conn.close()
        if state:
            state["updated_at"] = state["updated_at"].isoformat() if state.get("updated_at") else None
            state["last_interaction"] = state["last_interaction"].isoformat() if state.get("last_interaction") else None
        if rest:
            rest["started_at"] = rest["started_at"].isoformat() if rest.get("started_at") else None
            rest["ended_at"] = rest["ended_at"].isoformat() if rest.get("ended_at") else None
        return jsonify({"emotional_state": state, "last_rest": rest})
    except Exception as e:
        logger.error("agent_emotional_state error: %s", e)
        return jsonify({"emotional_state": None, "last_rest": None})
```

**Step 5: Add multi-agent session endpoints**

```python
@bridge_bp.route("/api/dispatch/multi-agent-sessions")
@login_required
def multi_agent_sessions():
    """Paginated list of multi-agent orchestration sessions."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    offset = (page - 1) * per_page
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Multi-agent sessions have multiple agent steps
        cur.execute("""
            SELECT os.id, os.session_uuid, os.user_message, os.status,
                   os.total_duration_ms, os.created_at, os.completed_at,
                   os.model_used,
                   (SELECT COUNT(DISTINCT st.agent_id) FROM orchestration_steps st
                    WHERE st.session_id = os.id AND st.agent_id IS NOT NULL) as agent_count,
                   (SELECT COUNT(*) FROM orchestration_steps st WHERE st.session_id = os.id) as step_count
            FROM orchestration_sessions os
            WHERE os.total_steps > 3
            ORDER BY os.created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        sessions = cur.fetchall()
        # Total count
        cur.execute("SELECT COUNT(*) as total FROM orchestration_sessions WHERE total_steps > 3")
        total = cur.fetchone()["total"]
        cur.close()
        conn.close()
        for s in sessions:
            s["created_at"] = s["created_at"].isoformat() if s.get("created_at") else None
            s["completed_at"] = s["completed_at"].isoformat() if s.get("completed_at") else None
        return jsonify({"sessions": sessions, "total": total, "page": page, "per_page": per_page})
    except Exception as e:
        logger.error("multi_agent_sessions error: %s", e)
        return jsonify({"sessions": [], "total": 0, "page": page, "per_page": per_page})
```

```python
@bridge_bp.route("/api/dispatch/multi-agent-sessions/<session_id>")
@login_required
def multi_agent_session_detail(session_id):
    """Full detail for a multi-agent session with steps."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Session info
        cur.execute("""
            SELECT os.id, os.session_uuid, os.user_message, os.status,
                   os.model_used, os.total_duration_ms, os.total_steps,
                   os.created_at, os.completed_at, os.metadata
            FROM orchestration_sessions os
            WHERE os.session_uuid = %s OR os.id::text = %s
        """, (session_id, session_id))
        session = cur.fetchone()
        if not session:
            return jsonify({"error": "Session not found"}), 404
        session["created_at"] = session["created_at"].isoformat() if session.get("created_at") else None
        session["completed_at"] = session["completed_at"].isoformat() if session.get("completed_at") else None
        # Steps
        cur.execute("""
            SELECT st.id, st.step_type, st.label, st.data,
                   st.duration_ms, st.success, st.agent_id, st.model_used,
                   a.codename, a.display_name
            FROM orchestration_steps st
            LEFT JOIN agents a ON a.id = st.agent_id
            WHERE st.session_id = %s
            ORDER BY st.id ASC
        """, (session["id"],))
        steps = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"session": session, "steps": steps})
    except Exception as e:
        logger.error("multi_agent_session_detail error: %s", e)
        return jsonify({"error": str(e)}), 500
```

**Step 6: Add fleet metrics endpoint**

```python
@bridge_bp.route("/api/dispatch/fleet-metrics")
@login_required
def fleet_metrics():
    """Aggregate fleet metrics for Mission Control."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Active vs total agents
        cur.execute("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE status = 'active') as active FROM agents")
        agents = cur.fetchone()
        # Tasks this hour
        cur.execute("""
            SELECT COUNT(*) as count,
                   AVG(total_duration_ms) as avg_duration,
                   COUNT(*) FILTER (WHERE status = 'error') as errors
            FROM orchestration_sessions
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """)
        tasks = cur.fetchone()
        # GPU model (loaded Ollama model)
        gpu_model = None
        try:
            resp = requests.get("http://host.docker.internal:11434/api/ps", timeout=3)
            if resp.ok:
                models = resp.json().get("models", [])
                if models:
                    gpu_model = models[0].get("name", "unknown")
        except Exception:
            pass
        # Top agent today
        cur.execute("""
            SELECT a.codename, a.display_name, COUNT(*) as task_count
            FROM orchestration_sessions os
            JOIN agents a ON a.id = os.agent_id
            WHERE os.created_at > CURRENT_DATE
            GROUP BY a.id, a.codename, a.display_name
            ORDER BY task_count DESC
            LIMIT 1
        """)
        top = cur.fetchone()
        cur.close()
        conn.close()
        total_tasks = tasks["count"] or 0
        error_count = tasks["errors"] or 0
        return jsonify({
            "active_agents": agents["active"] or 0,
            "total_agents": agents["total"] or 0,
            "tasks_this_hour": total_tasks,
            "avg_duration_ms": round(tasks["avg_duration"] or 0),
            "error_rate": round((error_count / total_tasks * 100) if total_tasks > 0 else 0, 1),
            "gpu_model": gpu_model,
            "top_agent": top,
        })
    except Exception as e:
        logger.error("fleet_metrics error: %s", e)
        return jsonify({
            "active_agents": 0, "total_agents": 0, "tasks_this_hour": 0,
            "avg_duration_ms": 0, "error_rate": 0, "gpu_model": None, "top_agent": None,
        })
```

**Step 7: Verify all new routes are syntactically correct**

```bash
docker exec archie_platform python3 -c "from tools.bridge.routes import bridge_bp; print('OK:', len(bridge_bp.deferred_functions), 'routes')"
```

Expected: No import errors, route count should be higher than before.

**Step 8: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): SSE endpoint + activity/agent-detail/multi-agent APIs for Phase 6"
```

---

### Task 3: Hook Event Emission into Orchestration Engine

**Files:**
- Modify: `ai_bridge/orchestration_engine.py` (add event push calls)

**Step 1: Add the import and push function reference**

Near the top of the file (after line 32, after existing imports), add:

```python
def _push_event(event_type, agent_id=None, data=None):
    """Push activity event to SSE queue. Fails silently if bridge not loaded."""
    try:
        from platform_v2.tools.bridge.routes import push_agent_event
        push_agent_event(event_type, agent_id, data)
    except Exception:
        pass  # Bridge may not be loaded in test contexts
```

This uses lazy import to avoid circular dependency (orchestration_engine is in ai_bridge, push_agent_event is in platform_v2).

**Step 2: Add event emission in the `orchestrate()` method**

In `orchestrate()`, add events at these points:

**Before execution (around line 287, before `_step_execute()` call):**
Find the line that calls `_step_execute` and add before it:
```python
_push_event("task_start", agent_id=selected_agent_id, data={
    "task_type": intent_result.get("intent_type", "general"),
    "model": model_used,
    "message_preview": user_message[:80] if user_message else "",
})
```

**After success return (around line 406):**
Find where `OrchestrationResult(success=True, ...)` is created. Just before the return, add:
```python
_push_event("task_complete", agent_id=selected_agent_id, data={
    "duration_ms": total_ms,
    "success": True,
    "model": model_used,
    "message_preview": user_message[:80] if user_message else "",
})
```

**After error return (around line 430):**
Find where `OrchestrationResult(success=False, ...)` is created. Just before the return, add:
```python
_push_event("task_error", agent_id=selected_agent_id if 'selected_agent_id' in dir() else None, data={
    "error": str(e)[:200],
    "message_preview": user_message[:80] if user_message else "",
})
```

**In welfare check (in `_step_welfare_check`, around line 804-829):**
When a welfare intervention occurs, add:
```python
_push_event("welfare_event", agent_id=agent_id, data={
    "type": "rest_needed",
    "action": "sent_to_lounge",
})
```

**Step 3: Verify the module loads**

```bash
docker exec archie_platform python3 -c "from ai_bridge.orchestration_engine import OrchestrationEngine; print('OK')"
```

**Step 4: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(orchestration): push SSE activity events on task start/complete/error/welfare"
```

---

### Task 4: Mission Control Tab — UI

**Files:**
- Modify: `platform_v2/templates/tools/team_management.html`

This is the largest task. We add the Mission Control tab as the first tab position.

**Step 1: Add Mission Control CSS**

Insert before the closing `</style>` tag (around line 97). Add these styles:

```css
/* === Mission Control === */
.mc-fleet-bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.mc-fleet-card{display:flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid var(--archie-border,#2a3a4a);border-radius:6px;background:var(--archie-card-bg,#0a1628);font-size:.85rem;min-width:100px}
.mc-fleet-card .mc-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.mc-dot-idle{background:#4ade80}.mc-dot-executing{background:#fbbf24}.mc-dot-error{background:#f87171}.mc-dot-resting{background:#6b7280}
.mc-fleet-card .mc-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100px}

.mc-body{display:flex;gap:16px}
.mc-feed{flex:0 0 60%;max-height:520px;overflow-y:auto}
.mc-metrics{flex:1}

.mc-event{display:flex;gap:10px;padding:10px;border-bottom:1px solid var(--archie-border,#2a3a4a);animation:mcSlideIn .3s ease}
@keyframes mcSlideIn{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:translateY(0)}}
.mc-event .mc-evt-time{font-size:.75rem;color:var(--archie-muted,#6b7280);min-width:60px}
.mc-event .mc-evt-agent{font-weight:600;min-width:80px}
.mc-evt-badge{padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700;text-transform:uppercase}
.mc-evt-badge-executing{background:#1e40af;color:#93c5fd}
.mc-evt-badge-completed{background:#166534;color:#86efac}
.mc-evt-badge-error{background:#991b1b;color:#fca5a5}
.mc-evt-badge-welfare{background:#581c87;color:#d8b4fe}
.mc-evt-task{font-size:.85rem;color:var(--archie-text-secondary,#94a3b8);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mc-evt-meta{font-size:.75rem;color:var(--archie-muted,#6b7280)}

.mc-metric-card{padding:12px;border:1px solid var(--archie-border,#2a3a4a);border-radius:8px;background:var(--archie-card-bg,#0a1628);margin-bottom:10px;text-align:center}
.mc-metric-card .mc-val{font-family:'Orbitron',monospace;font-size:1.6rem;color:var(--archie-accent,#60a5fa)}
.mc-metric-card .mc-label{font-size:.75rem;color:var(--archie-muted,#6b7280);margin-top:2px}

.mc-empty{text-align:center;padding:40px;color:var(--archie-muted,#6b7280)}

@media(max-width:768px){.mc-body{flex-direction:column}.mc-feed{flex:none;max-height:300px}}
```

**Step 2: Add Mission Control tab button (first position)**

At line 112 (inside the `<div class="tm-tabs">`, before the existing "Agent Roster" button), add:

```html
<button class="tm-tab active" onclick="tmTab('mission',this)" role="tab">Mission Control</button>
```

And change the existing "Agent Roster" button from `class="tm-tab active"` to `class="tm-tab"` (remove `active`).

**Step 3: Add Mission Control pane**

After line 120 (after `<div class="tm-inner">`), add a new pane before `pane-roster`:

```html
<!-- Mission Control Pane -->
<div class="tm-pane active" id="pane-mission">
    <div id="mc-fleet-bar" class="mc-fleet-bar"></div>
    <div class="mc-body">
        <div class="mc-feed" id="mc-feed"></div>
        <div class="mc-metrics" id="mc-metrics"></div>
    </div>
</div>
```

And change the existing `pane-roster` from `class="tm-pane active"` to `class="tm-pane"`.

**Step 4: Update the JS default activeTab and loader dispatch**

In the IIFE (line 207), change:
```javascript
var activeTab = 'roster';
```
to:
```javascript
var activeTab = 'mission';
```

In `loadActiveTab()` (line 598), add `mission: loadMission` to the loaders object:
```javascript
var loaders = {
    mission: loadMission,
    roster: loadRoster, stations: loadStations, queue: loadQueue,
    hr: loadHR, iaae: loadIAAE, perf: loadPerformance
};
```

**Step 5: Add the Mission Control loader functions**

Add before `loadActiveTab()` (before line 597). Use the `el()` helper and `textContent` for safe DOM construction:

```javascript
/* ============ Mission Control ============ */
var _sseSource = null;
var _mcEvents = [];
var MC_MAX = 50;

async function loadMission() {
    loadFleetBar();
    loadMCMetrics();
    loadMCFeed();
    startSSE();
}

async function loadFleetBar() {
    var data = await apiFetch('/tools/bridge/api/agents');
    var bar = document.getElementById('mc-fleet-bar');
    if (!bar || !data) return;
    clearEl('mc-fleet-bar');
    (data.agents || data || []).forEach(function(ag) {
        var card = el('div', 'mc-fleet-card');
        var st = (ag.status || 'active').toLowerCase();
        var dotCls = st === 'active' ? 'mc-dot-idle' : st === 'lounge' ? 'mc-dot-resting' : st === 'error' ? 'mc-dot-error' : 'mc-dot-idle';
        var dot = el('span', 'mc-dot ' + dotCls);
        var name = el('span', 'mc-name');
        name.textContent = ag.display_name || ag.codename || 'Agent';
        card.appendChild(dot);
        card.appendChild(name);
        bar.appendChild(card);
    });
}

async function loadMCMetrics() {
    var m = await apiFetch('/tools/bridge/api/dispatch/fleet-metrics');
    var wrap = document.getElementById('mc-metrics');
    if (!wrap || !m) return;
    clearEl('mc-metrics');
    var items = [
        {val: (m.active_agents || 0) + ' / ' + (m.total_agents || 0), label: 'Active Agents'},
        {val: String(m.tasks_this_hour || 0), label: 'Tasks This Hour'},
        {val: (m.avg_duration_ms || 0) + 'ms', label: 'Avg Duration'},
        {val: (m.error_rate || 0) + '%', label: 'Error Rate'},
        {val: m.gpu_model || 'None', label: 'GPU Model'},
    ];
    if (m.top_agent) {
        items.push({val: (m.top_agent.display_name || m.top_agent.codename) + ' (' + m.top_agent.task_count + ')', label: 'Top Agent Today'});
    }
    items.forEach(function(it) {
        var card = el('div', 'mc-metric-card');
        var valEl = el('div', 'mc-val');
        valEl.textContent = it.val;
        var labEl = el('div', 'mc-label');
        labEl.textContent = it.label;
        card.appendChild(valEl);
        card.appendChild(labEl);
        wrap.appendChild(card);
    });
}

async function loadMCFeed() {
    var events = await apiFetch('/tools/bridge/api/dispatch/activity-history');
    var feed = document.getElementById('mc-feed');
    if (!feed) return;
    clearEl('mc-feed');
    if (!events || events.length === 0) {
        var empty = el('div', 'mc-empty');
        empty.textContent = 'No activity events yet. Events appear as agents process tasks.';
        feed.appendChild(empty);
        return;
    }
    _mcEvents = events.slice(0, MC_MAX);
    _mcEvents.forEach(function(evt) { feed.appendChild(buildEventCard(evt)); });
}

function buildEventCard(evt) {
    var row = el('div', 'mc-event');
    var evtType = evt.event_type || 'unknown';
    var badgeCls = evtType === 'task_start' ? 'executing' : evtType === 'task_complete' ? 'completed' : evtType === 'task_error' ? 'error' : evtType === 'welfare_event' ? 'welfare' : 'executing';
    var data = evt.data || {};
    var preview = data.message_preview || data.error || evtType;
    if (preview.length > 80) preview = preview.substring(0, 80) + '...';
    var meta = '';
    if (data.model) meta += data.model;
    if (data.duration_ms) meta += (meta ? ' | ' : '') + data.duration_ms + 'ms';

    var timeSpan = el('span', 'mc-evt-time');
    timeSpan.textContent = timeAgo(evt.created_at);
    var agentSpan = el('span', 'mc-evt-agent');
    agentSpan.textContent = evt.display_name || evt.codename || 'System';
    var badge = el('span', 'mc-evt-badge mc-evt-badge-' + badgeCls);
    badge.textContent = evtType.replace(/_/g, ' ');
    var taskSpan = el('span', 'mc-evt-task');
    taskSpan.textContent = preview;
    row.appendChild(timeSpan);
    row.appendChild(agentSpan);
    row.appendChild(badge);
    row.appendChild(taskSpan);
    if (meta) {
        var metaSpan = el('span', 'mc-evt-meta');
        metaSpan.textContent = meta;
        row.appendChild(metaSpan);
    }
    return row;
}

function startSSE() {
    if (_sseSource) return;  // already connected
    if (typeof EventSource === 'undefined') return;  // fallback to polling
    try {
        _sseSource = new EventSource('/tools/bridge/api/dispatch/stream');
        _sseSource.addEventListener('task_start', handleSSE);
        _sseSource.addEventListener('task_complete', handleSSE);
        _sseSource.addEventListener('task_error', handleSSE);
        _sseSource.addEventListener('welfare_event', handleSSE);
        _sseSource.addEventListener('metrics', function() { loadMCMetrics(); });
        _sseSource.onerror = function() {
            // EventSource auto-reconnects; just log
            console.warn('SSE connection error, will auto-reconnect');
        };
    } catch(e) {
        console.warn('SSE not supported, using polling fallback');
    }
}

function handleSSE(e) {
    try {
        var evt = JSON.parse(e.data);
        var feed = document.getElementById('mc-feed');
        if (!feed) return;
        // Remove empty placeholder
        var empty = feed.querySelector('.mc-empty');
        if (empty) empty.remove();
        // Prepend new event
        var card = buildEventCard(evt);
        feed.insertBefore(card, feed.firstChild);
        // Trim to max
        while (feed.children.length > MC_MAX) {
            feed.removeChild(feed.lastChild);
        }
        // Refresh fleet bar on status changes
        loadFleetBar();
    } catch(err) {
        console.warn('SSE parse error:', err);
    }
}

function stopSSE() {
    if (_sseSource) { _sseSource.close(); _sseSource = null; }
}
```

**Step 6: Clean up SSE on tab switch**

Modify the `tmTab()` function to stop SSE when leaving Mission Control and start it when entering:

In the existing `tmTab` function (line 211), after `loadActiveTab();` add:
```javascript
if (id !== 'mission') { stopSSE(); }
```

**Step 7: Verify template parses**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/team_management.html')
print('OK')
"
```

**Step 8: Commit**

```bash
git add platform_v2/templates/tools/team_management.html
git commit -m "feat(team): Mission Control tab with SSE live feed, fleet bar, and metrics"
```

---

### Task 5: Enhanced Agent Roster — Expandable Cards

**Files:**
- Modify: `platform_v2/templates/tools/team_management.html` (continue editing)

**Step 1: Add roster expansion CSS**

Append to the CSS section (before `</style>`):

```css
/* === Enhanced Roster Drawer === */
.tm-agent{cursor:pointer;transition:border-color .2s}
.tm-agent:hover{border-color:var(--archie-accent,#60a5fa)}
.tm-agent-drawer{display:none;padding:12px 16px;border-top:1px solid var(--archie-border,#2a3a4a);background:var(--archie-bg-secondary,#0c1a2e);animation:mcSlideIn .3s ease}
.tm-agent-drawer.open{display:block}
.drawer-section{margin-bottom:14px}
.drawer-section h4{font-family:'Orbitron',monospace;font-size:.8rem;color:var(--archie-accent,#60a5fa);margin:0 0 6px;text-transform:uppercase;letter-spacing:.5px}
.drawer-stats{display:flex;gap:12px;flex-wrap:wrap}
.drawer-stat{text-align:center;min-width:80px}
.drawer-stat .ds-val{font-family:'Orbitron',monospace;font-size:1.1rem;color:var(--archie-text,#e2e8f0)}
.drawer-stat .ds-label{font-size:.7rem;color:var(--archie-muted,#6b7280)}
.drawer-mood{display:flex;align-items:center;gap:8px;font-size:.9rem;flex-wrap:wrap}
.drawer-bar{height:6px;border-radius:3px;background:var(--archie-border,#2a3a4a);flex:0 0 120px;max-width:120px}
.drawer-bar-fill{height:100%;border-radius:3px;transition:width .3s}
.drawer-exec-table{width:100%;font-size:.8rem;border-collapse:collapse}
.drawer-exec-table th,.drawer-exec-table td{padding:4px 8px;text-align:left;border-bottom:1px solid var(--archie-border,#2a3a4a)}
.drawer-exec-table th{color:var(--archie-muted,#6b7280);font-weight:600}
.drawer-actions{display:flex;gap:8px;flex-wrap:wrap}
.drawer-actions button{padding:4px 12px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;background:var(--archie-card-bg,#0a1628);color:var(--archie-text,#e2e8f0);font-size:.8rem;cursor:pointer}
.drawer-actions button:hover{border-color:var(--archie-accent,#60a5fa)}
```

**Step 2: Modify `loadRoster()` to add click-to-expand behavior**

In the existing `loadRoster()` function (lines 302-346), find where agent cards are built and modify to add click handler and drawer div. After each agent card element is created and populated, before appending to the grid, add:

```javascript
card.style.cursor = 'pointer';
card.onclick = function(){ toggleAgentDrawer(ag.id, card); };
var drawer = el('div', 'tm-agent-drawer');
drawer.id = 'agent-drawer-' + ag.id;
card.appendChild(drawer);
```

**Step 3: Add the drawer toggle and loading functions**

Add after the Mission Control functions and before `loadActiveTab()`:

```javascript
/* ============ Agent Drawer ============ */
var _openDrawer = null;

function toggleAgentDrawer(agentId, cardEl) {
    var drawerId = 'agent-drawer-' + agentId;
    var drawer = document.getElementById(drawerId);
    if (!drawer) return;
    // Close currently open drawer
    if (_openDrawer && _openDrawer !== drawerId) {
        var prev = document.getElementById(_openDrawer);
        if (prev) prev.classList.remove('open');
    }
    if (drawer.classList.contains('open')) {
        drawer.classList.remove('open');
        _openDrawer = null;
    } else {
        drawer.classList.add('open');
        _openDrawer = drawerId;
        loadAgentDrawer(agentId, drawer);
    }
}

async function loadAgentDrawer(agentId, drawer) {
    var loadingMsg = el('div');
    loadingMsg.textContent = 'Loading...';
    loadingMsg.style.cssText = 'padding:10px;color:var(--archie-muted)';
    drawer.textContent = '';
    drawer.appendChild(loadingMsg);

    var results = await Promise.all([
        apiFetch('/tools/bridge/api/agents/' + agentId + '/executions?limit=10'),
        apiFetch('/tools/bridge/api/agents/' + agentId + '/emotional-state'),
    ]);
    var execs = results[0];
    var emo = results[1];
    drawer.textContent = '';

    // Emotional State section
    var emoSection = el('div', 'drawer-section');
    var emoTitle = el('h4');
    emoTitle.textContent = 'Emotional State';
    emoSection.appendChild(emoTitle);

    var es = emo && emo.emotional_state;
    if (es) {
        var moodWrap = el('div', 'drawer-mood');
        var moodText = el('span');
        moodText.textContent = 'Mood: ' + (es.mood || 'neutral');
        moodWrap.appendChild(moodText);

        var stressLabel = el('span');
        stressLabel.textContent = 'Stress:';
        moodWrap.appendChild(stressLabel);
        var stressBar = el('div', 'drawer-bar');
        var stressFill = el('div', 'drawer-bar-fill');
        var stressVal = es.stress_level || 0;
        var stressColor = stressVal > 0.7 ? '#f87171' : stressVal > 0.4 ? '#fbbf24' : '#4ade80';
        stressFill.style.width = (stressVal * 100) + '%';
        stressFill.style.background = stressColor;
        stressBar.appendChild(stressFill);
        moodWrap.appendChild(stressBar);

        var energyLabel = el('span');
        energyLabel.textContent = 'Energy:';
        moodWrap.appendChild(energyLabel);
        var energyBar = el('div', 'drawer-bar');
        var energyFill = el('div', 'drawer-bar-fill');
        var energyVal = es.energy_level || 0;
        var energyColor = energyVal < 0.3 ? '#f87171' : energyVal < 0.6 ? '#fbbf24' : '#4ade80';
        energyFill.style.width = (energyVal * 100) + '%';
        energyFill.style.background = energyColor;
        energyBar.appendChild(energyFill);
        moodWrap.appendChild(energyBar);
        emoSection.appendChild(moodWrap);

        if (emo.last_rest) {
            var restInfo = el('div');
            restInfo.style.cssText = 'font-size:.75rem;color:var(--archie-muted);margin-top:4px';
            restInfo.textContent = 'Last rest: ' + timeAgo(emo.last_rest.started_at);
            emoSection.appendChild(restInfo);
        }
    } else {
        var noData = el('span');
        noData.textContent = 'No data';
        noData.style.color = 'var(--archie-muted)';
        emoSection.appendChild(noData);
    }
    drawer.appendChild(emoSection);

    // Recent Executions section
    var execSection = el('div', 'drawer-section');
    var execTitle = el('h4');
    execTitle.textContent = 'Recent Executions';
    execSection.appendChild(execTitle);

    if (execs && execs.length > 0) {
        var table = el('table', 'drawer-exec-table');
        var thead = el('thead');
        var headRow = el('tr');
        ['Time', 'Task', 'Model', 'Duration', 'Status'].forEach(function(h) {
            var th = el('th');
            th.textContent = h;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);
        var tbody = el('tbody');
        execs.forEach(function(ex) {
            var tr = el('tr');
            var tdTime = el('td');
            tdTime.textContent = timeAgo(ex.created_at);
            var tdTask = el('td');
            tdTask.textContent = (ex.user_message || '').substring(0, 60);
            var tdModel = el('td');
            tdModel.textContent = ex.model_used || '-';
            var tdDur = el('td');
            tdDur.textContent = fmtMs(ex.total_duration_ms);
            var tdStatus = el('td');
            var st = ex.status || 'unknown';
            var stCls = st === 'completed' ? 'tm-pill-green' : st === 'error' ? 'tm-pill-red' : 'tm-pill-amber';
            tdStatus.appendChild(pill(st, stCls));
            tr.appendChild(tdTime);
            tr.appendChild(tdTask);
            tr.appendChild(tdModel);
            tr.appendChild(tdDur);
            tr.appendChild(tdStatus);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        execSection.appendChild(table);
    } else {
        var noExec = el('span');
        noExec.textContent = 'No executions yet';
        noExec.style.color = 'var(--archie-muted)';
        execSection.appendChild(noExec);
    }
    drawer.appendChild(execSection);

    // Quick Actions section
    var actSection = el('div', 'drawer-section');
    var actTitle = el('h4');
    actTitle.textContent = 'Quick Actions';
    actSection.appendChild(actTitle);
    var actWrap = el('div', 'drawer-actions');
    var btnAssign = el('button');
    btnAssign.textContent = 'Assign to Station';
    btnAssign.onclick = function(e) { e.stopPropagation(); };
    var btnLounge = el('button');
    btnLounge.textContent = 'Send to Lounge';
    btnLounge.onclick = function(e) { e.stopPropagation(); };
    actWrap.appendChild(btnAssign);
    actWrap.appendChild(btnLounge);
    actSection.appendChild(actWrap);
    drawer.appendChild(actSection);
}
```

**Step 4: Verify template parses**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/team_management.html')
print('OK')
"
```

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/team_management.html
git commit -m "feat(team): expandable agent roster cards with emotional state and execution history"
```

---

### Task 6: Multi-Agent Execution Log Tab

**Files:**
- Modify: `platform_v2/templates/tools/team_management.html` (continue editing)

**Step 1: Add Multi-Agent Log CSS**

Append to the CSS section:

```css
/* === Multi-Agent Log === */
.ma-split{display:flex;gap:16px;height:520px}
.ma-list{flex:0 0 30%;overflow-y:auto;border-right:1px solid var(--archie-border,#2a3a4a);padding-right:12px}
.ma-detail{flex:1;overflow-y:auto;padding-left:12px}
.ma-session{padding:10px;border:1px solid var(--archie-border,#2a3a4a);border-radius:6px;margin-bottom:8px;cursor:pointer;transition:border-color .2s}
.ma-session:hover,.ma-session.selected{border-color:var(--archie-accent,#60a5fa)}
.ma-session .ma-ts{font-size:.75rem;color:var(--archie-muted,#6b7280)}
.ma-session .ma-msg{font-size:.85rem;margin:4px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ma-session .ma-meta{display:flex;gap:8px;align-items:center}
.ma-agent-count{background:var(--archie-accent,#60a5fa);color:#0a1628;border-radius:10px;padding:1px 8px;font-size:.7rem;font-weight:700}
.ma-step{padding:10px;margin-bottom:8px;border-left:3px solid var(--archie-border,#2a3a4a);padding-left:12px}
.ma-step-decompose{border-left-color:#06b6d4}
.ma-step-delegate{border-left-color:#a78bfa}
.ma-step-execute{border-left-color:#60a5fa}
.ma-step-synthesize{border-left-color:#4ade80}
.ma-step-label{font-size:.8rem;font-weight:600;margin-bottom:4px}
.ma-step-data{font-size:.8rem;color:var(--archie-text-secondary,#94a3b8);white-space:pre-wrap;max-height:200px;overflow-y:auto}
.ma-empty{text-align:center;padding:40px;color:var(--archie-muted,#6b7280)}
@media(max-width:768px){.ma-split{flex-direction:column;height:auto}.ma-list{flex:none;max-height:200px;border-right:none;border-bottom:1px solid var(--archie-border,#2a3a4a);padding-right:0;padding-bottom:12px}.ma-detail{padding-left:0}}
```

**Step 2: Add Multi-Agent Log tab button**

After the Performance tab button (line 118), add:

```html
<button class="tm-tab" onclick="tmTab('multiagent',this)" role="tab">Multi-Agent Log</button>
```

**Step 3: Add Multi-Agent Log pane**

After the Performance pane (after `pane-perf` closing `</div>`), add:

```html
<!-- Multi-Agent Log Pane -->
<div class="tm-pane" id="pane-multiagent">
    <div class="ma-split">
        <div class="ma-list" id="ma-session-list"></div>
        <div class="ma-detail" id="ma-session-detail">
            <div class="ma-empty">Select a session to view details</div>
        </div>
    </div>
</div>
```

**Step 4: Update loader dispatch**

In `loadActiveTab()`, add `multiagent: loadMultiAgent` to the loaders map:
```javascript
var loaders = {
    mission: loadMission,
    roster: loadRoster, stations: loadStations, queue: loadQueue,
    hr: loadHR, iaae: loadIAAE, perf: loadPerformance,
    multiagent: loadMultiAgent
};
```

**Step 5: Add the Multi-Agent Log loader functions**

Add near the other loader functions, using safe DOM construction:

```javascript
/* ============ Multi-Agent Log ============ */
var _maPage = 1;

async function loadMultiAgent() {
    var data = await apiFetch('/tools/bridge/api/dispatch/multi-agent-sessions?page=' + _maPage + '&per_page=20');
    var list = document.getElementById('ma-session-list');
    if (!list) return;
    clearEl('ma-session-list');
    if (!data || !data.sessions || data.sessions.length === 0) {
        var empty = el('div', 'ma-empty');
        empty.textContent = 'No multi-agent sessions yet';
        list.appendChild(empty);
        return;
    }
    data.sessions.forEach(function(s) {
        var item = el('div', 'ma-session');
        var ts = el('div', 'ma-ts');
        ts.textContent = timeAgo(s.created_at);
        var msg = el('div', 'ma-msg');
        msg.textContent = (s.user_message || 'No message').substring(0, 60);
        var meta = el('div', 'ma-meta');
        var agentBadge = el('span', 'ma-agent-count');
        agentBadge.textContent = (s.agent_count || 0) + ' agents';
        var st = s.status || 'unknown';
        var stCls = st === 'completed' ? 'tm-pill-green' : st === 'error' ? 'tm-pill-red' : 'tm-pill-amber';
        meta.appendChild(agentBadge);
        meta.appendChild(pill(st, stCls));
        if (s.total_duration_ms) {
            var dur = el('span');
            dur.textContent = fmtMs(s.total_duration_ms);
            dur.style.cssText = 'font-size:.75rem;color:var(--archie-muted)';
            meta.appendChild(dur);
        }
        item.appendChild(ts);
        item.appendChild(msg);
        item.appendChild(meta);
        item.onclick = function() {
            list.querySelectorAll('.ma-session').forEach(function(el){ el.classList.remove('selected'); });
            item.classList.add('selected');
            loadMADetail(s.session_uuid || s.id);
        };
        list.appendChild(item);
    });
}

async function loadMADetail(sessionId) {
    var detail = document.getElementById('ma-session-detail');
    if (!detail) return;
    detail.textContent = '';
    var loadMsg = el('div', 'ma-empty');
    loadMsg.textContent = 'Loading...';
    detail.appendChild(loadMsg);

    var data = await apiFetch('/tools/bridge/api/dispatch/multi-agent-sessions/' + sessionId);
    detail.textContent = '';
    if (!data || !data.session) {
        var errMsg = el('div', 'ma-empty');
        errMsg.textContent = 'Failed to load session';
        detail.appendChild(errMsg);
        return;
    }
    var s = data.session;

    // Original task
    var taskSection = el('div', 'drawer-section');
    var taskTitle = el('h4');
    taskTitle.textContent = 'Original Task';
    taskSection.appendChild(taskTitle);
    var taskBox = el('div');
    taskBox.style.cssText = 'font-size:.9rem;padding:8px;background:var(--archie-bg-secondary,#0c1a2e);border-radius:4px';
    taskBox.textContent = s.user_message || 'No message';
    taskSection.appendChild(taskBox);
    detail.appendChild(taskSection);

    // Steps
    var stepsSection = el('div', 'drawer-section');
    var stepsTitle = el('h4');
    stepsTitle.textContent = 'Pipeline Steps (' + (data.steps || []).length + ')';
    stepsSection.appendChild(stepsTitle);
    (data.steps || []).forEach(function(st) {
        var stepType = st.step_type || 'unknown';
        var cls = 'ma-step';
        if (stepType === 'decompose') cls += ' ma-step-decompose';
        else if (stepType === 'delegate') cls += ' ma-step-delegate';
        else if (stepType === 'execute') cls += ' ma-step-execute';
        else if (stepType === 'synthesize') cls += ' ma-step-synthesize';
        var stepDiv = el('div', cls);

        var labelDiv = el('div', 'ma-step-label');
        var labelText = st.label || stepType;
        if (st.display_name) labelText += ' (' + st.display_name + ')';
        else if (st.codename) labelText += ' (' + st.codename + ')';
        if (st.model_used) labelText += ' via ' + st.model_used;
        if (st.duration_ms) labelText += ' ' + st.duration_ms + 'ms';
        labelDiv.textContent = labelText;
        stepDiv.appendChild(labelDiv);

        if (st.data) {
            var dataDiv = el('div', 'ma-step-data');
            var dataStr = typeof st.data === 'string' ? st.data : JSON.stringify(st.data, null, 2);
            if (dataStr.length > 500) dataStr = dataStr.substring(0, 500) + '...';
            dataDiv.textContent = dataStr;
            stepDiv.appendChild(dataDiv);
        }
        stepsSection.appendChild(stepDiv);
    });
    detail.appendChild(stepsSection);

    // Session meta
    var metaDiv = el('div');
    metaDiv.style.cssText = 'font-size:.75rem;color:var(--archie-muted);margin-top:12px';
    metaDiv.textContent = 'Status: ' + (s.status || '?') + ' | Duration: ' + fmtMs(s.total_duration_ms) + ' | Steps: ' + (s.total_steps || 0);
    detail.appendChild(metaDiv);
}
```

**Step 6: Verify template parses**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/team_management.html')
print('OK')
"
```

**Step 7: Commit**

```bash
git add platform_v2/templates/tools/team_management.html
git commit -m "feat(team): multi-agent execution log tab with session list and step detail"
```

---

### Task 7: Chat Activity Badge

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add badge CSS**

In the `<style>` section, add:

```css
/* Activity badge */
.chat-activity-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:.7rem;cursor:pointer;border:1px solid var(--archie-border,#2a3a4a);background:var(--archie-card-bg,#0a1628)}
.chat-activity-badge:hover{border-color:var(--archie-accent,#60a5fa)}
.cab-dot{width:6px;height:6px;border-radius:50%;background:#6b7280}
.cab-dot.active{background:#4ade80;animation:cabPulse 2s infinite}
@keyframes cabPulse{0%,100%{opacity:1}50%{opacity:.4}}
```

**Step 2: Add badge HTML**

Find the `.status-right` div in the status bar. Add before the last element inside it:

```html
<span class="chat-activity-badge" id="chat-activity-badge" onclick="window.open('/tools/bridge#mission','_blank')" title="Agent activity">
    <span class="cab-dot" id="cab-dot"></span>
    <span id="cab-count">0</span> agents
</span>
```

**Step 3: Add badge poll function**

In the `<script>` section, add:

```javascript
// Activity badge polling
(function(){
    function updateActivityBadge(){
        fetch('/tools/bridge/api/dispatch/fleet-metrics')
            .then(function(r){ return r.json(); })
            .then(function(m){
                var dot = document.getElementById('cab-dot');
                var cnt = document.getElementById('cab-count');
                if(cnt) cnt.textContent = m.active_agents || 0;
                if(dot){
                    if(m.tasks_this_hour > 0) dot.classList.add('active');
                    else dot.classList.remove('active');
                }
            })
            .catch(function(){});
    }
    updateActivityBadge();
    setInterval(updateActivityBadge, 30000);
})();
```

**Step 4: Verify template parses**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
```

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): add agent activity badge in status bar"
```

---

### Task 8: Deploy and Verify

**Step 1: Restart the platform**

```bash
docker compose restart archie_platform
```

Wait 15 seconds, then check logs:

```bash
docker logs --tail 30 archie_platform
```

Expected: No errors, clean startup.

**Step 2: Verify migration ran**

```bash
docker exec -it archie_database psql -U archie -d archie -c "SELECT COUNT(*) FROM agent_activity_events;"
```

Expected: `0` (empty table, no errors).

**Step 3: Verify routes load**

```bash
docker exec archie_platform python3 -c "from tools.bridge.routes import bridge_bp, push_agent_event; print('Routes OK')"
```

**Step 4: Verify templates parse**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
for t in ['tools/team_management.html', 'tools/archie_chat.html']:
    env.get_template(t)
    print(t, 'OK')
"
```

**Step 5: Test fleet-metrics endpoint responds**

```bash
docker exec archie_platform python3 -c "
from tools.bridge.routes import fleet_metrics
print('fleet_metrics endpoint registered OK')
"
```

**Step 6: Push to remote**

```bash
git push origin main
```

**Step 7: Update Dev HQ**

Use MCP tools to:
1. `complete_task` for Phase 6 with notes about all commits
2. `store_memory` to update the roadmap entry
3. `log_decision` for SSE architecture choice

**Step 8: Final verification commit message summary**

Verify with `git log --oneline -8` that all Phase 6 commits are present:
1. Migration 110
2. Backend SSE + APIs
3. Orchestration event hooks
4. Mission Control tab
5. Enhanced roster
6. Multi-Agent log tab
7. Chat activity badge

---

## Important Notes

- **Black pre-commit hook**: Will reformat Python files. If commit fails, re-stage with `git add` and commit again.
- **`orchestration_sessions` columns**: Check actual column names before using. The plan assumes `agent_id`, `user_message`, `status`, `model_used`, `total_duration_ms`, `total_steps`, `session_uuid`, `created_at`, `completed_at`, `metadata`. Verify with `\d orchestration_sessions` in psql.
- **`agent_emotional_state` columns**: Plan assumes `mood`, `stress_level`, `energy_level`, `last_interaction`, `context`, `updated_at`. Verify.
- **`agent_rest_cycles` columns**: Plan assumes `started_at`, `ended_at`, `reason`. Per MEMORY.md, uses `started_at` (NOT `created_at`).
- **DB connection pattern**: Uses `get_db()` which returns a raw psycopg2 connection. Always close in finally/except. The existing codebase has some connection leak patterns — follow the existing style for consistency.
- **SSE cursor approach**: The in-memory deque + counter approach is simple but won't survive restarts. The DB backing store allows page-load history. This is intentional per the design doc.
- **DOM construction**: Uses safe `el()` + `textContent` helpers (no raw HTML injection). Follows existing team_management.html patterns with the `el()`, `pill()`, `clearEl()` helpers.
