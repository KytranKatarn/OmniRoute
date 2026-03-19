"""
Code Metrics Service
====================
Scans the platform codebase and produces file/line/folder metrics.
Stores snapshots for historical tracking.
"""

import os
import logging
import subprocess
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
    ".mjs": "js",
    ".css": "css",
    ".html": "html",
    ".sql": "sql",
    ".sh": "shell",
    ".json": "json",
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


def _match_module_name(filename, module_names):
    """Try to match a filename to a module name."""
    base = os.path.splitext(filename)[0].lower()
    # Direct match: security_network.html -> security_network
    if base in module_names:
        return base
    # Hyphen to underscore: google-work-suite.js -> google_work_suite
    underscore = base.replace("-", "_")
    if underscore in module_names:
        return underscore
    # Partial match: consciousness.js -> consciousness
    for mod in module_names:
        if base == mod or underscore == mod:
            return mod
    return None


def _get_module_stats():
    """Get per-module breakdown including templates, JS, and CSS files."""
    tools_dir = os.path.join(PLATFORM_ROOT, "tools")
    templates_dir = os.path.join(PLATFORM_ROOT, "templates", "tools")
    js_dir = os.path.join(PLATFORM_ROOT, "static", "js")
    css_dir = os.path.join(PLATFORM_ROOT, "static", "css")

    modules = {}

    if not os.path.isdir(tools_dir):
        return modules

    # Step 1: Scan Python files in each module directory
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

    module_names = set(modules.keys())

    # Step 2: Map template HTML files to modules
    if os.path.isdir(templates_dir):
        for fname in os.listdir(templates_dir):
            if not fname.endswith(".html"):
                continue
            mod = _match_module_name(fname, module_names)
            if mod and mod in modules:
                lines = _count_lines(os.path.join(templates_dir, fname))
                modules[mod]["files"] += 1
                modules[mod]["lines"] += lines
                if "html" not in modules[mod]["by_type"]:
                    modules[mod]["by_type"]["html"] = {"files": 0, "lines": 0}
                modules[mod]["by_type"]["html"]["files"] += 1
                modules[mod]["by_type"]["html"]["lines"] += lines

    # Step 3: Map static JS files to modules
    if os.path.isdir(js_dir):
        for fname in os.listdir(js_dir):
            if not fname.endswith(".js"):
                continue
            mod = _match_module_name(fname, module_names)
            if mod and mod in modules:
                lines = _count_lines(os.path.join(js_dir, fname))
                modules[mod]["files"] += 1
                modules[mod]["lines"] += lines
                if "js" not in modules[mod]["by_type"]:
                    modules[mod]["by_type"]["js"] = {"files": 0, "lines": 0}
                modules[mod]["by_type"]["js"]["files"] += 1
                modules[mod]["by_type"]["js"]["lines"] += lines

    # Step 4: Map static CSS files to modules
    if os.path.isdir(css_dir):
        for fname in os.listdir(css_dir):
            if not fname.endswith(".css"):
                continue
            mod = _match_module_name(fname, module_names)
            if mod and mod in modules:
                lines = _count_lines(os.path.join(css_dir, fname))
                modules[mod]["files"] += 1
                modules[mod]["lines"] += lines
                if "css" not in modules[mod]["by_type"]:
                    modules[mod]["by_type"]["css"] = {"files": 0, "lines": 0}
                modules[mod]["by_type"]["css"]["files"] += 1
                modules[mod]["by_type"]["css"]["lines"] += lines

    # Step 5: Also scan module-local templates (e.g. consciousness/templates/)
    for mod in list(modules.keys()):
        local_templates = os.path.join(tools_dir, mod, "templates")
        if os.path.isdir(local_templates):
            for fname in os.listdir(local_templates):
                if not fname.endswith(".html"):
                    continue
                lines = _count_lines(os.path.join(local_templates, fname))
                modules[mod]["files"] += 1
                modules[mod]["lines"] += lines
                if "html" not in modules[mod]["by_type"]:
                    modules[mod]["by_type"]["html"] = {"files": 0, "lines": 0}
                modules[mod]["by_type"]["html"]["files"] += 1
                modules[mod]["by_type"]["html"]["lines"] += lines

    # Remove empty modules (like 'static' with 0 lines)
    modules = {k: v for k, v in modules.items() if v["lines"] > 0}

    # Step 6: Add "app_core" — root-level platform files (login, dashboard, rbac, etc.)
    core_files = [
        "app.py",
        "rbac.py",
        "oauth_routes.py",
        "dashboard_generator.py",
        "module_registry.py",
        "database.py",
        "logging_config.py",
    ]
    core_stats = {"files": 0, "lines": 0, "folders": 0, "by_type": {}}
    for fname in core_files:
        fpath = os.path.join(PLATFORM_ROOT, fname)
        if os.path.isfile(fpath):
            lines = _count_lines(fpath)
            core_stats["files"] += 1
            core_stats["lines"] += lines
            if "python" not in core_stats["by_type"]:
                core_stats["by_type"]["python"] = {"files": 0, "lines": 0}
            core_stats["by_type"]["python"]["files"] += 1
            core_stats["by_type"]["python"]["lines"] += lines

    # Add core templates (login, dashboard, base, etc.)
    core_templates = os.path.join(PLATFORM_ROOT, "templates")
    if os.path.isdir(core_templates):
        for fname in os.listdir(core_templates):
            fpath = os.path.join(core_templates, fname)
            if os.path.isfile(fpath) and fname.endswith(".html"):
                lines = _count_lines(fpath)
                core_stats["files"] += 1
                core_stats["lines"] += lines
                if "html" not in core_stats["by_type"]:
                    core_stats["by_type"]["html"] = {"files": 0, "lines": 0}
                core_stats["by_type"]["html"]["files"] += 1
                core_stats["by_type"]["html"]["lines"] += lines

    # Add template includes (nav bars, theme controls)
    includes_dir = os.path.join(PLATFORM_ROOT, "templates", "includes")
    if os.path.isdir(includes_dir):
        for fname in os.listdir(includes_dir):
            fpath = os.path.join(includes_dir, fname)
            if os.path.isfile(fpath) and fname.endswith(".html"):
                lines = _count_lines(fpath)
                core_stats["files"] += 1
                core_stats["lines"] += lines
                if "html" not in core_stats["by_type"]:
                    core_stats["by_type"]["html"] = {"files": 0, "lines": 0}
                core_stats["by_type"]["html"]["files"] += 1
                core_stats["by_type"]["html"]["lines"] += lines

    # Add services layer
    services_dir = os.path.join(PLATFORM_ROOT, "services")
    if os.path.isdir(services_dir):
        svc_stats = _scan_directory(services_dir)
        core_stats["files"] += svc_stats["files"]
        core_stats["lines"] += svc_stats["lines"]
        for ftype, counts in svc_stats["by_type"].items():
            if ftype not in core_stats["by_type"]:
                core_stats["by_type"][ftype] = {"files": 0, "lines": 0}
            core_stats["by_type"][ftype]["files"] += counts["files"]
            core_stats["by_type"][ftype]["lines"] += counts["lines"]

    # Add core static CSS files (base, login, signup, dashboard, etc.)
    core_css = [
        "base.css",
        "login.css",
        "signup.css",
        "dashboard.css",
        "dev-hq.css",
        "verify-2fa.css",
        "competitors.css",
        "directory.css",
        "components.css",
        "animations.css",
        "theme.css",
        "light-mode.css",
        "mobile.css",
        "lcars-panels.css",
        "lcars-frames.css",
        "category-nav.css",
        "station-ops.css",
        "glass-nav.css",
        "holo-sphere.css",
        "neural-core.css",
        "pixel-crew.css",
        "admin-ops.css",
        "agent-badge.css",
        "ops-alert-bar.css",
        "dual-chat.css",
        "xterm.css",
    ]
    css_dir = os.path.join(PLATFORM_ROOT, "static", "css")
    if os.path.isdir(css_dir):
        for fname in core_css:
            fpath = os.path.join(css_dir, fname)
            if os.path.isfile(fpath):
                lines = _count_lines(fpath)
                core_stats["files"] += 1
                core_stats["lines"] += lines
                if "css" not in core_stats["by_type"]:
                    core_stats["by_type"]["css"] = {"files": 0, "lines": 0}
                core_stats["by_type"]["css"]["files"] += 1
                core_stats["by_type"]["css"]["lines"] += lines

    # Add core static JS files (base, login, signup, dashboard, etc.)
    core_js = [
        "base.js",
        "login.js",
        "signup.js",
        "dashboard.js",
        "verify-2fa.js",
        "directory.js",
        "archie-time.js",
        "archie-i18n.js",
        "archie-theme.js",
        "station-ops.js",
        "glass-nav.js",
        "holo-sphere.js",
        "neural-core.js",
        "pixel-crew.js",
        "agent-badge.js",
        "ops-alert-bar.js",
        "collaboration.js",
        "competitors-i18n.js",
        "devhq.js",
    ]
    js_dir = os.path.join(PLATFORM_ROOT, "static", "js")
    if os.path.isdir(js_dir):
        for fname in core_js:
            fpath = os.path.join(js_dir, fname)
            if os.path.isfile(fpath):
                lines = _count_lines(fpath)
                core_stats["files"] += 1
                core_stats["lines"] += lines
                if "js" not in core_stats["by_type"]:
                    core_stats["by_type"]["js"] = {"files": 0, "lines": 0}
                core_stats["by_type"]["js"]["files"] += 1
                core_stats["by_type"]["js"]["lines"] += lines

    if core_stats["lines"] > 0:
        modules["[APP_CORE]"] = core_stats

    # Step 7: Add "ai_bridge" — the AI routing/orchestration layer
    bridge_dir = AI_BRIDGE_ROOT
    if os.path.isdir(bridge_dir):
        bridge_stats = _scan_directory(bridge_dir)
        if bridge_stats["lines"] > 0:
            modules["[AI_BRIDGE]"] = {
                "files": bridge_stats["files"],
                "lines": bridge_stats["lines"],
                "folders": bridge_stats["folders"],
                "by_type": {k: dict(v) for k, v in bridge_stats["by_type"].items()},
            }

    # Step 8: Add "migrations" — database schema
    mig_dir = MIGRATIONS_ROOT
    if os.path.isdir(mig_dir):
        mig_stats = _scan_directory(mig_dir)
        if mig_stats["lines"] > 0:
            modules["[MIGRATIONS]"] = {
                "files": mig_stats["files"],
                "lines": mig_stats["lines"],
                "folders": mig_stats["folders"],
                "by_type": {k: dict(v) for k, v in mig_stats["by_type"].items()},
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

    # Per-module breakdown (includes [APP_CORE], [AI_BRIDGE], [MIGRATIONS])
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
        "shell": dict(type_totals.get("shell", {"files": 0, "lines": 0})),
        "json": dict(type_totals.get("json", {"files": 0, "lines": 0})),
        "areas": {
            "platform": {"files": platform_stats["files"], "lines": platform_stats["lines"]},
            "ai_bridge": {"files": bridge_stats["files"], "lines": bridge_stats["lines"]},
            "migrations": {"files": migration_stats["files"], "lines": migration_stats["lines"]},
        },
        "modules": module_stats,
        "orphans": _find_orphan_files(set(module_stats.keys())),
    }

    # Add [SHARED] — everything not claimed by any module, with proper type breakdown
    module_lines = sum(v["lines"] for v in module_stats.values())
    module_files = sum(v["files"] for v in module_stats.values())
    shared_lines = total_lines - module_lines
    shared_files = total_files - module_files
    if shared_lines > 0:
        # Calculate per-type breakdown for shared (total type - sum of module types)
        shared_by_type = {}
        for ftype in ["python", "js", "css", "html", "sql", "shell", "json"]:
            total_t = type_totals.get(ftype, {"files": 0, "lines": 0})
            mod_t_files = sum(v.get("by_type", {}).get(ftype, {}).get("files", 0) for v in module_stats.values())
            mod_t_lines = sum(v.get("by_type", {}).get(ftype, {}).get("lines", 0) for v in module_stats.values())
            rem_files = total_t["files"] - mod_t_files
            rem_lines = total_t["lines"] - mod_t_lines
            if rem_lines > 0:
                shared_by_type[ftype] = {"files": max(rem_files, 0), "lines": rem_lines}
        # Any remaining goes to other
        typed_lines = sum(v["lines"] for v in shared_by_type.values())
        if shared_lines > typed_lines:
            shared_by_type["other"] = {
                "files": max(shared_files - sum(v["files"] for v in shared_by_type.values()), 0),
                "lines": shared_lines - typed_lines,
            }
        result["modules"]["[SHARED]"] = {
            "files": max(shared_files, 0),
            "lines": shared_lines,
            "folders": 0,
            "by_type": shared_by_type,
        }

    return result


