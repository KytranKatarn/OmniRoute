"""Tests for the Faith module (Project #284).

Uses a minimal Flask test client — the full ARCHIE app cannot be imported
in tests because oauth_routes.py does `from app import User` and
/app/__init__.py (package init) shadows app.py (known pre-existing issue,
documented in test_approvals_multi_source.py).

Run: docker exec archie_platform python -m pytest tests/test_faith_routes.py -v
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin


@pytest.fixture(scope="module")
def faith_client():
    """Minimal Flask test client with only the faith blueprint mounted."""
    mini_app = Flask(__name__, template_folder="/app/templates")
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["WTF_CSRF_ENABLED"] = False

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    from tools.faith import faith_bp

    mini_app.register_blueprint(faith_bp)

    return mini_app.test_client()


def _login(client):
    """Inject a Flask-Login session for user 1."""
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True


def test_faith_blueprint_registered(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/")
    assert resp.status_code in (200, 302), f"Got {resp.status_code}"


def test_faith_status_endpoint(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agent_id"] == 352


def test_faith_chat_returns_response(faith_client):
    from unittest.mock import patch

    mock_result = {
        "success": True,
        "response": "Peace I leave with you.\n\n---\n**From the Chaplain**\nFaith walks in the dark.",
        "model_used": "mistral:7b",
        "agent": "F.A.I.T.H.",
    }
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock_result), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), patch("tools.faith.routes.get_db_cursor"):
        resp = faith_client.post(
            "/tools/faith/api/faith/chat",
            json={"message": "What does scripture say about doubt?"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_chat_crisis_detection(faith_client):
    from unittest.mock import patch

    mock_result = {"success": True, "response": "...", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock_result), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), patch("tools.faith.routes.get_db_cursor"):
        resp = faith_client.post(
            "/tools/faith/api/faith/chat",
            json={"message": "I have no reason to live"},
        )
    assert resp.status_code == 200
    assert resp.get_json().get("crisis_detected") is True


def test_faith_devotional(faith_client):
    from unittest.mock import patch

    mock = {"success": True, "response": "John 14:27", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), patch("tools.faith.routes.get_db_cursor"):
        resp = faith_client.get("/tools/faith/api/faith/devotional")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_scripture_search(faith_client):
    from unittest.mock import patch

    mock = {"success": True, "response": "Psalm 34:18", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), patch("tools.faith.routes.get_db_cursor"):
        resp = faith_client.post("/tools/faith/api/faith/scripture-search", json={"query": "grief"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_bible_meta(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/bible/meta")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["translation"]["id"] == "web"
    assert data["translation"]["verse_count"] > 30000
    assert any(book["code"] == "JOH" for book in data["books"])


def test_faith_bible_passage(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/bible/passage?book=John&chapter=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["book"] == "JOH"
    assert any(verse["verse"] == 16 for verse in data["verses"])


def test_faith_bible_search(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/bible/search?q=God%20so%20loved")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert any(result["reference"] == "John 3:16" for result in data["results"])


def test_faith_encyclopedia_search(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/encyclopedia/search?q=fathers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert any("Fathers" in entry["title"] for entry in data["entries"])


def test_faith_checkin_saves(faith_client):
    from unittest.mock import MagicMock, patch

    _login(faith_client)
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"id": 1}
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("tools.faith.routes.get_db_cursor", return_value=mock_ctx):
        resp = faith_client.post(
            "/tools/faith/api/faith/checkin",
            json={"score": 4, "reflection": "Feeling close to God."},
        )
    assert resp.status_code == 201


def test_faith_journal_list(faith_client):
    from unittest.mock import MagicMock, patch

    _login(faith_client)
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("tools.faith.routes.get_db_cursor", return_value=mock_ctx):
        resp = faith_client.get("/tools/faith/api/faith/journal")
    assert resp.status_code == 200
    assert "entries" in resp.get_json()


def test_connect_chaplain(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._send_chaplain_email", return_value=True), patch("tools.faith.routes.get_db_cursor"):
        resp = faith_client.post(
            "/tools/faith/api/faith/connect-chaplain",
            json={"message": "I need to talk."},
        )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
