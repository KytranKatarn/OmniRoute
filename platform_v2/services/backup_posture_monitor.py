"""Alert-only watchdog for the PRIMARY backup tier.

Born from 2026-07-20: full backups had been OOM-killed for an unknown length of time, the
last successful primary backup silently aged past 12 hours, and NOTHING told anyone. It
surfaced only because someone happened to query `backup_log` while chasing an unrelated bug.

There WAS a job meant to catch this — W.A.R.D.E.N.'s "Daily Backup Integrity Check" — and it
had two independent defects:

  1. it queried ``FROM backups``, a table that does not exist (the table is ``backup_log``),
     so every run threw and its ``except`` swallowed the error; and
  2. even on success it had no alert path at all — it asked an LLM to "flag anything that
     needs attention" and wrote the answer into a log row nobody reads.

So the checks here are DETERMINISTIC and do not depend on a model being warm, reachable, or
correct. An alert that only fires when an LLM cooperates is not an alert. This mirrors
``dr_posture_monitor`` (same shape, same send_system cooldowns) but watches tier='primary'
— DR freshness was already monitored; the tier we actually restore from was not.

Never mutates anything.
"""

from __future__ import annotations

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

# The primary backup is nightly, so anything past ~a day means a run was missed or failed.
# Deliberately NOT the 6h deploy-gate threshold — that governs whether it is safe to deploy,
# which is a stricter question than whether backups are healthy.
PRIMARY_STALE_HOURS = 26.0

# Window for "attempts are failing". A failed nightly matters even when a later manual
# backup succeeded — the automation is still broken and will be relied on unattended.
FAILURE_LOOKBACK_HOURS = 24.0

# backup_log.status values seen in the wild: success / failed / partial / skipped / prune.
# 'partial' counts as a failure: a half-written backup is not a restore point, and it is the
# most dangerous value because it looks plausible.
_FAILURE_STATUSES = ("failed", "partial")


def check_backup_posture(stale_hours: float = PRIMARY_STALE_HOURS):
    """Check primary-tier backup health and alert. Returns a dict; never raises."""
    result = {"checked": True, "alerted": [], "success_age_h": None, "recent_failures": 0}
    try:
        from services.telegram_service import send_system
    except Exception as exc:  # comms unavailable — never take the loop down with us
        logger.warning("backup_posture: telegram unavailable: %s", exc)
        return {"checked": False, "error": str(exc), "alerted": []}

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # ---- 1. FRESHNESS of the last SUCCESSFUL primary backup ------------------
            # status='success' is load-bearing: a FAILED backup also writes a tier='primary'
            # row, and measuring the newest row regardless of status is exactly the bug
            # fixed in #5013 — it certifies a restore point that does not exist.
            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) / 3600.0 AS age_h
                FROM backup_log
                WHERE tier = 'primary' AND status = 'success'
                """
            )
            row = cur.fetchone()
            age_h = (row["age_h"] if isinstance(row, dict) else row[0]) if row else None
            result["success_age_h"] = round(float(age_h), 1) if age_h is not None else None

            if age_h is None or float(age_h) > stale_hours:
                send_system(
                    "Backup posture: no recent successful backup",
                    "Newest tier='primary' backup_log success is %s (limit %.0fh). "
                    "The restore point is stale — check Backup Manager and the nightly "
                    "backup_triage.sh. A failed run still writes a 'primary' row, so the "
                    "dashboard can look current while no usable backup exists."
                    % ("MISSING ENTIRELY" if age_h is None else "%.0fh old" % float(age_h), stale_hours),
                    cooldown_hours=12.0,
                )
                result["alerted"].append("primary_backup_stale")

            # ---- 2. ARE ATTEMPTS FAILING? -------------------------------------------
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM backup_log
                WHERE tier = 'primary'
                  AND status = ANY(%s)
                  AND created_at > NOW() - (%s * INTERVAL '1 hour')
                """,
                (list(_FAILURE_STATUSES), FAILURE_LOOKBACK_HOURS),
            )
            row = cur.fetchone()
            n = int((row["n"] if isinstance(row, dict) else row[0]) or 0) if row else 0
            result["recent_failures"] = n

            if n:
                send_system(
                    "Backup posture: backup attempts are failing",
                    "%d primary backup attempt(s) failed or completed partially in the last "
                    "%.0fh. Even if a later run succeeded, the unattended path is broken. "
                    "Check container memory — a full dump that OOMs dies part-written "
                    "(see task #5014)." % (n, FAILURE_LOOKBACK_HOURS),
                    cooldown_hours=6.0,
                )
                result["alerted"].append("primary_backup_failures")

    except Exception as exc:
        # A watchdog that crashes is a watchdog that stops watching — and this whole module
        # exists because the previous one failed silently. Log loudly, return honestly.
        logger.error("backup_posture: check FAILED (backups are now unmonitored): %s", exc)
        result["checked"] = False
        result["error"] = str(exc)

    return result
