"""Tests for _capture_fix_failure — persists the model's raw reply + attempted find
on a fix-apply failure so the find_not_located/unparseable yield problem is observable.
"""

import json

from database import get_db_cursor
from services.audit_pipeline import _capture_fix_failure


def _insert():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO improvement_proposals (title, description, status, metadata) "
            "VALUES ('fix-debug test','t','approved', %s::jsonb) RETURNING id",
            (json.dumps({"source": "code_health_audit"}),),
        )
        return cur.fetchone()["id"]


def _meta(pid):
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT metadata FROM improvement_proposals WHERE id=%s", (pid,))
        return cur.fetchone()["metadata"]


def test_capture_records_raw_and_find():
    pid = _insert()
    try:
        raw = '{"find": "except:", "replace": "except Exception:"}'
        _capture_fix_failure(pid, raw, "find_not_located")
        dbg = _meta(pid).get("fix_debug")
        assert dbg is not None
        assert dbg["reason"] == "find_not_located"
        assert dbg["raw_response"] == raw
        assert dbg["attempted_find"] == "except:"
        assert dbg.get("captured_at")
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM improvement_proposals WHERE id=%s", (pid,))


def test_capture_tolerates_unparseable_raw():
    pid = _insert()
    try:
        _capture_fix_failure(pid, "not json at all — the model rambled", "unparseable")
        dbg = _meta(pid).get("fix_debug")
        assert dbg["reason"] == "unparseable"
        assert dbg["attempted_find"] == ""  # nothing parseable → empty, not a crash
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM improvement_proposals WHERE id=%s", (pid,))
