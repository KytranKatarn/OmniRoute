"""
External AI Provider Integration
Supports OpenAI, Perplexity, and xAI (Grok) via OpenAI-compatible APIs.

All functions return: {success, response, model, provider, prompt_tokens, completion_tokens, cost_usd}
"""

import json
import logging
import os
import time
import requests
from typing import Optional, Dict

logger = logging.getLogger(__name__)

COST_PER_1K_TOKENS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "llama-3.1-sonar-small-128k-online": {"input": 0.0002, "output": 0.0002},
    "grok-2": {"input": 0.002, "output": 0.01},
}

PROVIDER_CONFIGS = {
    "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"},
    "perplexity": {"base_url": "https://api.perplexity.ai", "default_model": "llama-3.1-sonar-small-128k-online"},
    "xai": {"base_url": "https://api.x.ai/v1", "default_model": "grok-2"},
}


def _get_api_key(provider: str) -> Optional[str]:
    """Get API key for provider -- from env var or DB fallback."""
    env_map = {"openai": "OPENAI_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "xai": "XAI_API_KEY"}
    key = os.getenv(env_map.get(provider, ""))
    if key:
        return key
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT api_key_encrypted FROM external_api_keys WHERE provider = %s AND is_active = TRUE",
            (provider,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.debug(f"DB key lookup failed for {provider}: {e}")
    return None


def _check_budget(provider: str) -> bool:
    """Check if provider is within monthly budget."""
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT monthly_budget_usd, current_month_cost_usd FROM external_api_keys WHERE provider = %s",
            (provider,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return True
        return float(row[1] or 0) < float(row[0] or 10)
    except Exception:
        return True


def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD."""
    rates = COST_PER_1K_TOKENS.get(model, {"input": 0.001, "output": 0.001})
    return (prompt_tokens * rates["input"] / 1000) + (completion_tokens * rates["output"] / 1000)


def _update_cost(provider: str, cost: float):
    """Add cost to current month tracking."""
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE external_api_keys SET current_month_cost_usd = current_month_cost_usd + %s, updated_at = NOW() WHERE provider = %s",
            (cost, provider),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to update cost for {provider}: {e}")


def _log_usage(provider: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float):
    """Log to cloud_model_usage table."""
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cloud_model_usage (model_name, provider, prompt_tokens, completion_tokens, cost_usd, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (model, provider, prompt_tokens, completion_tokens, cost))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"Failed to log usage: {e}")


def _call_openai_compatible(
    provider: str,
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> Dict:
    """Generic OpenAI-compatible API call."""
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        return {"success": False, "error": f"Unknown provider: {provider}", "provider": provider}

    api_key = _get_api_key(provider)
    if not api_key:
        return {"success": False, "error": f"No API key for {provider}", "provider": provider}

    if not _check_budget(provider):
        return {"success": False, "error": f"Monthly budget exceeded for {provider}", "provider": provider}

    model = model or config["default_model"]
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        start = time.time()
        resp = requests.post(
            f"{config['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        duration_ms = int((time.time() - start) * 1000)
        resp.raise_for_status()

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = _calculate_cost(model, prompt_tokens, completion_tokens)

        _update_cost(provider, cost)
        _log_usage(provider, model, prompt_tokens, completion_tokens, cost)

        return {
            "success": True,
            "response": choice["message"]["content"],
            "model": model,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost,
            "duration_ms": duration_ms,
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error": f"Timeout after {timeout}s", "model": model, "provider": provider}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}", "model": model, "provider": provider}
    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": provider}


def call_openai(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call OpenAI API."""
    return _call_openai_compatible("openai", prompt, model, system_prompt, json_mode, timeout)


def call_perplexity(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call Perplexity API (with web search)."""
    return _call_openai_compatible("perplexity", prompt, model, system_prompt, json_mode, timeout)


def call_grok(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call xAI Grok API."""
    return _call_openai_compatible("xai", prompt, model, system_prompt, json_mode, timeout)
