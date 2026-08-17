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
                   models, rate_limits, is_active, capabilities
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

            caps_raw = d.get("capabilities")
            if isinstance(caps_raw, str):
                caps_raw = json.loads(caps_raw)
            d["capabilities"] = caps_raw or ["text_chat"]

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


def get_providers_with_capability(capability: str) -> List[Dict]:
    """Return active providers that support a given capability, ordered by tier_position.

    Args:
        capability: e.g. 'image_gen', 'audio_tts', 'video_gen', 'text_chat'

    Returns:
        List of dicts: [{provider_key, display_name, capabilities, is_free_tier, tier_position, models}]
    """
    _load_all_providers()
    results = []
    for key, provider in _provider_cache.items():
        caps = provider.get("capabilities", ["text_chat"])
        if capability in caps and provider.get("is_active", False):
            results.append(
                {
                    "provider_key": key,
                    "display_name": provider.get("display_name", key),
                    "capabilities": caps,
                    "is_free_tier": provider.get("tier_position", 99) >= 8
                    and not provider.get("is_cloud_proxy", False),
                    "tier_position": provider.get("tier_position", 99),
                    "models": provider.get("models", []),
                    "base_url": provider.get("base_url", ""),
                }
            )
    results.sort(key=lambda p: p["tier_position"])
    return results


def get_all_capabilities() -> Dict[str, List[Dict]]:
    """Return a summary of which capabilities are available and how many providers support each.

    Returns:
        Dict: {capability: [{provider_key, display_name, is_free_tier}]}
    """
    _load_all_providers()
    caps_map: Dict[str, List[Dict]] = {}
    for key, provider in _provider_cache.items():
        if not provider.get("is_active", False):
            continue
        for cap in provider.get("capabilities", ["text_chat"]):
            if cap not in caps_map:
                caps_map[cap] = []
            caps_map[cap].append(
                {
                    "provider_key": key,
                    "display_name": provider.get("display_name", key),
                    "is_free_tier": provider.get("tier_position", 99) >= 8
                    and not provider.get("is_cloud_proxy", False),
                }
            )
    return caps_map


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

    # #3658: per-provider WEEKLY free-tier request cap (rate_limits.free.weekly_limit).
    # Fail-open, and a no-op for providers without a free weekly_limit configured.
    if not check_weekly_budget(provider):
        return {
            "success": False,
            "error": f"Weekly free-tier limit reached for {provider}",
            "provider": provider,
            "weekly_budget": weekly_budget_status(provider),
        }

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
# WEEKLY FREE-TIER BUDGET GUARD + PROVIDER ROTATION (#3658)
# Free cloud TEXT providers have a per-week request allowance on their free tier
# (contractor_providers.rate_limits.free.weekly_limit). These helpers count the
# last-7-day usage from cloud_model_usage, refuse a provider that has run out
# (with a safety margin), and pick the free provider with the most headroom so a
# caller can rotate across providers instead of blowing one free tier into
# paid overage. All fail-open: a counting error never blocks dispatch.
# ============================================================================

# Free-tier TEXT providers eligible for weekly-budget rotation. Ordered richest
# free allowance first (groq 14.4k/wk > cerebras 8.4k/wk > cohere 1k/wk).
FREE_TEXT_PROVIDERS = ["groq", "cerebras", "cohere"]

# Full cloud TEXT rotation preference for #3659's dispatch guard: the Ollama-Cloud
# proxies first (already the wired translation proxies, 7k/wk each), then the free
# OpenAI-compatible tiers. A caller rotates to the first with weekly headroom and
# falls back to local when all are exhausted.
# minimax_cloud removed 2026-08-17 (#5706) — minimax-m2.5:cloud 410s on every dispatch.
CLOUD_TEXT_ROTATION = ["qwen3_cloud", "groq", "cerebras", "cohere"]


def get_weekly_free_limit(provider: str) -> Optional[int]:
    """Weekly free-tier request cap from rate_limits.free.weekly_limit, or None if uncapped."""
    cfg = _get_provider_config(provider) or {}
    free = (cfg.get("rate_limits") or {}).get("free") or {}
    lim = free.get("weekly_limit")
    return int(lim) if isinstance(lim, (int, float)) and lim else None


