"""Tests for the Collaboration tab trio endpoint — POST /api/collab/message (#4285).

The endpoint is ephemeral (no DB writes) and returns three distinct voices
{available, kytran, archie, claude}, gated on the Claude bridge health.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeBridge:
    """Stand-in for ClaudeBridge — no proxy/API calls."""

    def __init__(self, health, reply):
        self._health = health
        self._reply = reply
        self.sent = []

    def health_check(self):
        return self._health

    def send_message(self, message, system_prompt=None):
        self.sent.append(message)
        return self._reply


def _fresh_app(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    sys.modules.pop("app_comms", None)  # fresh import with the test SECRET_KEY
    import app_comms

    app_comms.app.config["TESTING"] = True
    app_comms.app.config["SESSION_COOKIE_SECURE"] = False
    app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
    return app_comms


def _patch_bridge(monkeypatch, health, reply):
    bridge = _FakeBridge(health, reply)
    monkeypatch.setattr(
        "collaboration.claude_bridge.get_claude_bridge", lambda: bridge
    )
    return bridge


class TestCollabMessage:
    def test_unauthenticated_returns_401(self, monkeypatch):
        app_comms = _fresh_app(monkeypatch)
        with app_comms.app.test_client() as c:
            resp = c.post("/api/collab/message", json={"message": "hi"})
            assert resp.status_code == 401

    def test_empty_message_returns_400(self, monkeypatch):
        app_comms = _fresh_app(monkeypatch)
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post("/api/collab/message", json={"message": "   "})
            assert resp.status_code == 400

    def test_malformed_json_returns_400_not_500(self, monkeypatch):
        """A non-JSON body must yield a clean 400, never an unhandled 500/415."""
        app_comms = _fresh_app(monkeypatch)
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post(
                "/api/collab/message",
                data="not json at all",
                content_type="text/plain",
            )
            assert resp.status_code == 400

    def test_bridge_offline_returns_available_false(self, monkeypatch):
        app_comms = _fresh_app(monkeypatch)
        _patch_bridge(
            monkeypatch,
            health={"status": "unavailable", "note": "Claude proxy down"},
            reply=None,
        )
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post("/api/collab/message", json={"message": "hi"})
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["available"] is False
            assert "note" in data

    def test_healthy_returns_three_voices(self, monkeypatch):
        app_comms = _fresh_app(monkeypatch)
        bridge = _patch_bridge(
            monkeypatch,
            health={"status": "healthy", "mode": "proxy"},
            reply="Hi — Claude here.",
        )
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post(
                "/api/collab/message", json={"message": "Confirm the trio works."}
            )
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["available"] is True
            assert data["kytran"] == "Confirm the trio works."
            assert data["archie"]  # A.R.C.H.I.E.'s framing line is non-empty
            assert data["claude"] == "Hi — Claude here."
            # The owner's message is forwarded to the bridge (framed).
            assert any("Confirm the trio works." in m for m in bridge.sent)

    def test_healthy_but_empty_reply_returns_available_false(self, monkeypatch):
        app_comms = _fresh_app(monkeypatch)
        _patch_bridge(
            monkeypatch,
            health={"status": "healthy", "mode": "proxy"},
            reply=None,  # reachable but no response
        )
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            resp = c.post("/api/collab/message", json={"message": "hi"})
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["available"] is False

    def test_ephemeral_no_db_writes(self, monkeypatch):
        """The endpoint must not persist to conversations (ephemeral by design)."""
        app_comms = _fresh_app(monkeypatch)
        _patch_bridge(
            monkeypatch,
            health={"status": "healthy", "mode": "proxy"},
            reply="ok",
        )
        from services import conversation_service

        calls = []
        monkeypatch.setattr(
            conversation_service, "save_message",
            lambda *a, **kw: calls.append(a) or {"id": 1},
        )
        with app_comms.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 1
            c.post("/api/collab/message", json={"message": "hi"})
            assert calls == []  # nothing written to the conversation store
