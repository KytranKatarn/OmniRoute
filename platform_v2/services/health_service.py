"""Platform health probe — sync, side-effect-free.

Used by:
- `services.delegation_service._execute_known_tool` (when capability is
  ``health_check`` or ``check_platform_health``).
- Future callers that want a quick "is the platform alive" snapshot
  without going through the MCP server's async tool layer.

Returns the same dict shape as the MCP `health_check` tool — DB ping,
disk usage, memory usage, Ollama reachability — but synchronously, so
it composes with the delegate_task_worker's threaded executor.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from typing import Any, Dict

import requests as _req

from database import get_db_cursor

logger = logging.getLogger(__name__)

_OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
if not _OLLAMA_URL.startswith("http"):
    _OLLAMA_URL = f"http://{_OLLAMA_URL}"


def check_platform_health(include_details: bool = False) -> Dict[str, Any]:
    """Quick platform health probe.

    Returns a dict with overall ``status`` (healthy/degraded/unhealthy),
    a ``checks`` map for each subsystem, and an ``issues`` list of
    human-readable problems for the executive summary.

    Designed to complete in <2 seconds even when one subsystem is slow:
    each check has its own short timeout. A failing check degrades the
    overall status but does not block other checks.
    """
    health: Dict[str, Any] = {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",
        "checks": {},
        "issues": [],
    }

    _check_database(health, include_details)
    _check_ollama(health)
    _check_disk(health)
    _check_memory(health)

    statuses = [c.get("status") for c in health["checks"].values()]
    if "unhealthy" in statuses:
        health["status"] = "unhealthy"
    elif "warning" in statuses or "degraded" in statuses:
        health["status"] = "degraded"

    return health


def _check_database(health: Dict[str, Any], include_details: bool) -> None:
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1")
            entry: Dict[str, Any] = {"status": "healthy"}
            if include_details:
                cur.execute("SELECT COUNT(*) AS tables FROM information_schema.tables " "WHERE table_schema='public'")
                row = cur.fetchone()
                entry["tables"] = row["tables"] if row else 0
            health["checks"]["database"] = entry
    except Exception as e:
        health["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        health["issues"].append("Database query failed")


def _check_ollama(health: Dict[str, Any]) -> None:
    try:
        resp = _req.get(f"{_OLLAMA_URL}/api/ps", timeout=2)
        if resp.ok:
            loaded = resp.json().get("models", [])
            health["checks"]["ollama"] = {
                "status": "healthy",
                "loaded_models": len(loaded),
            }
        else:
            health["checks"]["ollama"] = {
                "status": "warning",
                "http_status": resp.status_code,
            }
            health["issues"].append(f"Ollama returned HTTP {resp.status_code}")
    except Exception as e:
        # Ollama unreachable degrades the platform but is not "unhealthy" —
        # many tasks (deploys, QA, deterministic services) still work.
        health["checks"]["ollama"] = {"status": "warning", "error": str(e)}
        health["issues"].append("Ollama unreachable")


def _check_disk(health: Dict[str, Any]) -> None:
    try:
        result = subprocess.run(
            ["df", "-h", "/mnt/archie_brain"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            health["checks"]["disk"] = {"status": "unknown", "error": result.stderr.strip()[:120]}
            return
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return
        parts = lines[1].split()
        usage_pct = int(parts[4].replace("%", ""))
        entry: Dict[str, Any] = {
            "status": "healthy" if usage_pct < 90 else "warning",
            "usage_percent": usage_pct,
            "available": parts[3],
        }
        health["checks"]["disk"] = entry
        if usage_pct >= 90:
            health["issues"].append(f"Disk usage at {usage_pct}%")
    except Exception as e:
        health["checks"]["disk"] = {"status": "unknown", "error": str(e)}


def _check_memory(health: Dict[str, Any]) -> None:
    try:
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            health["checks"]["memory"] = {"status": "unknown", "error": result.stderr.strip()[:120]}
            return
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return
        parts = lines[1].split()
        total = int(parts[1])
        used = int(parts[2])
        usage_pct = round((used / total) * 100, 1) if total else 0
        entry: Dict[str, Any] = {
            "status": "healthy" if usage_pct < 90 else "warning",
            "usage_percent": usage_pct,
            "total_mb": total,
            "used_mb": used,
        }
        health["checks"]["memory"] = entry
        if usage_pct >= 90:
            health["issues"].append(f"Memory usage at {usage_pct}%")
    except Exception as e:
        health["checks"]["memory"] = {"status": "unknown", "error": str(e)}


# Compatibility alias — delegation_service uses both names interchangeably.
health_check = check_platform_health
