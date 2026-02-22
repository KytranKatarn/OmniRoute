"""
External AI Provider Integration — Dynamic DB-Driven
Supports any OpenAI-compatible provider via contractor_providers table.
Legacy constants kept as fallback if DB is unreachable.

All functions return: {success, response, model, provider, prompt_tokens, completion_tokens, cost_usd}
"""

import json
import logging
import os
import time
import requests
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# ============================================================================
# LEGACY FALLBACK CONSTANTS (used only if contractor_providers table unavailable)
# ============================================================================

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

# ============================================================================
# DYNAMIC PROVIDER CACHE (from contractor_providers table)
# ============================================================================

_provider_cache: Dict[str, Dict] = {}
_provider_cache_time: float = 0
_PROVIDER_CACHE_TTL: int = 60  # seconds

# Model-name → provider_key lookup (built from cache)
_model_provider_map: Dict[str, str] = {}


def _load_all_providers() -> Dict[str, Dict]:
    """Load all providers from contractor_providers table, cached for 60s."""
    global _provider_cache, _provider_cache_time, _model_provider_map

    now = time.time()
    if _provider_cache and (now - _provider_cache_time) < _PROVIDER_CACHE_TTL:
        return _provider_cache

    try:
        from database import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT provider_key, display_name, base_url, default_model,
                   auth_method, auth_env_var, is_cloud_proxy, tier_position,
                   models, rate_limits, is_active
            FROM contractor_providers
            ORDER BY tier_position
            """
        )
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        conn.close()

        new_cache = {}
        new_model_map = {}
        for row in rows:
            d = dict(zip(cols, row))
            key = d["provider_key"]
            # Parse JSONB fields
            models_raw = d.get("models")
            if isinstance(models_raw, str):
                models_raw = json.loads(models_raw)
            d["models"] = models_raw or []

            rate_limits_raw = d.get("rate_limits")
            if isinstance(rate_limits_raw, str):
                rate_limits_raw = json.loads(rate_limits_raw)
            d["rate_limits"] = rate_limits_raw or {}

            new_cache[key] = d

            # Build model → provider reverse map
            for m in d["models"]:
                new_model_map[m["name"]] = key

        _provider_cache = new_cache
        _model_provider_map = new_model_map
        _provider_cache_time = now
        logger.debug(f"[ExternalProviders] Loaded {len(new_cache)} providers from DB")
        return _provider_cache

    except Exception as e:
        logger.warning(f"[ExternalProviders] DB load failed, using legacy: {e}")
        # Return legacy fallback
        if not _provider_cache:
            _provider_cache = {
                key: {
                    "provider_key": key,
                    "base_url": cfg["base_url"],
                    "default_model": cfg["default_model"],
                    "auth_env_var": {
                        "openai": "OPENAI_API_KEY",
                        "perplexity": "PERPLEXITY_API_KEY",
                        "xai": "XAI_API_KEY",
                    }.get(key),
                    "is_cloud_proxy": False,
                    "models": [],
                    "rate_limits": {},
                    "is_active": False,
                }
                for key, cfg in PROVIDER_CONFIGS.items()
            }
            _provider_cache_time = now
        return _provider_cache


def _get_provider_config(provider_key: str) -> Optional[Dict]:
    """Get config for a single provider from cache."""
    providers = _load_all_providers()
    return providers.get(provider_key)


def get_provider_for_model(model_name: str) -> Optional[str]:
    """Look up which provider_key owns a given model name."""
    _load_all_providers()
    return _model_provider_map.get(model_name)


def get_all_provider_models() -> Dict[str, str]:
    """Return model_name → provider_key map for all providers."""
    _load_all_providers()
    return dict(_model_provider_map)


def invalidate_provider_cache():
    """Force a cache refresh on next call. Call from routes.py after provider edits."""
    global _provider_cache, _provider_cache_time, _model_provider_map
    _provider_cache = {}
    _model_provider_map = {}
    _provider_cache_time = 0
    logger.info("[ExternalProviders] Provider cache invalidated")


# ============================================================================
# API KEY & BUDGET
# ============================================================================


def _get_api_key(provider: str) -> Optional[str]:
    """Get API key for provider — dynamic env_var from DB, then external_api_keys fallback."""
    # 1. Try dynamic env var from contractor_providers
    config = _get_provider_config(provider)
    if config and config.get("auth_env_var"):
        key = os.getenv(config["auth_env_var"], "")
        if key:
            return key

    # 2. Legacy env var fallback
    legacy_env = {"openai": "OPENAI_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "xai": "XAI_API_KEY"}
    key = os.getenv(legacy_env.get(provider, ""))
    if key:
        return key

    # 3. DB fallback (external_api_keys table)
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
    """Calculate cost in USD — uses DB models JSONB first, legacy fallback."""
    # Try dynamic lookup from provider cache
    _load_all_providers()
    provider_key = _model_provider_map.get(model)
    if provider_key:
        config = _provider_cache.get(provider_key, {})
        for m in config.get("models", []):
            if m["name"] == model:
                costs = m.get("cost_per_1k", {})
                inp = costs.get("input", 0.001)
                out = costs.get("output", 0.001)
                return (prompt_tokens * inp / 1000) + (completion_tokens * out / 1000)

    # Legacy fallback
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
        cur.execute(
            """
            INSERT INTO cloud_model_usage (model_name, provider, prompt_tokens, completion_tokens, cost_usd, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """,
            (model, provider, prompt_tokens, completion_tokens, cost),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"Failed to log usage: {e}")


# ============================================================================
# GENERIC CALL — works for any OpenAI-compatible provider
# ============================================================================


def _call_openai_compatible(
    provider: str,
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> Dict:
    """Generic OpenAI-compatible API call. Resolves config from DB or legacy."""
    # Try dynamic config first
    config = _get_provider_config(provider)
    if config:
        base_url = config["base_url"]
        model = model or config.get("default_model", "")
    else:
        # Legacy fallback
        legacy = PROVIDER_CONFIGS.get(provider)
        if not legacy:
            return {"success": False, "error": f"Unknown provider: {provider}", "provider": provider}
        base_url = legacy["base_url"]
        model = model or legacy["default_model"]

    api_key = _get_api_key(provider)
    if not api_key:
        return {"success": False, "error": f"No API key for {provider}", "provider": provider}

    if not _check_budget(provider):
        return {"success": False, "error": f"Monthly budget exceeded for {provider}", "provider": provider}

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
            f"{base_url}/chat/completions",
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
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            "model": model,
            "provider": provider,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": provider}


# ============================================================================
# GENERIC ENTRY POINT — call any provider by key
# ============================================================================


def call_external(
    provider_key: str,
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> Dict:
    """
    Generic entry point for any external provider.
    Looks up provider config from DB, dispatches to appropriate call method.

    For cloud proxy providers (MiniMax/Qwen3), delegates to call_ollama_cloud.
    For standard OpenAI-compatible providers, calls _call_openai_compatible.
    """
    config = _get_provider_config(provider_key)
    if not config:
        return {"success": False, "error": f"Unknown provider: {provider_key}", "provider": provider_key}

    # Cloud proxy providers route through Ollama cloud
    if config.get("is_cloud_proxy"):
        try:
            from archie_bridge import call_ollama_cloud

            return call_ollama_cloud(prompt, model=model or config.get("default_model"), system_prompt=system_prompt)
        except ImportError:
            return {"success": False, "error": "archie_bridge not available for cloud proxy", "provider": provider_key}

    return _call_openai_compatible(provider_key, prompt, model, system_prompt, json_mode, timeout)


# ============================================================================
# LEGACY CONVENIENCE FUNCTIONS (kept for backward compatibility)
# ============================================================================


def call_openai(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call OpenAI API."""
    return _call_openai_compatible("openai", prompt, model, system_prompt, json_mode, timeout)


def call_perplexity(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call Perplexity API (with web search)."""
    return _call_openai_compatible("perplexity", prompt, model, system_prompt, json_mode, timeout)


def call_grok(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call xAI Grok API."""
    return _call_openai_compatible("xai", prompt, model, system_prompt, json_mode, timeout)
