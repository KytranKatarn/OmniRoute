# Phase 4b — Work pane + Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Work pane (projects + tasks, triage + delegate) to the cockpit and an Apply action that turns a Code Builder result into a branch + PR through a Tier-2 approval.

**Architecture:** Same shape as Phase 4a. The hub gets two new scopes (`tasks:read`, `tasks:write`, comms-only), a single-writer `services/task_service.py`, eight `/api/internal/{projects,tasks*}` routes, an optional `target_path` on the cloud-code run route, a `POST …/run/<id>/apply` route, a `cloud_code_apply` approval type whose executor composes the existing `github_service` branch/push/PR primitives, and the `cockpit/` prefix on the human-merge gate. archie-comms stays a session-gated pass-through: six new proxy routes, a Work pane + task sheet + `+ Task` form, a `target file` input, and an `Apply` button.

**Tech Stack:** Flask + psycopg2 (hub, bind-mounted `platform_v2/` → `/app`), Flask (comms, image-baked, `COPY . .`), vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-phase4b-work-pane-and-apply-design.md`

## Global Constraints

- Two PRs, two branches cut from `main`: `feat/phase4b-hub` (Tasks 1–8) then `feat/phase4b-comms` (Tasks 9–13). Never commit to `main`. Commit trailer exactly `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` then `Claude-Session: https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6`. Absolute paths in `git add`. Never `--no-verify`. Hooks (black etc.) may reformat: re-stage and commit again.
- Merge only on a clean F.O.R.G.E. APPROVE, never stale, never on a MISSING verdict; a coverage-only demotion is discharged by an independent full read of the dropped files, then `merge_pr(n, method='squash', human_override=True)`. Tier-3 PRs pause for the owner.
- **The live platform serves whichever branch is checked out in `/mnt/archie_brain`** (bind mount). Never `docker compose up`/`build` while a feature branch touching `platform_v2` is checked out. Hub deploy = `git checkout main && git pull --ff-only origin main && docker compose restart archie_platform archie_scheduler`. Comms deploy = from `main` only, `docker compose up -d --build archie_comms`.
- Hub tests run in-container: `docker exec -i archie_platform python3 -m pytest /app/tests/<file> -q -p no:cacheprovider`. pytest forces the empty `archie_test` DB: every DB-backed test SEEDS its own rows on an autocommit connection, asserts `total > 0`, and cleans up. Comms tests run on the HOST: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh [args]`.
- Comms holds no SQL, no GitHub token, no repo path. All hub errors pass through verbatim. Every rendered API string uses `textContent`. `escalation_mode` stays `local_only`. Only `archie-platform` is a valid Apply target repo.
- Spec naming note (deviation, deliberate): the cloud-code worker dispatches `metadata.prompt`. So with a target file, `prompt` holds the ASSEMBLED prompt (what was sent) and `prompt_original` holds the owner's text — the reverse of the spec's `prompt`/`prompt_effective` wording — so the worker stays untouched.
- Never `docker compose restart` after an env change (use `up -d --no-deps`); no env changes are expected in this plan.

---

## File structure

**Hub (`platform_v2/`)**
- `services/internal_auth.py` — +2 scopes (Task 1)
- `services/task_service.py` — NEW, single writer for projects/tasks reads + writes (Tasks 2–3)
- `app.py` — +8 routes after the cloud-code providers route; `target_path` on the run route; `/apply` route; extra keys on status + runs (Tasks 4, 6)
- `services/cloud_code_apply.py` — NEW, path policy, fence stripper, prompt builder, approval request, executor (Tasks 5–7)
- `tools/repair_bay/services/github_service.py` — +`get_file_at_ref` (Task 6)
- `ai_bridge/agent_loop.py` — +`cloud_code_apply` executor branch (Task 7)
- `tools/repair_bay/services/pr_review_service.py` — `cockpit/` + `[cockpit]` on the human-merge gate (Task 7)
- tests: `tests/test_internal_auth_scopes.py` (+), `tests/test_task_service.py` (NEW), `tests/test_cockpit_task_routes.py` (NEW), `tests/test_cloud_code_apply.py` (NEW), `tests/test_cloud_code_run_target.py` (NEW), `tests/test_forge_automerge_gate.py` (+)

**Comms (`archie-comms/`)**
- `services/cockpit_proxy.py` — +6 functions (Task 9)
- `cockpit_routes.py` — +6 rules (Task 10)
- `templates/cockpit.html`, `static/css/cockpit.css` — Work pane, switch, task sheet, `+ Task` form, target file, 4th tab (Task 11)
- `static/js/cockpit.js` — Work pane logic, task sheet, Apply (Task 12)
- tests: `tests/test_cockpit_proxy.py` (+), `tests/test_cockpit_routes.py` (+), `tests/test_cockpit_page.py` (+)

---

### Task 1: scopes `tasks:read` + `tasks:write`, comms-only

**Files:**
- Modify: `platform_v2/services/internal_auth.py:90` (SCOPES) and `:107` (CALLER_SCOPES["archie_comms"])
- Test: `platform_v2/tests/test_internal_auth_scopes.py`

**Interfaces:**
- Produces: the strings `"tasks:read"` and `"tasks:write"` accepted by `require_internal_scope(...)`.

- [ ] **Step 1: Write the failing test** — append to `platform_v2/tests/test_internal_auth_scopes.py`:

```python
def test_tasks_scopes_exist_and_are_granted_to_comms_only():
    for scope in ("tasks:read", "tasks:write"):
        assert scope in ia.SCOPES, scope
        holders = [c for c, s in ia.CALLER_SCOPES.items() if scope in s]
        assert holders == ["archie_comms"], (scope, holders)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_internal_auth_scopes.py -q -p no:cacheprovider -k tasks_scopes 2>&1 | tail -3`
Expected: `1 failed` — `assert 'tasks:read' in ...`.

- [ ] **Step 3: Implement** — in `SCOPES` (after the `"agents:read"` line) add:

```python
        "tasks:read",  # cockpit Work pane: projects/tasks READS — comms only (#6679 Phase 4b)
        "tasks:write",  # cockpit Work pane: create/status/priority/note/delegate — comms only (#6679 Phase 4b)
```

and in `CALLER_SCOPES["archie_comms"]` (after `"agents:read",`) add:

```python
            "tasks:read",
            "tasks:write",
```

- [ ] **Step 4: Run the whole scope suite**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_internal_auth_scopes.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass (`test_every_scope_is_granted_and_nobody_holds_everything` still holds — both new scopes have a holder and comms still lacks `engine`, `sessions`, `fleet`, `notify`, `compliance`, `repair:write`, `approvals:request`).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/internal_auth.py /mnt/archie_brain/platform_v2/tests/test_internal_auth_scopes.py
git commit -m "feat(auth): tasks:read + tasks:write scopes for the cockpit Work pane, comms only (#6679 Phase 4b)"
```

---

### Task 2: `task_service` reads — projects, tasks, one task, capabilities

**Files:**
- Create: `platform_v2/services/task_service.py`
- Test: `platform_v2/tests/test_task_service.py`

**Interfaces:**
- Produces:
  - `clamp_page(limit, offset) -> (int, int)` (limit 1–200 default 50, offset ≥ 0)
  - `list_projects(status=None, limit=50, offset=0) -> (rows: list[dict], total: int)`; each row has `id, name, slug, status, priority, project_type, target_date, open_tasks, total_tasks`
  - `list_tasks(q=None, project_id=None, status=None, min_priority=None, limit=50, offset=0) -> (rows, total, facets)`; row keys `id, project_id, project_name, title, status, priority, task_type, assigned_agent_id, agent_name, delegation_source, due_date, created_at, updated_at`; `facets = {"status": {..}, "projects": {"<id>": name}, "capabilities": [..]}`
  - `get_task(task_id) -> dict | None` (all columns + `project_name`, `agent_name`, `notes` newest-10 newest-first)
  - `capabilities() -> list[str]` (sorted keys of `CAPABILITY_DEPARTMENT_MAP`)
  - constants `TASK_STATUSES, OPEN_STATUSES, TASK_TYPES, PROJECT_DEFAULT_STATUSES, NOTE_CAP=50, NOTE_MAX_CHARS=2000, MAX_LIMIT=200`
  - `ValueError` for bad filter values (user-facing message).

- [ ] **Step 1: Write the failing tests** — create `platform_v2/tests/test_task_service.py`:

```python
"""#6679 Phase 4b — task_service is the single writer behind the cockpit Work pane.
Seeds its own rows on an AUTOCOMMIT connection (the service opens its own connections,
so uncommitted fixture rows would be invisible) and cleans them up. Runs in-container:
    docker exec -i archie_platform python3 -m pytest /app/tests/test_task_service.py -q
"""
import uuid

import pytest

from services import task_service as ts


@pytest.fixture(scope="module")
def db(app):
    with app.app_context():
        from database import get_db

        conn = get_db()
        conn.autocommit = True
        yield conn
        conn.close()


@pytest.fixture(scope="module")
def seeded(db):
    tag = uuid.uuid4().hex[:8]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO unified_projects (name, slug, status, priority, project_type) VALUES (%s, %s, 'active', 8, 'feature') RETURNING id",
            (f"P4B probe {tag}", f"p4b-probe-{tag}"),
        )
        p1 = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO unified_projects (name, slug, status, priority, project_type) VALUES (%s, %s, 'completed', 1, 'feature') RETURNING id",
            (f"P4B done {tag}", f"p4b-done-{tag}"),
        )
        p2 = cur.fetchone()["id"]
        ids = []
        for title, status, prio, ttype in [
            (f"alpha {tag}", "pending", 9, "implementation"),
            (f"bravo {tag}", "in_progress", 5, "bugfix"),
            (f"charlie {tag}", "blocked", 7, "research"),
            (f"delta {tag}", "completed", 3, "testing"),
            (f"echo {tag}", "cancelled", 2, "review"),
            (f"foxtrot {tag} needle", "pending", 4, "documentation"),
        ]:
            cur.execute(
                "INSERT INTO unified_tasks (project_id, title, description, status, priority, task_type) "
                "VALUES (%s, %s, 'seeded by test_task_service', %s, %s, %s) RETURNING id",
                (p1, title, status, prio, ttype),
            )
            ids.append(cur.fetchone()["id"])
    yield {"tag": tag, "p1": p1, "p2": p2, "tasks": ids}
    with db.cursor() as cur:
        cur.execute("DELETE FROM unified_tasks WHERE project_id IN (%s, %s)", (p1, p2))
        cur.execute("DELETE FROM unified_projects WHERE id IN (%s, %s)", (p1, p2))


def test_clamp_page_bounds():
    assert ts.clamp_page(None, None) == (50, 0)
    assert ts.clamp_page("500", "-3") == (200, 0)
    assert ts.clamp_page(0, 7) == (1, 7)
    assert ts.clamp_page("x", "y") == (50, 0)


def test_list_projects_counts_open_and_total(seeded):
    rows, total = ts.list_projects()
    assert total > 0
    mine = [r for r in rows if r["id"] == seeded["p1"]]
    assert mine and mine[0]["open_tasks"] == 3 and mine[0]["total_tasks"] == 6
    assert all(r["id"] != seeded["p2"] for r in rows), "completed projects are not listed by default"
    rows2, _ = ts.list_projects(status="completed", limit=200)
    assert any(r["id"] == seeded["p2"] for r in rows2)


def test_list_tasks_defaults_to_open_and_sorts_priority_desc(seeded):
    rows, total, facets = ts.list_tasks(project_id=seeded["p1"])
    assert total == 3
    assert [r["title"].split(" ")[0] for r in rows] == ["alpha", "charlie", "bravo"]
    assert rows[0]["project_name"].startswith("P4B probe")
    assert set(facets) == {"status", "projects", "capabilities"}
    assert facets["status"].get("pending", 0) >= 2
    assert str(seeded["p1"]) in facets["projects"]
    assert "code" in facets["capabilities"] and facets["capabilities"] == sorted(facets["capabilities"])


def test_list_tasks_filters(seeded):
    rows, total, _ = ts.list_tasks(project_id=seeded["p1"], status="completed,cancelled")
    assert total == 2 and {r["status"] for r in rows} == {"completed", "cancelled"}
    rows, total, _ = ts.list_tasks(project_id=seeded["p1"], q="needle")
    assert total == 1 and rows[0]["title"].startswith("foxtrot")
    rows, total, _ = ts.list_tasks(project_id=seeded["p1"], min_priority=7)
    assert total == 2
    rows, total, _ = ts.list_tasks(project_id=seeded["p1"], limit=2, offset=2)
    assert total == 3 and len(rows) == 1
    with pytest.raises(ValueError):
        ts.list_tasks(status="pending,bogus")


def test_get_task_returns_project_and_notes(seeded):
    t = ts.get_task(seeded["tasks"][0])
    assert t["title"].startswith("alpha") and t["project_name"].startswith("P4B probe")
    assert t["notes"] == [] and t["agent_name"] is None
    assert ts.get_task(-1) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_task_service.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: collection error `ModuleNotFoundError: No module named 'services.task_service'`.

- [ ] **Step 3: Implement** — create `platform_v2/services/task_service.py`:

```python
"""Single writer for the cockpit Work pane (#6679, Phase 4b) — unified_tasks / unified_projects.

Module-level functions, get_db_cursor context-managed, RealDictCursor rows, no Flask.
Notes live on the task (metadata->'notes'); the session-scoped work_notes table is
deliberately not used. Delegation stamps the SAME row so the agent-loop
delegate_task_worker (delegation_source IS NOT NULL AND status='pending') claims it.
The MCP handlers (mcp_server/tools/project_tools.py) and Dev HQ keep their own SQL for
now — converging them onto this module is a filed follow-up, not this slice.
"""
from __future__ import annotations

import difflib
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import Json

from database import get_db_cursor

TASK_STATUSES = ("pending", "in_progress", "blocked", "completed", "cancelled")
OPEN_STATUSES = ("pending", "in_progress", "blocked")
TASK_TYPES = ("implementation", "bugfix", "research", "testing", "review", "documentation")
PROJECT_STATUSES = ("active", "planning", "on_hold", "completed", "cancelled")
PROJECT_DEFAULT_STATUSES = ("active", "planning", "on_hold")
NOTE_CAP = 50
NOTE_MAX_CHARS = 2000
MAX_LIMIT = 200


def clamp_page(limit, offset):
    try:
        limit = int(limit or 50)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(offset or 0)
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(MAX_LIMIT, limit)), max(0, offset)


def _csv(value, allowed, label):
    if not value:
        return None
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    for p in parts:
        if p not in allowed:
            raise ValueError(f"unknown {label} {p!r}; allowed: {', '.join(allowed)}")
    return parts or None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def capabilities():
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

    return sorted(CAPABILITY_DEPARTMENT_MAP.keys())


# ---- reads -----------------------------------------------------------------------
def list_projects(status=None, limit=50, offset=0):
    limit, offset = clamp_page(limit, offset)
    statuses = _csv(status, PROJECT_STATUSES, "project status") or list(PROJECT_DEFAULT_STATUSES)
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM unified_projects WHERE status = ANY(%s)", (statuses,))
        total = cur.fetchone()["n"]
        cur.execute(
            """SELECT p.id, p.name, p.slug, p.status, p.priority, p.project_type, p.target_date,
                      COUNT(t.id) FILTER (WHERE t.status IN ('pending', 'in_progress', 'blocked')) AS open_tasks,
                      COUNT(t.id) AS total_tasks
                 FROM unified_projects p
                 LEFT JOIN unified_tasks t ON t.project_id = p.id
                WHERE p.status = ANY(%s)
                GROUP BY p.id
                ORDER BY p.priority DESC NULLS LAST, p.name
                LIMIT %s OFFSET %s""",
            (statuses, limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return rows, total


def list_tasks(q=None, project_id=None, status=None, min_priority=None, limit=50, offset=0):
    limit, offset = clamp_page(limit, offset)
    statuses = _csv(status, TASK_STATUSES, "status") or list(OPEN_STATUSES)
    where = ["t.status = ANY(%s)"]
    params: list = [statuses]
    if project_id not in (None, ""):
        where.append("t.project_id = %s")
        params.append(int(project_id))
    if q and str(q).strip():
        like = f"%{str(q).strip()}%"
        where.append("(t.title ILIKE %s OR t.description ILIKE %s)")
        params += [like, like]
    if min_priority not in (None, ""):
        where.append("t.priority >= %s")
        params.append(int(min_priority))
    sql_where = " AND ".join(where)
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) AS n FROM unified_tasks t WHERE {sql_where}", params)
        total = cur.fetchone()["n"]
        cur.execute(
            f"""SELECT t.id, t.project_id, p.name AS project_name, t.title, t.status, t.priority, t.task_type,
                       t.assigned_agent_id, a.name AS agent_name, t.delegation_source, t.due_date,
                       t.created_at, t.updated_at
                  FROM unified_tasks t
                  LEFT JOIN unified_projects p ON p.id = t.project_id
                  LEFT JOIN agents a ON a.id = t.assigned_agent_id
                 WHERE {sql_where}
                 ORDER BY t.priority DESC NULLS LAST, t.created_at DESC
                 LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT status, COUNT(*) AS n FROM unified_tasks WHERE status = ANY(%s) GROUP BY status",
            (list(TASK_STATUSES),),
        )
        status_facet = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT id, name FROM unified_projects WHERE status = ANY(%s) ORDER BY name",
            (list(PROJECT_DEFAULT_STATUSES),),
        )
        projects_facet = {str(r["id"]): r["name"] for r in cur.fetchall()}
    return rows, total, {"status": status_facet, "projects": projects_facet, "capabilities": capabilities()}


def get_task(task_id) -> Optional[dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT t.*, p.name AS project_name, a.name AS agent_name
                 FROM unified_tasks t
                 LEFT JOIN unified_projects p ON p.id = t.project_id
                 LEFT JOIN agents a ON a.id = t.assigned_agent_id
                WHERE t.id = %s""",
            (int(task_id),),
        )
        row = cur.fetchone()
    if not row:
        return None
    task = dict(row)
    notes = list((task.get("metadata") or {}).get("notes") or [])
    task["notes"] = notes[-10:][::-1]
    return task
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_task_service.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/task_service.py /mnt/archie_brain/platform_v2/tests/test_task_service.py
git commit -m "feat(tasks): task_service reads — projects, tasks, one task, capabilities (#6679 Phase 4b)"
```

