"""
Code Metrics Service
====================
Scans the platform codebase and produces file/line/folder metrics.
Stores snapshots for historical tracking.
"""

import json
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
    # Standalone products: prefer /mnt/standalone if mounted, fall back to /mnt/archie_brain
    STANDALONE_BASE = "/mnt/standalone" if os.path.isdir("/mnt/standalone") else "/mnt/archie_brain"
    # Websites: prefer /mnt/standalone/websites, fall back to /mnt/archie_brain/website
    WEBSITE_BASE = (
        "/mnt/standalone/websites" if os.path.isdir("/mnt/standalone/websites") else "/mnt/archie_brain/website"
    )
else:
    PLATFORM_ROOT = "/mnt/archie_brain/platform_v2"
    AI_BRIDGE_ROOT = "/mnt/archie_brain/ai_bridge"
    MIGRATIONS_ROOT = "/mnt/archie_brain/database/migrations"
    STANDALONE_BASE = "/mnt/standalone" if os.path.isdir("/mnt/standalone") else "/mnt/archie_brain"
    WEBSITE_BASE = (
        "/mnt/standalone/websites" if os.path.isdir("/mnt/standalone/websites") else "/mnt/archie_brain/website"
    )

# Repo root — same path inside the container and on the host (AI_BRIDGE_ROOT and
# MIGRATIONS_ROOT above already rely on it being mounted). Holds the ROOT
# docker-compose.yml that builds several standalones as services of the main stack.
BRAIN_ROOT = "/mnt/archie_brain"

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
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".go": "go",
    ".svg": "svg",
    ".conf": "config",
    ".toml": "config",
    ".ini": "config",
    ".xml": "config",
    ".txt": "text",
}

# Standalone products tracked in Code Health (see .claude/rules/standalone-extraction.md)
# dir_name is relative to STANDALONE_BASE; path is computed at scan time
_STANDALONE_DEFS = [
    {
        "name": "Kytran System Operations",
        "dir_name": "kytran-server-manager",
        "module_key": "standalone_kytran_system_operations",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu", "hipaa"],
    },
    {
        "name": "Kytran Business Suite",
        "dir_name": "kytran-business-suite",
        "module_key": "standalone_kytran_business_suite",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu", "hipaa"],
    },
    {
        "name": "Kytran Civic Watch",
        "dir_name": "kytran-civic-watch",
        "module_key": "standalone_kytran_civic_watch",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu"],
    },
    {
        "name": "Kytran Legal Watch",
        "dir_name": "kytran-legal-watch",
        "module_key": "standalone_kytran_legal_watch",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu"],
    },
    {
        "name": "Kytran Market Watch",
        "dir_name": "kytran-market-watch",
        "module_key": "standalone_kytran_market_watch",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu"],
    },
    {
        "name": "Kytran Gov Watch",
        "dir_name": "kytran-gov-watch",
        "module_key": "standalone_kytran_gov_watch",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu"],
    },
    {
        "name": "C.R.E.E.D. Governance Platform",
        "dir_name": "kytran-creed",
        "module_key": "standalone_creed_governance",
        "tier": 2,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu"],
    },
    {
        "name": "What The Fact",
        "dir_name": "what-the-fact",
        "module_key": "standalone_what_the_fact",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig", "network-stig"],
    },
    {
        "name": "A.R.C.H.I.E. Code (CLI)",
        "dir_name": "archie-code",
        "module_key": "standalone_archie_code",
        "tier": 1,
        "type": "cli",  # CLI tool — no Docker, no static
        "compliance_packs": [],
    },
    {
        "name": "A.R.C.H.I.E. Comms",
        "dir_name": "archie-comms",
        "module_key": "standalone_archie_comms",
        "tier": 1,
        "compliance_packs": ["docker-stig"],
    },
    {
        "name": "Media Hub",
        "dir_name": "media_hub",
        "module_key": "standalone_media_hub",
        "tier": 1,
        "compliance_packs": ["ubuntu-stig", "docker-stig"],
    },
]


def _resolve_standalone_path(dir_name):
    """Find standalone product on filesystem, checking multiple known locations."""
    candidates = [
        os.path.join(STANDALONE_BASE, dir_name),
        os.path.join("/mnt/archie_brain", dir_name),
        # Newer standalones live under /mnt/archie_brain/standalone/<dir> — keeps
        # all extraction products co-located (Project #273 onward).
        os.path.join("/mnt/archie_brain/standalone", dir_name),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return os.path.join(STANDALONE_BASE, dir_name)  # default even if missing


STANDALONE_PRODUCTS = [{**d, "path": _resolve_standalone_path(d["dir_name"])} for d in _STANDALONE_DEFS]

# Infrastructure services tracked in Code Health (not customer-facing products)
INFRASTRUCTURE_SERVICES = [
    {
        "name": "Stalwart Mail Server",
        "path": "/mnt/archie_brain/stalwart-mail",
        "module_key": "infra_stalwart_mail",
        "service_type": "mail",
    },
]

# Website products tracked in Code Health (static sites deployed to Hostinger)
_WEBSITE_DEFS = [
    {"name": "kytranempowerment.com", "dir_name": "kytranempowerment.com", "module_key": "website_kytranempowerment"},
    {"name": "creed-ai.org", "dir_name": "creed-ai.org", "module_key": "website_creed_ai"},
    {"name": "What The Fact (.com)", "dir_name": "what-the-fact.com", "module_key": "website_what_the_fact"},
]

WEBSITE_PRODUCTS = [{**d, "path": os.path.join(WEBSITE_BASE, d["dir_name"])} for d in _WEBSITE_DEFS]


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


_STATIC_FILE_MAP = {
    # Game engine files -> game_studio
    "game-engine": "game_studio",
    "game-module-builder": "game_studio",
    "game-module-explorer": "game_studio",
    "game-module-shooter": "game_studio",
    "game-network": "game_studio",
    "scene-editor": "game_studio",
    # Media Hub service worker
    "media-hub-sw": "media_hub",
    # Department HQ assets whose filenames don't start with the module name.
    # All five are loaded by tools/department_hq/templates/department_hq.html —
    # verified by reference, not by naming convention. They were being counted as
    # orphans at -5 each, i.e. the platform's headline health grade was penalising a
    # gap in THIS map rather than anything wrong with the code. (One key covers both
    # extensions: _match_module_name strips the suffix before lookup.)
    "agent_profile_modal": "department_hq",  # .js + .css — the SHARED agent profile modal
    "alerts-history": "department_hq",
    "dispatch-history": "department_hq",
    "scout": "department_hq",  # S.C.O.U.T. tab
}


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
    # Prefix match: consciousness-dashboard-v2 -> consciousness, security-network-app -> security_network
    for mod in sorted(module_names, key=len, reverse=True):
        if underscore.startswith(mod + "_") or underscore.startswith(mod + "-") or underscore == mod:
            return mod
    # Explicit static file map for files that don't follow naming convention
    mapped = _STATIC_FILE_MAP.get(base)
    if mapped and mapped in module_names:
        return mapped
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
        "components.css",
        "animations.css",
        "theme.css",
        "light-mode.css",
        "mobile.css",
        "lcars-panels.css",
        "lcars-frames.css",
        "station-ops.css",
        "department-ops.css",
        "glass-nav.css",
        "holo-sphere.css",
        "neural-core.css",
        "pixel-crew.css",
        "admin-ops.css",
        "agent-badge.css",
        "ops-alert-bar.css",
        "dual-chat.css",
        "xterm.css",
        "system-operations-theme-vars.css",
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
        "archie-time.js",
        "archie-i18n.js",
        "archie-theme.js",
        "station-ops.js",
        "department-ops.js",
        "glass-nav.js",
        "holo-sphere.js",
        "neural-core.js",
        "pixel-crew.js",
        "agent-badge.js",
        "agent-profile.js",
        "ops-alert-bar.js",
        "collaboration.js",
        "competitors-i18n.js",
        "archie-chat-overlay.js",
        "devhq.js",
        "socket.io.min.js",
        "xterm.min.js",
        "xterm-addon-fit.min.js",
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


def _get_standalone_stats():
    """Scan registered standalone products and return metrics."""
    standalone_metrics = {}
    for product in STANDALONE_PRODUCTS:
        path = product["path"]
        if not os.path.isdir(path):
            continue
        stats = {"files": 0, "lines": 0, "folders": 0, "by_type": {}}
        seen_dirs = set()
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git", "venv", ".venv")
            ]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                lang = EXT_MAP.get(ext)
                if lang is None:
                    continue
                filepath = os.path.join(root, f)
                line_count = _count_lines(filepath)
                stats["files"] += 1
                stats["lines"] += line_count
                if lang not in stats["by_type"]:
                    stats["by_type"][lang] = {"files": 0, "lines": 0}
                stats["by_type"][lang]["files"] += 1
                stats["by_type"][lang]["lines"] += line_count
                parent = os.path.dirname(filepath)
                if parent not in seen_dirs:
                    seen_dirs.add(parent)
                    stats["folders"] += 1
        standalone_metrics[product["module_key"]] = stats
    return standalone_metrics


