"""Hub Client — machine-to-machine dispatch bridge to ARCHIE Department HQ agents."""

import os
import logging

import requests

logger = logging.getLogger(__name__)

HUB_URL = os.environ.get("ARCHIE_HUB_URL", "http://192.168.1.200:3000")
SERVICE_TOKEN = os.environ.get("ARCHIE_SERVICE_TOKEN", "")
TIMEOUT = int(os.environ.get("HUB_DISPATCH_TIMEOUT", "120"))


def dispatch_to_agent(agent_name, prompt, model=None):
    """Dispatch a prompt to an ARCHIE hub agent and return the response.

    Args:
        agent_name: Name of the agent (e.g., "Quant", "Oracle")
        prompt: The prompt/task for the agent
        model: Optional model override

    Returns:
        dict with keys: success, response, agent_name, duration_ms
        Falls back to mock response if hub unreachable.
    """
    if not SERVICE_TOKEN:
        logger.warning("No ARCHIE_SERVICE_TOKEN set — using mock response")
        return _mock_response(agent_name, prompt)

    payload = {
        "agent_name": agent_name,
        "prompt": prompt,
        "source": "market-watch",
    }
    if model:
        payload["model"] = model

    try:
        resp = requests.post(
            f"{HUB_URL}/api/bridge/dispatch",
            json=payload,
            headers={
                "Authorization": f"Bearer {SERVICE_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error("Hub dispatch failed (%d): %s", resp.status_code, resp.text[:200])
            return _mock_response(agent_name, prompt)

        data = resp.json()
        return {
            "success": True,
            "response": data.get("response", ""),
            "agent_name": agent_name,
            "model": data.get("model"),
            "duration_ms": data.get("duration_ms", 0),
        }
    except requests.exceptions.ConnectionError:
        logger.warning("Hub unreachable at %s — falling back to mock", HUB_URL)
        return _mock_response(agent_name, prompt)
    except requests.exceptions.Timeout:
        logger.warning("Hub dispatch timed out after %ds", TIMEOUT)
        return _mock_response(agent_name, prompt)
    except Exception as e:
        logger.error("Hub dispatch error: %s", e)
        return _mock_response(agent_name, prompt)


def check_hub_health():
    """Check if ARCHIE hub is reachable."""
    try:
        resp = requests.get(f"{HUB_URL}/api/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _mock_response(agent_name, prompt):
    """Return a mock response when hub is unavailable (graceful degradation)."""
    return {
        "success": False,
        "response": f"[MOCK] {agent_name} agent unavailable — hub offline. Analysis pending.",
        "agent_name": agent_name,
        "model": None,
        "duration_ms": 0,
        "mock": True,
    }
