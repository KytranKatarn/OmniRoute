"""ComfyUI container lifecycle — record last-use, cold-start, idle-stop.

Project #240 task #2019 (2026-04-16).

ComfyUI's container (archie_comfyui) keeps a huge virtual allocation (~165 GB)
even when idle. Without a policy, it sits forever and the kernel eventually
pages out its inactive memory, polluting swap (6.5 GB was lost this way on
2026-04-16).

Parallel to Ollama's KEEP_ALIVE=5m: when no generation has happened for
COMFYUI_IDLE_SECONDS, stop the container. The dispatcher calls
`ensure_running()` before every gen and cold-starts if needed.

Timestamp is stored in `system_config` (key='comfyui_last_used_at') so it
survives platform restarts.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("comfyui_lifecycle")

_CONTAINER_NAME = "archie_comfyui"
_LAST_USED_KEY = "comfyui_last_used_at"
_COLD_START_TIMEOUT = 60  # seconds to wait for ComfyUI to answer after start


def _docker_client():
    """Return a docker-py client, or None if unavailable."""
    try:
        import docker

        return docker.from_env()
    except Exception as e:
        logger.warning(f"docker-py unavailable: {e}")
        return None


def _get_container():
    client = _docker_client()
    if not client:
        return None
    try:
        return client.containers.get(_CONTAINER_NAME)
    except Exception as e:
        logger.warning(f"container {_CONTAINER_NAME} not found: {e}")
        return None


# ---------------------------------------------------------------------------
# State — persisted in system_config
# ---------------------------------------------------------------------------


def record_last_used() -> None:
    """Mark now as the last ComfyUI use. Called after every gen completes."""
    try:
        from database import get_db_cursor

        ts = int(time.time())
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO system_config (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (_LAST_USED_KEY, str(ts)),
            )
    except Exception as e:
        logger.warning(f"record_last_used failed: {e}")


def get_last_used() -> Optional[int]:
    """Return the unix timestamp of the last ComfyUI use, or None if never."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = %s", (_LAST_USED_KEY,))
            row = cur.fetchone()
            if row and row["value"]:
                return int(row["value"])
    except Exception as e:
        logger.warning(f"get_last_used failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Container control
# ---------------------------------------------------------------------------


def ensure_running(timeout: int = _COLD_START_TIMEOUT) -> bool:
    """Cold-start the ComfyUI container if stopped, and wait for it to answer.

    Returns True if container is running (or was already running).
    Called by the dispatcher before every generate_image.
    """
    container = _get_container()
    if not container:
        return False

    container.reload()
    if container.status == "running":
        return True

    logger.info(f"ComfyUI was {container.status}; cold-starting")
    try:
        # Restore restart policy so Docker keeps it up during normal operation.
        container.update(restart_policy={"Name": "unless-stopped"})
        container.start()
    except Exception as e:
        logger.error(f"ComfyUI cold-start failed: {e}")
        return False

    # Wait for the HTTP endpoint to answer.
    import os

    import requests

    host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{host}/system_stats", timeout=3)
            if r.status_code == 200:
                logger.info("ComfyUI cold-start ready")
                return True
        except Exception:
            pass
        time.sleep(2)

    logger.warning(f"ComfyUI did not answer within {timeout}s after cold-start")
    return False


def idle_stop_if_needed(max_idle_seconds: int = 1800) -> dict:
    """Stop the ComfyUI container if it has been idle longer than the threshold.

    Sets restart policy to 'no' before stopping so Docker doesn't auto-revive.
    The ensure_running() path restores 'unless-stopped' on cold-start.

    Called by an autonomy job every few minutes.
    Returns a dict describing what happened (for logging).
    """
    last_used = get_last_used()
    now = int(time.time())
    idle_for = None if last_used is None else now - last_used

    container = _get_container()
    if not container:
        return {"action": "skip", "reason": "no container", "idle_for": idle_for}
    container.reload()

    if container.status != "running":
        return {"action": "skip", "reason": f"already {container.status}", "idle_for": idle_for}

    if last_used is None:
        # No gens ever recorded — don't stop a never-used-but-running container on its first check;
        # seed the timestamp so we have a baseline.
        record_last_used()
        return {"action": "seed", "reason": "no last_used, seeded", "idle_for": 0}

    if idle_for < max_idle_seconds:
        return {"action": "skip", "reason": "not idle enough", "idle_for": idle_for}

    logger.info(f"ComfyUI idle for {idle_for}s > {max_idle_seconds}s — stopping")
    try:
        container.update(restart_policy={"Name": "no"})
        container.stop(timeout=15)
    except Exception as e:
        logger.error(f"ComfyUI idle-stop failed: {e}")
        return {"action": "error", "reason": str(e), "idle_for": idle_for}

    return {"action": "stopped", "reason": "idle threshold", "idle_for": idle_for}