def _get_website_stats():
    """Scan registered website products and return metrics."""
    website_metrics = {}
    for site in WEBSITE_PRODUCTS:
        path = site["path"]
        if not os.path.isdir(path):
            continue
        stats = {"files": 0, "lines": 0, "folders": 0, "by_type": {}}
        seen_dirs = set()
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git", "venv", ".venv")
            ]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                lang = EXT_MAP.get(ext)
                if lang is None:
                    continue
                filepath = os.path.join(root, f)
                line_count = _count_lines(filepath)
                stats["files"] += 1
                stats["lines"] += line_count
                if lang not in stats["by_type"]:
                    stats["by_type"][lang] = {"files": 0, "lines": 0}
                stats["by_type"][lang]["files"] += 1
                stats["by_type"][lang]["lines"] += line_count
                parent = os.path.dirname(filepath)
                if parent not in seen_dirs:
                    seen_dirs.add(parent)
                    stats["folders"] += 1
        website_metrics[site["module_key"]] = stats
    return website_metrics


import time as _time

# In-memory cache for scan results (avoids rescanning filesystem on every page load)
_scan_cache = {"result": None, "timestamp": 0}
_SCAN_CACHE_TTL = 300  # 5 minutes


# The audit `notes` field is the SINGLE SOURCE the UI counts findings from
# (#5881 made the badge, the audit-log table and the details drilldown all derive
# from `_parse_audit_findings(notes)`). It was capped at 30, so the displayed count
# was PINNED at 30 and could not fall until the true count dropped below it --
# a re-audit reporting fewer findings changed nothing on screen (#5926).
# Keep a sane upper bound so one pathological module cannot write an unbounded row.
_NOTES_MAX_FINDINGS = 500


def scan_codebase(force=False):
    """
    Full codebase scan. Returns comprehensive metrics dict.
    Results are cached for 5 minutes to avoid rescanning on every page load.
    Pass force=True to bypass cache (used by scheduled scans / manual trigger).
    """
    if not force and _scan_cache["result"] and (_time.time() - _scan_cache["timestamp"]) < _SCAN_CACHE_TTL:
        return _scan_cache["result"]

    result = _scan_codebase_uncached()
    _scan_cache["result"] = result
    _scan_cache["timestamp"] = _time.time()
    return result


