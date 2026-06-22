"""Unit tests for the S6-P1-8b client behavior in browser_service.

run_skill forwards the idempotency_key; run_skill_sync, ONLY when a key is set (a publish),
re-polls a few more times past the deadline so a post that completes just-too-late reports
'completed' (truthful) instead of a false 'timeout' an operator might retry into a double-post.
Pure — HTTP mocked, no sidecar / DB.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_browser_service_idempotency.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import browser_service as bs  # noqa: E402


class _Resp:
    ok = True

    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_run_skill_forwards_idempotency_key(monkeypatch):
    captured = {}

    def _post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return _Resp({"task_id": "t", "status": "pending"})

    monkeypatch.setattr(bs.requests, "post", _post)
    bs.run_skill("linkedin_post", {"content": "x"}, idempotency_key="abc", post_metadata={"k": 1})
    assert captured["body"]["idempotency_key"] == "abc"
    assert captured["body"]["post_metadata"] == {"k": 1}


def test_run_skill_omits_key_when_absent(monkeypatch):
    captured = {}

    def _post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return _Resp({"task_id": "t", "status": "pending"})

    monkeypatch.setattr(bs.requests, "post", _post)
    bs.run_skill("linkedin_feed", {"limit": 5})
    assert "idempotency_key" not in captured["body"]
    assert "post_metadata" not in captured["body"]


def test_grace_repoll_recovers_late_completion_with_key(monkeypatch):
    # timeout_s=0 → main poll loop is skipped → only the grace re-poll runs (key set).
    monkeypatch.setattr(bs, "RECOVERY_BACKOFF_S", 0)
    monkeypatch.setattr(bs, "run_skill", lambda *a, **k: {"task_id": "t", "status": "pending"})
    monkeypatch.setattr(
        bs.requests,
        "get",
        lambda *a, **k: _Resp({"status": "completed", "result": {"success": True, "post_url": "u"}}),
    )
    res = bs.run_skill_sync("linkedin_post", {"content": "x"}, timeout_s=0, idempotency_key="abc")
    assert res["_status"] == "completed" and res.get("success") is True and res.get("post_url") == "u"


def test_no_grace_repoll_without_key(monkeypatch):
    # No key (a read skill) → no grace re-poll → a never-completing task is a clean timeout.
    monkeypatch.setattr(bs, "run_skill", lambda *a, **k: {"task_id": "t", "status": "pending"})
    monkeypatch.setattr(bs.requests, "get", lambda *a, **k: _Resp({"status": "running"}))
    res = bs.run_skill_sync("linkedin_feed", {"limit": 5}, timeout_s=0)
    assert res["_status"] == "timeout"


def test_grace_repoll_bounded_then_timeout(monkeypatch):
    # Key set but the task never completes → grace re-poll is bounded → still a timeout.
    monkeypatch.setattr(bs, "RECOVERY_BACKOFF_S", 0)
    monkeypatch.setattr(bs, "RECOVERY_REPOLLS", 2)
    monkeypatch.setattr(bs, "run_skill", lambda *a, **k: {"task_id": "t", "status": "pending"})
    monkeypatch.setattr(bs.requests, "get", lambda *a, **k: _Resp({"status": "running"}))
    res = bs.run_skill_sync("linkedin_post", {"content": "x"}, timeout_s=0, idempotency_key="abc")
    assert res["_status"] == "timeout"
