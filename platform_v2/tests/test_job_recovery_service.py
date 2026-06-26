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
        fetchall=[(1, "fact_check", "wtf", "d", {"x": 1}, None, None, "t0", "t1")],
        description=[
            ("id",),
            ("job_type",),
            ("module_source",),
            ("description",),
            ("checkpoint",),
            ("replay_of",),
            ("replayed_at",),
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
            "replayed_at": None,
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


# --- #4499: per-job-type resume handlers (true mid-step resume, Scope A) ---


def test_register_resume_handler_roundtrips():
    def fn(cur, job):
        return {"executed": True}

    jr.register_resume_handler("demo_resumable_rt", fn)
    try:
        assert jr.RESUME_HANDLERS.get("demo_resumable_rt") is fn
    finally:
        jr.RESUME_HANDLERS.pop("demo_resumable_rt", None)


def test_replay_job_uses_registered_resume_handler(monkeypatch):
    # An interrupted multi-step job whose job_type has a resume handler is
    # resumed IN PLACE (handler does the real work) — no useless pending clone.
    cur = FakeCursor(
        fetchone=[
            (
                "demo_resumable",
                "consciousness",
                "embed 200",
                {"k": 1},
                {"completed_steps": 50, "total_steps": 200},
                "S.P.E.C.T.R.A.",
            ),
        ]
    )
    seen = {}

    def fake_handler(c, job):
        seen["job"] = job
        return {"executed": True, "detail": "re-triggered embedding backlog"}

    # skip the lazy real-handlers import; inject our fake for a test-only job_type
    monkeypatch.setattr(jr, "_handlers_loaded", True, raising=False)
    monkeypatch.setitem(jr.RESUME_HANDLERS, "demo_resumable", fake_handler)

    res = jr.replay_job(cur, 77)
    assert res["resumed"] is True
    assert res["executed"] is True
    assert res["needs_handler"] is False
    assert res["new_job_id"] is None
    assert res["detail"] == "re-triggered embedding backlog"
    # handler received the job row dict
    assert seen["job"]["id"] == 77
    assert seen["job"]["job_type"] == "demo_resumable"
    assert seen["job"]["checkpoint"] == {"completed_steps": 50, "total_steps": 200}
    # NO clone INSERT — resume is in place
    assert all("INSERT INTO bridge_jobs" not in (c[0] or "") for c in cur.calls)
    # original is stamped replayed_at
    assert cur.calls[-1] == ("UPDATE bridge_jobs SET replayed_at = NOW() WHERE id = %s", (77,))


def test_replay_job_without_handler_keeps_slice1_behavior(monkeypatch):
    # job_type with no resume handler still uses the slice-1 clone path
    cur = FakeCursor(
        fetchone=[
            ("some_batch", "wtf", "batch", {}, None, "AGENT"),
            (2001,),
        ]
    )
    monkeypatch.setattr(jr, "_handlers_loaded", True, raising=False)
    monkeypatch.setattr(jr, "_dispatch_replay", lambda *a: True)
    res = jr.replay_job(cur, 9)
    assert res["needs_handler"] is True
    assert res.get("resumed", False) is False
    assert any("INSERT INTO bridge_jobs" in (c[0] or "") for c in cur.calls)


# --- RealDictCursor (production) path — slice-1 only had tuple-stub tests, so the
#     real DHQ endpoints (which use a RealDictCursor) mis-mapped rows. Lock the fix. ---


def test_list_interrupted_handles_realdict_rows():
    # RealDictCursor yields dict-like rows (no positional access / no description use)
    cur = FakeCursor(
        fetchall=[
            {
                "id": 42,
                "job_type": "batch_embedding",
                "module_source": "consciousness",
                "description": "embed",
                "checkpoint": {"completed_steps": 5},
                "replay_of": None,
                "replayed_at": None,
                "created_at": "t0",
                "updated_at": "t1",
            },
        ]
    )
    rows = jr.list_interrupted(cur, limit=10)
    assert rows[0]["id"] == 42
    assert rows[0]["job_type"] == "batch_embedding"
    assert rows[0]["checkpoint"] == {"completed_steps": 5}


def test_replay_job_handles_realdict_row(monkeypatch):
    cur = FakeCursor(
        fetchone=[
            {
                "job_type": "unhandled_type",
                "module_source": "wtf",
                "description": "d",
                "metadata": {},
                "checkpoint": None,
                "agent_name": "AGENT",
            },
            {"id": 3003},  # RETURNING id as a dict row
        ]
    )
    monkeypatch.setattr(jr, "_handlers_loaded", True, raising=False)
    res = jr.replay_job(cur, 55)
    assert res["new_job_id"] == 3003
    assert res["needs_handler"] is True