def get_weekly_usage(provider: str) -> int:
    """Successful+failed cloud text requests for a provider in the last 7 days.

    Fail-open: any error returns 0 so a counting bug can never block dispatch.
    """
    conn = None
    try:
        from database import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM cloud_model_usage " "WHERE provider = %s AND created_at > NOW() - INTERVAL '7 days'",
            (provider,),
        )
        row = cur.fetchone()
        cur.close()
        n = row[0] if not isinstance(row, dict) else list(row.values())[0]
        return int(n or 0)
    except Exception as e:
        logger.warning("[ExternalProviders] weekly usage count failed for %s: %s", provider, e)
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def weekly_budget_status(provider: str, safety_margin: float = 0.1) -> dict:
    """Per-provider weekly free-tier budget snapshot.

    Returns {provider, limit, used, remaining, effective_cap, over_budget, warn}.
    A provider with no free weekly_limit is reported as uncapped (over_budget False).
    ``effective_cap`` = limit * (1 - safety_margin) so we stop just short of the
    real free ceiling. ``warn`` flips at 80% of the raw limit (the task's alert point).
    """
    limit = get_weekly_free_limit(provider)
    used = get_weekly_usage(provider)
    if not limit:
        return {
            "provider": provider,
            "limit": None,
            "used": used,
            "remaining": None,
            "effective_cap": None,
            "over_budget": False,
            "warn": False,
        }
    cap = int(limit * (1 - safety_margin))
    return {
        "provider": provider,
        "limit": limit,
        "used": used,
        "remaining": max(0, cap - used),
        "effective_cap": cap,
        "over_budget": used >= cap,
        "warn": used >= int(limit * 0.8),
    }


def check_weekly_budget(provider: str, safety_margin: float = 0.1) -> bool:
    """True if the provider still has weekly free-tier headroom (fail-open).

    Logs a warning at >=80% (the task's alert threshold) so a monitor/Telegram
    relay can surface it before the cap is hit.
    """
    st = weekly_budget_status(provider, safety_margin)
    if st["limit"] and st["warn"]:
        logger.warning(
            "[ExternalProviders] %s weekly free tier at %s/%s requests (>=80%%)%s",
            provider,
            st["used"],
            st["limit"],
            " — OVER effective cap" if st["over_budget"] else "",
        )
    return not st["over_budget"]


def pick_free_text_provider(
    candidates: Optional[List[str]] = None,
    prefer: Optional[str] = None,
    safety_margin: float = 0.1,
) -> Optional[str]:
    """Rotation: pick the free TEXT provider with the MOST weekly headroom.

    ``prefer`` wins if it still has headroom (sticky routing); otherwise the
    provider with the most remaining free requests is chosen. Returns None when
    every candidate is out of free-tier budget (caller should fall back to local).
    """
    cands = candidates or FREE_TEXT_PROVIDERS
    scored = []
    for p in cands:
        st = weekly_budget_status(p, safety_margin)
        if st["over_budget"]:
            continue
        # Uncapped providers sort as effectively-infinite headroom.
        rem = st["remaining"] if st["remaining"] is not None else 10**9
        scored.append((rem, p))
    if not scored:
        return None
    if prefer:
        for _rem, p in scored:
            if p == prefer:
                return prefer
    scored.sort(reverse=True)  # most remaining first
    return scored[0][1]


def cloud_budget_status(
    providers: Optional[List[str]] = None,
    safety_margin: float = 0.1,
) -> dict:
    """Aggregate weekly free-tier budget across the cloud TEXT fleet (#3659 primitive).

    Read-only snapshot for the K.I.N. welfare view, A.R.C.H.I.E. briefing, and the
    80%-alert surface — and the data the #3659 dispatch guard reads before it decides
    to rotate or fall back to local. Reuses weekly_budget_status per provider, so it
    inherits the same fail-open behaviour.

    Returns {providers: [status...], total_limit, total_used, total_remaining,
             any_headroom, warnings: [keys>=80%], exhausted: [keys over cap]}.
    """
    provs = providers or CLOUD_TEXT_ROTATION
    rows = [weekly_budget_status(p, safety_margin) for p in provs]
    capped = [r for r in rows if r["limit"]]
    return {
        "providers": rows,
        "total_limit": sum(r["limit"] for r in capped) if capped else None,
        "total_used": sum(r["used"] for r in capped) if capped else None,
        "total_remaining": sum(r["remaining"] for r in capped) if capped else None,
        "any_headroom": any(not r["over_budget"] for r in rows),
        "warnings": [r["provider"] for r in rows if r["warn"]],
        "exhausted": [r["provider"] for r in rows if r["over_budget"]],
    }


# ============================================================================
# MEDIA GENERATION — image, video, audio adapters
# ============================================================================


