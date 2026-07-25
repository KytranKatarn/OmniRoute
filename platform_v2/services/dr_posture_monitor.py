"""DR posture monitor — task #4031.

Alert-only watchdog for the warm-standby DR tier (boston-2 / Citadel). Born from
the 2026-06-11 incident: the boston-2 replica had been a PROMOTED FORK since
2026-06-04 17:30Z and ran silent for 7 days — the hub retained 48GB of WAL for
the inactive ``boston2_replica`` slot (root LV hit 87%), the standby platform
long-polled Telegram (#4011 Conflict storm), and outpost-us's zombie WTF stack
kept writing into the fork. fleet_identity_monitor (FIX8) watches node
identity; NOTHING watched replica health. KB mistakes #272169 / #272172.

Hub-side checks (pure SQL — a promoted/disconnected replica is visible here as
an inactive slot, so fork detection needs no boston-2 access):

  1. SLOT MISSING / NOT STREAMING — ``boston2_replica`` slot absent or
     ``active = f`` (the exact signature of the 06-04 fork). CRITICAL.
  2. RETAINED WAL — slot retaining > ``RETAINED_WAL_ALERT_BYTES`` (disk-fill
     trajectory; the incident accumulated ~7GB/day). CRITICAL.
  3. WAL DIR SIZE — pg_wal on disk > ``WAL_DIR_ALERT_BYTES`` (catches non-slot
     WAL bloat too). WARN.
  4. REPLAY LAG — streaming but > ``REPLAY_LAG_ALERT_SECONDS`` behind. WARN.
  5. DR COLD BACKUP STALE — newest ``backup_log`` row with tier='dr' +
     status='success' older than ``DR_BACKUP_STALE_HOURS`` (nightly
     backup_triage.sh ship to boston-2 stopped). WARN.

Runs every 15 min from the agent loop. NEVER mutates anything — alerts via the
unified Telegram channel (send_system has per-title cooldowns). Toggle:
work_control key ``dr_posture_monitor`` (default on).

Remediation when it fires: stop fork writers, then on boston-2 run
``bash /opt/archie-dr/setup_replica.sh`` (NOT failback.sh — that is the
hub-was-down pipeline). Full recipe: KB #272172 / ADR-006 (#726).
"""

import logging
import os

logger = logging.getLogger(__name__)

REPLICA_SLOT = "boston2_replica"
RETAINED_WAL_ALERT_BYTES = 5 * 1024**3  # 5 GiB ≈ under a day of incident-rate growth
WAL_DIR_ALERT_BYTES = 10 * 1024**3  # normal is ~200MB-1GB; the incident hit 48GB
REPLAY_LAG_ALERT_SECONDS = 600
DR_BACKUP_STALE_HOURS = 48

# Truthy spellings accepted for ARCHIE_DR_MODE. Compose sets "1"; the rest are here
# so a hand-edited .env during an outage cannot silently fail to raise the alarm.
_DR_ACTIVE_VALUES = frozenset({"1", "true", "yes", "on"})


def is_dr_active():
    """True when THIS process is the boston-2 DR standby rather than the hub.

    ``ARCHIE_DR_MODE=1`` is already set on both standby services in
    ``scripts/dr/docker-compose.standby.yml`` (#3728, where it tags dispatches as
    DRP-mode work in ``task_execution_log``), so ``failover.sh`` establishes this
    signal for free — there is no new switch for anyone to remember to flip while
    the hub is down, which is exactly when a manual step would get missed.

    Read at call time and deliberately NOT cached. The value is fixed for a
    container's lifetime, so caching would buy nothing measurable while making the
    flag untestable and letting a stale value outlive a compose change.

    Fail-safe **False**: an unset, empty or unrecognised value must never paint a
    red alert across a healthy hub.
    """
    return os.getenv("ARCHIE_DR_MODE", "").strip().lower() in _DR_ACTIVE_VALUES


def _fmt_gb(num_bytes):
    return "%.1f GB" % (num_bytes / 1024**3)


