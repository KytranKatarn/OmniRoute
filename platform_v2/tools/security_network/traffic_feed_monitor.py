"""Deterministic freshness watchdog for the network_traffic_stats feed (#5704).

Born from 2026-07-30 -> 2026-08-17: the host rebooted, the network-tools stack came back
serving ntopng auth from a stale redis dataset, and every 5-minute collector cycle since
failed login and skipped — writing status='success' with items_processed=0 to
autonomy_loop_log. The Traffic panels quietly froze at the 2026-07-30 21:00 UTC hour
bucket for 17 days and NOTHING alarmed, because the skip path masqueraded as success and
no one watched the table itself.

So this check is DETERMINISTIC and LLM-free (same shape as
services/backup_posture_monitor.py):

  * Durable signal: MAX(hour_bucket) FROM network_traffic_stats — the table the panels
    read; it survives log pruning (autonomy_loop_log is retention-pruned at ~14 days,
    which is why no in-DB record of the July break remained).
  * Corroborating signal: the last PRODUCTIVE collector run (items_processed > 0) and
    the newest recorded error_message — quoted in the alert so it names the actual
    cause (e.g. "credentials rejected") instead of generic advice.
  * 'No rows ever' = 'unknown', NOT an alert — a fresh install must not page.
  * Threshold tunable at runtime via platform_settings key
    'security:traffic:stale_hours' (default 3h — the collector is 5-minute, so 3h
    absorbs quiet periods and restarts without flapping).
  * The feed name is in the alert TITLE because send_system dedups on (title, source).

Never mutates anything.
"""

from __future__ import annotations

import logging
import os

from database import get_db_cursor

logger = logging.getLogger(__name__)

FEED_NAME = "network_traffic_stats"

# The collector ('agent_traffic_stats' / collect_traffic_stats, archie_scheduler) runs
# every 5 minutes and upserts one row per device per hour bucket, so a healthy feed's
# newest bucket is never more than ~1h old. 3h is deliberately generous: it absorbs
# platform restarts, quiet network periods, and the hour-bucket granularity itself.
STALE_HOURS_DEFAULT = 3.0

# Runtime override — no deploy needed to retune.
SETTING_KEY = "security:traffic:stale_hours"


def evaluate_freshness(age_h, total_rows: int, limit_h: float) -> str:
    """PURE decision: 'unknown' | 'stale' | 'ok'.

    Pure so it can be tested without a database — the test DB has no
    network_traffic_stats rows, so an end-to-end 'no alert fired' assertion would pass
    without exercising anything (the backup_posture_monitor lesson).
    """
    if total_rows == 0:
        # No rows EVER = the feed was never configured here. Not an alert — a fresh
        # deploy must not page — but reported as 'unknown' rather than omitted.
        return "unknown"
    if age_h is None or float(age_h) > float(limit_h):
        return "stale"
    return "ok"


def alert_title() -> str:
    """The feed name is in the title: send_system dedups on (title, source)."""
    return "Traffic feed '%s' is stale — collector not writing" % FEED_NAME


def _stale_hours_override(cur) -> float:
    """Read platform_settings 'security:traffic:stale_hours' -> hours.

    Never raises; falls back to the code default so unreadable settings cannot
    blind the watchdog.
    """
    try:
        cur.execute("SELECT value FROM platform_settings WHERE key = %s", (SETTING_KEY,))
        row = cur.fetchone()
        if row:
            val = row["value"] if isinstance(row, dict) else row[0]
            return float(val)
    except Exception as exc:
        logger.warning("traffic_feed_monitor: threshold override unreadable (using default): %s", exc)
    return STALE_HOURS_DEFAULT


