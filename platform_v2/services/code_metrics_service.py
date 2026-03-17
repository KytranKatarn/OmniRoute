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


def backfill_git_history(repo_path="/mnt/archie_brain", days=90):
    """
    Walk git log and create daily snapshots from commit history.
    Uses git log --numstat to calculate cumulative lines per day.
    """
    import subprocess
    import json
    from datetime import datetime, timedelta

    try:
        # Ensure git trusts the repo directory (needed inside Docker)
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", repo_path],
            capture_output=True,
            timeout=5,
        )

        # Get daily insertions/deletions from git log
        result = subprocess.run(
            [
                "git",
                "log",
                "--numstat",
                "--format=%ad",
                "--date=short",
                "--since",
                f"{days} days ago",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.error("git log failed: %s", result.stderr)
            return {"error": result.stderr}

        # Parse git log output into daily totals
        daily = defaultdict(lambda: {"added": 0, "removed": 0, "commits": 0})
        current_date = None

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Date line (YYYY-MM-DD)
            if len(line) == 10 and line[4] == "-" and line[7] == "-":
                current_date = line
                daily[current_date]["commits"] += 1
                continue
            # Numstat line: added\tremoved\tfile
            parts = line.split("\t")
            if len(parts) == 3 and current_date:
                try:
                    added = int(parts[0]) if parts[0] != "-" else 0
                    removed = int(parts[1]) if parts[1] != "-" else 0
                    daily[current_date]["added"] += added
                    daily[current_date]["removed"] += removed
                except ValueError:
                    pass

        if not daily:
            return {"error": "No git history found", "days": 0}

        # Build cumulative timeline
        sorted_dates = sorted(daily.keys())

        # Get current total as baseline and work backwards
        current = scan_codebase()
        current_total = current["total_lines"]
        current_files = current["total_files"]

        # Calculate cumulative by working backwards from today
        timeline = []
        cumulative_lines = current_total
        cumulative_delta = 0

        # First pass: sum all deltas from oldest to newest
        for date in sorted_dates:
            d = daily[date]
            cumulative_delta += d["added"] - d["removed"]

        # Now work forward, starting from (current - total_delta)
        base_lines = current_total - cumulative_delta
        running = base_lines

        for date in sorted_dates:
            d = daily[date]
            net = d["added"] - d["removed"]
            running += net
            timeline.append(
                {
                    "date": date,
                    "total_lines": running,
                    "added": d["added"],
                    "removed": d["removed"],
                    "net": net,
                    "commits": d["commits"],
                }
            )

        # Store as snapshots in DB (one per day, skip if already exists)
        inserted = 0
        with get_db_cursor(commit=True) as (conn, cur):
            for entry in timeline:
                cur.execute(
                    "SELECT id FROM code_metrics_snapshots WHERE scanned_at::date = %s",
                    (entry["date"],),
                )
                if cur.fetchone():
                    continue  # Already have this day

                cur.execute(
                    """INSERT INTO code_metrics_snapshots
                           (total_files, total_lines, total_folders,
                            python_files, python_lines, js_files, js_lines,
                            css_files, css_lines, html_files, html_lines,
                            sql_files, sql_lines, per_module, scanned_at)
                       VALUES (%s, %s, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, %s, %s)""",
                    (
                        current_files,
                        entry["total_lines"],
                        json.dumps(
                            {
                                "git_daily": {
                                    "added": entry["added"],
                                    "removed": entry["removed"],
                                    "commits": entry["commits"],
                                }
                            }
                        ),
                        entry["date"],
                    ),
                )
                inserted += 1

        logger.info("Backfilled %d days of git history (%d total days found)", inserted, len(timeline))
        return {"success": True, "days": len(timeline), "inserted": inserted, "timeline": timeline}
    except Exception as e:
        logger.error("backfill_git_history failed: %s", e)
        return {"error": str(e)}
