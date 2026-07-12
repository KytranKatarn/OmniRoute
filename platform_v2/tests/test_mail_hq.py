"""Mail HQ — platform side (Slice 3 of the COO command surface).

Reads the owner/business inbox; drafts via R.E.S.O.L.V.E.; queues a reply into the EXISTING
approve-to-send gate (autonomy_approval_queue, action_type='email_reply') — never sends directly.
"""

import contextlib


def _fake_cursor(rows, capture=None):
    class _Cur:
        def execute(self, q, params=None):
            if capture is not None:
                capture["q"] = q
                capture["params"] = params

        def fetchall(self):
            return rows

        def fetchone(self):
            return rows[0] if rows else None

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


def test_list_inbox_scopes_owner_business(monkeypatch):
    import services.mail_hq_service as svc

    cap = {}
    monkeypatch.setattr(
        svc,
        "_get_cursor",
        lambda: _fake_cursor(
            [
                {
                    "id": 1,
                    "from_address": "a@b.com",
                    "subject": "Hi",
                    "ai_priority": "action",
                    "received_at": "2026-07-12",
                }
            ],
            cap,
        ),
    )
    rows = svc.list_inbox(limit=10)
    assert rows[0]["subject"] == "Hi"
    assert "mailbox_type = ANY(%s)" in cap["q"] and cap["params"][0] == ["owner", "business", "human_agent"]


def test_read_message_returns_body(monkeypatch):
    import services.mail_hq_service as svc

    monkeypatch.setattr(
        svc,
        "_get_cursor",
        lambda: _fake_cursor(
            [{"id": 5, "body_text": "hello", "from_address": "a@b.com", "mailbox_address": "owner@x.com"}]
        ),
    )
    m = svc.read_message(5)
    assert m["body_text"] == "hello" and m["mailbox_address"] == "owner@x.com"


def test_draft_reply_uses_support_dispatch(client, monkeypatch):
    # `client` boots the app so the dispatcher module (and its `from db import`) loads with the
    # ai_bridge path set up before we import it below (KB #272154); in prod it's always app-context.
    import services.mail_hq_service as svc

    monkeypatch.setattr(
        svc, "read_message", lambda mid: {"from_address": "a@b.com", "subject": "Q", "body_text": "help?"}
    )
    seen = {}
    import tools.department_hq.services.department_dispatcher as dd

    class _R:
        success = True
        response = "Happy to help."
        agent_name = "R.E.S.O.L.V.E."

    monkeypatch.setattr(dd, "dispatch", lambda **k: seen.update(k) or _R())
    out = svc.draft_reply(7)
    assert out["draft"] == "Happy to help." and out["agent"] == "R.E.S.O.L.V.E."
    assert seen["capability"] == "support" and seen["prefer_agent"] == "R.E.S.O.L.V.E."


def test_queue_reply_inserts_gated_approval(monkeypatch):
    import services.mail_hq_service as svc

    cap = {}

    class _Cur:
        def execute(self, q, params=None):
            cap.setdefault("qs", []).append(q)
            cap["last_params"] = params

        def fetchone(self):
            if "SELECT" in cap["qs"][-1]:
                return {
                    "mailbox_id": 2,
                    "from_address": "sender@x.com",
                    "subject": "Hello",
                    "message_id": "<abc@x>",
                    "thread_id": None,
                    "our_address": "owner@k.com",
                }
            return {"id": 99}  # RETURNING id

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    monkeypatch.setattr(svc, "_get_cursor", lambda: _cm)
    out = svc.queue_reply(7, "My reply body")
    assert out == {"queued": True, "approval_id": 99}
    ins = [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q][0]
    assert "'email_reply'" in ins and "'cockpit'" in ins


def test_queue_reply_empty_body(monkeypatch):
    import services.mail_hq_service as svc

    assert svc.queue_reply(7, "  ") is None


def test_inbox_endpoint_requires_key(client):
    assert client.get("/api/internal/mail/inbox").status_code == 401


def test_inbox_endpoint_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.mail_hq_service as svc

    monkeypatch.setattr(svc, "list_inbox", lambda **k: [{"id": 1, "subject": "Hi"}])
    r = client.get("/api/internal/mail/inbox?limit=5", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.get_json()["messages"][0]["subject"] == "Hi"


def test_queue_reply_endpoint_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.mail_hq_service as svc

    monkeypatch.setattr(svc, "queue_reply", lambda mid, body: {"queued": True, "approval_id": 12})
    r = client.post(
        "/api/internal/mail/queue-reply",
        json={"message_id": 7, "body": "hello"},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200 and r.get_json()["approval_id"] == 12
