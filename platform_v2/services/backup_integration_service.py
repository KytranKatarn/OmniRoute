"""Backup integration with Repair Bay — pre-change snapshots.

Creates a lightweight backup before code changes are deployed.
Integrates with deployment_notifier for notifications.
"""

import os
import subprocess
import logging
from datetime import datetime
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Inside the archie_platform container, /mnt/data2 is not writable. The `./backups:/backups`
# compose mount points at /mnt/archie_brain/backups on the host, which is a symlink to
# /mnt/data2/backups. So the host sees /mnt/data2/backups while the container writes to /backups.
# Same physical location, two address spaces.
PRECHANGE_DIR = "/backups/pre-change"
PRIMARY_DIR = "/backups"
USB_DIR = "/mnt/external-backup"
RETENTION_PRECHANGE = 20
RETENTION_DAILY = 30
RETENTION_WEEKLY = 12


def _current_build():
    """Current platform build number (read-only) to stamp pre-change snapshots (#5087).

    Read straight from the counter file the button/programmatic path owns
    (set_build_number) — a snapshot records the build it ran under, never bumps it.
    Returns None (→ SQL NULL) if the file is missing or unreadable; a build stamp must
    never be able to fail a backup.
    """
    try:
        with open(os.path.join(PRIMARY_DIR, ".current_build")) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def create_prechange_snapshot(description=""):
    """Create a lightweight snapshot before code changes.

    Hardened 2026-04-17 (task #2054):
    - pg_dump uses -Fc custom format (compressed, matches Phase 1-6 pipeline)
    - Output streams directly to file via stdout pipe (no 2+ GB in-memory buffer
      that the old capture_output=True, text=True approach required)
    - Timeout extended from 120s → 600s to match production pg_dump size
    - --no-owner --no-privileges so the dump restores cleanly into a fresh
      postgres instance (e.g. DR drill sandbox)
    - Failed dump now logs a 'failed' row to backup_log and returns error
      instead of silently writing an empty file
    """
    os.makedirs(PRECHANGE_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"{timestamp}_pre_change"
    snapshot_dir = os.path.join(PRECHANGE_DIR, snapshot_name)

    try:
        os.makedirs(snapshot_dir, exist_ok=True)

        # Snapshot the database — streaming pg_dump -Fc directly to file.
        db_file = os.path.join(snapshot_dir, f"archie_{timestamp}.dump")
        try:
            with open(db_file, "wb") as f:
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        "archie_database",
                        "pg_dump",
                        "-U",
                        "archie",
                        "-d",
                        "archie",
                        "-Fc",
                        "-Z",
                        "6",
                        "--no-owner",
                        "--no-privileges",
                    ],
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=600,
                )
            if result.returncode != 0:
                err = (result.stderr or b"").decode("utf-8", errors="replace")[:500]
                logger.error("[Backup] pg_dump failed rc=%s err=%s", result.returncode, err)
                # Clean up the partial file so we don't mislead downstream scans.
                try:
                    os.remove(db_file)
                except OSError:
                    pass
                with get_db_cursor(commit=True) as (_, cur):
                    cur.execute(
                        """INSERT INTO backup_log
                            (component, tier, status, file_path, size_bytes,
                             backup_type, file_size_bytes, notes, error_message,
                             build_number, completed_at, created_at)
                           VALUES
                            ('pre-change', 'primary', 'failed', %s, 0,
                             'pre_change', 0, %s, %s, %s, NOW(), NOW())""",
                        (snapshot_dir, description, f"pg_dump rc={result.returncode}: {err}", _current_build()),
                    )
                return {"error": f"pg_dump failed (rc={result.returncode})"}
        except subprocess.TimeoutExpired:
            logger.error("[Backup] pg_dump timed out after 600s")
            return {"error": "pg_dump timed out after 600s"}

        # Snapshot git state
        git_file = os.path.join(snapshot_dir, "git_state.txt")
        git_result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd="/mnt/archie_brain",
            capture_output=True,
            text=True,
            timeout=10,
        )
        with open(git_file, "w") as f:
            f.write(f"Description: {description}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Git HEAD:\n{git_result.stdout}\n")

        # Log to DB
        with get_db_cursor(commit=True) as (conn, cur):
            # Phase 5 / Task 21 — write canonical (component, tier, size_bytes)
            # columns so watchdog freshness + UI tier-health queries see pre-change
            # snapshots. Keep legacy columns populated for backward compat with
            # older dashboards reading backup_type/file_size_bytes.
            snap_size = 0
            try:
                for root, _dirs, files in os.walk(snapshot_dir):
                    for fn in files:
                        try:
                            snap_size += os.path.getsize(os.path.join(root, fn))
                        except OSError:
                            pass
            except Exception:
                pass
            cur.execute(
                """
                INSERT INTO backup_log
                    (component, tier, status, file_path, size_bytes,
                     backup_type, file_size_bytes, notes, build_number, completed_at, created_at)
                VALUES
                    ('pre-change', 'primary', 'success', %s, %s,
                     'pre_change', %s, %s, %s, NOW(), NOW())
                """,
                (snapshot_dir, snap_size, snap_size, description, _current_build()),
            )

        # Cleanup old snapshots
        cleanup_old_snapshots(PRECHANGE_DIR, RETENTION_PRECHANGE)

        logger.info(f"[Backup] Pre-change snapshot created: {snapshot_name}")
        return {"success": True, "path": snapshot_dir, "name": snapshot_name}
    except Exception as e:
        logger.error(f"[Backup] Pre-change snapshot failed: {e}")
        return {"error": str(e)}


def cleanup_old_snapshots(directory, max_keep):
    """Remove oldest snapshots beyond retention limit."""
    try:
        entries = sorted(os.listdir(directory))
        while len(entries) > max_keep:
            oldest = entries.pop(0)
            path = os.path.join(directory, oldest)
            if os.path.isdir(path):
                subprocess.run(["rm", "-rf", path], timeout=30)
                logger.info(f"[Backup] Removed old snapshot: {oldest}")
    except Exception as e:
        logger.warning(f"[Backup] Cleanup error: {e}")


def cleanup_usb_to_weekly():
    """Keep only weekly backups on USB (run after each backup cycle)."""
    try:
        entries = sorted(os.listdir(USB_DIR))
        # Keep entries from Sundays only (or the closest day)
        # Simple: keep max RETENTION_WEEKLY entries, remove oldest
        while len(entries) > RETENTION_WEEKLY:
            oldest = entries.pop(0)
            path = os.path.join(USB_DIR, oldest)
            if os.path.isdir(path):
                subprocess.run(["sudo", "rm", "-rf", path], timeout=60)
                logger.info(f"[Backup] Removed old USB backup: {oldest}")
    except Exception as e:
        logger.warning(f"[Backup] USB cleanup error: {e}")


def get_backup_stats():
    """Return backup statistics."""
    stats = {}
    for name, path in [
        ("primary", PRIMARY_DIR),
        ("usb", USB_DIR),
        ("pre_change", PRECHANGE_DIR),
    ]:
        try:
            if os.path.exists(path):
                entries = os.listdir(path)
                stats[name] = {
                    "count": len(entries),
                    "path": path,
                    "latest": sorted(entries)[-1] if entries else None,
                }
            else:
                stats[name] = {"count": 0, "path": path, "latest": None}
        except Exception:
            stats[name] = {"count": 0, "path": path, "error": True}
    return stats
