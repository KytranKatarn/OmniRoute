"""
Dispatch Service — executes LLM inference using an assigned agent's model.

Calls Ollama /api/generate with the assigned agent's model and host,
then releases the agent back to the coordinator in a finally block.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    success: bool = False
    response: str = ""
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DispatchService:
    def __init__(self, coordinator=None):
        if coordinator is None:
            from services.department_coordinator import get_coordinator

            coordinator = get_coordinator()
        self._coordinator = coordinator

    def dispatch(
        self,
        assignment,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        timeout: int = 120,
        job_id: Optional[int] = None,
    ) -> DispatchResult:
        """
        POST a prompt to Ollama using the agent assigned in *assignment*.

        Always releases the agent in a finally block regardless of outcome.
        """
        result = DispatchResult(model_used=assignment.model)
        start_ms = int(time.time() * 1000)

        try:
            payload: dict = {
                "model": assignment.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_ctx": 4096,
                    "num_predict": 1024,
                },
            }

            if system_prompt:
                payload["system"] = system_prompt

            if json_mode:
                payload["format"] = "json"

            url = f"{assignment.host}/api/generate"
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)

            result.response = data.get("response", "")
            result.completion_tokens = data.get("eval_count", 0)
            result.prompt_tokens = data.get("prompt_eval_count", 0)
            result.success = True

        except Exception as exc:
            error_str = str(exc)
            logger.error(
                "dispatch failed agent=%s model=%s: %s",
                assignment.agent_name,
                assignment.model,
                error_str,
            )
            # Normalise timeout error message for callers
            if "timed out" in error_str.lower() or "timeout" in error_str.lower():
                result.error = f"timed out: {error_str}"
            else:
                result.error = error_str

        finally:
            result.duration_ms = int(time.time() * 1000) - start_ms
            try:
                self._coordinator.release_agent(assignment.agent_id, job_id)
            except Exception as rel_exc:  # noqa: BLE001
                logger.error(
                    "release_agent failed for agent_id=%s: %s",
                    assignment.agent_id,
                    rel_exc,
                )

        return result


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dispatch_service: Optional[DispatchService] = None
_lock_imported = False


def get_dispatch_service() -> DispatchService:
    global _dispatch_service
    if _dispatch_service is None:
        _dispatch_service = DispatchService()
    return _dispatch_service