def _scan_codebase_uncached():
    """
    Internal: full codebase scan without caching.
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
        "yaml": dict(type_totals.get("yaml", {"files": 0, "lines": 0})),
        "markdown": dict(type_totals.get("markdown", {"files": 0, "lines": 0})),
        "go": dict(type_totals.get("go", {"files": 0, "lines": 0})),
        "svg": dict(type_totals.get("svg", {"files": 0, "lines": 0})),
        "config": dict(type_totals.get("config", {"files": 0, "lines": 0})),
        "text": dict(type_totals.get("text", {"files": 0, "lines": 0})),
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
        for ftype in [
            "python",
            "js",
            "css",
            "html",
            "sql",
            "shell",
            "json",
            "yaml",
            "markdown",
            "go",
            "svg",
            "config",
            "text",
        ]:
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

    # Scan standalone products
    standalone_stats = _get_standalone_stats()
    for key, stats in standalone_stats.items():
        result["modules"][key] = stats
        result["total_files"] += stats["files"]
        result["total_lines"] += stats["lines"]
        result["total_folders"] += stats["folders"]
        # Add standalone per-language stats to top-level totals
        for lang, lang_stats in stats.get("by_type", {}).items():
            if lang in result:
                result[lang]["files"] += lang_stats.get("files", 0)
                result[lang]["lines"] += lang_stats.get("lines", 0)

    # Scan website products
    website_stats = _get_website_stats()
    for key, stats in website_stats.items():
        result["modules"][key] = stats
        result["total_files"] += stats["files"]
        result["total_lines"] += stats["lines"]
        result["total_folders"] += stats["folders"]
        for lang, lang_stats in stats.get("by_type", {}).items():
            if lang in result:
                result[lang]["files"] += lang_stats.get("files", 0)
                result[lang]["lines"] += lang_stats.get("lines", 0)

    # Structural audits
    result["kbs_audit"] = _audit_kbs_plugins()
    result["standalone_audit"] = _audit_standalone_products()
    result["retired_modules"] = _detect_retired_modules()
    result["health_score"] = _calculate_health_score(result)

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
        "archie-time.js",
        "archie-i18n.js",
        "archie-theme.js",
        "station-ops.js",
        "department-ops.js",
        "glass-nav.js",
        "holo-sphere.js",
        "neural-core.js",
        "pixel-crew.js",
        "agent-badge.js",
        "agent-profile.js",
        "ops-alert-bar.js",
        "collaboration.js",
        "competitors-i18n.js",
        "archie-chat-overlay.js",
        "devhq.js",
        "socket.io.min.js",
        "xterm.min.js",
        "xterm-addon-fit.min.js",
        # Core CSS
        "base.css",
        "login.css",
        "signup.css",
        "dashboard.css",
        "dev-hq.css",
        "verify-2fa.css",
        "competitors.css",
        "components.css",
        "animations.css",
        "theme.css",
        "light-mode.css",
        "mobile.css",
        "lcars-panels.css",
        "lcars-frames.css",
        "station-ops.css",
        "department-ops.css",
        "glass-nav.css",
        "holo-sphere.css",
        "neural-core.css",
        "pixel-crew.css",
        "admin-ops.css",
        "agent-badge.css",
        "ops-alert-bar.css",
        "dual-chat.css",
        "xterm.css",
        "system-operations-theme-vars.css",
        "lcars-header.css",
        "lcars-tokens.css",
        "lcars-modals.css",
        "fleet.css",
        "archie-breakpoints.css",
        "consciousness-dashboard-v2.css",
        "content-studio.css",
        "website-studio.css",
        "stockbot.css",
        "security-network-theme-vars.css",
        # Core JS (shared components + module-specific in static/)
        "lcars-header.js",
        "consciousness-dashboard-v2.js",
        "content-studio.js",
        "website-studio.js",
        "security-network-app.js",
        # APP_CORE page assets — loaded by root templates, not by any module.
        # Verified by reference: platform-chat.js <- templates/dashboard_dynamic.html,
        # subscribe.css <- templates/subscribe.html.
        "platform-chat.js",
        "subscribe.css",
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


# ============================================================================
# STRUCTURAL AUDITS — KBS, Standalones, Retired Modules, Health Score
# ============================================================================

KBS_PLUGINS_ROOT = "/mnt/archie_brain/kytran-business-suite/plugins"
KBS_MANIFEST_REQUIRED = {"slug", "name", "version", "category", "tier_required", "dependencies"}


def _audit_kbs_plugins():
    """Audit KBS plugin structure — verify manifest, routes, migrations, templates."""
    if not os.path.isdir(KBS_PLUGINS_ROOT):
        return {"plugins": [], "issues": [], "total": 0, "healthy": 0}

    plugins = []
    issues = []

    for entry in sorted(os.listdir(KBS_PLUGINS_ROOT)):
        plugin_path = os.path.join(KBS_PLUGINS_ROOT, entry)
        if not os.path.isdir(plugin_path) or entry.startswith("."):
            continue

        plugin = {
            "name": entry,
            "path": plugin_path,
            "has_manifest": False,
            "has_init": False,
            "has_routes": False,
            "has_migrations": False,
            "has_templates": False,
            "has_static": False,
            "has_tests": False,
            "manifest_valid": False,
            "manifest_fields_missing": [],
            "issues": [],
        }

        # Check required files
        manifest_path = os.path.join(plugin_path, "manifest.json")
        if os.path.isfile(manifest_path):
            plugin["has_manifest"] = True
            try:
                import json

                with open(manifest_path) as f:
                    manifest = json.load(f)
                missing = KBS_MANIFEST_REQUIRED - set(manifest.keys())
                if missing:
                    plugin["manifest_fields_missing"] = sorted(missing)
                    plugin["issues"].append(f"manifest missing fields: {', '.join(sorted(missing))}")
                else:
                    plugin["manifest_valid"] = True
            except Exception as exc:
                plugin["issues"].append(f"manifest parse error: {exc}")
        else:
            plugin["issues"].append("missing manifest.json")

        plugin["has_init"] = os.path.isfile(os.path.join(plugin_path, "__init__.py"))
        if not plugin["has_init"]:
            plugin["issues"].append("missing __init__.py")

        plugin["has_routes"] = os.path.isfile(os.path.join(plugin_path, "routes.py"))
        if not plugin["has_routes"]:
            plugin["issues"].append("missing routes.py")

        plugin["has_migrations"] = os.path.isdir(os.path.join(plugin_path, "migrations"))
        plugin["has_templates"] = os.path.isdir(os.path.join(plugin_path, "templates"))
        plugin["has_static"] = os.path.isdir(os.path.join(plugin_path, "static"))
        plugin["has_tests"] = os.path.isdir(os.path.join(plugin_path, "tests"))

        plugins.append(plugin)
        issues.extend([f"[{entry}] {i}" for i in plugin["issues"]])

    healthy = sum(1 for p in plugins if not p["issues"])
    return {
        "plugins": plugins,
        "issues": issues,
        "total": len(plugins),
        "healthy": healthy,
    }


def _has_own_static(path):
    """Check if a product has its own static assets (CSS/JS/templates).

    Checks root and one level of subdirectories to handle Python package
    layouts like kytran_server_manager/kytran_server_manager/static/.
    """
    check_dirs = ("static", "public", "assets", "templates")
    # Check root
    for d in check_dirs:
        if os.path.isdir(os.path.join(path, d)):
            return True
    # Check shared/static (KBS pattern)
    if os.path.isdir(os.path.join(path, "shared", "static")):
        return True
    # Check one level deep (Python package pattern)
    try:
        for entry in os.listdir(path):
            subdir = os.path.join(path, entry)
            if os.path.isdir(subdir) and not entry.startswith(".") and entry not in SKIP_DIRS:
                for d in check_dirs:
                    if os.path.isdir(os.path.join(subdir, d)):
                        return True
    except Exception:
        pass
    return False


def _audit_standalone_products():
    """Audit standalone products against the extraction playbook tiers."""
    results = []
    issues = []

    all_products = (
        [(p, "standalone") for p in STANDALONE_PRODUCTS]
        + [(w, "website") for w in WEBSITE_PRODUCTS]
        + [(s, "infrastructure") for s in INFRASTRUCTURE_SERVICES]
    )

    for product, product_type in all_products:
        path = product["path"]
        name = product["name"]
        exists = os.path.isdir(path)

        audit = {
            "name": name,
            "path": path,
            "type": product_type,
            "exists": exists,
            "tier1": {},
            "issues": [],
        }

        if not exists:
            audit["issues"].append("directory does not exist")
            issues.append(f"[{name}] directory does not exist: {path}")
            results.append(audit)
            continue

        if product_type == "standalone":
            # Tier 1 checks — adapt based on product subtype
            subtype = product.get("type", "webapp")  # webapp, api, cli
            checks = {
                "readme": os.path.isfile(os.path.join(path, "README.md")),
            }
            # Docker checks — skip for CLI tools. Both accept the shapes a real
            # product actually takes: per-service Dockerfile.<name> variants for a
            # multi-container build, and being a service of the ROOT compose instead
            # of carrying a private one.
            if subtype != "cli":
                checks["dockerfile"] = _has_dockerfile(path)
                checks["docker_compose"] = (
                    os.path.isfile(os.path.join(path, "docker-compose.yml"))
                    or os.path.isfile(os.path.join(path, "docker-compose.yaml"))
                    or _built_by_root_compose(path)
                )
            # Health endpoint — skip for CLI tools
            if subtype != "cli":
                checks["health_endpoint"] = _has_health_endpoint(path)
            # Own static — skip for API-only and CLI products
            if subtype not in ("api", "cli"):
                checks["own_static"] = _has_own_static(path)

            audit["tier1"] = checks

            for check_name, passed in checks.items():
                if not passed:
                    label = check_name.replace("_", " ").title()
                    audit["issues"].append(f"Tier 1: missing {label}")
                    issues.append(f"[{name}] Tier 1: missing {label}")

        elif product_type == "website":
            has_index = os.path.isfile(os.path.join(path, "index.html"))
            audit["tier1"] = {"index_html": has_index}
            if not has_index:
                audit["issues"].append("missing index.html")
                issues.append(f"[{name}] missing index.html")

        elif product_type == "infrastructure":
            has_config = (
                os.path.isfile(os.path.join(path, "docker-compose.yml"))
                or os.path.isfile(os.path.join(path, "docker-compose.yaml"))
                or os.path.isfile(os.path.join(path, "config.toml"))
                or os.path.isfile(os.path.join(path, "config.yml"))
            )
            has_readme = os.path.isfile(os.path.join(path, "README.md"))
            audit["tier1"] = {"config": has_config, "readme": has_readme}
            if not has_config:
                audit["issues"].append("missing config/docker-compose")
                issues.append(f"[{name}] missing config/docker-compose")

        results.append(audit)

    healthy = sum(1 for r in results if not r["issues"])
    return {
        "products": results,
        "issues": issues,
        "total": len(results),
        "healthy": healthy,
    }


def _has_health_endpoint(product_path):
    """Check if a product has a health endpoint defined in any routes file.

    Reads each file in full. It previously read only the first 50,000 bytes, which
    made the check a function of file SIZE rather than of whether the endpoint exists:
    What The Fact defines @bp.route("/api/health") at consumer/routes.py:2952 in a
    190,600-byte file, so the route was invisible and the product was reported as
    "Tier 1: missing Health Endpoint" (-5) while serving /api/health in production.
    Scanned line-by-line so a large file costs no more memory than its longest line.
    """
    for root, dirs, files in os.walk(product_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(root, fname)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "/health" in line:
                            return True
            except Exception:
                pass
    return False


def _has_dockerfile(product_path):
    """True when the product ships ANY Dockerfile, including per-service variants.

    A multi-container product names them by service — What The Fact has
    Dockerfile.consumer / .ingest / .tech and no bare `Dockerfile`, because a single
    root Dockerfile would be meaningless for a 3-container build. Matching only the
    exact name reported it as "Tier 1: missing Dockerfile" (-5) while it built and
    deployed three images.
    """
    try:
        return any(f == "Dockerfile" or f.startswith("Dockerfile.") for f in os.listdir(product_path))
    except Exception:
        return False


def _built_by_root_compose(product_path):
    """True when the ROOT docker-compose.yml builds this product as a service.

    A standalone that is part of the main stack legitimately has no compose file of
    its own — archie-comms is built by /mnt/archie_brain/docker-compose.yml via
    `context: ./archie-comms`. Requiring a private compose would push us to add a
    duplicate, conflicting one purely to satisfy the check.
    """
    root_compose = os.path.join(BRAIN_ROOT, "docker-compose.yml")
    dir_name = os.path.basename(os.path.normpath(product_path))
    if not dir_name or not os.path.isfile(root_compose):
        return False
    try:
        with open(root_compose, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return f"./{dir_name}" in content or f": {dir_name}\n" in content
    except Exception:
        return False


def _detect_retired_modules():
    """Detect ARCHIE modules that are stubs, redirects, or retired."""
    tools_dir = os.path.join(PLATFORM_ROOT, "tools")
    if not os.path.isdir(tools_dir):
        return []

    retired = []

    for entry in sorted(os.listdir(tools_dir)):
        module_path = os.path.join(tools_dir, entry)
        if not os.path.isdir(module_path) or entry.startswith(".") or entry == "__pycache__":
            continue

        routes_file = os.path.join(module_path, "routes.py")
        if not os.path.isfile(routes_file):
            continue

        try:
            with open(routes_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Check for redirect pattern
            has_redirect = "redirect(" in content and ("KBS_URL" in content or "KBS_BASE_URL" in content)
            has_retired_marker = "RETIRED" in content.upper()[:500]

            # Count functional lines across ALL .py files in the module
            # (not just routes.py — modules like agent_academy split into sub-route files)
            functional_lines = 0
            for py_root, py_dirs, py_files in os.walk(module_path):
                py_dirs[:] = [d for d in py_dirs if d != "__pycache__"]
                for py_file in py_files:
                    if not py_file.endswith(".py"):
                        continue
                    py_path = os.path.join(py_root, py_file)
                    try:
                        with open(py_path, "r", encoding="utf-8", errors="ignore") as pf:
                            in_docstring = False
                            for line in pf:
                                stripped = line.strip()
                                if stripped.startswith('"""') or stripped.startswith("'''"):
                                    in_docstring = not in_docstring
                                    continue
                                if in_docstring:
                                    continue
                                if (
                                    not stripped
                                    or stripped.startswith("#")
                                    or stripped.startswith("import")
                                    or stripped.startswith("from")
                                ):
                                    continue
                                functional_lines += 1
                    except Exception:
                        pass

            status = "active"
            redirect_target = None

            if has_redirect or has_retired_marker:
                status = "retired"
                # Extract redirect target
                import re

                match = re.search(r'redirect\(f?"([^"]*)"', content)
                if match:
                    redirect_target = match.group(1)
            elif functional_lines < 15 and "render_template" not in content and "jsonify" not in content:
                status = "stub"

            if status != "active":
                retired.append(
                    {
                        "module": entry,
                        "status": status,
                        "functional_lines": functional_lines,
                        "redirect_target": redirect_target,
                    }
                )

        except Exception:
            pass

    return retired


