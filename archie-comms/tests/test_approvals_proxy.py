"""COO Cockpit Slice 1 — the thin cockpit->platform approvals proxy.

Mirrors conversation_service.dhq_chat_raw: GET/POST the platform's
@_require_internal_key approval endpoints with Bearer INTERNAL_API_KEY.
approve()/deny() are fail-CLOSED — any transport error returns
{"ok": False, "error": ...}, never an optimistic success.
"""

import services.approvals_proxy as ap


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload

    def json(self):
        return self._p


def test_list_pending_hits_internal_endpoint(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = (headers or {}).get("Authorization")
        return _Resp(200, {"approvals": [{"id": "autonomy:1"}]})

    monkeypatch.setattr(ap.requests, "get", fake_get)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ap.list_pending()
    assert out == [{"id": "autonomy:1"}]
    assert seen["url"].endswith("/api/internal/approvals/pending")
    assert seen["auth"] == "Bearer k"


def test_approve_posts_user_id(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        ap.requests,
        "post",
        lambda url, json=None, headers=None, timeout=None: seen.update(url=url, body=json)
        or _Resp(200, {"ok": True, "action_type": "improvement_approve_red"}),
    )
    out = ap.approve("autonomy:9", user_id=2)
    assert out["ok"] is True
    assert seen["url"].endswith("/api/internal/approvals/autonomy:9/approve")
    assert seen["body"]["user_id"] == 2


def test_deny_posts_reason(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        ap.requests,
        "post",
        lambda url, json=None, headers=None, timeout=None: seen.update(url=url, body=json)
        or _Resp(200, {"ok": True}),
    )
    out = ap.deny("autonomy:5", user_id=2, reason="not now")
    assert out["ok"] is True
    assert seen["url"].endswith("/api/internal/approvals/autonomy:5/deny")
    assert seen["body"] == {"user_id": 2, "reason": "not now"}


def test_approve_fail_closed_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("platform down")

    monkeypatch.setattr(ap.requests, "post", boom)
    out = ap.approve("autonomy:9", user_id=2)
    assert out["ok"] is False and "error" in out  # never optimistic


def test_approve_fail_closed_on_non_ok_status(monkeypatch):
    monkeypatch.setattr(
        ap.requests,
        "post",
        lambda url, json=None, headers=None, timeout=None: _Resp(409, {"ok": False}),
    )
    out = ap.approve("autonomy:9", user_id=2)
    assert out["ok"] is False


def test_list_pending_returns_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("platform down")

    monkeypatch.setattr(ap.requests, "get", boom)
    assert ap.list_pending() == []


def test_act_rejects_malformed_id_without_network(monkeypatch):
    """SSRF/path-traversal guard: a crafted id (slashes, dots, scheme, empty
    index, extra segments) is rejected fail-closed BEFORE any request is made —
    it can never ride the Bearer key to another internal endpoint."""

    def must_not_call(*a, **k):
        raise AssertionError("malformed id must not reach the network")

    monkeypatch.setattr(ap.requests, "post", must_not_call)
    for bad in (
        "../engine/telemetry",
        "autonomy:1/../dhq/chat",
        "autonomy:",
        "autonomy:1;rm",
        "http://evil/x",
        "autonomy:1/approve",
        "",
    ):
        out = ap.approve(bad, user_id=2)
        assert out["ok"] is False
        assert "invalid" in out["error"]
        out = ap.deny(bad, user_id=2, reason="x")
        assert out["ok"] is False


def test_valid_id_still_reaches_network(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        ap.requests,
        "post",
        lambda url, json=None, headers=None, timeout=None: seen.update(url=url) or _Resp(200, {"ok": True}),
    )
    assert ap.approve("autonomy:123", user_id=2)["ok"] is True
    assert seen["url"].endswith("/api/internal/approvals/autonomy:123/approve")
