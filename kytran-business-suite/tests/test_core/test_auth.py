"""
tests/test_core/test_auth.py — Tests for Flask app factory and auth endpoints.

Env vars required for DB-touching tests:
    KBS_DB_HOST=192.168.1.200 KBS_DB_NAME=archie KBS_DB_USER=archie
    KBS_DB_PASSWORD=CTIf6MjCwuGUwVR_sWNNVIaMB6G7wnZ3RinJ_Cr6jwI

The conftest.py already sets these from DB_PASSWORD env var and
creates the `app` and `client` fixtures. We import `client` from there.
"""

import pytest


# ---------------------------------------------------------------------------
# Test 1: App creates successfully
# ---------------------------------------------------------------------------


def test_app_creates(app):
    """The Flask app factory must return a valid app object."""
    assert app is not None
    assert app.name is not None


# ---------------------------------------------------------------------------
# Test 2: /health returns 200 with {"status": "ok"}
# ---------------------------------------------------------------------------


def test_health_endpoint(client):
    """GET /health must return 200 and JSON with status=ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    assert data["status"] == "ok"
    assert "product" in data


# ---------------------------------------------------------------------------
# Test 3: /auth/login GET returns 200
# ---------------------------------------------------------------------------


def test_login_get(client):
    """GET /auth/login must return 200 with the login form."""
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Sign In" in resp.data or b"login" in resp.data.lower()


# ---------------------------------------------------------------------------
# Test 4: /auth/signup GET returns 200
# ---------------------------------------------------------------------------


def test_signup_get(client):
    """GET /auth/signup must return 200 with the signup form."""
    resp = client.get("/auth/signup")
    assert resp.status_code == 200
    assert b"Create Account" in resp.data or b"signup" in resp.data.lower()


# ---------------------------------------------------------------------------
# Test 5: /auth/sso returns 501
# ---------------------------------------------------------------------------


def test_sso_returns_501(client):
    """GET /auth/sso must return 501 Not Implemented (stub)."""
    resp = client.get("/auth/sso")
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Test 6: Unauthenticated access to /dashboard redirects to login
# ---------------------------------------------------------------------------


def test_dashboard_unauthenticated_redirects(client):
    """GET /dashboard without auth must redirect to /auth/login."""
    resp = client.get("/dashboard")
    assert resp.status_code in (301, 302)
    location = resp.headers.get("Location", "")
    assert "login" in location


# ---------------------------------------------------------------------------
# Test 7: Unauthenticated access to / also redirects
# ---------------------------------------------------------------------------


def test_root_unauthenticated_redirects(client):
    """GET / without auth must redirect to login."""
    resp = client.get("/")
    assert resp.status_code in (301, 302)
    location = resp.headers.get("Location", "")
    assert "login" in location
