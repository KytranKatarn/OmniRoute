"""llama.cpp server as a kill-switched second LOCAL inference provider.

#5317 / ADR-019 phase 2. The spike (#5316) measured llama-server on hub CPU:
~2s cold start, 24.2 tok/s single-stream, x3.73 4-way concurrency scaling
(vs Ollama NUM_PARALLEL=1), 330MB RAM, OpenAI surface working unmodified.

This module is called ONLY from the dispatcher's hub execution chokepoint
(`_execute_llm`) — never from modules directly (ADR-013 holds: all inference
still enters through dispatch()). Routing is opt-in per (capability, model)
via platform_settings and defaults OFF:

    llamacpp:enabled       'true' arms the pilot (anything else = off)
    llamacpp:capabilities  csv allowlist — EMPTY routes nothing even when armed
    llamacpp:models        csv of models the sidecar serves (default qwen2.5:1.5b)

The sidecar (compose service `archie_llamacpp`) is Docker-internal only; the
result dict matches call_ollama's contract exactly, with provider='llamacpp'
(the telemetry split for the side-by-side week) and node_id=None — node_id
MUST stay None or the dispatcher's starship provider-tagger rewrites provider.
Callers treat ANY failure here as "fall through to Ollama".
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

LLAMACPP_URL = os.getenv("LLAMACPP_URL", "http://archie_llamacpp:8080")

_SETTING_ENABLED = "llamacpp:enabled"
_SETTING_CAPS = "llamacpp:capabilities"
_SETTING_MODELS = "llamacpp:models"
_DEFAULT_MODELS = "qwen2.5:1.5b"


def _setting(key: str, default: str = "") -> str:
    """Read one platform_settings value; ANY failure returns the default."""
    try:
        from db import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            value = row[0] if row else None
            return value if value not in (None, "") else default
        finally:
            conn.close()
    except Exception:
        return default


def _csv_set(raw: str) -> set:
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


def should_route(capability, model, json_mode: bool = False) -> bool:
    """True only when the pilot is armed AND this (capability, model) is
    allowlisted. Fails CLOSED on any settings error — the pilot must never
    become the default path by accident. json_mode is excluded: the pilot
    covers the plain-text branch only.
    """
    try:
        if json_mode:
            return False
        if _setting(_SETTING_ENABLED, "false").strip().lower() != "true":
            return False
        capabilities = _csv_set(_setting(_SETTING_CAPS, ""))
        if not capabilities or (capability or "") not in capabilities:
            return False
        models = _csv_set(_setting(_SETTING_MODELS, _DEFAULT_MODELS))
        return (model or "") in models
    except Exception:
        return False


def chat(prompt, model, system_prompt=None, temperature: float = 0.5, timeout: int = 120, options=None):
    """POST /v1/chat/completions on the sidecar; returns the call_ollama shape.

    Raises on transport/HTTP errors — the caller's contract is to catch and
    fall through to Ollama, so failures here must be LOUD, not shaped.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages, "temperature": temperature}
    num_predict = (options or {}).get("num_predict")
    if num_predict:
        payload["max_tokens"] = int(num_predict)

    resp = requests.post(f"{LLAMACPP_URL}/v1/chat/completions", json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    usage = body.get("usage") or {}
    return {
        "success": True,
        "response": (body.get("choices") or [{}])[0].get("message", {}).get("content", ""),
        "model": model,
        "provider": "llamacpp",
        # None on purpose: a non-hub node_id makes the dispatcher's starship
        # tagger overwrite provider, destroying the telemetry split.
        "node_id": None,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }
