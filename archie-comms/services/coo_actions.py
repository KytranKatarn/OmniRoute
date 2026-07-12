"""Cockpit-side proxy to the platform Tools & Actions endpoints. Server-side only —
INTERNAL_API_KEY never reaches the browser. Curated safe actions. Slice 4 of the COO command surface."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def catalog():
    try:
        r = requests.get(f"{_base()}/api/internal/actions/catalog", headers=_headers(), timeout=15)
        if r.status_code == 200:
            return {"actions": r.json().get("actions", [])}
    except Exception as e:
        logger.warning("actions catalog proxy failed: %s", e)
    return {"actions": []}


def run(key):
    try:
        r = requests.post(
            f"{_base()}/api/internal/actions/run",
            json={"key": key},
            headers=_headers(),
            timeout=float(os.getenv("ACTION_TIMEOUT", "120")),
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("actions run proxy failed: %s", e)
    return {"ok": False, "error": "unreachable"}
