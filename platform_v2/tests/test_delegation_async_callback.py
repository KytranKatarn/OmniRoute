"""Layer-3 (#269999) async cold-load delegation callback.

Covers the delegation_service side: a dispatch that returns ``queued=True``
(model cold) must NOT be reported as a failure — instead it attaches a
``delegation_result`` callback to the queue row and returns a ``queued``
outcome so the worker leaves the task in_progress (the dispatch_pending_queue
callback later completes/blocks it). The model_dispatch_service write-back
side is covered by a live end-to-end check.
"""

from __future__ import annotations

import sys
import types

import pytest

# Stub tools.department_hq.services.department_dispatcher in sys.modules so we
# can swap `dispatch` without importing the real module (it pulls
# ``from db import ...`` where ``db`` is under ai_bridge — not on the test
# sys.path). Same pattern as test_delegation_service.py.
sys.modules.setdefault("tools", types.ModuleType("tools"))
sys.modules.setdefault("tools.department_hq", types.ModuleType("tools.department_hq"))
_pkg_services = sys.modules.setdefault("tools.department_hq.services", types.ModuleType("tools.department_hq.services"))
_stub_dispatcher = types.ModuleType("tools.department_hq.services.department_dispatcher")
_stub_dispatcher.dispatch = lambda **kw: None

# PEP 562 catch-all: a sys.modules stub replaces the module for the WHOLE session, so
# ANY name a later-collected module imports from it must resolve or collection aborts
# for all 3,332 tests (#5665). Enumerating names is whack-a-mole — dispatch_json,
# DispatchResult and resolve_department_escalation_owner each surfaced in turn.
# Explicitly-set attributes above still win; this only catches the rest.
_stub_dispatcher.__getattr__ = lambda _n: MagicMock()
sys.modules["tools.department_hq.services.department_dispatcher"] = _stub_dispatcher
_pkg_services.department_dispatcher = _stub_dispatcher

# emit_delegation_event lazily imports telegram_service; stub it defensively.
_stub_telegram = types.ModuleType("services.telegram_service")
sys.modules.setdefault("services.telegram_service", _stub_telegram)

from services import delegation_service as ds  # noqa: E402


class _FakeResult:
    def __init__(self, **kw):
        self.success = False
        self.queued = False
        self.queue_id = None
        self.error = None
        self.response = None
        self.agent_name = "D.A.R.W.I.N."
        self.model_used = "qwen2.5:7b"
        self.__dict__.update(kw)


@pytest.fixture
def fake_dispatch(monkeypatch):
    """Set the stub dispatcher's return for one test."""

    def _set(result):
        _stub_dispatcher.dispatch = lambda **kw: result

    yield _set
    _stub_dispatcher.dispatch = lambda **kw: None


def test_queued_attaches_callback_and_returns_queued(fake_dispatch, monkeypatch):
    calls = {}
    fake_dispatch(_FakeResult(queued=True, queue_id=999))
    monkeypatch.setattr(
        ds,
        "_attach_delegation_callback",
        lambda qid, tid, cap, reason: calls.setdefault("attach", (qid, tid, cap)),
    )
    out = ds._execute_via_dispatcher("research", {}, "do research", origin="claude", task_id=42)
    assert out["queued"] is True
    assert out["success"] is False  # not done yet — the callback completes it
    assert out["result"]["queue_id"] == 999
    assert calls["attach"] == (999, 42, "research")  # callback wired to THIS task


def test_queued_without_task_id_does_not_attach(fake_dispatch, monkeypatch):
    calls = {}
    fake_dispatch(_FakeResult(queued=True, queue_id=999))
    monkeypatch.setattr(ds, "_attach_delegation_callback", lambda *a: calls.setdefault("attach", a))
    out = ds._execute_via_dispatcher("research", {}, "x")  # no task_id
    assert out["queued"] is True
    assert "attach" not in calls  # nothing to call back to


def test_real_non_queued_failure_still_refused(fake_dispatch):
    fake_dispatch(_FakeResult(success=False, queued=False, error="no agent available"))
    out = ds._execute_via_dispatcher("research", {}, "x", task_id=1)
    assert out["success"] is False
    assert not out.get("queued")
    assert "Dispatcher refused" in out["summary"]


def test_success_path_unchanged(fake_dispatch):
    fake_dispatch(_FakeResult(success=True, response="the answer", model_used="qwen2.5:7b"))
    out = ds._execute_via_dispatcher("research", {}, "x", task_id=1)
    assert out["success"] is True
    assert not out.get("queued")
    assert out["result"]["response"] == "the answer"