---

### Task 3: `task_service` writes — create, status, priority, note, delegate

**Files:**
- Modify: `platform_v2/services/task_service.py` (append)
- Test: `platform_v2/tests/test_task_service.py` (append)

**Interfaces:**
- Produces (all return the refreshed `get_task(...)` dict except `add_note`, which returns the note dict `{"ts","author","text"}`):
  - `create_task(project_id, title, description="", priority=5, task_type="implementation", requested_by="cockpit")`
  - `set_status(task_id, status, requested_by="cockpit")`
  - `set_priority(task_id, priority, requested_by="cockpit")`
  - `add_note(task_id, text, author="cockpit")`
  - `delegate(task_id, capability, requested_by="cockpit")`
  - Errors: `LookupError` = not found (routes map to 404); `ValueError` = user-facing validation (400).

- [ ] **Step 1: Write the failing tests** — append to `platform_v2/tests/test_task_service.py`:

```python
def test_create_task_validates_and_inserts_pending(seeded, db):
    t = ts.create_task(seeded["p1"], f"  created {seeded['tag']}  ", "desc", priority=7, task_type="bugfix")
    try:
        assert t["status"] == "pending" and t["priority"] == 7 and t["task_type"] == "bugfix"
        assert t["title"] == f"created {seeded['tag']}" and t["metadata"]["created_via"] == "cockpit"
        with pytest.raises(ValueError):
            ts.create_task(seeded["p1"], "", priority=5)
        with pytest.raises(ValueError):
            ts.create_task(seeded["p1"], "x", priority=11)
        with pytest.raises(ValueError):
            ts.create_task(seeded["p1"], "x", task_type="portrait_refinement")
        with pytest.raises(ValueError):
            ts.create_task(seeded["p2"], "x")  # completed project
        with pytest.raises(LookupError):
            ts.create_task(-1, "x")
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM unified_tasks WHERE id = %s", (t["id"],))


def test_set_status_stamps_timestamps_and_refuses_worker_owned(seeded, db):
    tid = seeded["tasks"][0]  # alpha, pending
    t = ts.set_status(tid, "in_progress")
    assert t["status"] == "in_progress" and t["started_at"] is not None
    t = ts.set_status(tid, "completed")
    assert t["completed_at"] is not None
    t = ts.set_status(tid, "pending")
    assert t["status"] == "pending"
    with pytest.raises(ValueError):
        ts.set_status(tid, "done")
    with pytest.raises(LookupError):
        ts.set_status(-1, "pending")
    with db.cursor() as cur:
        cur.execute("UPDATE unified_tasks SET delegation_source='cockpit', status='in_progress' WHERE id=%s", (tid,))
    try:
        with pytest.raises(ValueError):
            ts.set_status(tid, "completed")
    finally:
        with db.cursor() as cur:
            cur.execute("UPDATE unified_tasks SET delegation_source=NULL, status='pending' WHERE id=%s", (tid,))


def test_set_priority_range(seeded):
    tid = seeded["tasks"][1]
    assert ts.set_priority(tid, 10)["priority"] == 10
    assert ts.set_priority(tid, "5")["priority"] == 5
    with pytest.raises(ValueError):
        ts.set_priority(tid, 0)


def test_add_note_appends_and_caps(seeded):
    tid = seeded["tasks"][2]
    n = ts.add_note(tid, "  first note  ")
    assert n["text"] == "first note" and n["author"] == "cockpit" and n["ts"].endswith("+00:00")
    for i in range(ts.NOTE_CAP + 5):
        ts.add_note(tid, f"note {i}")
    t = ts.get_task(tid)
    assert len(t["metadata"]["notes"]) == ts.NOTE_CAP
    assert t["notes"][0]["text"] == f"note {ts.NOTE_CAP + 4}" and len(t["notes"]) == 10
    with pytest.raises(ValueError):
        ts.add_note(tid, "   ")
    with pytest.raises(ValueError):
        ts.add_note(tid, "x" * (ts.NOTE_MAX_CHARS + 1))


def test_delegate_stamps_the_same_row_for_the_worker(seeded, db):
    tid = seeded["tasks"][5]  # foxtrot, pending
    t = ts.delegate(tid, "research")
    try:
        assert t["id"] == tid, "no duplicate row"
        assert t["delegation_source"] == "cockpit" and t["status"] == "pending"
        assert t["delegation_args"]["capability"] == "research"
        assert t["delegation_args"]["args"]["origin_task_id"] == tid
        assert t["delegation_args"]["reason"].startswith("seeded by")
        assert t["notes"][0]["text"] == "delegated to fleet: research"
        with pytest.raises(ValueError):
            ts.delegate(tid, "research")  # already queued
        with pytest.raises(ValueError) as e:
            ts.delegate(seeded["tasks"][2], "reserch")
        assert "nearest" in str(e.value)
        with pytest.raises(ValueError):
            ts.delegate(seeded["tasks"][1], "research")  # in_progress
        with pytest.raises(LookupError):
            ts.delegate(-1, "research")
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM unified_tasks WHERE delegation_args->'args'->>'origin_task_id' = %s", (str(tid),))
            assert cur.fetchone()["n"] == 1
    finally:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE unified_tasks SET delegation_source=NULL, delegation_args=NULL, status='pending' WHERE id=%s", (tid,)
            )
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_task_service.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: `5 failed, 5 passed` — `AttributeError: module 'services.task_service' has no attribute 'create_task'` etc.

- [ ] **Step 3: Implement** — append to `platform_v2/services/task_service.py`:

```python
# ---- writes ----------------------------------------------------------------------
def _priority(value) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError):
        raise ValueError("priority must be an integer 1–10")
    if not 1 <= p <= 10:
        raise ValueError("priority must be an integer 1–10")
    return p


def _fetch(cur, task_id):
    cur.execute("SELECT * FROM unified_tasks WHERE id = %s", (int(task_id),))
    row = cur.fetchone()
    if not row:
        raise LookupError("task not found")
    return dict(row)


def _append_note(meta: dict, author: str, text: str) -> dict:
    note = {"ts": _now_iso(), "author": author, "text": text}
    notes = list(meta.get("notes") or [])
    notes.append(note)
    meta["notes"] = notes[-NOTE_CAP:]
    return note


def create_task(project_id, title, description="", priority=5, task_type="implementation", requested_by="cockpit"):
    title = (title or "").strip()
    if not 1 <= len(title) <= 500:
        raise ValueError("title must be 1–500 characters")
    priority = _priority(priority)
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type must be one of {', '.join(TASK_TYPES)}")
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT id, status FROM unified_projects WHERE id = %s", (int(project_id),))
        project = cur.fetchone()
        if not project:
            raise LookupError("project not found")
        if project["status"] in ("completed", "cancelled"):
            raise ValueError(f"project is {project['status']} — pick an open project")
        cur.execute(
            """INSERT INTO unified_tasks (project_id, title, description, status, priority, task_type, metadata,
                                          created_at, updated_at)
               VALUES (%s, %s, %s, 'pending', %s, %s, %s, NOW(), NOW()) RETURNING id""",
            (int(project_id), title, description or "", priority, task_type, Json({"created_via": requested_by})),
        )
        task_id = cur.fetchone()["id"]
    return get_task(task_id)


def set_status(task_id, status, requested_by="cockpit"):
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {', '.join(TASK_STATUSES)}")
    with get_db_cursor(commit=True) as (conn, cur):
        row = _fetch(cur, task_id)
        if row.get("delegation_source") and row.get("status") == "in_progress":
            raise ValueError("the fleet worker owns this task while it runs — wait for it to finish")
        cur.execute(
            """UPDATE unified_tasks
                  SET status = %s,
                      updated_at = NOW(),
                      completed_at = CASE WHEN %s = 'completed' THEN NOW() ELSE completed_at END,
                      started_at = CASE WHEN %s = 'in_progress' AND started_at IS NULL THEN NOW() ELSE started_at END
                WHERE id = %s""",
            (status, status, status, int(task_id)),
        )
    return get_task(task_id)


def set_priority(task_id, priority, requested_by="cockpit"):
    priority = _priority(priority)
    with get_db_cursor(commit=True) as (conn, cur):
        _fetch(cur, task_id)
        cur.execute("UPDATE unified_tasks SET priority = %s, updated_at = NOW() WHERE id = %s", (priority, int(task_id)))
    return get_task(task_id)


def add_note(task_id, text, author="cockpit"):
    text = (text or "").strip()
    if not text:
        raise ValueError("note text required")
    if len(text) > NOTE_MAX_CHARS:
        raise ValueError(f"note is longer than {NOTE_MAX_CHARS} characters")
    with get_db_cursor(commit=True) as (conn, cur):
        row = _fetch(cur, task_id)
        meta = dict(row.get("metadata") or {})
        note = _append_note(meta, author, text)
        cur.execute("UPDATE unified_tasks SET metadata = %s, updated_at = NOW() WHERE id = %s", (Json(meta), int(task_id)))
    return note


def _known_capabilities(cur) -> list:
    known = set(capabilities())
    cur.execute("SELECT DISTINCT skill_name FROM agent_skills WHERE skill_name IS NOT NULL")
    known.update(r["skill_name"] for r in cur.fetchall())
    return sorted(known)


def delegate(task_id, capability, requested_by="cockpit"):
    capability = (capability or "").strip()
    with get_db_cursor(commit=True) as (conn, cur):
        known = _known_capabilities(cur)
        if capability not in known:
            near = difflib.get_close_matches(capability, known, n=3) or known[:3]
            raise ValueError(f"unknown capability {capability!r}; nearest: {', '.join(near)}")
        row = _fetch(cur, task_id)
        if row.get("status") not in ("pending", "blocked"):
            raise ValueError(f"only pending or blocked tasks can be delegated (this one is {row.get('status')})")
        if row.get("delegation_source") and row.get("status") == "pending":
            raise ValueError("this task is already queued for the fleet")
        args = {
            "capability": capability,
            "reason": (row.get("description") or row.get("title") or "")[:2000],
            "args": {"origin_task_id": row["id"], "requested_by": requested_by},
        }
        meta = dict(row.get("metadata") or {})
        _append_note(meta, requested_by, f"delegated to fleet: {capability}")
        cur.execute(
            """UPDATE unified_tasks
                  SET delegation_source = 'cockpit', delegation_args = %s, status = 'pending',
                      metadata = %s, updated_at = NOW()
                WHERE id = %s""",
            (Json(args), Json(meta), int(task_id)),
        )
    return get_task(task_id)
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_task_service.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/task_service.py /mnt/archie_brain/platform_v2/tests/test_task_service.py
git commit -m "feat(tasks): task_service writes — create, status, priority, note, delegate (same-row stamp) (#6679 Phase 4b)"
```

---

### Task 4: the eight `/api/internal/{projects,tasks*}` routes

**Files:**
- Modify: `platform_v2/app.py` — insert after the `api_internal_cloud_code_providers` route (the function that starts at `app.py:6137`; insert after its final `return`)
- Modify: `platform_v2/tests/test_internal_auth_scopes.py:29-45` (PROBES) and `:106` (floor)
- Test: `platform_v2/tests/test_cockpit_task_routes.py`

**Interfaces:**
- Consumes: `task_service` (Tasks 2–3), `_cockpit_row`, `require_internal_scope`.
- Produces the routes in spec §2.3, serialised through `_cockpit_row`.

- [ ] **Step 1: Write the failing tests** — create `platform_v2/tests/test_cockpit_task_routes.py`:

```python
"""#6679 Phase 4b — the cockpit Work pane routes: scope-gated, thin, hub errors verbatim.
Runs in-container: docker exec -i archie_platform python3 -m pytest /app/tests/test_cockpit_task_routes.py -q
"""
import pytest

from services import internal_auth as ia
from services import task_service as ts

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.delenv(ia.LEGACY_ENV, raising=False)
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


def _h(caller="archie_comms"):
    return {"Authorization": f"Bearer {CALLER_KEYS[caller]}"}


def test_no_key_is_401_and_engine_key_is_403(client, keys):
    assert client.get("/api/internal/tasks").status_code == 401
    assert client.get("/api/internal/tasks", headers=_h("archie_engine")).status_code == 403
    assert client.post("/api/internal/tasks/1/note", headers=_h("archie_engine"), json={"text": "x"}).status_code == 403


def test_projects_list_passes_filters_and_echoes_paging(client, keys, monkeypatch):
    seen = {}

    def fake(status=None, limit=50, offset=0):
        seen.update(status=status, limit=limit, offset=offset)
        return [{"id": 343, "name": "Master", "open_tasks": 4, "total_tasks": 9}], 1

    monkeypatch.setattr(ts, "list_projects", fake)
    r = client.get("/api/internal/projects?status=active&limit=500&offset=-2", headers=_h())
    assert r.status_code == 200
    body = r.get_json()
    assert body["projects"][0]["name"] == "Master" and body["total"] == 1
    assert body["limit"] == 200 and body["offset"] == 0
    assert seen["status"] == "active"


def test_tasks_list_returns_facets(client, keys, monkeypatch):
    monkeypatch.setattr(
        ts, "list_tasks", lambda **kw: ([{"id": 1, "title": "t"}], 1, {"status": {"pending": 1}, "projects": {}, "capabilities": ["code"]})
    )
    body = client.get("/api/internal/tasks?q=t&project_id=343&min_priority=8", headers=_h()).get_json()
    assert body["success"] and body["facets"]["capabilities"] == ["code"] and body["tasks"][0]["id"] == 1


def test_bad_filter_is_400_verbatim(client, keys, monkeypatch):
    def boom(**kw):
        raise ValueError("unknown status 'bogus'; allowed: pending")

    monkeypatch.setattr(ts, "list_tasks", boom)
    r = client.get("/api/internal/tasks?status=bogus", headers=_h())
    assert r.status_code == 400 and r.get_json()["error"].startswith("unknown status 'bogus'")


def test_task_detail_404(client, keys, monkeypatch):
    monkeypatch.setattr(ts, "get_task", lambda tid: None)
    assert client.get("/api/internal/tasks/99", headers=_h()).status_code == 404


def test_create_task_is_201(client, keys, monkeypatch):
    seen = {}

    def fake(project_id, title, description="", priority=5, task_type="implementation", requested_by="cockpit"):
        seen.update(project_id=project_id, title=title, priority=priority, task_type=task_type, requested_by=requested_by)
        return {"id": 5, "title": title, "status": "pending"}

    monkeypatch.setattr(ts, "create_task", fake)
    r = client.post("/api/internal/tasks", headers=_h(), json={"project_id": 343, "title": "T", "priority": 7, "task_type": "bugfix"})
    assert r.status_code == 201 and r.get_json()["task"]["id"] == 5
    assert seen == {"project_id": 343, "title": "T", "priority": 7, "task_type": "bugfix", "requested_by": "cockpit"}


