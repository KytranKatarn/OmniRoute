"""Alert-delivery self-health for scripts/host_monitor.py.

REAL INCIDENT THIS PINS: from ~2026-01-30 to 2026-07-26, every create_alert()
call on the hub failed. psycopg2 lived in the invoking user's site-packages but
the service runs as root, so `import psycopg2` raised ModuleNotFoundError on all
9 call sites. The bare `except: print(...)` swallowed it, and Python
block-buffers stdout when it is a pipe (systemd), so the message never reached
the journal either. stack_health_alerts sat at 13 rows for six months while the
monitor looked healthy.

The tests below are about the SECOND failure, not the first: a monitor that
cannot deliver alerts must say so, because in that state it is
indistinguishable from a monitor with nothing to report.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

hm = pytest.importorskip(  # noqa: E402
    "host_monitor",
    reason=(
        "host-only: this module lives in scripts/ on the HOST and is not present in the archie_platform container. Skipping keeps it honest — an ImportError here aborts collection for the ENTIRE suite (#5665)."
    ),
)


@pytest.fixture(autouse=True)
def reset_alert_health():
    """Each test starts from a clean 'never attempted' state."""
    hm._ALERT_HEALTH.update(
        {
            "ok": None,
            "last_error": None,
            "last_success_at": None,
            "consecutive_failures": 0,
            "total_failures": 0,
        }
    )
    hm._last_alert_times.clear()
    yield


def _break_db(monkeypatch, exc=None):
    def boom():
        raise exc or ModuleNotFoundError("No module named 'psycopg2'")

    monkeypatch.setattr(hm, "get_db_connection", boom)


class TestDeliveryFailureIsVisible:
    def test_failed_alert_marks_health_degraded(self, monkeypatch):
        _break_db(monkeypatch)
        assert hm.create_alert("hardware", "/mnt/Plex", "mount_missing", "critical", "x") is None

        h = hm.alerting_health()
        assert h["ok"] is False
        assert h["degraded"] is True
        assert "psycopg2" in h["last_error"]
        assert h["consecutive_failures"] == 1

    def test_the_exact_six_month_bug_would_now_be_reported(self, monkeypatch):
        # Reproduce the real failure verbatim and assert it is no longer silent.
        _break_db(monkeypatch, ModuleNotFoundError("No module named 'psycopg2'"))
        for _ in range(5):
            hm.create_alert("stack", "c", "container_down", "critical", "down")

        h = hm.alerting_health()
        assert h["degraded"] is True
        assert h["consecutive_failures"] == 5
        assert h["total_failures"] == 5
        # And it never claimed a successful delivery.
        assert h["last_success_at"] is None

    def test_never_attempted_is_not_degraded(self):
        # A fresh process has not tried yet. "Unknown" must not read as "broken"
        # -- that is the same rule the backup freshness monitor uses.
        h = hm.alerting_health()
        assert h["ok"] is None
        assert h["degraded"] is False


class TestFailedAlertDoesNotMuteItself:
    def test_cooldown_is_not_stamped_on_a_failed_delivery(self, monkeypatch):
        # THE SUBTLE ONE. If a failed write stamped the cooldown, a delivery
        # outage would silence the alert for the whole cooldown window on top of
        # having dropped it -- the outage would suppress its own evidence.
        _break_db(monkeypatch)
        hm.create_alert("hardware", "/mnt/Plex", "mount_missing", "critical", "x")

        assert ("/mnt/Plex", "mount_missing") not in hm._last_alert_times
        assert hm.should_alert("/mnt/Plex", "mount_missing", 360) is True


class TestHealthIsPublished:
    def test_alerting_health_shape_is_serializable(self, monkeypatch):
        import json

        _break_db(monkeypatch)
        hm.create_alert("hardware", "k", "t", "critical", "m")
        # Goes into host_monitor_data.json, so it must survive json.dumps.
        json.dumps(hm.alerting_health())

    def test_snapshot_is_a_copy_not_the_live_dict(self, monkeypatch):
        h = hm.alerting_health()
        h["ok"] = "tampered"
        assert hm._ALERT_HEALTH["ok"] is not "tampered"  # noqa: F632


class TestStartupProbe:
    def test_probe_reports_broken_backend_loudly(self, monkeypatch, capsys):
        _break_db(monkeypatch)
        assert hm.check_alert_backend() is False

        out = capsys.readouterr().out
        assert "ALERT DELIVERY IS BROKEN" in out
        assert hm.alerting_health()["degraded"] is True

    def test_probe_marks_healthy_when_backend_works(self, monkeypatch):
        class _Cur:
            def execute(self, *a, **k):
                return None

            def close(self):
                return None

        class _Conn:
            def cursor(self):
                return _Cur()

            def close(self):
                return None

        monkeypatch.setattr(hm, "get_db_connection", lambda: _Conn())
        assert hm.check_alert_backend() is True
        assert hm.alerting_health()["ok"] is True
        assert hm.alerting_health()["degraded"] is False
