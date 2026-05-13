# Dispatch History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "VIEW ALL →" link in Mission Briefing Recent Activity that leads to a new DHQ Dispatch History section with stats bar, filters, paginated unified log (task_execution_log + bridge_jobs), and expandable rows.

**Architecture:** Three new Flask routes in `dispatch_routes.py` serve history data. Frontend is a new LCARS section in `department_hq.html` driven by `dispatch-history.js`. Dashboard gets a single link. No DB migrations.

**Tech Stack:** Flask + psycopg2, vanilla JS + LCARS CSS, pytest + Flask test client.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `platform_v2/templates/dashboard_dynamic.html` | Modify ~line 255 | Add VIEW ALL link |
| `platform_v2/static/css/dashboard.css` | Append | `.briefing-view-all` style |
| `platform_v2/tools/department_hq/dispatch_routes.py` | Append after line 950 | 3 new history endpoints |
| `platform_v2/tools/department_hq/templates/department_hq.html` | Modify after line 282 | Dispatch History section HTML |
| `platform_v2/static/js/dispatch-history.js` | Create | JS fetch/render module |
| `platform_v2/tests/test_dispatch_history_routes.py` | Create | Tests for 3 new routes |

---

## Task 1: Dashboard "VIEW ALL →" Link

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html:253-257`
- Modify: `platform_v2/static/css/dashboard.css`

- [ ] **Step 1: Add link to activity section header**

Open `platform_v2/templates/dashboard_dynamic.html`. Find the `#briefingSectionActivity` header block at line 253. It looks like:

```html
<div class="briefing-section-header" onclick="toggleBriefingSection('activity')">
    <svg class="briefing-section-chevron" ...></svg>
    <span data-i18n="dashboard_activity_title">RECENT ACTIVITY</span>
    <span class="briefing-badge" id="briefingBadgeActivity"></span>
</div>
```

Add the VIEW ALL link before the closing `</div>`:

```html
<div class="briefing-section-header" onclick="toggleBriefingSection('activity')">
    <svg class="briefing-section-chevron" ...></svg>
    <span data-i18n="dashboard_activity_title">RECENT ACTIVITY</span>
    <span class="briefing-badge" id="briefingBadgeActivity"></span>
    <a href="/tools/department-hq#dispatch-history"
       class="briefing-view-all"
       onclick="event.stopPropagation()">VIEW ALL &rarr;</a>
</div>
```

The `stopPropagation()` prevents the click from toggling the accordion.

- [ ] **Step 2: Add CSS**

Append to `platform_v2/static/css/dashboard.css`:

```css
.briefing-view-all {
    margin-left: auto;
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    color: var(--archie-palette-teal-400, #2dd4bf);
    opacity: 0.6;
    text-decoration: none;
    white-space: nowrap;
    transition: opacity 0.2s;
}
.briefing-view-all:hover { opacity: 1; }
```

- [ ] **Step 3: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
```

Navigate to `http://192.168.1.200:3000/dashboard`. Confirm "VIEW ALL →" appears right-aligned in the Recent Activity header and clicking navigates to `/tools/department-hq#dispatch-history` without toggling the accordion.

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/dispatch-history
git add platform_v2/templates/dashboard_dynamic.html platform_v2/static/css/dashboard.css
git commit -m "feat(dashboard): add VIEW ALL link from Recent Activity to dispatch history"
```

---

## Task 2: Schema Check + Dropdown Endpoints

**Files:**
- Create: `platform_v2/tests/test_dispatch_history_routes.py`
- Modify: `platform_v2/tools/department_hq/dispatch_routes.py`

- [ ] **Step 1: Verify bridge_jobs schema**

```bash
docker exec archie_database psql -U archie -d archie -c "\d bridge_jobs"
```

Confirm these columns exist: `agent_name`, `task_type`, `module_id`, `status`, `duration_ms`, `error_message`, `created_at`. If column names differ from the Task 3 SQL, update the SQL accordingly before implementing.

- [ ] **Step 2: Write failing tests**

Create `platform_v2/tests/test_dispatch_history_routes.py`:

```python
import pytest
import json


