"""Node-side triage — determines if a task can be handled locally.

Imports shared triage logic concepts and adds Ollama model checks.
"""

import logging

try:
    import requests as _requests_lib

    _HAS_REQUESTS = True
except ImportError:
    _requests_lib = None
    _HAS_REQUESTS = False
    import urllib.request
    import urllib.error
    import json

logger = logging.getLogger(__name__)

# Local copy of capability map — synced from Bridge
_capability_station_map = {}


def update_capability_map(new_map):
    """Update local capability map from Bridge sync."""
    global _capability_station_map
    _capability_station_map = new_map


def capability_to_station(capability):
    """Map capability to station using local map."""
    for station, caps in _capability_station_map.items():
        if capability in caps:
            return station
    return None


def get_loaded_models(ollama_host="http://localhost:11434"):
    """Query local Ollama for loaded models."""
    try:
        url = f"{ollama_host.rstrip('/')}/api/ps"
        if _HAS_REQUESTS:
            resp = _requests_lib.get(url, timeout=5)
            if resp.ok:
                return {
                    m["name"].split(":")[0] for m in resp.json().get("models", [])
                }
        else:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    m["name"].split(":")[0] for m in data.get("models", [])
                }
    except Exception as e:
        logger.warning(f"Ollama ps check failed: {e}")
    return set()


def can_handle_locally(capability, local_agents, ollama_host="http://localhost:11434"):
    """Check if any local agent can handle this capability.

    Returns best agent dict or None (meaning escalate to Bridge).
    """
    station = capability_to_station(capability)
    if not station:
        return None

    loaded_models = get_loaded_models(ollama_host)

    candidates = []
    for agent in local_agents:
        if station not in agent.get("station_codes", []):
            continue
        if agent.get("status") != "active":
            continue
        shift = agent.get("shift_state", "active")
        if shift in ("cooldown", "off_duty"):
            continue
        stress = agent.get("stress", 0.0)
        energy = agent.get("energy", 1.0)
        if stress >= 0.9 and energy <= 0.15:
            continue
        if agent.get("task_count", 0) >= agent.get("task_limit", 10):
            continue

        # Check model is loaded in Ollama
        model_name = agent.get("model", "").split(":")[0]
        if model_name not in loaded_models:
            continue

        candidates.append(agent)

    if not candidates:
        return None

    candidates.sort(key=lambda a: a.get("task_count", 0))
    return candidates[0]
