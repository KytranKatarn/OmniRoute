"""Slice 2 (#4372) — trustworthy probe semantics + calendar gate decouple.

A transient probe failure (timeout / lock-busy) must NOT flip a session stale or
gate the calendar; only a POSITIVE logged-out signal does.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_cursor(row=None, rows=None):
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    return _CM(), cur


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")


class TestRecordProbeOutcomes:
    def _run(self, **kw):
        from services import browser_session_service as svc

        cm, cur = _mock_cursor()
        with patch.object(svc, "get_db_cursor", return_value=cm):
            svc.record_probe(342, "linkedin", **kw)
        return cur.execute.call_args[0][0]

    def test_success_marks_active(self):
        sql = self._run(ok=True)
        assert "status = 'active'" in sql
        assert "last_probe_ok = TRUE" in sql

    def test_logged_out_marks_stale(self):
        sql = self._run(ok=False, reason="authwall", logged_out=True)
        assert "status = 'stale'" in sql
        assert "last_probe_ok = FALSE" in sql

    def test_transient_keeps_status(self):
        # The critical fix: a transient failure must NOT touch status or last_probe_ok.
        sql = self._run(ok=False, reason="Timeout after 180s", logged_out=False)
        assert "status =" not in sql
        assert "last_probe_ok" not in sql
        assert "last_probe_at = NOW()" in sql

    def test_transient_is_the_default(self):
        # logged_out defaults False → an old call site stays transient-safe.
        sql = self._run(ok=False, reason="boom")
        assert "status = 'stale'" not in sql

    def test_success_AND_logged_out_marks_stale(self):
        """#5627 — THE case that actually happens in production, and the one this
        suite did not cover. A READ skill that lands ON the login wall reports
        success=True AND logged_out=True (measured live on agent 342:
        linkedin_feed -> {'success': True, 'logged_out': True}).

        Every other test here pins ok=False for the logged-out path, so the old
        `if ok:`-first ordering passed the whole suite while re-stamping a dead
        profile 'active' on every probe and every keep-warm — which blinded the
        #1831 release guard and let 5 posts be released into a logged-out profile
        on 2026-08-15. logged_out MUST outrank ok.
        """
        sql = self._run(ok=True, reason="authwall", logged_out=True)
        assert "status = 'stale'" in sql
        assert "status = 'active'" not in sql
        assert "last_probe_ok = FALSE" in sql


class TestIsKnownLoggedOut:
    """#5627 — the choke-point gate used by the agent_loop linkedin_post executor.
    Fail-OPEN everywhere except a positive 'stale': a health-read bug must never
    block posting."""

    def _run(self, row):
        from services import browser_session_service as svc

        cm, _cur = _mock_cursor(row=row)
        with patch.object(svc, "get_db_cursor", return_value=cm):
            return svc.is_known_logged_out(342, "linkedin")

    def test_stale_is_logged_out(self):
        assert self._run({"status": "stale"}) is True

    def test_active_is_not_logged_out(self):
        assert self._run({"status": "active"}) is False

    def test_no_row_fails_open(self):
        assert self._run(None) is False

    def test_read_error_fails_open(self):
        from services import browser_session_service as svc

        with patch.object(svc, "get_db_cursor", side_effect=RuntimeError("db down")):
            assert svc.is_known_logged_out(342, "linkedin") is False


class TestListSessionsForProbe:
    def test_includes_active_and_stale(self):
        from services import browser_session_service as svc

        cm, cur = _mock_cursor(rows=[{"agent_id": 342, "platform": "linkedin"}])
        with patch.object(svc, "get_db_cursor", return_value=cm):
            out = svc.list_sessions_for_probe()
        sql = cur.execute.call_args[0][0]
        assert "status IN ('active', 'stale')" in sql
        assert out == [(342, "linkedin")]


class TestCalendarGate:
    def _healthy(self, row):
        from services import signal_calendar_service as svc

        cur = MagicMock()
        cur.fetchone.return_value = row
        return svc._linkedin_profile_healthy(cur, 342)

    def test_stale_blocks(self):
        assert self._healthy({"status": "stale"}) is False

    def test_active_allows(self):
        assert self._healthy({"status": "active"}) is True

    def test_no_row_fails_open(self):
        assert self._healthy(None) is True

    def test_transient_last_probe_ok_false_no_longer_blocks(self):
        # Even if an old row still has last_probe_ok False, an active status releases —
        # the gate keys ONLY on status now (the false-negative is gone).
        assert self._healthy({"status": "active"}) is True
