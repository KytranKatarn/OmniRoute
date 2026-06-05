"""Fleet identity monitor — DR remediation FIX8.

Alert-only watchdog that surfaces the two signatures of the 2026-06-04
re-registration storm, which orphaned 7 of 9 fleet nodes and ran SILENT for ~13
hours because nothing watched for it:

  1. MASS OFFLINE  — more than ``MASS_OFFLINE_THRESHOLD`` approved nodes go stale
                     at once (the shape of a storm or a DR mishap).
  2. DUPLICATE ID  — a pending 'standard' row whose hostname matches an approved
                     node. This is impossible once the hub reclaim fix (FIX1) is
                     live; an alert here means FIX1 has REGRESSED.

Runs every 5 min from the agent loop. NEVER mutates the fleet — it only alerts
via the unified Operations inbox (B.A.S.E.). Toggle: work_control key
``fleet_identity_monitor`` (default on).

Postmortem: .claude/dr-postmortem-and-remediation.md · KB mistake #270611.
"""

import logging

logger = logging.getLogger(__name__)

# The two volatile Windows LAN Starships rest overnight (hardware rest 8PM-6AM ET)
# and flap; excluding them from the mass-offline COUNT avoids nightly false pages.
# The duplicate-identity detector still covers them (and every node).
REST_EXCLUDED = {
    "starship_5501c2766526e746",  # USS-245 (Runabout)
    "starship_76583490e36955ab",  # USS-246 (Defiant)
}
STALE_SECONDS = 180  # an approved node silent > 3 min is "offline"
MASS_OFFLINE_THRESHOLD = 1  # MORE than this many at once -> alert (storm-shaped)


def check_fleet_identity():
    """One pass of the fleet-identity watchdog. Safe to call on a schedule."""
    try:
        from services.work_control_service import is_enabled

        if not is_enabled("fleet_identity_monitor", True):
            return {"skipped": "disabled"}
    except Exception:
        pass  # toggle store optional — default to running

    try:
        from database import get_db_cursor
        from services.telegram_service import send_system
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("fleet_identity_monitor: dependencies unavailable: %s", e)
        return {"error": str(e)}

    result = {"mass_offline": 0, "duplicates": 0, "alerted": []}

    try:
        with get_db_cursor() as (conn, cur):
            # ---- 1. MASS OFFLINE ----------------------------------------
            cur.execute(
                """
                SELECT node_id, node_name, deployment_mode,
                       COALESCE(EXTRACT(EPOCH FROM NOW() - last_heartbeat)::int, 999999) AS age_s
                FROM remote_nodes
                WHERE approval_status = 'approved'
                  AND is_active = TRUE
                  AND deployment_mode <> 'satellite'
                  AND (last_heartbeat IS NULL
                       OR last_heartbeat < NOW() - make_interval(secs => %s))
                ORDER BY node_id
                """,
                (STALE_SECONDS,),
            )
            rows = cur.fetchall()
            offline = [r for r in rows if (r["node_id"] if isinstance(r, dict) else r[0]) not in REST_EXCLUDED]
            result["mass_offline"] = len(offline)
            if len(offline) > MASS_OFFLINE_THRESHOLD:
                names = ", ".join(
                    "%s (%ds)"
                    % (
                        (r["node_id"] if isinstance(r, dict) else r[0]),
                        (r["age_s"] if isinstance(r, dict) else r[3]),
                    )
                    for r in offline
                )
                send_system(
                    "Fleet: %d nodes OFFLINE" % len(offline),
                    "%d approved fleet nodes went silent (>%ds): %s. "
                    "Check ARMADA + run scripts/dr/reconcile_fleet_identity.sh." % (len(offline), STALE_SECONDS, names),
                    cooldown_hours=1.0,
                )
                result["alerted"].append("mass_offline")

            # ---- 2. DUPLICATE IDENTITY (FIX1 regression signature) ------
            cur.execute(
                """
                SELECT p.node_id AS junk, p.hostname, a.node_id AS approved_node
                FROM remote_nodes p
                JOIN remote_nodes a
                  ON a.hostname = p.hostname AND a.id <> p.id
                WHERE p.approval_status = 'pending'
                  AND p.deployment_mode = 'standard'
                  AND p.hostname IS NOT NULL
                  AND a.approval_status = 'approved'
                """
            )
            dupes = cur.fetchall()
            result["duplicates"] = len(dupes)
            if dupes:
                pairs = ", ".join(
                    "%s~%s@%s"
                    % (
                        (d["junk"] if isinstance(d, dict) else d[0]),
                        (d["approved_node"] if isinstance(d, dict) else d[2]),
                        (d["hostname"] if isinstance(d, dict) else d[1]),
                    )
                    for d in dupes
                )
                send_system(
                    "Fleet: %d DUPLICATE node identities" % len(dupes),
                    "Pending 'standard' rows match approved hardware: %s. This is the "
                    "re-registration-storm signature and should be IMPOSSIBLE under the "
                    "hub reclaim fix (PR #1464) — FIX1 may have regressed. "
                    "Run scripts/dr/reconcile_fleet_identity.sh --apply." % pairs,
                    cooldown_hours=6.0,
                )
                result["alerted"].append("duplicate_identity")
    except Exception as e:
        logger.warning("fleet_identity_monitor: check failed: %s", e)
        result["error"] = str(e)

    return result
