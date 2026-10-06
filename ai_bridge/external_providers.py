"""
External AI Provider Integration — Dynamic DB-Driven
Supports any OpenAI-compatible provider via contractor_providers table.
Legacy constants kept as fallback if DB is unreachable.

All functions return: {success, response, model, provider, prompt_tokens, completion_tokens, cost_usd}
"""

import calendar
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
                   models, rate_limits, is_active, capabilities,
                   dispatchable, provider_class
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
        # Both switches required. `is_active` = configured; `dispatchable` = the operator
        # has allowed routing here. The second is the one that makes "never dispatch a
        # paid provider unless enabled" true in code rather than by habit.
        if capability in caps and provider.get("is_active", False) and provider.get("dispatchable", False):
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
                    "provider_class": provider.get("provider_class"),
                    "dispatchable": bool(provider.get("dispatchable", False)),
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
        # `dispatchable` is the separate operator switch: a provider can be fully
        # configured (key present, probe passing) and still receive nothing. Until it is
        # flipped, it must not appear as a routing candidate at all — otherwise "never
        # dispatch unless enabled" is only true by convention.
        if not provider.get("dispatchable", False):
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


#: Monthly-budget bands, as a fraction of the configured limit.
#:
#:   warn  — dispatch continues, but the operator is told. Without this the only signal was
#:           the refusal at 100%, i.e. the budget was already spent before anyone heard.
#:   block — dispatch stops with headroom still intact, so an in-flight task can finish and
#:           the month does not overshoot. At 100% there is nothing left to protect.
#:
#: The stop is 95% rather than 100% deliberately. Combined with `check_weekly_budget`'s 10%
#: safety margin (#3659), that leaves roughly 15% visible when a warning fires.
BUDGET_WARN_FRACTION = 0.80
BUDGET_BLOCK_FRACTION = 0.95

#: Used when a provider has no configured budget. Matches the historical default this
#: function has always applied, named explicitly so it is a decision and not an accident.
DEFAULT_MONTHLY_BUDGET_USD = 10.0

#: Returned when the budget query itself fails. Fail-OPEN is correct — a database blip must
#: not block a provider that would otherwise work — but it used to be indistinguishable from
#: "no budget configured", which meant a broken query silently disabled the budget entirely.
#: Logging makes the difference visible.
BUDGET_UNKNOWN = "unknown"


