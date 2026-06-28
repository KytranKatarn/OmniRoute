"""Unified dispatch-health metric — the single source of truth.

Before this, every panel computed "dispatch success" from a different table
with a different definition, so they disagreed wildly for the SAME window:

    DHQ DISPATCH METRICS (24h)  → task_execution_log only      → ~100% (lie)
    DHQ Overview "Jobs 24h"     → bridge_jobs only, ok/total   → ~53%  (pessimistic)
    Consciousness 1h dispatch   → task_execution_log only      → ~100% (lie)

task_execution_log holds almost exclusively *successful synchronous*
executions; the real fleet/cold-queue failures live in bridge_jobs. Counting
either table alone is misleading.

`dispatch_health(hours)` unions BOTH sinks with one consistent definition:

    outcome:
        ok      = task succeeded            OR bridge_job status='completed'
        failed  = task success IS FALSE      OR bridge_job in
                  (failed, error, expired, cancelled, timeout)
        pending = task success IS NULL       OR any other (running/queued/...)

Non-terminal jobs are NOT counted as failures, and `success_rate` is computed
over DECIDED work only (ok + failed) so in-flight work never skews it.

Returns a dict::

    {
      "total": int,             # all dispatch attempts in the window
      "success": int,           # ok
      "failed": int,            # terminal failures (real + infra timeout)
      "failed_real": int,       # genuine dispatch failures (excludes infra timeouts) (#4538)
      "failed_timeout": int,    # infra queue/timeouts among failures (GPU contention etc.) (#4538)
      "pending": int,           # in-flight / non-terminal
      "decided": int,           # ok + failed
      "success_rate": float,    # round(ok / decided * 100, 1), 0 when no decided
      "success_rate_real": float, # round(ok / (ok + failed_real) * 100, 1) — infra timeouts excluded (#4538)
      "avg_duration_ms": float  # avg over rows that recorded a duration
    }
"""

from __future__ import annotations

from typing import Dict

from database import get_db_cursor

# Terminal failure statuses on bridge_jobs. Anything not here and not
# 'completed' is treated as in-flight (pending), NOT a failure.
_JOB_FAILED_STATUSES = ("failed", "error", "expired", "cancelled", "timeout")

# A bridge_jobs failure is an INFRA queue/timeout (not a genuine dispatch failure)
# when its status is a non-error terminal (timeout/expired/cancelled) OR its
# error_message carries a timeout/reaped signature. Splitting the FAILED bucket on
# this keeps a GPU-contention backlog event (e.g. 240s fact_check timeouts) from
# reading as a dispatch regression (#4538). task_execution_log failures are always
# "real". Matched case-insensitively as a POSIX regex on error_message.
_TIMEOUT_NONERROR_STATUSES = ("timeout", "expired", "cancelled")
_TIMEOUT_SIGNATURE_RE = r"timeout|timed out|did not respond|reaped|stale|auto-killed"


def dispatch_health(hours: float = 24.0) -> Dict[str, object]:
    """Unified dispatch health over the last ``hours`` across both sinks."""
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        hours = 24.0
    if hours <= 0:
        hours = 24.0
    window = f"{hours} hours"

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            WITH unified AS (
                SELECT CASE WHEN success IS TRUE THEN 'ok'
                            WHEN success IS FALSE THEN 'failed'
                            ELSE 'pending' END AS outcome,
                       FALSE AS is_timeout,
                       duration_ms, tokens_used
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL %(win)s
                UNION ALL
                SELECT CASE WHEN status = 'completed' THEN 'ok'
                            WHEN status = ANY(%(failed)s) THEN 'failed'
                            ELSE 'pending' END AS outcome,
                       (status = ANY(%(tostat)s)
                        OR lower(COALESCE(error_message, '')) ~ %(tosig)s) AS is_timeout,
                       NULL::int AS duration_ms, NULL::int AS tokens_used
                FROM bridge_jobs
                WHERE created_at > NOW() - INTERVAL %(win)s
            )
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE outcome = 'ok') AS success,
                COUNT(*) FILTER (WHERE outcome = 'failed') AS failed,
                COUNT(*) FILTER (WHERE outcome = 'failed' AND is_timeout) AS failed_timeout,
                COUNT(*) FILTER (WHERE outcome = 'pending') AS pending,
                COALESCE(SUM(tokens_used), 0) AS tokens,
                COALESCE(
                    ROUND(AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL)::numeric, 1),
                    0
                ) AS avg_duration_ms
            FROM unified
            """,
            {
                "win": window,
                "failed": list(_JOB_FAILED_STATUSES),
                "tostat": list(_TIMEOUT_NONERROR_STATUSES),
                "tosig": _TIMEOUT_SIGNATURE_RE,
            },
        )
        row = cur.fetchone() or {}

    success = int(row.get("success") or 0)
    failed = int(row.get("failed") or 0)
    failed_timeout = int(row.get("failed_timeout") or 0)
    failed_real = max(failed - failed_timeout, 0)
    pending = int(row.get("pending") or 0)
    decided = success + failed
    decided_real = success + failed_real
    return {
        "total": int(row.get("total") or 0),
        "success": success,
        "failed": failed,
        "failed_real": failed_real,
        "failed_timeout": failed_timeout,
        "pending": pending,
        "decided": decided,
        "success_rate": round(success / decided * 100, 1) if decided else 0.0,
        "success_rate_real": round(success / decided_real * 100, 1) if decided_real else 0.0,
        "avg_duration_ms": float(row.get("avg_duration_ms") or 0),
        # Reported model tokens (prompt+completion) over the window. LOWER BOUND:
        # only task_execution_log rows carry tokens; bridge_jobs and ~2,250
        # agent_loop LLM rows log 0. Honest label downstream: "reported tokens".
        "tokens": int(row.get("tokens") or 0),
    }