def _calculate_health_score(report):
    """Calculate a 0-100 health score from the full audit report."""
    score = 100
    deductions = []

    # Orphan files: -5 each
    orphans = report.get("orphans", {})
    orphan_count = sum(len(v) for v in orphans.values())
    if orphan_count:
        penalty = orphan_count * 5
        score -= penalty
        deductions.append(f"-{penalty}: {orphan_count} orphan file(s)")

    # KBS plugin issues: -3 each
    kbs = report.get("kbs_audit", {})
    kbs_issues = len(kbs.get("issues", []))
    if kbs_issues:
        penalty = kbs_issues * 3
        score -= penalty
        deductions.append(f"-{penalty}: {kbs_issues} KBS plugin issue(s)")

    # Standalone issues: -5 each Tier 1 failure
    standalone = report.get("standalone_audit", {})
    standalone_issues = len(standalone.get("issues", []))
    if standalone_issues:
        penalty = standalone_issues * 5
        score -= penalty
        deductions.append(f"-{penalty}: {standalone_issues} standalone issue(s)")

    # Retired modules without redirect: -2 each
    retired = report.get("retired_modules", [])
    stubs = [m for m in retired if m["status"] == "stub"]
    if stubs:
        penalty = len(stubs) * 2
        score -= penalty
        deductions.append(f"-{penalty}: {len(stubs)} stub module(s) without redirect")

    return {
        "score": max(score, 0),
        "grade": _score_to_grade(max(score, 0)),
        "deductions": deductions,
    }


