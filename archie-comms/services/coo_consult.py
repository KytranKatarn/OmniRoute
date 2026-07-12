"""Cockpit-side proxy to the platform COO consult endpoints. Server-side only —
the INTERNAL_API_KEY never reaches the browser. Slice 1 of the COO command surface.

Base-URL + bearer mirror conversation_service._dhq_chat_reply (PLATFORM_URL)."""
import os

import requests


def _platform_url():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Content-Type": "application/json", "Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def consult(target, prompt, user_id=None):
    """Dispatch a consult to an agent/department via the platform; return its JSON or None."""
    try:
        r = requests.post(
            f"{_platform_url()}/api/internal/coo/consult",
            json={"target": target, "prompt": prompt, "user_id": user_id},
            headers=_headers(),
            timeout=float(os.getenv("DHQ_CHAT_TIMEOUT", "120")),
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def list_agents():
    """Consultable crew + departments for the switcher; fail-soft to empty."""
    try:
        r = requests.get(f"{_platform_url()}/api/internal/coo/agents", headers=_headers(), timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {"agents": d.get("agents", []), "departments": d.get("departments", [])}
    except Exception:
        pass
    return {"agents": [], "departments": []}