def test_task_actions_map_to_service(client, keys, monkeypatch):
    calls = []
    monkeypatch.setattr(ts, "set_status", lambda tid, s, requested_by="cockpit": calls.append(("status", tid, s)) or {"id": tid, "status": s})
    monkeypatch.setattr(ts, "set_priority", lambda tid, p, requested_by="cockpit": calls.append(("priority", tid, p)) or {"id": tid, "priority": p})
    monkeypatch.setattr(ts, "add_note", lambda tid, t, author="cockpit": calls.append(("note", tid, t)) or {"ts": "now", "author": author, "text": t})
    monkeypatch.setattr(ts, "get_task", lambda tid: {"id": tid})
    monkeypatch.setattr(ts, "delegate", lambda tid, c, requested_by="cockpit": calls.append(("delegate", tid, c)) or {"id": tid, "delegation_source": "cockpit"})
    assert client.post("/api/internal/tasks/7/status", headers=_h(), json={"status": "blocked"}).status_code == 200
    assert client.post("/api/internal/tasks/7/priority", headers=_h(), json={"priority": 9}).status_code == 200
    r = client.post("/api/internal/tasks/7/note", headers=_h(), json={"text": "hi"})
    assert r.status_code == 200 and r.get_json()["note"]["text"] == "hi" and r.get_json()["task"]["id"] == 7
    r = client.post("/api/internal/tasks/7/delegate", headers=_h(), json={"capability": "research"})
    assert r.status_code == 202 and r.get_json()["worker"] == "delegate_task_worker" and r.get_json()["claims_within_s"] == 30
    assert calls == [("status", 7, "blocked"), ("priority", 7, 9), ("note", 7, "hi"), ("delegate", 7, "research")]


def test_lookup_error_is_404_and_value_error_is_400(client, keys, monkeypatch):
    def missing(*a, **k):
        raise LookupError("task not found")

    def bad(*a, **k):
        raise ValueError("only pending or blocked tasks can be delegated (this one is completed)")

    monkeypatch.setattr(ts, "set_status", missing)
    monkeypatch.setattr(ts, "delegate", bad)
    assert client.post("/api/internal/tasks/1/status", headers=_h(), json={"status": "pending"}).status_code == 404
    r = client.post("/api/internal/tasks/1/delegate", headers=_h(), json={"capability": "research"})
    assert r.status_code == 400 and "only pending or blocked" in r.get_json()["error"]
```

Also, in `platform_v2/tests/test_internal_auth_scopes.py`: add to `PROBES` (after the `"agents:read"` entry)

```python
    "tasks:read": ("GET", "/api/internal/tasks"),
    "tasks:write": ("POST", "/api/internal/tasks/0/note"),
```

and change the floor at line 106 from `>= 48` to `>= 56`.

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cockpit_task_routes.py /app/tests/test_internal_auth_scopes.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: the new file fails with 404s (routes missing); `test_every_internal_route_is_scoped` fails on the floor.

- [ ] **Step 3: Implement** — insert into `platform_v2/app.py` right after the `api_internal_cloud_code_providers` function (the last cloud-code route):

```python
# ---- Cockpit Work pane: projects + tasks (#6679 Phase 4b) ----------------------------
# Thin routes over services/task_service (the single writer). LookupError → 404,
# ValueError → 400 with the message verbatim (comms shows it as-is), anything else → 500.
def _task_error(exc):
    if isinstance(exc, LookupError):
        return jsonify({"success": False, "error": str(exc)}), 404
    if isinstance(exc, ValueError):
        return jsonify({"success": False, "error": str(exc)}), 400
    logger.error("cockpit task route failed: %s", exc)
    return jsonify({"success": False, "error": "task read/write failed"}), 500


@app.route("/api/internal/projects", methods=["GET"])
@require_internal_scope("tasks:read")
def api_internal_projects_list():
    from services import task_service as ts

    a = request.args
    try:
        rows, total = ts.list_projects(status=a.get("status"), limit=a.get("limit"), offset=a.get("offset"))
    except Exception as exc:
        return _task_error(exc)
    limit, offset = ts.clamp_page(a.get("limit"), a.get("offset"))
    return jsonify(
        {"success": True, "projects": [_cockpit_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}
    )


@app.route("/api/internal/tasks", methods=["GET"])
@require_internal_scope("tasks:read")
def api_internal_tasks_list():
    from services import task_service as ts

    a = request.args
    try:
        rows, total, facets = ts.list_tasks(
            q=a.get("q"),
            project_id=a.get("project_id") or None,
            status=a.get("status"),
            min_priority=a.get("min_priority") or None,
            limit=a.get("limit"),
            offset=a.get("offset"),
        )
    except Exception as exc:
        return _task_error(exc)
    limit, offset = ts.clamp_page(a.get("limit"), a.get("offset"))
    return jsonify(
        {
            "success": True,
            "tasks": [_cockpit_row(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "facets": facets,
        }
    )


@app.route("/api/internal/tasks/<int:task_id>", methods=["GET"])
@require_internal_scope("tasks:read")
def api_internal_task_detail(task_id):
    from services import task_service as ts

    try:
        task = ts.get_task(task_id)
    except Exception as exc:
        return _task_error(exc)
    if not task:
        return jsonify({"success": False, "error": "task not found"}), 404
    return jsonify({"success": True, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_create():
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.create_task(
            data.get("project_id"),
            data.get("title"),
            description=data.get("description") or "",
            priority=data.get("priority", 5),
            task_type=data.get("task_type") or "implementation",
            requested_by="cockpit",
        )
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task)}), 201


@app.route("/api/internal/tasks/<int:task_id>/status", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_status(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.set_status(task_id, (data.get("status") or "").strip(), requested_by="cockpit")
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks/<int:task_id>/priority", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_priority(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.set_priority(task_id, data.get("priority"), requested_by="cockpit")
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks/<int:task_id>/note", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_note(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        note = ts.add_note(task_id, data.get("text"), author="cockpit")
        task = ts.get_task(task_id)
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "note": note, "task": _cockpit_row(task)})


@app.route("/api/internal/tasks/<int:task_id>/delegate", methods=["POST"])
@require_internal_scope("tasks:write")
def api_internal_task_delegate(task_id):
    from services import task_service as ts

    data = request.get_json(silent=True) or {}
    try:
        task = ts.delegate(task_id, data.get("capability"), requested_by="cockpit")
    except Exception as exc:
        return _task_error(exc)
    return jsonify({"success": True, "task": _cockpit_row(task), "worker": "delegate_task_worker", "claims_within_s": 30}), 202
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cockpit_task_routes.py /app/tests/test_internal_auth_scopes.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass (8 new + the scope suite with the floor at 56).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/app.py /mnt/archie_brain/platform_v2/tests/test_cockpit_task_routes.py /mnt/archie_brain/platform_v2/tests/test_internal_auth_scopes.py
git commit -m "feat(api): /api/internal/projects + /tasks* — eight cockpit Work pane routes under tasks:read/write (#6679 Phase 4b)"
```

---

### Task 5: `cloud_code_apply` pure helpers — path policy, fence stripper, prompt, names

**Files:**
- Create: `platform_v2/services/cloud_code_apply.py`
- Test: `platform_v2/tests/test_cloud_code_apply.py`

**Interfaces:**
- Produces: `ACTION_TYPE = "cloud_code_apply"`, `ALLOWED_PREFIXES`, `BLOCKED_GLOBS`, `validate_target(path) -> str`, `strip_fences(text) -> str`, `content_sha256(text) -> str`, `build_edit_prompt(target_path, prompt, current: str | None) -> str`, `branch_name(job_id, target_path) -> str`, `commit_message(job_id, target_path, meta) -> str`, `pr_title(target_path, meta) -> str`, `pr_body(job_id, target_path, meta, base_sha) -> str`, `apply_precondition(status, meta) -> str | None`.

- [ ] **Step 1: Write the failing tests** — create `platform_v2/tests/test_cloud_code_apply.py`:

```python
"""#6680 Phase 4b — Apply a cloud coding result: pure policy helpers (no DB, no network)."""
import os

import pytest

from services import cloud_code_apply as ap


@pytest.mark.parametrize(
    "path",
    ["platform_v2/services/x.py", "ai_bridge/y.py", "scripts/z.sh", "docs/notes.md", "archie-comms/app_comms.py", "./platform_v2/a.py"],
)
def test_validate_target_accepts_allowed(path):
    assert ap.validate_target(path).startswith(("platform_v2/", "ai_bridge/", "scripts/", "docs/", "archie-comms/"))


@pytest.mark.parametrize(
    "path",
    [
        "", "   ", "/etc/passwd", "../platform_v2/x.py", "platform_v2/../../etc/passwd", "platform_v2\\x.py",
        "platform_v2/.env", "platform_v2/.env.local", "secrets/k.pem", "platform_v2/id.key", "docker-compose.yml",
        "Dockerfile", "scripts/dr/failover.sh", ".github/workflows/ci.yml", "platform_v2/.git/config",
        "platform_v2/services/agent_service.py", "platform_v2/tools/department_hq/services/department_dispatcher.py",
        "platform_v2/tools/repair_bay/services/github_service.py", "platform_v2/tools/repair_bay/services/pr_review_service.py",
        "scripts/check_agent_single_writer.py", "scripts/agents/run.sh", "scripts/backup/x.sh",
        "platform_v2/services/internal_auth.py", "platform_v2/services/cloud_code_apply.py", "platform_v2/services/cloud_code_lane.py",
        "database/migrations/483_x.sql", "what-the-fact/consumer/routes.py", "platform_v2/" + "a" * 240 + ".py", "platform_v2/x\x00.py",
    ],
)
def test_validate_target_rejects(path):
    with pytest.raises(ValueError):
        ap.validate_target(path)


def test_strip_fences_variants():
    assert ap.strip_fences("x = 1\n") == "x = 1\n"
    assert ap.strip_fences("x = 1") == "x = 1\n"
    assert ap.strip_fences("```\nx = 1\n```") == "x = 1\n"
    assert ap.strip_fences("```python\nx = 1\ny = 2\n```\n") == "x = 1\ny = 2\n"
    assert ap.strip_fences("Here you go:\n```python\nx = 1\n```") == "Here you go:\n```python\nx = 1\n```\n"
    assert ap.strip_fences("") == ""


def test_prompt_and_names():
    p = ap.build_edit_prompt("docs/a.md", "Add a line", "old\n")
    assert p.startswith("You are editing the file docs/a.md") and "--- current contents of docs/a.md ---\nold\n" in p and "Task: Add a line" in p
    assert "does not exist yet" in ap.build_edit_prompt("docs/a.md", "Add", None)
    assert ap.branch_name(1202345, "docs/cockpit-apply-probe.md") == "cockpit/apply-1202345-docs-cockpit-apply-probe-md"
    assert len(ap.branch_name(1, "platform_v2/" + "x" * 100 + ".py")) <= len("cockpit/apply-1-") + 40
    meta = {"provider": "omniroute", "model": "oc/big-pickle", "result": {"model_used": "big-pickle"}, "prompt_original": "Write a note"}
    assert ap.commit_message(7, "docs/a.md", meta).startswith("feat(cockpit-apply): docs/a.md via omniroute:big-pickle (job #7)")
    assert "Co-Authored-By: A.R.C.H.I.E. Cockpit <cockpit@kytranempowerment.com>" in ap.commit_message(7, "docs/a.md", meta)
    assert ap.pr_title("docs/a.md", meta) == "[cockpit] docs/a.md: Write a note"
    body = ap.pr_body(7, "docs/a.md", meta, "abc1234")
    assert "job #7" in body and "human merge only" in body and "abc1234" in body and "omniroute" in body
    assert ap.content_sha256("x\n") == ap.content_sha256("x\n") and len(ap.content_sha256("x\n")) == 64


def test_apply_precondition():
    ok = {"target_path": "docs/a.md", "result": {"response": "x"}}
    assert ap.apply_precondition("completed", ok) is None
    assert "not completed" in ap.apply_precondition("running", ok)
    assert "no answer" in ap.apply_precondition("completed", {"target_path": "docs/a.md", "result": {"response": ""}})
    assert "without a target file" in ap.apply_precondition("completed", {"result": {"response": "x"}})
    assert "already applied" in ap.apply_precondition("completed", dict(ok, pr_number=12))


def test_blocked_globs_match_the_engine_scope_guard():
    engine = "/mnt/standalone/archie-code/archie_engine/scope_guard.py"
    if not os.path.exists(engine):
        pytest.skip("engine source not mounted here")
    src = open(engine, encoding="utf-8").read()
    for g in ap.ENGINE_BLOCKED_GLOBS:
        assert f'"{g}"' in src, f"{g} is no longer in the engine's blocked_globs — reconcile the two lists"
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_apply.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: collection error `No module named 'services.cloud_code_apply'`.

- [ ] **Step 3: Implement** — create `platform_v2/services/cloud_code_apply.py`:

```python
"""Apply a cloud coding result to the repo (#6680, Phase 4b).

Pure helpers (no DB, no network) plus the approval executor at the bottom. The
executor composes the EXISTING github_service primitives — create_branch /
push_changes(content_overrides) / create_pr — so `main` is only ever a base and the
shared /mnt/archie_brain tree is never read or written. Every apply is a Tier-2 human
approval bound to a content hash and the base blob sha the model read.

BLOCKED_GLOBS mirrors archie_engine/scope_guard.py (the hub cannot import the engine);
tests/test_cloud_code_apply.py checks the copy against the engine file when mounted.
"""
from __future__ import annotations

import fnmatch
import hashlib
import posixpath
import re
from datetime import datetime, timezone
from typing import Optional

ACTION_TYPE = "cloud_code_apply"  # Tier-2 approval type (Ship category, prefix cloud_code_)
BRANCH_PREFIX = "cockpit/apply-"
PR_LABEL = "cockpit-apply"
MAX_PATH_LEN = 240
MAX_FILE_BYTES = 200 * 1024

# scope_guard.PLATFORM_SCOPE.allowed_paths + archie-comms/ (where the cockpit lives).
# database/migrations/ stays revoked, as the owner ruled for the engine.
ALLOWED_PREFIXES = ("platform_v2/", "ai_bridge/", "scripts/", "docs/", "archie-comms/")

ENGINE_BLOCKED_GLOBS = (
    "*.env",
    ".env*",
    "*.key",
    "*.pem",
    "*.pfx",
    "secrets/*",
    "docker-compose*",
    "Dockerfile*",
    "scripts/dr/*",
    ".git/*",
    ".github/*",
    "*agent_service.py",
    "*department_dispatcher.py",
    "*repair_bay/services/github_service.py",
    "*repair_bay/services/pr_review_service.py",
    "scripts/check_agent_single_writer.py",
    "scripts/agents/*",
    "scripts/backup/*",
)
# The lane must never be able to rewrite its own gate.
BLOCKED_GLOBS = ENGINE_BLOCKED_GLOBS + ("*internal_auth.py", "*cloud_code_apply.py", "*cloud_code_lane.py")
_BLOCKED_SEGMENTS = {".git", "secrets", ".ssh", ".gnupg", ".aws"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_target(path) -> str:
    """Return the normalised repo-relative path, or raise ValueError with a user-facing reason."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("target_path required")
    p = path.strip()
    if "\x00" in p:
        raise ValueError("target_path contains NUL")
    if len(p) > MAX_PATH_LEN:
        raise ValueError(f"target_path is longer than {MAX_PATH_LEN} characters")
    if "\\" in p:
        raise ValueError("target_path must use forward slashes")
    if p.startswith("/"):
        raise ValueError("target_path must be repo-relative (no leading /)")
    norm = posixpath.normpath(p)
    segments = norm.split("/")
    if ".." in segments or norm.startswith("../"):
        raise ValueError("target_path escapes the repository")
    if not norm.startswith(ALLOWED_PREFIXES):
        raise ValueError(f"target_path must start with one of: {', '.join(ALLOWED_PREFIXES)}")
    if any(seg in _BLOCKED_SEGMENTS for seg in segments):
        raise ValueError("target_path is inside a protected directory")
    base = posixpath.basename(norm)
    for g in BLOCKED_GLOBS:
        if fnmatch.fnmatch(norm, g) or fnmatch.fnmatch(base, g):
            raise ValueError(f"target_path is blocked by policy ({g})")
    return norm


_FENCE = re.compile(r"\A\s*```[\w+.\-]*[ \t]*\r?\n(.*?)\r?\n?```\s*\Z", re.S)


def strip_fences(text) -> str:
    """One whole-response fenced block → its body; anything else unchanged. Exactly one trailing newline."""
    text = text or ""
    if not text.strip():
        return ""
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    return body.rstrip() + "\n"


def content_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_edit_prompt(target_path: str, prompt: str, current: Optional[str]) -> str:
    head = (
        f"You are editing the file {target_path} in the archie-platform repository. "
        "Return the COMPLETE new contents of that file and nothing else — no prose, no fences."
    )
    if current is None:
        body = f"--- {target_path} does not exist yet ---"
    else:
        body = f"--- current contents of {target_path} ---\n{current}\n--- end of {target_path} ---"
    return f"{head}\n\nTask: {prompt}\n\n{body}"


def branch_name(job_id: int, target_path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", target_path.lower()).strip("-")[:40].rstrip("-")
    return f"{BRANCH_PREFIX}{job_id}-{slug}"


def _served(meta: dict) -> str:
    return ((meta.get("result") or {}).get("model_used") or meta.get("model") or "?").strip()


def commit_message(job_id: int, target_path: str, meta: dict) -> str:
    return (
        f"feat(cockpit-apply): {target_path} via {meta.get('provider', '?')}:{_served(meta)} (job #{job_id})\n\n"
        f"Applied from the A.R.C.H.I.E. cockpit Code Builder. Prompt: "
        f"{(meta.get('prompt_original') or meta.get('prompt') or '')[:200]}\n\n"
        "Co-Authored-By: A.R.C.H.I.E. Cockpit <cockpit@kytranempowerment.com>"
    )


def pr_title(target_path: str, meta: dict) -> str:
    first = (meta.get("prompt_original") or meta.get("prompt") or "").strip().splitlines()[0:1]
    return f"[cockpit] {target_path}: {(first[0] if first else '')[:60]}".rstrip(": ")


def pr_body(job_id: int, target_path: str, meta: dict, base_sha: Optional[str]) -> str:
    return "\n".join(
        [
            "## Cockpit apply",
            f"- job #{job_id} · provider `{meta.get('provider', '?')}` · requested `{meta.get('model', '?')}` · served `{_served(meta)}`",
            f"- target `{target_path}` · base blob sha `{base_sha or 'new file'}`",
            "",
            "### Prompt",
            (meta.get("prompt_original") or meta.get("prompt") or "")[:2000],
            "",
            "Opened from the cockpit; content came from a cloud model with no test gate — human merge only.",
            "",
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
        ]
    )


def apply_precondition(status: str, meta: dict) -> Optional[str]:
    """None when the job can be applied, else the user-facing reason (a 409)."""
    meta = meta or {}
    if status != "completed":
        return f"job is {status}, not completed"
    if not ((meta.get("result") or {}).get("response") or "").strip():
        return "job has no answer to apply"
    if not meta.get("target_path"):
        return "job was run without a target file — re-run it with one"
    if meta.get("pr_number"):
        return f"already applied as PR #{meta['pr_number']}"
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_apply.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass (the engine-parity test skips in-container unless `/mnt/standalone` is mounted; run it once on the host too: `cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_cloud_code_apply.py -q -k engine_scope` if a host venv exists, otherwise note it as skipped in the report).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/cloud_code_apply.py /mnt/archie_brain/platform_v2/tests/test_cloud_code_apply.py
git commit -m "feat(cloud-code): cloud_code_apply policy helpers — target allowlist/denylist, fence stripper, prompt, names (#6680 Phase 4b)"
```

---

### Task 6: `get_file_at_ref`, `target_path` on the run route, the `/apply` route, status/runs keys

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/github_service.py` (insert after `_api_get`, which ends at `:100`)
- Modify: `platform_v2/app.py:5985-6059` (run route), `:6060-6089` (status route), `:6091-6136` (runs route); insert the apply route after the status route
- Modify: `platform_v2/services/cloud_code_apply.py` (append `request_tier2_approval`)
- Modify: `platform_v2/tests/test_internal_auth_scopes.py:106` floor `>= 56` → `>= 57`
- Test: `platform_v2/tests/test_cloud_code_run_target.py`

**Interfaces:**
- Consumes: Task 5 helpers.
- Produces: `github_service.get_file_at_ref(path, ref="main") -> {"sha","content","size"} | None` (raises `ValueError` non-file/too large/non-UTF-8, `RuntimeError` other API failure); `cloud_code_apply.request_tier2_approval(*, job_id, meta, content, requested_by) -> int | None`; job metadata keys `target_path, base_sha, base_size, prompt_original, apply_approval_id, apply_requested_at`; status/runs responses carry `target_path, base_sha, pr_number, pr_url, branch, apply_approval_id, apply_error, prompt_original`.

- [ ] **Step 1: Write the failing tests** — create `platform_v2/tests/test_cloud_code_run_target.py`:

```python
"""#6680 Phase 4b — target file up front on the cloud-code run route + the apply route.
Seeds bridge_jobs rows on an autocommit connection; GitHub and the approval queue are faked.
"""
import json
import uuid

import pytest

from services import cloud_code_apply as ap
from services import cloud_code_lane as lane
from services import internal_auth as ia
from tools.repair_bay.services import github_service as gh

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.delenv(ia.LEGACY_ENV, raising=False)
    return CALLER_KEYS


@pytest.fixture(scope="module")
def db(app):
    with app.app_context():
        from database import get_db

        conn = get_db()
        conn.autocommit = True
        yield conn
        conn.close()


def _h():
    return {"Authorization": f"Bearer {CALLER_KEYS['archie_comms']}"}


@pytest.fixture
def lane_ok(monkeypatch):
    monkeypatch.setattr(lane, "code_allowed", lambda: True)
    monkeypatch.setattr(lane, "active_provider", lambda k: {"is_active": True, "default_model": "oc/big-pickle"})
    monkeypatch.setattr(lane, "request_tier2_approval", lambda **kw: 777)


def _meta(db, job_id):
    with db.cursor() as cur:
        cur.execute("SELECT metadata FROM bridge_jobs WHERE id=%s", (job_id,))
        return cur.fetchone()["metadata"]


def _cleanup(db, job_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM bridge_jobs WHERE id=%s", (job_id,))


def test_run_without_target_is_byte_identical_to_today(client, keys, lane_ok, db):
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "hi"})
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]
    try:
        assert set(_meta(db, job_id)) == {"lane", "provider", "model", "capability", "prompt", "system_prompt", "requested_by", "approval_id"}
    finally:
        _cleanup(db, job_id)


