"""
Async Backup Download Service.
Prepares tar.gz archives in background threads, tracks state in backup_download_jobs.
Auto-cleanup: expires_at = created_at + 1h. W.A.R.D.E.N. nightly prune.
"""

from __future__ import annotations

import logging
import os
import tarfile
import threading
from typing import Any

from database import get_db_cursor

logger = logging.getLogger(__name__)

BACKUP_DIR = "/backups"
DOWNLOAD_TEMP_DIR = "/backups/.downloads"


def prepare_download(backup_name: str, triggered_by: str = "user") -> dict[str, Any]:
    """
    Start async preparation of a backup archive for download.
    Returns immediately with job_id. Poll get_download_status(job_id) for progress.
    """
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        return {"success": False, "error": "backup_not_found"}

    # Clean up expired jobs first
    try:
        cleanup_expired()
    except Exception:
        pass

    # Reuse existing active job for this backup if one exists
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, status FROM backup_download_jobs
               WHERE backup_name = %s AND status IN ('pending','preparing','ready')
                 AND expires_at > NOW()
               ORDER BY created_at DESC LIMIT 1""",
            (backup_name,),
        )
        existing = cur.fetchone()
        if existing:
            return {
                "success": True,
                "job_id": existing["id"],
                "status": existing["status"],
                "reused": True,
            }

    # Create new job
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO backup_download_jobs (backup_name, status) VALUES (%s, 'pending') RETURNING id",
            (backup_name,),
        )
        job_id = cur.fetchone()["id"]

    # Start background thread
    t = threading.Thread(target=_prepare_archive, args=(job_id, backup_name, backup_path), daemon=True)
    t.start()

    return {"success": True, "job_id": job_id, "status": "pending"}


def _prepare_archive(job_id: int, backup_name: str, backup_path: str) -> None:
    """Background thread: creates tar.gz and updates job status."""
    os.makedirs(DOWNLOAD_TEMP_DIR, exist_ok=True)
    archive_path = os.path.join(DOWNLOAD_TEMP_DIR, f"download_{job_id}_{backup_name}.tar.gz")

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE backup_download_jobs SET status='preparing' WHERE id=%s",
                (job_id,),
            )
    except Exception as e:
        logger.warning("Could not set preparing status for job %s: %s", job_id, e)

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_path, arcname=backup_name)

        file_size = os.path.getsize(archive_path)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE backup_download_jobs
                   SET status='ready', archive_path=%s, file_size_bytes=%s
                   WHERE id=%s""",
                (archive_path, file_size, job_id),
            )
        logger.info("Download prepared: job=%s backup=%s size=%s", job_id, backup_name, file_size)

    except Exception as e:
        logger.error("Archive preparation failed for job %s: %s", job_id, e)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE backup_download_jobs SET status='failed', error=%s WHERE id=%s",
                    (str(e), job_id),
                )
        except Exception:
            pass
        if os.path.exists(archive_path):
            os.remove(archive_path)


def get_download_status(job_id: int) -> dict[str, Any]:
    """Return current status of a download preparation job."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT * FROM backup_download_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "job_not_found"}
        return {
            "success": True,
            "job_id": row["id"],
            "backup_name": row["backup_name"],
            "status": row["status"],
            "file_size_bytes": row["file_size_bytes"],
            "error": row["error"],
            "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
        }


def serve_and_delete(job_id: int) -> dict[str, Any]:
    """Mark job as expired and return archive_path for send_file (one-time use)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE backup_download_jobs
               SET status='expired', downloaded_at=NOW()
               WHERE id=%s AND status='ready'
               RETURNING archive_path""",
            (job_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "job_not_ready"}
        return {"success": True, "archive_path": row["archive_path"]}


def cleanup_expired() -> int:
    """Delete expired/downloaded/failed job records and their archive files. Returns count."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, archive_path FROM backup_download_jobs
               WHERE expires_at < NOW() OR status IN ('expired','failed')"""
        )
        rows = cur.fetchall()

    for row in rows:
        if row["archive_path"] and os.path.exists(row["archive_path"]):
            try:
                os.remove(row["archive_path"])
            except Exception as e:
                logger.warning("Could not delete archive %s: %s", row["archive_path"], e)

    if rows:
        ids = [r["id"] for r in rows]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM backup_download_jobs WHERE id = ANY(%s)", (ids,))

    return len(rows)
