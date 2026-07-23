"""Live Admin Ops department briefing injected into W.A.R.D.E.N. chat context."""

import os
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor
from services.time_utils import now_local_str


def _build_warden_briefing() -> str:
    """
    Return a plain-text briefing of the Backup Manager's current state.
    Prepended to the user's first message in new W.A.R.D.E.N. conversations
    so he can answer status questions without extra fetches.
    """
    from tools.backup_manager._shared import (
        LOCK_FILE,
        get_backup_db_cursor,
    )

    now_str = now_local_str()
    lines = [f"\n[W.A.R.D.E.N. DEPARTMENT BRIEFING — {now_str}]"]

    try:
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (_, cur):
            # Latest successful non-standalone backup
            cur.execute(
                "SELECT file_path, created_at, size_bytes FROM backup_log "
                "WHERE status = 'success' AND (backup_type IS NULL OR backup_type != 'standalone') "
                "ORDER BY created_at DESC LIMIT 1"
            )
            latest = cur.fetchone()
            if latest:
                age = datetime.now(timezone.utc) - latest["created_at"].astimezone(timezone.utc)
                h = int(age.total_seconds() // 3600)
                name = os.path.basename((latest["file_path"] or "").rstrip("/")) or "unknown"
                size_mb = round((latest["size_bytes"] or 0) / 1024 / 1024, 1)
                lines.append(f"Latest backup: {name} ({h}h ago, {size_mb} MB)")
            else:
                lines.append("Latest backup: none recorded")

            # Total count + storage size
            cur.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(size_bytes), 0) AS total_bytes "
                "FROM backup_log WHERE backup_type IS NULL OR backup_type != 'standalone'"
            )
            row_cnt = cur.fetchone() or {}
            cnt = row_cnt.get("cnt", 0)
            total_gb = round((row_cnt.get("total_bytes") or 0) / 1024 / 1024 / 1024, 1)
            storage_note = " ⚠️ OVER 100 GB — verify the nightly retention prune is running" if total_gb > 100 else ""
            lines.append(f"Total backups: {cnt} ({total_gb} GB used){storage_note}")

            # Standalones — latest status per product
            cur.execute(
                """
                SELECT DISTINCT ON (standalone_name)
                       standalone_name, status, created_at
                FROM backup_log
                WHERE backup_type = 'standalone'
                  AND standalone_name IS NOT NULL
                ORDER BY standalone_name, created_at DESC
                """
            )
            standalones = cur.fetchall()
            if standalones:
                lines.append(f"Standalones ({len(standalones)} products):")
                for s in standalones:
                    badge = "⚠️" if s["status"] == "partial" else ("✅" if s["status"] == "success" else "❌")
                    lines.append(f"  {badge} {s['standalone_name']}: {s['status']}")
            else:
                lines.append("Standalones: no records")

            # Failures in last 24h
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM backup_log "
                "WHERE status = 'failed' AND created_at > NOW() - INTERVAL '24 hours'"
            )
            fail_cnt = (cur.fetchone() or {}).get("cnt", 0)
            lines.append(f"Recent failures (24h): {fail_cnt}" if fail_cnt else "Recent failures (24h): none")

    except Exception as exc:
        lines.append(f"[Briefing data unavailable: {exc}]")

    # Lock
    lines.append(f"Backup lock: {'ACTIVE ⚠️' if os.path.exists(LOCK_FILE) else 'none'}")

    # Retention — report the canonical nightly engine's LAST RUN, not a delete plan.
    # The old code called get_backup_retention_status() and surfaced its delete_count: a
    # RETIRED single-triple pruner's projection for a policy the system does not enforce
    # (the real engine is scripts/backup/retention_prune.py, per-component/tier, and it
    # writes retention_last_run / retention_last_deleted_count to system_config). #5141.
    try:
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (_, cur):
            cur.execute(
                "SELECT key, value FROM system_config "
                "WHERE key IN ('retention_last_run', 'retention_last_deleted_count')"
            )
            rr = {r["key"]: r["value"] for r in cur.fetchall()}
        last_run = rr.get("retention_last_run") or "never"
        last_del = rr.get("retention_last_deleted_count") or "0"
        lines.append(f"Retention: automatic (nightly, per-component/tier). Last prune {last_run}, {last_del} removed.")
    except Exception:
        lines.append("Retention: automatic (nightly) — last-run data unavailable")

    # Path health advisory — flag DB entries using non-canonical host paths
    try:
        with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (_, cur):
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM backup_log WHERE file_path NOT LIKE '/backups/%'"
                " AND file_path NOT LIKE '/mnt/external-backup/%'"
                " AND file_path IS NOT NULL AND file_path != ''"
            )
            non_canonical = (cur.fetchone() or {}).get("cnt", 0)
            if non_canonical > 10:
                lines.append(
                    f"⚠️ Path advisory: {non_canonical} DB entries use non-standard paths "
                    f"(host-path vs container-path mismatch)."
                )
    except Exception:
        pass

    lines.append(
        "[End briefing — use this data to answer status questions. "
        "Propose actions using the [ACTION]{...}[/ACTION] format when the user asks you to do something.]\n"
    )
    return "\n".join(lines)
