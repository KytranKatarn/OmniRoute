"""Stream A.R.C.H.I.E.'s cockpit reply THROUGH the platform dispatcher (#6654).

Replaces the non-streaming ``_dhq_chat_reply`` + its direct-Ollama fallback:
the reply now arrives token-by-token from ``/api/internal/dhq/chat/stream``, so
it is welfare/cost-gated + cold-load-queued + fleet-routed AND renders live in
the cockpit. On ANY failure this raises :class:`DHQUnavailable` — there is no
direct-Ollama bypass any more (all inference goes through DHQ, ADR-013). The
caller turns that into an honest error bubble and saves no assistant turn.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


class DHQUnavailable(Exception):
    """The DHQ stream could not be established or completed."""


def stream_dhq_chat(system_prompt, user_prompt, user_id=None, capability="conversation", *, pin_agent=True, model=None):
    """Yield reply token strings as they arrive, then a final ``done`` dict
    ``{type:'done', model_used, agent_name, provider, prompt_tokens,
    completion_tokens}``. Raises :class:`DHQUnavailable` on no key / non-200 /
    connection error / a stream ``error`` event / a stream that ends with no
    ``done``."""
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        raise DHQUnavailable("no INTERNAL_API_KEY configured")
    platform_url = os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")
    body = {
        "prompt": user_prompt,
        "system_prompt": system_prompt,
        "user_id": user_id,
        "capability": capability,
        "pin_agent": pin_agent,
    }
    if model:
        body["model"] = model
    try:
        import requests

        with requests.post(
            f"{platform_url}/api/internal/dhq/chat/stream",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            stream=True,
            timeout=(10, float(os.getenv("DHQ_CHAT_TIMEOUT", "300"))),
        ) as resp:
            if resp.status_code != 200:
                raise DHQUnavailable(f"dhq stream HTTP {resp.status_code}")
            done_seen = False
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue  # SSE comment / keepalive
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    evt = json.loads(payload)
                except Exception:
                    continue
                etype = evt.get("type")
                if etype == "token":
                    tok = evt.get("content", "")
                    if tok:
                        yield tok
                elif etype == "done":
                    done_seen = True
                    yield {
                        "type": "done",
                        "model_used": evt.get("model_used"),
                        "agent_name": evt.get("agent_name"),
                        "provider": evt.get("provider"),
                        "prompt_tokens": evt.get("prompt_tokens"),
                        "completion_tokens": evt.get("completion_tokens"),
                    }
                    return
                elif etype == "error":
                    raise DHQUnavailable(evt.get("message") or evt.get("code") or "dhq stream error")
            if not done_seen:
                raise DHQUnavailable("dhq stream ended without a done event")
    except DHQUnavailable:
        raise
    except Exception as exc:  # connection reset, timeout, DNS…
        raise DHQUnavailable(str(exc)) from exc