def test_run_with_target_reads_main_and_assembles_the_prompt(client, keys, lane_ok, db, monkeypatch):
    seen = {}

    def fake_get(path, ref="main"):
        seen.update(path=path, ref=ref)
        return {"sha": "abc1234def", "content": "old = 1\n", "size": 8}

    monkeypatch.setattr(gh, "get_file_at_ref", fake_get)
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "Add two", "target_path": "./docs/a.md"})
    assert r.status_code == 202, r.get_json()
    job_id = r.get_json()["job_id"]
    try:
        m = _meta(db, job_id)
        assert seen == {"path": "docs/a.md", "ref": "main"}
        assert m["target_path"] == "docs/a.md" and m["base_sha"] == "abc1234def" and m["base_size"] == 8
        assert m["prompt_original"] == "Add two"
        assert m["prompt"].startswith("You are editing the file docs/a.md") and "old = 1" in m["prompt"] and "Task: Add two" in m["prompt"]
    finally:
        _cleanup(db, job_id)


def test_run_with_missing_target_is_a_new_file(client, keys, lane_ok, db, monkeypatch):
    monkeypatch.setattr(gh, "get_file_at_ref", lambda path, ref="main": None)
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "Create", "target_path": "docs/new.md"})
    job_id = r.get_json()["job_id"]
    try:
        m = _meta(db, job_id)
        assert m["base_sha"] is None and "does not exist yet" in m["prompt"]
    finally:
        _cleanup(db, job_id)


def test_run_with_blocked_target_is_400_and_creates_no_job(client, keys, lane_ok, db, monkeypatch):
    monkeypatch.setattr(gh, "get_file_at_ref", lambda *a, **k: pytest.fail("must not read a blocked path"))
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "x", "target_path": "platform_v2/.env"})
    assert r.status_code == 400 and "blocked by policy" in r.get_json()["error"]


def test_run_when_github_is_down_is_503(client, keys, lane_ok, monkeypatch):
    def boom(path, ref="main"):
        raise RuntimeError("github contents read failed: HTTP 502")

    monkeypatch.setattr(gh, "get_file_at_ref", boom)
    r = client.post("/api/internal/cloud-code/run", headers=_h(), json={"prompt": "x", "target_path": "docs/a.md"})
    assert r.status_code == 503 and "could not read docs/a.md" in r.get_json()["error"]


def _seed_job(db, status="completed", meta=None):
    tag = uuid.uuid4().hex[:6]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO bridge_jobs (job_type, module_source, description, status, agent_name, metadata) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (lane.JOB_TYPE, lane.MODULE_ID, f"p4b {tag}", status, "CONTRACTOR→cloud", json.dumps(meta or {})),
        )
        return cur.fetchone()["id"]


COMPLETED_META = {
    "provider": "omniroute", "model": "oc/big-pickle", "target_path": "docs/a.md", "base_sha": "abc1234def",
    "prompt_original": "Write a note", "prompt": "…", "result": {"response": "```markdown\n# note\n```", "model_used": "big-pickle"},
}


def test_apply_raises_tier2_and_stamps_the_job(client, keys, db, monkeypatch):
    seen = {}

    def fake_req(*, job_id, meta, content, requested_by):
        seen.update(job_id=job_id, content=content, requested_by=requested_by, target=meta.get("target_path"))
        return 888

    monkeypatch.setattr(ap, "request_tier2_approval", fake_req)
    job_id = _seed_job(db, meta=COMPLETED_META)
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 202 and r.get_json() == {"success": True, "job_id": job_id, "approval_id": 888, "status": "pending_approval"}
        assert seen == {"job_id": job_id, "content": "# note\n", "requested_by": "cockpit:archie_comms", "target": "docs/a.md"}
        m = _meta(db, job_id)
        assert m["apply_approval_id"] == 888 and m["apply_requested_at"]
        s = client.get(f"/api/internal/cloud-code/run/{job_id}", headers=_h()).get_json()
        assert s["target_path"] == "docs/a.md" and s["apply_approval_id"] == 888 and s["prompt_original"] == "Write a note" and s["pr_number"] is None
        runs = client.get("/api/internal/cloud-code/runs?limit=5", headers=_h()).get_json()["runs"]
        mine = [x for x in runs if x["job_id"] == job_id][0]
        assert mine["target_path"] == "docs/a.md" and mine["pr_number"] is None and mine["apply_error"] is None and "prompt" not in mine
    finally:
        _cleanup(db, job_id)


@pytest.mark.parametrize(
    "status,meta,needle",
    [
        ("running", COMPLETED_META, "not completed"),
        ("completed", dict(COMPLETED_META, result={"response": ""}), "no answer"),
        ("completed", {k: v for k, v in COMPLETED_META.items() if k != "target_path"}, "without a target file"),
        ("completed", dict(COMPLETED_META, pr_number=12), "already applied"),
    ],
)
def test_apply_preconditions_are_409(client, keys, db, monkeypatch, status, meta, needle):
    monkeypatch.setattr(ap, "request_tier2_approval", lambda **kw: pytest.fail("must not request"))
    job_id = _seed_job(db, status=status, meta=meta)
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 409 and needle in r.get_json()["error"]
    finally:
        _cleanup(db, job_id)


def test_apply_dedup_is_409(client, keys, db, monkeypatch):
    monkeypatch.setattr(ap, "request_tier2_approval", lambda **kw: None)
    job_id = _seed_job(db, meta=COMPLETED_META)
    try:
        r = client.post(f"/api/internal/cloud-code/run/{job_id}/apply", headers=_h())
        assert r.status_code == 409 and "already waiting" in r.get_json()["error"]
    finally:
        _cleanup(db, job_id)


def test_apply_404_and_scope(client, keys):
    assert client.post("/api/internal/cloud-code/run/0/apply", headers=_h()).status_code == 404
    assert client.post("/api/internal/cloud-code/run/0/apply").status_code == 401


def test_get_file_at_ref_shapes(monkeypatch):
    import base64

    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (True, {"type": "file", "sha": "s1", "size": 4, "content": base64.b64encode(b"abc\n").decode()}))
    assert gh.get_file_at_ref("docs/a.md") == {"sha": "s1", "content": "abc\n", "size": 4}
    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (False, {"error": "HTTP 404", "detail": ""}))
    assert gh.get_file_at_ref("docs/none.md") is None
    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (True, {"type": "dir"}))
    with pytest.raises(ValueError):
        gh.get_file_at_ref("docs")
    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (True, {"type": "file", "sha": "s", "size": 300 * 1024, "content": ""}))
    with pytest.raises(ValueError):
        gh.get_file_at_ref("docs/big.md")
    monkeypatch.setattr(gh, "_api_get", lambda path, params=None, timeout=15: (False, {"error": "HTTP 502"}))
    with pytest.raises(RuntimeError):
        gh.get_file_at_ref("docs/a.md")
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_run_target.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: failures — `AttributeError: ... no attribute 'get_file_at_ref'`, 404 on `/apply`, metadata missing `target_path`.

- [ ] **Step 3a: `get_file_at_ref`** — insert into `github_service.py` immediately after the `_api_get` function:

```python
def get_file_at_ref(path: str, ref: str = "main") -> Optional[Dict]:
    """The blob at <ref> via the contents API (read token). None when the path does not exist.

    Raises ValueError for a non-file (directory/symlink/submodule), a file over 200 KB or
    non-UTF-8 content; RuntimeError for any other API failure. Used by the cockpit Apply
    lane (#6680) so the model reads, and the sha check binds to, exactly what is on main.
    """
    import base64

    ok, data = _api_get(f"/repos/{REPO_FULL}/contents/{path}", params={"ref": ref})
    if not ok:
        if "404" in str((data or {}).get("error", "")):
            return None
        raise RuntimeError(f"github contents read failed: {(data or {}).get('error')}")
    if isinstance(data, list) or (data or {}).get("type") != "file":
        raise ValueError(f"{path} is not a file")
    size = int(data.get("size") or 0)
    if size > 200 * 1024:
        raise ValueError(f"{path} is larger than 200 KB")
    raw = base64.b64decode(data.get("content") or "")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{path} is not UTF-8 text")
    return {"sha": data.get("sha"), "content": text, "size": size}
```

(`Optional` and `Dict` are already imported at the top of the module — verify with `grep -n "^from typing" github_service.py`.)

- [ ] **Step 3b: `request_tier2_approval`** — append to `services/cloud_code_apply.py`:

```python
# ---- approval request (the only subsystem touchpoint besides the executor) ---------------
def request_tier2_approval(*, job_id: int, meta: dict, content: str, requested_by: str) -> Optional[int]:
    """Ask-first. None when request_approval() could not enqueue (one pending apply at a time)."""
    from ai_bridge.agent_loop import request_approval

    target = meta.get("target_path")
    return request_approval(
        action_type=ACTION_TYPE,
        action_data={
            "job_id": job_id,
            "target_path": target,
            "base_sha": meta.get("base_sha"),
            "content_sha256": content_sha256(content),
            "provider": meta.get("provider"),
            "model": meta.get("model"),
            "requested_by": requested_by,
        },
        reason=f"Apply cloud coding result to {target} (job #{job_id})",
        requested_by="cloud_code_lane",
        tier=2,
    )
```

- [ ] **Step 3c: run route** — in `api_internal_cloud_code_run`, right after the line `provider_key = (data.get("provider") or "omniroute").strip()` add:

```python
    target_path = (data.get("target_path") or "").strip() or None
    base_sha = None
    base_size = None
    prompt_effective = prompt
    if target_path:
        from services import cloud_code_apply as apply_svc
        from tools.repair_bay.services import github_service as gh

        try:
            target_path = apply_svc.validate_target(target_path)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        try:
            current = gh.get_file_at_ref(target_path, "main")
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            logger.error("cloud-code target read failed for %s: %s", target_path, exc)
            return jsonify({"success": False, "error": f"could not read {target_path} from main: {exc}"}), 503
        if current:
            base_sha, base_size = current["sha"], current["size"]
        prompt_effective = apply_svc.build_edit_prompt(target_path, prompt, current["content"] if current else None)
```

then change the `meta = lane.build_job_metadata(prompt=prompt, ...)` call to `prompt=prompt_effective`, and right after it add:

```python
    if target_path:
        meta.update({"target_path": target_path, "base_sha": base_sha, "base_size": base_size, "prompt_original": prompt})
```