def _budget_period_start(reset_day, now=None):
    """Start of the budget period containing `now`, per `budget_reset_day`.

    A budget period runs from its reset day-of-month to the day before the next one. So the
    start is the most recent occurrence of that day at or before `now`; if this month's has
    not arrived yet, the period began last month.

    Clamped to the length of the month. `budget_reset_day = 31` in February is the case that
    breaks naive construction — `replace(day=31)` raises ValueError, and a helper that raises
    inside the budget read takes the fail-open path and silently disables the guard. That is
    the same failure this module already documents for a broken query.

    Naive local time, deliberately. `budget_reset_day` is an operator setting with no timezone
    and the only comparable column (`last_reset_at`) is timestamptz; reading both in the same
    naive frame keeps the comparison meaningful instead of correct-but-confusing.
    """
    from datetime import datetime

    if now is None:
        now = datetime.now()
    try:
        day = int(reset_day)
    except (TypeError, ValueError):
        day = 1
    # Above 31 is not a day of any month, so it is a configuration error rather than an end-of-
    # month request. Falls back to the 1st, matching the fail-safe default used everywhere else
    # in this module. Within 1..31 a short month clamps, which is the case day=31 exists for.
    if day < 1 or day > 31:
        day = 1

    this_month_len = calendar.monthrange(now.year, now.month)[1]
    start = now.replace(day=min(day, this_month_len), hour=0, minute=0, second=0, microsecond=0)
    if start > now:
        year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        prev_len = calendar.monthrange(year, month)[1]
        start = now.replace(
            year=year,
            month=month,
            day=min(day, prev_len),
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    # Attach the local offset when naive, so the result compares against a TIMESTAMPTZ column.
    return start.astimezone() if start.tzinfo is None else start


def _budget_used_for_current_period(used, last_reset_at, reset_day, now=None) -> float:
    """The spend that counts against the CURRENT period.

    Zero once the period has rolled over. The stored counter is deliberately NOT zeroed here:
    reading should not write, and `_update_cost` performs the reset on the next accumulate.
    Until then the stale total is simply not counted, which is what lets the bands recover.
    """
    # Both sides must be timezone-COMPARABLE. `last_reset_at` is TIMESTAMPTZ, so psycopg2
    # returns an aware datetime, while the period start is derived from operator-configured
    # local-time day-of-month and is naive. Comparing the two raises TypeError, which is caught
    # one frame up and fails OPEN — silently disabling the whole budget guard.
    #
    # This is not hypothetical: it is exactly what happened on the first live run against the
    # real column, after every unit test had passed. Those tests all used naive datetimes, so
    # the mismatch was invisible until a real TIMESTAMPTZ met a naive boundary.
    if last_reset_at is not None and last_reset_at.tzinfo is None:
        last_reset_at = last_reset_at.astimezone()
    if last_reset_at is None:
        # No period stamp: the period is UNKNOWN, not empty. Counting the stored total is the
        # conservative reading — treating it as zero would report $0.00 for a provider that had
        # genuinely spent, and under-reporting spend is the one direction a money guard must
        # never be wrong in. Migration 489 stamps existing rows so this stops being reachable.
        return float(used or 0.0)
    if last_reset_at < _budget_period_start(reset_day, now):
        return 0.0
    return float(used or 0.0)


def monthly_budget_status(provider: str) -> dict:
    """Three-state monthly budget read: ok / warn / block.

    Returns ``{provider, band, limit, used, fraction, reason}``.

    ``band`` is one of ``ok`` | ``warn`` | ``block`` | ``unknown`` | ``unconfigured``.

    Fail-open by design. A provider with no budget row is ``unconfigured`` and allowed; a
    provider whose budget query raises is ``unknown`` and allowed, but the failure is logged
    so a persistently broken query cannot masquerade as an unlimited budget.
    """
    try:
        from database import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT monthly_budget_usd, current_month_cost_usd,
                       budget_reset_day, last_reset_at
                  FROM external_api_keys
                 WHERE provider = %s
                """,
                (provider,),
            )
            row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return {
                "provider": provider,
                "band": "unconfigured",
                "limit": None,
                "used": None,
                "fraction": None,
                "reason": "no budget row — allowed",
            }

        raw_limit, raw_used, reset_day, last_reset_at = row[0], row[1], row[2], row[3]
        limit = float(raw_limit) if raw_limit is not None else DEFAULT_MONTHLY_BUDGET_USD
        # Only the CURRENT period's spend counts. Before this the counter was monotonic for the
        # life of the install, so a provider that once crossed 95% stayed `block` forever — the
        # bands could warn but never recover, which is not a budget guard.
        used = _budget_used_for_current_period(raw_used, last_reset_at, reset_day)
        fraction = (used / limit) if limit > 0 else 0.0

        if fraction >= BUDGET_BLOCK_FRACTION:
            band = "block"
        elif fraction >= BUDGET_WARN_FRACTION:
            band = "warn"
        else:
            band = "ok"

        return {
            "provider": provider,
            "band": band,
            "limit": limit,
            "used": used,
            "fraction": round(fraction, 4),
            "reason": (
                f"{fraction * 100:.1f}% of ${limit:.2f} used" if band != "unconfigured" else "no budget row — allowed"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silently
        logger.warning(
            "monthly_budget_status(%s): budget query failed, allowing fail-open (%s: %s)",
            provider,
            exc.__class__.__name__,
            exc,
        )
        return {
            "provider": provider,
            "band": BUDGET_UNKNOWN,
            "limit": None,
            "used": None,
            "fraction": None,
            "reason": f"budget query failed ({exc.__class__.__name__}) — allowed",
        }


def _check_budget(provider: str) -> bool:
    """True unless the provider is in the `block` band.

    Everything not ``block`` is allowed, including ``warn`` and ``unknown`` — the warn band
    is a notification, not a refusal.

    This remains the seam the call site goes through on purpose. Tests neutralise it with
    `monkeypatch.setattr(ep, "_check_budget", lambda p: True)` to stay hermetic; had the
    call site switched to calling `monthly_budget_status` directly, those patches would have
    become silent no-ops and the tests would have quietly started hitting a real database.
    """
    return monthly_budget_status(provider)["band"] != "block"


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


def _reset_day_for(provider: str) -> int:
    """This provider's configured reset day, defaulting to the 1st.

    Read separately so the cost UPDATE stays one atomic statement. Fails soft to day 1: an
    unreadable reset day must not stop cost being recorded, which is the one thing this
    function cannot afford to lose.
    """
    try:
        from database import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT budget_reset_day FROM external_api_keys WHERE provider = %s",
                (provider,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        return int(row[0]) if row and row[0] is not None else 1
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reset-day lookup failed for %s (%s: %s) — defaulting to the 1st",
            provider,
            exc.__class__.__name__,
            exc,
        )
        return 1


def _warn_threshold_for(provider: str) -> tuple[float, float]:
    """(limit, warn_threshold_usd) for a provider, or (inf, inf) to disable the warning.

    A provider with no budget row gets `inf` thresholds, so the claim can never fire. Failing
    toward "no warning" is right: there is no limit to be near, so there is nothing to announce,
    and an operator who has not configured a budget should not receive budget notifications.

    A zero or negative limit also gets `inf`. Such a provider is governed entirely by the gate,
    which already refuses its traffic; a warning about a budget that is already fully spent every
    single cycle is pure noise.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute(
                "SELECT monthly_budget_usd FROM external_api_keys WHERE provider = %s",
                (provider,),
            )
            row = cur.fetchone()
        if not row or row["monthly_budget_usd"] is None:
            return float("inf"), float("inf")
        limit = float(row["monthly_budget_usd"])
        if limit <= 0:
            return float("inf"), float("inf")
        return limit, limit * BUDGET_WARN_FRACTION
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "budget warn threshold unavailable for %s (%s: %s) — skipping the warning this cycle",
            provider,
            exc.__class__.__name__,
            exc,
        )
        return float("inf"), float("inf")


