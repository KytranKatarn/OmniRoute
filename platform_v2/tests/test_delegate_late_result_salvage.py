"""#5313 — a late-but-successful delegate result is SALVAGED, not discarded.

EVIDENCE (2026-07-27, task #5310): the D.A.R.W.I.N. runtime survey spent
~12.5 min in the dispatch/cold-load queue (hub fact-check burst), so the
delegate worker's 660s deadline expired BEFORE inference even started —
then the generation itself succeeded in ~2m46s ("Fleet dispatch success:
D.A.R.W.I.N.@Starship - Runabout - USS-245 returned 5695 chars") and
run_delegation_cycle threw the finished artifact away at the line
"already blocked on a prior cycle — discard the late result". Third
identical loss for this one work item; queue wait, not generation time,
consumed the ceiling. Status != artifact.

Contract pinned here:
  * marked_blocked + future SUCCEEDED -> salvage_late_result() persists it
    and stats["salvaged"] increments (the entry still leaves inflight);
  * marked_blocked + future RAISED or returned failure -> nothing persisted
    (the row is already honestly blocked);
  * marked_blocked + cold-load "queued" result -> untouched (the
    dispatch_pending_queue callback owns that flip);
  * salvage_late_result flips ONLY a row still in status='blocked' (never
    stomps a re-queued/re-running task) and only then writes work_notes.
"""

from __future__ import annotations

import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest  # noqa: E402
from tests.modstub import stub_module_scoped  # noqa: E402

_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

# --- Resolve heavy imports the same way test_delegation_worker_concurrency.py does ----
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


# NOT a sys.modules stub. This used to install a bare
# `types.ModuleType("services.telegram_service")` via setdefault at MODULE level, which
# leaked into every test collected after this file and caused 9 failures across
# test_telegram_consolidation / test_pr_merge_surfaces / test_blocked_merge_escalation:
#   AttributeError: <module 'services.telegram_service'> has no attribute 'send_with_buttons'
#
# A bare ModuleType is a REAL module object carrying only the attributes set on it, so the
# error names a module that exists and looks legitimate — the failures read as "production
# moved, tests didn't" rather than as contamination. Those three files pass 44/45 in
# isolation; only collection ORDER made them fail.
#
# `setdefault` is what made it permanent: it wins whenever this file is collected before
# anything imports the real module, and nothing ever removes it.
#
# The real module imports cleanly (20+ other test files import it), and no test here ever
# referenced the stub — it existed only to keep delegation_service's import from doing real
# Telegram work. Patching the real functions achieves that without touching sys.modules.
@pytest.fixture(scope="module", autouse=True)
def _telegram_quiet():
    """Silence Telegram sends for this module without replacing the module object."""
    with patch("services.telegram_service.send_info", MagicMock(return_value={"sent": True})), patch(
        "services.telegram_service.send_system", MagicMock(return_value={"sent": True})
    ):
        yield


from services import delegation_service as ds  # noqa: E402


def _blocked_entry(pool, result=None, exc=None, task_id=5310, capability="research"):
    """An inflight entry whose thread finished AFTER the deadline marked it blocked."""

    def _run():
        if exc is not None:
            raise exc
        return result

    fut = pool.submit(_run)
    fut.exception()  # wait for the future to settle either way
    return {
        "future": fut,
        "task_id": task_id,
        "capability": capability,
        "source": "claude",
        "channel": None,
        "timeout": 660,
        "deadline": 0.0,  # long past
        "marked_blocked": True,
    }


@pytest.fixture
def cycle_env(monkeypatch):
    rec = {"salvaged": [], "completed": [], "failed": [], "queued": [], "emits": []}
    monkeypatch.setattr(ds, "fetch_pending_delegations", lambda limit: [])
    monkeypatch.setattr(ds, "reclaim_stale_delegations", lambda *a, **k: None)
    monkeypatch.setattr(
        ds, "mark_task_completed", lambda tid, summary, response=None, capability=None: rec["completed"].append(tid)
    )
    monkeypatch.setattr(ds, "mark_task_failed", lambda tid, err: rec["failed"].append((tid, err)))
    monkeypatch.setattr(ds, "mark_task_queued", lambda tid, summary: rec["queued"].append(tid))
    monkeypatch.setattr(ds, "emit_delegation_event", lambda tid, event, **k: rec["emits"].append((tid, event)))
    monkeypatch.setattr(
        ds,
        "salvage_late_result",
        lambda tid, summary, response=None, capability=None: (rec["salvaged"].append((tid, response)), True)[1],
    )
    return rec