def _find_orphan_files(module_names):
    """Find template, JS, and CSS files that don't map to any module."""
    templates_dir = os.path.join(PLATFORM_ROOT, "templates", "tools")
    js_dir = os.path.join(PLATFORM_ROOT, "static", "js")
    css_dir = os.path.join(PLATFORM_ROOT, "static", "css")

    # Files claimed by APP_CORE — not orphans
    shared_files = {
        # Core JS
        "base.js",
        "login.js",
        "signup.js",
        "dashboard.js",
        "verify-2fa.js",
        "directory.js",
        "archie-time.js",
        "archie-i18n.js",
        "archie-theme.js",
        "station-ops.js",
        "glass-nav.js",
        "holo-sphere.js",
        "neural-core.js",
        "pixel-crew.js",
        "agent-badge.js",
        "ops-alert-bar.js",
        "collaboration.js",
        "competitors-i18n.js",
        "devhq.js",
        # Core CSS
        "base.css",
        "login.css",
        "signup.css",
        "dashboard.css",
        "dev-hq.css",
        "verify-2fa.css",
        "competitors.css",
        "directory.css",
        "components.css",
        "animations.css",
        "theme.css",
        "light-mode.css",
        "mobile.css",
        "lcars-panels.css",
        "lcars-frames.css",
        "category-nav.css",
        "station-ops.css",
        "glass-nav.css",
        "holo-sphere.css",
        "neural-core.css",
        "pixel-crew.css",
        "admin-ops.css",
        "agent-badge.css",
        "ops-alert-bar.css",
        "dual-chat.css",
        "xterm.css",
        # Core HTML
        "base.html",
    }

    orphans = {"templates": [], "js": [], "css": []}

    if os.path.isdir(templates_dir):
        for fname in sorted(os.listdir(templates_dir)):
            if not fname.endswith(".html") or fname in shared_files:
                continue
            mod = _match_module_name(fname, module_names)
            if not mod:
                lines = _count_lines(os.path.join(templates_dir, fname))
                orphans["templates"].append({"file": fname, "lines": lines})

    if os.path.isdir(js_dir):
        for fname in sorted(os.listdir(js_dir)):
            if not fname.endswith(".js") or fname in shared_files:
                continue
            mod = _match_module_name(fname, module_names)
            if not mod:
                lines = _count_lines(os.path.join(js_dir, fname))
                orphans["js"].append({"file": fname, "lines": lines})

    if os.path.isdir(css_dir):
        for fname in sorted(os.listdir(css_dir)):
            if not fname.endswith(".css") or fname in shared_files:
                continue
            mod = _match_module_name(fname, module_names)
            if not mod:
                lines = _count_lines(os.path.join(css_dir, fname))
                orphans["css"].append({"file": fname, "lines": lines})

    return orphans


