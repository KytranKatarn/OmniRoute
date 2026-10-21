"""The DS9 app-server health job must ALARM on a fault and stay quiet otherwise.

The job is the platform's only notice that the app-server sidecar died (#7384).
Three behaviours matter, and each one has cost somebody a night before:

  1. It alarms on a fault (a dead sidecar, a signed-out CLI).
  2. It does NOT alarm on a healthy sidecar, and it does NOT alarm on a
     deliberately DISABLED connection — paging on something somebody turned
     off is how an alert channel gets muted (#6803).
  3. It does not re-page for the SAME unchanged outage. The dedup is on the
     CONDITION, not on the numbers, because the numbers move every cycle.

The job is tested against stubbed dependencies (toggle, probe, Telegram, DB),
so it never touches the real DS9, the real settings table, or a real phone.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _platform_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parents[1], here.parents[2] / "platform_v2"):
        if (cand / "services").is_dir() and (cand / "tools").is_dir():
            return cand
    raise AssertionError(f"cannot locate platform_v2 from {here}")


PLATFORM = _platform_root()
sys.path.insert(0, str(PLATFORM))

JOBS_PATH = PLATFORM / "tools" / "department_hq" / "jobs.py"


@pytest.fixture(scope="module")
def jobs():
    spec = importlib.util.spec_from_file_location("dhq_jobs_tested", JOBS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeDB:
    """A minimal stand-in for get_db_cursor's settings write.

    The job's dedup is a read-then-write on platform_settings. This records the
    writes so a test can assert that a SECOND run with the same condition does
    not alert again.
    """

    def __init__(self):
        self.stored = None
        self.writes = 0

    def read(self):
        return self.stored

    def write(self, value):
        self.writes += 1
        self.stored = value


def _run(job, monkeypatch, health_result, fake_db, alerts, enabled=True):
    """Run the job with every side effect stubbed out."""
    import services.ds9_app_server_service as svc
    import services.work_control_service as wc

    monkeypatch.setattr(wc, "is_enabled", lambda _key, default=True: enabled)
    monkeypatch.setattr(svc, "get_app_server_health", lambda: health_result)

    class _Cursor:
        def execute(self, sql, params=None):
            if sql.strip().upper().startswith("SELECT"):
                row = fake_db.read()
                self._row = {"value": row} if row is not None else None
            else:
                fake_db.write((params or [None])[0])

        def fetchone(self):
            return getattr(self, "_row", None)

    class _Conn:
        # The job does `with get_db_cursor(commit=True) as (conn, cur)`, so the
        # object returned by get_db_cursor is itself the context manager and
        # yields the (conn, cur) pair.
        def __enter__(self):
            return (self, _Cursor())

        def __exit__(self, *a):
            return False

    import database

    monkeypatch.setattr(database, "get_db_cursor", lambda commit=False: _Conn())

    import services.telegram_service as tg

    monkeypatch.setattr(tg, "send_system", lambda title, detail=None: alerts.append((title, detail)))

    job()


def test_a_healthy_sidecar_never_alarms(jobs, monkeypatch):
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "healthy",
            "detail": "reachable and signed in",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    assert alerts == [], alerts
    assert fake_db.writes == 0, "a healthy sidecar must not even touch the dedup row"


def test_a_disabled_connection_never_alarms(jobs, monkeypatch):
    """is_active=0 is a deliberate operator setting, not a fault."""
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "disabled",
            "detail": "deliberately disabled",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    assert alerts == [], alerts


def test_no_connection_at_all_never_alarms(jobs, monkeypatch):
    """A platform that does not run DS9's app-server is not a broken platform."""
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "absent",
            "detail": "no app-server connection",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    assert alerts == [], alerts


def test_a_dead_sidecar_alarms(jobs, monkeypatch):
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "down",
            "detail": "The Codex app-server sidecar is NOT answering its readiness probe",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    assert len(alerts) == 1, alerts
    title, detail = alerts[0]
    assert "down" in title.lower()
    assert "readiness probe" in detail


def test_a_signed_out_cli_alarms(jobs, monkeypatch):
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "signed_out",
            "detail": "the Codex CLI is NOT SIGNED IN",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    assert len(alerts) == 1, alerts


def test_the_same_outage_does_not_re_page(jobs, monkeypatch):
    """Dedup on the condition, so one unchanged outage pages once."""
    fake_db = _FakeDB()
    alerts = []
    health = {
        "condition": "down",
        "detail": "sidecar down",
        "checked_at": "2026-10-21T00:00:00Z",
        "connections": [],
    }
    _run(jobs.ds9_codex_appserver_health_job, monkeypatch, health, fake_db, alerts)
    assert len(alerts) == 1, alerts

    _run(jobs.ds9_codex_appserver_health_job, monkeypatch, health, fake_db, alerts)
    assert len(alerts) == 1, f"re-paged for an unchanged outage: {alerts}"


def test_a_different_outage_pages_again(jobs, monkeypatch):
    """A NEW fault must page even if a previous one was recorded."""
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "down",
            "detail": "sidecar down",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "signed_out",
            "detail": "signed out",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
    )
    assert len(alerts) == 2, alerts


def test_the_toggle_silences_the_job(jobs, monkeypatch):
    """work-control: an operator can turn the alarm off without a code change."""
    fake_db = _FakeDB()
    alerts = []
    _run(
        jobs.ds9_codex_appserver_health_job,
        monkeypatch,
        {
            "condition": "down",
            "detail": "sidecar down",
            "checked_at": "2026-10-21T00:00:00Z",
            "connections": [],
        },
        fake_db,
        alerts,
        enabled=False,
    )
    assert alerts == [], alerts
    assert fake_db.writes == 0
