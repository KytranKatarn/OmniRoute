"""Regression tests for the K.I.N. barracked-RESCUE fix (bug #5155, 2026-07-24).

Root cause: 'barracked' is the failure-standby bench and does NOT auto-recover.
But agents also reach 'barracked' for NON-failure reasons (a fresh hire benched
seconds after creation — G.A.M.B.I.T. was barracked 1 min after being hired
active; a fleet-health/node-offline flap), then strand FOREVER. So approved hires
never joined the dispatchable pool, and recommend_pool_staffing_gaps re-proposed
the same News skills (fact_check / bias_analysis) every daily cycle despite the
prior day's approvals.

Fix: _run_kin_stuck_agent_reaper (tools/department_hq/jobs.py) recovers a
barracked agent -> active ONLY when it is genuinely stuck (>10 min), low stress
(<0.70), has no active rest cycle, and carries NO recent failure-standby marker
(agent_learning_records.learning_type='failure_standby' within 6h). Genuinely-
failing agents keep their Academy/verification window; only accidental strandings
are recovered, so this cannot defeat the failure-standby.

The reaper is raw SQL inside a scheduler job, so the primary proof is the
SQL-source regression below plus the DB-predicate behavioural check (the piece
that keeps the rescue safe), which runs when a DB is reachable and skips cleanly
otherwise.
"""

from __future__ import annotations

import os

import pytest
from tests.dbguard import db_or_skip, import_or_skip  # noqa: E402

_JOBS_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "department_hq", "jobs.py")


def test_reaper_has_barracked_rescue_with_failure_bench_exclusion():
    """The reaper must recover stranded 'barracked' agents AND exclude genuinely
    failure-benched ones — the exclusion is what makes it safe."""
    with open(_JOBS_PATH, encoding="utf-8") as fh:
        src = fh.read()
    assert "a.shift_state='barracked'" in src, "reaper must recover stranded barracked agents"
    assert "freed_barracked" in src, "barracked-rescue branch must be wired into the reaper"
    # The failure-standby exclusion is load-bearing: without it the rescue would
    # wake genuinely-failing agents that the failure-standby correctly benched.
    assert (
        "learning_type='failure_standby'" in src and "lr.learned_at > NOW() - INTERVAL '6 hours'" in src
    ), "barracked-rescue must exclude agents inside their failure-standby Academy window"
    # Only rescue agents genuinely stuck (not mid-transition) with cleared welfare.
    assert "a.updated_at < NOW() - INTERVAL '10 minutes'" in src, "rescue only genuinely-stuck barracked agents"


def _db_or_skip():
    try:
        from database import get_db_cursor  # noqa: WPS433

        return get_db_cursor
    except Exception as exc:  # pragma: no cover - import/env dependent
        import_or_skip(exc, "database module")


def test_failure_bench_marker_excludes_agent_from_rescue():
    """Behavioural: an agent becomes NON-rescuable the moment it gets a recent
    failure_standby learning record, and is rescuable without one. Rolled back."""
    get_db_cursor = _db_or_skip()
    rescuable_q = (
        "SELECT NOT EXISTS(SELECT 1 FROM agent_learning_records lr "
        "WHERE lr.agent_id=%s AND lr.learning_type='failure_standby' "
        "AND lr.learned_at > NOW() - INTERVAL '6 hours') AS rescuable"
    )
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT id FROM agents WHERE worker_type='ai' LIMIT 1")
            row = cur.fetchone()
            if not row:
                pytest.skip("no ai agent rows to test against")
            aid = row["id"] if isinstance(row, dict) else row[0]
            try:
                cur.execute(rescuable_q, (aid,))
                res = cur.fetchone()
                before = res["rescuable"] if isinstance(res, dict) else res[0]
                assert before is True, "agent with no failure-bench marker must be rescuable"

                cur.execute(
                    "INSERT INTO agent_learning_records "
                    "(agent_id, learning_type, subject, lesson_learned, source_type, learned_at) "
                    "VALUES (%s,'failure_standby','reliability','pytest bench','pytest',NOW())",
                    (aid,),
                )
                cur.execute(rescuable_q, (aid,))
                res = cur.fetchone()
                after = res["rescuable"] if isinstance(res, dict) else res[0]
                assert after is False, "a recently failure-benched agent must be EXCLUDED from rescue"
            finally:
                conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - DB connectivity dependent
        db_or_skip(exc)


def test_transition_shift_state_bumps_updated_at():
    """The canonical single-writer must bump agents.updated_at on every transition.

    Without it (bug #5155) a woken/transitioned agent showed a FROZEN 'last updated'
    in the K.I.N. tab — V.I.S.A.G.E. read 8 days stale right after being woken to
    active. The reaper's raw SQL already sets updated_at=NOW(); the writer must match.
    """
    svc_path = os.path.join(os.path.dirname(__file__), "..", "services", "agent_service.py")
    with open(svc_path, encoding="utf-8") as fh:
        src = fh.read()
    assert (
        "UPDATE agents SET shift_state = %s, updated_at = NOW() WHERE id = %s" in src
    ), "transition_shift_state must set updated_at=NOW() alongside shift_state (bug #5155)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
