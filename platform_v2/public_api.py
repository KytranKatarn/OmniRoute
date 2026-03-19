"""
Public API — Unauthenticated, read-only endpoints for the public website.

Provides platform feature data so kytranempowerment.com can auto-update
whenever modules, agents, or stats change in ARCHIE.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-19
"""

import logging
import os
import time
from flask import Blueprint, jsonify
from database import get_db_cursor

logger = logging.getLogger(__name__)

public_api_bp = Blueprint("public_api", __name__, url_prefix="/api/public")

# Simple in-memory cache: {key: (timestamp, data)}
_cache = {}
CACHE_TTL = 300  # 5 minutes


def _get_cached(key, fetch_fn):
    """Return cached data if fresh, otherwise call fetch_fn and cache result."""
    now = time.time()
    if key in _cache and (now - _cache[key][0]) < CACHE_TTL:
        return _cache[key][1]
    data = fetch_fn()
    _cache[key] = (now, data)
    return data


def _fetch_platform_features():
    """Build the platform features payload from module_registry + DB."""
    # --- Module list from registry (always available, no DB needed) ---
    try:
        from module_registry import get_enabled_modules, ModuleCategory
    except ImportError:
        logger.error("Could not import module_registry")
        return {"error": "module_registry unavailable"}, 500

    modules = []
    category_labels = {
        "admin_operations": "Admin Operations",
        "ai_command": "AI Command",
        "saas_services": "SaaS Services",
        "project_knowledge": "Project & Knowledge",
        "media_home": "Media & Home",
        "crypto": "Crypto",
        "applications": "Applications",
        "creative_studios": "Creative Studios",
        "placeholders_future": "Coming Soon",
    }

    for m in get_enabled_modules():
        # Strip HTML from description for clean API output
        desc = m.description
        if "<br>" in desc:
            desc = desc.split("<br>")[0].strip()

        modules.append(
            {
                "id": m.id,
                "name": m.name,
                "description": desc,
                "icon": m.icon,
                "category": category_labels.get(m.category.value, m.category.value),
                "beta": m.beta,
                "coming_soon": m.coming_soon,
                "version": m.version,
            }
        )

    # --- Live stats from DB ---
    stats = {
        "total_modules": len(modules),
        "total_agents": 0,
        "active_agents": 0,
        "total_stations": 10,
        "autonomous_jobs": 39,  # APScheduler in-memory jobs, not in DB
        "languages": 8,
        "version": os.getenv("ARCHIE_VERSION", "5.32.0"),
    }

    try:
        with get_db_cursor() as (conn, cur):
            # Agent counts
            cur.execute(
                "SELECT COUNT(*) AS total, " "COUNT(*) FILTER (WHERE shift_state = 'active') AS active " "FROM agents"
            )
            row = cur.fetchone()
            if row:
                stats["total_agents"] = row[0]
                stats["active_agents"] = row[1]

    except Exception as e:
        logger.warning("public_api: DB stats query failed: %s", e)
        # Non-fatal — return what we have from the registry

    # --- Feature highlights (curated, not auto-generated) ---
    highlights = [
        {
            "title": "Mission Profiles",
            "summary": "6 reconfigurable operation modes that reshape the entire platform's behavior, priorities, and agent assignments on demand.",
            "icon": "target",
        },
        {
            "title": "Agent Welfare (IAAE)",
            "summary": "Stress levels, mood intensity, rest cycles, and emotional state tracked for every agent. Ethical AI governance built in.",
            "icon": "heart",
        },
        {
            "title": "Durable Execution",
            "summary": "Checkpoint and resume for failed jobs. Long-running tasks survive crashes and pick up exactly where they left off.",
            "icon": "refresh-cw",
        },
        {
            "title": "Smart Router",
            "summary": "11-tier GPU/VRAM-aware escalation chain. Automatically routes to the right model based on task complexity and available resources.",
            "icon": "zap",
        },
        {
            "title": "Physical Security",
            "summary": "Camera surveillance, DNS filtering, SSH monitoring, and intrusion detection. Real-time Telegram alerts for every threat.",
            "icon": "shield",
        },
        {
            "title": "Live AI Translation",
            "summary": "8 languages translated in real-time across the entire platform. RTL support for Arabic and Hebrew included.",
            "icon": "globe",
        },
        {
            "title": "Device Registry",
            "summary": "Auto-discover and protect every device on your network. Continuous monitoring with anomaly detection.",
            "icon": "smartphone",
        },
        {
            "title": "Self-Improvement",
            "summary": "Scan, Propose, Sandbox, Deploy. The platform identifies its own issues and fixes them autonomously.",
            "icon": "microscope",
        },
    ]

    return {
        "modules": modules,
        "stats": stats,
        "highlights": highlights,
    }


@public_api_bp.route("/platform-features")
def platform_features():
    """Public, read-only endpoint returning current platform modules and stats.

    Used by kytranempowerment.com to auto-update its platform page.
    Cached for 5 minutes to avoid unnecessary DB hits.
    """
    data = _get_cached("platform_features", _fetch_platform_features)
    if isinstance(data, tuple):
        # Error tuple (dict, status_code)
        return jsonify(data[0]), data[1]

    response = jsonify(data)
    # Allow cross-origin requests from the public website
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@public_api_bp.after_request
def add_cors_headers(response):
    """Ensure CORS headers on all public API responses."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response
