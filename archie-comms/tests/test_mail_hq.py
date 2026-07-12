"""Mail HQ — cockpit proxy (Slice 3). Server-side proxy to the platform Mail endpoints; the
INTERNAL_API_KEY never reaches the browser. Reads free; send GATED (queue_reply -> approval)."""
import services.mail_hq as mh


def test_inbox_proxy(monkeypatch):
    class _R:
        status_code = 200

        def json(self):
            return {"success": True, "messages": [{"id": 1, "subject": "Hi"}]}

    import requests as rq

    monkeypatch.setattr(rq, "get", lambda url, headers=None, params=None, timeout=None: _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert mh.inbox()["messages"][0]["subject"] == "Hi"


def test_queue_reply_proxy_posts_body(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"success": True, "queued": True, "approval_id": 3}

    import requests as rq

    monkeypatch.setattr(
        rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(url=url, json=json) or _R()
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = mh.queue_reply(7, "body text")
    assert out["approval_id"] == 3
    assert seen["url"].endswith("/api/internal/mail/queue-reply") and seen["json"]["body"] == "body text"


def test_inbox_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert mh.inbox() == {"messages": []}
