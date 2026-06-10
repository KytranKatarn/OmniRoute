"""Tests for Brainstorm route input validation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


@pytest.fixture
def brainstorm_client():
    """Minimal Flask client with only the brainstorm blueprint mounted."""
    mini_app = Flask(__name__, template_folder=str(PLATFORM_ROOT / "templates"))
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    from tools.brainstorm import brainstorm_bp

    mini_app.register_blueprint(brainstorm_bp)

    with mini_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield client


def test_update_session_rejects_injected_field_name(brainstorm_client):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.patch(
            "/tools/brainstorm/api/sessions/123",
            json={"title": "Safe title", "status = 'archived' --": "ignored"},
        )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "Unknown field" in data["error"]
    get_db_cursor.assert_not_called()


def test_update_idea_rejects_injected_field_name(brainstorm_client):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.patch(
            "/tools/brainstorm/api/ideas/456",
            json={"content": "Safe idea", "cluster = 'x', votes = 999 --": "ignored"},
        )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "Unknown field" in data["error"]
    get_db_cursor.assert_not_called()
