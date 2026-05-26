"""Cluster Orchestration Service — score engine, config hierarchy, state cache, work queue.

Imported by:
  cluster_orchestration_worker (jobs.py) — writes agent_overflow_state each cycle
  department_coordinator.select_agent() — reads overflow cache for +0.4 score bonus
  Any module that wants to enqueue overflow work: enqueue_work()
  Any idle-agent job that wants to claim work: claim_work()
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import psycopg2.extras

logger = logging.getLogger(__name__)

_overflow_cache: dict = {}
_cache_lock = threading.Lock()
_cache_built_at: float = 0.0
_CACHE_TTL_SECONDS = 90


def compute_overflow_score(
    idle_minutes: float,
    util_pct: float,
    queue_depth: int,
    config: dict,
) -> float:
    """Return 0.0-1.0 overflow score from three normalised signals."""
    # Cast to float — NUMERIC columns return decimal.Decimal from psycopg2
    idle_thresh = max(1, float(config["idle_threshold_minutes"]))
    util_thresh = max(1.0, float(config["utilization_threshold_pct"]))
    queue_thresh = max(1, float(config["queue_pressure_threshold"]))

    idle_score = min(1.0, idle_minutes / idle_thresh)
    util_score = max(0.0, 1.0 - util_pct / util_thresh)
    queue_score = min(1.0, queue_depth / queue_thresh)

    return (
        float(config["idle_weight"]) * idle_score
        + float(config["utilization_weight"]) * util_score
        + float(config["queue_pressure_weight"]) * queue_score
    )


CONFIG_KEYS = frozenset(
    {
        "idle_threshold_minutes",
        "utilization_threshold_pct",
        "queue_pressure_threshold",
        "idle_weight",
        "utilization_weight",
        "queue_pressure_weight",
        "overflow_enabled",
        "overflow_paused",
        "priority_boost",
        "max_overflow_concurrent",
    }
)


def resolve_config(
    all_configs: list,
    agent_id: Optional[int],
    capability: Optional[str],
    node_id: Optional[int],
) -> dict:
    """Merge config rows by scope priority: node > agent > capability > global.
    Only config payload keys are copied — scope discriminators are excluded.
    """
    PRIORITY = {"global": 0, "capability": 1, "agent": 2, "node": 3}
    result: dict = {}
    for row in sorted(all_configs, key=lambda r: PRIORITY.get(r["scope"], 0)):
        scope = row["scope"]
        matches = (
            scope == "global"
            or (scope == "capability" and row.get("capability") == capability)
            or (scope == "agent" and row.get("agent_id") == agent_id)
            or (scope == "node" and row.get("node_id") == node_id)
        )
        if matches:
            result.update({k: v for k, v in row.items() if k in CONFIG_KEYS})
    return result


def update_overflow_cache(states: list) -> None:
    """Replace the module-level cache atomically. Called by the worker each cycle."""
    global _overflow_cache, _cache_built_at
    new_cache: dict = {}
    for s in states:
        try:
            key = (s["agent_id"], s["capability"])
            new_cache[key] = {
                "is_active": s["is_active"],
                "score": s["overflow_score"],
            }
        except KeyError as exc:
            logger.warning("Skipping malformed overflow state row (missing key %s): %s", exc, s)
    with _cache_lock:
        _overflow_cache = new_cache
        _cache_built_at = time.monotonic()


def get_overflow_bonus(agent_id: int, capability: str) -> float:
    """Return +0.4 if agent is in active overflow for this capability, else 0.
    Zero DB queries — reads only the in-memory cache.
    """
    with _cache_lock:
        stale = (time.monotonic() - _cache_built_at) > _CACHE_TTL_SECONDS
        if stale:
            return 0.0
        entry = _overflow_cache.get((agent_id, capability), {})
    return 0.4 if entry.get("is_active") else 0.0


def get_full_cache_snapshot() -> list:
    """All current overflow state entries — used by the status API endpoint."""
    with _cache_lock:
        return [{"agent_id": aid, "capability": cap, **data} for (aid, cap), data in _overflow_cache.items()]


# ── cluster_work_queue DB helpers ────────────────────────────────────────────
# These functions are the only way to interact with cluster_work_queue.
# The table is the unified pending table for all capability types (T3166).


def enqueue_work(
    capability: str,
    payload: dict,
    *,
    priority: int = 5,
    source: Optional[str] = None,
    max_attempts: int = 3,
    available_after: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> int:
    """Insert a work item into cluster_work_queue and return its id.

    Thread-safe; uses a short-lived DB connection so callers don't need to hold
    a cursor open.  Returns the new row id on success, raises on DB error.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            INSERT INTO cluster_work_queue
                (capability, payload, priority, source, max_attempts, available_after, expires_at)
            VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                capability,
                psycopg2.extras.Json(payload),
                max(1, min(10, priority)),
                source,
                max_attempts,
                available_after or datetime.now(tz=timezone.utc),
                expires_at,
            ),
        )
        row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def claim_work(
    capability: Optional[str] = None,
    *,
    agent_id: Optional[int] = None,
) -> Optional[dict]:
    """Atomically claim the highest-priority pending work item using SKIP LOCKED.

    Pass `capability` to restrict to a specific capability bucket (targeted drain).
    Omit `capability` to allow any idle agent to pick up any pending item.

    Returns the full row as a dict, or None if the queue is empty.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_, cur):
        if capability:
            cur.execute(
                """
                UPDATE cluster_work_queue
                SET status     = 'claimed',
                    claimed_by = %s,
                    claimed_at = NOW(),
                    attempts   = attempts + 1,
                    updated_at = NOW()
                WHERE id = (
                    SELECT id FROM cluster_work_queue
                    WHERE status = 'pending'
                      AND capability = %s
                      AND available_after <= NOW()
                    ORDER BY priority DESC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                (agent_id, capability),
            )
        else:
            cur.execute(
                """
                UPDATE cluster_work_queue
                SET status     = 'claimed',
                    claimed_by = %s,
                    claimed_at = NOW(),
                    attempts   = attempts + 1,
                    updated_at = NOW()
                WHERE id = (
                    SELECT id FROM cluster_work_queue
                    WHERE status = 'pending'
                      AND available_after <= NOW()
                    ORDER BY priority DESC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                (agent_id,),
            )
        row = cur.fetchone()
    return dict(row) if row else None


def complete_work(job_id: int, result: Any) -> None:
    """Mark a claimed work item as completed and store its result."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            UPDATE cluster_work_queue
            SET status     = 'completed',
                result     = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s AND status = 'claimed'
            """,
            (psycopg2.extras.Json(result if result is not None else {}), job_id),
        )


def fail_work(job_id: int, error: str, *, retry: bool = True, backoff_seconds: int = 60) -> None:
    """Mark a claimed work item failed.

    If retry=True and attempts < max_attempts, resets status to 'pending' with
    an exponential back-off via available_after.  Otherwise marks as 'failed'.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_, cur):
        if retry:
            cur.execute(
                """
                UPDATE cluster_work_queue
                SET status          = CASE WHEN attempts < max_attempts THEN 'pending' ELSE 'failed' END,
                    error_text      = %s,
                    available_after = CASE WHEN attempts < max_attempts
                                          THEN NOW() + (%s * attempts) * INTERVAL '1 second'
                                          ELSE available_after END,
                    updated_at      = NOW()
                WHERE id = %s AND status = 'claimed'
                """,
                (error, backoff_seconds, job_id),
            )
        else:
            cur.execute(
                """
                UPDATE cluster_work_queue
                SET status     = 'failed',
                    error_text = %s,
                    updated_at = NOW()
                WHERE id = %s AND status = 'claimed'
                """,
                (error, job_id),
            )


def get_queue_depth(capability: Optional[str] = None) -> dict:
    """Return pending/claimed/completed/failed counts for the given capability (or all).

    Used by the cluster orchestration worker for queue_pressure calculation.
    """
    from database import get_db_cursor

    with get_db_cursor() as (_, cur):
        if capability:
            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM cluster_work_queue
                WHERE capability = %s
                GROUP BY status
                """,
                (capability,),
            )
        else:
            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM cluster_work_queue
                GROUP BY status
                """
            )
        rows = cur.fetchall() or []
    return {
        (r["status"] if isinstance(r, dict) else r[0]): int(r["cnt"] if isinstance(r, dict) else r[1]) for r in rows
    }


def expire_old_work(max_age_days: int = 7) -> int:
    """Reap completed/failed rows older than max_age_days. Returns count deleted."""
    from database import get_db_cursor

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """
            DELETE FROM cluster_work_queue
            WHERE status IN ('completed', 'failed')
              AND updated_at < %s
            """,
            (cutoff,),
        )
        return cur.rowcount
