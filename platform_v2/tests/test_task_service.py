"""#6679 Phase 4b — task_service is the single writer behind the cockpit Work pane.
Seeds its own rows on an AUTOCOMMIT connection (the service opens its own connections,
so uncommitted fixture rows would be invisible) and cleans them up. Runs in-container:
    docker exec -i archie_platform python3 -m pytest /app/tests/test_task_service.py -q
"""

import uuid

import pytest

from services import task_service as ts


@pytest.fixture
def db():
    # A connection from database.get_db() is POOLED (ThreadedConnectionPool) —
    # setting autocommit/cursor_factory on it and returning it via .close()
    # hands the SAME physical connection back out to the next getconn() caller,
    # still poisoned with both. Bypass the pool entirely with a raw connection
    # instead, mirroring conftest.py's _seed_admin_user fixture (same need).
    import os

    import psycopg2
    import psycopg2.extras

    import database

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        port=os.environ.get("DB_PORT", "5432"),
        user=os.environ.get("DB_USER", "archie"),
        password=database._get_db_password(),
        dbname=os.environ.get("TEST_DB_NAME", "archie_test"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        # Ask the CONNECTION which database it is on, not the environment: DB_NAME can be
        # unset and still resolve to prod through a module-level default (#6016) — the
        # same belt-and-suspenders check as conftest.py's _seed_admin_user fixture.
        cur.execute("SELECT current_database() AS db")
        if cur.fetchone()["db"] == database.PROD_DB_NAME:
            conn.close()
            raise RuntimeError("refusing to seed task_service test rows into production")
    yield conn
    conn.close()


@pytest.fixture
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
    assert mine and mine[0]["open_tasks"] == 4 and mine[0]["total_tasks"] == 6
    assert all(r["id"] != seeded["p2"] for r in rows), "completed projects are not listed by default"
    rows2, _ = ts.list_projects(status="completed", limit=200)
    assert any(r["id"] == seeded["p2"] for r in rows2)


def test_list_tasks_defaults_to_open_and_sorts_priority_desc(seeded):
    rows, total, facets = ts.list_tasks(project_id=seeded["p1"])
    assert total == 4
    assert [r["title"].split(" ")[0] for r in rows] == ["alpha", "charlie", "bravo", "foxtrot"]
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
    assert total == 4 and len(rows) == 2
    with pytest.raises(ValueError):
        ts.list_tasks(status="pending,bogus")


def test_get_task_returns_project_and_notes(seeded):
    t = ts.get_task(seeded["tasks"][0])
    assert t["title"].startswith("alpha") and t["project_name"].startswith("P4B probe")
    assert t["notes"] == [] and t["agent_name"] is None
    assert ts.get_task(-1) is None


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
            cur.execute(
                "SELECT COUNT(*) AS n FROM unified_tasks WHERE delegation_args->'args'->>'origin_task_id' = %s",
                (str(tid),),
            )
            assert cur.fetchone()["n"] == 1
    finally:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE unified_tasks SET delegation_source=NULL, delegation_args=NULL, status='pending' WHERE id=%s",
                (tid,),
            )
