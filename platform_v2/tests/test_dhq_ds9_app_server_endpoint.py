"""The DS9 app-server endpoint must serve the connection to an ADMIN.

The DS9 tab is admin-gated like every other DHQ surface, so the endpoint's
contract has two halves:

  * unauthenticated  -> the platform's access wall, NOT a data leak;
  * authenticated    -> the app-server connection, with its auth state.

The second half is what the tab renders, so it is the half worth pinning: a
route that returns 200 to everyone would leak the connection's identity and
health; a route that returns nothing to an admin would leave the card blank.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "platform_v2"))

from services import ds9_app_server_service as svc  # noqa: E402


@pytest.fixture()
def client(app):
    """A Flask test client with an admin session, as the DHQ tests do.

    Uses the platform's own `app` fixture (tests/conftest.py) rather than
    importing app.py directly: the conftest loads it by path and caches the
    ~1 GB build, and `from app import app` picks up the wrong object (the app
    PACKAGE's `app` module, not the Flask instance).
    """
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = "2"
        yield c


def test_endpoint_requires_authentication(client):
    """Unauthenticated must NOT return the connection data."""
    with client.session_transaction() as sess:
        sess.pop("_user_id", None)
    resp = client.get("/tools/department-hq/api/engineers/app-server-connections")
    assert resp.status_code in (302, 401, 403), f"expected an auth refusal, got HTTP {resp.status_code}"
    body = resp.get_data(as_text=True)
    assert "codex-app-server" not in body, "the endpoint leaked the app-server connection to an unauthenticated caller"


def test_endpoint_serves_the_connection_to_an_admin(client, monkeypatch, tmp_path):
    """An admin gets the connection, its auth state, and its models."""
    import sqlite3

    db = tmp_path / "storage.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE provider_connections (
            id TEXT, provider TEXT, name TEXT, is_active INTEGER,
            auth_type TEXT, provider_specific_data TEXT,
            last_tested TEXT, test_status TEXT, created_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO provider_connections VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "conn-1",
            "codex-app-server",
            "DS9 Codex app-server",
            1,
            "apikey",
            "{}",
            None,
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(svc, "DS9_DB", str(db))
    monkeypatch.setattr(svc, "_probe", lambda cid: {"valid": True, "latencyMs": 30})
    monkeypatch.setattr(svc, "_models", lambda: {"models": [{"id": "cxa/gpt-6.1-sol"}], "variant_count": 7})

    resp = client.get("/tools/department-hq/api/engineers/app-server-connections")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    data = json.loads(resp.get_data(as_text=True))
    assert data["success"] is True
    assert len(data["connections"]) == 1
    c = data["connections"][0]
    assert c["name"] == "DS9 Codex app-server"
    assert c["auth_state"] == "authenticated"
    assert c["models"] == [{"id": "cxa/gpt-6.1-sol"}]


def test_endpoint_degrades_when_ds9_is_missing(client, monkeypatch, tmp_path):
    """DS9 being absent must not 500 the tab — it must degrade."""
    monkeypatch.setattr(svc, "DS9_DB", str(tmp_path / "nope.sqlite"))
    resp = client.get("/tools/department-hq/api/engineers/app-server-connections")
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))
    assert data["success"] is True
    assert data["connections"] == []
    assert data["reason"]
