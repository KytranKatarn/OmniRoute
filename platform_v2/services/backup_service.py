"""Flask-free backup service layer.

Importable without a Flask application context — safe to call from:
  - W.A.R.D.E.N. scheduled jobs
  - APScheduler / archie_scheduler sidecar
  - Governance service (Phase 3)
  - Tests without app fixtures

Functions
---------
get_health_summary()        -- tier-level health snapshot from backup_log
verify_integrity(backup_id) -- check file exists on disk, update verification_status
run_retention(policy)       -- prune old backup_log rows per policy
snapshot_module(...)        -- insert into module_snapshots (stubs until migration 371)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Tiers present in backup_log ("vps" retired 2026-08-29, decision #1049 — outposts lapse;
# historical vps rows remain in backup_log but the tier is no longer written or reported)
_KNOWN_TIERS = ("primary", "gdrive", "usb")

# Default retention policy (conservative — keeps everything for a year)
_DEFAULT_POLICY: dict[str, Any] = {
    "max_age_days": 365,
    "min_keep": 100,
}


# ---------------------------------------------------------------------------
# get_health_summary
# ---------------------------------------------------------------------------


def get_health_summary() -> dict:
    """Return a tier-level health snapshot from backup_log.

    Returns
    -------
    {
        "status": "healthy" | "degraded",
        "last_backup": "<ISO string>" | None,
        "tier_health": {
            "primary": {"last_run": ..., "status": ..., "age_hours": ...,
                        "last_success": ..., "last_success_age_hours": ...},
            "gdrive":  {...},
            "usb":     {...},
        }
    }

    ``age_hours`` is the age of the LATEST row whatever its status — that is the honest
    dashboard answer ("your last backup attempt failed 9.7h ago" is what an operator needs
    to see, so it is deliberately NOT filtered).

    ``last_success_age_hours`` is the age of the latest row with ``status='success'`` — i.e.
    the age of an actual restore point. **Anything gating on backup freshness MUST use this
    one.** `backup_log.status` carries 'success', 'failed', 'partial', 'skipped' and 'prune'
    (prune is not even a backup), and 171 tier-carrying rows were 'failed' as of 2026-07-20 —
    so the latest row is frequently not a restore point at all. Using ``age_hours`` to gate a
    deploy certifies a backup that may not exist. See task #5013 / KB #282925.
    """
    now_utc = datetime.now(timezone.utc)
    tier_health: dict[str, dict] = {}

    def _age_h(ts):
        if ts is None:
            return None, None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)  # created_at is naive UTC
        return ts, round((now_utc - ts).total_seconds() / 3600, 1)

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Latest row per tier
            cur.execute(
                """
                SELECT DISTINCT ON (tier)
                    tier,
                    status,
                    created_at
                FROM backup_log
                WHERE tier IS NOT NULL
                ORDER BY tier, created_at DESC
                """
            )
            rows = cur.fetchall()

            # Latest SUCCESSFUL row per tier — the real restore point.
            cur.execute(
                """
                SELECT DISTINCT ON (tier)
                    tier,
                    created_at
                FROM backup_log
                WHERE tier IS NOT NULL AND status = 'success'
                ORDER BY tier, created_at DESC
                """
            )
            success_rows = {r["tier"]: r["created_at"] for r in cur.fetchall()}

        for row in rows:
            tier = row["tier"]
            raw_ts, age_hours = _age_h(row["created_at"])
            ok_ts, ok_age = _age_h(success_rows.get(tier))
            tier_health[tier] = {
                "last_run": raw_ts.isoformat() if raw_ts else None,
                "status": row["status"],
                "age_hours": age_hours,
                "last_success": ok_ts.isoformat() if ok_ts else None,
                "last_success_age_hours": ok_age,
            }

        # Fill in any known tiers with no rows
        for t in _KNOWN_TIERS:
            if t not in tier_health:
                tier_health[t] = {
                    "last_run": None,
                    "status": None,
                    "age_hours": None,
                    "last_success": None,
                    "last_success_age_hours": None,
                }

        # Determine overall last_backup (most recent success across all tiers)
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT created_at FROM backup_log
                    WHERE status = 'success'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        except Exception:
            row = None

        last_backup: str | None = None
        if row and row["created_at"]:
            ts = row["created_at"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            last_backup = ts.isoformat()

        # Degraded if any known tier has no recent success (>48h or never)
        degraded = False
        for t in _KNOWN_TIERS:
            th = tier_health.get(t, {})
            if th.get("status") not in ("success", "skipped") or (
                th.get("age_hours") is not None and th["age_hours"] > 48
            ):
                degraded = True
                break

        return {
            "status": "degraded" if degraded else "healthy",
            "last_backup": last_backup,
            "tier_health": tier_health,
        }

    except Exception as exc:
        logger.error("get_health_summary failed: %s", exc)
        return {
            "status": "degraded",
            "last_backup": None,
            "tier_health": {t: {"last_run": None, "status": None, "age_hours": None} for t in _KNOWN_TIERS},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# verify_integrity
# ---------------------------------------------------------------------------


def verify_integrity(backup_id: int) -> dict:
    """Check that a backup_log row's file_path exists on disk.

    Updates verification_status to 'verified' or 'missing'.

    Returns
    -------
    {
        "success": bool,
        "error": str | None,          -- "not_found" if row missing
        "verification_status": str,
        "backup_id": int,
        "file_path": str | None,
    }
    """
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id, file_path, verification_status FROM backup_log WHERE id = %s",
                (backup_id,),
            )
            row = cur.fetchone()

        if not row:
            return {
                "success": False,
                "error": "not_found",
                "backup_id": backup_id,
                "file_path": None,
                "verification_status": None,
            }

        file_path = row["file_path"]
        if file_path and os.path.exists(file_path):
            new_status = "verified"
        else:
            new_status = "missing"

        # Update verification_status
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE backup_log SET verification_status = %s WHERE id = %s",
                (new_status, backup_id),
            )

        return {
            "success": True,
            "error": None,
            "backup_id": backup_id,
            "file_path": file_path,
            "verification_status": new_status,
        }

    except Exception as exc:
        logger.error("verify_integrity(%s) failed: %s", backup_id, exc)
        return {
            "success": False,
            "error": str(exc),
            "backup_id": backup_id,
            "file_path": None,
            "verification_status": None,
        }


# ---------------------------------------------------------------------------
# run_retention
# ---------------------------------------------------------------------------


def run_retention(policy: dict | None = None) -> dict:
    """Prune backup_log rows older than policy['max_age_days'], keeping at least
    policy['min_keep'] rows.

    Returns
    -------
    {"success": bool, "pruned": int, "error": str | None}
    """
    if policy is None:
        policy = _DEFAULT_POLICY

    max_age_days: int = int(policy.get("max_age_days", _DEFAULT_POLICY["max_age_days"]))
    min_keep: int = int(policy.get("min_keep", _DEFAULT_POLICY["min_keep"]))

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Count total rows
            cur.execute("SELECT COUNT(*) AS cnt FROM backup_log")
            total = cur.fetchone()["cnt"]

            if total <= min_keep:
                return {"success": True, "pruned": 0, "kept": total}

            # Delete rows older than max_age_days, but preserve the newest min_keep rows
            cur.execute(
                """
                DELETE FROM backup_log
                WHERE id IN (
                    SELECT id FROM backup_log
                    ORDER BY created_at DESC
                    OFFSET %s
                )
                AND created_at < NOW() - INTERVAL '%s days'
                """,
                (min_keep, max_age_days),
            )
            pruned = cur.rowcount

        return {"success": True, "pruned": pruned}

    except Exception as exc:
        logger.error("run_retention failed: %s", exc)
        return {"success": False, "pruned": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# snapshot_module
# ---------------------------------------------------------------------------


def snapshot_module(
    module_name: str,
    snapshot_type: str,
    trigger_source: str,
    backup_id: int | None = None,
    clearance_task_id: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """Insert a row into module_snapshots.

    Requires migration 371 (Task 7). Until that migration runs, this returns
    a descriptive error rather than crashing.

    Returns
    -------
    {"success": bool, "snapshot_id": int | None, "error": str | None}
    """
    import json

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO module_snapshots
                    (module_name, snapshot_type, trigger_source, backup_id,
                     clearance_task_id, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    module_name,
                    snapshot_type,
                    trigger_source,
                    backup_id,
                    clearance_task_id,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            row = cur.fetchone()
            snapshot_id = row["id"] if row else None

        return {"success": True, "snapshot_id": snapshot_id, "error": None}

    except Exception as exc:
        exc_str = str(exc)
        # Detect missing table (psycopg2 ProgrammingError / UndefinedTable)
        if "module_snapshots" in exc_str and ("does not exist" in exc_str or "undefined" in exc_str.lower()):
            return {
                "success": False,
                "snapshot_id": None,
                "error": "module_snapshots table missing — run migration 371",
            }
        logger.error("snapshot_module(%s) failed: %s", module_name, exc)
        return {"success": False, "snapshot_id": None, "error": exc_str}