(The Tier-2 dispatch approval keeps `prompt=prompt` — the owner's own words in the preview.)

- [ ] **Step 3d: status route** — in `api_internal_cloud_code_status`, add to the returned dict after `"completed_at": ...,`:

```python
            "target_path": meta.get("target_path"),
            "base_sha": meta.get("base_sha"),
            "prompt_original": meta.get("prompt_original"),
            "apply_approval_id": meta.get("apply_approval_id"),
            "apply_error": meta.get("apply_error"),
            "pr_number": meta.get("pr_number"),
            "pr_url": meta.get("pr_url"),
            "branch": meta.get("branch"),
```

- [ ] **Step 3e: runs route** — in `api_internal_cloud_code_runs`, add to each `runs.append({...})` dict after `"completed_at": ...,`:

```python
                "target_path": meta.get("target_path"),
                "pr_number": meta.get("pr_number"),
                "pr_url": meta.get("pr_url"),
                "apply_approval_id": meta.get("apply_approval_id"),
                "apply_error": meta.get("apply_error"),
```

- [ ] **Step 3f: apply route** — insert after `api_internal_cloud_code_status` (before the runs route):

```python
@app.route("/api/internal/cloud-code/run/<int:job_id>/apply", methods=["POST"])
@require_internal_scope("cloud:code")
def api_internal_cloud_code_apply(job_id):
    """#6680 Phase 4b — turn a completed cloud coding answer into a Tier-2 'cloud_code_apply'
    approval. Nothing is written here; the approval executor (cloud_code_apply.execute) does
    the branch + commit + PR after the owner says yes."""
    import json as _json

    from database import get_db_cursor
    from services import cloud_code_apply as apply_svc
    from services import cloud_code_lane as lane

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id, status, metadata FROM bridge_jobs WHERE id=%s AND job_type=%s", (job_id, lane.JOB_TYPE))
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "job not found"}), 404
    meta = row["metadata"] or {}
    problem = apply_svc.apply_precondition(row["status"], meta)
    if problem:
        return jsonify({"success": False, "error": problem}), 409
    content = apply_svc.strip_fences((meta.get("result") or {}).get("response") or "")
    if not content.strip():
        return jsonify({"success": False, "error": "the answer is empty — nothing to apply"}), 409
    requested_by = f"cockpit:{getattr(g, 'internal_caller', 'archie_comms')}"
    approval_id = apply_svc.request_tier2_approval(job_id=job_id, meta=meta, content=content, requested_by=requested_by)
    if approval_id is None:
        return jsonify({"success": False, "error": "an apply is already waiting for approval — decide that one first"}), 409
    stamp = {"apply_approval_id": approval_id, "apply_requested_at": apply_svc._now_iso(), "apply_error": None}
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE bridge_jobs SET metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb, updated_at=NOW() WHERE id=%s",
            (_json.dumps(stamp), job_id),
        )
    return jsonify({"success": True, "job_id": job_id, "approval_id": approval_id, "status": "pending_approval"}), 202
```

Then set the floor in `test_internal_auth_scopes.py:106` to `>= 57`.

- [ ] **Step 4: Run to verify they pass**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_run_target.py /app/tests/test_internal_auth_scopes.py /app/tests/test_cloud_code_apply.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/app.py /mnt/archie_brain/platform_v2/services/cloud_code_apply.py /mnt/archie_brain/platform_v2/tools/repair_bay/services/github_service.py /mnt/archie_brain/platform_v2/tests/test_cloud_code_run_target.py /mnt/archie_brain/platform_v2/tests/test_internal_auth_scopes.py
git commit -m "feat(cloud-code): target file up front + POST run/<id>/apply raising a Tier-2 cloud_code_apply approval (#6680 Phase 4b)"
```

---

### Task 7: the executor, the agent-loop branch, and the human-merge gate

**Files:**
- Modify: `platform_v2/services/cloud_code_apply.py` (append `execute` + DB helpers)
- Modify: `ai_bridge/agent_loop.py` — inside `_execute_approved_action` (starts at `:6089`), insert a new `elif` immediately BEFORE the `else:` that carries the `# #5011 — an unhandled action type is a FAILURE` comment (after the `cloud_code_dispatch`/`cloud_comparison` branch at ~`:7423-7433`)
- Modify: `platform_v2/tools/repair_bay/services/pr_review_service.py:711-737`
- Test: `platform_v2/tests/test_cloud_code_apply.py` (append), `platform_v2/tests/test_forge_automerge_gate.py` (append two tests copying `:71-82`)

**Interfaces:**
- Produces: `cloud_code_apply.execute(action_data, *, gh=None, load_job=None, stamp_job=None) -> {"executed": bool, "error"?: str, "pr_number"?: int, "pr_url"?: str, "branch"?: str}`.

- [ ] **Step 1: Write the failing tests** — append to `platform_v2/tests/test_cloud_code_apply.py`:

```python
class _FakeGH:
    def __init__(self, current=None, fail=None):
        self.current = current
        self.fail = fail
        self.calls = []

    def get_file_at_ref(self, path, ref="main"):
        self.calls.append(("get", path, ref))
        if self.fail == "get":
            raise RuntimeError("github down")
        return self.current

    def create_branch(self, name, base="main"):
        self.calls.append(("branch", name, base))
        return {"success": self.fail != "branch", "branch": name, "error": "no"}

    def push_changes(self, branch, files, msg, content_overrides=None):
        self.calls.append(("push", branch, tuple(files), msg.splitlines()[0], content_overrides))
        if self.fail == "push":
            return {"success": False, "error": "push boom"}
        if self.fail == "nochange":
            return {"success": True, "committed": False, "message": "No changes to commit"}
        return {"success": True, "committed": True, "sha": "deadbeef", "branch": branch}

    def create_pr(self, branch, title, body, labels=None, base="main"):
        self.calls.append(("pr", branch, title, labels))
        if self.fail == "pr":
            return {"success": False, "error": "pr boom"}
        return {"success": True, "pr_number": 4242, "pr_url": "https://example/pull/4242", "branch": branch}

    def delete_branch(self, name, remote=True):
        self.calls.append(("delete", name))
        return {"success": True}


JOB = {
    "id": 77,
    "status": "completed",
    "metadata": {
        "provider": "omniroute", "model": "oc/big-pickle", "target_path": "docs/a.md", "base_sha": "abc1234",
        "prompt_original": "Write a note", "result": {"response": "```\n# note\n```", "model_used": "big-pickle"},
    },
}


def _action(content="# note\n", **over):
    a = {"job_id": 77, "target_path": "docs/a.md", "base_sha": "abc1234", "content_sha256": ap.content_sha256(content)}
    a.update(over)
    return a


def _run(gh, action=None, job=JOB):
    stamps = []
    r = ap.execute(action or _action(), gh=gh, load_job=lambda jid: job if jid == 77 else None, stamp_job=lambda jid, patch: stamps.append((jid, patch)))
    return r, stamps


def test_execute_happy_path_orders_the_primitives_and_stamps_the_pr():
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4})
    r, stamps = _run(gh)
    assert r == {"executed": True, "pr_number": 4242, "pr_url": "https://example/pull/4242", "branch": "cockpit/apply-77-docs-a-md"}
    kinds = [c[0] for c in gh.calls]
    assert kinds == ["get", "branch", "push", "pr"]
    push = gh.calls[2]
    assert push[2] == ("docs/a.md",) and push[4] == {"docs/a.md": "# note\n"} and push[3].startswith("feat(cockpit-apply): docs/a.md via omniroute:big-pickle (job #77)")
    assert gh.calls[3][2] == "[cockpit] docs/a.md: Write a note" and gh.calls[3][3] == ["cockpit-apply"]
    assert stamps[-1][0] == 77 and stamps[-1][1]["pr_number"] == 4242 and stamps[-1][1]["branch"] == "cockpit/apply-77-docs-a-md" and stamps[-1][1]["apply_error"] is None


def test_execute_refuses_when_main_moved_and_writes_nothing():
    gh = _FakeGH(current={"sha": "ffff999", "content": "new\n", "size": 4})
    r, stamps = _run(gh)
    assert r["executed"] is False and "changed on main" in r["error"] and "abc1234" in r["error"] and "ffff999" in r["error"]
    assert [c[0] for c in gh.calls] == ["get"]
    assert stamps[-1][1]["apply_error"].startswith("docs/a.md changed on main")


def test_execute_new_file_needs_base_sha_none():
    gh = _FakeGH(current=None)
    job = dict(JOB, metadata=dict(JOB["metadata"], base_sha=None))
    r, _ = _run(gh, _action(base_sha=None), job=job)
    assert r["executed"] is True
    gh2 = _FakeGH(current={"sha": "now", "content": "x", "size": 1})
    r2, _ = _run(gh2, _action(base_sha=None), job=job)
    assert r2["executed"] is False and "changed on main" in r2["error"]


def test_execute_refuses_content_hash_mismatch():
    gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4})
    r, _ = _run(gh, _action(content="something else\n"))
    assert r["executed"] is False and "changed since the approval" in r["error"] and gh.calls == []


def test_execute_cleans_the_branch_on_push_or_pr_failure():
    for fail, needle in (("push", "push boom"), ("pr", "pr boom"), ("nochange", "identical")):
        gh = _FakeGH(current={"sha": "abc1234", "content": "old\n", "size": 4}, fail=fail)
        r, stamps = _run(gh)
        assert r["executed"] is False and needle in r["error"], (fail, r)
        assert ("delete", "cockpit/apply-77-docs-a-md") in gh.calls
        assert stamps[-1][1]["apply_error"]


def test_execute_missing_job_or_github_read_failure():
    r, _ = _run(_FakeGH(), _action(job_id=5))
    assert r["executed"] is False and "not found" in r["error"]
    r, _ = _run(_FakeGH(fail="get"))
    assert r["executed"] is False and "could not read" in r["error"]
```

And append to `platform_v2/tests/test_forge_automerge_gate.py` (it already defines the `merges` fixture and the `_review(monkeypatch, *, branch, title)` helper at `:66`):

```python
def test_cockpit_branch_pr_is_gated(merges, monkeypatch):
    _review(monkeypatch, branch="cockpit/apply-1-docs-a-md", title="feat: looks normal")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == []  # a cockpit apply is cloud-model content with no test gate — human merge only


def test_cockpit_title_pr_is_gated(merges, monkeypatch):
    _review(monkeypatch, branch="fix/normal-looking", title="[cockpit] docs/a.md: sneaky")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == []  # gated by the [cockpit] title even on a normal branch
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_apply.py /app/tests/test_forge_automerge_gate.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: `AttributeError: ... no attribute 'execute'`; the two cockpit gate tests fail (the PR is not gated).

- [ ] **Step 3a: executor** — append to `services/cloud_code_apply.py`:

```python
# ---- executor (runs in the approval-queue drain, after the owner said yes) ------------
def _load_job(job_id: int) -> Optional[dict]:
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id, status, metadata FROM bridge_jobs WHERE id=%s", (int(job_id),))
        row = cur.fetchone()
    return dict(row) if row else None


def _stamp_job(job_id: int, patch: dict) -> None:
    import json as _json

    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE bridge_jobs SET metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb, updated_at=NOW() WHERE id=%s",
            (_json.dumps(patch), int(job_id)),
        )


def execute(action_data: dict, *, gh=None, load_job=None, stamp_job=None) -> dict:
    """Approval executor for ACTION_TYPE. Returns {"executed": bool, ...}; never raises.

    sha check → branch → ONE commit (content_overrides, literal text) → PR. `main` is only a
    base. Any failure after the branch exists deletes the branch. Every outcome is stamped
    on the job (pr_number/pr_url/branch or apply_error) so the cockpit shows it verbatim.
    """
    if gh is None:
        from tools.repair_bay.services import github_service as gh  # noqa: N813
    load_job = load_job or _load_job
    stamp_job = stamp_job or _stamp_job
    job_id = int((action_data or {}).get("job_id") or 0)

    def fail(msg: str) -> dict:
        if job_id:
            stamp_job(job_id, {"apply_error": msg})
        return {"executed": False, "error": msg}

    job = load_job(job_id) if job_id else None
    if not job:
        return {"executed": False, "error": f"job #{job_id} not found"}
    meta = job.get("metadata") or {}
    target = meta.get("target_path") or action_data.get("target_path")
    base_sha = meta.get("base_sha")
    content = strip_fences((meta.get("result") or {}).get("response") or "")
    if not target or not content.strip():
        return fail("job has no target file or no answer")
    if content_sha256(content) != action_data.get("content_sha256"):
        return fail("the job's answer changed since the approval was raised — apply again")
    try:
        current = gh.get_file_at_ref(target, "main")
    except Exception as exc:
        return fail(f"could not read {target} from main: {exc}")
    now_sha = current["sha"] if current else None
    if now_sha != base_sha:
        return fail(
            f"{target} changed on main since the model read it (was {(base_sha or 'new file')[:7]}, "
            f"now {(now_sha or 'new file')[:7]}) — re-run the job to pick up the new base"
        )
    branch = branch_name(job_id, target)
    r = gh.create_branch(branch, base="main")
    if not r.get("success"):
        return fail(f"branch: {r.get('error')}")
    r = gh.push_changes(branch, [target], commit_message(job_id, target, meta), content_overrides={target: content})
    if not r.get("success") or not r.get("committed"):
        gh.delete_branch(branch)
        return fail("the answer is identical to main — nothing to apply" if r.get("success") else f"push: {r.get('error')}")
    r = gh.create_pr(branch, title=pr_title(target, meta), body=pr_body(job_id, target, meta, base_sha), labels=[PR_LABEL])
    if not r.get("success"):
        gh.delete_branch(branch)
        return fail(f"pull request: {r.get('error')}")
    stamp_job(
        job_id,
        {"pr_number": r["pr_number"], "pr_url": r["pr_url"], "branch": branch, "applied_at": _now_iso(), "apply_error": None},
    )
    return {"executed": True, "pr_number": r["pr_number"], "pr_url": r["pr_url"], "branch": branch}
```

- [ ] **Step 3b: agent-loop branch** — read `ai_bridge/agent_loop.py:6089-6130` to learn the local name that holds the approval's payload dict in `_execute_approved_action` (the neighbouring `cloud_code_dispatch` branch at ~`:7423` shows which locals are in scope; it is the parsed `action_data` of `item`). Insert immediately before the `else:` that starts the `# #5011` comment:

```python
        elif action_type == "cloud_code_apply":
            # #6680 Phase 4b — unlike cloud_code_dispatch (worker-drained), the approval IS
            # the write gate: sha check → branch → one commit → PR, never main.
            from services import cloud_code_apply as _apply

            try:
                return _apply.execute(action_data)
            except Exception as apply_err:
                logger.error(f"cloud_code_apply execution failed: {apply_err}")
                return {"executed": False, "error": str(apply_err)}
```

(`action_data` = the same dict the `cloud_code_dispatch` branch's siblings read `job_id` from; if that local is named differently there, use that name.)

- [ ] **Step 3c: human-merge gate** — in `pr_review_service.py`: change the default in `_os.getenv("FORGE_NO_AUTOMERGE_BRANCH_PREFIXES", "engine/")` to `"engine/,cockpit/"`; change `_title.startswith("[engine]")` to `_title.startswith(("[engine]", "[cockpit]"))`; in the notification title replace `(engine-authored)` with `(autonomous or cockpit-authored)`, and in its message replace `engine PR` with `autonomous/cockpit PR`; extend the comment above the gate with one line: `# Phase 4b (#6680): cockpit applies ("cockpit/…", "[cockpit] …") carry cloud-model content with no test gate — same human-merge rule.`

- [ ] **Step 4: Run to verify they pass**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_cloud_code_apply.py /app/tests/test_forge_automerge_gate.py /app/tests/test_cloud_code_run_target.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/platform_v2/services/cloud_code_apply.py /mnt/archie_brain/ai_bridge/agent_loop.py /mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_review_service.py /mnt/archie_brain/platform_v2/tests/test_cloud_code_apply.py /mnt/archie_brain/platform_v2/tests/test_forge_automerge_gate.py
git commit -m "feat(cloud-code): cloud_code_apply executor — sha check, branch, one commit, PR; cockpit/ PRs are human-merge only (#6680 Phase 4b)"
```

---

### Task 8: hub PR — review, merge, deploy, verify

**Files:** none new.

- [ ] **Step 1: Full hub suite for the touched files**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_internal_auth_scopes.py /app/tests/test_task_service.py /app/tests/test_cockpit_task_routes.py /app/tests/test_cloud_code_apply.py /app/tests/test_cloud_code_run_target.py /app/tests/test_forge_automerge_gate.py /app/tests/test_dhq_chat_routing.py /app/tests/test_internal_approvals.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass. Also `python3 -m py_compile` is implied by the import; `docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); import services.task_service, services.cloud_code_apply; print('ok')"`.

- [ ] **Step 2: Push + PR**

