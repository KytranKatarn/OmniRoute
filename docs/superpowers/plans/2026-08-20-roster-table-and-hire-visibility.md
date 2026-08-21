# Roster Table + Hire Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Department HQ Roster's inert card grouping with one configurable table (filter / group / sort / multi-select / bulk shift / CSV), and surface the 15 pending hiring candidates in Roster and K.I.N.

**Architecture:** Backend first, frontend second. Filter predicates are centralised in `agent_service` so the list and the count can never disagree. Sorting is client-side over a complete payload, with a guard that disables it if the payload is ever truncated. Bulk shift is a server-side loop returning per-agent results. Hire visibility is a separate read-only route file feeding one shared renderer mounted twice.

**Tech Stack:** Python 3 / Flask blueprints, psycopg2 (RealDictCursor), `unittest` (352 existing test files under `platform_v2/tests/`), vanilla ES5-style browser JS (globals, no build step), Node v24 for pure-JS unit tests via `.mjs`.

**Spec:**
- A: `docs/superpowers/specs/2026-08-20-roster-table-design.md`
- B: `docs/superpowers/specs/2026-08-20-hire-visibility-design.md`

## Global Constraints

- **All agent mutations go through `services/agent_service.py`.** No direct SQL on agent tables. Enforced by `scripts/check_agent_single_writer.py` (pre-commit).
- **NULL is not zero.** `performance_score`, `success_rate`, `total_tasks_completed` are missing on 17–18 of 140 agents. Render `—`; sort to the END in **both** directions.
- **Decommissioned agents never appear** unless explicitly requested via `?shift_state=decommissioned`.
- **Timestamps**: platform convention is TIMESTAMPTZ + UTC storage, EDT display. `hiring_candidates.proposed_at` must be checked for `timestamp WITHOUT time zone` — compute ages **in SQL**, never Python arithmetic on a naive value (a naive/aware `TypeError` once 500'd the whole K.I.N. tab, KB #283579).
- **`get_db_cursor()` returns RealDictCursor** (dict rows). Use `row['col']`. Never `dict(zip(cur.description, row))`, never int-index a row, never pass `dict_cursor=True` (no such kwarg) — this pattern bug recurred 10+ times (KB #289780).
- **psql verification**: always merge stderr (`2>&1`). An errored query prints nothing and reads exactly like "no rows".
- **Black reformats Python on pre-commit**; trailing-whitespace hook rewrites Markdown. Both abort the first commit — re-`git add` and commit again.
- **Branch**: `feat/roster-table-redesign` (already exists, carries the three specs). Never commit to `main`.
- **Live browser drive is the acceptance gate**, not a green suite (KB #292215). Log in as `claude` — never `kytran`.

---

## File Structure

| file | responsibility |
|---|---|
| `platform_v2/services/agent_service.py` | MODIFY — one shared filter-predicate builder; `list_agents` + new `count_agents` consume it; add `worker_type`; widen `search` |
| `platform_v2/tools/department_hq/roster_routes.py` | MODIFY — use `count_agents` (delete the duplicated count SQL); pass `worker_type`; add `bulk-shift` |
| `platform_v2/tools/department_hq/hiring_routes.py` | CREATE — sub-project B's read-only endpoint. Own file, one responsibility |
| `platform_v2/tools/department_hq/__init__.py` | MODIFY — register hiring routes |
| `platform_v2/tools/department_hq/static/js/roster_sort.js` | CREATE — pure comparator + grouping helpers, browser-global and node-requireable |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | MODIFY — table renderer, selection, CSV; DELETE card/gallery renderers |
| `platform_v2/tools/department_hq/templates/department_hq.html` | MODIFY — control bar; DELETE view switcher |
| `platform_v2/tools/department_hq/static/css/department-hq.css` | MODIFY — table/group/selection styles; DELETE `dhq-crew-*` |
| `platform_v2/tests/test_roster_filters.py` | CREATE — Tasks 1–2 |
| `platform_v2/tests/test_roster_bulk_shift.py` | CREATE — Task 3 |
| `platform_v2/tests/test_hiring_pending.py` | CREATE — Task 4 |
| `platform_v2/tests/test_roster_sort.mjs` | CREATE — Task 7 |

---

### Task 1: One filter-predicate builder, plus `worker_type` and a wider search

**Files:**
- Modify: `platform_v2/services/agent_service.py` (`list_agents`, currently ~line 175)
- Test: `platform_v2/tests/test_roster_filters.py`

**Interfaces:**
- Produces: `_agent_filter_sql(department, floor, shift_state, worker_type, search, is_department_ai, status) -> (where_sql: str, params: list)` — the single definition of roster filtering. `list_agents(...)` gains a `worker_type=None` kwarg.

- [ ] **Step 1: Write the failing test**

```python
"""One filter definition, used by both the list and the count (spec A §8)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent_service import _agent_filter_sql  # noqa: E402


class TestAgentFilterSql(unittest.TestCase):
    def test_worker_type_is_filterable(self):
        where, params = _agent_filter_sql(worker_type="ai")
        self.assertIn("a.worker_type = %s", where)
        self.assertIn("ai", params)

    def test_search_covers_title_acronym_and_department(self):
        where, params = _agent_filter_sql(search="forge")
        for col in ("a.name", "a.display_name", "a.title", "a.acronym", "a.department"):
            self.assertIn(col, where)
        self.assertEqual(params.count("%forge%"), 5)

    def test_status_defaults_to_active(self):
        where, params = _agent_filter_sql()
        self.assertIn("a.status = %s", where)
        self.assertIn("active", params)

    def test_no_filters_still_returns_a_usable_where(self):
        where, _ = _agent_filter_sql(status=None)
        self.assertFalse(where.strip().endswith("AND"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_roster_filters.py -v`
Expected: FAIL — `ImportError: cannot import name '_agent_filter_sql'`

- [ ] **Step 3: Write minimal implementation**

Add above `list_agents` in `services/agent_service.py`:

```python
def _agent_filter_sql(
    department=None,
    floor=None,
    shift_state=None,
    worker_type=None,
    search=None,
    is_department_ai=None,
    status="active",
):
    """Build the roster WHERE clause ONCE.

    The list and the count MUST agree. They used to be written twice — once
    here and once by hand in roster_routes for a COUNT(*) — so a filter added
    to one silently skipped the other (spec A §8).
    """
    conditions, params = [], []
    if status is not None:
        conditions.append("a.status = %s")
        params.append(status)
    if department:
        conditions.append("a.department = %s")
        params.append(department)
    if floor:
        conditions.append("a.floor = %s")
        params.append(floor)
    if shift_state:
        conditions.append("a.shift_state = %s")
        params.append(shift_state)
    else:
        conditions.append("a.shift_state <> 'decommissioned'")
    if worker_type:
        conditions.append("a.worker_type = %s")
        params.append(worker_type)
    if is_department_ai is not None:
        conditions.append("a.is_department_ai = %s")
        params.append(is_department_ai)
    if search:
        conditions.append(
            "(a.name ILIKE %s OR a.display_name ILIKE %s OR a.title ILIKE %s "
            "OR a.acronym ILIKE %s OR a.department ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 5)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where, params
```

Then rewrite `list_agents` to use it, adding the `worker_type=None` kwarg and keeping its existing `ORDER BY a.floor, a.department, a.is_department_ai DESC, a.name` and `LIMIT %s`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_roster_filters.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_service.py platform_v2/tests/test_roster_filters.py
git commit -m "feat(roster): single filter predicate + worker_type + wider search [A]"
```

---

### Task 2: `count_agents` shares the predicate; delete the duplicated count SQL

**Files:**
- Modify: `platform_v2/services/agent_service.py` (add `count_agents`)
- Modify: `platform_v2/tools/department_hq/roster_routes.py:70-180` (the `api_roster` handler)
- Test: `platform_v2/tests/test_roster_filters.py` (append)

**Interfaces:**
- Consumes: `_agent_filter_sql` (Task 1)
- Produces: `count_agents(**same_kwargs) -> int`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roster_filters.py`:

```python
class TestCountSharesThePredicate(unittest.TestCase):
    def test_count_agents_uses_the_same_builder(self):
        import inspect

        from services import agent_service

        src = inspect.getsource(agent_service.count_agents)
        self.assertIn("_agent_filter_sql", src)

    def test_roster_route_no_longer_hand_builds_a_count(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "tools/department_hq/roster_routes.py"
        text = src.read_text()
        self.assertNotIn("count_conditions", text)
        self.assertIn("count_agents", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_roster_filters.py -v -k Count`
Expected: FAIL — `AttributeError: module 'services.agent_service' has no attribute 'count_agents'`

- [ ] **Step 3: Write minimal implementation**

In `agent_service.py`:

```python
def count_agents(**kwargs):
    """Total matching the SAME predicate list_agents uses."""
    where, params = _agent_filter_sql(**kwargs)
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) AS total FROM agents a {where}", params)
        row = cur.fetchone()
        return row["total"] if row else 0
```

In `roster_routes.py::api_roster`: delete the whole `count_conditions` / `count_params` block (~lines 98–125) and the Python-side decommissioned filter, then:

```python
filters = dict(
    department=request.args.get("department"),
    floor=request.args.get("floor"),
    shift_state=request.args.get("shift_state"),
    worker_type=request.args.get("worker_type"),
    search=request.args.get("search", "").strip() or None,
)
all_agents = list_agents(limit=limit + offset, **filters)
total = count_agents(**filters)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_roster_filters.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Verify live through the running process**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.agent_service import list_agents, count_agents
for wt in ('ai','internal','contractor'):
    print(wt, len(list_agents(worker_type=wt, limit=500)), count_agents(worker_type=wt))"
```
Expected: `ai 116 116` / `internal 23 23` / `contractor 1 1` — list and count agree.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_service.py platform_v2/tools/department_hq/roster_routes.py platform_v2/tests/test_roster_filters.py
git commit -m "fix(roster): count and list share one predicate [A]"
```

---

### Task 3: `POST /api/roster/bulk-shift` with per-agent results

**Files:**
- Modify: `platform_v2/tools/department_hq/roster_routes.py` (add after `api_roster_shift`, ~line 246)
- Test: `platform_v2/tests/test_roster_bulk_shift.py`

**Interfaces:**
- Produces: `POST /tools/department-hq/api/roster/bulk-shift` → `{success, results:[{agent_id,name,ok,previous?,error?}], ok_count, failed_count}`

- [ ] **Step 1: Write the failing test**

```python
"""A batch over N targets is N decisions — each one reports its own outcome."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.department_hq import roster_routes  # noqa: E402


class TestBulkShiftResults(unittest.TestCase):
    def test_partial_failure_is_visible_per_agent(self):
        def fake_update(agent_id, **fields):
            if agent_id == 2:
                raise ValueError("boom")

        agents = {1: {"name": "A.L.P.H.A.", "shift_state": "active"},
                  2: {"name": "B.E.T.A.", "shift_state": "active"}}
        with patch.object(roster_routes, "update_agent", side_effect=fake_update), \
             patch.object(roster_routes, "get_agent", side_effect=lambda i: agents.get(i)):
            out = roster_routes._apply_bulk_shift([1, 2], "barracked")

        self.assertEqual(out["ok_count"], 1)
        self.assertEqual(out["failed_count"], 1)
        byid = {r["agent_id"]: r for r in out["results"]}
        self.assertTrue(byid[1]["ok"])
        self.assertEqual(byid[1]["previous"], "active")
        self.assertFalse(byid[2]["ok"])
        self.assertIn("boom", byid[2]["error"])

    def test_a_failure_does_not_abort_the_rest(self):
        """The failing agent is FIRST — later agents must still be attempted."""
        def fake_update(agent_id, **fields):
            if agent_id == 1:
                raise ValueError("boom")

        agents = {1: {"name": "A", "shift_state": "active"},
                  2: {"name": "B", "shift_state": "active"}}
        with patch.object(roster_routes, "update_agent", side_effect=fake_update), \
             patch.object(roster_routes, "get_agent", side_effect=lambda i: agents.get(i)):
            out = roster_routes._apply_bulk_shift([1, 2], "barracked")
        self.assertEqual(out["ok_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_roster_bulk_shift.py -v`
Expected: FAIL — `AttributeError: module has no attribute '_apply_bulk_shift'`

- [ ] **Step 3: Write minimal implementation**

Module-level in `roster_routes.py` (outside `register_roster_routes` so it is testable):

```python
def _apply_bulk_shift(agent_ids, shift_state):
    """Apply a shift change to N agents, reporting EACH outcome.

    An aggregate-only count is what makes a half-applied batch read as a
    success. One agent's failure never aborts the others.
    """
    results = []
    for agent_id in agent_ids:
        try:
            agent = get_agent(agent_id)
            if not agent:
                results.append({"agent_id": agent_id, "name": None, "ok": False,
                                "error": "Agent not found"})
                continue
            previous = agent["shift_state"]
            update_agent(agent_id, shift_state=shift_state)
            results.append({"agent_id": agent_id, "name": agent["name"],
                            "ok": True, "previous": previous})
        except Exception as e:
            results.append({"agent_id": agent_id, "name": None, "ok": False,
                            "error": str(e)})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "failed_count": len(results) - ok}
```

And the route inside `register_roster_routes`:

```python
    @bp.route("/api/roster/bulk-shift", methods=["POST"])
    @admin_required
    def api_roster_bulk_shift():
        data = request.get_json(silent=True) or {}
        agent_ids = data.get("agent_ids") or []
        shift_state = data.get("shift_state")
        if not agent_ids or not shift_state:
            return jsonify({"error": "agent_ids and shift_state are required"}), 400
        if shift_state not in VALID_SHIFT_STATES:
            return jsonify({"error": f"Invalid shift_state: {shift_state}"}), 400
        if len(agent_ids) > 100:
            return jsonify({"error": "Refusing a batch over 100 agents"}), 400
        out = _apply_bulk_shift(agent_ids, shift_state)
        out["success"] = True
        return jsonify(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_roster_bulk_shift.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/roster_routes.py platform_v2/tests/test_roster_bulk_shift.py
git commit -m "feat(roster): bulk-shift endpoint with per-agent results [A]"
```

---

### Task 4: `GET /api/hiring/pending` (sub-project B backend)

**Files:**
- Create: `platform_v2/tools/department_hq/hiring_routes.py`
- Modify: `platform_v2/tools/department_hq/__init__.py`
- Test: `platform_v2/tests/test_hiring_pending.py`

**Interfaces:**
- Produces: `GET /tools/department-hq/api/hiring/pending` → `{candidates:[{id,capability,gap_reason,precheck_status,precheck_message,proposed_at,age_hours}], count:int}`; and `register_hiring_routes(bp, admin_required)`

- [ ] **Step 1: Write the failing test**

```python
"""Pending hires must be visible, and the age must be computed in SQL."""
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.department_hq import hiring_routes  # noqa: E402


class TestHiringPending(unittest.TestCase):
    def test_only_pending_is_selected(self):
        sql = hiring_routes.PENDING_SQL
        self.assertIn("status = 'pending'", sql)

    def test_age_is_computed_in_sql_not_python(self):
        """proposed_at may be naive; Python arithmetic on it raises TypeError."""
        self.assertIn("EXTRACT(EPOCH", hiring_routes.PENDING_SQL)
        src = inspect.getsource(hiring_routes)
        self.assertNotIn("now_utc() -", src)

    def test_uses_proposed_at_not_created_at(self):
        """hiring_candidates has NO created_at column."""
        self.assertIn("proposed_at", hiring_routes.PENDING_SQL)
        self.assertNotIn("created_at", hiring_routes.PENDING_SQL)

    def test_query_is_bounded(self):
        self.assertIn("LIMIT", hiring_routes.PENDING_SQL)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_hiring_pending.py -v`
Expected: FAIL — `ModuleNotFoundError: tools.department_hq.hiring_routes`

- [ ] **Step 3: Write minimal implementation**

Create `platform_v2/tools/department_hq/hiring_routes.py`:

```python
"""Read-only visibility for pending hiring candidates (spec B).

These live in `hiring_candidates`, NOT `autonomy_approval_queue` — looking for
them in the approvals queue returns nothing and reads as "no pending hires".
"""

from flask import jsonify

from database import get_db_cursor

PENDING_SQL = """
    SELECT id, capability, gap_reason, precheck_status, precheck_message,
           proposed_at,
           ROUND(EXTRACT(EPOCH FROM (now() - proposed_at)) / 3600.0)::int AS age_hours
      FROM hiring_candidates
     WHERE status = 'pending'
     ORDER BY proposed_at DESC
     LIMIT 50
"""

COUNT_SQL = "SELECT COUNT(*) AS n FROM hiring_candidates WHERE status = 'pending'"


def register_hiring_routes(bp, admin_required):
    @bp.route("/api/hiring/pending")
    @admin_required
    def api_hiring_pending():
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(PENDING_SQL)
                rows = [dict(r) for r in cur.fetchall()]
                cur.execute(COUNT_SQL)
                total = cur.fetchone()["n"]
            for r in rows:
                r["proposed_at"] = r["proposed_at"].isoformat() if r["proposed_at"] else None
            return jsonify({"candidates": rows, "count": total})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

In `__init__.py`, beside the other `register_*_routes` calls:

```python
from .hiring_routes import register_hiring_routes
register_hiring_routes(department_hq_bp, admin_required)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_hiring_pending.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify against real data**

```bash
docker exec -i archie_database psql -U archie -d archie 2>&1 -c \
  "SELECT count(*) FROM hiring_candidates WHERE status='pending';"
```
Expected: `15` — must match the endpoint's `count`.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/hiring_routes.py platform_v2/tools/department_hq/__init__.py platform_v2/tests/test_hiring_pending.py
git commit -m "feat(hiring): read-only pending-candidates endpoint [B]"
```

---

### Task 5: Pure sort + grouping module, with the NULL rule under test

**Files:**
- Create: `platform_v2/tools/department_hq/static/js/roster_sort.js`
- Test: `platform_v2/tests/test_roster_sort.mjs`

**Interfaces:**
- Produces (browser globals + node-loadable): `compareAgents(a, b, key, dir)`, `sortAgents(list, key, dir)`, `groupAgents(list, groupKey)`

- [ ] **Step 1: Write the failing test**

```javascript
// NULL is not zero. An unscored agent must never rank as the worst performer.
import { readFileSync } from 'node:fs';
import { strict as assert } from 'node:assert';
import test from 'node:test';

const src = readFileSync(
  new URL('../tools/department_hq/static/js/roster_sort.js', import.meta.url), 'utf8');
const { sortAgents, groupAgents } =
  new Function(src + '; return { sortAgents, groupAgents };')();

const AGENTS = [
  { id: 1, name: 'A', performance_score: 0.9, department: 'Eng' },
  { id: 2, name: 'B', performance_score: null, department: 'Eng' },
  { id: 3, name: 'C', performance_score: 0.2, department: 'Ops' },
];

test('nulls sort last ascending', () => {
  const ids = sortAgents(AGENTS, 'performance_score', 'asc').map(a => a.id);
  assert.deepEqual(ids, [3, 1, 2]);
});

test('nulls sort last DESCENDING too', () => {
  const ids = sortAgents(AGENTS, 'performance_score', 'desc').map(a => a.id);
  assert.deepEqual(ids, [1, 3, 2]);
});

test('null is not treated as zero', () => {
  const ids = sortAgents(AGENTS, 'performance_score', 'asc').map(a => a.id);
  assert.notEqual(ids[0], 2, 'unscored agent ranked as worst — NULL coerced to 0');
});

test('grouping keeps every agent exactly once', () => {
  const groups = groupAgents(AGENTS, 'department');
  const total = Object.values(groups).reduce((n, g) => n + g.length, 0);
  assert.equal(total, AGENTS.length);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/archie_brain/platform_v2 && node --test tests/test_roster_sort.mjs`
Expected: FAIL — cannot read `roster_sort.js` (ENOENT)

- [ ] **Step 3: Write minimal implementation**

```javascript
/* Roster sorting + grouping. Pure functions, no DOM — unit-tested in
   tests/test_roster_sort.mjs. Loaded as a plain script (globals). */

function compareAgents(a, b, key, dir) {
    var av = a[key], bv = b[key];
    var aNull = (av === null || av === undefined || av === '');
    var bNull = (bv === null || bv === undefined || bv === '');
    // NULLs always last, in BOTH directions. Never coerce to 0: an unscored
    // agent would render as the worst performer in the fleet.
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    var cmp;
    if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
    else cmp = String(av).localeCompare(String(bv));
    return dir === 'desc' ? -cmp : cmp;
}

function sortAgents(list, key, dir) {
    return list.slice().sort(function (a, b) { return compareAgents(a, b, key, dir); });
}

function groupAgents(list, groupKey) {
    var groups = {};
    list.forEach(function (a) {
        var k = a[groupKey] || '—';
        (groups[k] = groups[k] || []).push(a);
    });
    return groups;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/archie_brain/platform_v2 && node --test tests/test_roster_sort.mjs`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/roster_sort.js platform_v2/tests/test_roster_sort.mjs
git commit -m "feat(roster): pure sort/group module, NULLs last both directions [A]"
```

---

### Task 6: Control bar markup; delete the view switcher

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:86-113`

**Interfaces:**
- Consumes: nothing
- Produces: DOM ids `rosterSearch`, `rosterDept`, `rosterType`, `rosterFloor`, `rosterShift`, `rosterGroupBy`, `rosterCount`, `rosterBulkBar`, `rosterSelCount`, `rosterBulkShift`, `rosterExportCsv`, `rosterContent`

- [ ] **Step 1: Replace the control bar**

Replace the block containing `rosterSearch` / `rosterFloor` / `rosterShift` and **delete all three `.dhq-view-btn` buttons** (lines ~104–106). Keep the `data-rosterview` LIST/ORG CHART buttons untouched — different axis.

```html
<input type="text" id="rosterSearch" class="dhq-input" placeholder="Search name, role, acronym, department…" oninput="debounceRoster()">
<select id="rosterDept" class="dhq-select" onchange="loadRoster()"><option value="">All Departments</option></select>
<select id="rosterType" class="dhq-select" onchange="loadRoster()">
  <option value="">All Types</option><option value="ai">AI</option>
  <option value="internal">Human-like</option><option value="contractor">Contractor</option>
</select>
<select id="rosterFloor" class="dhq-select" onchange="loadRoster()"><option value="">All Floors</option></select>
<select id="rosterShift" class="dhq-select" onchange="loadRoster()"><option value="">All Shifts</option></select>
<select id="rosterGroupBy" class="dhq-select" onchange="renderRoster(lastRosterData)">
  <option value="department" selected>Group: Department</option>
  <option value="floor">Group: Floor</option>
  <option value="shift_state">Group: Shift</option>
  <option value="worker_type">Group: Type</option>
  <option value="">No grouping</option>
</select>
<span class="dhq-roster-count" id="rosterCount"></span>
<div id="rosterBulkBar" class="dhq-bulk-bar" style="display:none">
  <span id="rosterSelCount"></span>
  <select id="rosterBulkShift" class="dhq-select"><option value="">Set shift…</option></select>
  <button class="dhq-btn" onclick="applyBulkShift()">Apply</button>
  <button class="dhq-btn" onclick="exportRosterCsv()" id="rosterExportCsv">Export CSV</button>
</div>
```

- [ ] **Step 2: Add the script tag for the sort module**

Beside the existing `department-hq.js` include, **before** it:

```html
<script src="{{ url_for('department_hq.static', filename='js/roster_sort.js') }}"></script>
```

- [ ] **Step 3: Verify the template renders**

```bash
docker compose restart archie_platform && sleep 5
docker logs --tail 20 archie_platform 2>&1 | grep -i "error\|traceback" || echo "clean start"
```
Expected: `clean start`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(roster): control bar with dept/type/group-by; drop view switcher [A]"
```

---

### Task 7: Table renderer with grouping; delete card + gallery renderers

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js` (`loadRoster` ~382, `renderRoster` ~411, `renderRosterGallery` ~422, `renderRosterTable` ~510, `SHIFT_GROUPS` ~534, `renderRosterCards` ~540, `setRosterView` ~360)

**Interfaces:**
- Consumes: `sortAgents`, `groupAgents` (Task 5); `/api/roster` with `worker_type` (Task 2)
- Produces: `renderRoster(data)`, `rosterSortKey`, `rosterSortDir`, `sortRosterBy(key)`, `rosterSelection` (a `Set` of agent ids)

- [ ] **Step 1: Delete the dead renderers**

Delete `setRosterView`, `renderRosterCards`, `renderRosterGallery`, `SHIFT_GROUPS`, and the `rosterView` variable. Verified in the spec (§10) to have no consumer outside this module.

- [ ] **Step 2: Send the new filters**

In `loadRoster`, replace the params block:

```javascript
var params = new URLSearchParams();
['rosterSearch','rosterDept','rosterType','rosterFloor','rosterShift'].forEach(function(id){
    var v = (document.getElementById(id) || {}).value;
    if (v) params.set({rosterSearch:'search', rosterDept:'department', rosterType:'worker_type',
                       rosterFloor:'floor', rosterShift:'shift_state'}[id], v);
});
```

- [ ] **Step 3: Write the table renderer**

```javascript
var rosterSortKey = 'name', rosterSortDir = 'asc';
var rosterSelection = new Set();

var ROSTER_COLS = [
    {key:'display_name',          label:'Agent'},
    {key:'department',            label:'Dept'},
    {key:'floor',                 label:'Floor'},
    {key:'shift_state',           label:'Shift'},
    {key:'title',                 label:'Role'},
    {key:'worker_type',           label:'Type'},
    {key:'performance_score',     label:'Perf'},
    {key:'success_rate',          label:'Success'},
    {key:'total_tasks_completed', label:'Tasks'}
];

function fmtCell(v) {
    // NULL renders as an em dash. Never 0, never blank — see spec A §5.1.
    return (v === null || v === undefined || v === '') ? '—' : String(v);
}

function sortRosterBy(key) {
    if (rosterSortKey === key) rosterSortDir = (rosterSortDir === 'asc' ? 'desc' : 'asc');
    else { rosterSortKey = key; rosterSortDir = 'asc'; }
    renderRoster(lastRosterData);
}

function renderRoster(data) {
    var el = document.getElementById('rosterContent');
    if (!data) return;
    var truncated = data.total > data.agents.length;
    var groupKey = (document.getElementById('rosterGroupBy') || {}).value || '';
    var rows = truncated ? data.agents : sortAgents(data.agents, rosterSortKey, rosterSortDir);

    var head = '<tr><th></th>' + ROSTER_COLS.map(function(c){
        var arrow = (c.key === rosterSortKey && !truncated) ? (rosterSortDir === 'asc' ? ' ▲' : ' ▼') : '';
        return truncated
            ? '<th>' + esc(c.label) + '</th>'
            : '<th class="dhq-sortable" onclick="sortRosterBy(\'' + c.key + '\')">' + esc(c.label) + arrow + '</th>';
    }).join('') + '</tr>';

    function agentCell(a) {
        // Avatar thumb + name + acronym (spec A §5). 131/140 have an avatar;
        // the rest fall back to initials, same pattern the old card used.
        var initials = (a.display_name || a.name || '?').split(' ')
            .map(function(w){ return w[0]; }).join('').substring(0, 2).toUpperCase();
        var av = a.avatar_url
            ? '<img class="dhq-row-av" src="' + esc(bust(a.avatar_url, a.avatar_updated_at))
              + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">'
            : '<span class="dhq-row-av dhq-row-av-fallback">' + esc(initials) + '</span>';
        var acr = a.acronym ? ' <span class="dhq-acr">' + esc(a.acronym) + '</span>' : '';
        return '<td>' + av + esc(a.display_name || a.name || '—') + acr + '</td>';
    }

    function bodyFor(list) {
        return list.map(function(a){
            return '<tr><td><input type="checkbox" class="dhq-row-sel" data-id="' + a.id + '"'
                 + (rosterSelection.has(a.id) ? ' checked' : '') + ' onchange="toggleRosterSel(' + a.id + ',this.checked)"></td>'
                 + ROSTER_COLS.map(function(c){
                       if (c.key === 'display_name') return agentCell(a);
                       return '<td>' + esc(fmtCell(a[c.key])) + '</td>';
                   }).join('') + '</tr>';
        }).join('');
    }

    var body;
    if (groupKey) {
        var groups = groupAgents(rows, groupKey);
        body = Object.keys(groups).sort().map(function(k){
            return '<tr class="dhq-group-row"><td colspan="' + (ROSTER_COLS.length + 1) + '">'
                 + esc(k) + ' (' + groups[k].length + ')</td></tr>' + bodyFor(groups[k]);
        }).join('');
    } else {
        body = bodyFor(rows);
    }

    var notice = truncated
        ? '<div class="dhq-warn">Showing ' + data.agents.length + ' of ' + data.total
          + ' — sorting disabled on a partial list. Narrow the filters.</div>' : '';
    setHtml(el, notice + '<table class="dhq-roster-table"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>');
}
```

- [ ] **Step 4: Verify in the browser**

Restart, log in as `claude`, open the Roster tab, and check the group headers show department names with counts. Expected: `Engineering & Technology (53)` as the largest group.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(roster): grouped sortable table; remove card/gallery renderers [A]"
```

---

### Task 8: Selection, bulk shift confirm, CSV export

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

**Interfaces:**
- Consumes: `rosterSelection` (Task 7), `POST /api/roster/bulk-shift` (Task 3)
- Produces: `toggleRosterSel(id, on)`, `applyBulkShift()`, `exportRosterCsv()`

- [ ] **Step 1: Implement selection + bulk apply**

```javascript
function toggleRosterSel(id, on) {
    if (on) rosterSelection.add(id); else rosterSelection.delete(id);
    var bar = document.getElementById('rosterBulkBar');
    document.getElementById('rosterSelCount').textContent = rosterSelection.size + ' selected';
    bar.style.display = rosterSelection.size ? 'flex' : 'none';
}

async function applyBulkShift() {
    var state = document.getElementById('rosterBulkShift').value;
    if (!state || !rosterSelection.size) return;
    var ids = Array.from(rosterSelection);
    var all = (lastRosterData && lastRosterData.agents) || [];
    var chosen = all.filter(function(a){ return rosterSelection.has(a.id); });
    var directors = chosen.filter(function(a){ return a.is_department_ai; });

    // A batch over N targets is N decisions — name the count, the transition,
    // and anything unusual in the selection before acting.
    var msg = 'Change shift for ' + ids.length + ' agent(s) to "' + state + '".';
    if (directors.length) msg += '\n\n⚠ ' + directors.length + ' of them are department directors.';
    if (!confirm(msg)) return;

    var res = await apiPost('/api/roster/bulk-shift', {agent_ids: ids, shift_state: state});
    var failed = (res.results || []).filter(function(r){ return !r.ok; });
    alert('Applied: ' + res.ok_count + ' ok, ' + res.failed_count + ' failed'
          + (failed.length ? '\n\n' + failed.map(function(f){
                return '#' + f.agent_id + ': ' + f.error; }).join('\n') : ''));
    rosterSelection.clear();
    toggleRosterSel(null, false);
    loadRoster();
}
```

- [ ] **Step 2: Implement CSV export**

```javascript
function exportRosterCsv() {
    var groupKey = (document.getElementById('rosterGroupBy') || {}).value || '';
    var rows = sortAgents((lastRosterData && lastRosterData.agents) || [], rosterSortKey, rosterSortDir);
    if (groupKey) {
        var g = groupAgents(rows, groupKey);
        rows = Object.keys(g).sort().reduce(function(acc, k){ return acc.concat(g[k]); }, []);
    }
    var q = function(v){ return '"' + String(v === null || v === undefined ? '' : v).replace(/"/g, '""') + '"'; };
    var csv = [ROSTER_COLS.map(function(c){ return q(c.label); }).join(',')]
        .concat(rows.map(function(a){
            return ROSTER_COLS.map(function(c){ return q(a[c.key]); }).join(',');
        })).join('\n');
    var url = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
    var link = document.createElement('a');
    link.href = url; link.download = 'roster.csv';
    document.body.appendChild(link); link.click();
    document.body.removeChild(link); URL.revokeObjectURL(url);
}
```

Note: missing values export as empty, matching the `—` rendering rule.

- [ ] **Step 3: Verify in the browser**

Select 2 agents, confirm the bar appears with the count, cancel the confirm dialog and verify **nothing changed** in the DB, then export CSV and confirm the row count and order match the visible table.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(roster): selection, bulk shift with confirm, CSV export [A]"
```

---

### Task 9: Populate the filter dropdowns; shift options carry live counts

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

**Interfaces:**
- Consumes: `/api/roster` payload
- Produces: `populateRosterFilters(agents)`

- [ ] **Step 1: Implement**

```javascript
var ALL_SHIFT_STATES = ['active','deployed','barracked','off_duty','winding_down','cooldown'];

function populateRosterFilters(agents) {
    var counts = {};
    agents.forEach(function(a){ counts[a.shift_state] = (counts[a.shift_state] || 0) + 1; });

    // Every valid state is listed WITH its count. A zero-count option that is
    // visible is honest; a removed one is indistinguishable from a state that
    // does not exist (spec A §6).
    var shift = document.getElementById('rosterShift');
    var keep = shift.value;
    shift.innerHTML = '<option value="">All Shifts</option>';
    ALL_SHIFT_STATES.forEach(function(s){
        var o = document.createElement('option');
        o.value = s; o.textContent = s + ' (' + (counts[s] || 0) + ')';
        shift.appendChild(o);
    });
    shift.value = keep;

    var depts = Array.from(new Set(agents.map(function(a){ return a.department; }).filter(Boolean))).sort();
    var dsel = document.getElementById('rosterDept'), dkeep = dsel.value;
    dsel.innerHTML = '<option value="">All Departments</option>';
    depts.forEach(function(d){
        var o = document.createElement('option');
        o.value = d; o.textContent = d;
        dsel.appendChild(o);
    });
    dsel.value = dkeep;

    var bulk = document.getElementById('rosterBulkShift');
    if (bulk && bulk.options.length <= 1) {
        ALL_SHIFT_STATES.forEach(function(s){
            var o = document.createElement('option'); o.value = s; o.textContent = s;
            bulk.appendChild(o);
        });
    }
}
```

⚠️ Populate from an **unfiltered** fetch on first load, or filtering to one department empties the department list and traps the user. Call `populateRosterFilters` only when no filters are active, or cache the first full payload.

- [ ] **Step 2: Verify in the browser**

Expected on load: shift options read `active (135)`, `off_duty (4)`, `winding_down (1)`, and `deployed (0)`, `barracked (0)`, `cooldown (0)` — visible, not hidden.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(roster): data-driven filter options with live counts [A]"
```

---

### Task 10: CSS — table, groups, selection; delete `dhq-crew-*`

**Files:**
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css:1240-1330` (delete `dhq-crew-*`), append new rules

- [ ] **Step 1: Delete the card CSS**

Remove the `.dhq-crew-group*`, `.dhq-crew-card*`, `.dhq-crew-avatar*` rules (~1240–1330). Verified in spec A §10 to have no other consumer.

- [ ] **Step 2: Add table styles**

```css
.dhq-roster-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.dhq-roster-table th { text-align: left; padding: 8px; border-bottom: 2px solid var(--archie-border); white-space: nowrap; }
.dhq-roster-table td { padding: 6px 8px; border-bottom: 1px solid var(--archie-border); }
.dhq-sortable { cursor: pointer; user-select: none; }
.dhq-sortable:hover { color: var(--archie-accent); }
.dhq-group-row td { background: var(--archie-surface-2); font-weight: 600; letter-spacing: .04em; }
.dhq-bulk-bar { display: flex; gap: 8px; align-items: center; padding: 8px; }
.dhq-warn { padding: 8px; border-left: 3px solid #f59e0b; margin-bottom: 8px; }
.dhq-row-av { width: 22px; height: 22px; border-radius: 50%; vertical-align: middle; margin-right: 6px; object-fit: cover; }
.dhq-row-av-fallback { display: inline-flex; align-items: center; justify-content: center; font-size: 10px; background: var(--archie-surface-2); }
.dhq-acr { opacity: .6; font-size: 11px; margin-left: 4px; }
.dhq-hiring-strip { padding: 10px; border-left: 3px solid #f59e0b; margin-bottom: 10px; }
.dhq-hiring-empty { opacity: .5; border-left-color: var(--archie-border); }
.dhq-precheck, .dhq-age { opacity: .6; font-size: 11px; margin-left: 6px; }
```

Use existing `--archie-*` tokens only — they resolve in light mode via `light-mode.css` (a private namespace would not; see `lightmode-audit-status.md`).

- [ ] **Step 3: Verify BOTH themes**

Load the Roster in dark and light mode. Expected: readable in both, no hardcoded dark backgrounds.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/css/department-hq.css
git commit -m "style(roster): table/group/selection CSS; remove dhq-crew-* [A]"
```

---

### Task 11: "Needed agents" strip, one renderer, two mounts (B frontend)

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` (add `<div id="rosterHiringStrip">` above `rosterContent`, and `<div id="kinHiringStrip">` in the K.I.N. panel)

**Interfaces:**
- Consumes: `GET /api/hiring/pending` (Task 4)
- Produces: `renderHiringStrip(elId, data)`, `loadHiringStrip()`

- [ ] **Step 1: Implement one shared renderer**

```javascript
function renderHiringStrip(elId, data) {
    var el = document.getElementById(elId);
    if (!el) return;
    // Always render something. An absent panel is indistinguishable from a
    // failed load; an explicit empty state is honest (spec B §5.2).
    if (!data || !data.count) {
        setHtml(el, '<div class="dhq-hiring-strip dhq-hiring-empty">No agents proposed</div>');
        return;
    }
    var rows = data.candidates.map(function(c){
        return '<li><b>' + esc(c.capability || '—') + '</b> — ' + esc(c.gap_reason || '')
             + ' <span class="dhq-precheck">' + esc(c.precheck_status || '') + '</span>'
             + ' <span class="dhq-age">' + esc(String(c.age_hours)) + 'h</span></li>';
    }).join('');
    var more = data.count > data.candidates.length
        ? '<li>… ' + (data.count - data.candidates.length) + ' more</li>' : '';
    setHtml(el, '<div class="dhq-hiring-strip">⚠ ' + data.count
        + ' agent(s) proposed but not hired<ul>' + rows + more + '</ul></div>');
}

async function loadHiringStrip() {
    try {
        var data = await api('/api/hiring/pending');
        renderHiringStrip('rosterHiringStrip', data);
        renderHiringStrip('kinHiringStrip', data);
    } catch (err) {
        renderHiringStrip('rosterHiringStrip', null);
        renderHiringStrip('kinHiringStrip', null);
    }
}
```

Call `loadHiringStrip()` from both the roster and K.I.N. tab loaders.

- [ ] **Step 2: Verify in the browser**

Expected: `⚠ 15 agent(s) proposed but not hired` on **both** the Roster and K.I.N. tabs, matching the DB count.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/static/js/department-hq.js platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(hiring): needed-agents strip on Roster + K.I.N. [B]"
```

---

### Task 12: Full-suite run, live drive, PR

**Files:** none modified

- [ ] **Step 1: Run every new test**

```bash
cd /mnt/archie_brain/platform_v2
python3 -m pytest tests/test_roster_filters.py tests/test_roster_bulk_shift.py tests/test_hiring_pending.py -v
node --test tests/test_roster_sort.mjs
```
Expected: all PASS.

- [ ] **Step 2: Confirm no regression in the wider suite**

```bash
cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/ -q -x --timeout=300 2>&1 | tail -20
```
Expected: no NEW failures. Record any pre-existing ones rather than "fixing" them here.

- [ ] **Step 3: Deploy**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform && sleep 8
docker logs --tail 30 archie_platform 2>&1 | grep -iE "error|traceback" || echo "clean"
```

- [ ] **Step 4: Live browser drive — THE acceptance gate**

Log in as `claude` (never `kytran`):

```bash
grep -s '^ARCHIE_CLAUDE_PASSWORD=' /mnt/archie_brain/credentials/agent_passwords.env | cut -d= -f2
```

Drive `http://192.168.1.200:3000/tools/department-hq` → Roster and verify:
1. Group headers show departments with counts; `Engineering & Technology (53)`.
2. Department filter narrows the table; the count label matches the rows.
3. Type filter → `internal` shows 23.
4. Sort by Perf **descending**, then ascending — confirm `—` rows sit at the BOTTOM in both.
5. Shift dropdown shows zero-count states visibly.
6. Select 2 agents → bar appears → confirm dialog names the count → **cancel** → DB unchanged.
7. CSV export matches the visible order and row count.
8. `⚠ 15 agent(s) proposed but not hired` on Roster **and** K.I.N.
9. Light mode readable.

⚠️ Flask serves cached templates. If the page looks stale, confirm the browser actually has the new markup (grep `document.documentElement.innerHTML` for `rosterGroupBy`) before debugging logic.

- [ ] **Step 5: Confirm the DB is unchanged by read-only steps**

```bash
docker exec -i archie_database psql -U archie -d archie 2>&1 -c \
  "SELECT shift_state, count(*) FROM agents WHERE status='active' AND shift_state<>'decommissioned' GROUP BY 1 ORDER BY 2 DESC;"
```
Expected: still `active 135 / off_duty 4 / winding_down 1` unless a bulk shift was deliberately applied.

- [ ] **Step 6: Open the PR**

```bash
cd /mnt/archie_brain
git push -u origin feat/roster-table-redesign
```
Then `/commit-push-pr` (registers with Repair Bay so F.O.R.G.E. reviews it). Do **not** self-merge — per `feedback_forge-no-silent-override`, a REQUEST CHANGES is not a clear, and a missing verdict is never an approval.

---

## Notes for the executor

- **The fleet cannot implement this.** `CAP_MAP` deliberately excludes `bugfix`/`implementation` because 7B agents produce analysis, not commits (KB #290290). `work:fleet_backlog_runner:enabled` was set `false` on 2026-08-20 — leave it off.
- **Codex CLI is scoped out of `department_hq`** by `config/agents/codex.yaml`. Widening that allowlist is an owner decision, not a step in this plan.
- Sub-projects C (agent lifecycle), D (portraits) and E (identity/access) are specced/deferred separately and are **not** in scope here.
