"""Alert-only liveness watchdog for the model-affinity dispatch drain (#5699).

Born from 2026-08-13/15: the entire agent-loop scheduler was down for ~50 hours and,
the rest of the week, the drain worker's cycles stretched from 15s to 5-12+ minutes
(claimed-into-a-full-pool + 300s completion barriers + max_instances=1 skips). 1,589
rows of REAL work were shot by the 2h reaper as 'expired: no drain worker' — and
nothing paged, because no surface tracked worker cycle cadence: dispatch_health reads
task_execution_log/bridge_jobs (never dispatch_pending_queue), and the DHQ queue panel
shows depth, not drain progress.

Two deterministic checks, no LLM in the alert path (mirrors backup_posture_monitor):

  1. HEARTBEAT — the worker now writes one autonomy_loop_log row per cycle
     (job_name='model_dispatch_worker', every 15s). If the newest heartbeat is older
     than the threshold while the scheduler is alive enough to run THIS monitor, the
     drain worker specifically is stuck/absent.
  2. STALL — queued NON-WARMUP rows older than the stall threshold exist while no
     claim has advanced within the same window. Warmup rows (kin_warmth pings) are
     EXCLUDED: they are minutes-TTL infrastructure noise and were exactly what
     drowned the real signal (1,791 warmup 'expired' rows vs the invisible real ones).

Thresholds are tunable at runtime via platform_settings (no deploy):
  dispatch:liveness:heartbeat_stall_min   (default 5)
  dispatch:liveness:queue_stall_min       (default 30)

Fail-open: this monitor never raises and never mutates dispatch state — a broken
watchdog must never block or damage the drain path it watches.

Known limitation (deliberate, documented): this job runs INSIDE archie_scheduler, so
a whole-scheduler outage (the 50h class) also silences it. Catching that class needs
a watchdog outside the scheduler (host cron / archie_platform) — tracked separately.
The heartbeat rows this PR adds make that outage class visible in DATA either way.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Worker fires every 15s; even a busy cycle should land a heartbeat well inside 5
# minutes. The recon's chronic-stretch cycles ran 5-12+ minutes, so 5 min catches
# both a dead worker and pathological cycle stretching without paging on one slow
# cycle alone (send_system cooldown bounds repeats).
HEARTBEAT_STALL_MIN_DEFAULT = 5.0

# Real work should be claimed long before the 2h reaper deadline. 30 min of queued
# non-warmup work with zero claim progress means the drain has effectively stopped.
QUEUE_STALL_MIN_DEFAULT = 30.0


def heartbeat_is_stale(age_min, limit_min: float) -> bool:
    """PURE decision: is the newest worker heartbeat too old?

    ``age_min is None`` means no heartbeat row exists at all — reported 'unknown'
    upstream, NOT stale: a fresh deploy (heartbeats ship with this module) must not
    page, mirroring the backup monitor's no-rows-is-unknown rule.
    """
    if age_min is None:
        return False
    return float(age_min) > float(limit_min)


def queue_is_stalled(stalled_rows: int, newest_claim_age_min, limit_min: float) -> bool:
    """PURE decision: queued real work is aging AND no claim is advancing.

    ``newest_claim_age_min is None`` (no claim ever recorded) counts as no progress —
    with stalled rows present that is the worst case, not an excuse.
    """
    if int(stalled_rows or 0) <= 0:
        return False
    if newest_claim_age_min is None:
        return True
    return float(newest_claim_age_min) > float(limit_min)


def _threshold(cur, key: str, default: float) -> float:
    """Read one platform_settings threshold (minutes). Never raises."""
    try:
        cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        if row:
            val = row["value"] if isinstance(row, dict) else row[0]
            return max(1.0, float(val))
    except Exception as exc:
        logger.warning("drain_liveness: threshold %s unreadable (using %.0f): %s", key, default, exc)
    return default


def check_drain_liveness():
    """Run both liveness checks and alert via send_system. Returns a dict; never raises."""
    result = {
        "checked": True,
        "alerted": [],
        "heartbeat_age_min": None,
        "stalled_rows": 0,
        "newest_claim_age_min": None,
    }
    try:
        # Lazy imports: the pure decision helpers above must stay importable
        # without a DB driver (they are unit-tested outside the container).
        from database import get_db_cursor
        from services.telegram_service import send_system
    except Exception as exc:  # comms/DB unavailable — never take the loop down with us
        logger.warning("drain_liveness: dependencies unavailable: %s", exc)
        return {"checked": False, "error": str(exc), "alerted": []}

    try:
        with get_db_cursor(commit=False) as (_conn, cur):
            hb_limit = _threshold(cur, "dispatch:liveness:heartbeat_stall_min", HEARTBEAT_STALL_MIN_DEFAULT)
            stall_limit = _threshold(cur, "dispatch:liveness:queue_stall_min", QUEUE_STALL_MIN_DEFAULT)

            # ---- 1. HEARTBEAT ----------------------------------------------------
            # created_at is timestamp WITHOUT time zone (DB clock = UTC) — compute
            # the age IN SQL; subtracting it from an aware datetime in Python raises.
            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW()::timestamp - MAX(created_at))) / 60.0 AS age_min
                FROM autonomy_loop_log
                WHERE job_name = 'model_dispatch_worker'
                  AND created_at > NOW()::timestamp - INTERVAL '7 days'
                """
            )
            row = cur.fetchone()
            hb_age = (row["age_min"] if isinstance(row, dict) else row[0]) if row else None
            result["heartbeat_age_min"] = round(float(hb_age), 1) if hb_age is not None else None

            if heartbeat_is_stale(hb_age, hb_limit):
                send_system(
                    "Dispatch drain: worker heartbeat stale",
                    "model_dispatch_worker's newest per-cycle heartbeat is %.0f min old "
                    "(limit %.0f min; normal cadence 15s). The scheduler is alive (this "
                    "monitor ran) but the drain worker is stuck or absent — queued "
                    "dispatch work is NOT draining and will hit the 2h reaper. Check "
                    "`docker logs archie_scheduler` for 'maximum number of running "
                    "instances reached' skips (a cycle wedged in the thread pool) or a "
                    "crashed job. Task #5699 has the anatomy." % (float(hb_age), hb_limit),
                    cooldown_hours=2.0,
                )
                result["alerted"].append("drain_heartbeat_stale")

            # ---- 2. QUEUE STALL (warmup EXCLUDED) --------------------------------
            # COALESCE: NULL capability is real work; NULL <> 'warmup' is NULL and
            # would silently drop those rows from the count.
            cur.execute(
                """
                SELECT COUNT(*) AS stalled
                FROM dispatch_pending_queue
                WHERE status = 'queued'
                  AND COALESCE(capability, '') <> 'warmup'
                  AND queued_at < NOW() - (%s * INTERVAL '1 minute')
                """,
                (stall_limit,),
            )
            row = cur.fetchone()
            stalled = int((row["stalled"] if isinstance(row, dict) else row[0]) or 0) if row else 0
            result["stalled_rows"] = stalled

            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(claimed_at))) / 60.0 AS age_min
                FROM dispatch_pending_queue
                WHERE claimed_at IS NOT NULL
                """
            )
            row = cur.fetchone()
            claim_age = (row["age_min"] if isinstance(row, dict) else row[0]) if row else None
            result["newest_claim_age_min"] = round(float(claim_age), 1) if claim_age is not None else None

            if queue_is_stalled(stalled, claim_age, stall_limit):
                send_system(
                    "Dispatch drain: queue stalled with no claim progress",
                    "%d queued non-warmup dispatch row(s) are older than %.0f min and the "
                    "newest claim is %s — the drain has effectively stopped while real "
                    "work waits. Left alone these rows are shot by the 2h reaper as "
                    "'expired: no drain worker' (classify/translate were the dominant "
                    "losses, task #5699). Check model_dispatch_worker heartbeats in "
                    "autonomy_loop_log and archie_scheduler logs."
                    % (
                        stalled,
                        stall_limit,
                        ("absent (nothing ever claimed)" if claim_age is None else "%.0f min old" % float(claim_age)),
                    ),
                    cooldown_hours=2.0,
                )
                result["alerted"].append("drain_queue_stalled")

    except Exception as exc:
        # A watchdog that crashes is a watchdog that stops watching. Log loudly,
        # return honestly, never propagate into the scheduler.
        logger.error("drain_liveness: check FAILED (drain is now unmonitored): %s", exc)
        result["checked"] = False
        result["error"] = str(exc)

    return result
