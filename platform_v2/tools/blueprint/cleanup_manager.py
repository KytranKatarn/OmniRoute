"""Platform Cleanup Manager - Manage cleanup candidates and execute cleanups."""

import os
import shutil
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Platform directories
PLATFORM_ROOT = "/mnt/archie_brain"
ARCHIVE_DIR = os.path.join(PLATFORM_ROOT, "backups", "archived_files")
DOCS_DIR = os.path.join(PLATFORM_ROOT, "docs")
TOOLS_DIR = os.path.join(PLATFORM_ROOT, "platform_v2", "tools")
DEPRECATED_DIR = os.path.join(PLATFORM_ROOT, "platform_v2", "_deprecated")

# Known cleanup patterns
STUB_TOOLS = [
    "automation_services",
    "book_builder",
    "cursor_integration",
    "google_workspace",
    "picture_generation",
    "site_manager",
    "stock_bot",
    "story_generation",
    "task_planner",
    "video_generation",
]

DUPLICATE_TOOLS = [
    ("game_builder", "game_studio"),
    ("website_builder", "website_studio"),
]

DATE_STAMPED_DOCS = [
    "IMPROVEMENT_WORKFLOW_STATUS_20260108.md",
    "IMPROVEMENT_WORKFLOW_STATUS_20260109.md",
    "IMPROVEMENT_WORKFLOW_STATUS_20260110.md",
    "IMPROVEMENT_WORKFLOW_STATUS_20260111.md",
    "IMPROVEMENT_WORKFLOW_STATUS_20260112.md",
    "IMPROVEMENT_WORKFLOW_STATUS_20260113.md",
]


def get_file_size(path: str) -> int:
    """Get file or directory size in bytes."""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        elif os.path.isdir(path):
            total = 0
            for dirpath, _, filenames in os.walk(path):
                for f in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
            return total
    except OSError:
        return 0
    return 0


def scan_for_candidates() -> List[Dict[str, Any]]:
    """Scan platform for cleanup candidates."""
    candidates = []

    # 1. Check deprecated directory
    if os.path.exists(DEPRECATED_DIR):
        for item in os.listdir(DEPRECATED_DIR):
            item_path = os.path.join(DEPRECATED_DIR, item)
            candidates.append(
                {
                    "file_path": item_path,
                    "file_type": "directory" if os.path.isdir(item_path) else "python",
                    "category": "deprecated",
                    "file_size_bytes": get_file_size(item_path),
                    "reason": "Located in _deprecated directory",
                    "action_recommended": "archive",
                }
            )

    # 2. Check stub tools
    for stub in STUB_TOOLS:
        stub_path = os.path.join(TOOLS_DIR, stub)
        if os.path.exists(stub_path):
            # Check if it's actually a stub (less than 200 lines total)
            line_count = 0
            for f in os.listdir(stub_path):
                if f.endswith(".py"):
                    try:
                        with open(os.path.join(stub_path, f)) as fp:
                            line_count += sum(1 for _ in fp)
                    except:
                        pass

            if line_count < 200:
                candidates.append(
                    {
                        "file_path": stub_path,
                        "file_type": "directory",
                        "category": "orphaned",
                        "file_size_bytes": get_file_size(stub_path),
                        "reason": f"Stub tool ({line_count} lines), not in module_registry",
                        "action_recommended": "delete",
                    }
                )

    # 3. Check duplicate tools
    for old_name, new_name in DUPLICATE_TOOLS:
        old_path = os.path.join(TOOLS_DIR, old_name)
        new_path = os.path.join(TOOLS_DIR, new_name)
        if os.path.exists(old_path) and os.path.exists(new_path):
            candidates.append(
                {
                    "file_path": old_path,
                    "file_type": "directory",
                    "category": "duplicate",
                    "file_size_bytes": get_file_size(old_path),
                    "reason": f"Duplicate of {new_name} (newer version exists)",
                    "action_recommended": "delete",
                }
            )

    # 4. Check date-stamped docs
    for doc in DATE_STAMPED_DOCS:
        doc_path = os.path.join(DOCS_DIR, doc)
        if os.path.exists(doc_path):
            candidates.append(
                {
                    "file_path": doc_path,
                    "file_type": "markdown",
                    "category": "outdated",
                    "file_size_bytes": get_file_size(doc_path),
                    "reason": "Date-stamped status doc, superseded by current version",
                    "action_recommended": "archive",
                }
            )

    # 5. Check for old phase docs
    for f in os.listdir(DOCS_DIR):
        if f.startswith("PHASE_") and f.endswith(".md"):
            # Old phase docs (PHASE_0_, PHASE_1_, etc.)
            doc_path = os.path.join(DOCS_DIR, f)
            candidates.append(
                {
                    "file_path": doc_path,
                    "file_type": "markdown",
                    "category": "outdated",
                    "file_size_bytes": get_file_size(doc_path),
                    "reason": "Old phase documentation, phases now in database",
                    "action_recommended": "archive",
                }
            )

    logger.info(f"Found {len(candidates)} cleanup candidates")
    return candidates


