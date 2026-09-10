# Phase 4 Cockpit UI (Crew + Code Builder) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first slice of the cockpit at archie.kytranempowerment.com — a `/cockpit` page in archie-comms with a **Crew** pane (roster, agent card, skills/budget/assign/shift-state/hire) and a **Code Builder** pane (ask-first cloud coding jobs), plus the hub read endpoints they need.

**Architecture:** Two PRs. **Hub PR** (platform_v2, bind-mounted): one new scope `agents:read`, five single-reader helpers in `agent_service`, four `GET` routes (`/api/internal/agents`, `/api/internal/agents/<id>`, `/api/internal/cloud-code/runs`, `/api/internal/cloud-code/providers`), and the Code Builder tile deep-link. **Comms PR** (archie-comms, image-baked): `services/cockpit_proxy.py` (thin, fail-closed, errors verbatim), a `cockpit_routes.py` Blueprint (`/cockpit` page + `/api/cockpit/*` session-gated routes), `templates/cockpit.html`, `static/css/cockpit.css`, `static/js/cockpit.js`, a header shortcut on the chat page, and a host-venv test runner. Then a live acceptance drive at 390 px and 1280 px.

**Tech Stack:** Flask 3 (hub + comms), psycopg2 RealDictCursor via `database.get_db_cursor`, `requests`, vanilla JS (no framework, `textContent` only), CSS grid/media queries, pytest (hub: `docker exec -i archie_platform python3 -m pytest …`; comms: host venv, `cwd=archie-comms`), hub Playwright for acceptance.

**Spec:** `docs/superpowers/specs/2026-09-10-phase4-cockpit-ui-design.md` (same branch). Mockups: https://claude.ai/code/artifact/6b727716-96f8-4a44-a6fd-bbee1a5bcecb

## Global Constraints