def test_history_agents_returns_list(admin_client):
    """Agents endpoint returns a JSON array of strings."""
    resp = admin_client.get("/tools/department-hq/api/dispatch/history/agents")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)
    for item in data:
        assert isinstance(item, str) and item


def test_history_capabilities_returns_list(admin_client):
    """Capabilities endpoint returns a JSON array of strings."""
    resp = admin_client.get("/tools/department-hq/api/dispatch/history/capabilities")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)


def test_history_agents_requires_admin(client):
    """Unauthenticated request is redirected or 403."""
    resp = client.get("/tools/department-hq/api/dispatch/history/agents")
    assert resp.status_code in (302, 403)
```

- [ ] **Step 3: Run to confirm failure**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_dispatch_history_routes.py -v 2>&1 | tail -15
```

Expected: 3 FAILED (routes don't exist).

- [ ] **Step 4: Implement dropdown endpoints**

Open `dispatch_routes.py`. After the `dispatch_claude_feed` route (~line 950), add:

```python
@bp.route("/api/dispatch/history/agents", methods=["GET"])
@admin_required_decorator
def dispatch_history_agents():
    """Distinct agent names for the history filter dropdown."""
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT agent_name
                FROM task_execution_log
                WHERE agent_name IS NOT NULL
                  AND created_at > NOW() - INTERVAL '90 days'
                ORDER BY agent_name
                """
            )
            agents = [r["agent_name"] for r in cur.fetchall()]
        return jsonify(agents)
    except Exception:
        logger.exception("dispatch_history_agents failed")
        return jsonify([]), 500


@bp.route("/api/dispatch/history/capabilities", methods=["GET"])
@admin_required_decorator
def dispatch_history_capabilities():
    """Distinct capabilities for the history filter dropdown."""
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT capability
                FROM task_execution_log
                WHERE capability IS NOT NULL
                  AND created_at > NOW() - INTERVAL '90 days'
                ORDER BY capability
                """
            )
            caps = [r["capability"] for r in cur.fetchall()]
        return jsonify(caps)
    except Exception:
        logger.exception("dispatch_history_capabilities failed")
        return jsonify([]), 500
```

- [ ] **Step 5: Restart and run tests**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 5
docker exec archie_platform python3 -m pytest /app/tests/test_dispatch_history_routes.py -k "agents or capabilities" -v 2>&1 | tail -10
```

Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/dispatch_routes.py platform_v2/tests/test_dispatch_history_routes.py
git commit -m "feat(dispatch): add history dropdown endpoints for agents and capabilities"
```

---

## Task 3: Main History Endpoint

**Files:**
- Modify: `platform_v2/tools/department_hq/dispatch_routes.py`
- Modify: `platform_v2/tests/test_dispatch_history_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `test_dispatch_history_routes.py`:

```python
def test_history_default_response_shape(admin_client):
    """Default call returns expected shape."""
    resp = admin_client.get("/tools/department-hq/api/dispatch/history")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "stats" in data and "rows" in data
    assert "total" in data and "page" in data and "pages" in data
    assert isinstance(data["rows"], list)
    assert isinstance(data["stats"]["total_calls"], int)
    assert isinstance(data["stats"]["success_rate"], (int, float))
    assert isinstance(data["stats"]["avg_duration_s"], (int, float))


def test_history_pagination(admin_client):
    """per_page param is respected and pages don't overlap."""
    r1 = admin_client.get("/tools/department-hq/api/dispatch/history?per_page=5&page=1")
    r2 = admin_client.get("/tools/department-hq/api/dispatch/history?per_page=5&page=2")
    d1, d2 = json.loads(r1.data), json.loads(r2.data)
    assert len(d1["rows"]) <= 5
    if d1["total"] > 5:
        ts1 = {r.get("created_at") for r in d1["rows"]}
        ts2 = {r.get("created_at") for r in d2["rows"]}
        assert not ts1.intersection(ts2)


def test_history_source_task_filter(admin_client):
    """source=task returns only task rows."""
    resp = admin_client.get("/tools/department-hq/api/dispatch/history?source=task&per_page=10")
    data = json.loads(resp.data)
    for row in data["rows"]:
        assert row["source"] == "task"


def test_history_agent_filter(admin_client):
    """agent filter returns only rows for that agent."""
    agents_resp = admin_client.get("/tools/department-hq/api/dispatch/history/agents")
    agents = json.loads(agents_resp.data)
    if not agents:
        pytest.skip("No agents in log")
    agent = agents[0]
    resp = admin_client.get(
        f"/tools/department-hq/api/dispatch/history?agent={agent}&per_page=10"
    )
    data = json.loads(resp.data)
    for row in data["rows"]:
        assert row["agent_name"] == agent


def test_history_requires_admin(client):
    """Unauthenticated request rejected."""
    resp = client.get("/tools/department-hq/api/dispatch/history")
    assert resp.status_code in (302, 403)
```

- [ ] **Step 2: Run to confirm failure**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_dispatch_history_routes.py -k "default_response or pagination or source_task or agent_filter or requires_admin" -v 2>&1 | tail -15
```

Expected: All FAILED.

- [ ] **Step 3: Implement the history endpoint**

Add after the dropdown endpoints in `dispatch_routes.py`:

```python
@bp.route("/api/dispatch/history", methods=["GET"])
@admin_required_decorator
def dispatch_history():
    """Paginated unified dispatch log (task_execution_log + bridge_jobs)."""
    from database import get_db_cursor
    from datetime import datetime, timedelta

    agent = request.args.get("agent", "").strip()
    capability = request.args.get("capability", "").strip()
    source = request.args.get("source", "all")
    q = request.args.get("q", "").strip()
    per_page = min(int(request.args.get("per_page", 25)), 100)
    page = max(int(request.args.get("page", 1)), 1)
    offset = (page - 1) * per_page

    now = datetime.utcnow()
    default_from = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    default_to = now.strftime("%Y-%m-%d")
    from_dt = request.args.get("from", default_from) + " 00:00:00"
    to_dt = request.args.get("to", default_to) + " 23:59:59"

    try:
        with get_db_cursor() as (conn, cur):
            # Build WHERE clauses for each source
            def _task_where():
                w = ["tel.created_at BETWEEN %(from_dt)s AND %(to_dt)s"]
                if agent:
                    w.append("tel.agent_name = %(agent)s")
                if capability:
                    w.append("tel.capability = %(capability)s")
                if q:
                    w.append(
                        "(tel.agent_name ILIKE %(q_like)s OR tel.capability ILIKE %(q_like)s"
                        " OR tel.module_source ILIKE %(q_like)s"
                        " OR tel.error_message ILIKE %(q_like)s)"
                    )
                return " AND ".join(w)

            def _job_where():
                w = ["bj.created_at BETWEEN %(from_dt)s AND %(to_dt)s"]
                if agent:
                    w.append("bj.agent_name = %(agent)s")
                if capability:
                    w.append("bj.task_type = %(capability)s")
                if q:
                    w.append(
                        "(bj.agent_name ILIKE %(q_like)s OR bj.task_type ILIKE %(q_like)s"
                        " OR bj.module_id ILIKE %(q_like)s"
                        " OR bj.error_message ILIKE %(q_like)s)"
                    )
                return " AND ".join(w)

            task_cte = f"""
                SELECT 'task'::text AS source, tel.agent_name,
                       tel.capability, tel.module_source AS module,
                       tel.model_used, tel.duration_ms, tel.success,
                       tel.error_message, tel.created_at,
                       tel.tokens_used, tel.cost::float AS cost
                FROM task_execution_log tel
                WHERE {_task_where()}
            """
            job_cte = f"""
                SELECT 'job'::text AS source, bj.agent_name,
                       bj.task_type AS capability, bj.module_id AS module,
                       NULL::text AS model_used, bj.duration_ms,
                       (bj.status = 'completed') AS success,
                       bj.error_message, bj.created_at,
                       NULL::int AS tokens_used, NULL::float AS cost
                FROM bridge_jobs bj
                WHERE {_job_where()}
            """

            if source == "task":
                union_sql = task_cte
            elif source == "job":
                union_sql = job_cte
            else:
                union_sql = f"({task_cte}) UNION ALL ({job_cte})"

            params = {
                "from_dt": from_dt, "to_dt": to_dt,
                "agent": agent or None,
                "capability": capability or None,
                "q_like": f"%{q}%" if q else None,
            }

            # Stats
            cur.execute(
                f"""
                WITH combined AS ({union_sql})
                SELECT
                    COUNT(*)::int AS total_calls,
                    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                          / NULLIF(COUNT(*), 0), 1) AS success_rate,
                    ROUND(AVG(CASE WHEN success THEN duration_ms END) / 1000.0, 1)
                          AS avg_duration_s,
                    MODE() WITHIN GROUP (ORDER BY agent_name) AS top_agent,
                    MODE() WITHIN GROUP (ORDER BY module) AS top_module
                FROM combined
                """,
                params,
            )
            sr = cur.fetchone()
            stats = {
                "total_calls": int(sr["total_calls"] or 0),
                "success_rate": float(sr["success_rate"] or 0),
                "avg_duration_s": float(sr["avg_duration_s"] or 0),
                "top_agent": sr["top_agent"] or "—",
                "top_module": sr["top_module"] or "—",
            }

            # Rows
            cur.execute(
                f"""
                WITH combined AS ({union_sql})
                SELECT * FROM combined
                ORDER BY created_at DESC
                LIMIT %(per_page)s OFFSET %(offset)s
                """,
                {**params, "per_page": per_page, "offset": offset},
            )
            rows = [
                {
                    "source": r["source"],
                    "agent_name": r["agent_name"],
                    "capability": r["capability"],
                    "module": r["module"],
                    "model_used": r["model_used"],
                    "duration_ms": r["duration_ms"],
                    "success": r["success"],
                    "error_message": r["error_message"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "tokens_used": r["tokens_used"],
                    "cost": r["cost"],
                }
                for r in cur.fetchall()
            ]

            total = stats["total_calls"]
            pages = max(1, (total + per_page - 1) // per_page)

        return jsonify({"stats": stats, "rows": rows,
                        "total": total, "page": page, "pages": pages})

    except Exception:
        logger.exception("dispatch_history failed")
        return jsonify({"error": "internal error", "stats": {},
                        "rows": [], "total": 0, "page": 1, "pages": 1}), 500
```

- [ ] **Step 4: Restart and run all tests**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 5
docker exec archie_platform python3 -m pytest /app/tests/test_dispatch_history_routes.py -v 2>&1 | tail -20
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/dispatch_routes.py platform_v2/tests/test_dispatch_history_routes.py
git commit -m "feat(dispatch): add /api/dispatch/history endpoint with stats and pagination"
```

---

## Task 4: HTML Section

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` (insert after line 282)

- [ ] **Step 1: Insert the Dispatch History section**

Open `department_hq.html`. After line 282 (end of `dispatchClaudeContent` div), insert:

```html
<!-- DISPATCH HISTORY -->
<div id="dispatch-history" class="dhq-section" style="margin-top:1.5rem;">
  <div class="lcars-bar" style="background:var(--archie-palette-teal-500,#14b8a6);">DISPATCH HISTORY</div>

  <!-- Stats bar -->
  <div class="dh-stats-bar">
    <div class="dh-stat-card" id="dhStatTotal">
      <div class="dh-stat-value">&#8212;</div>
      <div class="dh-stat-label">Total Calls</div>
    </div>
    <div class="dh-stat-card" id="dhStatSuccess">
      <div class="dh-stat-value">&#8212;</div>
      <div class="dh-stat-label">Success Rate</div>
    </div>
    <div class="dh-stat-card" id="dhStatDuration">
      <div class="dh-stat-value">&#8212;</div>
      <div class="dh-stat-label">Avg Duration</div>
    </div>
    <div class="dh-stat-card" id="dhStatTop">
      <div class="dh-stat-value" id="dhStatTopAgent">&#8212;</div>
      <div class="dh-stat-sub" id="dhStatTopModule">&#8212;</div>
      <div class="dh-stat-label">Top Agent / Module</div>
    </div>
  </div>

  <!-- Filter bar -->
  <div class="dh-filters">
    <select id="dhFilterAgent" class="dh-filter-select" onchange="dhFetch(true)">
      <option value="">All Agents</option>
    </select>
    <select id="dhFilterCapability" class="dh-filter-select" onchange="dhFetch(true)">
      <option value="">All Capabilities</option>
    </select>
    <select id="dhFilterSource" class="dh-filter-select" onchange="dhFetch(true)">
      <option value="all">All Sources</option>
      <option value="task">Tasks only</option>
      <option value="job">Jobs only</option>
    </select>
    <input type="date" id="dhFilterFrom" class="dh-filter-input" onchange="dhFetch(true)">
    <input type="date" id="dhFilterTo"   class="dh-filter-input" onchange="dhFetch(true)">
    <input type="text" id="dhFilterQ"    class="dh-filter-input"
           placeholder="Search&#8230;" oninput="dhDebounce()">
    <button class="sc-btn sc-btn-sm" onclick="dhReset()">RESET</button>
  </div>

  <!-- Table -->
  <div style="overflow-x:auto;">
    <table class="dhq-table dh-history-table" style="width:100%;font-size:0.75rem;">
      <thead>
        <tr>
          <th>Time</th><th>Src</th><th>Agent</th><th>Capability</th>
          <th>Module</th><th>Model</th><th>Duration</th><th>Status</th>
        </tr>
      </thead>
      <tbody id="dhHistoryBody"></tbody>
    </table>
  </div>

  <!-- Pagination -->
  <div class="dh-pagination">
    <button class="sc-btn sc-btn-sm" id="dhPrevBtn" onclick="dhPage(-1)">&#8592; PREV</button>
    <span id="dhPageInfo">Page 1 of 1</span>
    <button class="sc-btn sc-btn-sm" id="dhNextBtn" onclick="dhPage(1)">NEXT &#8594;</button>
    <span style="margin-left:auto;opacity:0.6;">Per page:</span>
    <select id="dhPerPage" class="dh-filter-select" onchange="dhFetch(true)">
      <option value="25">25</option>
      <option value="50">50</option>
      <option value="100">100</option>
    </select>
  </div>
</div>
<!-- END DISPATCH HISTORY -->
```

- [ ] **Step 2: Add CSS**

Find the `<style>` block in `department_hq.html` (or the linked DHQ CSS file). Add:

```css
.dh-stats-bar {
    display: flex; gap: 0.75rem; padding: 0.75rem 0; flex-wrap: wrap;
}
.dh-stat-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(20,184,166,0.2);
    border-radius: 4px; padding: 0.5rem 0.75rem; min-width: 110px; flex: 1;
}
.dh-stat-value { font-size: 1.1rem; font-weight: 700; color: var(--archie-palette-teal-300,#5eead4); }
.dh-stat-sub   { font-size: 0.7rem; opacity: 0.6; }
.dh-stat-label { font-size: 0.6rem; letter-spacing: 0.08em; opacity: 0.5; margin-top: 2px; }
.dh-filters {
    display: flex; gap: 0.5rem; flex-wrap: wrap; padding: 0.5rem 0; align-items: center;
}
.dh-filter-select, .dh-filter-input {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.15);
    color: inherit; border-radius: 3px; padding: 0.25rem 0.4rem; font-size: 0.7rem;
}
.dh-filter-input { min-width: 100px; }
.dh-pagination {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.75rem 0; font-size: 0.75rem;
}
.dh-history-table tr.dh-row:hover { background: rgba(20,184,166,0.06); cursor: pointer; }
.dh-history-table tr.dh-row-expanded { background: rgba(20,184,166,0.04); }
.dh-expand-details { padding: 0.5rem 0.75rem; font-size: 0.7rem; opacity: 0.85; }
.dh-dur-ok  { color: var(--archie-palette-green-400,#4ade80); }
.dh-dur-mid { color: var(--archie-palette-amber-400,#fbbf24); }
.dh-dur-bad { color: var(--archie-palette-red-400,#f87171); }
.dh-badge-task { color: var(--archie-palette-teal-300,#5eead4); }
.dh-badge-job  { color: var(--archie-palette-amber-300,#fcd34d); }
```

- [ ] **Step 3: Restart and verify HTML renders**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Navigate to Dispatch tab, scroll to bottom — confirm section renders with empty `dhHistoryBody`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dispatch-history): HTML section with stats bar, filters, table, pagination"
```

---

## Task 5: dispatch-history.js

**Files:**
- Create: `platform_v2/static/js/dispatch-history.js`
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` (add script tag)