def add_candidates_to_db(candidates: List[Dict[str, Any]]) -> int:
    """Add cleanup candidates to database (skip existing)."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    added = 0

    try:
        for c in candidates:
            # Check if already exists
            cur.execute(
                "SELECT id FROM platform_cleanup_candidates WHERE file_path = %s",
                (c["file_path"],),
            )
            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO platform_cleanup_candidates
                (file_path, file_type, category, file_size_bytes, reason, action_recommended)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    c["file_path"],
                    c["file_type"],
                    c["category"],
                    c["file_size_bytes"],
                    c["reason"],
                    c["action_recommended"],
                ),
            )
            added += 1

        conn.commit()
        logger.info(f"Added {added} new cleanup candidates")
        return added
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding candidates: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def get_candidates(status: str = None, category: str = None) -> List[Dict[str, Any]]:
    """Get cleanup candidates, optionally filtered."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        query = "SELECT * FROM platform_cleanup_candidates WHERE 1=1"
        params = []

        if status:
            query += " AND status = %s"
            params.append(status)

        if category:
            query += " AND category = %s"
            params.append(category)

        query += " ORDER BY created_at DESC"

        cur.execute(query, params)

        results = []
        for row in cur.fetchall():
            r = dict(row)
            for key in ["created_at", "approved_at", "executed_at"]:
                if r.get(key):
                    r[key] = r[key].isoformat()
            results.append(r)

        return results
    finally:
        cur.close()
        conn.close()


