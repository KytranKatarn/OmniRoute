"""Tests for the network_traffic_stats freshness alarm + ntopng auth-reason surfacing (#5704).

The decision functions are PURE on purpose (backup_posture_monitor lesson): the test DB
has no network_traffic_stats rows, so an end-to-end "no alert fired" assertion would pass
without exercising anything. Test the decision, not the wiring.

Each test here was proven capable of failing by inverting its expected value during
development (e.g. asserting 'ok' for the stale case fails).
"""

import os
import sys

import pytest

_PLATFORM_V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLATFORM_V2 not in sys.path:
    sys.path.insert(0, _PLATFORM_V2)

from tools.security_network.traffic_feed_monitor import (  # noqa: E402
    FEED_NAME,
    STALE_HOURS_DEFAULT,
    alert_title,
    evaluate_freshness,
)
from tools.security_network.ntopng_service import NtopngService  # noqa: E402


# ---------------------------------------------------------------------------------------
# evaluate_freshness — the alarm decision
# ---------------------------------------------------------------------------------------


class TestEvaluateFreshness:
    def test_no_rows_ever_is_unknown_not_stale(self):
        # A fresh install must not page — 'unknown', never 'stale'.
        assert evaluate_freshness(None, 0, 3.0) == "unknown"

    def test_fresh_feed_is_ok(self):
        assert evaluate_freshness(0.5, 43443, 3.0) == "ok"

    def test_age_exactly_at_limit_is_ok(self):
        # <= limit is fresh — the alarm fires strictly past the threshold.
        assert evaluate_freshness(3.0, 100, 3.0) == "ok"

    def test_stale_feed_alarms(self):
        # The live incident: 17 days (~408h) past the newest bucket.
        assert evaluate_freshness(408.0, 43443, 3.0) == "stale"

    def test_rows_exist_but_null_age_is_stale(self):
        # Defensive: rows exist but MAX() came back NULL — treat as stale, not ok.
        assert evaluate_freshness(None, 10, 3.0) == "stale"

    def test_default_threshold_is_generous_enough_not_to_flap(self):
        # Collector is 5-min writing hourly buckets; a bucket that just rolled over is
        # ~1h "old". The default must comfortably absorb that plus a restart.
        assert STALE_HOURS_DEFAULT >= 2.0
        assert evaluate_freshness(1.2, 100, STALE_HOURS_DEFAULT) == "ok"


class TestAlertTitle:
    def test_title_carries_feed_name(self):
        # send_system dedups on (title, source) — the feed name in the title keeps this
        # alarm's cooldown independent of every other system alert.
        assert FEED_NAME in alert_title()
        assert FEED_NAME == "network_traffic_stats"


# ---------------------------------------------------------------------------------------
# NtopngService._ensure_auth — auth-rejected vs unreachable must be distinguishable
# ---------------------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, url):
        self.url = url


class TestNtopngAuthReason:
    def _svc(self):
        return NtopngService(host="127.0.0.1", port=1, user="admin", password="x")

    def test_wrong_credentials_sets_credentials_rejected(self, monkeypatch):
        svc = self._svc()
        monkeypatch.setattr(
            svc.session,
            "post",
            lambda *a, **k: _FakeResp("http://127.0.0.1:1/lua/login.lua?reason=wrong-credentials"),
        )
        svc._ensure_auth()
        assert svc._authenticated is False
        assert svc.auth_failure_reason == "credentials_rejected"

    def test_connection_error_sets_unreachable(self, monkeypatch):
        svc = self._svc()

        def _boom(*a, **k):
            raise ConnectionError("refused")

        monkeypatch.setattr(svc.session, "post", _boom)
        svc._ensure_auth()
        assert svc._authenticated is False
        assert svc.auth_failure_reason is not None
        assert svc.auth_failure_reason.startswith("unreachable")

    def test_successful_auth_clears_reason(self, monkeypatch):
        svc = self._svc()
        # First fail with bad credentials, then succeed — the reason must clear.
        monkeypatch.setattr(
            svc.session,
            "post",
            lambda *a, **k: _FakeResp("http://127.0.0.1:1/lua/login.lua?reason=wrong-credentials"),
        )
        svc._ensure_auth()
        assert svc.auth_failure_reason == "credentials_rejected"

        monkeypatch.setattr(svc.session, "post", lambda *a, **k: _FakeResp("http://127.0.0.1:1/"))
        svc._ensure_auth()
        assert svc._authenticated is True
        assert svc.auth_failure_reason is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
