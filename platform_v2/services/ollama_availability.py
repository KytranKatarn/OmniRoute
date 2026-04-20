"""Minimal Ollama model-availability helper used by hiring & profile update.

Single public entrypoint: is_model_available(model, hub_host=None) -> (ok, message).
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import requests

DEFAULT_HUB = "http://192.168.1.200:11434"


def is_model_available(
    model: str,
    hub_host: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (ok, message). 5s timeout, any failure => not ok.

    Cloud models (``*:cloud`` suffix) skip the probe and return ok.
    """
    if not model:
        return False, "model empty"

    if model.endswith(":cloud"):
        return True, "cloud model (probe skipped)"

    host = hub_host or os.environ.get("OLLAMA_HOST") or DEFAULT_HUB
    host = host.rstrip("/")

    try:
        r = requests.get(f"{host}/api/tags", timeout=5)
    except requests.Timeout:
        return False, f"ollama timeout at {host}"
    except requests.ConnectionError:
        return False, f"ollama unreachable at {host}"

    if r.status_code != 200:
        return False, f"ollama returned {r.status_code}"

    try:
        names = {m.get("name") for m in r.json().get("models", [])}
    except Exception:
        return False, "ollama /api/tags malformed"

    if model in names:
        return True, f"{model} available"
    return False, f"{model} not present on {host}"
