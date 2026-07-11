"""Track B (CLI collaboration) — v1 chat API tests.

Hermetic: a fresh Flask app + the chat blueprint, with the auth boundary and
the conversation layer monkeypatched. Pins the contracts a CLI depends on:
Bearer-key entry, the DHQ round-trip (with explicit 502 degradation when the
platform is unreachable), and the chat-schema message writer.
"""

from flask import Blueprint, Flask
from flask_login import LoginManager

import chat.api_routes as ar
import chat.auth_middleware as am
import services.conversation_service as cs


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    # the decorator's session fallback resolves flask_login.current_user —
    # production app_comms initializes a LoginManager; the test app must too
    login_manager = LoginManager(app)

    @login_manager.user_loader
    def _load_user(user_id):  # anonymous-only in these tests
        return None
    bp = Blueprint("chat", __name__)
    ar.register_routes(bp, admin_required=lambda f: f)
    app.register_blueprint(bp)
    app.config["TESTING"] = True
    return app


def _auth_bearer(monkeypatch, user_id=7):
    monkeypatch.setattr(
        am,
        "_check_bearer_token",
        lambda: {
            "id": user_id,
            "username": "cli",
            "is_admin": False,
            "auth_method": "api_key",
            "scopes": ["chat"],
            "rate_limit": 30,
        },
    )


def _stub_conversation_layer(monkeypatch):
    monkeypatch.setattr(ar, "check_chat_access", lambda uid: {"allowed": True, "reason": ""})
    monkeypatch.setattr(ar, "get_user_team_id", lambda uid: None)
    monkeypatch.setattr(
        ar,
        "create_conversation",
        lambda uid, team_id=None, agent_target=None: {"id": 5, "conversation_uuid": "conv-uuid-5", "title": None},
    )
    monkeypatch.setattr(ar, "save_chat_message", lambda *a, **k: {"id": 99})
    monkeypatch.setattr(ar, "auto_title_conversation", lambda cid, msg: None)
    monkeypatch.setattr(ar, "get_conversation_context", lambda cid, max_messages=20, max_chars=4000: "")
    monkeypatch.setattr(ar, "get_conversation_messages", lambda cid, include_thinking=False, limit=20: [])
    monkeypatch.setattr(ar, "check_rate_limit", lambda uid, limit: True)


def test_v1_message_round_trips_through_dhq(monkeypatch):
    _auth_bearer(monkeypatch)
    _stub_conversation_layer(monkeypatch)
    seen = {}

    def stub_dhq(prompt, system_prompt=None, user_id=None):
        seen.update({"prompt": prompt, "user_id": user_id})
        return {"success": True, "response": "pong", "agent_name": "A.R.C.H.I.E.", "model_used": "dolphin3-8k"}

    monkeypatch.setattr(ar, "dhq_chat", stub_dhq)

    client = _app().test_client()
    r = client.post(
        "/api/v1/chat/message",
        json={"message": "ping"},
        headers={"Authorization": "Bearer archie_test"},
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["success"] is True
    assert body["response"] == "pong"
    assert body["conversation_id"] == "conv-uuid-5"
    assert body["agent"]["name"] == "A.R.C.H.I.E."
    assert body["model_used"] == "dolphin3-8k"
    assert seen["user_id"] == 7
    assert "ping" in seen["prompt"]


def test_v1_message_degrades_to_502_when_dhq_unreachable(monkeypatch):
    _auth_bearer(monkeypatch)
    _stub_conversation_layer(monkeypatch)
    monkeypatch.setattr(ar, "dhq_chat", lambda prompt, system_prompt=None, user_id=None: None)

    client = _app().test_client()
    r = client.post(
        "/api/v1/chat/message",
        json={"message": "ping"},
        headers={"Authorization": "Bearer archie_test"},
    )
    assert r.status_code == 502
    assert r.get_json()["error"]["code"] == "ORCHESTRATION_ERROR"


def test_v1_message_rejects_unauthenticated(monkeypatch):
    monkeypatch.setattr(am, "_check_bearer_token", lambda: None)
    client = _app().test_client()
    r = client.post("/api/v1/chat/message", json={"message": "hi"})
    assert r.status_code == 401


def test_save_chat_message_composes_unified_metadata(monkeypatch):
    captured = {}

    def fake_unified_save(conversation_id, channel, direction, sender, content, metadata=None):
        captured.update(
            {
                "conversation_id": conversation_id,
                "channel": channel,
                "direction": direction,
                "sender": sender,
                "content": content,
                "metadata": metadata,
            }
        )
        return {"id": 42}

    monkeypatch.setattr(cs, "save_message", fake_unified_save)

    out = cs.save_chat_message(
        5,
        "assistant",
        "hello there",
        agent_used="A.R.C.H.I.E.",
        model_used="dolphin3-8k",
        station_code="COMMAND",
        duration_ms=1234,
        thinking_steps=[{"step_type": "route"}],
    )
    assert out == {"id": 42}
    assert captured["direction"] == "outbound"
    assert captured["sender"] == "A.R.C.H.I.E."
    assert captured["channel"] == "api"
    md = captured["metadata"]
    # exactly the keys get_conversation_messages() unpacks
    assert md["role"] == "assistant"
    assert md["agent_used"] == "A.R.C.H.I.E."
    assert md["model_used"] == "dolphin3-8k"
    assert md["station_code"] == "COMMAND"
    assert md["duration_ms"] == 1234
    assert md["thinking_steps"] == [{"step_type": "route"}]


def test_save_chat_message_user_direction(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cs,
        "save_message",
        lambda cid, channel, direction, sender, content, metadata=None: captured.update(
            {"direction": direction, "sender": sender, "metadata": metadata}
        )
        or {"id": 1},
    )
    cs.save_chat_message(5, "user", "hi")
    assert captured["direction"] == "inbound"
    assert captured["sender"] == "user"
    assert captured["metadata"]["role"] == "user"
