"""Integration tests for the /api/signal/calendar/live endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _get_app():
    """Load app.py via importlib to avoid __init__.py package shadowing."""
    import importlib.util
    import sys

    if "app" in sys.modules and hasattr(sys.modules["app"], "User"):
        return sys.modules["app"].app

    spec = importlib.util.spec_from_file_location("flask_app_module", "/app/app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = mod
    spec.loader.exec_module(mod)
    return mod.app


@pytest.fixture
def admin_client():
    flask_app = _get_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 2
            sess["username"] = "kytran"
            sess["_user_id"] = "2"
            sess["_fresh"] = True
            sess["is_admin"] = True
        yield c


@pytest.fixture
def unauth_client():
    flask_app = _get_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


class TestCalendarLiveRoute:
    def test_admin_gets_week_view(self, admin_client):
        fake = {
            "account": "company",
            "week_start": "2026-05-04",
            "today": "2026-05-04",
            "days": [{"date": "2026-05-04", "is_today": True, "posts": []}] * 7,
        }
        with patch(
            "services.signal_calendar_live_service.get_week_view",
            return_value=fake,
        ):
            r = admin_client.get("/tools/department-hq/api/signal/calendar/live?account=company")
        assert r.status_code == 200
        body = r.get_json()
        assert body["account"] == "company"
        assert len(body["days"]) == 7

    def test_rejects_unsupported_account(self, admin_client):
        r = admin_client.get("/tools/department-hq/api/signal/calendar/live?account=bogus")
        assert r.status_code == 400

    def test_requires_account_param(self, admin_client):
        r = admin_client.get("/tools/department-hq/api/signal/calendar/live")
        assert r.status_code == 400

    def test_unauth_redirects_or_401(self, unauth_client):
        r = unauth_client.get("/tools/department-hq/api/signal/calendar/live?account=company")
        # /tools/department-hq/* paths get 302 to /dashboard for unauth
        assert r.status_code in (302, 401)
