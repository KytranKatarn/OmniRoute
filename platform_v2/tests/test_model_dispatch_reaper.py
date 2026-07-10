"""Stale-'running' reaper in model_dispatch_service._expire_stale_tasks (orphan-row fix).

Self-cleaning integration test against the real archie DB: a task stuck 'running' past the
reap threshold (default 900s) is marked 'failed'; a freshly-claimed 'running' task is spared.
Sentinel capability '__reaper_test__' keeps rows findable; cleanup runs in a `finally`.
"""

from services.model_dispatch_service import _expire_stale_tasks

SENTINEL = "__reaper_test__"


def test_reaper_fails_stale_running_but_spares_fresh():
    from database import get_db_cursor

    stale_id = fresh_id = None
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # stale: running, claimed 20 min ago -> reaped -> failed
            cur.execute(
                "INSERT INTO dispatch_pending_queue (capability, model_needed, prompt, status, "
                "queued_at, claimed_at) VALUES (%s,%s,%s,'running', NOW()-interval '25 min', "
                "NOW()-interval '20 min') RETURNING id",
                (SENTINEL, "qwen2.5:7b", "x"),
            )
            stale_id = cur.fetchone()["id"]
            # fresh: running, claimed just now -> must be spared
            cur.execute(
                "INSERT INTO dispatch_pending_queue (capability, model_needed, prompt, status, "
                "queued_at, claimed_at) VALUES (%s,%s,%s,'running', NOW(), NOW()) RETURNING id",
                (SENTINEL, "qwen2.5:7b", "y"),
            )
            fresh_id = cur.fetchone()["id"]

        _expire_stale_tasks()

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT status, error FROM dispatch_pending_queue WHERE id=%s", (stale_id,))
            s = cur.fetchone()
            cur.execute("SELECT status FROM dispatch_pending_queue WHERE id=%s", (fresh_id,))
            f = cur.fetchone()

        assert s["status"] == "failed", f"stale should be reaped->failed, got {s['status']}"
        assert "reaped" in (s["error"] or ""), f"expected reaped error marker, got {s['error']!r}"
        assert f["status"] == "running", f"fresh (claimed now) must be spared, got {f['status']}"
    finally:
        from database import get_db_cursor as _gdc

        with _gdc(commit=True) as (conn, cur):
            cur.execute("DELETE FROM dispatch_pending_queue WHERE capability=%s", (SENTINEL,))
