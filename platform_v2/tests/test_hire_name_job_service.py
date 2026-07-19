"""Unit tests for the async hire-name job store (#4969).

State lives in the hire_name_jobs table (archie_platform runs 4 gunicorn workers,
so an in-memory store would let the POST and the poll land on different workers).
DB is monkeypatched; create_job's _runner seam avoids a real dispatch, and
_run_job's _generate seam avoids the real (slow) identity build.
"""

from __future__ import annotations

import contextlib
import json
import sys
import threading
import uuid

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from services import hire_name_job_service as svc  # noqa: E402


class _FakeCur:
    def __init__(self, row=None):
        self.calls = []
        self._row = row

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._row


def _fake_db(cur):
    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, cur)

    return _cm


def test_create_job_inserts_generating_and_spawns_runner(monkeypatch):
    cur = _FakeCur()
    monkeypatch.setattr(svc, "get_db_cursor", _fake_db(cur))
    monkeypatch.setattr(svc, "prune_old", lambda: None)

    ran = {}
    done = threading.Event()

    def _runner(job_id, hire_id, capability):
        ran["args"] = (job_id, hire_id, capability)
        done.set()

    job_id = svc.create_job(7, "fact_check", _runner=_runner)

    uuid.UUID(job_id)  # a real uuid
    inserts = [c for c in cur.calls if "INSERT INTO hire_name_jobs" in c[0]]
    assert inserts and inserts[0][1] == (job_id, 7, "fact_check")
    assert "'generating'" in inserts[0][0]
    assert done.wait(timeout=2), "background runner never ran"
    assert ran["args"] == (job_id, 7, "fact_check")


def test_get_job_returns_shape(monkeypatch):
    row = {"status": "done", "result": {"name": "V.E.R.I.F.Y."}, "error": None}
    monkeypatch.setattr(svc, "get_db_cursor", _fake_db(_FakeCur(row)))
    assert svc.get_job("abc") == {"status": "done", "result": {"name": "V.E.R.I.F.Y."}, "error": None}


def test_get_job_unknown_returns_none(monkeypatch):
    monkeypatch.setattr(svc, "get_db_cursor", _fake_db(_FakeCur(None)))
    assert svc.get_job("nope") is None


def test_run_job_persists_done_on_success(monkeypatch):
    cur = _FakeCur()
    monkeypatch.setattr(svc, "get_db_cursor", _fake_db(cur))
    monkeypatch.setattr(svc, "_generate", lambda hid, cap: {"name": "V.E.R.I.F.Y.", "source": "llm"})

    svc._run_job("job1", 7, "fact_check")

    updates = [c for c in cur.calls if "status='done'" in c[0]]
    assert updates, "expected a done UPDATE"
    assert json.loads(updates[0][1][0]) == {"name": "V.E.R.I.F.Y.", "source": "llm"}
    assert updates[0][1][1] == "job1"


def test_run_job_persists_error_on_failure(monkeypatch):
    cur = _FakeCur()
    monkeypatch.setattr(svc, "get_db_cursor", _fake_db(cur))

    def _boom(hid, cap):
        raise RuntimeError("dispatch exploded")

    monkeypatch.setattr(svc, "_generate", _boom)

    svc._run_job("job2", 7, "fact_check")  # must never raise

    errs = [c for c in cur.calls if "status='error'" in c[0]]
    assert errs and errs[0][1][1] == "job2"
    assert "dispatch exploded" in errs[0][1][0]
