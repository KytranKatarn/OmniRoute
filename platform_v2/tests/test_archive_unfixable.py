import json
import pytest
from database import get_db_cursor
from services.audit_pipeline import archive_unfixable_audit_proposals


def _insert(cur, file_path):
    cur.execute(
        """INSERT INTO improvement_proposals (title, description, status, metadata)
           VALUES (%s, %s, 'approved', %s::jsonb) RETURNING id""",
        (
            "scope-filter test",
            "test row",
            json.dumps({"source": "code_health_audit", "file_path": file_path}),
        ),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def temp_proposals():
    ids = {}
    with get_db_cursor(commit=True) as (conn, cur):
        ids["unfixable"] = _insert(cur, "standalone_what_the_fact/app.py")
        ids["junk"] = _insert(cur, "[dispatch_routing]/agents/X/y")
        ids["fixable"] = _insert(cur, "[APP_CORE]/app.py")
    yield ids
    with get_db_cursor(commit=True) as (conn, cur):
        # restore any REAL backlog rows the sweep archived as a table-wide side effect
        cur.execute(
            """UPDATE improvement_proposals
               SET status='approved',
                   metadata = metadata - 'archive_reason' - 'archived_at' - 'archived_by'
               WHERE metadata->>'archived_by'='scope_filter_4940'
                 AND id <> ALL(%s)""",
            (list(ids.values()),),
        )
        cur.execute(
            "DELETE FROM improvement_proposals WHERE id = ANY(%s)",
            (list(ids.values()),),
        )


def _status(pid):
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT status, metadata FROM improvement_proposals WHERE id=%s", (pid,))
        return cur.fetchone()


def test_sweep_archives_unfixable_keeps_fixable(temp_proposals):
    res = archive_unfixable_audit_proposals()
    assert res["archived"] >= 2  # our two unfixable rows (plus any real backlog ones)

    assert _status(temp_proposals["unfixable"])["status"] == "archived"
    assert _status(temp_proposals["junk"])["status"] == "archived"
    assert _status(temp_proposals["fixable"])["status"] == "approved"

    meta = _status(temp_proposals["unfixable"])["metadata"]
    assert meta["archived_by"] == "scope_filter_4940"
    assert meta["archive_reason"] == "out_of_scope:standalone"
    assert _status(temp_proposals["junk"])["metadata"]["archive_reason"] == "not_a_file:routing_label"


def test_sweep_is_idempotent(temp_proposals):
    archive_unfixable_audit_proposals()
    first_archived_at = _status(temp_proposals["unfixable"])["metadata"]["archived_at"]

    archive_unfixable_audit_proposals()

    # second run must not re-process the already-archived row (WHERE status='approved'
    # excludes it) -> status stays archived and archived_at is unchanged
    second_status = _status(temp_proposals["unfixable"])
    assert second_status["status"] == "archived"
    assert second_status["metadata"]["archived_at"] == first_archived_at


def test_dry_run_writes_nothing(temp_proposals):
    archive_unfixable_audit_proposals(dry_run=True)
    assert _status(temp_proposals["unfixable"])["status"] == "approved"
