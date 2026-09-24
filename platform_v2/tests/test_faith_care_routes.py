"""Tests for the Faith module care routes (Project #284).

Covers the LLM-facing and safety routes: chat (incl. crisis detection),
devotional, scripture-search, guided prayer, Lectio Divina, timer, sessions,
check-ins, journal, and connect-with-chaplain. Uses a minimal Flask test
client — the full ARCHIE app cannot be imported in tests because
oauth_routes.py does `from app import User` and /app/__init__.py (package
init) shadows app.py (known pre-existing issue, documented in
test_approvals_multi_source.py). The reader / search / profile tests have
their own file, test_faith_routes.py, with the same client/stub block.

Run: docker exec archie_platform python -m pytest tests/test_faith_care_routes.py -v
"""

from __future__ import annotations

import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

from tests.modstub import stub_module_scoped


@pytest.fixture(autouse=True, scope="module")
def _stub_department_dispatcher():
    """Stub the DHQ dispatcher for this module (#272154).

    routes.py imports `dispatch` at module import time, and the real module
    pulls `from db import _get_db_password` from a module that is not
    importable under the coder-lane pytest invocation (--noconftest). Every
    LLM-facing test here mocks archie_bridge, so the stub is never invoked.
    """
    stub = types.ModuleType("tools.department_hq.services.department_dispatcher")
    stub.dispatch = lambda *args, **kwargs: {"success": False, "response": "(dispatcher stubbed)"}
    stub.__file__ = __file__
    stub.__package__ = "tools.department_hq.services"
    with stub_module_scoped("tools.department_hq.services.department_dispatcher", stub):
        yield stub


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


def _logout(client):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = None


@contextmanager
def _patched_db():
    c = MagicMock()
    c.fetchone.return_value = {"id": 1}
    c.fetchall.return_value = []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), c))
    ctx.__exit__ = MagicMock(return_value=False)
    with patch("tools.faith.routes.get_db_cursor", return_value=ctx):
        yield c


