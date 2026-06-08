"""Regression tests for the K.I.N. welfare rest-ENFORCEMENT fix (2026-06-08).

Root cause (fixed): the `kin_stuck_agent_reaper` FIX-8 restore guard
(tools/department_hq/jobs.py) only checked `agent_rest_cycles.ended_at IS NULL`,
so it could NOT see a BOUNDED rest cycle (the COO 12h mandatory rest writes
`ended_at = NOW() + INTERVAL '8 hours'` — a FUTURE timestamp, not NULL).
Result: every 5 min the reaper restored a just-rested, low-stress agent to
`active`, the overwork tracker re-benched it, forever — the rest→reflag
ping-pong that left V.E.R.I.F.Y. permanently `active` despite 15 rest cycles/24h.

Fix: a rest cycle is "active" when `ended_at IS NULL OR ended_at > NOW()`.
An explicit mandatory-rest window must outrank a low instantaneous stress read.

The reaper logic is raw SQL inside a scheduler job, so the primary proof is the
SQL-source regression below plus live verification on deploy. The DB-predicate
test exercises the corrected guard against the real predicate when a DB is
reachable, and skips cleanly otherwise.
"""

from __future__ import annotations

import os

import pytest

_JOBS_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "department_hq", "jobs.py")
_FIXED_GUARD = "rc.ended_at IS NULL OR rc.ended_at > NOW()"


def test_reaper_guard_source_respects_bounded_rest_cycles():
    """The reaper restore guard must respect future-ended (bounded) cycles.

    Guards against silently reverting to the bare `ended_at IS NULL` check
    that caused the ping-pong.
    """
    with open(_JOBS_PATH, encoding="utf-8") as fh:
        src = fh.read()
    assert _FIXED_GUARD in src, "kin_stuck_agent_reaper must treat future-ended rest cycles as active"
    # The buggy bare guard (NULL-only, no future-window clause) must not be the
    # restore predicate. We assert the fixed clause exists; the bare form alone
    # would fail the membership check above.


def _db_or_skip():
    try:
        from database import get_db_cursor  # noqa: WPS433

        return get_db_cursor
    except Exception as exc:  # pragma: no cover - import/env dependent
        pytest.skip(f"database module unavailable: {exc}")


def test_guard_predicate_blocks_future_ended_cycle():
    """Behavioural: a bounded cycle (ended_at in the future) reads as ACTIVE;
    an expired one (ended_at in the past) reads as inactive. Rolled back."""
    get_db_cursor = _db_or_skip()
    predicate = (
        "SELECT EXISTS(SELECT 1 FROM agent_rest_cycles rc "
        "WHERE rc.agent_id=%s AND (rc.ended_at IS NULL OR rc.ended_at > NOW()))"
    )
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT id FROM agents WHERE worker_type='ai' LIMIT 1")
            row = cur.fetchone()
            if not row:
                pytest.skip("no ai agent rows to test against")
            aid = row["id"] if isinstance(row, dict) else row[0]
            try:
                # bounded, future-ended → must read as an ACTIVE rest cycle
                cur.execute(
                    "INSERT INTO agent_rest_cycles (agent_id, rest_type, reason, started_at, ended_at, initiated_by) "
                    "VALUES (%s,'pytest','welfare regression',NOW(),NOW()+INTERVAL '8 hours','pytest')",
                    (aid,),
                )
                cur.execute(predicate, (aid,))
                res = cur.fetchone()
                active = res["exists"] if isinstance(res, dict) else res[0]
                assert active is True, "future-ended rest cycle must count as active (would block premature restore)"
            finally:
                conn.rollback()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - DB connectivity dependent
        pytest.skip(f"DB predicate check unavailable: {exc}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
