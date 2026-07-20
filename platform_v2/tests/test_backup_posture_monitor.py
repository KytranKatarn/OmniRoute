"""Backup-failure alerting — the watchdog that did not exist when it was needed.

On 2026-07-20 full backups had been OOM-killed for an unknown period, the last successful
primary backup aged past 12h, and nothing told anyone. The job meant to catch it queried a
table that does not exist (`backups` — it is `backup_log`), threw on every run, and had no
alert path even on success.

These tests pin the two properties that make a watchdog worth having:
  * it fires on the conditions that actually occurred, and
  * it NEVER depends on an LLM, and never crashes the loop it runs in.
"""

import contextlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.backup_posture_monitor as bpm  # noqa: E402


class _Cur:
    """Answers the two queries in order: freshness age, then failure count."""

    def __init__(self, age_h, failures):
        self._answers = [{"age_h": age_h}, {"n": failures}]
        self._i = -1
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append(q)
        self._i += 1

    def fetchone(self):
        return self._answers[self._i]


@pytest.fixture
def alerts(monkeypatch):
    sent = []

    @contextlib.contextmanager
    def _cursor(commit=False):
        yield (None, _cursor.cur)

    monkeypatch.setattr(bpm, "get_db_cursor", _cursor)
    import services.telegram_service as ts

    # capture the BODY too — the assertions below check what the operator actually reads
    monkeypatch.setattr(ts, "send_system", lambda title, msg="", **kw: sent.append((title, msg, kw)) or {})

    def _run(age_h, failures=0, **kw):
        _cursor.cur = _Cur(age_h, failures)
        res = bpm.check_backup_posture(**kw)
        return res, sent, _cursor.cur

    return _run


class TestFiresWhenItShould:
    def test_no_successful_backup_at_all_alerts(self, alerts):
        """The worst case: nothing to restore from. Must be loud, not silent."""
        res, sent, _ = alerts(None)
        assert "primary_backup_stale" in res["alerted"]
        assert "MISSING ENTIRELY" in str(sent)

    def test_stale_success_alerts(self, alerts):
        res, sent, _ = alerts(30.0)
        assert "primary_backup_stale" in res["alerted"]
        assert res["success_age_h"] == 30.0

    def test_failures_alert_even_when_a_later_backup_SUCCEEDED(self, alerts):
        """THE REAL CASE. A manual backup can mask a broken nightly — the unattended
        path is still broken and will be relied on when nobody is watching."""
        res, _, _ = alerts(0.5, failures=2)
        assert "primary_backup_failures" in res["alerted"]
        assert "primary_backup_stale" not in res["alerted"]
        assert res["recent_failures"] == 2

    def test_both_conditions_alert_independently(self, alerts):
        res, _, _ = alerts(40.0, failures=3)
        assert set(res["alerted"]) == {"primary_backup_stale", "primary_backup_failures"}


class TestQuietWhenHealthy:
    def test_fresh_success_no_failures_is_silent(self, alerts):
        """A watchdog that cries constantly gets muted, which is the same as being off."""
        res, sent, _ = alerts(1.2, failures=0)
        assert res["alerted"] == []
        assert sent == []

    def test_boundary_just_inside_limit_is_silent(self, alerts):
        res, _, _ = alerts(bpm.PRIMARY_STALE_HOURS - 0.1)
        assert res["alerted"] == []

    def test_boundary_just_past_limit_alerts(self, alerts):
        res, _, _ = alerts(bpm.PRIMARY_STALE_HOURS + 0.1)
        assert "primary_backup_stale" in res["alerted"]


class TestCorrectnessOfTheMeasure:
    def test_freshness_query_filters_on_success(self, alerts):
        """#5013's lesson: a FAILED run also writes a tier='primary' row. Measuring the
        newest row regardless of status certifies a restore point that does not exist."""
        _, _, cur = alerts(1.0)
        assert "status = 'success'" in cur.sql[0]
        assert "tier = 'primary'" in cur.sql[0]

    def test_partial_counts_as_a_failure(self):
        """'partial' is the most dangerous status — plausible-looking and unusable."""
        assert "partial" in bpm._FAILURE_STATUSES
        assert "failed" in bpm._FAILURE_STATUSES


class TestNeverTakesTheLoopDown:
    def test_db_error_is_reported_not_raised(self, monkeypatch):
        @contextlib.contextmanager
        def _boom(commit=False):
            raise RuntimeError("db gone")
            yield  # pragma: no cover

        monkeypatch.setattr(bpm, "get_db_cursor", _boom)
        res = bpm.check_backup_posture()
        assert res["checked"] is False
        assert "db gone" in res["error"]

    def test_alert_path_is_deterministic_no_llm(self):
        """The predecessor asked a model to 'flag anything that needs attention'. An alert
        that only fires when an LLM is warm, reachable and correct is not an alert."""
        src = open(bpm.__file__).read()
        for forbidden in ("dispatch(", "get_dispatcher", "capability="):
            assert forbidden not in src, f"alert path must not depend on the LLM ({forbidden})"