def test_faith_chat_returns_response(faith_client):
    mock_result = {
        "success": True,
        "response": "Peace I leave with you.\n\n---\n**From the Chaplain**\nFaith walks in the dark.",
        "model_used": "mistral:7b",
        "agent": "F.A.I.T.H.",
    }
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock_result), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.post(
            "/tools/faith/api/faith/chat",
            json={"message": "What does scripture say about doubt?"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_chat_passes_authenticated_user_to_dispatch(faith_client):
    _login(faith_client)
    with patch(
        "tools.faith.routes.archie_bridge",
        return_value={"success": True, "response": "A thoughtful response.", "model_used": "dhq", "agent": "F.A.I.T.H."},
    ) as bridge, patch("tools.faith.routes.BRIDGE_AVAILABLE", True), _patched_db():
        resp = faith_client.post("/tools/faith/api/faith/chat", json={"message": "Help me reflect."})

    assert resp.status_code == 200
    assert bridge.call_args.kwargs["user_id"] == 1


def test_faith_chat_crisis_detection(faith_client):
    mock_result = {"success": True, "response": "...", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock_result), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.post(
            "/tools/faith/api/faith/chat",
            json={"message": "I have no reason to live"},
        )
    assert resp.status_code == 200
    assert resp.get_json().get("crisis_detected") is True


def test_faith_devotional(faith_client):
    mock = {"success": True, "response": "John 14:27", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.get("/tools/faith/api/faith/devotional")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_scripture_search(faith_client):
    mock = {"success": True, "response": "Psalm 34:18", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.post("/tools/faith/api/faith/scripture-search", json={"query": "grief"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_scripture_search_uses_profile_tradition(faith_client):
    captured = {}

    def fake_bridge(prompt, system_prompt, user_id=None):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        captured["user_id"] = user_id
        return {"success": True, "response": "Qur'an reference", "model_used": "dhq", "agent": "F.A.I.T.H."}

    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", side_effect=fake_bridge), patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "muslim", "prayer_style": "guided", "scripture_translation": "web"},
    ):
        resp = faith_client.post("/tools/faith/api/faith/scripture-search", json={"query": "mercy"})

    assert resp.status_code == 200
    assert "Muslim user" in captured["prompt"]
    assert "Tradition preference: Muslim" in captured["system_prompt"]


def test_faith_devotional_uses_multi_tradition_reflection_prompt(faith_client):
    captured = {}

    def fake_bridge(prompt, system_prompt, user_id=None):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        captured["user_id"] = user_id
        return {"success": True, "response": "A Dhammapada reflection", "model_used": "dhq", "agent": "F.A.I.T.H."}

    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", side_effect=fake_bridge), patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "buddhist", "prayer_style": "meditation", "scripture_translation": "web"},
    ):
        resp = faith_client.get("/tools/faith/api/faith/devotional")

    assert resp.status_code == 200
    assert "daily spiritual reflection" in captured["prompt"]
    assert "Buddhist user" in captured["prompt"]
    assert "Prayer/meditation style: meditation" in captured["system_prompt"]


def test_faith_checkin_saves(faith_client):
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
    _login(faith_client)
    with patch("tools.faith.routes._send_chaplain_email", return_value=True), _patched_db():
        resp = faith_client.post(
            "/tools/faith/api/faith/connect-chaplain",
            json={"message": "I need to talk."},
        )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


@pytest.mark.parametrize(
    'payload',
    [
        [],
        {},
        {"prayer_type": ""},
        {"prayer_type": "prosperity"},
        {"type": "general", "intention": "x" * 501},
    ],
)
def test_guided_prayer_rejects_invalid_payload_before_dispatch(faith_client, payload):
    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post("/tools/faith/api/faith/prayer", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    practice_dispatch.assert_not_called()


def test_guided_prayer_accepts_valid_prayer_type_field(faith_client):
    _login(faith_client)
    with patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "christian", "prayer_style": "guided"},
    ), patch(
        "tools.faith.routes._practice_dispatch",
        return_value={"success": True, "response": "A short prayer."},
    ) as practice_dispatch:
        resp = faith_client.post(
            "/tools/faith/api/faith/prayer",
            json={"prayer_type": "thanksgiving", "intention": "family"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    practice_dispatch.assert_called_once()


@pytest.mark.parametrize("payload", [{}, {"passage": ""}, {"passage": "x" * 501}])
def test_lectio_divina_rejects_invalid_payload_before_dispatch(faith_client, payload):
    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post("/tools/faith/api/faith/lectio", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    practice_dispatch.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "x" * 2001},
        {"message": "Please contact me.", "journal_ids": "1"},
        {"message": "Please contact me.", "journal_ids": ["abc"]},
        {"message": "Please contact me.", "journal_ids": list(range(21))},
    ],
)
def test_connect_chaplain_rejects_invalid_payload_before_email(faith_client, payload):
    _login(faith_client)
    with patch("tools.faith.routes._send_chaplain_email") as send_chaplain_email, patch(
        "tools.faith.routes.get_db_cursor"
    ) as get_db_cursor:
        resp = faith_client.post("/tools/faith/api/faith/connect-chaplain", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    send_chaplain_email.assert_not_called()
    get_db_cursor.assert_not_called()


def test_devotional_requires_authentication(faith_client):
    _logout(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.get("/tools/faith/api/faith/devotional")

    assert resp.status_code in (302, 401)
    practice_dispatch.assert_not_called()


def test_devotional_reports_dispatch_failure(faith_client):
    _login(faith_client)
    with patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "christian", "prayer_style": "guided"},
    ), patch(
        "tools.faith.routes._practice_dispatch",
        return_value={"success": False, "response": "F.A.I.T.H. is unavailable."},
    ):
        resp = faith_client.get("/tools/faith/api/faith/devotional")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert data["response"] == "F.A.I.T.H. is unavailable."


def test_guided_prayer_rejects_malformed_json_before_dispatch(faith_client):
    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post(
            "/tools/faith/api/faith/prayer",
            data="{",
            content_type="application/json",
        )

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "prayer_type required"}
    practice_dispatch.assert_not_called()


def test_guided_prayer_rejects_missing_prayer_type_before_dispatch(faith_client):
    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post("/tools/faith/api/faith/prayer", json={"intention": "family"})

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "prayer_type required"}
    practice_dispatch.assert_not_called()


def test_lectio_divina_rejects_malformed_json_before_dispatch(faith_client):
    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post(
            "/tools/faith/api/faith/lectio",
            data="{",
            content_type="application/json",
        )

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "passage required"}
    practice_dispatch.assert_not_called()


def test_checkin_history_returns_500_on_database_failure(faith_client):
    from psycopg2 import Error as PsycopgError

    _login(faith_client)
    with patch("tools.faith.routes._ensure_tables"), patch(
        "tools.faith.routes.get_db_cursor",
        side_effect=PsycopgError("database unavailable"),
    ):
        resp = faith_client.get("/tools/faith/api/faith/checkin/history")

    assert resp.status_code == 500
    assert resp.get_json() == {"success": False, "error": "Failed to load"}