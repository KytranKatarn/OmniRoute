"""Route tests for code_routes.py — A.R.C.H.I.E. Chat Code Tab endpoints.

Strategy: minimal Flask test client. code_service is mocked so tests run
without DB or subprocess dependencies. LOGIN_DISABLED bypasses flask_login.
"""

from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import MagicMock


@pytest.fixture(scope="module", autouse=True)
def add_app_to_path():
    app_path = "/app"
    if app_path not in sys.path:
        sys.path.insert(0, app_path)


@pytest.fixture(scope="module")
def mock_service():
    svc = MagicMock()
    svc.list_sessions.return_value = []
    svc.create_session.return_value = 42
    svc.get_session.return_value = None
    svc.get_session_events.return_value = []
    return svc


@pytest.fixture(scope="module")
def code_client(mock_service):
    """Minimal Flask test client with code routes + login disabled."""
    from flask import Flask, Blueprint
    from flask_login import LoginManager

    # Inject mock code_service into the tools.archie_chat package namespace
    # so the relative import inside code_routes resolves correctly.
    pkg_tools = sys.modules.get("tools") or types.ModuleType("tools")
    pkg_chat = sys.modules.get("tools.archie_chat") or types.ModuleType("tools.archie_chat")
    pkg_chat.code_service = mock_service
    sys.modules.setdefault("tools", pkg_tools)
    sys.modules["tools.archie_chat"] = pkg_chat

    # Import the real code_routes module from the filesystem path
    import importlib.util
    import os

    routes_path = os.path.join("/app", "tools", "archie_chat", "code_routes.py")
    spec = importlib.util.spec_from_file_location("tools.archie_chat.code_routes", routes_path)
    code_routes_mod = importlib.util.module_from_spec(spec)
    # Set the package so relative imports resolve to our mock package
    code_routes_mod.__package__ = "tools.archie_chat"
    spec.loader.exec_module(code_routes_mod)

    bp = Blueprint("archie_chat", __name__, url_prefix="/tools/archie-chat")
    code_routes_mod.register_code_routes(bp)

    mini_app = Flask(__name__)
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["LOGIN_DISABLED"] = True

    LoginManager(mini_app)
    mini_app.register_blueprint(bp)

    with mini_app.test_client() as client:
        with mini_app.app_context():
            yield client


def test_list_code_sessions_returns_200(code_client, mock_service):
    """GET /api/code-sessions returns 200 with a sessions list."""
    mock_service.list_sessions.return_value = []

    resp = code_client.get("/tools/archie-chat/api/code-sessions")

    assert resp.status_code == 200
    data = resp.get_json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


def test_create_code_session_returns_201(code_client, mock_service):
    """POST /api/code-sessions returns 201 with a session_id."""
    mock_service.create_session.return_value = 42

    resp = code_client.post(
        "/tools/archie-chat/api/code-sessions",
        json={"title": "Test Session"},
        content_type="application/json",
    )

    assert resp.status_code == 201
    data = resp.get_json()
    assert "session_id" in data
    assert data["session_id"] == 42


def test_get_code_session_404_when_not_found(code_client, mock_service):
    """GET /api/code-sessions/<id> returns 404 when session does not exist."""
    mock_service.get_session.return_value = None

    resp = code_client.get("/tools/archie-chat/api/code-sessions/9999")

    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data