def check_traffic_feed_freshness(stale_hours: float | None = None) -> dict:
    """Check network_traffic_stats freshness and alert when the feed is stale.

    Returns a dict; never raises. ``stale_hours`` overrides the limit (tests pass it
    directly; production reads platform_settings on top of the code default).
    """
    result = {
        "checked": True,
        "status": "unknown",
        "age_h": None,
        "total_rows": 0,
        "limit_h": None,
        "last_productive_run": None,
        "last_error": None,
        "alerted": [],
    }
    try:
        from services.telegram_service import send_system
    except Exception as exc:  # comms unavailable — never take the scheduler down with us
        logger.warning("traffic_feed_monitor: telegram unavailable: %s", exc)
        return {"checked": False, "error": str(exc), "alerted": []}

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            limit_h = float(stale_hours) if stale_hours is not None else _stale_hours_override(cur)
            result["limit_h"] = limit_h

            # ---- Durable signal: the table the panels read ---------------------------
            # hour_bucket is timestamp WITHOUT time zone written from NOW() in a
            # timezone=UTC database, so NOW() - MAX(hour_bucket) is a correct age here.
            cur.execute(
                """
                SELECT COUNT(*) AS total_rows,
                       EXTRACT(EPOCH FROM (NOW() - MAX(hour_bucket))) / 3600.0 AS age_h
                FROM network_traffic_stats
                """
            )
            row = cur.fetchone()
            total = int((row["total_rows"] if isinstance(row, dict) else row[0]) or 0) if row else 0
            age_h = (row["age_h"] if isinstance(row, dict) else row[1]) if row else None
            result["total_rows"] = total
            result["age_h"] = None if age_h is None else round(float(age_h), 1)

            # ---- Corroborating signal: the writer's own run log ----------------------
            # ONLY via last row with items_processed > 0 — NEVER gated on status,
            # because the pre-#5704 skip path wrote status='success' with 0 items.
            # This log is retention-pruned (~14d) so it can never be the sole signal.
            try:
                cur.execute(
                    """
                    SELECT MAX(created_at) AS last_ok
                    FROM autonomy_loop_log
                    WHERE job_name = 'collect_traffic_stats' AND items_processed > 0
                    """
                )
                r2 = cur.fetchone()
                last_ok = (r2["last_ok"] if isinstance(r2, dict) else r2[0]) if r2 else None
                result["last_productive_run"] = str(last_ok) if last_ok else None

                cur.execute(
                    """
                    SELECT error_message
                    FROM autonomy_loop_log
                    WHERE job_name = 'collect_traffic_stats' AND error_message IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                r3 = cur.fetchone()
                err = (r3["error_message"] if isinstance(r3, dict) else r3[0]) if r3 else None
                if err:
                    result["last_error"] = " ".join(str(err).split())[:300]
            except Exception as exc:
                # Corroboration is best-effort — the durable signal must still decide.
                logger.warning("traffic_feed_monitor: autonomy_loop_log corroboration failed: %s", exc)

            status = evaluate_freshness(age_h, total, limit_h)
            result["status"] = status

            if status == "stale":
                cause = (
                    "NEWEST RECORDED COLLECTOR ERROR: %s -- fix THIS first. " % result["last_error"]
                    if result["last_error"]
                    else (
                        "No collector error recorded in autonomy_loop_log (it is pruned at "
                        "~14 days, so an old break leaves no trace there) — check "
                        "`docker logs archie_scheduler` for collect_traffic_stats lines. "
                    )
                )
                send_system(
                    alert_title(),
                    "Newest network_traffic_stats hour_bucket is %s (limit %.0fh). %s"
                    "Writer: job 'agent_traffic_stats' (collect_traffic_stats, "
                    "archie_scheduler, 5-min) sourcing ntopng at %s:%s. Last productive "
                    "run: %s. If the error says 'credentials rejected', the fix is the "
                    "ntopng admin password (redis ntopng.user.admin.password vs .env "
                    "NTOPNG_ADMIN_PASSWORD), not a restart."
                    % (
                        ("MISSING (rows exist, MAX is NULL)" if age_h is None else "%.1fh old" % float(age_h)),
                        limit_h,
                        cause,
                        os.getenv("NTOPNG_HOST", "192.168.1.200"),
                        os.getenv("NTOPNG_PORT", "3001"),
                        result["last_productive_run"] or "none in retained log window",
                    ),
                    cooldown_hours=6.0,
                )
                result["alerted"].append("traffic_feed_stale")

    except Exception as exc:
        # A watchdog that crashes is a watchdog that stops watching.
        logger.error("traffic_feed_monitor: check FAILED (traffic feed is now unmonitored): %s", exc)
        result["checked"] = False
        result["error"] = str(exc)

    return result
