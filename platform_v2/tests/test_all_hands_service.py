"""Tests for services/all_hands_service.py — All Hands protocol MVP (#2586).

Verifies the synchronous agent-level fan-out / fan-in:
  * items are assigned round-robin to the selected agents (distinct prefer_agent)
  * results are aligned to input order; success/failure counts + partial flag
  * a single item failing (returned OR raised) never fails the whole batch
  * empty agent set → un-pinned fallback (still dispatches + aggregates)
  * empty items → ValueError
"""

from __future__ import annotations

import pytest

from services import all_hands_service as ah


class _FakeResult:
    def __init__(self, success=True, response="ok", error=None, agent_name=None):
        self.success = success
        self.response = response
        self.error = error
        self.agent_name = agent_name


@pytest.fixture(autouse=True)
def _cap_concurrency(monkeypatch):
    # keep tests off the DB + deterministic
    monkeypatch.setattr(ah, "_max_concurrency", lambda: 4)


def _agents(*names):
    return [{"name": n, "id": i} for i, n in enumerate(names, 1)]


def test_fan_out_round_robins_items_across_distinct_agents():
    seen = []  # (prompt, prefer_agent)

    def fake_dispatch(cap, prompt, **kw):
        seen.append((prompt, kw.get("prefer_agent")))
        return _FakeResult(agent_name=kw.get("prefer_agent"))

    out = ah.all_hands_dispatch(
        "research",
        ["a", "b", "c", "d"],
        dispatch_fn=fake_dispatch,
        select_agents_fn=lambda cap, n: _agents("D.A.R.W.I.N.", "W.A.T.C.H."),
    )

    # 2 agents, 4 items → round-robin D/W/D/W
    assert dict(seen) == {"a": "D.A.R.W.I.N.", "b": "W.A.T.C.H.", "c": "D.A.R.W.I.N.", "d": "W.A.T.C.H."}
    assert out["total"] == 4 and out["succeeded"] == 4 and out["failed"] == 0
    assert out["partial"] is False
    assert out["agents_selected"] == ["D.A.R.W.I.N.", "W.A.T.C.H."]


def test_results_aligned_to_input_order():
    def fake_dispatch(cap, prompt, **kw):
        return _FakeResult(response=f"resp:{prompt}", agent_name=kw.get("prefer_agent"))

    items = ["one", "two", "three"]
    out = ah.all_hands_dispatch(
        "code", items, dispatch_fn=fake_dispatch, select_agents_fn=lambda c, n: _agents("F.O.R.G.E.")
    )
    assert [r["item"] for r in out["results"]] == items
    assert [r["index"] for r in out["results"]] == [0, 1, 2]
    assert [r["response"] for r in out["results"]] == ["resp:one", "resp:two", "resp:three"]


def test_partial_failure_returned_result_does_not_fail_batch():
    def fake_dispatch(cap, prompt, **kw):
        if prompt == "bad":
            return _FakeResult(success=False, response=None, error="model timeout")
        return _FakeResult(agent_name=kw.get("prefer_agent"))

    out = ah.all_hands_dispatch(
        "analyze",
        ["good", "bad", "good2"],
        dispatch_fn=fake_dispatch,
        select_agents_fn=lambda c, n: _agents("S.P.E.C.T.R.A."),
    )
    assert out["succeeded"] == 2 and out["failed"] == 1
    assert out["partial"] is True
    bad = next(r for r in out["results"] if r["item"] == "bad")
    assert bad["success"] is False and bad["error"] == "model timeout"


def test_item_exception_is_captured_not_raised():
    def fake_dispatch(cap, prompt, **kw):
        if prompt == "boom":
            raise RuntimeError("dispatcher blew up")
        return _FakeResult()

    out = ah.all_hands_dispatch(
        "research",
        ["ok", "boom"],
        dispatch_fn=fake_dispatch,
        select_agents_fn=lambda c, n: _agents("D.A.R.W.I.N."),
    )
    assert out["failed"] == 1
    boom = next(r for r in out["results"] if r["item"] == "boom")
    assert boom["success"] is False and "blew up" in boom["error"]


def test_no_available_agents_falls_back_to_unpinned_dispatch():
    calls = []

    def fake_dispatch(cap, prompt, **kw):
        calls.append(kw.get("prefer_agent"))
        return _FakeResult(agent_name="auto-picked")

    out = ah.all_hands_dispatch("research", ["x", "y"], dispatch_fn=fake_dispatch, select_agents_fn=lambda c, n: [])
    # every dispatch was un-pinned (no prefer_agent) but still ran + aggregated
    assert calls == [None, None]
    assert out["succeeded"] == 2
    assert out["agents_selected"] == []
    assert out["agents_used"] == ["auto-picked"]


def test_empty_items_raises():
    with pytest.raises(ValueError):
        ah.all_hands_dispatch("research", [], dispatch_fn=lambda *a, **k: _FakeResult())


def test_max_agents_caps_selection_request():
    requested = []

    def fake_select(cap, n):
        requested.append(n)
        return _agents("A", "B")

    ah.all_hands_dispatch(
        "research",
        ["1", "2", "3", "4", "5"],
        max_agents=2,
        dispatch_fn=lambda c, p, **k: _FakeResult(),
        select_agents_fn=fake_select,
    )
    # want = min(len(items)=5, max_agents=2) = 2
    assert requested == [2]
