"""Agent Model Service — model loading, unloading, warmboot, VRAM state tracking.

Owns the relationship between agents and their Ollama models.
Bridge dispatcher calls these instead of managing models directly.

Import:
    from services.agent_models import (
        get_model_state, load_model, unload_model, warmboot,
        get_loaded_models, check_vram_budget,
    )
"""

import json
import logging
import urllib.request
from database import get_db_cursor

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://192.168.1.200:11434"


def get_model_state(agent_id):
    """Get the load state of an agent's model. Returns dict with tier (gpu/cpu/cold), model name."""
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent:
        return {"ready": False, "tier": "unknown", "model": None}

    model_name = agent.get("model", "")
    if not model_name:
        return {"ready": False, "tier": "no_model", "model": None}

    # Check if model is loaded in Ollama
    loaded = get_loaded_models()
    for m in loaded:
        if m["name"] == model_name or m["name"].startswith(model_name.split(":")[0]):
            return {
                "ready": True,
                "tier": "gpu" if m.get("size_vram", 0) > 0 else "cpu",
                "model": model_name,
                "size_vram": m.get("size_vram", 0),
                "size": m.get("size", 0),
            }

    return {"ready": False, "tier": "cold", "model": model_name}


def get_loaded_models(ollama_url=None):
    """Get currently loaded models from Ollama. Returns list of model dicts."""
    url = (ollama_url or OLLAMA_URL) + "/api/ps"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("models", [])
    except Exception as e:
        logger.warning("Failed to get loaded models: %s", e)
        return []


def load_model(agent_id, ollama_url=None):
    """Load an agent's model into Ollama. Returns True on success."""
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent or not agent.get("model"):
        return False

    model_name = agent["model"]
    if ":cloud" in model_name:
        return True  # Cloud models don't need local loading

    url = (ollama_url or OLLAMA_URL) + "/api/generate"
    try:
        payload = json.dumps({"model": model_name, "prompt": "", "keep_alive": "5m"}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
        logger.info("Loaded model %s for agent #%d", model_name, agent_id)
        return True
    except Exception as e:
        logger.warning("Failed to load model %s for agent #%d: %s", model_name, agent_id, e)
        return False


def unload_model(agent_id, ollama_url=None):
    """Unload an agent's model from Ollama. Returns True on success."""
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent or not agent.get("model"):
        return False

    model_name = agent["model"]
    url = (ollama_url or OLLAMA_URL) + "/api/generate"
    try:
        payload = json.dumps({"model": model_name, "keep_alive": 0}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        logger.info("Unloaded model %s for agent #%d", model_name, agent_id)
        return True
    except Exception as e:
        logger.warning("Failed to unload model %s: %s", model_name, e)
        return False


def warmboot(agent_id, ollama_url=None):
    """Ensure an agent's model is ready for dispatch. Load if cold."""
    state = get_model_state(agent_id)
    if state.get("ready"):
        return True
    return load_model(agent_id, ollama_url=ollama_url)


def check_vram_budget(ollama_url=None):
    """Check current VRAM usage across all loaded models. Returns dict."""
    loaded = get_loaded_models(ollama_url)
    total_vram = sum(m.get("size_vram", 0) for m in loaded)
    total_ram = sum(m.get("size", 0) for m in loaded)
    return {
        "models_loaded": len(loaded),
        "total_vram_bytes": total_vram,
        "total_vram_gb": round(total_vram / (1024**3), 2),
        "total_ram_bytes": total_ram,
        "total_ram_gb": round(total_ram / (1024**3), 2),
        "models": [{"name": m["name"], "vram_gb": round(m.get("size_vram", 0) / (1024**3), 2)} for m in loaded],
    }
