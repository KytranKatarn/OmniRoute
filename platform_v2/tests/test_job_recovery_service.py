"""Unit tests for job_recovery_service (#1716) using a stub cursor (no live DB)."""

import services.job_recovery_service as jr


class FakeCursor:
    def __init__(self, fetchone=None, fetchall=None, rowcount=0, description=None):
        self.calls = []  # list of (sql, params)
        self._fetchone = list(fetchone or [])
        self._fetchall = fetchall or []
        self.rowcount = rowcount
        self.description = description

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return self._fetchall


def test_mark_interrupted_on_restart_updates_running_and_returns_rowcount():
    cur = FakeCursor(rowcount=3)
    n = jr.mark_interrupted_on_restart(cur)
    assert n == 3
    sql, params = cur.calls[0]
    assert "UPDATE bridge_jobs" in sql
    assert "WHERE status = 'running'" in sql
    assert "'restart'" in sql
    assert params == ("interrupted",)


def test_reap_stale_running_includes_age_predicate():
    cur = FakeCursor(rowcount=2)
    n = jr.reap_stale_running(cur, max_age_min=20)
    assert n == 2
    sql, params = cur.calls[0]
    assert "WHERE status = 'running'" in sql
    assert "updated_at <" in sql
    assert params == ("interrupted", "20")


def test_list_interrupted_maps_rows_to_dicts():
    cur = FakeCursor(
        fetchall=[(1, "fact_check", "wtf", "d", {"x": 1}, None, "t0", "t1")],
        description=[
            ("id",),
            ("job_type",),
            ("module_source",),
            ("description",),
            ("checkpoint",),
            ("replay_of",),
            ("created_at",),
            ("updated_at",),
        ],
    )
    rows = jr.list_interrupted(cur, limit=10)
    assert rows == [
        {
            "id": 1,
            "job_type": "fact_check",
            "module_source": "wtf",
            "description": "d",
            "checkpoint": {"x": 1},
            "replay_of": None,
            "created_at": "t0",
            "updated_at": "t1",
        }
    ]
    assert cur.calls[0][1] == ("interrupted", 10)


def test_replay_job_re_entrant_dispatches(monkeypatch):
    cur = FakeCursor(
        fetchone=[
            ("fact_check", "wtf", "headline", {"k": 1}, {"completed_steps": 2}, "B.I.A.S."),
            (999,),  # INSERT ... RETURNING id
        ]
    )
    seen = {}
    monkeypatch.setattr(jr, "_dispatch_replay", lambda jt, d, nid: seen.update(jt=jt, nid=nid) or True)
    res = jr.replay_job(cur, 42)
    assert res == {"new_job_id": 999, "executed": True, "needs_handler": False}
    assert seen == {"jt": "fact_check", "nid": 999}
    insert_sql, insert_params = cur.calls[1]
    assert "INSERT INTO bridge_jobs" in insert_sql and "'pending'" in insert_sql
    assert insert_params[-1] == 42  # replay_of
    # last call stamps replayed_at on the original
    assert cur.calls[2] == ("UPDATE bridge_jobs SET replayed_at = NOW() WHERE id = %s", (42,))


def test_replay_job_non_re_entrant_flags_needs_handler(monkeypatch):
    cur = FakeCursor(
        fetchone=[
            ("fact_check_backlog", "wtf", "batch", {}, None, "B.I.A.S."),
            (1000,),
        ]
    )
    called = {"n": 0}
    monkeypatch.setattr(jr, "_dispatch_replay", lambda *a: called.update(n=called["n"] + 1) or True)
    res = jr.replay_job(cur, 7)
    assert res == {"new_job_id": 1000, "executed": False, "needs_handler": True}
    assert called["n"] == 0  # dispatch NOT called for a non-re-entrant job_type
    insert_params = cur.calls[1][1]
    assert any("replay_needs_handler" in str(p) for p in insert_params)


def test_replay_job_missing_raises():
    cur = FakeCursor(fetchone=[None])
    try:
        jr.replay_job(cur, 12345)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "12345" in str(e)