- [ ] **Step 1: Create the JS module**

Create `platform_v2/static/js/dispatch-history.js`. This module uses DOM methods (`createElement`, `textContent`) for all user-derived data — never string concatenation into markup:

```javascript
/* dispatch-history.js — fetch, render, paginate the DHQ Dispatch History section */
(function () {
  'use strict';

  const BASE = '/tools/department-hq/api/dispatch/history';
  let _page = 1;
  let _debounceTimer = null;

  /* ── Public API (called from onclick attrs in the template) ── */

  window.dhFetch = function (resetPage) {
    if (resetPage) _page = 1;
    fetch(BASE + '?' + _params())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _renderStats(data.stats || {});
        _renderTable(data.rows || []);
        _renderPagination(data.page, data.pages, data.total);
      })
      .catch(function (err) { console.error('Dispatch history fetch failed', err); });
  };

  window.dhPage = function (delta) {
    _page = Math.max(1, _page + delta);
    window.dhFetch();
  };

  window.dhReset = function () {
    document.getElementById('dhFilterAgent').value = '';
    document.getElementById('dhFilterCapability').value = '';
    document.getElementById('dhFilterSource').value = 'all';
    document.getElementById('dhFilterQ').value = '';
    var now = new Date();
    document.getElementById('dhFilterTo').value = _fmtDate(now);
    var from = new Date(now);
    from.setDate(from.getDate() - 7);
    document.getElementById('dhFilterFrom').value = _fmtDate(from);
    window.dhFetch(true);
  };

  window.dhDebounce = function () {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(function () { window.dhFetch(true); }, 400);
  };

  window.dhToggleRow = function (idx) {
    var detail = document.getElementById('dh-detail-' + idx);
    var row = document.getElementById('dh-row-' + idx);
    if (!detail || !row) return;
    var hidden = detail.style.display === 'none' || detail.style.display === '';
    detail.style.display = hidden ? 'table-row' : 'none';
    row.classList.toggle('dh-row-expanded', hidden);
  };

  /* ── Init (call once when Dispatch tab first opens) ── */

  window.dhInit = function () {
    if (window._dhInitDone) return;
    window._dhInitDone = true;

    var now = new Date();
    document.getElementById('dhFilterTo').value = _fmtDate(now);
    var from = new Date(now);
    from.setDate(from.getDate() - 7);
    document.getElementById('dhFilterFrom').value = _fmtDate(from);

    // Populate agent dropdown
    fetch(BASE + '/agents')
      .then(function (r) { return r.json(); })
      .then(function (agents) {
        var sel = document.getElementById('dhFilterAgent');
        agents.forEach(function (a) {
          var opt = document.createElement('option');
          opt.value = a;
          opt.textContent = a;   // textContent — safe for user data
          sel.appendChild(opt);
        });
      });

    // Populate capability dropdown
    fetch(BASE + '/capabilities')
      .then(function (r) { return r.json(); })
      .then(function (caps) {
        var sel = document.getElementById('dhFilterCapability');
        caps.forEach(function (c) {
          var opt = document.createElement('option');
          opt.value = c;
          opt.textContent = c;   // textContent — safe for user data
          sel.appendChild(opt);
        });
      });

    window.dhFetch();
  };

  /* ── Private helpers ── */

  function _params() {
    return new URLSearchParams({
      agent:      document.getElementById('dhFilterAgent').value,
      capability: document.getElementById('dhFilterCapability').value,
      source:     document.getElementById('dhFilterSource').value,
      from:       document.getElementById('dhFilterFrom').value,
      to:         document.getElementById('dhFilterTo').value,
      q:          document.getElementById('dhFilterQ').value,
      page:       _page,
      per_page:   document.getElementById('dhPerPage').value,
    }).toString();
  }

  function _renderStats(s) {
    _setVal('dhStatTotal',    '.dh-stat-value', String((s.total_calls || 0).toLocaleString()));
    _setVal('dhStatSuccess',  '.dh-stat-value', ((s.success_rate || 0).toFixed(1)) + '%');
    _setVal('dhStatDuration', '.dh-stat-value', ((s.avg_duration_s || 0).toFixed(1)) + 's');
    var ag = document.getElementById('dhStatTopAgent');
    var mo = document.getElementById('dhStatTopModule');
    if (ag) ag.textContent = s.top_agent || '—';
    if (mo) mo.textContent = s.top_module || '—';
  }

  function _renderTable(rows) {
    var tbody = document.getElementById('dhHistoryBody');
    // Clear safely — no innerHTML
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

    if (!rows.length) {
      var emptyTr = document.createElement('tr');
      var emptyTd = document.createElement('td');
      emptyTd.colSpan = 8;
      emptyTd.style.cssText = 'text-align:center;opacity:0.5;';
      emptyTd.textContent = 'No records found';
      emptyTr.appendChild(emptyTd);
      tbody.appendChild(emptyTr);
      return;
    }

    rows.forEach(function (r, i) {
      /* Data row — all user data via textContent */
      var tr = document.createElement('tr');
      tr.className = 'dh-row';
      tr.id = 'dh-row-' + i;
      tr.setAttribute('onclick', 'dhToggleRow(' + i + ')');

      // Time
      var timeTd = document.createElement('td');
      timeTd.textContent = (r.created_at && typeof ArchieTime !== 'undefined')
        ? ArchieTime.format(r.created_at, 'datetime')
        : (r.created_at || '—');
      tr.appendChild(timeTd);

      // Source badge
      var srcTd = document.createElement('td');
      var srcSpan = document.createElement('span');
      srcSpan.className = r.source === 'task' ? 'dh-badge-task' : 'dh-badge-job';
      srcSpan.textContent = r.source === 'task' ? 'TASK' : 'JOB';
      srcTd.appendChild(srcSpan);
      tr.appendChild(srcTd);

      // Agent, capability, module, model — all textContent
      _appendCell(tr, r.agent_name);
      _appendCell(tr, r.capability);
      _appendCell(tr, r.module);
      _appendCell(tr, r.model_used ? r.model_used.split(':')[0] : '—');

      // Duration (coloured)
      var durTd = document.createElement('td');
      durTd.appendChild(_durNode(r.duration_ms));
      tr.appendChild(durTd);

      // Status
      var statTd = document.createElement('td');
      statTd.textContent = r.success ? '✅' : '❌';
      statTd.style.color = r.success ? '#4ade80' : '#f87171';
      tr.appendChild(statTd);
      tbody.appendChild(tr);

      /* Detail row — expandable, all textContent */
      var detailTr = document.createElement('tr');
      detailTr.className = 'dh-detail-row';
      detailTr.id = 'dh-detail-' + i;
      detailTr.style.display = 'none';
      var detailTd = document.createElement('td');
      detailTd.colSpan = 8;
      var div = document.createElement('div');
      div.className = 'dh-expand-details';

      if (r.error_message) {
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'color:#f87171;margin-bottom:4px;';
        errDiv.textContent = 'Error: ' + r.error_message;  // textContent
        div.appendChild(errDiv);
      }
      var meta = document.createElement('span');
      var cost = typeof r.cost === 'number' ? r.cost.toFixed(4) : '0.0000';
      meta.textContent = 'Tokens: ' + (r.tokens_used || 0)
        + '  |  Cost: $' + cost
        + '  |  Time: ' + (r.created_at || '—');
      div.appendChild(meta);
      detailTd.appendChild(div);
      detailTr.appendChild(detailTd);
      tbody.appendChild(detailTr);
    });
  }

  function _renderPagination(page, pages, total) {
    var info = document.getElementById('dhPageInfo');
    if (info) info.textContent = 'Page ' + page + ' of ' + pages
      + ' (' + (total || 0).toLocaleString() + ' total)';
    var prev = document.getElementById('dhPrevBtn');
    var next = document.getElementById('dhNextBtn');
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= pages;
    _page = page;
  }

  function _appendCell(tr, text) {
    var td = document.createElement('td');
    td.textContent = text || '—';
    tr.appendChild(td);
  }

  function _durNode(ms) {
    var span = document.createElement('span');
    if (!ms) { span.style.opacity = '0.4'; span.textContent = '—'; return span; }
    span.className = ms < 30000 ? 'dh-dur-ok' : ms < 120000 ? 'dh-dur-mid' : 'dh-dur-bad';
    span.textContent = (ms / 1000).toFixed(1) + 's';
    return span;
  }

  function _setVal(parentId, sel, text) {
    var el = document.querySelector('#' + parentId + ' ' + sel);
    if (el) el.textContent = text;
  }

  function _fmtDate(d) {
    return d.toISOString().split('T')[0];
  }
})();
```