def _run_cycle(pool, inflight):
    return ds.run_delegation_cycle(
        pool,
        inflight,
        concurrency=4,
        cycle_budget_secs=1,
        capability_timeouts={},
        default_timeout=10,
    )


class TestLateResultSalvage:
    def test_late_success_is_salvaged(self, cycle_env):
        pool = ThreadPoolExecutor(max_workers=1)
        entry = _blocked_entry(
            pool,
            result={"success": True, "summary": "ok", "result": {"response": "5695-char survey"}},
        )
        inflight = [entry]
        stats = _run_cycle(pool, inflight)
        pool.shutdown(wait=True)

        assert cycle_env["salvaged"] == [(5310, "5695-char survey")]
        assert stats.get("salvaged") == 1
        assert inflight == []  # slot freed
        assert cycle_env["failed"] == []  # not double-failed
        assert (5310, "complete") in cycle_env["emits"]

    def test_late_failure_stays_blocked(self, cycle_env):
        pool = ThreadPoolExecutor(max_workers=1)
        entry = _blocked_entry(pool, result={"success": False, "summary": "model err"})
        inflight = [entry]
        stats = _run_cycle(pool, inflight)
        pool.shutdown(wait=True)

        assert cycle_env["salvaged"] == []
        assert stats.get("salvaged") == 0
        assert inflight == []
        assert cycle_env["failed"] == []  # already marked on the timeout cycle

    def test_late_exception_stays_blocked(self, cycle_env):
        pool = ThreadPoolExecutor(max_workers=1)
        entry = _blocked_entry(pool, exc=RuntimeError("boom"))
        inflight = [entry]
        stats = _run_cycle(pool, inflight)
        pool.shutdown(wait=True)

        assert cycle_env["salvaged"] == []
        assert stats.get("salvaged") == 0
        assert inflight == []

    def test_late_queued_left_to_pending_queue_callback(self, cycle_env):
        pool = ThreadPoolExecutor(max_workers=1)
        entry = _blocked_entry(pool, result={"queued": True, "summary": "cold-load defer"})
        inflight = [entry]
        stats = _run_cycle(pool, inflight)
        pool.shutdown(wait=True)

        assert cycle_env["salvaged"] == []
        assert cycle_env["queued"] == []  # not re-marked either — callback owns it
        assert stats.get("salvaged") == 0


class _Cur:
    def __init__(self, rowcount):
        self.rowcount = rowcount
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))


class TestSalvageGuardSQL:
    def _stub_db(self, monkeypatch, rowcount):
        cur = _Cur(rowcount)

        @contextmanager
        def _gdc(commit=False):
            yield None, cur

        monkeypatch.setattr(ds, "get_db_cursor", _gdc)
        return cur

    def test_still_blocked_row_is_completed_with_notes(self, monkeypatch):
        cur = self._stub_db(monkeypatch, rowcount=1)
        ok = ds.salvage_late_result(5310, "late ok", response="the survey", capability="research")
        assert ok is True
        update_sql = cur.executed[0][0]
        assert "status = 'completed'" in update_sql
        assert "AND status = 'blocked'" in update_sql  # the guard
        note_types = [p for sql, p in cur.executed if "work_notes" in sql]
        assert len(note_types) == 2  # lifecycle note + real output

    def test_requeued_row_is_never_stomped(self, monkeypatch):
        cur = self._stub_db(monkeypatch, rowcount=0)
        ok = ds.salvage_late_result(5310, "late ok", response="the survey", capability="research")
        assert ok is False
        assert all("work_notes" not in sql for sql, _ in cur.executed)  # no notes written
