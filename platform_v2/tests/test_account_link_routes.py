"""Integration tests for Account Center email-linking routes (Project #311)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _get_app():
    """Load app.py via importlib to avoid __init__.py package shadowing.

    Mirrors the approach in conftest.py so that ``from app import User``
    inside oauth_routes resolves to the real module, not the package stub.
    """
    import importlib.util
    import sys

    if "app" in sys.modules and hasattr(sys.modules["app"], "User"):
        # Already loaded by conftest — reuse it.
        return sys.modules["app"].app

    spec = importlib.util.spec_from_file_location("flask_app_module", "/app/app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = mod
    spec.loader.exec_module(mod)
    return mod.app


@pytest.fixture
def client():
    """Boot the app and return a Flask test client logged in as user 7."""
    flask_app = _get_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 7
            sess["username"] = "kytran"
            sess["_user_id"] = "7"  # flask-login
            sess["_fresh"] = True
        yield c


class TestEmailLinkRoutes:
    def test_get_list_returns_verified_and_pending(self, client):
        with patch(
            "tools.account_center.email_link_routes._get_user_alternates",
            return_value={"verified": ["v@x.com"], "pending": []},
        ):
            r = client.get("/tools/account-center/api/alternate-emails")
        assert r.status_code == 200
        body = r.get_json()
        assert body["verified"] == ["v@x.com"]
        assert body["pending"] == []

    def test_post_alternate_returns_202(self, client):
        with patch(
            "services.account_link_service.request_alternate_email",
            return_value={
                "success": True,
                "pending_email": "alt@x.com",
                "expires_at": "2026-05-05T00:00:00",
            },
        ):
            r = client.post(
                "/tools/account-center/api/alternate-emails",
                json={"email": "alt@x.com"},
            )
        assert r.status_code == 202
        assert r.get_json()["pending_email"] == "alt@x.com"

    def test_post_alternate_returns_4xx_on_validation_error(self, client):
        with patch(
            "services.account_link_service.request_alternate_email",
            return_value={"success": False, "error": "Invalid email format"},
        ):
            r = client.post(
                "/tools/account-center/api/alternate-emails",
                json={"email": "bad"},
            )
        assert r.status_code == 400

    def test_verify_endpoint_renders_confirmation_on_success(self, client):
        with patch(
            "services.account_link_service.verify_alternate_email",
            return_value={
                "success": True,
                "user_id": 7,
                "alternate_email": "alt@x.com",
            },
        ):
            r = client.get("/account/verify-alternate?token=goodtoken")
        assert r.status_code == 200
        assert b"verified" in r.data.lower() or b"confirmed" in r.data.lower()

    def test_verify_endpoint_renders_error_on_bad_token(self, client):
        with patch(
            "services.account_link_service.verify_alternate_email",
            return_value={"success": False, "error": "Token expired"},
        ):
            r = client.get("/account/verify-alternate?token=bad")
        assert r.status_code in (400, 410)
        assert b"expired" in r.data.lower() or b"error" in r.data.lower()

    def test_delete_alternate(self, client):
        with patch(
            "services.account_link_service.remove_alternate_email",
            return_value={"success": True, "removed": True},
        ):
            r = client.delete("/tools/account-center/api/alternate-emails/alt@x.com")
        assert r.status_code == 200
        assert r.get_json()["removed"] is True


class TestEmailLinkAuthGate:
    def test_unauthenticated_get_redirects_or_401(self):
        flask_app = _get_app()
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        with flask_app.test_client() as c:
            r = c.get("/tools/account-center/api/alternate-emails")
        # @login_required typically returns 302 redirect to login or 401
        assert r.status_code in (302, 401), f"Expected auth gate (302/401); got {r.status_code}"

    def test_unauthenticated_post_redirects_or_401(self):
        flask_app = _get_app()
        flask_app.config["TESTING"] = True
        flask_app.config["WTF_CSRF_ENABLED"] = False
        with flask_app.test_client() as c:
            r = c.post(
                "/tools/account-center/api/alternate-emails",
                json={"email": "alt@x.com"},
            )
        assert r.status_code in (302, 401)
