"""Unit tests for mailbox_scout_capture (S.C.O.U.T. share-link -> Mailbox Story).

The archie_scraper HTTP calls and ingest_chat are stubbed — no network, no DB.
"""

import services.mailbox_scout_capture as svc


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _patch(monkeypatch, *, submit, polls, sleep_calls=None):
    """submit = POST /jobs payload; polls = list of successive GET /jobs/<id> payloads."""
    seq = list(polls)

    def fake_post(url, json=None, timeout=None):
        assert "/jobs" in url and (json or {}).get("job_type") == "chat_capture"
        return _Resp(submit)

    def fake_get(url, timeout=None):
        return _Resp(seq.pop(0) if seq else seq_last[0])

    seq_last = [polls[-1]] if polls else [{}]
    monkeypatch.setattr(svc.requests, "post", fake_post)
    monkeypatch.setattr(svc.requests, "get", fake_get)
    monkeypatch.setattr(svc.time, "sleep", lambda *_a, **_k: (sleep_calls or []).append(1))

    ingested = {}

    def fake_ingest(title, messages, owner_id=None):
        ingested["title"] = title
        ingested["messages"] = messages
        ingested["owner_id"] = owner_id
        return 7

    monkeypatch.setattr(svc, "ingest_chat", fake_ingest)
    return ingested


def test_rejects_non_http_url():
    assert "error" in svc.capture_share("ftp://nope")
    assert "error" in svc.capture_share("")


def test_happy_path_ingests_mapped_messages(monkeypatch):
    ingested = _patch(
        monkeypatch,
        submit={"job_id": 11, "status": "pending"},
        polls=[
            {"status": "running"},
            {
                "status": "approved",
                "data": {
                    "title": "Termination thread",
                    "messages": [["user", "hi"], ["assistant", "hello"], ["assistant", ""]],
                },
            },
        ],
    )
    res = svc.capture_share("https://chatgpt.com/share/abc", owner_id=1)
    assert res["import_id"] == 7
    assert res["messages"] == 2  # empty-text message dropped
    assert ingested["title"] == "Termination thread"
    assert ingested["messages"] == [("user", "hi", None), ("assistant", "hello", None)]
    assert ingested["owner_id"] == 1


def test_explicit_title_overrides_scraped(monkeypatch):
    _patch(
        monkeypatch,
        submit={"job_id": 1},
        polls=[{"status": "needs_review", "data": {"title": "auto", "messages": [["user", "q"]]}}],
    )
    res = svc.capture_share("https://x/share/1", title="My Title")
    assert res["title"] == "My Title"


def test_failed_job_returns_error(monkeypatch):
    _patch(monkeypatch, submit={"job_id": 2}, polls=[{"status": "failed", "error_log": "boom"}])
    res = svc.capture_share("https://x/share/2")
    assert res["error"] == "capture failed" and "boom" in res["detail"]


def test_no_messages_returns_error(monkeypatch):
    _patch(monkeypatch, submit={"job_id": 3}, polls=[{"status": "approved", "data": {"messages": []}}])
    assert "no messages" in svc.capture_share("https://x/share/3")["error"]


def test_submit_no_job_id_returns_error(monkeypatch):
    _patch(monkeypatch, submit={"status": "pending"}, polls=[{}])
    assert "no job_id" in svc.capture_share("https://x/share/4")["error"]


def test_timeout_returns_error(monkeypatch):
    # never reaches a terminal state; force the clock past the deadline immediately
    seq = iter([1000.0, 1000.0, 9_999_999.0])
    monkeypatch.setattr(svc.time, "time", lambda: next(seq))
    _patch(monkeypatch, submit={"job_id": 5}, polls=[{"status": "running"}])
    res = svc.capture_share("https://x/share/5", timeout_s=30)
    assert "timed out" in res["error"]
