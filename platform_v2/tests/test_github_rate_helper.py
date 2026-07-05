"""Tests for services.github_rate_helper — the bot-write GitHub rate guard (#2082)."""

import time

import pytest

from services import github_rate_helper as grh


class FakeResp:
    def __init__(self, status_code=200, headers=None, text="", payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clean_state():
    grh.reset_state()
    yield
    grh.reset_state()


def _write_resp(remaining, reset=None):
    return FakeResp(
        status_code=200,
        headers={
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset if reset is not None else time.time() + 3600),
        },
    )


def test_allows_when_quota_healthy():
    grh.observe(_write_resp(4999), is_write=True)
    allowed, info = grh.check_before_write(token=None)  # cache fresh → no probe
    assert allowed is True
    assert info["remaining"] == 4999
    assert "advisory" not in info


def test_advisory_below_threshold_but_allowed():
    grh.observe(_write_resp(3000), is_write=True)
    allowed, info = grh.check_before_write(token=None)
    assert allowed is True
    assert "advisory" in info


def test_blocks_when_quota_low():
    grh.observe(_write_resp(50), is_write=True)
    allowed, info = grh.check_before_write(token=None)
    assert allowed is False
    assert info["reason"] == "core_quota_low"
    assert info["remaining"] == 50


def test_allows_when_low_but_reset_already_elapsed():
    grh.observe(_write_resp(5, reset=time.time() - 10), is_write=True)
    allowed, info = grh.check_before_write(token=None)
    assert allowed is True
    assert info["reason"] == "quota_reset_elapsed"


def test_secondary_cooldown_blocks_with_retry_after():
    grh.record_secondary_rate_limit(retry_after=120)
    allowed, info = grh.check_before_write(token=None)
    assert allowed is False
    assert info["reason"] == "secondary_rate_limit_cooldown"
    assert 110 <= info["retry_after_s"] <= 120


def test_observe_trips_secondary_on_403_abuse_body():
    grh.observe(FakeResp(status_code=403, text="You have exceeded a secondary rate limit"))
    allowed, info = grh.check_before_write(token=None)
    assert allowed is False
    assert info["reason"] == "secondary_rate_limit_cooldown"


def test_observe_trips_secondary_on_429():
    grh.observe(FakeResp(status_code=429, text="Too Many Requests"))
    allowed, info = grh.check_before_write(token=None)
    assert allowed is False
    assert info["reason"] == "secondary_rate_limit_cooldown"


def test_read_response_does_not_move_write_bucket(monkeypatch):
    # A read-token response reporting a low bucket must NOT gate writes.
    grh.observe(_write_resp(1), is_write=False)
    # No probe should happen because token is None; remaining stays unknown → fail-open.
    called = {"probe": False}

    def _no_probe(*a, **k):
        called["probe"] = True
        raise AssertionError("should not probe without a token")

    monkeypatch.setattr(grh.requests, "get", _no_probe)
    allowed, info = grh.check_before_write(token=None)
    assert allowed is True
    assert info["reason"] == "rate_unknown_fail_open"
    assert called["probe"] is False


def test_fail_open_when_unknown_and_no_token():
    allowed, info = grh.check_before_write(token=None)
    assert allowed is True
    assert info["reason"] == "rate_unknown_fail_open"


def test_fail_open_when_probe_raises(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(grh.requests, "get", _boom)
    allowed, info = grh.check_before_write(token="tok")
    assert allowed is True
    assert info["reason"] == "rate_unknown_fail_open"


def test_probe_blocks_when_rate_limit_reports_low(monkeypatch):
    reset = time.time() + 3600

    def _fake_get(url, **k):
        assert url.endswith("/rate_limit")
        return FakeResp(payload={"resources": {"core": {"remaining": 10, "reset": reset}}})

    monkeypatch.setattr(grh.requests, "get", _fake_get)
    allowed, info = grh.check_before_write(token="tok", min_remaining=200)
    assert allowed is False
    assert info["reason"] == "core_quota_low"
    assert info["remaining"] == 10


def test_status_snapshot():
    grh.observe(_write_resp(4000), is_write=True)
    snap = grh.status()
    assert snap["core_remaining"] == 4000
    assert snap["secondary_cooldown_active"] is False