def _score_to_grade(score):
    """Convert numeric score to letter grade."""
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 85:
        return "B+"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _get_commit_hash(repo_path="/mnt/archie_brain"):
    """Get current git commit hash.

    The scheduler container runs as a different uid than the host-owned checkout,
    so bare git refuses with 'dubious ownership' — every snapshot since 2026-03-23
    stored an empty hash, disabling change detection (#6046). Same trap and same
    fix as services/hub_deploy_state.py: -C plus an explicit safe.directory.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "-c", f"safe.directory={repo_path}", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning("_get_commit_hash: %s", (result.stderr or "").strip()[:200])
    except Exception as e:
        logger.warning("_get_commit_hash: %s", e)
    return None


def save_snapshot(metrics=None):
    """Scan codebase and save a snapshot to the database."""
    if metrics is None:
        metrics = scan_codebase()

    commit_hash = _get_commit_hash()

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Detect which modules changed since the last snapshot
            modules_changed = []
            cur.execute("SELECT per_module FROM code_metrics_snapshots ORDER BY scanned_at DESC LIMIT 1")
            prev_row = cur.fetchone()
            if prev_row and prev_row.get("per_module"):
                prev_modules = (
                    prev_row["per_module"]
                    if isinstance(prev_row["per_module"], dict)
                    else json.loads(prev_row["per_module"])
                )
                new_modules = metrics.get("modules", {})
                for key, data in new_modules.items():
                    prev_data = prev_modules.get(key, {})
                    if data.get("files") != prev_data.get("files") or data.get("lines") != prev_data.get("lines"):
                        modules_changed.append(key)
                # New modules not in previous
                for key in new_modules:
                    if key not in prev_modules and key not in modules_changed:
                        modules_changed.append(key)

            if modules_changed:
                logger.info(
                    "Modules changed since last snapshot (%d): %s%s",
                    len(modules_changed),
                    ", ".join(modules_changed[:5]),
                    " ..." if len(modules_changed) > 5 else "",
                )

            # Skip if identical snapshot exists within last hour
            cur.execute(
                """SELECT id FROM code_metrics_snapshots
                   WHERE total_files = %s AND total_lines = %s
                     AND scanned_at > NOW() - INTERVAL '1 hour'
                   LIMIT 1""",
                (metrics["total_files"], metrics["total_lines"]),
            )
            if cur.fetchone():
                logger.info("Skipping duplicate snapshot (same file/line count within 1h)")
                return None

            cur.execute(
                """INSERT INTO code_metrics_snapshots
                       (total_files, total_lines, total_folders,
                        python_files, python_lines, js_files, js_lines,
                        css_files, css_lines, html_files, html_lines,
                        sql_files, sql_lines, per_module, commit_hash,
                        modules_changed)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    json.dumps(metrics["modules"]),
                    commit_hash,
                    json.dumps(modules_changed),
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


SEVERITY_MAP = {
    "HARDCODED_SECRET": "red",
    "SQL_INJECTION_RISK": "red",
    "DIRECT_OLLAMA": "red",
    "DIRECT_CLOUD": "red",
    "INSECURE_DEFAULT": "red",
    "BARE_EXCEPT": "yellow",
    "LARGE_FILE": "yellow",
    "MISSING_INIT": "yellow",
    "INLINE_SCRIPT": "yellow",
    "CONSOLE_LOG": "yellow",
    "LATEST_TAG": "yellow",
    "MISSING_RESOURCE_LIMIT": "yellow",
    "DEBUG_PRINT": "info",
    "DEBUG_BREAKPOINT": "info",
    "NO_DOCSTRING": "info",
    "TODO_FIXME": "info",
    "MIXED_CONCERNS": "info",
    "IMPORT_VIOLATION": "info",
}


def detect_audit_profile(module_data):
    """Auto-detect audit profile from module's file type composition.
    Returns 'python', 'web', or 'config' based on 60% threshold.
    """
    by_type = module_data.get("by_type", {})
    total = sum(v.get("lines", 0) for v in by_type.values())
    if total == 0:
        return "python"
    web_lines = sum(by_type.get(t, {}).get("lines", 0) for t in ["js", "html", "css", "svg"])
    config_lines = sum(by_type.get(t, {}).get("lines", 0) for t in ["yaml", "config"])
    if config_lines / total >= 0.6:
        return "config"
    if web_lines / total >= 0.6:
        return "web"
    return "python"


def audit_module_web(module_path):
    """Run web-focused checks on JS/HTML/CSS files.
    Returns (issues_found: int, notes: str, issues_list: list[dict]).
    """
    import re

    issues = []
    issues_list = []

    def _add_issue(code, fname, detail=""):
        severity = SEVERITY_MAP.get(code, "info")
        label = f"{code}: {fname}" if not detail else f"{code}: {fname} ({detail})"
        issues.append(label)
        issues_list.append({"code": code, "severity": severity, "file": fname, "detail": detail})

    web_exts = {".js", ".mjs", ".html", ".htm", ".css", ".svg"}
    todo_count = 0

    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in web_exts:
                continue
            fpath = os.path.join(root, f)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                fname = os.path.relpath(fpath, module_path)

                # Hardcoded secrets
                secret_pats = re.findall(
                    r'(?:password|api_key|token|secret)\s*[=:]\s*["\']([^"\']{8,})["\']',
                    content,
                    re.IGNORECASE,
                )
                for match in secret_pats:
                    if match.startswith("test_") or "${" in match or "process.env" in match:
                        continue
                    if re.match(r"^(sk-|ghp_|gho_|glpat-)", match):
                        _add_issue("HARDCODED_SECRET", fname, "possible API key")
                    elif not re.match(r"^[\w\-]+$", match):
                        _add_issue("HARDCODED_SECRET", fname)

                # Hardcoded default for a SECRET-keyed getenv()/environ.get() —
                # e.g. os.getenv("X_PASSWORD", "literal"). The keyword-anchored
                # pattern above misses these: the secret keyword is in the env-var
                # NAME, not before the assignment (KB #270467).
                for match in re.findall(
                    r'(?:getenv|environ\.get)\(\s*["\'][^"\']*'
                    r'(?:pass|pwd|secret|token|api_?key|cred)[^"\']*["\']'
                    r'\s*,\s*["\']([^"\']{8,})["\']',
                    content,
                    re.IGNORECASE,
                ):
                    if match.startswith("test_") or "${" in match or "process.env" in match:
                        continue
                    if re.match(r"^(sk-|ghp_|gho_|glpat-)", match):
                        _add_issue("HARDCODED_SECRET", fname, "possible API key (getenv default)")
                    elif not re.match(r"^[\w\-]+$", match):
                        _add_issue("HARDCODED_SECRET", fname, "hardcoded getenv default secret")

                # Inline script blocks in HTML (>5 lines of logic)
                if ext in (".html", ".htm"):
                    script_blocks = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
                    for block in script_blocks:
                        logic_lines = [
                            ln.strip() for ln in block.split("\n") if ln.strip() and not ln.strip().startswith("//")
                        ]
                        if len(logic_lines) > 5:
                            _add_issue("INLINE_SCRIPT", fname, f"{len(logic_lines)} lines of inline JS")
                            break

                # console.log in JS
                if ext in (".js", ".mjs"):
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        stripped = line.strip()
                        if stripped.startswith("//"):
                            continue
                        if "console.log(" in stripped:
                            _add_issue("CONSOLE_LOG", fname, f"line {i}")
                            break

                # Large file
                line_count = content.count("\n") + 1
                if line_count > 600:
                    _add_issue("LARGE_FILE", fname, f"{line_count} lines")

                # TODO/FIXME count
                todo_count += len(re.findall(r"\b(TODO|FIXME|HACK|XXX)\b", content))

            except Exception:
                pass

    if todo_count > 0:
        _add_issue("TODO_FIXME", module_path, f"{todo_count} TODO/FIXME/HACK/XXX comments")

    return (
        len(issues),
        "; ".join(issues[:_NOTES_MAX_FINDINGS]) if issues else "clean — all web checks passed",
        issues_list,
    )


