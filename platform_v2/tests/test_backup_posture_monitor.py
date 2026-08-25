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
    """Fake cursor. Routes each fetchall by the QUERY IT SAW, not by call order.

    It used to answer "the two fetchall queries" positionally — platform_settings, then
    the per-tier rollup — with `return settings_rows if "platform_settings" in q else
    tier_rows`. #5619 then added a THIRD fetchall (the DISTINCT ON error_message lookup
    that quotes each tier's real failure cause), which fell into the `else` and received
    ROLLUP rows. Those have no `error_message`, so the whole off-site block produced
    nothing and four tests failed with `assert 'offsite_gdrive_stale' in []`.

    Production had moved and the fake had not — the same shape as #5993. Keying on query
    CONTENT means the next added query returns [] (visibly empty) instead of silently
    inheriting another query's rows.
    """

    def __init__(self, age_h, failures, tier_rows=None, settings_rows=None, error_rows=None):
        self._answers = [{"age_h": age_h}, {"n": failures}]
        self._i = -1
        self._tier_rows = tier_rows or []
        self._settings_rows = settings_rows or []
        self._error_rows = error_rows or []
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append(q)
        self._i += 1

    def fetchone(self):
        return self._answers[self._i] if 0 <= self._i < len(self._answers) else None

    def fetchall(self):
        q = self.sql[-1] if self.sql else ""
        if "platform_settings" in q:
            return self._settings_rows
        if "error_message" in q:  # #5619 per-tier last-error lookup
            return self._error_rows
        if "success_age_h" in q:  # per-tier off-site rollup
            return self._tier_rows
        return []


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

    def _run(age_h, failures=0, tier_rows=None, settings_rows=None, error_rows=None, **kw):
        _cursor.cur = _Cur(age_h, failures, tier_rows, settings_rows, error_rows)
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


class TestOffSiteTierFreshness:
    """#5094. Watching only tier='primary' left the blind spot one level out: the local
    nightly dump succeeded every night from 2026-06-29 to 07-21 while the Google Drive
    copy of the database did not exist, and this module reported healthy the whole time."""

    def test_stale_offsite_alerts_while_primary_is_perfectly_fresh(self, alerts):
        """THE REGRESSION. Primary fresh + zero failures must NOT buy silence for a
        dead off-site leg — that combination is exactly what hid #5092 for three weeks."""
        res, sent, _ = alerts(
            1.0,
            failures=0,
            tier_rows=[{"tier": "gdrive", "success_age_h": 500.0, "total_rows": 254}],
        )
        assert "offsite_gdrive_stale" in res["alerted"]
        assert "primary_backup_stale" not in res["alerted"]
        assert res["tiers"]["gdrive"]["status"] == "stale"
        assert "gdrive" in str(sent)

    def test_unconfigured_tier_is_unknown_not_an_alert(self, alerts):
        """No rows at all = tier not configured here. A fresh deploy must not page —
        but it is still REPORTED, because a check that can never fire while looking
        absent is the failure mode this whole module exists to prevent."""
        res, sent, _ = alerts(1.0, tier_rows=[])
        assert res["alerted"] == []
        assert sent == []
        assert set(res["tiers"]) == set(bpm.OFFSITE_STALE_HOURS)
        assert all(v["status"] == "unknown" for v in res["tiers"].values())

    def test_tier_with_rows_but_never_a_success_alerts(self, alerts):
        """Rows exist so the tier IS configured — it has just never produced a restore
        point. That is worse than stale, not exempt."""
        res, sent, _ = alerts(1.0, tier_rows=[{"tier": "dr", "success_age_h": None, "total_rows": 57}])
        assert "offsite_dr_stale" in res["alerted"]
        assert "MISSING ENTIRELY" in str(sent)

    def test_fresh_offsite_tiers_are_silent(self, alerts):
        rows = [{"tier": t, "success_age_h": 6.0, "total_rows": 10} for t in bpm.OFFSITE_STALE_HOURS]
        res, sent, _ = alerts(1.0, tier_rows=rows)
        assert res["alerted"] == []
        assert sent == []

    def test_each_tier_gets_its_own_title_so_cooldowns_are_independent(self, alerts):
        """send_system dedups on (title, source). If the tier were not in the title, one
        stale tier would mute the alerts for every other tier for the whole cooldown."""
        res, sent, _ = alerts(
            1.0,
            tier_rows=[
                {"tier": "gdrive", "success_age_h": 500.0, "total_rows": 9},
                {"tier": "vps", "success_age_h": 500.0, "total_rows": 9},
            ],
        )
        titles = [t for t, _m, _k in sent]
        assert len(set(titles)) == 2, "tiers must not share an alert title"
        assert any("gdrive" in t for t in titles) and any("vps" in t for t in titles)

    def test_offsite_measure_filters_on_success(self, alerts):
        """Same lesson as #5013/#5092: a failed sync also writes a row for that tier, so
        measuring the newest row regardless of status certifies a copy that never landed."""
        _, _, cur = alerts(1.0, tier_rows=[])
        rollup = [q for q in cur.sql if "GROUP BY tier" in q]
        assert rollup, "off-site rollup query missing"
        assert "status = 'success'" in rollup[0]

    def test_usb_gets_more_slack_than_the_network_tiers(self):
        """Removable media unplugged over a long weekend should not page."""
        assert bpm.OFFSITE_STALE_HOURS["usb"] > bpm.OFFSITE_STALE_HOURS["gdrive"]

    def test_thresholds_are_tunable_without_a_deploy(self, alerts):
        rows = [{"tier": "gdrive", "success_age_h": 50.0, "total_rows": 9}]
        loose, _, _ = alerts(1.0, tier_rows=rows, offsite_stale_hours={"gdrive": 100.0})
        assert loose["alerted"] == []
        tight, _, _ = alerts(1.0, tier_rows=rows, offsite_stale_hours={"gdrive": 10.0})
        assert "offsite_gdrive_stale" in tight["alerted"]


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