def _notify_budget_warn(provider: str, used: float, limit: float) -> None:
    """Announce that a provider entered the monthly warn band. Once per period.

    Observability must never be the thing that breaks a dispatch, so every failure here is logged
    and swallowed. The claim in `_update_cost` is already committed by this point, so a failure
    means no repeat attempt — the trade is deliberate and documented there.
    """
    try:
        from database import get_db_cursor

        pct = (used / limit * 100.0) if limit > 0 else 0.0
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO system_notifications
                    (type, title, message, source, visibility, priority, telegram_forwarded)
                VALUES (%s, %s, %s, 'contractor_budget', 'admin', %s, %s)
                """,
                (
                    "budget_warning",
                    f"Budget warning: {provider} at {pct:.0f}% of its monthly limit",
                    (
                        f"{provider} has used ${used:.2f} of its ${limit:.2f} monthly budget "
                        f"({pct:.0f}%). Traffic is still allowed; requests will be refused at "
                        f"{BUDGET_BLOCK_FRACTION * 100:.0f}%. Announced once per budget period."
                    ),
                    "high",
                    True,
                ),
            )
        logger.info("budget warning issued for %s at %.0f%% of limit", provider, pct)
    except Exception as exc:  # noqa: BLE001
        logger.warning("budget warn notification failed for %s (%s: %s)", provider, exc.__class__.__name__, exc)


def _update_cost(provider: str, cost: float):
    """Add cost to current month tracking."""
    try:
        from database import get_db

        conn = get_db()
        cur = conn.cursor()
        # Reset-and-set or accumulate, decided INSIDE the statement so there is no
        # read-then-write race between concurrent dispatches both judging the period current.
        #
        #   period rolled  -> the new cost IS the period total, and the stamp moves to now
        #   period current -> accumulate onto the running total, stamp untouched
        #
        # A stale counter is never carried forward, which is what lets a provider that hit
        # `block` last month come back this month.
        period_start = _budget_period_start(_reset_day_for(provider))
        # The limit decides whether this crossing deserves a warning at all, so it is read here
        # rather than left to `monthly_budget_status` afterwards — the claim has to be part of
        # this transaction, and the threshold has to be known before the UPDATE runs.
        limit, warn_threshold = _warn_threshold_for(provider)
        cur.execute(
            """
            UPDATE external_api_keys
               SET current_month_cost_usd = CASE
                       WHEN last_reset_at IS NULL OR last_reset_at < %(period)s
                       THEN %(cost)s
                       ELSE current_month_cost_usd + %(cost)s
                   END,
                   last_reset_at = CASE
                       WHEN last_reset_at IS NULL OR last_reset_at < %(period)s
                       THEN NOW()
                       ELSE last_reset_at
                   END,
                   updated_at = NOW()
             WHERE provider = %(provider)s
            """,
            {"period": period_start, "cost": cost, "provider": provider},
        )

        # Claim the warn notification, atomically, in the SAME transaction as the increment.
        #
        # Two dispatches can cross 80% in the same instant. Without a claim, both read "not
        # warned yet", both notify, and the operator gets the same alert twice — which is the
        # entire problem this is solving, just faster. `WHERE budget_warned_at IS NULL OR <` makes
        # exactly one UPDATE report rowcount 1, and that caller alone notifies.
        #
        # The period comparison IS the reset. A stamp from last month fails it and the next
        # crossing warns again, so the period roll above deliberately does NOT clear the column:
        # one mechanism, not two that can disagree.
        #
        # NULL is included because NULL means "never warned", and silently treating that as
        # "already warned" would mean a provider that silently crossed 80% was never announced.
        cur.execute(
            """
            UPDATE external_api_keys
               SET budget_warned_at = NOW()
             WHERE provider = %(provider)s
               AND current_month_cost_usd >= %(threshold)s
               AND (budget_warned_at IS NULL OR budget_warned_at < %(period)s)
         RETURNING current_month_cost_usd
            """,
            {
                "provider": provider,
                "period": period_start,
                "threshold": warn_threshold,
            },
        )
        claimed = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if claimed:
            # After the commit on purpose: the claim is durable before the alert exists, so a
            # failed notify cannot cause a repeat on the next dispatch. Failing toward silence
            # is right here — a duplicate warning is noisier than a missed one, and the status
            # function still reports `warn` so nothing is actually hidden from an operator who
            # looks.
            _notify_budget_warn(provider, float(claimed[0]), limit)
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


def is_auto_router(model_id) -> bool:
    """True for a gateway auto-routing id (`auto`, `auto/<variant>[:<tier>]`).

    Such an id names a POLICY, not a model. It must never be recorded as
    task_execution_log.model_used (#6653) — that column is the accounting spine.
    """
    m = str(model_id).strip().lower() if model_id else ""
    return m == "auto" or m.startswith("auto/")


def resolve_served_model(data: dict, requested: str) -> tuple[str, bool]:
    """Which upstream model actually served an OpenAI-compatible response?

    OpenAI-compatible gateways echo the CONCRETE served model in the body's
    ``model`` field. Returns ``(model_id, resolved)``: ``resolved`` is False only
    when the best id we have is still an auto-router — the caller then records
    the requested id AND the flag, so a live check can catch a gateway that does
    not echo the served model instead of silently logging ``auto``.
    """
    body_model = (data or {}).get("model") if isinstance(data, dict) else None
    body_model = str(body_model).strip() if body_model else ""
    if body_model and not is_auto_router(body_model):
        return body_model, True
    req = (requested or "").strip()
    return req, not is_auto_router(req)


def _omniroute_quota_gate(model: str, base_url: str) -> Dict:
    """DS9 Phase 3 — consume the OmniRoute quota hint at the gateway call site,
    BEFORE the POST leaves the hub. Only gates providers fronted by the
    self-hosted OmniRoute gateway (its base_url); everything else returns allow.
    Fail-open: a quota error/short-circuit NEVER blocks a call that would
    otherwise work — unknown upstream / bad DB / exception all allow. An
    exhausted upstream refuses with the same short-circuit shape callers already
    fall back on from the weekly-budget gate (#3659). Work-control
    'omniroute_quota_consume' (default ON) drains the gate without a deploy.
    Called by _call_openai_compatible; kept a module-level function so callers
    and tests can stub the whole decision cleanly."""
    if not base_url or "omniroute" not in str(base_url).lower():
        return {"allow": True, "reason": "not an omniroute-fronted provider"}
    try:
        from services.work_control_service import is_enabled

        if not is_enabled("omniroute_quota_consume", default=True):
            return {"allow": True, "reason": "work-control gate disabled"}
    except Exception:  # noqa: BLE001 — fail-open
        pass
    try:
        from services.omniroute_quota_service import gate_upstream, upstream_for_model

        upstream = upstream_for_model(model)
        return gate_upstream(upstream) if upstream else {"allow": True, "reason": "no upstream mapping"}
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("[OmniRoute quota] gate check failed open: %s", exc)
        return {"allow": True, "reason": "quota unavailable, fail-open"}


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

    # The operator's routing switch, enforced at the CALL SITE as well as in the selector.
    # Gating only the selector would leave `call_external(provider=...)` — which callers do
    # use directly — as an open door to any configured provider, and "never dispatch a paid
    # provider unless enabled" would be true only of the path someone remembered to check.
    _cfg = _get_provider_config(provider)
    if _cfg is not None and not _cfg.get("dispatchable", False):
        return {
            "success": False,
            "error": (
                f"Provider {provider} is configured but not enabled for dispatch "
                "(contractor_providers.dispatchable is false)"
            ),
            "provider": provider,
            "dispatchable": False,
        }

    api_key = _get_api_key(provider)
    if not api_key:
        return {"success": False, "error": f"No API key for {provider}", "provider": provider}

    # Through `_check_budget`, not `monthly_budget_status`, so the existing monkeypatch
    # seam stays load-bearing. The detail dict is fetched separately and only for the
    # message — on the happy path that is one extra query, which is the cost of being able
    # to say WHY rather than just that it failed.
    if not _check_budget(provider):
        _budget = monthly_budget_status(provider)
        return {
            "success": False,
            "error": f"Monthly budget {BUDGET_BLOCK_FRACTION:.0%} reached for {provider} "
            f"({_budget['reason']}) — dispatch blocked with headroom intact",
            "provider": provider,
            "budget": _budget,
        }

    # #3658: per-provider WEEKLY free-tier request cap (rate_limits.free.weekly_limit).
    # Fail-open, and a no-op for providers without a free weekly_limit configured.
    if not check_weekly_budget(provider):
        return {
            "success": False,
            "error": f"Weekly free-tier limit reached for {provider}",
            "provider": provider,
            "weekly_budget": weekly_budget_status(provider),
        }

    # DS9 Phase 3 — consume the OmniRoute quota hint at the gateway call site.
    # Fail-open; only omniroute-fronted providers are gated (see helper).
    gate = _omniroute_quota_gate(model, base_url)
    if gate.get("status") == "degraded":
        logger.warning("[OmniRoute quota] %s — calling anyway (degraded, not blocked)", gate.get("reason"))
    if not gate.get("allow", True):
        logger.warning("[OmniRoute quota] %s — refusing call, fall back to local", gate.get("reason"))
        return {
            "success": False,
            "error": f"OmniRoute quota: {gate.get('reason')}",
            "provider": provider,
            "quota_status": gate,
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
        # #6653: record what SERVED the call, not what we asked for. An auto-routing
        # gateway (OmniRoute `auto/*`) resolves to a concrete upstream model per call.
        served_model, served_resolved = resolve_served_model(data, model)
        cost = _calculate_cost(served_model, prompt_tokens, completion_tokens)

        _update_cost(provider, cost)
        _log_usage(provider, served_model, prompt_tokens, completion_tokens, cost)

        return {
            "success": True,
            "response": choice["message"]["content"],
            "model": served_model,
            "requested_model": model,
            "served_model_resolved": served_resolved,
            "routing_decision": resp.headers.get("X-OmniRoute-Decision"),
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
    # The operator's two switches, enforced HERE and not only in the text selector.
    #
    # `_call_openai_compatible` — the shared text egress — already does this, and explains why in
    # its own comment: gating only the selector leaves any caller that names a provider directly as
    # an open door. Media was exactly that open door. The Media Studio cloud path checks the master cloud toggle, the capability
    # allowlist and the weekly free budget — three real gates — and then walked straight past the
    # per-provider switch an operator flips in the Contractors tab. Turning routing OFF for
    # `gemini` or `together` changed the text fleet and left media spending.
    #
    # Deliberately first, before the adapter lookup: the refusal should name the switch the
    # operator just changed, not "no media adapter", and either way nothing is dispatched.
    #
    # A provider with NO row is not gated, matching `_call_openai_compatible`. `local_tts` is the
    # case that
    # matters: it is local, free, and was never a contractor. Gating it on a config that does not
    # exist would break local text-to-speech to enforce a switch it was never subject to.
    _cfg = _get_provider_config(provider_key)
    if _cfg is not None:
        if not _cfg.get("is_active", False):
            return {
                "success": False,
                "error": (f"Provider {provider_key} is not configured " "(contractor_providers.is_active is false)"),
                "provider": provider_key,
                "is_active": False,
            }
        if not _cfg.get("dispatchable", False):
            return {
                "success": False,
                "error": (
                    f"Provider {provider_key} is configured but not enabled for dispatch "
                    "(contractor_providers.dispatchable is false)"
                ),
                "provider": provider_key,
                "dispatchable": False,
            }

    adapters = {
        "gemini": _gemini_media_adapter,
        "openai": _openai_image_adapter,
        "local_tts": _local_tts_adapter,
        "huggingface": _huggingface_image_adapter,
        "cloudflare_ai": _cloudflare_image_adapter,
        "together": _together_image_adapter,
        "pollinations": _pollinations_image_adapter,
        "omniroute": _omniroute_image_adapter,
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
    negative_prompt = request.get("negative_prompt") or params.get("negative_prompt", "")

    if not prompt:
        return {"success": False, "error": "Pollinations: empty prompt"}

    encoded = urllib.parse.quote(prompt, safe="")
    query = f"width={width}&height={height}&model={model}&nologo=true&private=true"
    if seed and seed > 0:
        query += f"&seed={seed}"
    if negative_prompt:
        query += "&" + urllib.parse.urlencode({"negative_prompt": negative_prompt})
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


def _omniroute_image_adapter(request: dict) -> dict:
    import base64
    import uuid
    from datetime import date

    prompt = request.get("prompt", "")
    negative_prompt = request.get("negative_prompt") or ""
    params = request.get("params") or {}
    if negative_prompt:
        prompt = f"{prompt}. Avoid: {negative_prompt}"
    model = params.get("model") or os.getenv("MEDIA_STUDIO_OMNIROUTE_IMAGE_MODEL", "aihorde/Realistic Vision")
    width = int(params.get("width", 1024))
    height = int(params.get("height", 1024))
    base_url = os.getenv("OMNIROUTE_BASE_URL", "http://omniroute:20128/v1").rstrip("/")
    api_key = os.getenv("OMNIROUTE_API_KEY", "").strip()
    if not api_key:
        return {"success": False, "error": "OMNIROUTE_API_KEY not configured"}
    if not prompt:
        return {"success": False, "error": "OmniRoute: empty prompt"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    start = time.time()
    try:
        response = requests.post(
            f"{base_url}/images/generations",
            headers=headers,
            json={"model": model, "prompt": prompt, "n": 1, "size": f"{width}x{height}"},
            timeout=int(os.getenv("OMNIROUTE_IMAGE_TIMEOUT", "180")),
        )
    except Exception as exc:
        return {"success": False, "error": f"OmniRoute request failed: {exc}"}

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"OmniRoute API error {response.status_code}: {response.text[:300]}",
        }

    try:
        payload = response.json()
    except Exception as exc:
        return {"success": False, "error": f"OmniRoute returned invalid JSON: {exc}"}

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        items = [payload] if isinstance(payload, dict) else []
    item = items[0] if items and isinstance(items[0], dict) else {}
    encoded = item.get("b64_json") or item.get("image_base64") or item.get("image")
    image_url = item.get("url") or item.get("image_url")
    image_bytes = None

    if isinstance(encoded, str) and encoded:
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        try:
            image_bytes = base64.b64decode(encoded)
        except Exception:
            image_bytes = None
    elif isinstance(image_url, str) and image_url:
        try:
            if image_url.startswith("data:") and "," in image_url:
                image_bytes = base64.b64decode(image_url.split(",", 1)[1])
            else:
                image_response = requests.get(image_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
                image_response.raise_for_status()
                image_bytes = image_response.content
        except Exception as exc:
            return {"success": False, "error": f"OmniRoute image download failed: {exc}"}

    if not image_bytes or len(image_bytes) < 1024:
        return {"success": False, "error": "OmniRoute returned no usable image data"}

    date_str = date.today().strftime("%Y-%m-%d")
    rel_dir = f"static/media/images/{date_str}"
    app_root = os.environ.get("FLASK_APP_ROOT", "/app")
    abs_dir = os.path.join(app_root, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    file_name = f"omniroute_{uuid.uuid4().hex[:12]}.png"
    file_path = os.path.join(abs_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(image_bytes)

    return {
        "success": True,
        "file_path": f"/{rel_dir}/{file_name}",
        "metadata": {
            "provider": "omniroute",
            "model": model,
            "cost_usd": 0.0,
            "mime_type": "image/png",
            "file_size_bytes": len(image_bytes),
            "width": width,
            "height": height,
            "duration_ms": int((time.time() - start) * 1000),
        },
    }