def audit_module_config(module_path):
    """Run config-focused checks on YAML/TOML/Docker files.
    Returns (issues_found: int, notes: str, issues_list: list[dict]).
    """
    import re

    issues = []
    issues_list = []

    def _add_issue(code, fname, detail=""):
        severity = SEVERITY_MAP.get(code, "info")
        label = f"{code}: {fname}" if not detail else f"{code}: {fname} ({detail})"
        issues.append(label)
        issues_list.append({"code": code, "severity": severity, "file": fname, "detail": detail})

    config_exts = {".yaml", ".yml", ".toml", ".conf", ".ini"}
    docker_files = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "docker-compose.hub.yml"}

    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            is_config = ext in config_exts
            is_docker = f in docker_files or f.startswith("Dockerfile")
            if not is_config and not is_docker:
                continue
            fpath = os.path.join(root, f)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                fname = os.path.relpath(fpath, module_path)

                # Hardcoded secrets
                secret_pats = re.findall(
                    r'(?:password|api_key|token|secret)\s*[=:]\s*["\']?([^\s"\']{8,})["\']?',
                    content,
                    re.IGNORECASE,
                )
                for match in secret_pats:
                    if "${" in match or "os.getenv" in match or match.startswith("$"):
                        continue
                    if re.match(r"^(sk-|ghp_|gho_|glpat-)", match):
                        _add_issue("HARDCODED_SECRET", fname, "possible API key")
                    elif not re.match(r"^[\w\-\.\/]+$", match):
                        _add_issue("HARDCODED_SECRET", fname)

                # Hardcoded default for a SECRET-keyed getenv()/environ.get()
                # (KB #270467) — the loop above skips any match containing
                # "os.getenv", so secret defaults slip through.
                for match in re.findall(
                    r'(?:getenv|environ\.get)\(\s*["\'][^"\']*'
                    r'(?:pass|pwd|secret|token|api_?key|cred)[^"\']*["\']'
                    r'\s*,\s*["\']([^"\']{8,})["\']',
                    content,
                    re.IGNORECASE,
                ):
                    if match.startswith("test_") or "${" in match or "process.env" in match:
                        continue
                    if re.match(r"^(sk-|ghp_|gho_|glpat-)", match):
                        _add_issue("HARDCODED_SECRET", fname, "possible API key (getenv default)")
                    elif not re.match(r"^[\w\-\.\/]+$", match):
                        _add_issue("HARDCODED_SECRET", fname, "hardcoded getenv default secret")

                # Docker-specific checks
                if is_docker:
                    if "privileged: true" in content or "privileged=true" in content:
                        _add_issue("INSECURE_DEFAULT", fname, "privileged: true")
                    if "read_only: false" in content:
                        _add_issue("INSECURE_DEFAULT", fname, "read_only: false")
                    # Latest tag
                    if re.search(r"image:\s*\S+:latest", content):
                        _add_issue("LATEST_TAG", fname, "uses :latest tag")
                    if f.startswith("Dockerfile") and re.search(r"^FROM\s+\S+:latest", content, re.MULTILINE):
                        _add_issue("LATEST_TAG", fname, "FROM uses :latest tag")
                    # Missing resource limits (docker-compose files)
                    if f.startswith("docker-compose"):
                        # Check each service block for resource limits
                        services = re.findall(r"^\s{2}(\w[\w-]*):", content, re.MULTILINE)
                        for svc in services:
                            # Simple heuristic: look for mem_limit or resources in the content
                            # after the service name
                            svc_pattern = re.search(
                                rf"^\s{{2}}{re.escape(svc)}:.*?(?=^\s{{2}}\w|\Z)",
                                content,
                                re.MULTILINE | re.DOTALL,
                            )
                            if svc_pattern:
                                svc_block = svc_pattern.group()
                                if "mem_limit" not in svc_block and "resources:" not in svc_block:
                                    _add_issue("MISSING_RESOURCE_LIMIT", fname, f"service '{svc}'")

            except Exception:
                pass

    return (
        len(issues),
        "; ".join(issues[:_NOTES_MAX_FINDINGS]) if issues else "clean — all config checks passed",
        issues_list,
    )


def _audit_module_python(module_name, module_path):
    """Run Python-focused checks on .py files.
    Returns (issues_found: int, notes: str, issues_list: list[dict]).
    """
    import re

    issues = []
    issues_list = []

    def _add_issue(code, fname, detail=""):
        severity = SEVERITY_MAP.get(code, "info")
        label = f"{code}: {fname}" if not detail else f"{code}: {fname} ({detail})"
        issues.append(label)
        issues_list.append({"code": code, "severity": severity, "file": fname, "detail": detail})

    py_files = []
    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    # Check 1: Structure — has __init__.py
    has_init = any(f.endswith("__init__.py") for f in py_files)
    if not has_init and py_files:
        _add_issue("MISSING_INIT", module_name, "no __init__.py")

    # Check 2: Pattern compliance — no direct Ollama/cloud calls
    for fpath in py_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            fname = os.path.relpath(fpath, module_path)

            # Skip scanner/checker files that reference these as strings
            if "compliance" in fname or "deploy_routes" in fname:
                pass
            else:
                if "call_ollama(" in content and "bridge" not in fpath:
                    _add_issue("DIRECT_OLLAMA", fname)

                if ("call_claude_api(" in content or "call_openai_api(" in content) and "bridge" not in fpath:
                    _add_issue("DIRECT_CLOUD", fname)

            # Check 3: Bare except
            if re.search(r"\bexcept\s*:", content):
                _add_issue("BARE_EXCEPT", fname)

            # Check 4: Hardcoded secrets (exclude test fixtures, shell templates, env lookups)
            secret_matches = re.findall(
                r'(?:password|token|secret)\s*=\s*["\']([^"\']{8,})["\']', content, re.IGNORECASE
            )
            for match in secret_matches:
                # Skip test fixtures, template placeholders, env var patterns
                if match.startswith("test_") or "openssl" in match or "${" in match or "os.getenv" in match:
                    continue
                _add_issue("HARDCODED_SECRET", fname)

            # Check 5: Large files (>600 lines per compliance rules)
            line_count = content.count("\n") + 1
            if line_count > 600:
                _add_issue("LARGE_FILE", fname, f"{line_count} lines")

            # Check 6: SQL injection risk — f-string or % formatting in execute()
            if re.search(r'\.execute\(\s*f["\']', content) or re.search(
                r'\.execute\(\s*["\'].*%s.*["\']\s*%\s*[^(]', content
            ):
                _add_issue("SQL_INJECTION_RISK", fname)

            # Check 7: Debug leftovers — print(), breakpoint(), pdb
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.match(r"^print\(", stripped) and "logger" not in stripped:
                    _add_issue("DEBUG_PRINT", fname, f"line {i}")
                    break  # Only report first occurrence per file
                if "breakpoint()" in stripped or "import pdb" in stripped:
                    _add_issue("DEBUG_BREAKPOINT", fname, f"line {i}")
                    break

            # Check 8: Missing module docstring (routes files only)
            if fname.endswith("routes.py") and not content.strip().startswith('"""'):
                if not content.strip().startswith("'") and not content.strip().startswith("#"):
                    _add_issue("NO_DOCSTRING", fname)

        except Exception:
            pass

    return (
        len(issues),
        "; ".join(issues[:_NOTES_MAX_FINDINGS]) if issues else "clean — all checks passed",
        issues_list,
    )


