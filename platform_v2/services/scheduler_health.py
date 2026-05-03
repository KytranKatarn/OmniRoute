"""Scheduler health helpers for HTTP routes.

Path C (decision_id 557): the scheduler now runs in a separate Docker
container in production, so routes can no longer read the in-process
``app.config["AGENT_LOOP"]`` / ``["CONSCIOUSNESS_SCHEDULER"]`` objects
to determine whether scheduling is alive. They call ``read_status()``
instead, which queries the ``scheduler_heartbeat`` table written by
the heartbeat job (every 30s).

A heartbeat older than 90s is treated as stale (scheduler unreachable
or wedged). 90s gives two missed heartbeats before alerting.
"""

from __future__ import annotations

from typing import Any, Dict


_STALE_AFTER_SECONDS = 90


def read_status() -> Dict[str, Any]:
    """Return scheduler health from the latest heartbeat row.

    Always returns a dict with the same keys, even on DB error or when
    the table is empty (e.g. just after a fresh deploy before the first
    heartbeat lands). Callers can render this directly into the DHQ
    health panel without nil-checking.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT hostname, ts, running, jobs_total, jobs_pending, next_run_ts,
                       details,
                       EXTRACT(EPOCH FROM (now() - ts))::int AS age_s
                  FROM scheduler_heartbeat
                 ORDER BY ts DESC
                 LIMIT 1
                """
            )
            row = cur.fetchone()
    except Exception as e:
        return _empty(detail=f"DB error: {e}")

    if row is None:
        return _empty(detail="No heartbeat yet")

    age_s = row.get("age_s") or 0
    stale = age_s > _STALE_AFTER_SECONDS
    running = bool(row.get("running")) and not stale
    details = row.get("details") or {}
    jobs = details.get("jobs", []) if isinstance(details, dict) else []

    return {
        "scheduler_running": running,
        # The heartbeat is written BY agent_loop, so its freshness is
        # equivalent to agent_loop liveness.
        "agent_loop_running": running,
        "jobs_total": row.get("jobs_total") or 0,
        "jobs": jobs,  # list of {id, name, next_run, trigger}
        "next_run_ts": row.get("next_run_ts"),
        "stale": stale,
        "detail": "Stale" if stale else "Running",
        "hostname": row.get("hostname"),
        "age_s": age_s,
    }


def _empty(detail: str) -> Dict[str, Any]:
    return {
        "scheduler_running": False,
        "agent_loop_running": False,
        "jobs_total": 0,
        "jobs": [],
        "next_run_ts": None,
        "stale": True,
        "detail": detail,
        "hostname": None,
        "age_s": None,
    }


def get_jobs() -> list:
    """Convenience accessor for the job list from the latest heartbeat."""
    return read_status().get("jobs", [])


def is_running() -> bool:
    """Convenience accessor for the running flag from the latest heartbeat."""
    return read_status().get("scheduler_running", False)