def approve_candidate(candidate_id: int, approved_by: str) -> bool:
    """Approve a cleanup candidate for execution."""
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE platform_cleanup_candidates
            SET status = 'approved', approved_by = %s, approved_at = NOW()
            WHERE id = %s AND status = 'pending'
        """,
            (approved_by, candidate_id),
        )

        success = cur.rowcount > 0
        conn.commit()

        if success:
            logger.info(f"Approved cleanup candidate {candidate_id}")

        return success
    except Exception as e:
        conn.rollback()
        logger.error(f"Error approving candidate: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def reject_candidate(candidate_id: int) -> bool:
    """Reject a cleanup candidate."""
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE platform_cleanup_candidates
            SET status = 'rejected'
            WHERE id = %s AND status = 'pending'
        """,
            (candidate_id,),
        )

        success = cur.rowcount > 0
        conn.commit()

        if success:
            logger.info(f"Rejected cleanup candidate {candidate_id}")

        return success
    except Exception as e:
        conn.rollback()
        logger.error(f"Error rejecting candidate: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def bulk_approve(candidate_ids: List[int], approved_by: str) -> int:
    """Approve multiple candidates at once."""
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE platform_cleanup_candidates
            SET status = 'approved', approved_by = %s, approved_at = NOW()
            WHERE id = ANY(%s) AND status = 'pending'
        """,
            (approved_by, candidate_ids),
        )

        count = cur.rowcount
        conn.commit()

        logger.info(f"Bulk approved {count} cleanup candidates")
        return count
    except Exception as e:
        conn.rollback()
        logger.error(f"Error bulk approving: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def execute_cleanup(candidate_id: int) -> Dict[str, Any]:
    """Execute cleanup for an approved candidate."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get candidate
        cur.execute(
            "SELECT * FROM platform_cleanup_candidates WHERE id = %s AND status = 'approved'",
            (candidate_id,),
        )
        candidate = cur.fetchone()

        if not candidate:
            return {"success": False, "error": "Candidate not found or not approved"}

        file_path = candidate["file_path"]
        action = candidate["action_recommended"]

        if not os.path.exists(file_path):
            # Already cleaned up or doesn't exist
            cur.execute(
                "UPDATE platform_cleanup_candidates SET status = 'executed', executed_at = NOW() WHERE id = %s",
                (candidate_id,),
            )
            conn.commit()
            return {
                "success": True,
                "action": "skipped",
                "reason": "File no longer exists",
            }

        result = {"success": False}

        if action == "archive":
            # Move to archive directory
            archive_path = _get_archive_path(file_path)
            os.makedirs(os.path.dirname(archive_path), exist_ok=True)

            if os.path.isdir(file_path):
                shutil.move(file_path, archive_path)
            else:
                shutil.move(file_path, archive_path)

            result = {
                "success": True,
                "action": "archived",
                "archive_path": archive_path,
            }

        elif action == "delete":
            # Permanently delete
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)

            result = {"success": True, "action": "deleted"}

        elif action == "merge":
            # Merge is complex - just mark as executed for manual review
            result = {
                "success": True,
                "action": "manual_review",
                "reason": "Merge requires manual review",
            }

        if result["success"]:
            cur.execute(
                "UPDATE platform_cleanup_candidates SET status = 'executed', executed_at = NOW() WHERE id = %s",
                (candidate_id,),
            )
            conn.commit()
            logger.info(f"Executed cleanup for candidate {candidate_id}: {result}")

        return result

    except Exception as e:
        conn.rollback()
        logger.error(f"Error executing cleanup: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def _get_archive_path(original_path: str) -> str:
    """Generate archive path preserving directory structure."""
    # Remove platform root prefix
    relative = os.path.relpath(original_path, PLATFORM_ROOT)

    # Add timestamp to avoid conflicts
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.basename(original_path)
    name, ext = os.path.splitext(base)

    if os.path.isdir(original_path):
        archive_name = f"{name}_{timestamp}"
    else:
        archive_name = f"{name}_{timestamp}{ext}"

    return os.path.join(ARCHIVE_DIR, os.path.dirname(relative), archive_name)


def bulk_execute(candidate_ids: List[int]) -> Dict[str, Any]:
    """Execute cleanup for multiple approved candidates."""
    results = {"success": 0, "failed": 0, "details": []}

    for cid in candidate_ids:
        result = execute_cleanup(cid)
        if result.get("success"):
            results["success"] += 1
        else:
            results["failed"] += 1
        results["details"].append({"id": cid, **result})

    logger.info(f"Bulk execute: {results['success']} success, {results['failed']} failed")
    return results


def get_cleanup_report() -> Dict[str, Any]:
    """Get summary report of cleanup status."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                status,
                category,
                COUNT(*) as count,
                SUM(file_size_bytes) as total_size_bytes
            FROM platform_cleanup_candidates
            GROUP BY status, category
            ORDER BY status, category
        """
        )

        by_status_category = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT
                status,
                COUNT(*) as count,
                SUM(file_size_bytes) as total_size_bytes
            FROM platform_cleanup_candidates
            GROUP BY status
        """
        )

        by_status = [dict(row) for row in cur.fetchall()]

        # Calculate totals
        total_pending = sum(r["count"] for r in by_status if r["status"] == "pending")
        total_approved = sum(r["count"] for r in by_status if r["status"] == "approved")
        total_executed = sum(r["count"] for r in by_status if r["status"] == "executed")
        total_rejected = sum(r["count"] for r in by_status if r["status"] == "rejected")

        pending_size = sum(r["total_size_bytes"] or 0 for r in by_status if r["status"] == "pending")
        approved_size = sum(r["total_size_bytes"] or 0 for r in by_status if r["status"] == "approved")

        return {
            "summary": {
                "pending": total_pending,
                "approved": total_approved,
                "executed": total_executed,
                "rejected": total_rejected,
                "pending_size_bytes": pending_size,
                "approved_size_bytes": approved_size,
                "pending_size_mb": round(pending_size / (1024 * 1024), 2),
                "approved_size_mb": round(approved_size / (1024 * 1024), 2),
            },
            "by_status": by_status,
            "by_status_category": by_status_category,
        }
    finally:
        cur.close()
        conn.close()


def scan_and_save() -> Dict[str, Any]:
    """Scan for candidates and save to database."""
    candidates = scan_for_candidates()
    added = add_candidates_to_db(candidates)
    return {"scanned": len(candidates), "added": added, "candidates": candidates}
