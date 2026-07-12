"""Cockpit-side proxy to the platform COMs hub read endpoint. Server-side only —
INTERNAL_API_KEY never reaches the browser. Read-only. Slice 2 of the COO command surface."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _platform_url():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def overview(limit=50, category=None, source_agent=None, status=None):
    """COMs feed + config + migration; fail-soft to empties."""
    params = {"limit": limit}
    if category:
        params["category"] = category
    if source_agent:
        params["source_agent"] = source_agent
    if status:
        params["status"] = status
    try:
        r = requests.get(
            f"{_platform_url()}/api/internal/coms/overview",
            headers=_headers(),
            params=params,
            timeout=float(os.getenv("COMS_TIMEOUT", "15")),
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "messages": d.get("messages", []),
                "config": d.get("config", {}),
                "migration": d.get("migration", {}),
            }
        logger.warning("coms overview proxy: platform returned %s", r.status_code)
    except Exception as e:
        logger.warning("coms overview proxy failed: %s", e)
    return {"messages": [], "config": {}, "migration": {}}