```bash
git push -u origin feat/phase4b-hub
gh pr create --title "feat(phase4b): task_service + tasks:read/write routes + cloud-code Apply lane (#6679 #6680)" --body "$(cat <<'EOF'
## Summary
- `services/task_service.py`: single writer for the cockpit Work pane (list projects/tasks, task detail, create, status, priority, note, delegate = same-row stamp for `delegate_task_worker`). Eight `/api/internal/{projects,tasks*}` routes under two new comms-only scopes `tasks:read` / `tasks:write`.
- Cloud-code lane: optional `target_path` on `POST /run` (validated against an allowlist + the engine's blocked globs; the file is read from `main` via the read token and included in the prompt), `POST /run/<id>/apply` raising a Tier-2 `cloud_code_apply` approval, an executor that re-checks the base blob sha, then branch `cockpit/apply-<job>` → one commit (`content_overrides`) → PR labelled `cockpit-apply`. `cockpit/` / `[cockpit]` added to the human-merge gate.
- Spec: docs/superpowers/specs/2026-09-10-phase4b-work-pane-and-apply-design.md (ADR-042 follow-on).

## Test Plan
- [x] tests/test_task_service.py (10, seeded) · test_cockpit_task_routes.py (8) · test_cloud_code_apply.py (policy + executor) · test_cloud_code_run_target.py (11) · test_internal_auth_scopes.py floor 57 · test_forge_automerge_gate.py (+2)
- [ ] after deploy: scope probes from inside archie_comms; comms half in the next PR

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6
EOF
)"
```

- [ ] **Step 3: Register + F.O.R.G.E. review + merge on a clean APPROVE** — same mechanics as Phase 4a Task 5: `poll_open_prs()` + `get_review(n)`; fire `review_pr(n)` detached (`docker exec -d archie_platform python3 -c "$(cat <script>)"` writing `/tmp/forge_<n>.json`) and poll `get_review(n)['review_status']`; evaluate with `verdict_is_approved`, `coverage_only_demotion`, `coverage_dropped_paths`, `merge_state`, `classify_pr_tier`. A coverage-only demotion is discharged by an independent full read of every dropped file (ledger ruling with cost-if-wrong), then `merge_pr(n, method='squash', human_override=True)`. Tier 3 → stop and ask the owner. A REQUEST CHANGES → fix, push, re-review; never override.

