"""Export service — ZIP archive generation as background jobs.

Validates media ownership, creates ZIP in MEDIA_ROOT/exports/,
cleans up expired archives hourly via APScheduler.
"""

import logging
import os
import time
import zipfile
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")
EXPORTS_DIR = os.path.join(MEDIA_ROOT, "exports")

# Max items per export to prevent OOM
MAX_EXPORT_ITEMS = 500

os.makedirs(EXPORTS_DIR, exist_ok=True)


def create_export_job(media_ids: List[int], owner_type: str, owner_id: int) -> Optional[int]:
    """Validate ownership of all media_ids and create an export job.

    Returns job_id or None if validation fails.
    """
    if not media_ids:
        return None

    if len(media_ids) > MAX_EXPORT_ITEMS:
        logger.warning(f"Export request exceeds {MAX_EXPORT_ITEMS} items, truncating")
        media_ids = media_ids[:MAX_EXPORT_ITEMS]

    with get_db_cursor(commit=True) as (conn, cur):
        # Verify ALL media_ids belong to this owner
        cur.execute(
            """
            SELECT id, file_path FROM media_library
            WHERE id = ANY(%s) AND owner_type = %s AND owner_id = %s AND is_deleted = false
            """,
            (media_ids, owner_type, owner_id),
        )
        owned = cur.fetchall()
        if len(owned) != len(media_ids):
            return None

        # Create export job record in media_generation_queue (reuse existing table)
        import psycopg2.extras

        cur.execute(
            """
            INSERT INTO media_generation_queue
                (owner_type, owner_id, media_type, status, params)
            VALUES (%s, %s, 'export', 'pending', %s)
            RETURNING id
            """,
            (
                owner_type,
                owner_id,
                psycopg2.extras.Json({"media_ids": media_ids, "type": "zip_export"}),
            ),
        )
        return cur.fetchone()["id"]


def generate_zip(job_id: int, media_ids: List[int]) -> Optional[str]:
    """Create ZIP archive from media files. Returns file path or None on failure."""
    zip_name = f"export_{job_id}_{int(time.time())}.zip"
    zip_path = os.path.join(EXPORTS_DIR, zip_name)

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, file_path, media_type, prompt FROM media_library WHERE id = ANY(%s) AND is_deleted = false",
                (media_ids,),
            )
            rows = cur.fetchall()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for row in rows:
                full_path = os.path.join(_PLATFORM_DIR, row["file_path"].lstrip("/"))
                if os.path.exists(full_path):
                    arcname = os.path.basename(full_path)
                    zf.write(full_path, arcname)

        # Update job status
        rel_path = f"/static/media/exports/{zip_name}"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'completed', result_path = %s, completed_at = now()
                WHERE id = %s
                """,
                (rel_path, job_id),
            )

        return rel_path
    except Exception as e:
        logger.error(f"ZIP export failed for job {job_id}: {e}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_generation_queue SET status = 'failed', error = %s WHERE id = %s",
                (str(e), job_id),
            )
        return None


def get_export_status(job_id: int, owner_type: str, owner_id: int) -> Optional[Dict]:
    """Get export job status with download URL when complete."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, status, result_path, created_at, completed_at
            FROM media_generation_queue
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND media_type = 'export'
            """,
            (job_id, owner_type, owner_id),
        )
        row = cur.fetchone()
    if not row:
        return None

    result = {"job_id": row["id"], "status": row["status"]}
    if row["status"] == "completed" and row["result_path"]:
        result["download_url"] = row["result_path"]
    return result


def cleanup_exports(max_age_hours: int = 1) -> int:
    """Delete expired export ZIP files. Returns count deleted."""
    deleted = 0
    cutoff = time.time() - (max_age_hours * 3600)

    if not os.path.isdir(EXPORTS_DIR):
        return 0

    expired_job_ids = []
    for fname in os.listdir(EXPORTS_DIR):
        if not fname.endswith(".zip"):
            continue
        fpath = os.path.join(EXPORTS_DIR, fname)
        if os.path.getmtime(fpath) < cutoff:
            try:
                os.remove(fpath)
                deleted += 1
                # Extract job_id from filename: export_{job_id}_{timestamp}.zip
                parts = fname.replace(".zip", "").split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    expired_job_ids.append(int(parts[1]))
            except OSError as e:
                logger.warning(f"Failed to delete export {fname}: {e}")

    # Mark DB records as expired so get_export_status doesn't return stale URLs
    if expired_job_ids:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE media_generation_queue SET status = 'expired' WHERE id = ANY(%s) AND status = 'completed'",
                (expired_job_ids,),
            )

    if deleted:
        logger.info(f"Cleaned up {deleted} expired export(s)")
    return deleted
