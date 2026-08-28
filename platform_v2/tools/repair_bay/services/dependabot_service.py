"""Dependabot alert polling, manifest discovery, and repair queue ingestion."""

import os
import logging
from typing import Dict, List

from database import get_db_cursor
from tools.repair_bay.services.github_service import get_dependabot_alerts

logger = logging.getLogger(__name__)

MANIFEST_PATTERNS = {
    "requirements.txt": "pip",
    "pyproject.toml": "pip",
    "package.json": "npm",
    "go.mod": "go",
    "Gemfile": "ruby",
    "Cargo.toml": "cargo",
}

REPO_ROOT = "/mnt/archie_brain"


def discover_manifests(root_path: str = REPO_ROOT) -> List[Dict]:
    """Walk the repo and find all dependency manifest files."""
    manifests = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox"}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            if fname in MANIFEST_PATTERNS:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root_path)
                manifests.append(
                    {
                        "file_path": rel_path,
                        "manifest_type": MANIFEST_PATTERNS[fname],
                    }
                )
    return manifests


def sync_manifest_registry(manifests: List[Dict] = None) -> Dict:
    """Update manifest_registry table with discovered manifests."""
    if manifests is None:
        manifests = discover_manifests()
    with get_db_cursor(commit=True) as (conn, cur):
        for m in manifests:
            cur.execute(
                """INSERT INTO manifest_registry (file_path, manifest_type)
                   VALUES (%s, %s)
                   ON CONFLICT (file_path) DO UPDATE SET last_scanned_at = NOW()""",
                (m["file_path"], m["manifest_type"]),
            )
    return {"success": True, "count": len(manifests)}


def poll_and_ingest() -> Dict:
    """Poll Dependabot API and ingest new alerts into repair_queue."""
    alerts_result = get_dependabot_alerts(state="open")
    if not alerts_result["success"]:
        logger.error("Dependabot poll failed: %s", alerts_result.get("error"))
        return {"success": False, "error": alerts_result.get("error")}

    new_count = 0
    skipped = 0

    with get_db_cursor(commit=True) as (conn, cur):
        for alert in alerts_result["alerts"]:
            cur.execute(
                "SELECT id FROM repair_queue WHERE source = 'dependabot' AND alert_number = %s",
                (alert["number"],),
            )
            if cur.fetchone():
                skipped += 1
                continue

            cur.execute(
                """INSERT INTO repair_queue
                   (source, severity, package_name, manifest_path,
                    alert_number, advisory_id, vulnerable_range, fix_version, status)
                   VALUES ('dependabot', %s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (
                    alert["severity"],
                    alert["package_name"],
                    alert["manifest_path"],
                    alert["number"],
                    alert["advisory_id"],
                    alert["vulnerable_range"],
                    alert["fix_version"],
                ),
            )
            new_count += 1

    logger.info("Dependabot poll: %d new, %d skipped", new_count, skipped)
    return {
        "success": True,
        "new_alerts": new_count,
        "skipped": skipped,
        "total_polled": alerts_result["count"],
    }


def get_repair_queue(status: str = None, severity: str = None, source: str = None) -> Dict:
    """Fetch repair queue entries with optional filters."""
    query = "SELECT * FROM repair_queue WHERE 1=1"
    params = []
    if status:
        query += " AND status = %s"
        params.append(status)
    if severity:
        query += " AND severity = %s"
        params.append(severity)
    if source:
        query += " AND source = %s"
        params.append(source)
    query += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC"

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
    return {"success": True, "items": rows, "count": len(rows)}


def update_repair_item(item_id: int, **fields) -> Dict:
    """Update a repair queue item."""
    allowed = {"status", "assigned_agent", "pr_number", "attempts", "dismiss_reason", "last_attempt_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return {"success": False, "error": "No valid fields to update"}

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [item_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE repair_queue SET {set_clause}, updated_at = NOW() WHERE id = %s",
            values,
        )
    return {"success": True, "id": item_id}
