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


class TestReopeningClearsTheDelegation:
    """Reopening a delegated task must not silently re-dispatch it to the fleet.

    ``delegation_service.fetch_pending_delegations`` claims on
    ``delegation_source IS NOT NULL AND status='pending'`` — nothing else. Neither
    ``mark_task_completed`` nor the failure path clears ``delegation_source``, so a
    finished delegation leaves the row one status change away from being claimed
    again. The owner setting a completed task back to ``pending`` from the Work pane
    therefore handed it straight back to the worker within 30 seconds, re-running the
    OLD ``delegation_args`` (the old capability), with nothing in the cockpit saying a
    dispatch had been triggered. ``delegate()`` then refuses with "already queued", so
    the capability could not be corrected either — the task was stuck re-running work
    nobody asked for.

    Reopening is a fresh start. Delegation is explicit (spec §2.2), so it does not
    survive one.
    """

    def _seed_delegated(self, db, seeded, status, source="cockpit", args=None):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO unified_tasks (project_id, title, description, status, priority, "
                "delegation_source, delegation_args) VALUES (%s, %s, 'delegated probe', %s, 5, %s, %s) "
                "RETURNING id",
                (
                    seeded["p1"],
                    f"delegated {seeded['tag']} {status}",
                    status,
                    source,
                    args if args is not None else '{"capability": "research"}',
                ),
            )
            return cur.fetchone()["id"]

    def _row(self, db, task_id):
        with db.cursor() as cur:
            cur.execute(
                "SELECT status, delegation_source, delegation_args FROM unified_tasks WHERE id = %s",
                (task_id,),
            )
            return cur.fetchone()

    def _claimable(self, db, task_id):
        """The worker's OWN predicate, not a paraphrase of it."""
        with db.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM unified_tasks WHERE id = %s AND delegation_source IS NOT NULL " "AND status = 'pending'",
                (task_id,),
            )
            return cur.fetchone() is not None

    def test_completed_to_pending_clears_source_and_args(self, db, seeded):
        tid = self._seed_delegated(db, seeded, "completed")
        assert self._claimable(db, tid) is False, "fixture sanity: a completed row is not claimable"

        ts.set_status(tid, "pending")

        row = self._row(db, tid)
        assert row["status"] == "pending"
        assert row["delegation_source"] is None
        assert row["delegation_args"] is None
        assert self._claimable(db, tid) is False, "reopened task is still claimable — it will re-dispatch"

    def test_blocked_to_pending_clears_it_too(self, db, seeded):
        """The failure path also leaves delegation_source set (delegation_service.py:1266)."""
        tid = self._seed_delegated(db, seeded, "blocked")

        ts.set_status(tid, "pending")

        assert self._claimable(db, tid) is False
        assert self._row(db, tid)["delegation_source"] is None

    def test_a_live_pending_delegation_is_left_alone(self, db, seeded):
        """Non-vacuity: pending -> pending is not a reopen, so it must NOT disarm a queued dispatch."""
        tid = self._seed_delegated(db, seeded, "pending")
        assert self._claimable(db, tid) is True

        ts.set_status(tid, "pending")

        row = self._row(db, tid)
        assert row["delegation_source"] == "cockpit"
        assert self._claimable(db, tid) is True, "a queued delegation was silently cancelled"

    def test_other_transitions_keep_the_delegation_record(self, db, seeded):
        """Only the transition TO pending clears it — completing a task must not erase who ran it."""
        tid = self._seed_delegated(db, seeded, "in_progress", source=None)
        with db.cursor() as cur:
            cur.execute("UPDATE unified_tasks SET delegation_source = 'cockpit' WHERE id = %s", (tid,))
            cur.execute("UPDATE unified_tasks SET status = 'blocked' WHERE id = %s", (tid,))

        ts.set_status(tid, "completed")

        assert self._row(db, tid)["delegation_source"] == "cockpit"

    def test_reopened_task_can_be_delegated_again(self, db, seeded):
        """The user-visible payoff: a reopen restores the ability to choose a capability."""
        tid = self._seed_delegated(db, seeded, "completed")
        ts.set_status(tid, "pending")

        ts.delegate(tid, "research")

        row = self._row(db, tid)
        assert row["delegation_source"] is not None, "delegate() should have re-armed it deliberately"


class TestIntegerArgsRefuseInThisModulesVoice:
    """A validation refusal must reach the caller as a readable 400, not a 500 (#6680 M1).

    ``int(None)`` raises TypeError, and app.py's ``_task_error`` maps TypeError to the
    generic 500 "task read/write failed" — so a Work-pane form submitted with no project
    selected read as a server fault. ``int("abc")`` does raise ValueError (→ 400) but with
    the text "invalid literal for int() with base 10: 'abc'", naming neither the field nor
    the rule (deferred minor m2.1). Both now refuse the way the rest of the module does.
    """

    @pytest.mark.parametrize("bad", [None, "", "   "])
    def test_create_task_without_a_project_says_so(self, bad):
        with pytest.raises(ValueError) as e:
            ts.create_task(bad, "a title")
        assert "project_id" in str(e.value)

    def test_create_task_with_a_non_numeric_project_names_the_field(self):
        with pytest.raises(ValueError) as e:
            ts.create_task("abc", "a title")
        assert "project_id" in str(e.value)
        assert "invalid literal" not in str(e.value), "int()'s own text is not a user-facing message"

    @pytest.mark.parametrize(
        "field,kwargs", [("project_id", {"project_id": "abc"}), ("min_priority", {"min_priority": "xyz"})]
    )
    def test_list_tasks_filters_name_the_field(self, field, kwargs):
        with pytest.raises(ValueError) as e:
            ts.list_tasks(**kwargs)
        assert field in str(e.value)
        assert "invalid literal" not in str(e.value)

    def test_numeric_strings_and_zero_are_still_accepted(self, seeded):
        """Non-vacuity: the coercion must not have become a rejection."""
        rows, total, _ = ts.list_tasks(project_id=str(seeded["p1"]), min_priority=0, limit=200)
        assert total >= 4, "the seeded open tasks should still be found through a string project_id"

    def test_create_task_still_works_with_a_string_project_id(self, seeded):
        task = ts.create_task(str(seeded["p1"]), f"coerced {seeded['tag']}")
        assert task["project_id"] == seeded["p1"]
