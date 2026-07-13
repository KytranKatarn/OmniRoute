"""Chat read-routes must FAIL CLOSED — a session that has `kytran_user` but no `user_id`
must not fall back to another user's (id 2) data. Regression guard for removing the
`session.get("user_id", 2)` fallback in app_comms.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _fresh_app(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    sys.modules.pop("app_comms", None)
    import app_comms

    app_comms.app.config["TESTING"] = True
    return app_comms


def test_conversations_fail_closed_when_user_id_missing(monkeypatch):
    # kytran_user present (passes the gate) but NO user_id — must 401, not read user 2.
    app_comms = _fresh_app(monkeypatch)
    with app_comms.app.test_client() as c:
        with c.session_transaction() as s:
            s["kytran_user"] = {"sub": "x"}
        r = c.get("/api/chat/conversations")
    assert r.status_code == 401


def test_conversations_unauthenticated_401(monkeypatch):
    app_comms = _fresh_app(monkeypatch)
    r = app_comms.app.test_client().get("/api/chat/conversations")
    assert r.status_code == 401