- [ ] **Step 4: Deploy from main**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main && docker compose restart archie_platform archie_scheduler && docker compose ps archie_platform archie_scheduler
```
Expected: both healthy within ~60 s (the scheduler runs the approval drain that executes `cloud_code_apply`).

- [ ] **Step 5: Verify through the running process** (from inside `archie_comms`, the only holder of the scopes):

```bash
docker exec -i archie_comms python3 - <<'EOF'
import os, json, urllib.request, urllib.error
B = os.environ.get("PLATFORM_URL", "http://archie_platform:3000"); K = os.environ["INTERNAL_API_KEY"]
def call(m, p, body=None, auth=True):
    req = urllib.request.Request(B + p, method=m, data=json.dumps(body).encode() if body is not None else None,
        headers={**({"Authorization": "Bearer " + K} if auth else {}), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:160]
s, b = call("GET", "/api/internal/projects?limit=3"); print("projects", s, b.get("total") if isinstance(b, dict) else b)
s, b = call("GET", "/api/internal/tasks?limit=3"); print("tasks", s, b.get("total") if isinstance(b, dict) else b, sorted(b.get("facets", {}).keys()) if isinstance(b, dict) else "")
print("no-auth", call("GET", "/api/internal/tasks", auth=False)[0])
print("bad status", call("GET", "/api/internal/tasks?status=bogus")[:2])
print("apply 404", call("POST", "/api/internal/cloud-code/run/0/apply", {})[0])
print("blocked target", call("POST", "/api/internal/cloud-code/run", {"prompt": "x", "target_path": "platform_v2/.env"})[:2])
EOF
docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from tools.repair_bay.services import pr_review_service as p, github_service as g; import inspect; print('gate:', 'cockpit/' in inspect.getsource(p)); print('get_file_at_ref:', hasattr(g, 'get_file_at_ref'))"
```
Expected: `projects 200 <n>0`, `tasks 200 <n> ['capabilities','projects','status']`, `no-auth 401`, `bad status (400, …unknown status…)`, `apply 404 404`, `blocked target (400, …blocked by policy…)`, `gate: True`, `get_file_at_ref: True`. Live read of a real file (read token, no write): `docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from tools.repair_bay.services import github_service as g; r=g.get_file_at_ref('docs/superpowers/specs/2026-09-10-phase4-cockpit-ui-design.md'); print(r['sha'][:7], r['size'])"`.

- [ ] **Step 6: Dev HQ** — `mcp__archie__add_work_note` (hub half shipped, PR number, verification lines).

---

### Task 9: comms proxy — task functions, `build_apply`, `target_path` passthrough

**Files:**
- Modify: `archie-comms/services/cockpit_proxy.py`
- Test: `archie-comms/tests/test_cockpit_proxy.py` (append)

**Interfaces:**
- Produces: `TASK_ACTIONS = ("status", "priority", "note", "delegate")`, `list_projects(params)`, `list_tasks(params)` (allowed keys `q, project_id, status, min_priority, limit, offset`), `get_task(task_id)`, `create_task(body)`, `task_action(task_id, action, body)`, `build_apply(job_id)` — each `(status, payload)` like the rest.

- [ ] **Step 1: Write the failing tests** — append to `archie-comms/tests/test_cockpit_proxy.py`:

```python
def test_task_reads_forward_allowed_params_only(monkeypatch):
    seen = []

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.append((method, url, params))
        return _Resp(200, {"success": True, "tasks": [], "total": 0})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    cp.list_projects({"status": "active", "limit": "5", "evil": "1"})
    cp.list_tasks({"q": "x", "project_id": "343", "status": "pending", "min_priority": "8", "limit": "50", "offset": "50", "evil": "1"})
    cp.get_task(12)
    assert seen[0][:2] == ("GET", cp._base() + "/api/internal/projects") and seen[0][2] == {"status": "active", "limit": "5"}
    assert seen[1][1].endswith("/api/internal/tasks") and seen[1][2] == {"q": "x", "project_id": "343", "status": "pending", "min_priority": "8", "limit": "50", "offset": "50"}
    assert seen[2][1].endswith("/api/internal/tasks/12")


def test_task_writes_post_bodies_and_refuse_unknown_actions(monkeypatch):
    seen = []
    monkeypatch.setattr(cp.requests, "request", lambda m, u, json=None, headers=None, timeout=None, params=None: seen.append((m, u, json, timeout)) or _Resp(200, {"success": True}))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    cp.create_task({"project_id": 343, "title": "T"})
    cp.task_action(12, "delegate", {"capability": "research"})
    status, body = cp.task_action(12, "delete", {})
    assert status == 400 and "unknown action" in body["error"]
    assert seen[0][:3] == ("POST", cp._base() + "/api/internal/tasks", {"project_id": 343, "title": "T"}) and seen[0][3] == 30
    assert seen[1][1].endswith("/api/internal/tasks/12/delegate") and seen[1][2] == {"capability": "research"}
    assert len(seen) == 2


def test_build_apply_and_target_path_passthrough(monkeypatch):
    seen = []
    monkeypatch.setattr(cp.requests, "request", lambda m, u, json=None, headers=None, timeout=None, params=None: seen.append((m, u, json)) or _Resp(202, {"success": True, "approval_id": 9}))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    cp.build_run({"prompt": "p", "provider": "omniroute", "model": "oc/big-pickle", "target_path": "docs/a.md"})
    status, body = cp.build_apply(1202345)
    assert seen[0][2]["target_path"] == "docs/a.md"
    assert seen[1][:2] == ("POST", cp._base() + "/api/internal/cloud-code/run/1202345/apply") and status == 202 and body["approval_id"] == 9
```

- [ ] **Step 2: Run to verify they fail**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_proxy.py 2>&1 | tail -3`
Expected: `3 failed` — `AttributeError: module 'services.cockpit_proxy' has no attribute 'list_projects'` etc.

- [ ] **Step 3: Implement** — in `services/cockpit_proxy.py` add after `ACTIONS`:

```python
TASK_ACTIONS = ("status", "priority", "note", "delegate")
_TASK_LIST_KEYS = ("q", "project_id", "status", "min_priority", "limit", "offset")
```

and append at the end of the file:

```python
# ---- Work pane: projects + tasks (#6679 Phase 4b) --------------------------------------
def list_projects(params):
    allowed = {k: v for k, v in (params or {}).items() if k in ("status", "limit", "offset")}
    return _call("GET", "/api/internal/projects", params=allowed)


def list_tasks(params):
    allowed = {k: v for k, v in (params or {}).items() if k in _TASK_LIST_KEYS}
    return _call("GET", "/api/internal/tasks", params=allowed)


def get_task(task_id):
    return _call("GET", f"/api/internal/tasks/{_int(task_id, 'task_id')}")


def create_task(body):
    return _call("POST", "/api/internal/tasks", json=body or {})


def task_action(task_id, action, body):
    if action not in TASK_ACTIONS:
        return 400, {"success": False, "error": f"unknown action {action!r}"}
    return _call("POST", f"/api/internal/tasks/{_int(task_id, 'task_id')}/{action}", json=body or {})


# ---- Code Builder: apply (#6680 Phase 4b) ----------------------------------------------
def build_apply(job_id):
    return _call("POST", f"/api/internal/cloud-code/run/{_int(job_id, 'job_id')}/apply", json={})
```

- [ ] **Step 4: Run to verify they pass**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_proxy.py 2>&1 | tail -3`
Expected: `10 passed`.

- [ ] **Step 5: Commit** (branch `feat/phase4b-comms`, cut from `main` after Task 8 merged)

```bash
git add /mnt/archie_brain/archie-comms/services/cockpit_proxy.py /mnt/archie_brain/archie-comms/tests/test_cockpit_proxy.py
git commit -m "feat(comms): cockpit_proxy — projects/tasks pass-through, task actions, build_apply, target_path (#6679 #6680 Phase 4b)"
```

---

### Task 10: comms routes — six new rules (13 → 19)

**Files:**
- Modify: `archie-comms/cockpit_routes.py` (append before the end of the file, after the last build route)
- Test: `archie-comms/tests/test_cockpit_routes.py` (append)

**Interfaces:**
- Consumes: Task 9 proxy functions, `_require_session`, `_pass`.
- Produces: `GET /api/cockpit/projects`, `GET /api/cockpit/tasks`, `GET /api/cockpit/tasks/<int:task_id>`, `POST /api/cockpit/tasks`, `POST /api/cockpit/tasks/<int:task_id>/<action>`, `POST /api/cockpit/build/<int:job_id>/apply`.

- [ ] **Step 1: Write the failing tests** — append to `archie-comms/tests/test_cockpit_routes.py` (the file has no fixtures; it builds the app with its own `_app()` factory and logs in with `_login(client)` — both defined at the top, use them as-is; `cp` is `services.cockpit_proxy`):

```python
def test_cockpit_blueprint_has_nineteen_rules():
    rules = [r.rule for r in _app().url_map.iter_rules() if r.endpoint.startswith("cockpit.")]
    assert len(rules) == 19, sorted(rules)
    for r in ("/api/cockpit/projects", "/api/cockpit/tasks", "/api/cockpit/tasks/<int:task_id>", "/api/cockpit/tasks/<int:task_id>/<action>", "/api/cockpit/build/<int:job_id>/apply"):
        assert r in rules


def test_task_routes_are_401_without_a_session():
    c = _app().test_client()
    assert c.get("/api/cockpit/tasks").status_code == 401
    assert c.post("/api/cockpit/tasks/1/note", json={"text": "x"}).status_code == 401
    assert c.post("/api/cockpit/build/1/apply").status_code == 401


def test_task_routes_map_to_proxy(monkeypatch):
    calls = []
    monkeypatch.setattr(cp, "list_projects", lambda p: calls.append(("projects", p)) or (200, {"success": True, "projects": []}))
    monkeypatch.setattr(cp, "list_tasks", lambda p: calls.append(("tasks", p)) or (200, {"success": True, "tasks": []}))
    monkeypatch.setattr(cp, "get_task", lambda i: calls.append(("task", i)) or (200, {"success": True, "task": {"id": i}}))
    monkeypatch.setattr(cp, "create_task", lambda b: calls.append(("create", b)) or (201, {"success": True, "task": {"id": 5}}))
    monkeypatch.setattr(cp, "task_action", lambda i, a, b: calls.append(("action", i, a, b)) or (202, {"success": True}))
    monkeypatch.setattr(cp, "build_apply", lambda i: calls.append(("apply", i)) or (202, {"success": True, "approval_id": 9}))
    c = _app().test_client()
    _login(c)
    assert c.get("/api/cockpit/projects?status=active").status_code == 200
    assert c.get("/api/cockpit/tasks?q=x&limit=5").status_code == 200
    assert c.get("/api/cockpit/tasks/7").get_json()["task"]["id"] == 7
    assert c.post("/api/cockpit/tasks", json={"project_id": 343, "title": "T"}).status_code == 201
    assert c.post("/api/cockpit/tasks/7/delegate", json={"capability": "research"}).status_code == 202
    assert c.post("/api/cockpit/build/1202345/apply").get_json()["approval_id"] == 9
    assert calls[0] == ("projects", {"status": "active"}) and calls[1] == ("tasks", {"q": "x", "limit": "5"})
    assert calls[2] == ("task", 7) and calls[3] == ("create", {"project_id": 343, "title": "T"})
    assert calls[4] == ("action", 7, "delegate", {"capability": "research"}) and calls[5] == ("apply", 1202345)


def test_task_hub_errors_are_verbatim(monkeypatch):
    monkeypatch.setattr(cp, "task_action", lambda i, a, b: (400, {"success": False, "error": "unknown capability 'reserch'; nearest: research"}))
    c = _app().test_client()
    _login(c)
    r = c.post("/api/cockpit/tasks/7/delegate", json={"capability": "reserch"})
    assert r.status_code == 400 and r.get_json()["error"].startswith("unknown capability")
```

- [ ] **Step 2: Run to verify they fail**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_routes.py 2>&1 | tail -3`
Expected: `4 failed` (13 rules, 404s).

- [ ] **Step 3: Implement** — append to `cockpit_routes.py`:

```python
# ---- Work pane: projects + tasks (#6679 Phase 4b) --------------------------------------
@cockpit_bp.route("/api/cockpit/projects", methods=["GET"])
@_require_session
def cockpit_projects():
    return _pass(cp.list_projects(request.args.to_dict()))


@cockpit_bp.route("/api/cockpit/tasks", methods=["GET"])
@_require_session
def cockpit_tasks():
    return _pass(cp.list_tasks(request.args.to_dict()))


@cockpit_bp.route("/api/cockpit/tasks/<int:task_id>", methods=["GET"])
@_require_session
def cockpit_task(task_id):
    return _pass(cp.get_task(task_id))


@cockpit_bp.route("/api/cockpit/tasks", methods=["POST"])
@_require_session
def cockpit_task_create():
    return _pass(cp.create_task(request.get_json(silent=True) or {}))


@cockpit_bp.route("/api/cockpit/tasks/<int:task_id>/<action>", methods=["POST"])
@_require_session
def cockpit_task_action(task_id, action):
    return _pass(cp.task_action(task_id, action, request.get_json(silent=True) or {}))


# ---- Code Builder: apply (#6680 Phase 4b) ----------------------------------------------
@cockpit_bp.route("/api/cockpit/build/<int:job_id>/apply", methods=["POST"])
@_require_session
def cockpit_build_apply(job_id):
    return _pass(cp.build_apply(job_id))
```

- [ ] **Step 4: Run to verify they pass**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_routes.py 2>&1 | tail -3`
Expected: all pass (11).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/archie-comms/cockpit_routes.py /mnt/archie_brain/archie-comms/tests/test_cockpit_routes.py
git commit -m "feat(comms): cockpit routes for projects, tasks, task actions and build apply — 19 rules (#6679 #6680 Phase 4b)"
```

---

### Task 11: template + CSS — Work pane, switch, task sheet, `+ Task` form, target file, 4th tab

**Files:**
- Modify: `archie-comms/templates/cockpit.html:24-33` (switch above the crew pane), after `:46` (new `#pane-work`, `#ck-task`, `#ck-task-new`), `:55-62` (compose form), `:74-78` (tabs)
- Modify: `archie-comms/static/css/cockpit.css` (base + both media blocks)
- Test: `archie-comms/tests/test_cockpit_page.py` (append)

**Interfaces:**
- Produces the ids the JS binds (Task 12): `ck-switch` (with two `button[data-left="crew|work"]`), `pane-work`, `ck-work-total`, `ck-task-open`, `ck-work-search`, `ck-work-chips`, `ck-work-list`, `ck-work-more`, `ck-task` (sheet, `aria-label="Task"`), `ck-task-close`, `ck-task-title`, `ck-task-body`, `ck-task-new` (form, `aria-label` via `<h3>`), `ck-task-new-project`, `ck-target` (input `name="target_path"`), a tab `button[data-pane="work"]`.

- [ ] **Step 1: Write the failing tests** — in `archie-comms/tests/test_cockpit_page.py` the module-level constants `HTML`, `CSS` and `JS` already hold the three files and `IDS` lists every id the JS binds (`test_template_has_every_id_the_js_binds` checks each one). Extend `IDS` with `"ck-switch", "pane-work", "ck-work-total", "ck-task-open", "ck-work-search", "ck-work-chips", "ck-work-list", "ck-work-more", "ck-task", "ck-task-close", "ck-task-title", "ck-task-body", "ck-task-new", "ck-task-new-project", "ck-target"`, then append:

```python
def test_template_has_the_work_pane_switch_sheet_form_and_target_field():
    html = HTML
    for needle in (
        'id="ck-switch"', 'data-left="crew"', 'data-left="work"',
        'id="pane-work"', 'aria-label="Work"', 'id="ck-work-total"', 'id="ck-task-open"', 'id="ck-work-search"',
        'id="ck-work-chips"', 'id="ck-work-list"', 'id="ck-work-more"',
        'id="ck-task"', 'aria-label="Task"', 'id="ck-task-close"', 'id="ck-task-title"', 'id="ck-task-body"',
        'id="ck-task-new"', 'id="ck-task-new-project"', 'name="title"', 'name="priority"', 'name="task_type"',
        'id="ck-target"', 'name="target_path"', 'data-pane="work"',
    ):
        assert needle in html, needle
    assert html.count('data-pane="') == 4


def test_css_places_the_work_pane_and_task_sheet_like_crew_and_agent():
    css = CSS
    assert "#pane-crew, #pane-work, #pane-builder { display: flex; }" not in css, "work and crew share a cell — only one shows"
    assert ".ck-switch" in css and ".ck-switch button[aria-pressed=\"true\"]" in css
    assert "#ck-task" in css and "#ck-task[hidden] { display: flex; }" in css
    assert "#pane-work.ck-show" in css or ".ck-left-work #pane-work" in css
```

- [ ] **Step 2: Run to verify they fail**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py 2>&1 | tail -3`
Expected: `2 failed`.

- [ ] **Step 3a: template** — in `templates/cockpit.html`:

(1) Immediately after `<main class="ck-main">` (line 24) and before `<section id="pane-crew"`, insert the left-column switch:

```html
    <div id="ck-switch" class="ck-switch" role="group" aria-label="Left column">
      <button type="button" data-left="crew" aria-pressed="true">Crew</button>
      <button type="button" data-left="work" aria-pressed="false">Work</button>
    </div>
```

(2) After the closing `</section>` of `#pane-crew` (after line 46, before `<section id="ck-agent"`), insert the Work pane and its sheets:

```html
    <section id="pane-work" class="ck-pane" aria-label="Work">
      <div class="ck-pane-head">
        <h2>Work <span id="ck-work-total" class="ck-count"></span></h2>
        <button id="ck-task-open" class="ck-btn ck-primary" type="button">+ Task</button>
      </div>
      <input id="ck-work-search" class="ck-search" type="search" placeholder="Search tasks…" autocomplete="off">
      <div id="ck-work-chips" class="ck-chips" role="group" aria-label="Task filters"></div>
      <div id="ck-work-list" class="ck-roster" role="list"></div>
      <button id="ck-work-more" class="ck-btn ck-block" type="button" hidden>Load more</button>

      <form id="ck-task-new" class="ck-sheet ck-form" hidden>
        <div class="ck-sheet-head"><button type="button" class="ck-back" data-close="ck-task-new">‹ Work</button><h3>New task</h3></div>
        <label>Project <select name="project_id" id="ck-task-new-project" required></select></label>
        <label>Title <input name="title" required maxlength="500"></label>
        <label>Description <textarea name="description" rows="3"></textarea></label>
        <div class="ck-two">
          <label>Priority <select name="priority"><option>1</option><option>2</option><option>3</option><option>4</option><option selected>5</option><option>6</option><option>7</option><option>8</option><option>9</option><option>10</option></select></label>
          <label>Type <select name="task_type"><option>implementation</option><option>bugfix</option><option>research</option><option>testing</option><option>review</option><option>documentation</option></select></label>
        </div>
        <button class="ck-btn ck-primary ck-block" type="submit">Create task</button>
      </form>
    </section>

    <section id="ck-task" class="ck-pane ck-sheet" aria-label="Task" hidden>
      <div class="ck-sheet-head"><button id="ck-task-close" type="button" class="ck-back">‹ Work</button><h3 id="ck-task-title"></h3></div>
      <div id="ck-task-body"></div>
    </section>
```

(3) In the compose form, after the `<label>Prompt …</label>` line (line 60) and before the `<details>`, insert:

```html
        <label>Target file (optional) <input id="ck-target" name="target_path" placeholder="platform_v2/… — the model gets the current file and returns the whole file" autocomplete="off"></label>
```

(4) In `#ck-tabs`, after the Crew button, insert `<button type="button" data-pane="work">Work</button>`.

- [ ] **Step 3b: CSS** — in `static/css/cockpit.css`:

Base (append after the `.ck-toast.ck-err` rule, line 72):

```css
.ck-switch { display: none; gap: 6px; margin-bottom: 8px; }
.ck-switch button { font: inherit; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: #8b90b3; background: none; border: 1px solid #2a2a55; border-radius: 6px; padding: 4px 10px; cursor: pointer; }
.ck-switch button[aria-pressed="true"] { color: #00d4ff; border-color: #00d4ff; }
.ck-task-notes { display: flex; flex-direction: column; gap: 6px; }
.ck-note { font-size: 12px; color: #c9cce0; border-left: 2px solid #2a2a55; padding-left: 8px; }
.ck-note-ts { display: block; font-size: 10px; color: #8b90b3; }
.ck-group-head { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #8b90b3; text-transform: uppercase; letter-spacing: .08em; padding: 6px 0 2px; cursor: pointer; }
.ck-group-head .ck-num { color: #c9cce0; }
```

In the `@media (min-width: 768px)` block replace `#pane-crew, #pane-builder { display: flex; }` with:

```css
  .ck-switch { display: flex; grid-column: 1; }
  #pane-crew, #pane-builder { display: flex; }
  body.ck-left-work #pane-crew { display: none; }
  body.ck-left-work #pane-work { display: flex; }
  #pane-crew, #pane-work { grid-column: 1; grid-row: 2; }
  #pane-builder { grid-column: 2; grid-row: 1 / span 2; }
```

In the `@media (min-width: 1024px)` block replace `#pane-crew, #pane-builder, #ck-agent { display: flex; }` with:

```css
  #pane-crew, #pane-builder, #ck-agent, #ck-task { display: flex; }
  body.ck-left-work #ck-agent { display: none; }
  body:not(.ck-left-work) #ck-task { display: none; }
  #ck-agent, #ck-task { position: static; padding: 0; background: transparent; grid-column: 2; grid-row: 1 / span 2; }
  #ck-agent[hidden], #ck-task[hidden] { display: flex; }
  #ck-agent-close, #ck-task-close { display: none; }
  #pane-builder { grid-column: 3; grid-row: 1 / span 2; }
```

and keep the existing `#ck-agent { position: static; … }` / `#ck-agent[hidden] { display: flex; }` / `#ck-agent-close { display: none; }` lines removed (they are folded into the lines above — the file must not carry both).

- [ ] **Step 4: Run to verify they pass**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py 2>&1 | tail -3`
Expected: all pass (the existing `test_css_has_the_three_breakpoints_and_the_desktop_grid` still passes — the grid line is unchanged).

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/archie-comms/templates/cockpit.html /mnt/archie_brain/archie-comms/static/css/cockpit.css /mnt/archie_brain/archie-comms/tests/test_cockpit_page.py
git commit -m "feat(comms): cockpit Work pane, task sheet, + Task form, target file field, fourth tab — markup + CSS (#6679 #6680 Phase 4b)"
```

---

### Task 12: JS — Work pane logic, task sheet, create/act/delegate, Apply

**Files:**
- Modify: `archie-comms/static/js/cockpit.js` — `PANES`/`showPane` (`:29-35`), compose submit (`:192-201`), `renderJobs` (`:216-234`), and a new Work section inserted before the `// ---- Approvals` comment (`:245`)
- Test: `archie-comms/tests/test_cockpit_page.py` (append)

**Interfaces:**
- Consumes: Task 10 routes; Task 11 ids.
- Produces: `WORK_POLL_MS = 30000`; functions `loadWork(reset)`, `openTask(id)`, `renderTask(t)`, `taskAct(id, action, body, okMsg)`, `applyJob(id)`; left-column choice persisted in `localStorage['ck-left']`.

- [ ] **Step 1: Write the failing tests** — append to `archie-comms/tests/test_cockpit_page.py`:

```python
def test_js_wires_the_work_pane_and_apply():
    js = JS
    assert "work: 'pane-work'" in js and "const WORK_POLL_MS = 30000" in js
    for needle in ("/api/cockpit/projects", "/api/cockpit/tasks", "'/api/cockpit/tasks/' + id + '/' + action", "/api/cockpit/build/' + id + '/apply'", "target_path", "localStorage"):
        assert needle in js, needle
    assert "function loadWork(" in js and "function openTask(" in js and "function taskAct(" in js and "function applyJob(" in js
    assert "window.prompt" not in js.split("// ---- Work")[1].split("// ---- Approvals")[0], "task actions use inline inputs, not prompts"
    assert ".innerHTML" not in JS and "insertAdjacentHTML" not in JS


def test_js_shows_apply_only_for_completed_targeted_unapplied_jobs():
    js = JS
    assert "j.status === 'completed' && j.target_path && !j.pr_number" in js
    assert "'PR #' + j.pr_number" in js and "j.apply_error" in js
```

- [ ] **Step 2: Run to verify they fail**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/test_cockpit_page.py 2>&1 | tail -3`
Expected: `2 failed`.

- [ ] **Step 3a: panes** — replace lines 29–35 (`const PANES … }` through the end of `showPane`) with:

```javascript
  const PANES = { crew: 'pane-crew', work: 'pane-work', builder: 'pane-builder', approvals: 'pane-approvals' };
  let leftChoice = 'crew';
  try { leftChoice = localStorage.getItem('ck-left') === 'work' ? 'work' : 'crew'; } catch (e) { /* private mode */ }
  function setLeft(name) {
    leftChoice = name === 'work' ? 'work' : 'crew';
    try { localStorage.setItem('ck-left', leftChoice); } catch (e) { /* ignore */ }
    document.body.classList.toggle('ck-left-work', leftChoice === 'work');
    document.querySelectorAll('#ck-switch button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.left === leftChoice)));
  }
  function showPane(name) {
    Object.keys(PANES).forEach((k) => { $(PANES[k]).classList.toggle('ck-show', k === name); });
    document.querySelectorAll('#ck-tabs button').forEach((b) => b.classList.toggle('ck-tab-on', b.dataset.pane === name));
    if (name === 'crew' || name === 'work') setLeft(name);
    if (name !== 'crew') { $('ck-agent').classList.remove('ck-show'); $('ck-hire').hidden = true; }
    if (name !== 'work') { $('ck-task').classList.remove('ck-show'); $('ck-task-new').hidden = true; }
    if (name === 'work' && !workLoaded) loadWork(true);
  }
  document.querySelectorAll('#ck-switch button').forEach((b) => b.addEventListener('click', () => { location.hash = b.dataset.left; showPane(b.dataset.left); }));
```

(`workLoaded` is declared in the Work section below; function declarations hoist, `let` does not — so the Work section's `let workLoaded = false;` must be placed ABOVE the first call, i.e. the Work section goes before the initial `showPane(paneFromHash())` call at the bottom of the file. Find that call with `grep -n "showPane(paneFromHash())" cockpit.js` and make sure the Work section precedes it.) Also, when the page boots with `leftChoice === 'work'` and no hash, open Work: change `paneFromHash` to `function paneFromHash() { const h = (location.hash || ('#' + leftChoice)).slice(1); return PANES[h] ? h : 'crew'; }`.

- [ ] **Step 3b: compose + jobs** — in the compose submit handler (line 194) change the body line to:

```javascript
    const body = { prompt: $('ck-prompt').value.trim(), provider: $('ck-provider').value, model: $('ck-model').value };
    const target = $('ck-target').value.trim(); if (target) body.target_path = target;
```

In `renderJobs`, after the line that appends the `ck-sub ck-num` requested/served line, add:

```javascript
      if (j.target_path) card.appendChild(mk('div', 'ck-sub ck-num', 'target ' + j.target_path));
      if (j.pr_number) { const a = mk('a', 'ck-sub', 'PR #' + j.pr_number); a.href = j.pr_url || '#'; a.target = '_blank'; a.rel = 'noopener'; card.appendChild(a); }
      else if (j.apply_error) card.appendChild(mk('div', 'ck-sub ck-bad', 'apply: ' + j.apply_error));
      else if (j.apply_approval_id) card.appendChild(mk('div', 'ck-sub', 'apply waits for approval #' + j.apply_approval_id));
```

and after the `card.appendChild(open);` line add:

```javascript
      if (j.status === 'completed' && j.target_path && !j.pr_number && !j.apply_approval_id) {
        const ap = mk('button', 'ck-btn ck-primary ck-small', 'Apply — needs your approval'); ap.type = 'button';
        ap.addEventListener('click', () => applyJob(j.job_id)); card.appendChild(ap);
      }
```

then add, right after the `showJobDetail` function:

```javascript
  async function applyJob(id) {
    const res = await api('/api/cockpit/build/' + id + '/apply', { method: 'POST', body: {} });
    if (!res.ok || res.data.success === false) { toast('Apply: ' + errText(res), true); return; }
    toast('Apply waits for your approval — #' + res.data.approval_id + ' in Approvals or Telegram');
    loadJobs(); loadApprovals();
  }
```

- [ ] **Step 3c: Work section** — insert before the `// ---- Approvals (tab on phone, strip on desktop)` comment:

```javascript
  // ---- Work: projects + tasks (#6679 Phase 4b) --------------------------------------
  const WORK_POLL_MS = 30000; const TASK_PAGE = 50;
  let workLoaded = false;
  const work = { q: '', project_id: '', status: 'pending,in_progress,blocked', min_priority: '', offset: 0, total: 0, projects: [], facets: { status: {}, projects: {}, capabilities: [] }, collapsed: new Set() };
  let workSearchTimer = null;
  $('ck-work-search').addEventListener('input', (e) => { clearTimeout(workSearchTimer); workSearchTimer = setTimeout(() => { work.q = e.target.value.trim(); loadWork(true); }, 250); });
  $('ck-work-more').addEventListener('click', () => { work.offset += TASK_PAGE; loadWork(false); });

  function workChip(label, on, onClick) { const b = mk('button', 'ck-chip', label); b.type = 'button'; b.setAttribute('aria-pressed', String(!!on)); b.addEventListener('click', onClick); return b; }
  function renderWorkChips() {
    const box = $('ck-work-chips'); box.textContent = '';
    const current = new Set(work.status.split(',').filter(Boolean));
    ['pending', 'in_progress', 'blocked', 'completed', 'cancelled'].forEach((s) => {
      const n = work.facets.status[s]; if (n == null && !current.has(s)) return;
      box.appendChild(workChip(s + (n != null ? ' · ' + n : ''), current.has(s), () => { if (current.has(s)) current.delete(s); else current.add(s); work.status = Array.from(current).join(',') || 'pending'; loadWork(true); }));
    });
    box.appendChild(workChip('priority ≥ 8', work.min_priority === '8', () => { work.min_priority = work.min_priority === '8' ? '' : '8'; loadWork(true); }));
    Object.keys(work.facets.projects).sort((a, b) => work.facets.projects[a].localeCompare(work.facets.projects[b])).forEach((pid) => {
      box.appendChild(workChip(work.facets.projects[pid], work.project_id === pid, () => { work.project_id = work.project_id === pid ? '' : pid; loadWork(true); }));
    });
  }
  function prioPill(p) { const el = mk('span', 'ck-pill ck-num', 'P' + (p == null ? '?' : p)); if (p >= 8) el.classList.add('ck-state-active'); return el; }
  async function loadWork(reset) {
    if (reset) work.offset = 0;
    const qs = new URLSearchParams({ q: work.q, project_id: work.project_id, status: work.status, min_priority: work.min_priority, limit: String(TASK_PAGE), offset: String(work.offset) });
    const [pr, tr] = await Promise.all([api('/api/cockpit/projects?limit=200'), api('/api/cockpit/tasks?' + qs.toString())]);
    const list = $('ck-work-list');
    if (!pr.ok) { toast('Projects: ' + errText(pr), true); return; }
    if (!tr.ok) { toast('Tasks: ' + errText(tr), true); return; }
    workLoaded = true;
    work.projects = pr.data.projects || []; work.total = tr.data.total || 0; work.facets = tr.data.facets || work.facets;
    $('ck-work-total').textContent = '· ' + work.total;
    renderWorkChips();
    if (reset) list.textContent = '';
    const byProject = new Map();
    (tr.data.tasks || []).forEach((t) => { const k = String(t.project_id); if (!byProject.has(k)) byProject.set(k, []); byProject.get(k).push(t); });
    byProject.forEach((tasks, pid) => {
      let group = list.querySelector('[data-project="' + pid + '"]');
      if (!group) {
        group = mk('div', 'ck-group'); group.dataset.project = pid;
        const p = work.projects.find((x) => String(x.id) === pid) || {};
        const head = mk('div', 'ck-group-head');
        head.appendChild(mk('span', null, (tasks[0].project_name || p.name || 'project ' + pid) + (p.status ? ' · ' + p.status : '')));
        head.appendChild(mk('span', 'ck-num', (p.open_tasks != null ? p.open_tasks + ' open / ' + p.total_tasks : String(tasks.length))));
        head.addEventListener('click', () => { if (work.collapsed.has(pid)) work.collapsed.delete(pid); else work.collapsed.add(pid); group.classList.toggle('ck-collapsed', work.collapsed.has(pid)); });
        group.appendChild(head); group.appendChild(mk('div', 'ck-group-body'));
        group.classList.toggle('ck-collapsed', work.collapsed.has(pid));
        list.appendChild(group);
      }
      const body = group.querySelector('.ck-group-body');
      tasks.forEach((t) => {
        const card = mk('button', 'ck-card'); card.type = 'button';
        const row = mk('div', 'ck-row'); row.appendChild(mk('span', 'ck-name', t.title)); row.appendChild(prioPill(t.priority)); row.appendChild(pill(t.status));
        card.appendChild(row);
        card.appendChild(mk('div', 'ck-sub', [t.task_type || '—', t.agent_name || (t.delegation_source ? 'fleet · ' + t.delegation_source : '')].filter(Boolean).join(' · ')));
        card.addEventListener('click', () => openTask(t.id));
        body.appendChild(card);
      });
    });
    if (!list.childElementCount) list.appendChild(mk('div', 'ck-empty', 'No tasks match.'));
    $('ck-work-more').hidden = work.offset + TASK_PAGE >= work.total;
    const sel = $('ck-task-new-project'); sel.textContent = '';
    work.projects.forEach((p) => { const o = mk('option', null, p.name); o.value = String(p.id); sel.appendChild(o); });
  }

  let currentTask = null; let taskWatch = null;
  async function openTask(id) {
    const res = await api('/api/cockpit/tasks/' + id);
    if (!res.ok) { toast('Task: ' + errText(res), true); return; }
    currentTask = res.data.task; renderTask(currentTask);
    $('ck-task').hidden = false; $('ck-task').classList.add('ck-show');
    clearInterval(taskWatch);
    if (currentTask.delegation_source && (currentTask.status === 'pending' || currentTask.status === 'in_progress')) taskWatch = setInterval(() => openTask(id), 10000);
  }
  $('ck-task-close').addEventListener('click', () => { $('ck-task').classList.remove('ck-show'); $('ck-task').hidden = true; clearInterval(taskWatch); });
  function renderTask(t) {
    $('ck-task-title').textContent = t.title || ('#' + t.id);
    const body = $('ck-task-body'); body.textContent = '';
    body.appendChild(mk('div', 'ck-sub', [t.project_name || '—', t.task_type || '—', 'priority ' + (t.priority == null ? '—' : t.priority), t.agent_name || ''].filter(Boolean).join(' · ')));
    const row0 = mk('div', 'ck-row'); row0.appendChild(pill(t.status)); if (t.delegation_source) row0.appendChild(mk('span', 'ck-sub', 'delegated · ' + ((t.delegation_args || {}).capability || '?') + ' · ' + t.status)); body.appendChild(row0);
    if (t.description) { const d = mk('div', 'ck-sub'); d.textContent = t.description; body.appendChild(d); }
    body.appendChild(mk('div', 'ck-sect', 'Actions'));
    const stSel = mk('select', 'ck-select'); ['pending', 'in_progress', 'blocked', 'completed', 'cancelled'].forEach((s) => { const o = mk('option', null, s); o.value = s; if (s === t.status) o.selected = true; stSel.appendChild(o); });
    const stBtn = mk('button', 'ck-btn ck-small', 'Set'); stBtn.type = 'button'; stBtn.addEventListener('click', () => taskAct(t.id, 'status', { status: stSel.value }, 'Status → ' + stSel.value));
    const r1 = mk('div', 'ck-row'); r1.appendChild(stSel); r1.appendChild(stBtn); body.appendChild(r1);
    const prSel = mk('select', 'ck-select'); for (let i = 1; i <= 10; i++) { const o = mk('option', null, String(i)); o.value = String(i); if (i === t.priority) o.selected = true; prSel.appendChild(o); }
    const prBtn = mk('button', 'ck-btn ck-small', 'Set'); prBtn.type = 'button'; prBtn.addEventListener('click', () => taskAct(t.id, 'priority', { priority: parseInt(prSel.value, 10) }, 'Priority → ' + prSel.value));
    const r2 = mk('div', 'ck-row'); r2.appendChild(mk('span', 'ck-sub', 'priority')); r2.appendChild(prSel); r2.appendChild(prBtn); body.appendChild(r2);
    const noteBox = mk('textarea', 'ck-select'); noteBox.rows = 2; noteBox.placeholder = 'Add a note…'; noteBox.maxLength = 2000;
    const noteBtn = mk('button', 'ck-btn ck-small', 'Add note'); noteBtn.type = 'button';
    noteBtn.addEventListener('click', () => { const text = noteBox.value.trim(); if (!text) return; taskAct(t.id, 'note', { text }, 'Note added').then(() => { noteBox.value = ''; }); });
    const r3 = mk('div', 'ck-row'); r3.appendChild(noteBox); r3.appendChild(noteBtn); body.appendChild(r3);
    const capSel = mk('select', 'ck-select'); (work.facets.capabilities || []).forEach((c) => { const o = mk('option', null, c); o.value = c; capSel.appendChild(o); });
    const dlBtn = mk('button', 'ck-btn ck-primary ck-small', 'Delegate to fleet'); dlBtn.type = 'button';
    dlBtn.disabled = !(t.status === 'pending' || t.status === 'blocked') || !!(t.delegation_source && t.status === 'pending');
    dlBtn.addEventListener('click', () => taskAct(t.id, 'delegate', { capability: capSel.value }, 'Delegated — the fleet claims it within 30 s'));
    const r4 = mk('div', 'ck-row'); r4.appendChild(capSel); r4.appendChild(dlBtn); body.appendChild(r4);
    body.appendChild(mk('div', 'ck-sect', 'Notes'));
    const notes = mk('div', 'ck-task-notes');
    (t.notes || []).forEach((n) => { const el = mk('div', 'ck-note', n.text); const ts = mk('span', 'ck-note-ts', (n.author || '') + ' · ' + (n.ts || '')); el.appendChild(ts); notes.appendChild(el); });
    if (!(t.notes || []).length) notes.appendChild(mk('div', 'ck-empty', 'No notes yet.'));
    body.appendChild(notes);
  }
  async function taskAct(id, action, body, okMsg) {
    const res = await api('/api/cockpit/tasks/' + id + '/' + action, { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast(okMsg);
    await openTask(id); loadWork(true);
  }

  $('ck-task-open').addEventListener('click', () => { $('ck-task-new').hidden = false; $('ck-task-new').classList.add('ck-show'); });
  document.querySelectorAll('[data-close="ck-task-new"]').forEach((b) => b.addEventListener('click', () => { $('ck-task-new').classList.remove('ck-show'); $('ck-task-new').hidden = true; }));
  $('ck-task-new').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { project_id: parseInt(f.get('project_id'), 10), title: String(f.get('title') || '').trim(), description: String(f.get('description') || '').trim(), priority: parseInt(f.get('priority'), 10), task_type: String(f.get('task_type') || 'implementation') };
    const res = await api('/api/cockpit/tasks', { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast('Task #' + res.data.task.id + ' created');
    $('ck-task-new').classList.remove('ck-show'); $('ck-task-new').hidden = true; e.target.reset(); loadWork(true);
  });
  setInterval(() => { if (workLoaded && $('pane-work').classList.contains('ck-show')) loadWork(true); }, WORK_POLL_MS);
```

Then apply the `ck-left-work` body class at boot: right after `setLeft` is defined, call `setLeft(leftChoice);` once (before the initial `showPane(paneFromHash())`). CSS for the collapsed group: append to the CSS base block `.ck-group.ck-collapsed .ck-group-body { display: none; }`. The chips reuse the roster's existing `.ck-chip` + `.ck-chip[aria-pressed="true"]` rules (`cockpit.css:19-20`) — no new chip CSS.

- [ ] **Step 4: Run to verify they pass**

Run: `bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh -q tests/ 2>&1 | tail -3` and `node --check /mnt/archie_brain/archie-comms/static/js/cockpit.js`
Expected: whole comms suite green; `node --check` silent.

- [ ] **Step 5: Commit**

```bash
git add /mnt/archie_brain/archie-comms/static/js/cockpit.js /mnt/archie_brain/archie-comms/static/css/cockpit.css /mnt/archie_brain/archie-comms/tests/test_cockpit_page.py
git commit -m "feat(comms): cockpit Work pane logic, task sheet with status/priority/note/delegate, + Task, Apply (#6679 #6680 Phase 4b)"
```

---

### Task 13: comms PR — review, merge, rebuild, live acceptance at 390 px and 1280 px, Dev HQ

**Files:** none new.

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/phase4b-comms
gh pr create --title "feat(phase4b): cockpit Work pane (tasks & projects) + Apply on a Builder result (#6679 #6680)" --body "$(cat <<'EOF'
## Summary
- Work pane (Crew ⇄ Work switch on the left column, 4th phone tab): projects grouped with their tasks, status/priority/project chips, search, `+ Task`; task sheet with status, priority, inline note, delegate-to-fleet (capabilities from the hub's facets).
- Builder: `target file` field; completed targeted jobs show `Apply — needs your approval`; the job card shows the approval, the PR link, or the apply error verbatim.
- Proxy + routes are pass-through (19 rules); comms still holds no SQL. Spec: docs/superpowers/specs/2026-09-10-phase4b-work-pane-and-apply-design.md.

## Test Plan
- [x] tests/test_cockpit_proxy.py (10) · test_cockpit_routes.py (11) · test_cockpit_page.py (+4) · whole comms suite green via scripts/run_tests.sh · node --check
- [ ] live acceptance at 390 px and 1280 px after `docker compose up -d --build archie_comms` (below)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0199Q3QGc4qizTT4bugJHBa6
EOF
)"
```

- [ ] **Step 2: Register + F.O.R.G.E. review + merge on a clean APPROVE** — same as Task 8 Step 3 (coverage demotion → independent full read of the dropped files; the JS and template are long, expect it).

- [ ] **Step 3: Rebuild comms from `main`**

```bash
cd /mnt/archie_brain && git checkout main && git pull --ff-only origin main && docker compose up -d --build archie_comms && docker compose ps archie_comms
```
Expected: healthy within ~30 s; `docker exec archie_comms ls -a /app | grep -c '^\.env$'` → 0.

- [ ] **Step 4: Live acceptance** (hub Playwright; the SSO leg lands on `http://192.168.1.200:3002` — keep working on that origin; `window.prompt` is gone from the Work pane, so no dialog handling there; run at 390×844 then 1280×800; screenshots via `page.screenshot({path:'/mnt/archie_brain/.playwright-mcp/<name>.png'})` then copied to the job tmp dir and deleted from the repo root if any land there)

1. `/cockpit` → Work tab (phone) / Work switch (desktop) → groups render with `open/total` counts; `Work · <n>` > 0.
2. `+ Task` → project `Kytran Empowerment — Master Platform Vision & Delivery Plan` (343), title `Phase 4b acceptance probe`, priority 7, type testing → toast `Task #<id> created` → DB `SELECT status, priority, metadata->>'created_via' FROM unified_tasks WHERE id=<id>` → `pending | 7 | cockpit`.
3. Open it → status `in_progress` + Set → DB `started_at` not null → priority 9 → DB → note `probe note` → DB `metadata->'notes'->-1->>'text'`.
4. Status back to `pending` → Delegate with capability `research` → toast → within 60 s: DB `delegation_source='cockpit'`, `delegation_args->>'capability'='research'`, and the row leaves `pending` (worker claimed) — the sheet's 10 s watch shows the status change → when it finishes (`completed` or `blocked`), set `cancelled` (or leave `completed`), and DB check.
5. Builder: provider OmniRoute, model `oc/big-pickle`, target `docs/cockpit-apply-probe.md`, prompt `Write a two-line markdown note saying this file was written by the cockpit apply probe.` → Run → approve the dispatch (strip) → completed → the card shows `target docs/cockpit-apply-probe.md` and `Apply — needs your approval` → click → toast with approval id → approval appears in the strip AND Telegram (`docker logs archie_platform --since 2m | grep -E "Tier-2 awaiting approval: cloud_code_apply"`) → Approve → within 60 s the card shows `PR #<n>` → DB `SELECT metadata->>'pr_number', metadata->>'branch', metadata->>'apply_error' FROM bridge_jobs WHERE id=<job>` → `gh pr view <n> --json title,headRefName,labels,files` → title `[cockpit] docs/cockpit-apply-probe.md: …`, head `cockpit/apply-<job>-docs-cockpit-apply-probe-md`, label `cockpit-apply`, one file → F.O.R.G.E. picks it up (`get_review(n)` exists) and it is GATED from auto-merge (log line `GATED from auto-merge`) → `gh pr close <n> --delete-branch`.
6. Negative: re-click Apply on the same job → `already applied as PR #n` toast (409 verbatim).
7. `escalation_mode` still `local_only`. Console: no errors other than the known hub-saturation 503 class (#6681).
8. Screenshots: `cockpit-390-work.png`, `cockpit-390-task.png`, `cockpit-1280-work.png`, `cockpit-1280-apply.png`.
9. Clean up: delete the probe task row (`DELETE FROM unified_tasks WHERE id=<id>`), leave the closed PR as evidence.

- [ ] **Step 5: Dev HQ + handoff**

- `mcp__archie__add_work_note` (Phase 4b shipped: both PR numbers, acceptance evidence incl. the closed probe PR number).
- `mcp__archie__complete_task(6679)` and `complete_task(6680)` with verification notes.
- `mcp__archie__log_decision(title="Phase 4b: cockpit Apply goes through the hub's PR primitives behind a Tier-2 approval and a human-merge gate", decision="Target file up front (hub reads it from main via the read token, includes it in the prompt, binds the approval to the blob sha and a content hash); the executor composes create_branch/push_changes(content_overrides)/create_pr; cockpit/ PRs are never auto-merged. The Work pane is backed by a single-writer task_service under tasks:read/tasks:write, comms-only; delegation stamps the same unified_tasks row for the existing worker.", context="Owner decisions 2026-09-10: triage + delegate; target file up front; task service; hub path.", project_id=343, task_id=6680)`.
- `mcp__archie__create_task` ×3 (project 343): "Converge mcp_server/tools/project_tools.py and devhq_routes.py onto services/task_service (fix the 'medium' priority default and the phantom assigned_to_user column)"; "Resolve the priority sort disagreement (cockpit + MCP DESC vs Dev HQ ASC)"; "Cockpit Apply: sandbox test gate via a synthetic Repair Bay proposal".
- `mcp__archie__update_project_understanding(343)`; rewrite `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` (Phase 4b done; next Phase 5 TTY lanes; 3b HOLD #6675; #6681 open).

---

## Deferred (explicitly not in this plan)
- Job history search; project create/archive; task delete; other target repos; the sandbox test gate; MCP/Dev HQ convergence (filed as tasks in Task 13); Phase 5 TTY lanes.