- Branch + PR, never `main`; merge only on a clean F.O.R.G.E. APPROVE (coverage demotion → an independent full read of the unread files before ack; never merge on REQUEST CHANGES). Commit trailer on every commit: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6`. Pre-commit hooks may rewrite files (Black) and abort the first commit → re-stage and commit again. `git add` with absolute paths only.
- NEVER `docker compose up` while a feature branch is checked out in `/mnt/archie_brain` (the platform bind-mounts the tree). Hub deploy = `git checkout main && git pull --ff-only origin main` then `docker compose restart archie_platform`. Comms is image-baked with no volumes: deploy = `docker compose up -d --build archie_comms`; `restart` deploys nothing.
- The ONLY new scope grant is `agents:read` → `archie_comms`. No new secrets; comms keeps using `INTERNAL_API_KEY` (compose maps it to the per-caller key). `INTERNAL_KEY_LEGACY_ACCEPT` untouched.
- All inference stays behind the DHQ dispatcher (ADR-013); nothing in this plan calls a model, Ollama, OmniRoute or the engine. The builder's capability is fixed server-side to `code` (`cloud_code_lane.CAPABILITY`); comms sends no capability.
- Agent mutations only via the existing `agent_service` single-writer methods; the new hub reads live in `agent_service` as single-reader helpers; no raw SQL in `app.py` routes except the two `bridge_jobs`/`contractor_providers` reads that mirror the existing cloud-code status route.
- Comms' direct-SQL roster peek `_fetch_agent_status()` in `app_comms.py` is deleted once the hub read is live (Task 8).
- UI: every piece of server text rendered with `textContent` (a source-scan test fails on `innerHTML` in `cockpit.js`); one real state class per shift state, never `sc-live`/`sc-static`; breakpoints 480 / 768 / 1024; `archie-chat.css` is comms' stylesheet (the spec's `comms.css` was a typo — fixed in Task 1).
- Every hub write shows the hub's own `error` text verbatim; no optimistic UI; reads/writes time out at 15 s / 30 s.
- Tests must be non-vacuous: fake-cursor tests assert the SQL fragments AND the mapped shape; route tests assert status + payload keys; the acceptance drive asserts DB round-trips.
- HARD CAP 3 concurrent agents; never two file-editing implementers in parallel; 2 failures on one step → STOP and report.

---

## File structure

**Hub (platform_v2)**
- `services/internal_auth.py` — add `agents:read` to `SCOPES` and to the `archie_comms` grant.
- `services/agent_service.py` — new single-reader helpers `list_roster`, `roster_facets`, `get_agent_skills`, `get_agent_budget`, `get_agent_recent_work` (appended after `set_token_budget`).
- `app.py` — 4 new GET routes: two `agents` reads inserted immediately BEFORE `@app.route("/api/internal/agents/create"` (L5718 region), two `cloud-code` reads inserted immediately AFTER the `api_internal_cloud_code_status` handler (ends ~L5976) and BEFORE `@app.route("/api/internal/delegation/submit"` (~L5979).
- `module_registry.py` — `code_builder.external_url` → `https://archie.kytranempowerment.com/cockpit#builder`.
- `tests/test_internal_auth_scopes.py` — PROBES entry + route tests (monkeypatched readers). `tests/test_agent_service_readers.py` (new) — fake-cursor tests for the five readers. `tests/test_cloud_code_reads.py` (new) — fake-cursor tests for runs/providers + the tile URL.

**Comms (archie-comms)**
- `scripts/run_tests.sh` (new) — host-venv runner (`cwd=archie-comms`).
- `services/cockpit_proxy.py` (new) — hub calls; `(status, payload)` pass-through; fail-closed.
- `cockpit_routes.py` (new, Blueprint `cockpit_bp`) — `GET /cockpit` + `/api/cockpit/*`; registered in `app_comms.py`.
- `templates/cockpit.html`, `static/css/cockpit.css`, `static/js/cockpit.js` (new).
- `templates/chat.html` — one header shortcut to `/cockpit`.
- `app_comms.py` — register the blueprint; delete `_fetch_agent_status` and its `/api/status` use.
- `tests/test_cockpit_proxy.py`, `tests/test_cockpit_routes.py`, `tests/test_cockpit_page.py` (new).

---

### Task 1: `agents:read` scope, granted to archie_comms only (+ spec typo fix)

**Files:**
- Modify: `platform_v2/services/internal_auth.py:72-121`
- Modify: `platform_v2/tests/test_internal_auth_scopes.py` (append the scope test; the PROBES entry is deliberately NOT added here — it lands in Task 3 with the route)
- (The spec's `comms.css` → `archie-chat.css` typo is already fixed on the docs branch; Step 4 is a no-op.)

**Interfaces:**
- Produces: scope string `"agents:read"` usable as `@require_internal_scope("agents:read")`; `ia.CALLER_SCOPES["archie_comms"]` contains it.

- [ ] **Step 1: Write the failing tests** — append to `platform_v2/tests/test_internal_auth_scopes.py`:

```python
# ---- Phase 4 (#6653 cockpit UI): the agents:read scope ------------------------------


def test_agents_read_scope_exists_and_is_granted_to_comms_only():
    assert "agents:read" in ia.SCOPES
    holders = [c for c, s in ia.CALLER_SCOPES.items() if "agents:read" in s]
    assert holders == ["archie_comms"], holders
```

Do NOT add a `PROBES` entry in this task. The probe route `GET /api/internal/agents` is created in Task 3, and this app answers an unmatched route with a **302 redirect, not a 404** — so a premature probe turns the out-of-scope assertion into `302 != 403` for 7 of 8 callers (`PROBES` has no `"agents:manage"` key, which makes `"agents:read"` the first out-of-scope probe alphabetically). Every commit on the branch must leave this test file fully green; the entry is added in Task 3 Step 1 alongside the route.

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py -q -k "agents_read_scope" 2>&1 | tail -3`
Expected: `1 failed` (`assert "agents:read" in ia.SCOPES`).

- [ ] **Step 3: Add the scope** — in `platform_v2/services/internal_auth.py`, inside the `SCOPES = frozenset({...})` literal after the `"cloud:code",  # …` line add:

```python
        "agents:read",  # cockpit roster/agent/skills/budget READS — comms only (#6653 Phase 4)
```

and in `CALLER_SCOPES["archie_comms"]` after `"cloud:code",` add:

```python
            "agents:read",
```

- [ ] **Step 4: (no-op)** — the spec's stylesheet name was already corrected on the docs branch; nothing to edit here.

- [ ] **Step 5: Run the whole scope file**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py -q 2>&1 | tail -3`
Expected: all pass (the per-caller table now probes `agents:read` for comms — a 404 from the not-yet-existing route counts as "not 401/403").

- [ ] **Step 6: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/internal_auth.py /mnt/archie_brain/platform_v2/tests/test_internal_auth_scopes.py
git commit -m "feat(internal-auth): agents:read scope for the cockpit roster reads, granted to archie_comms only (#6653 Phase 4)"
```

---

### Task 2: Single-reader helpers in `agent_service`

**Files:**
- Modify: `platform_v2/services/agent_service.py` (append after `set_token_budget`, ~L1185)
- Test: `platform_v2/tests/test_agent_service_readers.py` (new)

**Interfaces:**
- Produces:
  - `list_roster(q=None, department=None, shift_state=None, worker_type=None, include_decommissioned=False, limit=50, offset=0) -> tuple[list[dict], int]` — rows with keys `id, name, display_name, department, shift_state, worker_type, model, title, is_department_ai, performance_score, success_rate, last_used`; `total` = count for the same filter.
  - `roster_facets(include_decommissioned=False) -> dict` — `{"departments": {name: count}, "states": {state: count}}`.
  - `get_agent_skills(agent_id) -> list[dict]` — `skill_name, skill_category, proficiency_level, can_escalate_to`.
  - `get_agent_budget(agent_id) -> dict | None` — `token_limit_per_day, tokens_used_today, task_queue_limit, current_task_count, token_reset_at`.
  - `get_agent_recent_work(agent_id, limit=5) -> list[dict]` — `id, capability, model_used, provider, success, duration_ms, created_at`.

- [ ] **Step 1: Write the failing tests** — create `platform_v2/tests/test_agent_service_readers.py`:

```python
"""#6653 Phase 4 — cockpit READ helpers in agent_service (single-reader).

Fake cursor: asserts the SQL shape AND the mapped rows, so an empty test DB
cannot make these pass vacuously. Runs in-container:
    docker exec -i archie_platform python3 -m pytest tests/test_agent_service_readers.py -q
"""

import contextlib

import pytest

from services import agent_service as svc


class _Cur:
    def __init__(self, results):
        self._results = list(results)  # one fetch result per execute, in order
        self.sql = []
        self.params = []
        self._last = None

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self.params.append(tuple(params or ()))
        self._last = self._results.pop(0) if self._results else []

    def fetchall(self):
        return list(self._last or [])

    def fetchone(self):
        rows = self._last or []
        return rows[0] if rows else None


@pytest.fixture
def cursor(monkeypatch):
    holder = {}

    def make(results):
        cur = _Cur(results)
        holder["cur"] = cur

        @contextlib.contextmanager
        def fake_get_db_cursor(*a, **k):
            yield (None, cur)

        monkeypatch.setattr(svc, "get_db_cursor", fake_get_db_cursor)
        return cur

    return make


def test_list_roster_filters_and_counts(cursor):
    cur = cursor([[{"n": 2}], [{"id": 1, "name": "F.O.R.G.E."}, {"id": 2, "name": "P.R.O.B.E."}]])
    rows, total = svc.list_roster(q="f.o", department="Engineering & Technology", worker_type="ai", limit=10, offset=5)
    assert total == 2 and [r["id"] for r in rows] == [1, 2]
    count_sql, list_sql = cur.sql
    assert "SELECT count(*)" in count_sql and "FROM agents a" in list_sql
    assert "a.department = %s" in list_sql and "a.worker_type = %s" in list_sql
    assert "ILIKE %s" in list_sql and "<> 'decommissioned'" in list_sql
    assert cur.params[1][-2:] == (10, 5)  # LIMIT, OFFSET last
    assert "ORDER BY" in list_sql and "LIMIT %s OFFSET %s" in list_sql


def test_list_roster_can_include_decommissioned(cursor):
    cur = cursor([[{"n": 0}], []])
    svc.list_roster(include_decommissioned=True)
    assert "decommissioned" not in cur.sql[1]


def test_roster_facets_groups_departments_and_states(cursor):
    cur = cursor([[{"k": "Engineering & Technology", "n": 4}], [{"k": "active", "n": 3}, {"k": "barracked", "n": 1}]])
    f = svc.roster_facets()
    assert f == {"departments": {"Engineering & Technology": 4}, "states": {"active": 3, "barracked": 1}}
    assert "GROUP BY a.department" in cur.sql[0] and "GROUP BY a.shift_state" in cur.sql[1]


def test_get_agent_skills_reads_agent_skills(cursor):
    cur = cursor([[{"skill_name": "code", "skill_category": "engineering", "proficiency_level": 5, "can_escalate_to": None}]])
    out = svc.get_agent_skills(12)
    assert out[0]["skill_name"] == "code" and "FROM agent_skills" in cur.sql[0] and cur.params[0] == (12,)


def test_get_agent_budget_none_when_no_row(cursor):
    cursor([[]])
    assert svc.get_agent_budget(12) is None


def test_get_agent_budget_maps_row(cursor):
    cur = cursor([[{"token_limit_per_day": 250000, "tokens_used_today": 112000, "task_queue_limit": 500, "current_task_count": 3, "token_reset_at": None}]])
    out = svc.get_agent_budget(12)
    assert out["token_limit_per_day"] == 250000 and "FROM agent_budgets" in cur.sql[0]


def test_get_agent_recent_work_limits(cursor):
    cur = cursor([[{"id": 9, "capability": "code", "model_used": "qwen2.5:7b", "provider": "ollama", "success": True, "duration_ms": 1200, "created_at": None}]])
    out = svc.get_agent_recent_work(12, limit=5)
    assert out[0]["capability"] == "code" and "FROM task_execution_log" in cur.sql[0] and cur.params[0] == (12, 5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_agent_service_readers.py -q 2>&1 | tail -3`
Expected: 7 failed (`AttributeError: module 'services.agent_service' has no attribute 'list_roster'`).

- [ ] **Step 3: Implement** — append to `platform_v2/services/agent_service.py` immediately after `set_token_budget` (after its final `return limit`):

```python


# ---------------------------------------------------------------------------
# Cockpit READ helpers (#6653 Phase 4). Single-reader siblings of the
# agents:manage single-writers above; app.py routes call these, never SQL.
# ---------------------------------------------------------------------------
_ROSTER_COLS = (
    "a.id, a.name, a.display_name, a.department, a.shift_state, a.worker_type, a.model, "
    "a.title, a.is_department_ai, a.performance_score, a.success_rate, a.last_used"
)


def _roster_where(q=None, department=None, shift_state=None, worker_type=None, include_decommissioned=False):
    where, params = ["1=1"], []
    if not include_decommissioned and not shift_state:
        where.append("COALESCE(a.shift_state, '') <> 'decommissioned'")
    if department:
        where.append("a.department = %s")
        params.append(department)
    if shift_state:
        where.append("a.shift_state = %s")
        params.append(shift_state)
    if worker_type:
        where.append("a.worker_type = %s")
        params.append(worker_type)
    if q:
        q_nodot = q.replace(".", "")  # agent names are DOTTED (F.O.R.G.E.) — "forge" must match (database.md, #5272)
        where.append("(a.name ILIKE %s OR a.display_name ILIKE %s OR REPLACE(a.name, '.', '') ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q_nodot}%"])
    return " AND ".join(where), params


def list_roster(
    q=None, department=None, shift_state=None, worker_type=None, include_decommissioned=False, limit=50, offset=0
):
    """Cockpit roster page: (rows, total) for one filter. Decommissioned agents are
    excluded unless asked for by state or include_decommissioned=True."""
    where, params = _roster_where(q, department, shift_state, worker_type, include_decommissioned)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT count(*) AS n FROM agents a WHERE {where}", params)
        total = int((cur.fetchone() or {"n": 0})["n"])
        cur.execute(
            f"SELECT {_ROSTER_COLS} FROM agents a WHERE {where} "
            "ORDER BY a.display_name NULLS LAST, a.name LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
    return rows, total


def roster_facets(include_decommissioned=False):
    """Counts per department and per shift_state for the cockpit filter chips."""
    where, params = _roster_where(include_decommissioned=include_decommissioned)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"SELECT a.department AS k, count(*) AS n FROM agents a WHERE {where} GROUP BY a.department ORDER BY n DESC",
            params,
        )
        departments = {r["k"]: int(r["n"]) for r in cur.fetchall() if r["k"]}
        cur.execute(
            f"SELECT a.shift_state AS k, count(*) AS n FROM agents a WHERE {where} GROUP BY a.shift_state ORDER BY n DESC",
            params,
        )
        states = {r["k"]: int(r["n"]) for r in cur.fetchall() if r["k"]}
    return {"departments": departments, "states": states}


def get_agent_skills(agent_id):
    """Skills for one agent, highest proficiency first. Read-only (writes: add_skill/remove_skill)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT skill_name, skill_category, proficiency_level, can_escalate_to FROM agent_skills "
            "WHERE agent_id = %s ORDER BY proficiency_level DESC, skill_name",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_agent_budget(agent_id):
    """The agent_budgets row for the cockpit budget card, or None (write: set_token_budget)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT token_limit_per_day, tokens_used_today, task_queue_limit, current_task_count, token_reset_at "
            "FROM agent_budgets WHERE agent_id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_agent_recent_work(agent_id, limit=5):
    """Last N task_execution_log rows for one agent (cockpit 'Recent work')."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, capability, model_used, provider, success, duration_ms, created_at "
            "FROM task_execution_log WHERE agent_id = %s ORDER BY id DESC LIMIT %s",
            (agent_id, int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_agent_service_readers.py -q 2>&1 | tail -3`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/agent_service.py /mnt/archie_brain/platform_v2/tests/test_agent_service_readers.py
git commit -m "feat(agent_service): cockpit single-reader helpers — roster, facets, skills, budget, recent work (#6653 Phase 4)"
```

---

### Task 3: Hub routes `GET /api/internal/agents` and `GET /api/internal/agents/<id>`

**Files:**
- Modify: `platform_v2/app.py` — insert immediately BEFORE the line `@app.route("/api/internal/agents/create", methods=["POST"])` (keep the Phase 2 comment block above it intact; the new routes go between that comment and the create route).
- Test: `platform_v2/tests/test_internal_auth_scopes.py` (append)

**Interfaces:**
- Consumes: Task 2 readers; Task 1 scope.
- Produces: `GET /api/internal/agents` → `{"success": true, "agents": [...], "total": N, "limit": L, "offset": O, "facets": {...}}`; `GET /api/internal/agents/<id>` → `{"success": true, "agent": {...}, "skills": [...], "budget": {...}|null, "recent_work": [...]}`; 404 `{"success": false, "error": "agent not found"}`.

- [ ] **Step 1: Write the failing tests** — first add the probe for the new route to the `PROBES` dict in `tests/test_internal_auth_scopes.py` (after the `"cloud:code"` entry; deferred from Task 1 because the route did not exist yet and an unmatched route answers 302):

```python
    "agents:read": ("GET", "/api/internal/agents"),
```

then append the route tests:

```python
def test_agents_list_returns_roster_and_facets(client, keys, monkeypatch):
    import services.agent_service as svc

    seen = {}

    def fake_list_roster(**kw):
        seen.update(kw)
        return ([{"id": 12, "name": "F.O.R.G.E.", "display_name": "F.O.R.G.E.", "department": "Engineering & Technology",
                  "shift_state": "active", "worker_type": "ai", "model": "qwen2.5:7b", "title": "Director",
                  "is_department_ai": True, "performance_score": 88.0, "success_rate": 94.2, "last_used": None}], 1)

    monkeypatch.setattr(svc, "list_roster", fake_list_roster)
    monkeypatch.setattr(svc, "roster_facets", lambda include_decommissioned=False: {"departments": {"Engineering & Technology": 1}, "states": {"active": 1}})
    r = client.get("/api/internal/agents?q=forge&department=Engineering%20%26%20Technology&limit=10&offset=0", headers=_comms(keys))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["total"] == 1 and body["agents"][0]["id"] == 12 and body["facets"]["states"] == {"active": 1}
    assert seen["q"] == "forge" and seen["department"] == "Engineering & Technology" and seen["limit"] == 10


def test_agents_list_is_403_for_the_engine_and_401_without_a_key(client, keys):
    assert client.get("/api/internal/agents", headers=_bearer(keys["archie_engine"])).status_code == 403
    assert client.get("/api/internal/agents").status_code == 401


def test_agents_detail_bundles_skills_budget_and_recent_work(client, keys, monkeypatch):
    import services.agent_service as svc

    monkeypatch.setattr(svc, "get_agent", lambda agent_id: {"id": agent_id, "name": "F.O.R.G.E.", "display_name": "F.O.R.G.E.",
                                                            "department": "Engineering & Technology", "shift_state": "active",
                                                            "system_prompt": "SECRET-ish", "created_at": None})
    monkeypatch.setattr(svc, "get_agent_skills", lambda agent_id: [{"skill_name": "code", "skill_category": "engineering", "proficiency_level": 5, "can_escalate_to": None}])
    monkeypatch.setattr(svc, "get_agent_budget", lambda agent_id: {"token_limit_per_day": 250000, "tokens_used_today": 112000, "task_queue_limit": 500, "current_task_count": 3, "token_reset_at": None})
    monkeypatch.setattr(svc, "get_agent_recent_work", lambda agent_id, limit=5: [{"id": 1, "capability": "code", "model_used": "qwen2.5:7b", "provider": "ollama", "success": True, "duration_ms": 1200, "created_at": None}])
    r = client.get("/api/internal/agents/12", headers=_comms(keys))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["agent"]["id"] == 12 and "system_prompt" not in body["agent"]
    assert body["skills"][0]["skill_name"] == "code" and body["budget"]["token_limit_per_day"] == 250000
    assert body["recent_work"][0]["capability"] == "code"


def test_agents_detail_unknown_is_404(client, keys, monkeypatch):
    import services.agent_service as svc

    monkeypatch.setattr(svc, "get_agent", lambda agent_id: None)
    r = client.get("/api/internal/agents/999999", headers=_comms(keys))
    assert r.status_code == 404 and r.get_json()["error"] == "agent not found"
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py -q -k "agents_list or agents_detail" 2>&1 | tail -3`
Expected: 4 failed (404s where 200 expected; the 401/403 test fails on the 403 assertion because the route does not exist → 404).

- [ ] **Step 3: Implement** — insert into `platform_v2/app.py` immediately before `@app.route("/api/internal/agents/create", methods=["POST"])`:

```python
# Phase 4 (#6653): cockpit READS. agents:read (archie_comms only). Reads go
# through agent_service single-reader helpers; no SQL here.
_AGENT_PUBLIC_FIELDS = (
    "id", "name", "display_name", "department", "shift_state", "worker_type", "model", "title",
    "is_department_ai", "performance_score", "success_rate", "last_used", "bio", "first_name",
    "last_name", "email", "created_at", "status", "tier", "current_grade", "total_tasks_completed",
)


def _cockpit_json(value):
    """JSON-safe scalars for RealDictCursor rows: datetimes → isoformat, Decimal → float."""
    import datetime as _dt
    import decimal as _dec

    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, _dec.Decimal):
        return float(value)
    return value


def _cockpit_row(row, fields=None):
    return {k: _cockpit_json(v) for k, v in (row or {}).items() if fields is None or k in fields}


@app.route("/api/internal/agents", methods=["GET"])
@require_internal_scope("agents:read")
def api_internal_agents_list():
    """Cockpit roster page + filter facets (agent_service.list_roster / roster_facets)."""
    from services import agent_service as svc

    args = request.args
    try:
        limit = int(args.get("limit") or 50)
        offset = int(args.get("offset") or 0)
    except ValueError:
        return jsonify({"success": False, "error": "limit and offset must be integers"}), 400
    include_dec = args.get("state") == "decommissioned" or args.get("include_decommissioned") == "1"
    try:
        rows, total = svc.list_roster(
            q=(args.get("q") or "").strip() or None,
            department=(args.get("department") or "").strip() or None,
            shift_state=(args.get("state") or "").strip() or None,
            worker_type=(args.get("worker_type") or "").strip() or None,
            include_decommissioned=include_dec,
            limit=limit,
            offset=offset,
        )
        facets = svc.roster_facets(include_decommissioned=include_dec)
    except Exception as exc:
        logger.error("api_internal_agents_list failed: %s", exc)
        return jsonify({"success": False, "error": "roster read failed"}), 500
    return jsonify(
        {
            "success": True,
            "agents": [_cockpit_row(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "facets": facets,
        }
    )


@app.route("/api/internal/agents/<int:agent_id>", methods=["GET"])
@require_internal_scope("agents:read")
def api_internal_agents_detail(agent_id):
    """One agent + skills + budget + recent work for the cockpit agent card."""
    from services import agent_service as svc

    try:
        agent = svc.get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "agent not found"}), 404
        skills = svc.get_agent_skills(agent_id)
        budget = svc.get_agent_budget(agent_id)
        recent = svc.get_agent_recent_work(agent_id, limit=5)
    except Exception as exc:
        logger.error("api_internal_agents_detail failed: %s", exc)
        return jsonify({"success": False, "error": "agent read failed"}), 500
    return jsonify(
        {
            "success": True,
            "agent": _cockpit_row(agent, _AGENT_PUBLIC_FIELDS),
            "skills": [_cockpit_row(s) for s in skills],
            "budget": _cockpit_row(budget) if budget else None,
            "recent_work": [_cockpit_row(w) for w in recent],
        }
    )


```

(`system_prompt`, `personality_prompt`, `memory_context`, `api_key_configured` and the other internal columns are deliberately absent from `_AGENT_PUBLIC_FIELDS` — the cockpit never receives them.)

- [ ] **Step 4: Run to verify it passes** (whole file — the completeness test must still pass)

Run: `docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py -q 2>&1 | tail -3`
Expected: all pass (previous count + 5 new).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/app.py /mnt/archie_brain/platform_v2/tests/test_internal_auth_scopes.py
git commit -m "feat(internal-api): cockpit roster + agent detail reads under agents:read (#6653 Phase 4)"
```

---

### Task 4: Hub routes `GET /api/internal/cloud-code/runs` + `/providers`, and the Code Builder deep-link

**Files:**
- Modify: `platform_v2/app.py` — insert immediately AFTER the `api_internal_cloud_code_status` handler's final `)` (the `return jsonify({...})` that ends ~L5976) and BEFORE `@app.route("/api/internal/delegation/submit", methods=["POST"])`.
- Modify: `platform_v2/module_registry.py:812-835` — `code_builder` `external_url`.
- Test: `platform_v2/tests/test_cloud_code_reads.py` (new — every Task 4 test, including the 403/401 scope-gate test, lives here; `tests/test_internal_auth_scopes.py` is untouched: its completeness test discovers the routes dynamically and `cloud:code` already has a PROBES entry)

**Interfaces:**
- Produces: `GET /api/internal/cloud-code/runs?limit=20` → `{"success": true, "runs": [{job_id, status, model, provider, approval_id, created_at, completed_at, error, result: {model_used, served_model_resolved, prompt_tokens, completion_tokens, error}|null}]}`; `GET /api/internal/cloud-code/providers` → `{"success": true, "providers": [{provider_key, display_name, default_model, models: [str…], is_active}]}`.

- [ ] **Step 1: Write the failing tests** — create `platform_v2/tests/test_cloud_code_reads.py`:

```python
"""#6653 Phase 4 — cockpit reads for the coding lane: run history + providers, and the
Code Builder tile deep-link. In-container:
    docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_reads.py -q
"""

import contextlib

import pytest

from services import internal_auth as ia

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}


@pytest.fixture
def keys(monkeypatch):
    # Same shape as the fixture in test_internal_auth_scopes.py (which is not a conftest).
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.setenv(ia.LEGACY_ENV, "legacy-flat-key")
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def execute(self, sql, params=None):
        self.sql, self.params = " ".join(sql.split()), tuple(params or ())

    def fetchall(self):
        return list(self.rows)


@pytest.fixture
def db(monkeypatch):
    def install(rows):
        cur = _Cur(rows)

        @contextlib.contextmanager
        def fake(*a, **k):
            yield (None, cur)

        import database

        monkeypatch.setattr(database, "get_db_cursor", fake)
        return cur

    return install


def _comms_headers(keys):
    return _bearer(keys["archie_comms"])


def test_runs_lists_cloud_code_jobs_without_prompt_text(client, keys, db):
    cur = db([{"id": 1198308, "status": "completed", "metadata": {"approval_id": 15233, "model": "oc/big-pickle", "provider": "omniroute",
                                                                   "prompt": "SECRET PROMPT", "result": {"model_used": "big-pickle", "served_model_resolved": True,
                                                                   "prompt_tokens": 454, "completion_tokens": 1010, "error": None, "response": "def fizzbuzz"}},
               "error_message": None, "created_at": None, "completed_at": None}])
    r = client.get("/api/internal/cloud-code/runs?limit=5", headers=_comms_headers(keys))
    assert r.status_code == 200, r.get_json()
    run = r.get_json()["runs"][0]
    assert run["job_id"] == 1198308 and run["result"]["model_used"] == "big-pickle"
    assert "prompt" not in run and "response" not in run["result"]
    assert "job_type = %s" in cur.sql and "ORDER BY id DESC LIMIT %s" in cur.sql and cur.params[-1] == 5


def test_runs_limit_is_capped_at_100(client, keys, db):
    cur = db([])
    r = client.get("/api/internal/cloud-code/runs?limit=5000", headers=_comms_headers(keys))
    assert r.status_code == 200 and cur.params[-1] == 100


def test_providers_lists_active_non_proxy_text_chat_providers(client, keys, db):
    cur = db([{"provider_key": "omniroute", "display_name": "OmniRoute (self-hosted gateway)", "default_model": "oc/big-pickle",
               "models": [{"name": "oc/big-pickle"}, {"name": "auto/coding"}], "is_active": True}])
    r = client.get("/api/internal/cloud-code/providers", headers=_comms_headers(keys))
    assert r.status_code == 200, r.get_json()
    p = r.get_json()["providers"][0]
    assert p["provider_key"] == "omniroute" and p["models"] == ["oc/big-pickle", "auto/coding"] and p["default_model"] == "oc/big-pickle"
    assert "is_active" in cur.sql and "is_cloud_proxy" in cur.sql and "text_chat" in cur.sql


def test_cloud_code_reads_need_the_cloud_code_scope(client, keys):
    assert client.get("/api/internal/cloud-code/runs", headers=_bearer(keys["media_hub"])).status_code == 403
    assert client.get("/api/internal/cloud-code/providers").status_code == 401


def test_code_builder_tile_deep_links_to_the_builder_pane():
    from module_registry import MODULES

    tile = next(m for m in MODULES if m.id == "code_builder")
    assert tile.external_url == "https://archie.kytranempowerment.com/cockpit#builder"
```

(If `MODULES` entries are dicts rather than objects in `module_registry.py`, use `m["id"]` / `m["external_url"]` — read the file's existing entries first and match.)

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_reads.py -q 2>&1 | tail -3`
Expected: 5 failed (404s; the tile URL is still `https://archie.kytranempowerment.com`).

- [ ] **Step 3: Implement the two routes** — insert into `platform_v2/app.py` after the `api_internal_cloud_code_status` handler and before the delegation/submit route:

```python
@app.route("/api/internal/cloud-code/runs", methods=["GET"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_runs():
    """Cockpit job history (newest first). Prompt text and the full response are NOT
    included — the per-job status route has them."""
    from database import get_db_cursor
    from services import cloud_code_lane as lane

    try:
        limit = max(1, min(int(request.args.get("limit") or 20), 100))
    except ValueError:
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, status, metadata, error_message, created_at, completed_at FROM bridge_jobs "
            "WHERE job_type = %s ORDER BY id DESC LIMIT %s",
            (lane.JOB_TYPE, limit),
        )
        rows = cur.fetchall()
    runs = []
    for row in rows:
        meta = row["metadata"] or {}
        res = meta.get("result") or None
        runs.append(
            {
                "job_id": row["id"],
                "status": row["status"],
                "approval_id": meta.get("approval_id"),
                "model": meta.get("model"),
                "provider": meta.get("provider"),
                "error": row["error_message"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "result": (
                    {k: res.get(k) for k in ("model_used", "served_model_resolved", "prompt_tokens", "completion_tokens", "error")}
                    if isinstance(res, dict)
                    else None
                ),
            }
        )
    return jsonify({"success": True, "runs": runs})


@app.route("/api/internal/cloud-code/providers", methods=["GET"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_providers():
    """Providers the Code Builder may target: active, text_chat, NOT cloud-proxy rows
    (is_cloud_proxy=true routes via call_ollama_cloud, not the gateway)."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT provider_key, display_name, default_model, models, is_active FROM contractor_providers "
            "WHERE is_active = true AND COALESCE(is_cloud_proxy, false) = false AND capabilities ? 'text_chat' "
            "ORDER BY tier_position, provider_key"
        )
        rows = cur.fetchall()
    providers = []
    for row in rows:
        models = row["models"] or []
        names = [m.get("name") if isinstance(m, dict) else str(m) for m in models]
        providers.append(
            {
                "provider_key": row["provider_key"],
                "display_name": row["display_name"] or row["provider_key"],
                "default_model": row["default_model"],
                "models": [n for n in names if n],
                "is_active": bool(row["is_active"]),
            }
        )
    return jsonify({"success": True, "providers": providers})


```

- [ ] **Step 4: Point the tile at the builder** — in `platform_v2/module_registry.py` inside the `code_builder` entry change `external_url="https://archie.kytranempowerment.com"` to `external_url="https://archie.kytranempowerment.com/cockpit#builder"`.

- [ ] **Step 5: Run to verify it passes**, then the full hub sweep for this PR

Run: `docker exec -i archie_platform python3 -m pytest tests/test_cloud_code_reads.py tests/test_internal_auth_scopes.py tests/test_agent_service_readers.py tests/test_cloud_code_lane.py -q 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add /mnt/archie_brain/platform_v2/app.py /mnt/archie_brain/platform_v2/module_registry.py /mnt/archie_brain/platform_v2/tests/test_cloud_code_reads.py
git commit -m "feat(internal-api): cloud-code run history + providers reads; Code Builder tile deep-links to /cockpit#builder (#6653 Phase 4)"
```

---

### Task 5: Hub PR — review, merge, deploy, verify

**Files:** none new.

- [ ] **Step 1: Push + PR** (branch `feat/phase4-cockpit-hub-reads`, cut from `main` before Task 1)

```bash
git push -u origin feat/phase4-cockpit-hub-reads
gh pr create --title "feat(phase4): cockpit reads — agents:read scope, roster/agent/cloud-code/providers endpoints, Code Builder deep-link (#6653)" --body "$(cat <<'EOF'
## Summary
- New scope `agents:read` (archie_comms only) + `GET /api/internal/agents` (roster + facets) and `GET /api/internal/agents/<id>` (agent + skills + budget + recent work) via new `agent_service` single-reader helpers. Internal columns (system_prompt etc.) never leave.
- `GET /api/internal/cloud-code/runs` (history, no prompt/response text) + `GET /api/internal/cloud-code/providers` (active, non-proxy, text_chat) under `cloud:code`.
- Code Builder tile → `https://archie.kytranempowerment.com/cockpit#builder`.

## Test Plan
- [x] tests/test_internal_auth_scopes.py (+7) · tests/test_agent_service_readers.py (7) · tests/test_cloud_code_reads.py (5) — all green in-container
- [ ] live: from archie_comms `GET /api/internal/agents?limit=1` → 200 with `total > 0` (after deploy)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6
EOF
)"
```

- [ ] **Step 2: Register + F.O.R.G.E. review (background), merge on a clean APPROVE**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs; print(poll_open_prs())
from tools.repair_bay.services.pr_diff_analyzer import review_pr
r = review_pr(<PR>); print(r.get('ok'), r.get('verdict'), r.get('error'))"
```
When `reviewed`: original verdict must be `APPROVE` with no REQUEST CHANGES; if the coverage gate demoted it, dispatch an independent full read of the dropped files and merge only on its CLEAR. Merge: `merge_pr(<PR>, method='squash', human_override=True)`.

- [ ] **Step 3: Deploy + verify**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main && docker compose restart archie_platform
docker exec -i archie_comms python3 - <<'PY'
import os, json, urllib.request as u
BASE, KEY = os.environ.get("PLATFORM_URL", "http://archie_platform:3000"), os.environ["INTERNAL_API_KEY"]
for p in ("/api/internal/agents?limit=1", "/api/internal/cloud-code/providers", "/api/internal/cloud-code/runs?limit=2"):
    r = u.urlopen(u.Request(BASE + p, headers={"Authorization": f"Bearer {KEY}"}), timeout=15); d = json.load(r)
    print(p, r.status, {k: (v if not isinstance(v, list) else len(v)) for k, v in d.items() if k != "facets"})
PY
```
Expected: three 200s; `total > 0`; providers contains `omniroute` with `default_model oc/big-pickle`.

---

### Task 6: A working comms test runner (host venv)

**Files:**
- Create: `archie-comms/scripts/run_tests.sh`

**Interfaces:**
- Produces: `bash archie-comms/scripts/run_tests.sh [pytest args]` runs the comms suite with `cwd=archie-comms`; venv at `${COMMS_VENV:-$HOME/.cache/archie-comms-venv}`.

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# archie-comms unit tests run on the HOST: the image excludes tests/ (.dockerignore) and
# ships no pytest, so `docker exec archie_comms pytest` cannot work (#6653 Phase 4).
# Usage: bash archie-comms/scripts/run_tests.sh [pytest args]   (default: -q tests/)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${COMMS_VENV:-$HOME/.cache/archie-comms-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q "flask==3.1.*" "flask-login==0.6.*" "requests>=2.33.0" "pyjwt>=2.12.0" pytest
fi
cd "$HERE"
exec "$VENV/bin/python" -m pytest "${@:--q tests/}"
```

- [ ] **Step 2: Run the existing suite as the baseline**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh 2>&1 | tail -3`
Expected: the existing tests pass (record the count in the report; a pre-existing failure unrelated to this plan is reported, not fixed).

- [ ] **Step 3: Commit** (branch `feat/phase4-cockpit-comms`, cut from `main` after Task 5 merged)

```bash
chmod +x /mnt/archie_brain/archie-comms/scripts/run_tests.sh
git add /mnt/archie_brain/archie-comms/scripts/run_tests.sh
git commit -m "chore(comms): host-venv test runner — the image excludes tests/ and ships no pytest (#6653 Phase 4)"
```

---

### Task 7: `services/cockpit_proxy.py`

**Files:**
- Create: `archie-comms/services/cockpit_proxy.py`
- Test: `archie-comms/tests/test_cockpit_proxy.py`

**Interfaces:**
- Produces (every function returns `(status: int, payload: dict)` — the hub's status and JSON passed through; transport/config failures become `503`):
  - `list_agents(params: dict)`, `get_agent(agent_id: int)`, `create_agent(body: dict)`, `agent_action(agent_id: int, action: str, body: dict)` with `action ∈ ACTIONS = ("assign", "shift-state", "skills/add", "skills/remove", "budget")`
  - `build_providers()`, `build_run(body: dict)`, `build_status(job_id: int)`, `build_runs(limit: int = 20)`

- [ ] **Step 1: Write the failing tests** — create `archie-comms/tests/test_cockpit_proxy.py`:

```python
"""#6653 Phase 4 — thin cockpit->hub proxy. Passes the hub's status + JSON through
verbatim (the UI shows the hub's own error text); fail-CLOSED on transport/config."""

import services.cockpit_proxy as cp


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


def test_list_agents_forwards_query_and_bearer(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.update(method=method, url=url, headers=headers, timeout=timeout, params=params)
        return _Resp(200, {"success": True, "agents": [], "total": 0})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.list_agents({"q": "forge", "limit": "10"})
    assert status == 200 and body["total"] == 0
    assert seen["method"] == "GET" and seen["url"].endswith("/api/internal/agents")
    assert seen["params"] == {"q": "forge", "limit": "10"} and seen["headers"]["Authorization"] == "Bearer k"
    assert seen["timeout"] == 15


def test_writes_use_30s_and_pass_hub_errors_verbatim(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.update(method=method, url=url, json=json, timeout=timeout)
        return _Resp(400, {"success": False, "error": "skill_name required"})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.agent_action(12, "skills/add", {"skill_name": ""})
    assert status == 400 and body["error"] == "skill_name required"
    assert seen["method"] == "POST" and seen["url"].endswith("/api/internal/agents/12/skills/add") and seen["timeout"] == 30


def test_unknown_action_is_refused_locally(monkeypatch):
    called = []
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: called.append(1))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.agent_action(12, "delete", {})
    assert status == 400 and "unknown action" in body["error"] and not called


def test_missing_key_is_503_without_a_request(monkeypatch):
    called = []
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: called.append(1))
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    status, body = cp.build_providers()
    assert status == 503 and "not configured" in body["error"] and not called


def test_transport_error_is_503_hub_unreachable(monkeypatch):
    def boom(*a, **k):
        raise cp.requests.ConnectionError("refused")

    monkeypatch.setattr(cp.requests, "request", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.build_status(1198308)
    assert status == 503 and body["error"].startswith("hub unreachable")


def test_non_json_hub_reply_becomes_an_error_dict(monkeypatch):
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: _Resp(502, ValueError("not json")))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.build_runs(5)
    assert status == 502 and body == {"success": False, "error": "HTTP 502"}


def test_build_run_posts_prompt_and_model(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.update(method=method, url=url, json=json)
        return _Resp(202, {"success": True, "status": "pending_approval", "job_id": 1, "approval_id": 2})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.build_run({"prompt": "hi", "model": "oc/big-pickle", "provider": "omniroute"})
    assert status == 202 and body["job_id"] == 1 and seen["url"].endswith("/api/internal/cloud-code/run")
    assert seen["json"] == {"prompt": "hi", "model": "oc/big-pickle", "provider": "omniroute"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_proxy.py 2>&1 | tail -3`
Expected: collection error — `ModuleNotFoundError: No module named 'services.cockpit_proxy'`.

- [ ] **Step 3: Implement** — create `archie-comms/services/cockpit_proxy.py`:

```python
"""Cockpit -> hub proxy for the Crew and Code Builder panes (#6653 Phase 4).

Same shape as approvals_proxy: PLATFORM_URL + Bearer INTERNAL_API_KEY read at call time,
Docker-internal hostname only. Unlike the approvals proxy this one PASSES THROUGH the
hub's status code and JSON so the UI can show the hub's own error text verbatim — no
fail-soft empties, no optimistic success. Transport/config failures are 503 dicts.
"""

import os

import requests

READ_TIMEOUT = 15
WRITE_TIMEOUT = 30
ACTIONS = ("assign", "shift-state", "skills/add", "skills/remove", "budget")


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _call(method, path, json=None, params=None):
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        return 503, {"success": False, "error": "comms is not configured to reach the hub (no internal key)"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout = WRITE_TIMEOUT if method == "POST" else READ_TIMEOUT
    try:
        r = requests.request(method, f"{_base()}{path}", json=json, headers=headers, timeout=timeout, params=params)
    except requests.RequestException as exc:
        return 503, {"success": False, "error": f"hub unreachable: {exc.__class__.__name__}"}
    try:
        data = r.json()
    except ValueError:
        data = {"success": False, "error": f"HTTP {r.status_code}"}
    if not isinstance(data, dict):
        data = {"success": False, "error": "unexpected hub response"}
    return r.status_code, data


def _int(v, name):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


# ---- Crew ----------------------------------------------------------------------------
def list_agents(params):
    allowed = {k: v for k, v in (params or {}).items() if k in ("q", "department", "state", "worker_type", "limit", "offset", "include_decommissioned")}
    return _call("GET", "/api/internal/agents", params=allowed)


def get_agent(agent_id):
    return _call("GET", f"/api/internal/agents/{_int(agent_id, 'agent_id')}")


def create_agent(body):
    return _call("POST", "/api/internal/agents/create", json=body or {})


def agent_action(agent_id, action, body):
    if action not in ACTIONS:
        return 400, {"success": False, "error": f"unknown action {action!r}"}
    return _call("POST", f"/api/internal/agents/{_int(agent_id, 'agent_id')}/{action}", json=body or {})


# ---- Code Builder --------------------------------------------------------------------
def build_providers():
    return _call("GET", "/api/internal/cloud-code/providers")


def build_run(body):
    return _call("POST", "/api/internal/cloud-code/run", json=body or {})


def build_status(job_id):
    return _call("GET", f"/api/internal/cloud-code/run/{_int(job_id, 'job_id')}")


def build_runs(limit=20):
    return _call("GET", "/api/internal/cloud-code/runs", params={"limit": _int(limit, "limit")})
```

- [ ] **Step 4: Run to verify it passes**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_proxy.py 2>&1 | tail -3`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/archie-comms/services/cockpit_proxy.py /mnt/archie_brain/archie-comms/tests/test_cockpit_proxy.py
git commit -m "feat(comms): cockpit_proxy — pass-through hub calls for Crew + Code Builder, fail-closed (#6653 Phase 4)"
```

---

### Task 8: `cockpit_routes.py` Blueprint + registration; delete the direct-SQL roster peek

**Files:**
- Create: `archie-comms/cockpit_routes.py`
- Modify: `archie-comms/app_comms.py` — register the blueprint just above `if __name__ == "__main__":`; delete `_fetch_agent_status()` and make `/api/status` (~L348) return `"agents": []` with a comment pointing at the cockpit reads.
- Test: `archie-comms/tests/test_cockpit_routes.py`

**Interfaces:**
- Consumes: Task 7 proxy functions.
- Produces: `GET /cockpit` (redirect to `/login?next=/cockpit` without a session); `GET /api/cockpit/agents`, `GET /api/cockpit/agents/<int:id>`, `POST /api/cockpit/agents/create`, `POST /api/cockpit/agents/<int:id>/assign|shift-state|budget`, `POST /api/cockpit/agents/<int:id>/skills/add|remove`, `GET /api/cockpit/build/providers`, `POST /api/cockpit/build/run`, `GET /api/cockpit/build/runs`, `GET /api/cockpit/build/<int:job_id>` — all 401 `{"error":"Not authenticated"}` without `session["user_id"]`.

- [ ] **Step 1: Write the failing tests** — create `archie-comms/tests/test_cockpit_routes.py`:

```python
"""#6653 Phase 4 — the cockpit Blueprint: session-gated, thin, pass-through."""

from pathlib import Path

from flask import Flask

import cockpit_routes as cr
import services.cockpit_proxy as cp

ROOT = Path(__file__).resolve().parents[1]  # archie-comms/


def _app():
    # Absolute folders: Flask(__name__) would otherwise look for tests/templates.
    app = Flask("cockpit_test", template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.secret_key = "t"
    app.register_blueprint(cr.cockpit_bp)
    return app


def _login(client):
    with client.session_transaction() as s:
        s["user_id"] = 4


def test_page_redirects_to_login_without_a_session():
    c = _app().test_client()
    r = c.get("/cockpit")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login?next=/cockpit")


def test_api_is_401_without_a_session():
    c = _app().test_client()
    assert c.get("/api/cockpit/agents").status_code == 401
    assert c.post("/api/cockpit/build/run", json={"prompt": "x"}).status_code == 401


def test_agents_list_passes_query_and_status_through(monkeypatch):
    monkeypatch.setattr(cp, "list_agents", lambda params: (200, {"success": True, "agents": [], "total": 0, "q": params.get("q")}))
    c = _app().test_client()
    _login(c)
    r = c.get("/api/cockpit/agents?q=forge")
    assert r.status_code == 200 and r.get_json()["q"] == "forge"


def test_agent_action_routes_map_to_proxy_actions(monkeypatch):
    seen = []
    monkeypatch.setattr(cp, "agent_action", lambda agent_id, action, body: seen.append((agent_id, action, body)) or (200, {"success": True}))
    c = _app().test_client()
    _login(c)
    for path, action in (("assign", "assign"), ("shift-state", "shift-state"), ("skills/add", "skills/add"), ("skills/remove", "skills/remove"), ("budget", "budget")):
        assert c.post(f"/api/cockpit/agents/12/{path}", json={"x": 1}).status_code == 200
    assert [a for _, a, _ in seen] == ["assign", "shift-state", "skills/add", "skills/remove", "budget"]
    assert seen[0][0] == 12 and seen[0][2] == {"x": 1}


def test_hub_errors_are_returned_verbatim(monkeypatch):
    monkeypatch.setattr(cp, "build_run", lambda body: (409, {"success": False, "status": "approval_unavailable", "error": "one pending"}))
    c = _app().test_client()
    _login(c)
    r = c.post("/api/cockpit/build/run", json={"prompt": "x"})
    assert r.status_code == 409 and r.get_json()["error"] == "one pending"


def test_build_status_and_runs(monkeypatch):
    monkeypatch.setattr(cp, "build_status", lambda job_id: (200, {"success": True, "job_id": job_id}))
    monkeypatch.setattr(cp, "build_runs", lambda limit=20: (200, {"success": True, "runs": [], "limit": limit}))
    c = _app().test_client()
    _login(c)
    assert c.get("/api/cockpit/build/1198308").get_json()["job_id"] == 1198308
    assert c.get("/api/cockpit/build/runs?limit=5").get_json()["limit"] == 5


def test_page_renders_for_a_session():
    c = _app().test_client()
    _login(c)
    r = c.get("/cockpit")
    assert r.status_code == 200 and b'id="pane-crew"' in r.data and b'id="pane-builder"' in r.data
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_routes.py 2>&1 | tail -3`
Expected: collection error — `No module named 'cockpit_routes'`.

- [ ] **Step 3: Implement** — create `archie-comms/cockpit_routes.py`:

```python
"""Cockpit page + /api/cockpit/* routes (#6653 Phase 4). Session-gated like the
approvals routes (session['user_id']); every hub call goes through
services.cockpit_proxy, which passes the hub's status + JSON through verbatim.
A Blueprint so it is testable without importing app_comms."""

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session

from services import cockpit_proxy as cp

cockpit_bp = Blueprint("cockpit", __name__)


def _require_session(fn):
    @wraps(fn)
    def _wrapped(*a, **k):
        if not session.get("user_id"):
            return jsonify({"error": "Not authenticated"}), 401
        return fn(*a, **k)

    return _wrapped


def _pass(result):
    status, payload = result
    return jsonify(payload), status


@cockpit_bp.route("/cockpit")
def cockpit_page():
    if not session.get("user_id"):
        return redirect("/login?next=/cockpit")
    return render_template("cockpit.html")


# ---- Crew ----------------------------------------------------------------------------
@cockpit_bp.route("/api/cockpit/agents", methods=["GET"])
@_require_session
def cockpit_agents():
    return _pass(cp.list_agents(request.args.to_dict()))


@cockpit_bp.route("/api/cockpit/agents/<int:agent_id>", methods=["GET"])
@_require_session
def cockpit_agent(agent_id):
    return _pass(cp.get_agent(agent_id))


@cockpit_bp.route("/api/cockpit/agents/create", methods=["POST"])
@_require_session
def cockpit_agent_create():
    return _pass(cp.create_agent(request.get_json(silent=True) or {}))


def _action_route(action):
    def view(agent_id):
        return _pass(cp.agent_action(agent_id, action, request.get_json(silent=True) or {}))

    view.__name__ = "cockpit_agent_" + action.replace("/", "_").replace("-", "_")
    return _require_session(view)


for _action in cp.ACTIONS:
    cockpit_bp.add_url_rule(f"/api/cockpit/agents/<int:agent_id>/{_action}", view_func=_action_route(_action), methods=["POST"])


# ---- Code Builder --------------------------------------------------------------------
@cockpit_bp.route("/api/cockpit/build/providers", methods=["GET"])
@_require_session
def cockpit_build_providers():
    return _pass(cp.build_providers())


@cockpit_bp.route("/api/cockpit/build/run", methods=["POST"])
@_require_session
def cockpit_build_run():
    return _pass(cp.build_run(request.get_json(silent=True) or {}))


@cockpit_bp.route("/api/cockpit/build/runs", methods=["GET"])
@_require_session
def cockpit_build_runs():
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    return _pass(cp.build_runs(limit))


@cockpit_bp.route("/api/cockpit/build/<int:job_id>", methods=["GET"])
@_require_session
def cockpit_build_status(job_id):
    return _pass(cp.build_status(job_id))
```

- [ ] **Step 4: Register in `app_comms.py`** — immediately above `if __name__ == "__main__":` add:

```python
# #6653 Phase 4 — the cockpit (Crew + Code Builder). Blueprint so it stays testable
# without this module's import-time side effects.
from cockpit_routes import cockpit_bp  # noqa: E402

app.register_blueprint(cockpit_bp)
```

- [ ] **Step 5: Delete the direct-SQL roster peek** — in `app_comms.py` remove the whole `def _fetch_agent_status(...)` function and, in the `/api/status` handler (~L348), replace its call with `"agents": []` plus the comment `# roster moved to the cockpit's hub read (GET /api/cockpit/agents) — comms holds no agent SQL (#6653 Phase 4)`. Run `grep -n "_fetch_agent_status\|FROM agents" /mnt/archie_brain/archie-comms/app_comms.py` → no hits.

- [ ] **Step 6: Placeholder template so Step 7's render test can pass** — create `archie-comms/templates/cockpit.html` with the minimal skeleton (Task 9 replaces it in full):

```html
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>A.R.C.H.I.E. Cockpit</title></head>
<body><main id="pane-crew"></main><main id="pane-builder"></main></body></html>
```

- [ ] **Step 7: Run to verify it passes** (+ the whole comms suite)

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_routes.py 2>&1 | tail -3` → `7 passed`; then `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh 2>&1 | tail -3` → all pass.

- [ ] **Step 8: Commit**

```bash
git add /mnt/archie_brain/archie-comms/cockpit_routes.py /mnt/archie_brain/archie-comms/app_comms.py /mnt/archie_brain/archie-comms/templates/cockpit.html /mnt/archie_brain/archie-comms/tests/test_cockpit_routes.py
git commit -m "feat(comms): /cockpit page + /api/cockpit/* session-gated routes (Blueprint); drop the direct-SQL roster peek (#6653 Phase 4)"
```

---

### Task 9: `cockpit.html` + `cockpit.css` — both layouts

**Files:**
- Modify (replace): `archie-comms/templates/cockpit.html`
- Create: `archie-comms/static/css/cockpit.css`
- Test: `archie-comms/tests/test_cockpit_page.py` (new — template/CSS assertions; the JS scan is added in Task 10)

**Interfaces:**
- Produces: element ids consumed by `cockpit.js` (Task 10): `pane-crew`, `pane-builder`, `pane-approvals`, `ck-tabs` (+ buttons `data-pane="crew|builder|approvals"`), `ck-search`, `ck-chips`, `ck-roster`, `ck-more`, `ck-agent` (sheet), `ck-agent-close`, `ck-hire-open`, `ck-hire` (form), `ck-provider`, `ck-model`, `ck-prompt`, `ck-system`, `ck-run`, `ck-jobs`, `ck-approvals`, `ck-strip`, `ck-toast`.

- [ ] **Step 1: Write the failing tests** — create `archie-comms/tests/test_cockpit_page.py`:

```python
"""#6653 Phase 4 — the cockpit page: both layouts from one template; the JS never
renders server text with innerHTML."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "cockpit.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "cockpit.css").read_text(encoding="utf-8")

IDS = ["pane-crew", "pane-builder", "pane-approvals", "ck-tabs", "ck-search", "ck-chips", "ck-roster", "ck-more",
       "ck-agent", "ck-agent-close", "ck-hire-open", "ck-hire", "ck-provider", "ck-model", "ck-prompt", "ck-system",
       "ck-run", "ck-jobs", "ck-approvals", "ck-strip", "ck-toast"]


def test_template_has_every_id_the_js_binds():
    missing = [i for i in IDS if f'id="{i}"' not in HTML]
    assert not missing, missing


def test_template_loads_cockpit_assets_and_the_shared_stylesheet():
    assert '/static/css/archie-chat.css' in HTML and '/static/css/cockpit.css' in HTML and '/static/js/cockpit.js' in HTML
    assert 'name="viewport"' in HTML


def test_css_has_the_three_breakpoints_and_the_desktop_grid():
    assert "grid-template-columns: 320px 1fr 400px" in CSS
    for bp in ("480px", "768px", "1024px"):
        assert f"(max-width: {bp})" in CSS or f"(min-width: {bp})" in CSS, bp


def test_no_phantom_state_classes():
    assert "sc-live" not in HTML + CSS and "sc-static" not in HTML + CSS
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py 2>&1 | tail -3`
Expected: 3 failed (ids/assets/CSS missing), 1 passed.

- [ ] **Step 3: Write the template** — replace `archie-comms/templates/cockpit.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>A.R.C.H.I.E. Cockpit</title>
  <link rel="icon" type="image/png" href="/static/favicon.png">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/css/archie-chat.css">
  <link rel="stylesheet" href="/static/css/cockpit.css">
</head>
<body class="ck-body">
  <header class="ck-header">
    <a class="ck-brand" href="/chat">A.R.C.H.I.E. <span>▸ Cockpit</span></a>
    <nav class="ck-nav" aria-label="Sections">
      <a href="/chat">Chat</a>
      <a class="ck-nav-on" href="/cockpit#crew">Cockpit</a>
      <a href="/chat#terminal">Terminal</a>
    </nav>
  </header>

  <!-- desktop: approvals strip under the header; phone: hidden (Approvals is a tab) -->
  <section id="ck-strip" class="ck-strip" aria-label="Approvals waiting"></section>

  <main class="ck-main">
    <section id="pane-crew" class="ck-pane" aria-label="Crew">
      <div class="ck-pane-head">
        <h2>Crew <span id="ck-total" class="ck-count"></span></h2>
        <button id="ck-hire-open" class="ck-btn ck-primary" type="button">+ Propose a hire</button>
      </div>
      <input id="ck-search" class="ck-search" type="search" placeholder="Search crew…" autocomplete="off">
      <div id="ck-chips" class="ck-chips" role="group" aria-label="Filters"></div>
      <div id="ck-roster" class="ck-roster" role="list"></div>
      <button id="ck-more" class="ck-btn ck-block" type="button" hidden>Load more</button>

      <form id="ck-hire" class="ck-sheet ck-form" hidden>
        <div class="ck-sheet-head"><button type="button" class="ck-back" data-close="ck-hire">‹ Crew</button><h3>Propose a hire</h3></div>
        <label>Name <input name="name" required placeholder="S.C.A.N."></label>
        <label>Display name <input name="display_name" required></label>
        <label>Department <select name="department" id="ck-hire-dept"></select></label>
        <label>Model <input name="model" required placeholder="qwen2.5:7b"></label>
        <label>Capability <input name="capability" required placeholder="security"></label>
        <label>Reason <textarea name="reason" required rows="3"></textarea></label>
        <label>Suggested skills <input name="suggested_skills" placeholder="log_scanning, compliance"></label>
        <button class="ck-btn ck-primary ck-block" type="submit">Propose — needs your approval</button>
      </form>
    </section>

    <section id="ck-agent" class="ck-pane ck-sheet" aria-label="Agent" hidden>
      <div class="ck-sheet-head"><button id="ck-agent-close" type="button" class="ck-back">‹ Crew</button><h3 id="ck-agent-name"></h3><span id="ck-agent-state" class="ck-pill"></span></div>
      <div id="ck-agent-body"></div>
    </section>

    <section id="pane-builder" class="ck-pane" aria-label="Code Builder">
      <div class="ck-pane-head"><h2>Code Builder</h2><span class="ck-pill ck-pill-cloud">cloud · ask-first</span></div>
      <form id="ck-compose" class="ck-form">
        <div class="ck-two">
          <label>Provider <select id="ck-provider"></select></label>
          <label>Model <select id="ck-model"></select></label>
        </div>
        <label>Prompt <textarea id="ck-prompt" rows="4" required placeholder="Write a Python fizzbuzz(n) with a docstring. Reply with code only."></textarea></label>
        <details><summary>System prompt (optional)</summary><textarea id="ck-system" rows="3"></textarea></details>
        <button id="ck-run" class="ck-btn ck-primary ck-block" type="submit">Run — needs your approval</button>
      </form>
      <div class="ck-pane-head"><h3>Jobs</h3><button id="ck-jobs-refresh" class="ck-btn ck-small" type="button">Refresh</button></div>
      <div id="ck-jobs" class="ck-jobs" role="list"></div>
    </section>

    <section id="pane-approvals" class="ck-pane" aria-label="Approvals">
      <div class="ck-pane-head"><h2>Approvals <span id="ck-approvals-count" class="ck-count"></span></h2><span class="ck-muted">also in Telegram</span></div>
      <div id="ck-approvals" class="ck-approvals" role="list"></div>
    </section>
  </main>

  <nav id="ck-tabs" class="ck-tabs" aria-label="Cockpit panes">
    <button type="button" data-pane="crew" class="ck-tab-on">Crew</button>
    <button type="button" data-pane="builder">Builder</button>
    <button type="button" data-pane="approvals">Approvals <span id="ck-tab-badge" class="ck-badge" hidden></span></button>
  </nav>

  <div id="ck-toast" class="ck-toast" role="status" aria-live="polite" hidden></div>
  <script src="/static/js/cockpit.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write the stylesheet** — create `archie-comms/static/css/cockpit.css`:

```css
/* Cockpit (#6653 Phase 4). Phone-first (stacked panes + bottom tabs); desktop ≥1024px =
   three panes (320 | 1fr | 400) with the approvals STRIP under the header. Same components,
   only this file changes by breakpoint. Tokens come from archie-chat.css where defined. */
.ck-body { margin: 0; background: #0a0a1a; color: #e6e8f0; font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 13px; line-height: 1.45; }
.ck-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-bottom: 1px solid #2a2a55; background: #121230; position: sticky; top: 0; z-index: 4; }
.ck-brand { color: #e6e8f0; text-decoration: none; font-weight: 600; letter-spacing: .06em; }
.ck-brand span { color: #00d4ff; }
.ck-nav { display: none; gap: 16px; font-size: 12px; }
.ck-nav a { color: #8b90b3; text-decoration: none; padding-bottom: 2px; }
.ck-nav a.ck-nav-on { color: #e6e8f0; border-bottom: 2px solid #00d4ff; }
.ck-main { display: block; padding: 12px 14px 76px; }
.ck-pane { display: none; flex-direction: column; gap: 10px; min-width: 0; }
.ck-pane.ck-show { display: flex; }
.ck-pane-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.ck-pane-head h2, .ck-pane-head h3 { margin: 0; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #8b90b3; font-weight: 600; }
.ck-count, .ck-muted { color: #8b90b3; font-size: 11px; }
.ck-search { width: 100%; box-sizing: border-box; background: #0a0a1a; color: #e6e8f0; border: 1px solid #2a2a55; border-radius: 8px; padding: 9px 10px; font: inherit; }
.ck-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.ck-chip { font: inherit; font-size: 11px; border: 1px solid #3a3a70; background: transparent; color: #8b90b3; border-radius: 999px; padding: 3px 9px; cursor: pointer; }
.ck-chip[aria-pressed="true"] { border-color: #00d4ff; color: #00d4ff; }
.ck-roster, .ck-jobs, .ck-approvals { display: flex; flex-direction: column; gap: 8px; }
.ck-card { background: #1a1a3a; border: 1px solid #2a2a55; border-radius: 10px; padding: 10px 12px; text-align: left; color: inherit; font: inherit; width: 100%; box-sizing: border-box; }
button.ck-card { cursor: pointer; }
button.ck-card:focus-visible, .ck-btn:focus-visible, .ck-chip:focus-visible { outline: 2px solid #00d4ff; outline-offset: 2px; }
.ck-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.ck-name { font-weight: 600; }
.ck-sub { color: #8b90b3; font-size: 12px; }
.ck-num { font-variant-numeric: tabular-nums; }
.ck-pill { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid #3a3a70; color: #8b90b3; white-space: nowrap; }
.ck-state-active, .ck-state-deployed { color: #34d399; border-color: rgba(52,211,153,.55); }
.ck-state-barracked, .ck-state-off_duty, .ck-state-winding_down, .ck-state-cooldown { color: #f6c343; border-color: rgba(246,195,67,.55); }
.ck-state-decommissioned { color: #8b90b3; }
.ck-kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 8px 0; font-size: 13px; }
.ck-kv dt { color: #8b90b3; } .ck-kv dd { margin: 0; }
.ck-select { background: transparent; color: inherit; border: 1px solid #3a3a70; border-radius: 6px; padding: 6px 8px; font: inherit; }
.ck-pill-cloud { color: #ffb454; border-color: rgba(255,180,84,.55); }
.ck-job-completed { color: #34d399; border-color: rgba(52,211,153,.55); }
.ck-job-failed { color: #ef4444; border-color: rgba(239,68,68,.55); }
.ck-job-running, .ck-job-pending, .ck-job-pending_approval { color: #f6c343; border-color: rgba(246,195,67,.55); }
.ck-btn { display: inline-block; font: inherit; font-size: 12px; font-weight: 500; padding: 8px 12px; border-radius: 8px; border: 1px solid #3a3a70; color: #e6e8f0; background: #121230; cursor: pointer; }
.ck-primary { background: #00d4ff; color: #06202a; border-color: #00d4ff; font-weight: 600; }
.ck-danger { color: #ef4444; border-color: rgba(239,68,68,.55); }
.ck-small { padding: 5px 9px; font-size: 11px; }
.ck-block { display: block; width: 100%; text-align: center; }
.ck-btn[disabled] { opacity: .55; cursor: wait; }
.ck-form { display: flex; flex-direction: column; gap: 10px; }
.ck-form label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: #8b90b3; text-transform: uppercase; letter-spacing: .06em; }
.ck-form input, .ck-form select, .ck-form textarea { font: inherit; font-size: 13px; text-transform: none; letter-spacing: 0; color: #e6e8f0; background: #0a0a1a; border: 1px solid #2a2a55; border-radius: 8px; padding: 8px 10px; }
.ck-two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ck-sect { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: #8b90b3; margin-top: 6px; }
.ck-skills { display: flex; flex-wrap: wrap; gap: 6px; }
.ck-skill { display: inline-flex; gap: 6px; align-items: center; font-size: 11px; border: 1px solid #3a3a70; border-radius: 6px; padding: 3px 8px; }
.ck-skill button { font: inherit; background: none; border: 0; color: #8b90b3; cursor: pointer; padding: 0 2px; }
.ck-meter { height: 6px; background: #0a0a1a; border: 1px solid #2a2a55; border-radius: 999px; overflow: hidden; }
.ck-meter i { display: block; height: 100%; background: #00d4ff; }
.ck-code { background: #0a0a1a; border: 1px solid #2a2a55; border-radius: 8px; padding: 10px 12px; font-size: 11.5px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; color: #cfd6ff; margin: 0; }
.ck-work { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.ck-work td { padding: 5px 0; border-top: 1px solid #2a2a55; }
.ck-work td:last-child { text-align: right; color: #8b90b3; }
.ck-ok { color: #34d399; } .ck-bad { color: #ef4444; }
.ck-sheet { position: fixed; inset: 0; z-index: 6; background: #121230; overflow: auto; padding: 12px 14px 76px; display: none; flex-direction: column; gap: 10px; }
.ck-sheet.ck-show { display: flex; }
.ck-sheet-head { display: flex; align-items: center; gap: 10px; }
.ck-sheet-head h3 { margin: 0; flex: 1; font-size: 15px; }
.ck-back { font: inherit; background: none; border: 0; color: #8b90b3; cursor: pointer; padding: 4px 0; }
.ck-strip { display: none; }
.ck-tabs { position: fixed; left: 0; right: 0; bottom: 0; display: flex; border-top: 1px solid #2a2a55; background: #121230; z-index: 5; }
.ck-tabs button { flex: 1; font: inherit; font-size: 11px; color: #8b90b3; background: none; border: 0; padding: 10px 0 12px; position: relative; cursor: pointer; }
.ck-tabs button.ck-tab-on { color: #00d4ff; }
.ck-badge { position: absolute; top: 6px; right: 22%; background: #f6c343; color: #2a2000; font-size: 10px; font-weight: 600; border-radius: 999px; padding: 0 5px; }
.ck-toast { position: fixed; left: 50%; bottom: 64px; transform: translateX(-50%); background: #1a1a3a; border: 1px solid #3a3a70; border-radius: 8px; padding: 8px 12px; max-width: 92vw; z-index: 7; }
.ck-toast.ck-err { border-color: rgba(239,68,68,.7); }
.ck-empty { color: #8b90b3; font-size: 12px; padding: 8px 2px; }
@media (max-width: 480px) { .ck-two { grid-template-columns: 1fr; } }
@media (min-width: 768px) { .ck-nav { display: flex; } .ck-main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding-bottom: 76px; } #pane-crew, #pane-builder { display: flex; } }
@media (min-width: 1024px) {
  .ck-main { grid-template-columns: 320px 1fr 400px; padding-bottom: 20px; }
  #pane-crew, #pane-builder, #ck-agent { display: flex; }
  #ck-agent { position: static; padding: 0; background: transparent; }
  #ck-agent[hidden] { display: flex; }
  #ck-agent-close { display: none; }
  #pane-approvals { display: none !important; }
  .ck-tabs { display: none; }
  .ck-strip { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 8px 14px; background: rgba(246,195,67,.08); border-bottom: 1px solid rgba(246,195,67,.35); }
  .ck-strip .ck-card { width: auto; display: flex; gap: 8px; align-items: center; padding: 5px 10px; }
  .ck-strip:empty { display: none; }
}
```

(Desktop shows Crew · Agent · Builder side by side and turns Approvals into the strip; the `#ck-agent[hidden]` override keeps the centre pane in the grid before an agent is chosen — the JS fills it with an empty-state message.)

- [ ] **Step 5: Run to verify it passes**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py tests/test_cockpit_routes.py 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add /mnt/archie_brain/archie-comms/templates/cockpit.html /mnt/archie_brain/archie-comms/static/css/cockpit.css /mnt/archie_brain/archie-comms/tests/test_cockpit_page.py
git commit -m "feat(comms): cockpit template + stylesheet — phone stacked/tabs, desktop three panes + approvals strip (#6653 Phase 4)"
```

---

### Task 10: `cockpit.js` — data, actions, polling

**Files:**
- Create: `archie-comms/static/js/cockpit.js`
- Test: `archie-comms/tests/test_cockpit_page.py` (append the JS scans)

**Interfaces:**
- Consumes: the ids from Task 9; routes from Task 8.

- [ ] **Step 1: Write the failing tests** — append to `archie-comms/tests/test_cockpit_page.py`:

```python
JS = (ROOT / "static" / "js" / "cockpit.js").read_text(encoding="utf-8")


def test_js_never_renders_server_text_with_innerhtml():
    assert ".innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS


def test_js_binds_the_cockpit_routes_and_polls_every_5s():
    for route in ("/api/cockpit/agents", "/api/cockpit/agents/create", "/api/cockpit/build/providers", "/api/cockpit/build/run", "/api/cockpit/build/runs", "/api/approvals/pending"):
        assert route in JS, route
    assert "POLL_MS = 5000" in JS


def test_js_requires_the_typed_name_before_decommission():
    assert "decommissioned" in JS
    assert "type the agent's name" in JS.lower()  # the confirm prompt (double-quoted in the JS so the apostrophe is literal)
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py 2>&1 | tail -3`
Expected: the JS tests error (`FileNotFoundError` on `cockpit.js`).

- [ ] **Step 3: Write the script** — create `archie-comms/static/js/cockpit.js`:

```javascript
/* Cockpit (#6653 Phase 4): Crew + Code Builder + Approvals. Vanilla JS. Every piece of
   server text is rendered with textContent — never innerHTML. All calls go to comms'
   /api/cockpit/* (session) and /api/approvals/* (existing); comms proxies to the hub. */
(function () {
  'use strict';
  const POLL_MS = 5000;
  const ROSTER_PAGE = 50;
  const $ = (id) => document.getElementById(id);
  const mk = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = String(text); return el; };

  // ---- transport -------------------------------------------------------------------
  async function api(path, opts) {
    const o = Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {});
    if (o.body && typeof o.body !== 'string') o.body = JSON.stringify(o.body);
    let r;
    try { r = await fetch(path, o); } catch (_) { return { ok: false, status: 0, data: { error: 'hub unreachable — retry' } }; }
    let data = {};
    try { data = await r.json(); } catch (_) { data = { error: 'HTTP ' + r.status }; }
    return { ok: r.ok, status: r.status, data };
  }
  let toastTimer = null;
  function toast(msg, isErr) {
    const t = $('ck-toast'); t.textContent = msg; t.classList.toggle('ck-err', !!isErr); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, isErr ? 6000 : 3000);
  }
  const errText = (res) => (res.data && (res.data.error || res.data.status)) || ('HTTP ' + res.status);

  // ---- panes / tabs ----------------------------------------------------------------
  const PANES = { crew: 'pane-crew', builder: 'pane-builder', approvals: 'pane-approvals' };
  function showPane(name) {
    Object.keys(PANES).forEach((k) => { $(PANES[k]).classList.toggle('ck-show', k === name); });
    document.querySelectorAll('#ck-tabs button').forEach((b) => b.classList.toggle('ck-tab-on', b.dataset.pane === name));
    if (name !== 'crew') { $('ck-agent').classList.remove('ck-show'); $('ck-hire').hidden = true; }
  }
  document.querySelectorAll('#ck-tabs button').forEach((b) => b.addEventListener('click', () => { location.hash = b.dataset.pane; showPane(b.dataset.pane); }));
  function paneFromHash() { const h = (location.hash || '#crew').slice(1); return PANES[h] ? h : 'crew'; }
  window.addEventListener('hashchange', () => showPane(paneFromHash()));

  // ---- Crew: roster ----------------------------------------------------------------
  const roster = { q: '', department: '', state: '', worker_type: '', offset: 0, total: 0, facets: { departments: {}, states: {} } };
  let searchTimer = null;
  $('ck-search').addEventListener('input', (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { roster.q = e.target.value.trim(); roster.offset = 0; loadRoster(true); }, 300); });
  $('ck-more').addEventListener('click', () => { roster.offset += ROSTER_PAGE; loadRoster(false); });

  function pill(state) { const p = mk('span', 'ck-pill ck-state-' + String(state || 'unknown').replace(/[^a-z_]/gi, ''), state || '—'); return p; }

  function renderChips() {
    const box = $('ck-chips'); box.textContent = '';
    const chip = (label, key, val) => {
      const b = mk('button', 'ck-chip', label); b.type = 'button';
      b.setAttribute('aria-pressed', String(roster[key] === val));
      b.addEventListener('click', () => { roster[key] = roster[key] === val ? '' : val; roster.offset = 0; loadRoster(true); });
      return b;
    };
    Object.keys(roster.facets.states).sort().forEach((s) => box.appendChild(chip(s + ' · ' + roster.facets.states[s], 'state', s)));
    Object.keys(roster.facets.departments).sort().forEach((d) => box.appendChild(chip(d, 'department', d)));
    ['ai', 'internal', 'contract'].forEach((w) => box.appendChild(chip(w, 'worker_type', w)));
  }

  async function loadRoster(reset) {
    const qs = new URLSearchParams({ q: roster.q, department: roster.department, state: roster.state, worker_type: roster.worker_type, limit: String(ROSTER_PAGE), offset: String(roster.offset) });
    const res = await api('/api/cockpit/agents?' + qs.toString());
    const list = $('ck-roster');
    if (!res.ok) { toast('Crew: ' + errText(res), true); return; }
    if (reset) list.textContent = '';
    roster.total = res.data.total || 0; roster.facets = res.data.facets || roster.facets;
    $('ck-total').textContent = '· ' + roster.total;
    renderChips();
    (res.data.agents || []).forEach((a) => {
      const card = mk('button', 'ck-card'); card.type = 'button'; card.setAttribute('role', 'listitem');
      const row = mk('div', 'ck-row'); row.appendChild(mk('span', 'ck-name', a.display_name || a.name)); row.appendChild(pill(a.shift_state));
      card.appendChild(row);
      card.appendChild(mk('div', 'ck-sub', [a.department || '—', a.model || '—', a.success_rate != null ? Math.round(a.success_rate) + '%' : ''].filter(Boolean).join(' · ')));
      card.addEventListener('click', () => openAgent(a.id));
      list.appendChild(card);
    });
    if (!list.childElementCount) list.appendChild(mk('div', 'ck-empty', 'No agents match.'));
    $('ck-more').hidden = roster.offset + ROSTER_PAGE >= roster.total;
    const dept = $('ck-hire-dept'); dept.textContent = '';
    Object.keys(roster.facets.departments).sort().forEach((d) => { const o = mk('option', null, d); o.value = d; dept.appendChild(o); });
  }

  // ---- Crew: agent card ------------------------------------------------------------
  let currentAgent = null;
  async function openAgent(id) {
    const res = await api('/api/cockpit/agents/' + id);
    if (!res.ok) { toast('Agent: ' + errText(res), true); return; }
    currentAgent = res.data; renderAgent(res.data); $('ck-agent').hidden = false; $('ck-agent').classList.add('ck-show');
  }
  $('ck-agent-close').addEventListener('click', () => { $('ck-agent').classList.remove('ck-show'); });

  function kv(dl, k, v) { dl.appendChild(mk('dt', null, k)); dl.appendChild(mk('dd', 'ck-num', v == null || v === '' ? '—' : v)); }

  function renderAgent(d) {
    const a = d.agent || {}; const body = $('ck-agent-body'); body.textContent = '';
    $('ck-agent-name').textContent = a.display_name || a.name || ('#' + a.id);
    const st = $('ck-agent-state'); st.className = 'ck-pill ck-state-' + String(a.shift_state || '').replace(/[^a-z_]/gi, ''); st.textContent = a.shift_state || '—';
    body.appendChild(mk('div', 'ck-sub', [a.title, a.department, a.model].filter(Boolean).join(' · ')));
    const perf = mk('dl', 'ck-kv'); kv(perf, 'success', a.success_rate != null ? Math.round(a.success_rate) + '%' : null); kv(perf, 'score', a.performance_score); kv(perf, 'tasks', a.total_tasks_completed); kv(perf, 'last used', a.last_used ? new Date(a.last_used).toLocaleString() : null); body.appendChild(perf);

    // Skills
    body.appendChild(mk('div', 'ck-sect', 'Skills'));
    const skills = mk('div', 'ck-skills');
    (d.skills || []).forEach((s) => {
      const chip = mk('span', 'ck-skill'); chip.appendChild(mk('span', null, s.skill_name)); chip.appendChild(mk('em', null, 'Lv' + s.proficiency_level));
      const x = mk('button', null, '×'); x.type = 'button'; x.title = 'Remove ' + s.skill_name;
      x.addEventListener('click', () => act(a.id, 'skills/remove', { skill_name: s.skill_name }, 'Removed ' + s.skill_name));
      chip.appendChild(x); skills.appendChild(chip);
    });
    const add = mk('button', 'ck-skill', '+ add'); add.type = 'button'; add.style.color = '#00d4ff';
    add.addEventListener('click', () => {
      const name = window.prompt('Skill name (e.g. code_review)'); if (!name) return;
      const level = parseInt(window.prompt('Level 1–5', '3') || '3', 10); const category = window.prompt('Category', 'general') || 'general';
      act(a.id, 'skills/add', { skill_name: name.trim(), level, category }, 'Added ' + name.trim());
    });
    skills.appendChild(add); body.appendChild(skills);

    // Budget
    body.appendChild(mk('div', 'ck-sect', 'Budget'));
    const b = d.budget; const brow = mk('div', 'ck-row');
    brow.appendChild(mk('span', 'ck-num', b ? (fmtK(b.tokens_used_today) + ' / ' + fmtK(b.token_limit_per_day) + ' tokens today') : 'no budget row yet'));
    const setBtn = mk('button', 'ck-btn ck-small', 'Set limit'); setBtn.type = 'button';
    setBtn.addEventListener('click', () => { const v = window.prompt('Daily token limit (floor 50,000)', b ? String(b.token_limit_per_day) : '250000'); if (!v) return; act(a.id, 'budget', { token_limit_per_day: parseInt(v, 10) }, 'Budget set'); });
    brow.appendChild(setBtn); body.appendChild(brow);
    if (b) { const m = mk('div', 'ck-meter'); const i = mk('i'); i.style.width = Math.min(100, Math.round(100 * (b.tokens_used_today || 0) / Math.max(1, b.token_limit_per_day || 1))) + '%'; m.appendChild(i); body.appendChild(m); body.appendChild(mk('div', 'ck-sub ck-num', 'queue ' + (b.current_task_count ?? '—') + ' / ' + (b.task_queue_limit ?? '—'))); }

    // Actions
    body.appendChild(mk('div', 'ck-sect', 'Actions'));
    const dept = mk('select', 'ck-select'); Object.keys(roster.facets.departments).sort().forEach((dn) => { const o = mk('option', null, dn); o.value = dn; if (dn === a.department) o.selected = true; dept.appendChild(o); });
    const deptBtn = mk('button', 'ck-btn ck-small', 'Assign'); deptBtn.type = 'button'; deptBtn.addEventListener('click', () => act(a.id, 'assign', { department: dept.value }, 'Assigned to ' + dept.value));
    const drow = mk('div', 'ck-row'); drow.appendChild(dept); drow.appendChild(deptBtn); body.appendChild(drow);
    const states = ['active', 'deployed', 'barracked', 'off_duty', 'winding_down', 'cooldown'];
    const stSel = mk('select', 'ck-select'); states.forEach((s) => { const o = mk('option', null, s); o.value = s; if (s === a.shift_state) o.selected = true; stSel.appendChild(o); });
    const stBtn = mk('button', 'ck-btn ck-small', 'Set state'); stBtn.type = 'button';
    stBtn.addEventListener('click', () => { const reason = window.prompt('Reason', 'cockpit') || 'cockpit'; act(a.id, 'shift-state', { state: stSel.value, reason }, 'State → ' + stSel.value); });
    const srow = mk('div', 'ck-row'); srow.appendChild(stSel); srow.appendChild(stBtn); body.appendChild(srow);
    const dec = mk('button', 'ck-btn ck-danger ck-block', "Decommission — type the agent's name to confirm"); dec.type = 'button';
    dec.addEventListener('click', () => {
      const typed = window.prompt("This is terminal. Type the agent's name exactly to confirm:");
      if (typed !== (a.display_name || a.name)) { toast('Name did not match — nothing changed', true); return; }
      act(a.id, 'shift-state', { state: 'decommissioned', reason: 'cockpit decommission' }, 'Decommissioned');
    });
    body.appendChild(dec);

    // Recent work
    body.appendChild(mk('div', 'ck-sect', 'Recent work'));
    const tbl = mk('table', 'ck-work');
    (d.recent_work || []).forEach((w) => { const tr = mk('tr'); tr.appendChild(mk('td', null, [w.capability, w.model_used, w.provider].filter(Boolean).join(' · '))); const td = mk('td'); td.appendChild(mk('span', w.success ? 'ck-ok' : 'ck-bad', w.success ? '✓' : '✗')); td.appendChild(document.createTextNode(' ' + (w.created_at ? new Date(w.created_at).toLocaleTimeString() : ''))); tr.appendChild(td); tbl.appendChild(tr); });
    if (!tbl.childElementCount) tbl.appendChild(mk('tr')).appendChild(mk('td', 'ck-empty', 'No dispatches yet'));
    body.appendChild(tbl);
  }
  const fmtK = (n) => n == null ? '—' : (n >= 1000 ? Math.round(n / 1000) + 'k' : String(n));

  async function act(id, action, body, okMsg) {
    const res = await api('/api/cockpit/agents/' + id + '/' + action, { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast(okMsg); openAgent(id); loadRoster(true);
  }

  // ---- Crew: hire ------------------------------------------------------------------
  $('ck-hire-open').addEventListener('click', () => { $('ck-hire').hidden = false; $('ck-hire').classList.add('ck-show'); });
  document.querySelectorAll('[data-close="ck-hire"]').forEach((b) => b.addEventListener('click', () => { $('ck-hire').classList.remove('ck-show'); $('ck-hire').hidden = true; }));
  $('ck-hire').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target); const body = {};
    ['name', 'display_name', 'department', 'model', 'capability', 'reason'].forEach((k) => { body[k] = String(f.get(k) || '').trim(); });
    const sk = String(f.get('suggested_skills') || '').split(',').map((s) => s.trim()).filter(Boolean); if (sk.length) body.suggested_skills = sk;
    const res = await api('/api/cockpit/agents/create', { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast('Hire proposed — approval #' + (res.data.approval_id || '?') + ' is waiting in Approvals and Telegram');
    $('ck-hire').classList.remove('ck-show'); $('ck-hire').hidden = true; e.target.reset(); loadApprovals();
  });

  // ---- Builder ---------------------------------------------------------------------
  let providers = [];
  async function loadProviders() {
    const res = await api('/api/cockpit/build/providers');
    if (!res.ok) { toast('Providers: ' + errText(res), true); return; }
    providers = res.data.providers || [];
    const p = $('ck-provider'); p.textContent = '';
    providers.forEach((pr) => { const o = mk('option', null, pr.display_name || pr.provider_key); o.value = pr.provider_key; p.appendChild(o); });
    fillModels();
  }
  function fillModels() {
    const pr = providers.find((x) => x.provider_key === $('ck-provider').value) || providers[0]; const m = $('ck-model'); m.textContent = '';
    if (!pr) return;
    (pr.models || []).forEach((name) => { const o = mk('option', null, name); o.value = name; if (name === pr.default_model) o.selected = true; m.appendChild(o); });
  }
  $('ck-provider').addEventListener('change', fillModels);
  $('ck-compose').addEventListener('submit', async (e) => {
    e.preventDefault(); const btn = $('ck-run'); btn.disabled = true;
    const body = { prompt: $('ck-prompt').value.trim(), provider: $('ck-provider').value, model: $('ck-model').value };
    const sys = $('ck-system').value.trim(); if (sys) body.system_prompt = sys;
    const res = await api('/api/cockpit/build/run', { method: 'POST', body }); btn.disabled = false;
    if (res.status === 409 && res.data.status === 'approval_unavailable') { toast('Approve or deny the pending coding job first', true); return; }
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast('Job #' + res.data.job_id + ' waits for your approval — Approvals tab or Telegram');
    loadJobs(); loadApprovals();
  });
  $('ck-jobs-refresh').addEventListener('click', loadJobs);

  const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
  let jobs = []; let pollTimer = null; let expanded = null;
  async function loadJobs() {
    const res = await api('/api/cockpit/build/runs?limit=20');
    if (!res.ok) { toast('Jobs: ' + errText(res), true); return; }
    jobs = res.data.runs || []; renderJobs(); schedulePoll();
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (jobs.some((j) => !TERMINAL.has(j.status))) pollTimer = setTimeout(loadJobs, POLL_MS);
  }
  function renderJobs() {
    const list = $('ck-jobs'); list.textContent = '';
    if (!jobs.length) { list.appendChild(mk('div', 'ck-empty', 'No coding jobs yet.')); return; }
    jobs.forEach((j) => {
      const card = mk('div', 'ck-card'); card.setAttribute('role', 'listitem');
      const row = mk('div', 'ck-row'); row.appendChild(mk('span', 'ck-name ck-num', '#' + j.job_id));
      const label = j.status === 'pending' ? 'pending approval' : j.status; row.appendChild(mk('span', 'ck-pill ck-job-' + String(j.status).replace(/[^a-z_]/gi, ''), label));
      card.appendChild(row);
      const r = j.result || {};
      card.appendChild(mk('div', 'ck-sub ck-num', [j.model ? 'requested ' + j.model : '', r.model_used ? 'served ' + r.model_used + (r.served_model_resolved ? ' ✓' : ' (unresolved)') : '', r.prompt_tokens != null ? r.prompt_tokens + ' → ' + (r.completion_tokens ?? '?') + ' tok' : ''].filter(Boolean).join(' · ')));
      if (j.error || r.error) card.appendChild(mk('div', 'ck-sub ck-bad', j.error || r.error));
      if (j.status === 'pending') card.appendChild(mk('div', 'ck-sub', 'approve it in Approvals or Telegram'));
      const open = mk('button', 'ck-btn ck-small', expanded === j.job_id ? 'Hide' : 'Open'); open.type = 'button';
      open.addEventListener('click', () => { expanded = expanded === j.job_id ? null : j.job_id; renderJobs(); if (expanded) showJobDetail(j.job_id, card); });
      card.appendChild(open);
      list.appendChild(card);
      if (expanded === j.job_id) showJobDetail(j.job_id, card);
    });
  }
  async function showJobDetail(id, card) {
    const res = await api('/api/cockpit/build/' + id);
    if (!res.ok) { toast('Job: ' + errText(res), true); return; }
    const r = res.data.result || {}; let pre = card.querySelector('pre');
    if (!pre) { pre = mk('pre', 'ck-code'); card.appendChild(pre); const cp = mk('button', 'ck-btn ck-small', 'Copy'); cp.type = 'button'; cp.addEventListener('click', () => { navigator.clipboard && navigator.clipboard.writeText(pre.textContent).then(() => toast('Copied')); }); card.appendChild(cp); }
    pre.textContent = r.response || (res.data.status === 'pending' ? 'Waiting for approval…' : (res.data.status === 'running' ? 'Running…' : (res.data.error || 'No output')));
    if (r.routing_decision) card.appendChild(mk('div', 'ck-sub', r.routing_decision));
  }

  // ---- Approvals (tab on phone, strip on desktop) -----------------------------------
  async function loadApprovals() {
    const res = await api('/api/approvals/pending');
    const list = $('ck-approvals'); const strip = $('ck-strip'); list.textContent = ''; strip.textContent = '';
    if (!res.ok) { list.appendChild(mk('div', 'ck-empty', 'Approvals: ' + errText(res))); return; }
    const items = res.data.approvals || [];
    $('ck-approvals-count').textContent = '· ' + items.length; const badge = $('ck-tab-badge'); badge.textContent = String(items.length); badge.hidden = !items.length;
    if (!items.length) list.appendChild(mk('div', 'ck-empty', 'No pending approvals'));
    items.forEach((a) => { list.appendChild(approvalCard(a, false)); strip.appendChild(approvalCard(a, true)); });
  }
  function approvalCard(a, compact) {
    const card = mk('div', 'ck-card'); card.setAttribute('role', 'listitem');
    const title = a.display_name || a.action_type || a.id;
    card.appendChild(mk(compact ? 'span' : 'div', compact ? 'ck-sub' : 'ck-name', title));
    if (!compact && a.reason) card.appendChild(mk('div', 'ck-sub', a.reason));
    const row = mk('div', 'ck-row');
    const ok = mk('button', 'ck-btn ck-primary ck-small', 'Approve'); ok.type = 'button'; ok.addEventListener('click', () => decide(a.id, 'approve', card));
    const no = mk('button', 'ck-btn ck-small', 'Deny'); no.type = 'button'; no.addEventListener('click', () => decide(a.id, 'deny', card));
    row.appendChild(ok); row.appendChild(no); card.appendChild(row);
    return card;
  }
  async function decide(id, verb, card) {
    card.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    const res = await api('/api/approvals/' + encodeURIComponent(id) + '/' + verb, { method: 'POST', body: {} });
    if (!res.ok || !res.data.ok) { card.querySelectorAll('button').forEach((b) => { b.disabled = false; }); toast('Approval: ' + errText(res), true); return; }
    toast(verb === 'approve' ? 'Approved' : 'Denied'); loadApprovals(); loadJobs(); loadRoster(true);
  }

  // ---- boot ------------------------------------------------------------------------
  showPane(paneFromHash());
  $('ck-agent-body').appendChild(mk('div', 'ck-empty', 'Pick an agent from the crew list.'));
  loadRoster(true); loadProviders(); loadJobs(); loadApprovals();
  setInterval(loadApprovals, 30000);
})();
```

- [ ] **Step 4: Run to verify it passes** (+ whole comms suite)

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh 2>&1 | tail -3`
Expected: all pass (the innerHTML scan, the route list, `POLL_MS = 5000`, the typed-name check).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/archie-comms/static/js/cockpit.js /mnt/archie_brain/archie-comms/tests/test_cockpit_page.py
git commit -m "feat(comms): cockpit.js — roster/agent card/hire, code builder with 5 s polling, approvals tab+strip; textContent only (#6653 Phase 4)"
```

---

### Task 11: Header shortcut on the chat page + local smoke build

**Files:**
- Modify: `archie-comms/templates/chat.html:17-27` (`header_shortcuts`)
- Test: `archie-comms/tests/test_cockpit_page.py` (append)

- [ ] **Step 1: Write the failing test** — append:

```python
def test_chat_header_links_to_the_cockpit():
    chat = (ROOT / "templates" / "chat.html").read_text(encoding="utf-8")
    assert "/cockpit" in chat
```

- [ ] **Step 2: Run to verify it fails** — `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py -k header 2>&1 | tail -3` → 1 failed.

- [ ] **Step 3: Add the shortcut** — read `archie-comms/templates/lcars-header.html` to confirm the tuple shape it iterates for `header_shortcuts` (it renders each entry as a link; if the include expects `(url, label, icon)` use that order; if it expects dicts, mirror one existing example from any other template that sets `header_shortcuts`). Then in `chat.html` change `{% set header_shortcuts = [] %}` to `{% set header_shortcuts = [("/cockpit#crew", "Cockpit", "layout-grid")] %}` (or the dict form the include expects). The rendered result is checked by the smoke build in Step 5.

- [ ] **Step 4: Run to verify it passes** — `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh 2>&1 | tail -3` → all pass.

- [ ] **Step 5: Smoke build on a throwaway image (never the live container while on a feature branch)** — an import-level check; the app needs DB env to serve, so do not start gunicorn:

```bash
cd /mnt/archie_brain/archie-comms && docker build -q -t archie_comms_smoke:phase4 . && docker run --rm -e SECRET_KEY=x -e PLATFORM_URL=http://archie_platform:3000 -e INTERNAL_API_KEY=x archie_comms_smoke:phase4 python3 -c "
import app_comms
rules = sorted(r.rule for r in app_comms.app.url_map.iter_rules() if 'cockpit' in r.rule)
print(len(rules), rules[:3])
with app_comms.app.test_request_context('/chat'):
    from flask import render_template
    print('/cockpit' in render_template('chat.html'))
"
docker rmi -f archie_comms_smoke:phase4
```
Expected: `13` cockpit rules (1 page + 12 API routes: `agents`, `agents/<id>`, `agents/create`, the 5 agent-action rules registered by the `add_url_rule` loop over `cp.ACTIONS`, `build/providers`, `build/run`, `build/runs`, `build/<id>`) and `True` (the chat header carries the shortcut). If `import app_comms` needs a DB at import time, report the traceback — do not add env to work around it.

- [ ] **Step 6: Commit**

```bash
git add /mnt/archie_brain/archie-comms/templates/chat.html /mnt/archie_brain/archie-comms/tests/test_cockpit_page.py
git commit -m "feat(comms): header shortcut to the cockpit (#6653 Phase 4)"
```

---

### Task 12: Comms PR — review, merge, rebuild, live acceptance at 390 px and 1280 px, Dev HQ

**Files:** none new.

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/phase4-cockpit-comms
gh pr create --title "feat(phase4): the cockpit — Crew + Code Builder at /cockpit (archie-comms) (#6653)" --body "$(cat <<'EOF'
## Summary
- New `/cockpit` page (Blueprint `cockpit_routes.py`): Crew (roster, filters, agent card with skills/budget/assign/shift-state/typed-name decommission, propose-a-hire → Tier-2) and Code Builder (provider/model, prompt, run → approval, 5 s polling, answer with Copy). Approvals as a tab on phone and a strip on desktop.
- `services/cockpit_proxy.py`: pass-through hub calls, fail-closed; hub error text shown verbatim; no optimistic UI.
- Removed comms' direct-SQL roster peek. Host-venv test runner (`scripts/run_tests.sh`).

## Test Plan
- [x] tests/test_cockpit_proxy.py (7) · tests/test_cockpit_routes.py (7) · tests/test_cockpit_page.py (8) · whole comms suite green via scripts/run_tests.sh
- [ ] live acceptance at 390 px and 1280 px (below) after `docker compose up -d --build archie_comms`

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6
EOF
)"
```

- [ ] **Step 2: Register + F.O.R.G.E. review + merge on a clean APPROVE** — same commands as Task 5 Step 2 with the new PR number; coverage demotion → independent full read of the dropped files (the JS and template are long; expect this).

- [ ] **Step 3: Rebuild comms from `main`**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main && docker compose up -d --build archie_comms && docker compose ps archie_comms
```
Expected: `archie_comms` healthy within ~30 s.

- [ ] **Step 4: Live acceptance (hub Playwright, log in as Claude's own platform user per `reference_claude-platform-login.md`; run the SAME script at viewport 390×844 and 1280×800; screenshots to the job tmp dir)**

1. `https://archie.kytranempowerment.com/cockpit` (or `http://192.168.1.200:3002/cockpit` on the LAN) → redirected to login → after login the Crew pane renders with `total > 0` and chips.
2. Search `F.O.R.G.E.` → open the card → **add** skill `cockpit_probe` (Lv2, general) → DB: `SELECT proficiency_level FROM agent_skills WHERE agent_id=<id> AND skill_name='cockpit_probe'` → 2 → **remove** it → row gone.
3. **Set limit** to the current value + 1000 → DB `agent_budgets.token_limit_per_day` reflects it → set it back.
4. **Assign** to `Documentation & Knowledge` → DB `agents.department` → assign back to `Engineering & Technology`.
5. **Propose a hire** (`name` `C.K.P.T.`, model `qwen2.5:7b`, capability `general`, reason `phase 4 acceptance`) → approval appears in the strip/tab and Telegram → **Deny** it (no new agent is created by the acceptance).
6. Builder: OmniRoute · `oc/big-pickle` · prompt `Write a Python is_palindrome(s) with a docstring. Code only.` → Run → job `pending approval` → **Approve** in the strip/tab → within ≤ 90 s the job reads `completed`, served `big-pickle ✓`, tokens shown, the answer opens with Copy → DB `task_execution_log` newest `module_source='cloud_code_lane'` row: `provider='omniroute'`, `request_metadata->>'served_model_resolved'='true'`.
7. `escalation_mode` still `local_only` (`SELECT value FROM platform_settings WHERE key='escalation_mode'`).
8. Screenshots: `cockpit-390-crew.png`, `cockpit-390-agent.png`, `cockpit-390-builder.png`, `cockpit-1280.png`.

- [ ] **Step 5: Dev HQ + handoff**

- `mcp__archie__add_work_note(note="Phase 4 first slice SHIPPED: hub PR #<n1> (agents:read + 4 reads), comms PR #<n2> (/cockpit). Acceptance at 390/1280 passed: skill add/remove + budget + assign round-trips, hire → Tier-2 (denied), builder job → approved → completed served=big-pickle resolved=true; escalation_mode=local_only.", note_type="general")` on #6653.
- `mcp__archie__log_decision(title="Phase 4a: the cockpit lives at /cockpit in archie-comms", decision="Separate page (Blueprint) reusing comms auth/proxies/approvals; one new hub scope agents:read (comms only) with roster/agent/cloud-code reads; the builder shows results only (apply-via-engine deferred to 4b); comms holds no agent SQL.", context="Owner decisions 2026-09-10: Crew+Contractors first; both layouts; show-the-result; approach B.", project_id=343, task_id=6653)`.
- `mcp__archie__create_task` ×2 (project 343): "Phase 4b: tasks & projects panes (tasks:read/write internal APIs)"; "Phase 4b: Apply-via-engine on a builder result (engine apply_edit + approval → branch/PR)".
- Rewrite `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`: Phase 4a done; next Phase 4b / Phase 5 TTY lanes; 3b still HOLD on #6675.

---

## Deferred (explicitly not in this plan)
- Tasks & projects panes; apply-via-engine; job history search — Phase 4b.
- TTY lanes from the cockpit — Phase 5.
- Paid keys in OmniRoute — HOLD until #6675 (ADR-041).
- A shared fetch helper in `archie-chat.js` (the chat page keeps its ad-hoc `fetch` calls; `cockpit.js` has its own `api()`).
