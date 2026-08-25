"""Unit tests for delegation_service.run_delegation_cycle (Project #375).

Proves the concurrent draining engine that replaced the serial worker loop:
  * claimed tasks run CONCURRENTLY (wall-clock ~= slowest, not the sum),
  * free-slot accounting never oversubscribes the bounded pool,
  * a future past its real per-capability deadline is marked blocked ONCE
    and keeps its slot until the thread actually finishes (no pool clog),
  * the cold-load ``queued`` defer path leaves the row in_progress.

DB + comms boundaries are stubbed; we drive a REAL ThreadPoolExecutor so the
concurrency assertions are meaningful.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch


import pytest  # noqa: E402
from tests.modstub import stub_module_scoped  # noqa: E402

# --- Resolve heavy imports the same way test_delegation_service.py does ----
_pkg_tools = sys.modules.setdefault("tools", types.ModuleType("tools"))
_pkg_dhq = sys.modules.setdefault("tools.department_hq", types.ModuleType("tools.department_hq"))
_pkg_services = sys.modules.setdefault("tools.department_hq.services", types.ModuleType("tools.department_hq.services"))
_stub_dispatcher = types.ModuleType("tools.department_hq.services.department_dispatcher")
_stub_dispatcher.dispatch = MagicMock(return_value=MagicMock(success=False))

# PEP 562 catch-all: a sys.modules stub replaces the module for the WHOLE session, so
# ANY name a later-collected module imports from it must resolve or collection aborts
# for all 3,332 tests (#5665). Enumerating names is whack-a-mole — dispatch_json,
# DispatchResult and resolve_department_escalation_owner each surfaced in turn.
# Explicitly-set attributes above still win; this only catches the rest.
_stub_dispatcher.__getattr__ = lambda _n: MagicMock()
# ── Scoped to THIS MODULE'S tests, not the whole session (#6018) ─────────────────────
# This was a bare, permanent assignment at import time. pytest imports every test module
# during COLLECTION, so from that point the stub was what the ENTIRE session saw and any
# later module wanting the real dispatcher silently got the stub instead (#6017).
_DISPATCHER = "tools.department_hq.services.department_dispatcher"


@pytest.fixture(scope="module", autouse=True)
def _dispatcher_stub():
    """Install the dispatcher stub for this module only; restore both bindings after."""
    with stub_module_scoped(_DISPATCHER, _stub_dispatcher):
        yield


# NOT a sys.modules stub (see test_delegate_late_result_salvage.py for the full note).
# FIVE test modules each installed a bare `types.ModuleType("services.telegram_service")`
# via setdefault at import time, with DIFFERENT attribute sets — one of them empty. Because
# setdefault means first-writer-wins, whichever file pytest collected first silently defined
# the telegram API that every later test saw, and the rest inherited it. Removing only one
# handed the slot to a poorer stub and turned 10 failures into 38 errors.
# Patching the real module keeps sys.modules honest and makes collection order irrelevant.
@pytest.fixture(scope="module", autouse=True)
def _telegram_quiet():
    """Silence Telegram sends for this module without replacing the module object."""
    with patch("services.telegram_service.send_info", MagicMock(return_value={"sent": True})), patch(
        "services.telegram_service.send_system", MagicMock(return_value={"sent": True})
    ):
        yield


from services import delegation_service as ds  # noqa: E402


# Task ids this file ever queues. Anything else reaching the recorder came from OUTSIDE
# this test — see _recording_complete below (#6019).
_OWN_TASK_IDS = frozenset({1, 2, 3, 4, 5, 7, 9})


def _recording_complete(rec):
    """Record completions, and make a FOREIGN one self-diagnosing (#6019).

    test_tasks_run_concurrently failed once in three full-suite runs with
        assert [1, 2, 3, 4, 33, 34, ...] == [1, 2, 3, 4]
    Four consecutive ids this file never queues (it uses only 1,2,3,4,5,7,9) arrived in a
    PER-TEST fixture's recorder. Something outside the test called the monkeypatched
    `ds.mark_task_completed` while it was installed — a worker thread that outlived its own
    test and is still running against the same delegation_service module object.

    The leak source is NOT identifiable statically: every ThreadPoolExecutor in these files
    is `shutdown(wait=True)`, delegation_service's only detached thread is the telegram
    fire-and-forget one (which never touches mark_task_completed), and no delegation test
    file uses ids in the 30s. It is also not reproducible on demand — it passed the other
    two runs.

    So: capture it when it next happens rather than guess. This prints the offending id and
    the FULL STACK of whatever thread is calling, which names the leaker directly. Kept in
    the assertion path (not a bare print) so the evidence lands in the failure output.

    ⚠️ Do NOT "fix" #6019 by filtering foreign ids out of `rec`. That would hide a thread
    doing real work during unrelated tests, which is the actual defect.
    """

    def _mark(tid, summary, response=None, capability=None):
        if tid not in _OWN_TASK_IDS:
            import threading as _t
            import traceback as _tb

            rec.setdefault("foreign", []).append(
                {
                    "tid": tid,
                    "thread": _t.current_thread().name,
                    "stack": "".join(_tb.format_stack()),
                }
            )
        rec["completed"].append(tid)

    return _mark


@pytest.fixture
def patched(monkeypatch):
    """Patch every DB/comms boundary; return a recorder of mark_* calls."""
    rec = {
        "in_progress": [],
        "completed": [],
        "failed": [],
        "queued": [],
        "fetch_calls": [],
    }

    def _fetch(limit):
        rec["fetch_calls"].append(limit)
        batch = rec.pop("_next_batch", [])
        return batch

    monkeypatch.setattr(ds, "fetch_pending_delegations", _fetch)
    monkeypatch.setattr(ds, "mark_task_in_progress", lambda tid: rec["in_progress"].append(tid))
    monkeypatch.setattr(ds, "mark_task_completed", _recording_complete(rec))
    monkeypatch.setattr(ds, "mark_task_failed", lambda tid, err: rec["failed"].append((tid, err)))
    monkeypatch.setattr(ds, "mark_task_queued", lambda tid, summary: rec["queued"].append(tid))
    monkeypatch.setattr(ds, "emit_delegation_event", lambda *a, **k: None)
    # These tests exercise the concurrency/deadline loop with synthetic capabilities
    # (e.g. 'slowcap'); bypass the #cont-103 fail-fast gate so they reach the submit
    # path. The gate itself is covered by test_delegation_fail_fast.py + live checks.
    monkeypatch.setattr(ds, "_capability_is_routable", lambda capability: True)
    return rec


def _task(tid, capability="research"):
    return {
        "id": tid,
        "delegation_source": "mcp_client",
        "delegation_args": {"capability": capability},
        "streaming_channel": None,
    }


def test_tasks_run_concurrently(patched, monkeypatch):
    """4 tasks that each sleep 0.4s finish in ~0.4s (concurrent), not ~1.6s."""
    monkeypatch.setattr(
        ds,
        "execute_delegated_task",
        lambda task: (time.sleep(0.4) or {"success": True, "summary": "ok"}),
    )
    patched["_next_batch"] = [_task(i) for i in range(1, 5)]
    pool = ThreadPoolExecutor(max_workers=4)
    inflight = []
    t0 = time.time()
    stats = ds.run_delegation_cycle(
        pool,
        inflight,
        concurrency=4,
        cycle_budget_secs=5,
        capability_timeouts={},
        default_timeout=10,
    )
    elapsed = time.time() - t0
    pool.shutdown(wait=True)

    assert stats["completed"] == 4
    assert sorted(patched["completed"]) == [
        1,
        2,
        3,
        4,
    ], "foreign completions leaked in from another test's thread (#6019): " + repr(patched.get("foreign", []))
    assert elapsed < 1.2, f"serial would be ~1.6s; got {elapsed:.2f}s"
    assert inflight == []  # all finished within budget, nothing carried


def test_free_slot_gating_no_oversubscribe(patched, monkeypatch):
    """With all slots busy on carry-over tasks, a cycle claims nothing."""
    gate = threading.Event()

    def _gated(task):
        gate.wait(5)
        return {"success": True, "summary": "ok"}

    monkeypatch.setattr(ds, "execute_delegated_task", _gated)
    pool = ThreadPoolExecutor(max_workers=2)
    inflight = []
    try:
        # Cycle 1: claim 2 blocking tasks; budget tiny so both carry over.
        patched["_next_batch"] = [_task(1), _task(2)]
        ds.run_delegation_cycle(
            pool,
            inflight,
            concurrency=2,
            cycle_budget_secs=0.1,
            capability_timeouts={},
            default_timeout=10,
        )
        assert len(inflight) == 2
        assert patched["fetch_calls"] == [2]

        # Cycle 2: both still running → busy=2, free=0 → fetch NOT called again.
        ds.run_delegation_cycle(
            pool,
            inflight,
            concurrency=2,
            cycle_budget_secs=0.1,
            capability_timeouts={},
            default_timeout=10,
        )
        assert patched["fetch_calls"] == [2], "must not claim when no free slots"
        assert len(inflight) == 2
    finally:
        gate.set()
        pool.shutdown(wait=True)

    # Cycle 3: tasks done → carry-over handled, slots freed.
    patched["_next_batch"] = []
    ds.run_delegation_cycle(
        pool,
        inflight,
        concurrency=2,
        cycle_budget_secs=0.1,
        capability_timeouts={},
        default_timeout=10,
    )
    assert sorted(patched["completed"]) == [1, 2]
    assert inflight == []


def test_deadline_overrun_marks_blocked_once(patched, monkeypatch):
    """A task past its real deadline is marked blocked exactly once and kept."""
    gate = threading.Event()

    def _gated(task):
        gate.wait(5)
        return {"success": True, "summary": "ok"}

    monkeypatch.setattr(ds, "execute_delegated_task", _gated)
    pool = ThreadPoolExecutor(max_workers=1)
    inflight = []
    try:
        # capability timeout 0.1s; budget 0.05s → carries, then overruns deadline.
        patched["_next_batch"] = [_task(7, capability="slowcap")]
        ds.run_delegation_cycle(
            pool,
            inflight,
            concurrency=1,
            cycle_budget_secs=0.05,
            capability_timeouts={"slowcap": 0.1},
            default_timeout=10,
        )
        assert len(inflight) == 1 and not inflight[0]["marked_blocked"]

        time.sleep(0.2)  # pass the 0.1s real deadline
        ds.run_delegation_cycle(
            pool,
            inflight,
            concurrency=1,
            cycle_budget_secs=0.05,
            capability_timeouts={"slowcap": 0.1},
            default_timeout=10,
        )
        assert len(patched["failed"]) == 1, "blocked exactly once"
        assert inflight[0]["marked_blocked"] is True
        assert len(inflight) == 1, "still busy until the thread truly dies"

        # Another cycle: still running, already blocked → no double-mark.
        ds.run_delegation_cycle(
            pool,
            inflight,
            concurrency=1,
            cycle_budget_secs=0.05,
            capability_timeouts={"slowcap": 0.1},
            default_timeout=10,
        )
        assert len(patched["failed"]) == 1, "must not re-mark a blocked task"
    finally:
        gate.set()
        pool.shutdown(wait=True)

    # Once the thread finishes, the late success is discarded (already blocked).
    ds.run_delegation_cycle(
        pool,
        inflight,
        concurrency=1,
        cycle_budget_secs=0.05,
        capability_timeouts={"slowcap": 0.1},
        default_timeout=10,
    )
    assert patched["completed"] == [], "late result of a blocked task is dropped"
    assert inflight == []


def test_cycle_reclaims_stale_excluding_live_inflight(patched, monkeypatch):
    """Each cycle calls the orphan reclaimer, excluding tasks the live worker
    is currently tracking (its inflight set)."""
    calls = {}

    def _fake_reclaim(exclude_ids, idle_secs=600, limit=10):
        calls["exclude"] = list(exclude_ids)
        return {"reclaimed": 0, "gave_up": 0}

    monkeypatch.setattr(ds, "reclaim_stale_delegations", _fake_reclaim)
    monkeypatch.setattr(ds, "execute_delegated_task", lambda task: {"success": True, "summary": "ok"})

    pool = ThreadPoolExecutor(max_workers=2)
    # Pre-seed inflight with a fake running entry the worker is tracking.
    running = pool.submit(lambda: __import__("time").sleep(2) or {"success": True, "summary": "x"})
    inflight = [
        {
            "future": running,
            "task_id": 99,
            "capability": "research",
            "source": "mcp_client",
            "channel": None,
            "timeout": 10,
            "deadline": time.time() + 10,
            "marked_blocked": False,
        }
    ]
    patched["_next_batch"] = []
    try:
        ds.run_delegation_cycle(
            pool,
            inflight,
            concurrency=2,
            cycle_budget_secs=0.1,
            capability_timeouts={},
            default_timeout=10,
        )
        assert calls["exclude"] == [99], "must exclude the live inflight task id"
    finally:
        running.result(5)
        pool.shutdown(wait=True)


def test_queued_path_leaves_in_progress(patched, monkeypatch):
    """A cold-load 'queued' result records queued, never completed/failed."""
    monkeypatch.setattr(ds, "execute_delegated_task", lambda task: {"queued": True, "summary": "cold-load deferred"})
    patched["_next_batch"] = [_task(9)]
    pool = ThreadPoolExecutor(max_workers=2)
    inflight = []
    stats = ds.run_delegation_cycle(
        pool,
        inflight,
        concurrency=2,
        cycle_budget_secs=5,
        capability_timeouts={},
        default_timeout=10,
    )
    pool.shutdown(wait=True)
    assert stats["queued"] == 1
    assert patched["queued"] == [9]
    assert patched["completed"] == [] and patched["failed"] == []