- [ ] **Step 2: Add script tag to department_hq.html**

Find the closing `</body>` or script block in `department_hq.html`. Add before `</body>`:

```html
<script src="{{ url_for('static', filename='js/dispatch-history.js') }}"></script>
```

- [ ] **Step 3: Call dhInit when Dispatch tab opens**

Search `department_hq.html` for where tab switching is handled (look for `switchTab` or `data-tab="dispatch"` onclick). Add a `dhInit()` call when the dispatch tab activates. The exact location depends on the template's tab mechanism — find the dispatch tab click handler and add:

```javascript
// Example: if there's a function like activateTab(name):
if (name === 'dispatch') { dhInit(); }

// Or if tabs use onclick attributes, find the dispatch tab button and add:
// onclick="switchTab('dispatch'); dhInit();"
```

If no tab mechanism exists, add to the end of the script block:

```javascript
document.addEventListener('DOMContentLoaded', function () {
  var dispatchTab = document.querySelector('[data-tab="dispatch"]');
  if (dispatchTab) {
    dispatchTab.addEventListener('click', function () { dhInit(); });
  }
});
```

- [ ] **Step 4: Restart and smoke test end-to-end**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

1. `http://192.168.1.200:3000/dashboard` — confirm "VIEW ALL →" appears in Recent Activity header
2. Click "VIEW ALL →" — confirm navigation to Dispatch tab with `#dispatch-history` in URL
3. Scroll to DISPATCH HISTORY — confirm stats cards show numbers
4. Change agent filter — confirm table and stats update
5. Change date range — confirm results change
6. Type in search box — confirm debounced update
7. Click a table row — confirm detail row expands (error, tokens, cost, time)
8. Click Next pagination — confirm page 2 loads different rows
9. Click RESET — confirm filters clear and 7-day default reloads

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/dispatch-history.js platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dispatch-history): JS module with DOM-safe rendering + tab init"
```

---

## Task 6: PR and Merge

- [ ] **Step 1: Run full test suite**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_dispatch_history_routes.py -v 2>&1 | tail -25
```