def generate_media(provider_key: str, request: dict) -> dict:
    """Generate media (image/video/audio) via a provider adapter.

    Args:
        provider_key: e.g. 'gemini', 'openai', 'local_tts'
        request: {type, prompt, params: {size, style, duration, voice, ...}}

    Returns:
        {success: bool, file_path: str, metadata: dict, error: str}
    """
    adapters = {
        "gemini": _gemini_media_adapter,
        "openai": _openai_image_adapter,
        "local_tts": _local_tts_adapter,
        "huggingface": _huggingface_image_adapter,
        "cloudflare_ai": _cloudflare_image_adapter,
        "together": _together_image_adapter,
        "pollinations": _pollinations_image_adapter,
    }
    adapter = adapters.get(provider_key)
    if not adapter:
        return {"success": False, "error": f"No media adapter for provider: {provider_key}"}

    try:
        return adapter(request)
    except Exception as e:
        logger.error(f"Media generation failed ({provider_key}): {e}")
        return {"success": False, "error": str(e)}


def _gemini_media_adapter(request: dict) -> dict:
    """Generate images via Gemini Imagen 3 API."""
    import base64
    import uuid

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY not configured"}

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    req_type = request.get("type", "image")

    if req_type != "image":
        return {"success": False, "error": f"Gemini adapter only supports image generation, got: {req_type}"}

    # Gemini Imagen via predict endpoint; model is selectable per request.
    model = params.get("model") or "imagen-3.0-generate-002"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={api_key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": params.get("aspect_ratio", "1:1"),
            "safetyFilterLevel": "block_few",
        },
    }

    start = time.time()
    resp = requests.post(url, json=payload, timeout=60)
    duration_ms = int((time.time() - start) * 1000)

    if resp.status_code != 200:
        return {"success": False, "error": f"Gemini API error {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    predictions = data.get("predictions", [])
    if not predictions:
        return {"success": False, "error": "Gemini returned no predictions"}

    img_b64 = predictions[0].get("bytesBase64Encoded", "")
    if not img_b64:
        return {"success": False, "error": "Gemini returned empty image data"}

    img_bytes = base64.b64decode(img_b64)

    # Save to disk
    from datetime import datetime

    date_str = datetime.now().strftime("%Y-%m-%d")
    file_uuid = str(uuid.uuid4())[:12]
    rel_dir = f"static/media/images/{date_str}"
    app_root = os.environ.get("FLASK_APP_ROOT", "/app")
    abs_dir = os.path.join(app_root, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    file_name = f"{file_uuid}.png"
    file_path = os.path.join(abs_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(img_bytes)

    return {
        "success": True,
        "file_path": f"/{rel_dir}/{file_name}",
        "metadata": {
            "provider": "gemini",
            "model": params.get("model") or "imagen-3.0-generate-002",
            "cost_usd": 0.0,
            "mime_type": "image/png",
            "file_size_bytes": len(img_bytes),
            "aspect_ratio": params.get("aspect_ratio", "1:1"),
            "duration_ms": duration_ms,
        },
    }


def _openai_image_adapter(request: dict) -> dict:
    """Generate images via OpenAI image API (DALL-E 3 / DALL-E 2)."""
    import base64
    import uuid

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "OPENAI_API_KEY not configured"}

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    model = params.get("model") or "dall-e-3"
    size = params.get("size", "1024x1024")
    quality = params.get("quality", "standard")
    style = params.get("style", "vivid")

    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "style": style,
        "response_format": "b64_json",
    }

    start = time.time()
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    duration_ms = int((time.time() - start) * 1000)

    if resp.status_code != 200:
        return {"success": False, "error": f"OpenAI API error {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    images = data.get("data", [])
    if not images:
        return {"success": False, "error": "OpenAI returned no images"}

    img_b64 = images[0].get("b64_json", "")
    revised_prompt = images[0].get("revised_prompt", prompt)
    img_bytes = base64.b64decode(img_b64)

    # Cost calculation
    cost_map = {
        "1024x1024": {"standard": 0.04, "hd": 0.08},
        "1024x1792": {"standard": 0.08, "hd": 0.12},
        "1792x1024": {"standard": 0.08, "hd": 0.12},
    }
    cost_usd = cost_map.get(size, {}).get(quality, 0.04)

    # Save to disk
    from datetime import datetime

    date_str = datetime.now().strftime("%Y-%m-%d")
    file_uuid = str(uuid.uuid4())[:12]
    rel_dir = f"static/media/images/{date_str}"
    app_root = os.environ.get("FLASK_APP_ROOT", "/app")
    abs_dir = os.path.join(app_root, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    file_name = f"{file_uuid}.png"
    file_path = os.path.join(abs_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(img_bytes)

    return {
        "success": True,
        "file_path": f"/{rel_dir}/{file_name}",
        "metadata": {
            "provider": "openai",
            "model": model,
            "cost_usd": cost_usd,
            "mime_type": "image/png",
            "file_size_bytes": len(img_bytes),
            "size": size,
            "quality": quality,
            "style": style,
            "revised_prompt": revised_prompt,
            "duration_ms": duration_ms,
        },
    }


def _local_tts_adapter(request: dict) -> dict:
    """Generate audio via local Kokoro/XTTS engines."""
    import uuid

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    voice = params.get("voice", "default")
    language = params.get("language", "en")

    # Call existing Voice DNA endpoint
    tts_url = "http://localhost:3000/api/voice/generate"
    payload = {
        "text": prompt,
        "speaker": voice,
        "language": language,
        "emotion": params.get("emotion", "neutral"),
    }

    try:
        start = time.time()
        resp = requests.post(tts_url, json=payload, timeout=30)
        duration_ms = int((time.time() - start) * 1000)

        if resp.status_code != 200:
            return {"success": False, "error": f"Local TTS error {resp.status_code}: {resp.text[:200]}"}

        audio_bytes = resp.content

        from datetime import datetime

        date_str = datetime.now().strftime("%Y-%m-%d")
        file_uuid = str(uuid.uuid4())[:12]
        rel_dir = f"static/media/audio/{date_str}"
        abs_dir = os.path.join("/mnt/archie_brain/platform_v2", rel_dir)
        os.makedirs(abs_dir, exist_ok=True)

        file_name = f"{file_uuid}.wav"
        file_path = os.path.join(abs_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(audio_bytes)

        return {
            "success": True,
            "file_path": f"/{rel_dir}/{file_name}",
            "metadata": {
                "provider": "local_tts",
                "model": "kokoro" if language == "en" else "xtts_v2",
                "cost_usd": 0.0,
                "mime_type": "audio/wav",
                "file_size_bytes": len(audio_bytes),
                "language": language,
                "voice": voice,
                "duration_ms": duration_ms,
            },
        }
    except requests.ConnectionError:
        return {"success": False, "error": "Local TTS service unavailable"}


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


# ============================================================================
# Free-Tier Image Generation Adapters (Project #164)
# ============================================================================


def _huggingface_image_adapter(request: dict) -> dict:
    """Generate image via HuggingFace Inference API (free tier, rate-limited).

    Uses stabilityai/stable-diffusion-xl-base-1.0 by default.
    """
    import uuid
    from datetime import date

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    model = params.get("model", "stabilityai/stable-diffusion-xl-base-1.0")

    api_key = os.getenv("HF_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "HF_API_KEY not configured"}

    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(url, json={"inputs": prompt}, headers=headers, timeout=120)
        if resp.status_code == 200:
            image_bytes = resp.content
            date_dir = date.today().strftime("%Y-%m-%d")
            save_dir = os.path.join("static", "media", "images", date_dir)
            os.makedirs(save_dir, exist_ok=True)
            filename = f"hf_{uuid.uuid4().hex[:8]}.png"
            file_path = os.path.join(save_dir, filename)
            with open(file_path, "wb") as f:
                f.write(image_bytes)

            return {
                "success": True,
                "file_path": file_path,
                "model": model,
                "provider": "huggingface",
                "cost_usd": 0.0,
                "metadata": {"model": model, "prompt": prompt[:100]},
            }
        else:
            return {"success": False, "error": f"HF API returned {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": f"HuggingFace: {e}"}


def _cloudflare_image_adapter(request: dict) -> dict:
    """Generate image via Cloudflare Workers AI (free tier, 10K/day).

    Uses @cf/stabilityai/stable-diffusion-xl-base-1.0 by default.
    """
    import uuid
    from datetime import date

    prompt = request.get("prompt", "")
    params = request.get("params", {})

    api_key = os.getenv("CF_AI_API_KEY", "")
    account_id = os.getenv("CF_ACCOUNT_ID", "")
    if not api_key or not account_id:
        return {"success": False, "error": "CF_AI_API_KEY or CF_ACCOUNT_ID not configured"}

    model = params.get("model", "@cf/stabilityai/stable-diffusion-xl-base-1.0")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(url, json={"prompt": prompt}, headers=headers, timeout=120)
        if resp.status_code == 200:
            image_bytes = resp.content
            date_dir = date.today().strftime("%Y-%m-%d")
            save_dir = os.path.join("static", "media", "images", date_dir)
            os.makedirs(save_dir, exist_ok=True)
            filename = f"cf_{uuid.uuid4().hex[:8]}.png"
            file_path = os.path.join(save_dir, filename)
            with open(file_path, "wb") as f:
                f.write(image_bytes)

            return {
                "success": True,
                "file_path": file_path,
                "model": model,
                "provider": "cloudflare_ai",
                "cost_usd": 0.0,
                "metadata": {"model": model, "prompt": prompt[:100]},
            }
        else:
            return {"success": False, "error": f"Cloudflare AI returned {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": f"Cloudflare: {e}"}


def _together_image_adapter(request: dict) -> dict:
    """Generate image via Together AI (has SDXL and Flux models).

    Free credits on signup, then pay-per-use (~$0.003/image).
    """
    import base64
    import uuid
    from datetime import date

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    model = params.get("model", "stabilityai/stable-diffusion-xl-base-1.0")
    width = params.get("width", 1024)
    height = params.get("height", 1024)

    api_key = os.getenv("TOGETHER_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "TOGETHER_API_KEY not configured"}

    url = "https://api.together.xyz/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            url,
            json={
                "model": model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "n": 1,
                "response_format": "b64_json",
            },
            headers=headers,
            timeout=120,
        )
        if resp.status_code == 200:
            resp_data = resp.json()
            b64_data = resp_data.get("data", [{}])[0].get("b64_json", "")
            if not b64_data:
                return {"success": False, "error": "Together: empty image response"}

            image_bytes = base64.b64decode(b64_data)
            date_dir = date.today().strftime("%Y-%m-%d")
            save_dir = os.path.join("static", "media", "images", date_dir)
            os.makedirs(save_dir, exist_ok=True)
            filename = f"together_{uuid.uuid4().hex[:8]}.png"
            file_path = os.path.join(save_dir, filename)
            with open(file_path, "wb") as f:
                f.write(image_bytes)

            return {
                "success": True,
                "file_path": file_path,
                "model": model,
                "provider": "together",
                "cost_usd": 0.003,
                "metadata": {"model": model, "prompt": prompt[:100]},
            }
        else:
            return {"success": False, "error": f"Together AI returned {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": f"Together: {e}"}


def _pollinations_image_adapter(request: dict) -> dict:
    """Generate image via Pollinations.ai — free, no auth required.

    API: GET https://image.pollinations.ai/prompt/<urlencoded>?width=...&height=...&model=flux&nologo=true
    Returns image binary directly.
    """
    import urllib.parse
    import uuid
    from datetime import date

    prompt = request.get("prompt", "")
    params = request.get("params", {})
    model = params.get("model", "flux")  # flux | flux-realism | flux-anime | turbo
    width = params.get("width", 1024)
    height = params.get("height", 1024)
    seed = params.get("seed", -1)

    if not prompt:
        return {"success": False, "error": "Pollinations: empty prompt"}

    encoded = urllib.parse.quote(prompt, safe="")
    query = f"width={width}&height={height}&model={model}&nologo=true"
    if seed and seed > 0:
        query += f"&seed={seed}"
    url = f"https://image.pollinations.ai/prompt/{encoded}?{query}"

    start = time.time()
    try:
        resp = requests.get(url, timeout=120)
        duration_ms = int((time.time() - start) * 1000)
    except Exception as e:
        return {"success": False, "error": f"Pollinations request failed: {e}"}

    if resp.status_code != 200:
        return {"success": False, "error": f"Pollinations {resp.status_code}: {resp.text[:200]}"}

    image_bytes = resp.content
    if not image_bytes or len(image_bytes) < 1024:
        return {"success": False, "error": f"Pollinations returned empty/tiny response ({len(image_bytes)} bytes)"}

    date_str = date.today().strftime("%Y-%m-%d")
    rel_dir = f"static/media/images/{date_str}"
    app_root = os.environ.get("FLASK_APP_ROOT", "/app")
    abs_dir = os.path.join(app_root, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    file_name = f"pollinations_{uuid.uuid4().hex[:12]}.png"
    file_path = os.path.join(abs_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(image_bytes)

    return {
        "success": True,
        "file_path": f"/{rel_dir}/{file_name}",
        "metadata": {
            "provider": "pollinations",
            "model": model,
            "cost_usd": 0.0,
            "mime_type": "image/png",
            "file_size_bytes": len(image_bytes),
            "width": width,
            "height": height,
            "duration_ms": duration_ms,
        },
    }