def audit_status_for(issues_list) -> str:
    """#5942 — the audit status, derived from the FULL findings list.

    GREEN NOW MEANS "NO FINDINGS AT ALL", not "no RED findings". Measured from
    code_audit_log 2026-08-22: 16 of 34 `completed` modules carried findings in their
    notes and rendered as clean — e.g. `faith`, status completed / issues_found 0, notes
    "LARGE_FILE: routes.py (1553 lines)". Fixing yellow/info issues could never move the
    tile, because the tile was driven by the red count.

    Three states, most severe first:
      violations_found  at least one red
      findings_open     findings present, none red   <- these were green
      completed         nothing found

    ⚠️ This does NOT change `issues_found`, which stays len(red_issues). log_audit derives
    `priority = "high" if issues_found >= 10` and drives repair-task creation from it, so
    redefining it would silently change WHAT RAISES A TASK. A full count belongs in its own
    field, never on top of that one.
    """
    if not issues_list:
        return "completed"
    if any((i or {}).get("severity") == "red" for i in issues_list):
        return "violations_found"
    return "findings_open"


def audit_single_module(module_name, module_path=None, module_data=None):
    """
    Run automated checks on a single module and return audit results.
    Returns (issues_found: int, notes: str, status: str, issues_list: list[dict], profile: str).

    Each issue dict has: code, severity (red/yellow/info), file, detail.
    Profile is one of: 'python', 'web', 'config'.
    """
    # Determine path — tool modules live under tools/, special modules have known paths
    if module_path is None:
        if module_name.startswith("standalone_"):
            # Resolve from STANDALONE_PRODUCTS
            for prod in STANDALONE_PRODUCTS:
                if prod["module_key"] == module_name:
                    module_path = prod["path"]
                    break
            if module_path is None:
                return (0, "standalone not found in registry", "completed", [], "python")
        elif module_name.startswith("website_"):
            # Resolve from WEBSITE_PRODUCTS
            for prod in WEBSITE_PRODUCTS:
                if prod["module_key"] == module_name:
                    module_path = prod["path"]
                    break
            if module_path is None:
                return (0, "website not found in registry", "completed", [], "web")
        elif module_name == "[APP_CORE]":
            module_path = PLATFORM_ROOT
        elif module_name == "[AI_BRIDGE]":
            module_path = AI_BRIDGE_ROOT
        elif module_name == "[MIGRATIONS]":
            module_path = MIGRATIONS_ROOT
        elif module_name == "[SHARED]":
            module_path = os.path.join(PLATFORM_ROOT, "static")
        elif module_name.startswith("["):
            return (0, "special module — no audit profile", "completed", [], "python")
        else:
            tools_base = os.path.join(PLATFORM_ROOT, "tools")
            module_path = os.path.join(tools_base, module_name)

    if not os.path.isdir(module_path):
        return (0, "module directory not found", "completed", [], "python")

    # Detect audit profile
    if module_data is not None:
        profile = detect_audit_profile(module_data)
    elif module_name.startswith("website_"):
        profile = "web"
    elif module_name == "[SHARED]":
        profile = "web"
    else:
        profile = "python"

    # Route to correct checker
    if profile == "web":
        count, notes, issues_list = audit_module_web(module_path)
    elif profile == "config":
        count, notes, issues_list = audit_module_config(module_path)
    else:
        count, notes, issues_list = _audit_module_python(module_name, module_path)

    # Only red (critical) issues count — yellow = warnings, info = advisory
    red_issues = [i for i in issues_list if i.get("severity") == "red"] if issues_list else []
    has_critical = len(red_issues) > 0
    # #5942 — GREEN NOW MEANS "NO FINDINGS AT ALL", not "no RED findings".
    # Measured 2026-08-22: 26 of 54 modules rendered a green "clean" tile while their
    # badge showed findings (app_builder: green with 21), because status counted RED
    # only. Fixing yellow/info issues could never move the tile.
    # THREE states now: violations_found (red present) > findings_open (findings, none
    # red) > completed (nothing).
    # ⚠️ THE RETURNED COUNT IS DELIBERATELY UNCHANGED — still len(red_issues). log_audit
    # derives `priority = "high" if issues_found >= 10` and drives repair-task creation
    # from it, so redefining it would silently change WHAT RAISES A TASK. The full count
    # belongs in a separate field, never on top of this one.
    return (len(red_issues), notes, audit_status_for(issues_list), issues_list, profile)


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
    audit_profile="python",
    trigger_reason="scheduled",
    dispatched_via="local_static_analysis",
):
    """Record an audit entry and bridge issues into Repair Bay improvement_proposals.

    dispatched_via defaults to "local_static_analysis" — every current caller of
    this function (audit_single_module's python/web/config checks, and the
    PATTERN_COMPLIANCE grep sweep) IS local static analysis; no caller invokes an
    LLM to produce these rows. A caller that omitted dispatched_via used to write
    a silent NULL — "unmonitored while APPEARING monitored" (#5881) — the same
    defect class as W.A.R.D.E.N. swallowing its exception every run (#2366)."""
    import json as _json

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO code_audit_log
                   (module_name, category, files_reviewed, lines_before, lines_after,
                    issues_found, issues_fixed, notes, status,
                    audit_profile, trigger_reason, dispatched_via)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                audit_profile,
                trigger_reason,
                dispatched_via,
            ),
        )
        audit_id = cur.fetchone()["id"]

        # Bridge: create/update an improvement_proposal when issues are found
        if issues_found > 0:
            cur.execute(
                """SELECT id FROM improvement_proposals
                   WHERE module_name = %s
                     AND proposal_source = 'code_health_scan'
                     AND status NOT IN ('implemented', 'rejected', 'deployed')
                   ORDER BY proposed_at DESC LIMIT 1""",
                (module_name,),
            )
            existing = cur.fetchone()
            priority = "high" if issues_found >= 10 else "medium"
            meta = _json.dumps(
                {
                    "audit_id": audit_id,
                    "files_reviewed": files_reviewed,
                    "lines_before": lines_before,
                    "lines_after": lines_after,
                    "audit_profile": audit_profile,
                    "trigger_reason": trigger_reason,
                    "issues_fixed": issues_fixed,
                }
            )
            if existing:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET title = %s, description = %s, priority = %s,
                           metadata = %s::jsonb, proposed_at = NOW()
                       WHERE id = %s""",
                    (
                        f"Code Health: {issues_found} issue(s) in {module_name}",
                        notes or f"{issues_found} issue(s) detected by code health scan",
                        priority,
                        meta,
                        existing["id"],
                    ),
                )
            else:
                cur.execute(
                    """INSERT INTO improvement_proposals
                           (title, description, category, priority, status,
                            module_name, proposal_source, metadata)
                       VALUES (%s, %s, 'code_quality', %s, 'proposed',
                               %s, 'code_health_scan', %s::jsonb)""",
                    (
                        f"Code Health: {issues_found} issue(s) in {module_name}",
                        notes or f"{issues_found} issue(s) detected by code health scan",
                        priority,
                        module_name,
                        meta,
                    ),
                )

        return audit_id


def detect_changes_since_last_snapshot(repo_path="/mnt/archie_brain"):
    """
    Compare current commit against the previous snapshot's commit_hash.
    Returns {module_name: [list_of_changed_files]} for modules with changes.
    """
    try:
        current_hash = _get_commit_hash(repo_path)
        if not current_hash:
            logger.warning("detect_changes: could not get current commit hash")
            return {}

        # Get the previous snapshot's commit_hash (skip the most recent one)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT commit_hash FROM code_metrics_snapshots
                   WHERE commit_hash IS NOT NULL
                   ORDER BY scanned_at DESC LIMIT 1 OFFSET 1"""
            )
            row = cur.fetchone()

        if not row or not row["commit_hash"]:
            logger.info("detect_changes: no previous snapshot with commit_hash (first run)")
            return {}

        previous_hash = row["commit_hash"]

        if previous_hash == current_hash:
            logger.info("detect_changes: no commits since last snapshot")
            return {}

        # Get changed files between the two commits
        result = subprocess.run(
            ["git", "diff", "--name-only", previous_hash, current_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("detect_changes: git diff failed: %s", result.stderr.strip())
            return {}

        changed_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        if not changed_files:
            return {}

        # Map files to modules based on directory paths
        module_changes = defaultdict(list)
        for fpath in changed_files:
            module = _map_file_to_module(fpath)
            if module:
                module_changes[module].append(fpath)

        logger.info(
            "detect_changes: %d files changed across %d modules (%s..%s)",
            len(changed_files),
            len(module_changes),
            previous_hash[:8],
            current_hash[:8],
        )
        return dict(module_changes)

    except Exception as e:
        logger.error("detect_changes_since_last_snapshot failed: %s", e)
        return {}


def _map_file_to_module(filepath):
    """Map a git-relative file path to a module name."""
    # platform_v2/tools/<module_name>/... -> module_name
    if filepath.startswith("platform_v2/tools/"):
        parts = filepath.split("/")
        if len(parts) >= 3:
            return parts[2]

    # platform_v2/templates/tools/<module_name>.html -> module_name
    if filepath.startswith("platform_v2/templates/tools/"):
        parts = filepath.split("/")
        if len(parts) >= 4:
            basename = os.path.splitext(parts[3])[0]
            return basename.replace("-", "_")

    # platform_v2/static/js/<module>.js or css/<module>.css
    if filepath.startswith("platform_v2/static/js/") or filepath.startswith("platform_v2/static/css/"):
        parts = filepath.split("/")
        if len(parts) >= 4:
            basename = os.path.splitext(parts[3])[0]
            return basename.replace("-", "_")

    # ai_bridge/... -> [AI_BRIDGE]
    if filepath.startswith("ai_bridge/"):
        return "[AI_BRIDGE]"

    # platform_v2/services/... or platform_v2/app.py etc -> [APP_CORE]
    if filepath.startswith("platform_v2/") and not filepath.startswith("platform_v2/tools/"):
        return "[APP_CORE]"

    # database/migrations/... -> [MIGRATIONS]
    if filepath.startswith("database/migrations/"):
        return "[MIGRATIONS]"

    return None


def mark_stale_audits(changed_modules):
    """
    Mark existing audit entries as stale for modules that have changed.
    Only marks non-stale audits as stale.
    Returns count of audits marked stale.
    """
    if not changed_modules:
        return 0

    total_marked = 0
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for module_name in changed_modules:
                cur.execute(
                    """UPDATE code_audit_log
                       SET stale = TRUE
                       WHERE module_name = %s AND stale = FALSE""",
                    (module_name,),
                )
                count = cur.rowcount
                if count > 0:
                    total_marked += count
                    logger.info(
                        "Marked %d audit(s) stale for module '%s'",
                        count,
                        module_name,
                    )

        if total_marked > 0:
            logger.info(
                "mark_stale_audits: %d total audits marked stale across %d modules",
                total_marked,
                len(changed_modules),
            )
    except Exception as e:
        logger.error("mark_stale_audits failed: %s", e)

    return total_marked


def scan_and_detect_changes(repo_path="/mnt/archie_brain"):
    """
    Wrapper that runs the full scan pipeline:
    1. Scan codebase metrics
    2. Save snapshot
    3. Detect file changes since last snapshot
    4. Mark stale audits for changed modules
    5. Store change info in the snapshot's per_module JSONB
    Returns (metrics, snapshot_id, changed_modules).
    """
    # Step 1: Scan
    metrics = scan_codebase()

    # Step 2: Save snapshot
    snapshot_id = save_snapshot(metrics)

    # Step 3: Detect changes
    changed_modules = detect_changes_since_last_snapshot(repo_path)

    # Step 4: Mark stale audits
    if changed_modules:
        mark_stale_audits(changed_modules)

        # Step 5: Update the snapshot's per_module with change info
        if snapshot_id:
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "SELECT per_module FROM code_metrics_snapshots WHERE id = %s",
                        (snapshot_id,),
                    )
                    row = cur.fetchone()
                    if row and row["per_module"]:
                        per_module = (
                            row["per_module"] if isinstance(row["per_module"], dict) else json.loads(row["per_module"])
                        )
                    else:
                        per_module = {}

                    per_module["changes_since_last"] = {mod: files for mod, files in changed_modules.items()}

                    cur.execute(
                        "UPDATE code_metrics_snapshots SET per_module = %s WHERE id = %s",
                        (json.dumps(per_module), snapshot_id),
                    )
                    logger.info(
                        "Updated snapshot #%d with changes_since_last for %d modules",
                        snapshot_id,
                        len(changed_modules),
                    )
            except Exception as e:
                logger.error("Failed to update snapshot with change info: %s", e)

    return metrics, snapshot_id, changed_modules


def backfill_git_history(repo_path="/mnt/archie_brain"):
    """
    Walk full git history and create daily snapshots.
    Tracks both line changes (--numstat) and file changes (--diff-filter).
    """

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
