"""Unit tests for the S6-P1-7b rate_limited reschedule contract in browser_service.

The sidecar (S6-P1-7a) now returns task status='rate_limited' when a profile's bucket
is exhausted. run_skill_sync must surface this as a DISTINCT _status (not 'failed' /
'timeout') so callers SKIP rather than mark a post failed or a session stale. Pure —
the HTTP layer is mocked, no sidecar / DB.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_browser_service_rate_limited.py -v
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


def test_run_skill_sync_surfaces_rate_limited(monkeypatch):
    monkeypatch.setattr(bs, "POLL_INTERVAL_S", 0)
    monkeypatch.setattr(bs, "run_skill", lambda *a, **k: {"task_id": "t1", "status": "pending"})
    monkeypatch.setattr(
        bs.requests,
        "get",
        lambda *a, **k: _Resp(
            {"status": "rate_limited", "error": "rate_limited; retry after 1800s", "retry_after": 1800.0}
        ),
    )
    res = bs.run_skill_sync("linkedin_post", {"content": "x"})
    assert res["_status"] == "rate_limited"
    assert res["success"] is False
    assert res["retry_after"] == 1800.0
    assert bs.is_rate_limited(res) is True


def test_completed_is_not_rate_limited(monkeypatch):
    monkeypatch.setattr(bs, "POLL_INTERVAL_S", 0)
    monkeypatch.setattr(bs, "run_skill", lambda *a, **k: {"task_id": "t2", "status": "pending"})
    monkeypatch.setattr(
        bs.requests,
        "get",
        lambda *a, **k: _Resp({"status": "completed", "result": {"success": True, "name": "ok"}}),
    )
    res = bs.run_skill_sync("linkedin_feed", {"limit": 5})
    assert res["_status"] == "completed"
    assert bs.is_rate_limited(res) is False


def test_failed_is_not_rate_limited(monkeypatch):
    monkeypatch.setattr(bs, "POLL_INTERVAL_S", 0)
    monkeypatch.setattr(bs, "run_skill", lambda *a, **k: {"task_id": "t3", "status": "pending"})
    monkeypatch.setattr(bs.requests, "get", lambda *a, **k: _Resp({"status": "failed", "error": "boom"}))
    res = bs.run_skill_sync("linkedin_post", {"content": "x"})
    assert res["_status"] == "failed"
    assert bs.is_rate_limited(res) is False


def test_is_rate_limited_helper():
    assert bs.is_rate_limited({"_status": "rate_limited"}) is True
    assert bs.is_rate_limited({"_status": "failed"}) is False
    assert bs.is_rate_limited({"_status": "completed"}) is False
    assert bs.is_rate_limited({}) is False
    assert bs.is_rate_limited(None) is False
