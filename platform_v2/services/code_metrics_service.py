"""
Code Metrics Service
====================
Scans the platform codebase and produces file/line/folder metrics.
Stores snapshots for historical tracking.
"""

import os
import logging
from collections import defaultdict

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Auto-detect: /app/ inside Docker, /mnt/archie_brain/platform_v2/ on host
if os.path.isdir("/app/tools"):
    PLATFORM_ROOT = "/app"
    AI_BRIDGE_ROOT = "/mnt/archie_brain/ai_bridge"
    MIGRATIONS_ROOT = "/mnt/archie_brain/database/migrations"
else:
    PLATFORM_ROOT = "/mnt/archie_brain/platform_v2"
    AI_BRIDGE_ROOT = "/mnt/archie_brain/ai_bridge"
    MIGRATIONS_ROOT = "/mnt/archie_brain/database/migrations"

SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "static/vendor"}

EXT_MAP = {
    ".py": "python",
    ".js": "js",
    ".css": "css",
    ".html": "html",
    ".sql": "sql",
}


def _count_lines(filepath):
    """Count non-empty lines in a file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _scan_directory(root_dir, label=None):
    """Scan a directory tree and return metrics."""
    stats = {
        "files": 0,
        "lines": 0,
        "folders": 0,
        "by_type": defaultdict(lambda: {"files": 0, "lines": 0}),
    }

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip excluded dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        stats["folders"] += 1

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in EXT_MAP and ext not in (".md", ".json", ".yml", ".yaml", ".sh", ".conf"):
                continue

            filepath = os.path.join(dirpath, fname)
            lines = _count_lines(filepath)
            file_type = EXT_MAP.get(ext, "other")

            stats["files"] += 1
            stats["lines"] += lines
            stats["by_type"][file_type]["files"] += 1
            stats["by_type"][file_type]["lines"] += lines

    return stats


def _get_module_stats():
    """Get per-module breakdown from platform_v2/tools/."""
    tools_dir = os.path.join(PLATFORM_ROOT, "tools")
    modules = {}

    if not os.path.isdir(tools_dir):
        return modules

    for entry in sorted(os.listdir(tools_dir)):
        module_path = os.path.join(tools_dir, entry)
        if not os.path.isdir(module_path) or entry.startswith("_"):
            continue

        stats = _scan_directory(module_path, label=entry)
        modules[entry] = {
            "files": stats["files"],
            "lines": stats["lines"],
            "folders": stats["folders"],
            "by_type": {k: dict(v) for k, v in stats["by_type"].items()},
        }

    return modules


def scan_codebase():
    """
    Full codebase scan. Returns comprehensive metrics dict.
    """
    # Scan main areas
    platform_stats = _scan_directory(PLATFORM_ROOT)
    bridge_stats = _scan_directory(AI_BRIDGE_ROOT)
    migration_stats = _scan_directory(MIGRATIONS_ROOT)

    # Per-module breakdown
    module_stats = _get_module_stats()

    # Aggregate totals
    total_files = platform_stats["files"] + bridge_stats["files"] + migration_stats["files"]
    total_lines = platform_stats["lines"] + bridge_stats["lines"] + migration_stats["lines"]
    total_folders = platform_stats["folders"] + bridge_stats["folders"] + migration_stats["folders"]

    # Type breakdowns (aggregate)
    type_totals = defaultdict(lambda: {"files": 0, "lines": 0})
    for stats in [platform_stats, bridge_stats, migration_stats]:
        for ftype, counts in stats["by_type"].items():
            type_totals[ftype]["files"] += counts["files"]
            type_totals[ftype]["lines"] += counts["lines"]

    result = {
        "total_files": total_files,
        "total_lines": total_lines,
        "total_folders": total_folders,
        "python": dict(type_totals.get("python", {"files": 0, "lines": 0})),
        "js": dict(type_totals.get("js", {"files": 0, "lines": 0})),
        "css": dict(type_totals.get("css", {"files": 0, "lines": 0})),
        "html": dict(type_totals.get("html", {"files": 0, "lines": 0})),
        "sql": dict(type_totals.get("sql", {"files": 0, "lines": 0})),
        "areas": {
            "platform": {"files": platform_stats["files"], "lines": platform_stats["lines"]},
            "ai_bridge": {"files": bridge_stats["files"], "lines": bridge_stats["lines"]},
            "migrations": {"files": migration_stats["files"], "lines": migration_stats["lines"]},
        },
        "modules": module_stats,
    }

    return result


def save_snapshot(metrics=None):
    """Scan codebase and save a snapshot to the database."""
    if metrics is None:
        metrics = scan_codebase()

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO code_metrics_snapshots
                       (total_files, total_lines, total_folders,
                        python_files, python_lines, js_files, js_lines,
                        css_files, css_lines, html_files, html_lines,
                        sql_files, sql_lines, per_module)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    metrics["total_files"],
                    metrics["total_lines"],
                    metrics["total_folders"],
                    metrics["python"]["files"],
                    metrics["python"]["lines"],
                    metrics["js"]["files"],
                    metrics["js"]["lines"],
                    metrics["css"]["files"],
                    metrics["css"]["lines"],
                    metrics["html"]["files"],
                    metrics["html"]["lines"],
                    metrics["sql"]["files"],
                    metrics["sql"]["lines"],
                    __import__("json").dumps(metrics["modules"]),
                ),
            )
            snapshot_id = cur.fetchone()["id"]
            logger.info(
                "Saved code metrics snapshot #%d: %d files, %d lines",
                snapshot_id,
                metrics["total_files"],
                metrics["total_lines"],
            )
            return snapshot_id
    except Exception as e:
        logger.error("Failed to save metrics snapshot: %s", e)
        return None


def get_snapshots(limit=30):
    """Return recent metrics snapshots for charting."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, total_files, total_lines, total_folders,
                      python_files, python_lines, js_files, js_lines,
                      css_files, css_lines, html_files, html_lines,
                      sql_files, sql_lines, per_module, scanned_at
               FROM code_metrics_snapshots
               ORDER BY scanned_at DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            if hasattr(r.get("scanned_at"), "isoformat"):
                r["scanned_at"] = r["scanned_at"].isoformat()
            result.append(r)
        return result


def get_audit_log():
    """Return all audit entries."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, module_name, category, files_reviewed,
                      lines_before, lines_after, issues_found, issues_fixed,
                      notes, status, audited_at
               FROM code_audit_log ORDER BY audited_at DESC"""
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            r = dict(row)
            if hasattr(r.get("audited_at"), "isoformat"):
                r["audited_at"] = r["audited_at"].isoformat()
            result.append(r)
        return result


def log_audit(
    module_name,
    category,
    files_reviewed=0,
    lines_before=0,
    lines_after=0,
    issues_found=0,
    issues_fixed=0,
    notes="",
    status="completed",
):
    """Record an audit entry."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO code_audit_log
                   (module_name, category, files_reviewed, lines_before, lines_after,
                    issues_found, issues_fixed, notes, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                module_name,
                category,
                files_reviewed,
                lines_before,
                lines_after,
                issues_found,
                issues_fixed,
                notes,
                status,
            ),
        )
        return cur.fetchone()["id"]