def check_dr_posture():
    """One pass of the DR posture watchdog. Safe to call on a schedule."""
    try:
        from services.work_control_service import is_enabled

        if not is_enabled("dr_posture_monitor", True):
            return {"skipped": "disabled"}
    except Exception:
        pass  # toggle store optional — default to running

    try:
        from database import get_db_cursor
        from services.telegram_service import send_system
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("dr_posture_monitor: dependencies unavailable: %s", e)
        return {"error": str(e)}

    result = {
        "slot_active": None,
        "retained_bytes": None,
        "wal_dir_bytes": None,
        "replay_lag_s": None,
        "dr_backup_age_h": None,
        "alerted": [],
    }

    try:
        with get_db_cursor() as (conn, cur):
            # ---- 1+2. SLOT PRESENT + STREAMING + RETAINED WAL ------------
            cur.execute(
                """
                SELECT active,
                       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
                FROM pg_replication_slots
                WHERE slot_name = %s
                """,
                (REPLICA_SLOT,),
            )
            slot = cur.fetchone()
            if not slot:
                send_system(
                    "DR posture: replication slot MISSING",
                    "Slot '%s' does not exist on the hub — the boston-2 warm-standby "
                    "tier is not wired at all. Re-create via setup_replica.sh on "
                    "boston-2 (KB #272172)." % REPLICA_SLOT,
                    cooldown_hours=6.0,
                )
                result["alerted"].append("slot_missing")
            else:
                active = slot["active"] if isinstance(slot, dict) else slot[0]
                retained = int((slot["retained_bytes"] if isinstance(slot, dict) else slot[1]) or 0)
                result["slot_active"] = bool(active)
                result["retained_bytes"] = retained
                if not active:
                    send_system(
                        "DR posture: replica NOT STREAMING",
                        "Slot '%s' is INACTIVE (retaining %s of WAL). This is the "
                        "promoted-fork/down-replica signature of the 06-04 incident — "
                        "the hub will accumulate WAL until the disk fills. Check "
                        "archie_dr_replica on boston-2 (pg_is_in_recovery must be t); "
                        "rebuild with setup_replica.sh, NOT failback.sh (KB #272172)."
                        % (REPLICA_SLOT, _fmt_gb(retained)),
                        cooldown_hours=1.0,
                    )
                    result["alerted"].append("not_streaming")
                elif retained > RETAINED_WAL_ALERT_BYTES:
                    send_system(
                        "DR posture: replica falling behind",
                        "Slot '%s' is active but retaining %s of WAL (> %s) — the "
                        "replica is not keeping up or the link is degraded."
                        % (REPLICA_SLOT, _fmt_gb(retained), _fmt_gb(RETAINED_WAL_ALERT_BYTES)),
                        cooldown_hours=6.0,
                    )
                    result["alerted"].append("retained_wal")

            # ---- 3. WAL DIR SIZE ON DISK ---------------------------------
            cur.execute("SELECT COALESCE(SUM(size), 0) FROM pg_ls_waldir()")
            row = cur.fetchone()
            wal_bytes = int((row[list(row.keys())[0]] if isinstance(row, dict) else row[0]) or 0)
            result["wal_dir_bytes"] = wal_bytes
            if wal_bytes > WAL_DIR_ALERT_BYTES:
                send_system(
                    "DR posture: pg_wal bloat",
                    "pg_wal is %s on disk (> %s). The 06-04 incident reached 48GB and "
                    "87%% root-volume use. Check pg_replication_slots for an inactive "
                    "slot holding WAL." % (_fmt_gb(wal_bytes), _fmt_gb(WAL_DIR_ALERT_BYTES)),
                    cooldown_hours=6.0,
                )
                result["alerted"].append("wal_dir")

            # ---- 4. REPLAY LAG -------------------------------------------
            cur.execute(
                """
                SELECT COALESCE(EXTRACT(EPOCH FROM replay_lag), 0)::int AS lag_s
                FROM pg_stat_replication
                ORDER BY replay_lag DESC NULLS LAST
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row:
                lag_s = int((row["lag_s"] if isinstance(row, dict) else row[0]) or 0)
                result["replay_lag_s"] = lag_s
                if lag_s > REPLAY_LAG_ALERT_SECONDS:
                    send_system(
                        "DR posture: replica replay lag",
                        "Replica replay lag is %ds (> %ds)." % (lag_s, REPLAY_LAG_ALERT_SECONDS),
                        cooldown_hours=3.0,
                    )
                    result["alerted"].append("replay_lag")

            # ---- 5. DR COLD-BACKUP FRESHNESS -----------------------------
            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) / 3600.0 AS age_h
                FROM backup_log
                WHERE tier = 'dr' AND status = 'success'
                """
            )
            row = cur.fetchone()
            age_h = (row["age_h"] if isinstance(row, dict) else row[0]) if row else None
            result["dr_backup_age_h"] = round(float(age_h), 1) if age_h is not None else None
            if age_h is None or float(age_h) > DR_BACKUP_STALE_HOURS:
                send_system(
                    "DR posture: cold backup stale",
                    "Newest tier='dr' backup_log success is %s — the nightly "
                    "backup_triage.sh ship to boston-2 may have stopped (cron 02:00 ET "
                    "on the hub host)." % ("missing entirely" if age_h is None else "%.0fh old" % float(age_h)),
                    cooldown_hours=12.0,
                )
                result["alerted"].append("dr_backup_stale")
    except Exception as e:
        logger.warning("dr_posture_monitor: check failed: %s", e)
        result["error"] = str(e)

    return result