Expected: All tests PASS.

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin feat/dispatch-history
gh pr create \
  --title "feat(dispatch-history): unified log + stats bar + filters + VIEW ALL link" \
  --body "$(cat <<'EOF'
## Summary
- Adds VIEW ALL link in Mission Briefing Recent Activity pointing to DHQ Dispatch History section
- New DHQ section: stats bar (total calls / success rate / avg duration / top agent+module), filter bar (agent / capability / source / date range / text search), unified paginated table (task_execution_log + bridge_jobs UNION)
- Expandable rows show error message, tokens, cost, timestamp
- 3 new endpoints: /api/dispatch/history, /api/dispatch/history/agents, /api/dispatch/history/capabilities
- All user-derived data rendered via DOM textContent (no innerHTML with user data)

## Test Plan
- [ ] All pytest tests pass
- [ ] VIEW ALL link works from dashboard
- [ ] Filters (agent/capability/source/date/search) update stats and table
- [ ] Pagination prev/next works, per-page selector works
- [ ] Row expand/collapse shows detail
- [ ] Unauthenticated access rejected (302/403)

Closes: spectra_misroute_audit tracking gap (no long-term dispatch history view)

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge via merge-pr skill**

Run `/merge-pr <PR_NUMBER>` — never merge directly.

---

## Notes

- `bridge_jobs` schema verified in Task 2 Step 1 before any SQL is written — update `job_cte` column names if they differ
- `ArchieTime.format()` is globally available via `archie-time.js` (already loaded in DHQ template)
- Alerts History (system_notifications + system_alerts) follows this exact same pattern — file as a follow-up task pointing to this plan as the template
- `MODE() WITHIN GROUP (ORDER BY ...)` is PostgreSQL 9.4+ aggregate — available on the platform DB