def _get_commit_hash(repo_path="/mnt/archie_brain"):
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def save_snapshot(metrics=None):
    """Scan codebase and save a snapshot to the database."""
    if metrics is None:
        metrics = scan_codebase()

    commit_hash = _get_commit_hash()

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO code_metrics_snapshots
                       (total_files, total_lines, total_folders,
                        python_files, python_lines, js_files, js_lines,
                        css_files, css_lines, html_files, html_lines,
                        sql_files, sql_lines, per_module, commit_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    commit_hash,
                ),
            )
            snapshot_id = cur.fetchone()["id"]
            logger.info(
                "Saved code metrics snapshot #%d: %d files, %d lines (commit %s)",
                snapshot_id,
                metrics["total_files"],
                metrics["total_lines"],
                commit_hash[:8] if commit_hash else "unknown",
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


def backfill_git_history(repo_path="/mnt/archie_brain"):
    """
    Walk full git history and create daily snapshots.
    Tracks both line changes (--numstat) and file changes (--diff-filter).
    """
    import json

    try:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", repo_path],
            capture_output=True,
            timeout=5,
        )

        # Get line changes per commit (full history)
        result = subprocess.run(
            ["git", "log", "--numstat", "--format=%ad", "--date=short"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return {"error": result.stderr}

        # Get file additions/deletions per commit (full history)
        file_result = subprocess.run(
            ["git", "log", "--diff-filter=AD", "--summary", "--format=%ad", "--date=short"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Parse line changes
        daily = defaultdict(lambda: {"added": 0, "removed": 0, "commits": 0, "files_added": 0, "files_deleted": 0})
        current_date = None

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(line) == 10 and line[4] == "-" and line[7] == "-":
                current_date = line
                daily[current_date]["commits"] += 1
                continue
            parts = line.split("\t")
            if len(parts) == 3 and current_date:
                try:
                    a = int(parts[0]) if parts[0] != "-" else 0
                    r = int(parts[1]) if parts[1] != "-" else 0
                    daily[current_date]["added"] += a
                    daily[current_date]["removed"] += r
                except ValueError:
                    pass

        # Parse file additions/deletions
        current_date = None
        if file_result.returncode == 0:
            for line in file_result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if len(line) == 10 and line[4] == "-" and line[7] == "-":
                    current_date = line
                    continue
                if current_date:
                    if line.startswith("create mode"):
                        daily[current_date]["files_added"] += 1
                    elif line.startswith("delete mode"):
                        daily[current_date]["files_deleted"] += 1

        if not daily:
            return {"error": "No git history found", "days": 0}

        sorted_dates = sorted(daily.keys())

        # Get current totals as baseline
        current = scan_codebase()
        current_total = current["total_lines"]
        current_files = current["total_files"]

        # Calculate cumulative line delta
        total_line_delta = sum(daily[d]["added"] - daily[d]["removed"] for d in sorted_dates)
        base_lines = current_total - total_line_delta

        # Calculate cumulative file delta
        total_file_delta = sum(daily[d]["files_added"] - daily[d]["files_deleted"] for d in sorted_dates)
        base_files = current_files - total_file_delta

        # Build timeline
        timeline = []
        running_lines = base_lines
        running_files = base_files

        for date in sorted_dates:
            d = daily[date]
            running_lines += d["added"] - d["removed"]
            running_files += d["files_added"] - d["files_deleted"]
            timeline.append(
                {
                    "date": date,
                    "total_lines": max(running_lines, 0),
                    "total_files": max(running_files, 0),
                    "added": d["added"],
                    "removed": d["removed"],
                    "files_added": d["files_added"],
                    "files_deleted": d["files_deleted"],
                    "commits": d["commits"],
                }
            )

        # Clear old backfill data and re-insert (keeps today's full scan)
        inserted = 0
        with get_db_cursor(commit=True) as (conn, cur):
            # Delete old git-backfilled rows (keep today's full scan)
            cur.execute(
                "DELETE FROM code_metrics_snapshots WHERE total_folders = 0 AND scanned_at::date < CURRENT_DATE"
            )

            for entry in timeline:
                cur.execute(
                    "SELECT id FROM code_metrics_snapshots WHERE scanned_at::date = %s",
                    (entry["date"],),
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    """INSERT INTO code_metrics_snapshots
                           (total_files, total_lines, total_folders,
                            python_files, python_lines, js_files, js_lines,
                            css_files, css_lines, html_files, html_lines,
                            sql_files, sql_lines, per_module, scanned_at)
                       VALUES (%s, %s, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, %s, %s)""",
                    (
                        entry["total_files"],
                        entry["total_lines"],
                        json.dumps(
                            {
                                "git_daily": {
                                    "added": entry["added"],
                                    "removed": entry["removed"],
                                    "files_added": entry["files_added"],
                                    "files_deleted": entry["files_deleted"],
                                    "commits": entry["commits"],
                                }
                            }
                        ),
                        entry["date"],
                    ),
                )
                inserted += 1

        logger.info("Backfilled %d days of git history (%d total)", inserted, len(timeline))
        return {"success": True, "days": len(timeline), "inserted": inserted}
    except Exception as e:
        logger.error("backfill_git_history failed: %s", e)
        return {"error": str(e)}
