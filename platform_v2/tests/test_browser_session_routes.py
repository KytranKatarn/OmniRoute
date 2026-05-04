"""Integration tests for browser session HTTP routes."""

from __future__ import annotations

import importlib.util
import sys
from unittest.mock import patch

import pytest


def _get_app():
    """Load app.py via importlib to avoid __init__.py package shadowing.

    Mirrors the approach in conftest.py so that ``from app import User``
    inside oauth_routes resolves to the real module, not the package stub.
    """
    if "app" in sys.modules and hasattr(sys.modules["app"], "User"):
        return sys.modules["app"].app

    spec = importlib.util.spec_from_file_location("flask_app_module", "/app/app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = mod
    spec.loader.exec_module(mod)
    return mod.app


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-key")


@pytest.fixture
def admin_client():
    flask_app = _get_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 2
            sess["username"] = "Kytran"
            sess["_user_id"] = "2"  # flask-login
            sess["_fresh"] = True
        yield c


@pytest.fixture
def internal_client():
    """Client without admin session — uses X-Internal-Key header instead."""
    flask_app = _get_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


class TestImportCookies:
    def test_admin_can_import_cookies(self, admin_client):
        body = {
            "cookies": [
                {
                    "name": "li_at",
                    "value": "abc",
                    "domain": ".linkedin.com",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": True,
                    "secure": True,
                },
            ],
        }
        with patch("services.browser_session_service.save_session", return_value={"success": True, "id": 42}):
            r = admin_client.post(
                "/tools/department-hq/api/sessions/7/linkedin/import-cookies",
                json=body,
            )
        assert r.status_code == 200
        assert r.get_json()["success"] is True

    def test_rejects_empty_cookies(self, admin_client):
        r = admin_client.post(
            "/tools/department-hq/api/sessions/7/linkedin/import-cookies",
            json={"cookies": []},
        )
        assert r.status_code == 400

    def test_rejects_unauthenticated(self, internal_client):
        r = internal_client.post(
            "/tools/department-hq/api/sessions/7/linkedin/import-cookies",
            json={"cookies": [{"name": "x", "value": "y"}]},
        )
        assert r.status_code in (302, 401)


class TestGetState:
    def test_internal_key_can_read_state(self, internal_client):
        with patch(
            "services.browser_session_service.load_session", return_value={"cookies": [{"name": "li_at", "value": "v"}]}
        ):
            r = internal_client.get(
                "/tools/department-hq/api/sessions/7/linkedin/state",
                headers={"X-Internal-Key": "test-internal-key"},
            )
        assert r.status_code == 200
        assert r.get_json()["state"]["cookies"][0]["name"] == "li_at"

    def test_rejects_without_internal_key(self, internal_client):
        r = internal_client.get(
            "/tools/department-hq/api/sessions/7/linkedin/state",
        )
        assert r.status_code == 401

    def test_returns_404_when_no_session(self, internal_client):
        with patch("services.browser_session_service.load_session", return_value=None):
            r = internal_client.get(
                "/tools/department-hq/api/sessions/7/linkedin/state",
                headers={"X-Internal-Key": "test-internal-key"},
            )
        assert r.status_code == 404
