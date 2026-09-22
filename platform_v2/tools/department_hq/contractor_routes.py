"""Department HQ — External contractor/provider management routes.

Migrated from Starbase/Fleet provider_routes.py (2026-04-08).
Manages external AI providers (outsourced work), API keys, budgets,
and contractor provider definitions.

ENDPOINTS:
  /api/contractors/providers              GET  — List providers with 24h stats
  /api/contractors/providers              POST — Add/update provider API key
  /api/contractors/providers/<p>/toggle   POST — Enable/disable provider
  /api/contractors/providers/<p>/models/<m>/toggle PUT — Toggle model routing
  /api/contractors/definitions            GET  — List contractor definitions
  /api/contractors/definitions            POST — Create/update contractor definition
  /api/contractors/omniroute-quota        GET  — Latest OmniRoute throttle snapshot per provider
"""

import json
import logging
import os

from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_contractor_routes(bp, admin_required):
    """Register contractor/external-provider routes on the department_hq blueprint."""

    @bp.route("/api/contractors/providers", methods=["GET"])
    @login_required
    def get_external_providers():
        """List external AI providers with 24h stats, model breakdowns, and tier positions.
        All provider metadata comes from the contractor_providers table (dynamic)."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # 1. Fetch all contractor_providers (single source of truth)
                cur.execute(
                    """
                    SELECT provider_key, display_name, base_url, default_model,
                           auth_method, auth_env_var, is_cloud_proxy, tier_position,
                           models, rate_limits, is_active
                    FROM contractor_providers
                    ORDER BY tier_position
                """
                )
                cp_rows = cur.fetchall()
                contractor_providers = {row["provider_key"]: dict(row) for row in cp_rows}

                # 2. Fetch DB-managed API keys from external_api_keys
                cur.execute(
                    """
                    SELECT id, provider, is_active, monthly_budget_usd, current_month_cost_usd,
                           budget_reset_day, account_tier, created_at, updated_at,
                           CASE WHEN api_key_encrypted IS NOT NULL AND api_key_encrypted != ''
                                THEN '****' || RIGHT(api_key_encrypted, 4) ELSE NULL END as key_hint
                    FROM external_api_keys
                    ORDER BY provider
                """
                )
                db_keys = {row["provider"]: dict(row) for row in cur.fetchall()}

                # 3. Fetch 24h usage stats grouped by model
                cur.execute(
                    """
                    SELECT model_name, provider,
                           COUNT(*) as requests,
                           COALESCE(SUM(cost_usd), 0) as cost,
                           COALESCE(AVG(response_ms), 0) as avg_latency_ms,
                           ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                                 / NULLIF(COUNT(*), 0), 1) as success_rate
                    FROM cloud_model_usage
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY model_name, provider
                """
                )
                stats_by_model = {}
                for row in cur.fetchall():
                    stats_by_model[row["model_name"]] = {
                        "requests": row["requests"],
                        "cost": float(row["cost"]),
                        "avg_latency_ms": round(float(row["avg_latency_ms"]), 1),
                        "success_rate": float(row["success_rate"]) if row["success_rate"] is not None else 100.0,
                    }

                # 3b. Session (2h) and weekly (7d) usage windows
                cur.execute(
                    """
                    SELECT model_name,
                           COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '2 hours') as session_requests,
                           COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as weekly_requests
                    FROM cloud_model_usage
                    GROUP BY model_name
                """
                )
                usage_windows = {}
                for row in cur.fetchall():
                    usage_windows[row["model_name"]] = {
                        "session_2h": row["session_requests"],
                        "weekly_7d": row["weekly_requests"],
                    }

                # 3c. All-time usage stats
                cur.execute(
                    """
                    SELECT model_name,
                           COUNT(*) as requests,
                           COALESCE(SUM(cost_usd), 0) as cost,
                           COALESCE(AVG(response_ms), 0) as avg_latency_ms,
                           ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                                 / NULLIF(COUNT(*), 0), 1) as success_rate,
                           MIN(created_at) as first_used,
                           MAX(created_at) as last_used
                    FROM cloud_model_usage
                    GROUP BY model_name
                """
                )
                alltime_by_model = {}
                for row in cur.fetchall():
                    alltime_by_model[row["model_name"]] = {
                        "requests": row["requests"],
                        "cost": float(row["cost"]),
                        "avg_latency_ms": round(float(row["avg_latency_ms"]), 1),
                        "success_rate": float(row["success_rate"]) if row["success_rate"] is not None else 100.0,
                        "first_used": row["first_used"].isoformat() if row["first_used"] else None,
                        "last_used": row["last_used"].isoformat() if row["last_used"] else None,
                    }

                # 4. Per-model disabled state from platform_settings
                cur.execute(
                    """
                    SELECT key, value FROM platform_settings
                    WHERE key LIKE 'model_disabled:%%'
                """
                )
                disabled_models = set()
                for row in cur.fetchall():
                    model_name = row["key"].replace("model_disabled:", "", 1)
                    if row["value"].lower() == "true":
                        disabled_models.add(model_name)

                # 5. C.R.E.E.D. governance events from last 24h
                cur.execute(
                    """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN outcome = 'blocked' THEN 1 ELSE 0 END) as blocked
                    FROM governance_audit_log
                    WHERE timestamp >= NOW() - INTERVAL '24 hours'
                """
                )
                creed_row = cur.fetchone()
                creed_total_24h = creed_row["total"] if creed_row else 0
                creed_blocked_24h = creed_row["blocked"] if creed_row and creed_row["blocked"] else 0

                # 6. Ollama cloud API key check
                ollama_api_key_set = bool(os.environ.get("OLLAMA_API_KEY", "").strip())

                # 7. Build unified response — iterate all contractor_providers
                result = []
                for provider_key, cp in contractor_providers.items():
                    db_row = db_keys.get(provider_key)
                    models_def = cp.get("models") or []
                    if isinstance(models_def, str):
                        models_def = json.loads(models_def)
                    rate_limits_def = cp.get("rate_limits") or {}
                    if isinstance(rate_limits_def, str):
                        rate_limits_def = json.loads(rate_limits_def)
                    tier_pos = cp.get("tier_position", 99)

                    # Determine active state + budget
                    account_tier = db_row.get("account_tier", "free") if db_row else "free"
                    rate_limits = rate_limits_def.get(account_tier, rate_limits_def.get("free", {}))

                    if cp.get("is_cloud_proxy"):
                        is_active = (
                            db_row["is_active"] if db_row else (cp.get("is_active", False) and ollama_api_key_set)
                        )
                        auth_method = "OLLAMA_API_KEY env var"
                        source = "cloud_config"
                    else:
                        is_active = db_row["is_active"] if db_row else False
                        auth_method = (cp.get("auth_method") or "api_key").replace("_", " ").title()
                        source = "db"

                    monthly_budget = (
                        float(db_row["monthly_budget_usd"]) if db_row and db_row.get("monthly_budget_usd") else 0.0
                    )
                    current_cost = (
                        float(db_row["current_month_cost_usd"])
                        if db_row and db_row.get("current_month_cost_usd")
                        else 0.0
                    )
                    budget_pct = round((current_cost / monthly_budget) * 100, 1) if monthly_budget > 0 else 0.0

                    # Build per-model output
                    provider_requests = 0
                    provider_cost = 0.0
                    provider_latency_sum = 0.0
                    provider_success_sum = 0.0
                    provider_models_with_stats = 0

                    models_out = []
                    tier_positions = {}
                    for m in models_def:
                        m_name = m["name"]
                        m_stats = stats_by_model.get(
                            m_name,
                            {"requests": 0, "cost": 0.0, "avg_latency_ms": 0.0, "success_rate": 100.0},
                        )
                        m_alltime = alltime_by_model.get(m_name, None)
                        m_windows = usage_windows.get(m_name, None)
                        if m_windows and rate_limits:
                            m_windows["session_limit"] = rate_limits.get("session_limit")
                            m_windows["weekly_limit"] = rate_limits.get("weekly_limit")
                        elif rate_limits:
                            m_windows = {
                                "session_2h": 0,
                                "weekly_7d": 0,
                                "session_limit": rate_limits.get("session_limit"),
                                "weekly_limit": rate_limits.get("weekly_limit"),
                            }
                        models_out.append(
                            {
                                "name": m_name,
                                "tier": provider_key,
                                "tier_position": tier_pos,
                                "enabled": m_name not in disabled_models,
                                "stats_24h": m_stats,
                                "stats_alltime": m_alltime,
                                "usage_windows": m_windows,
                            }
                        )
                        tier_positions[m_name] = tier_pos

                        provider_requests += m_stats["requests"]
                        provider_cost += m_stats["cost"]
                        if m_stats["requests"] > 0:
                            provider_latency_sum += m_stats["avg_latency_ms"]
                            provider_success_sum += m_stats["success_rate"]
                            provider_models_with_stats += 1

                    avg_latency = (
                        round(provider_latency_sum / provider_models_with_stats, 1)
                        if provider_models_with_stats > 0
                        else 0.0
                    )
                    avg_success = (
                        round(provider_success_sum / provider_models_with_stats, 1)
                        if provider_models_with_stats > 0
                        else 100.0
                    )

                    # Use DB cost if available, else aggregated
                    if not current_cost and provider_cost > 0:
                        current_cost = round(provider_cost, 6)
                        budget_pct = round((current_cost / monthly_budget) * 100, 1) if monthly_budget > 0 else 0.0

                    entry = {
                        "provider": provider_key,
                        "display_name": cp.get("display_name", provider_key),
                        "is_active": is_active,
                        "account_tier": account_tier,
                        "monthly_budget_usd": monthly_budget,
                        "current_month_cost_usd": current_cost,
                        "budget_pct": budget_pct,
                        "source": source,
                        "auth_method": auth_method,
                        "key_hint": db_row.get("key_hint") if db_row else None,
                        "tier_positions": tier_positions,
                        "tier_position": tier_pos,
                        "is_cloud_proxy": cp.get("is_cloud_proxy", False),
                        "stats_24h": {
                            "requests": provider_requests,
                            "cost": round(provider_cost, 6),
                            "success_rate": avg_success,
                            "avg_latency_ms": avg_latency,
                        },
                        "models": models_out,
                    }
                    result.append(entry)

                return jsonify(
                    {
                        "success": True,
                        "providers": result,
                        "creed_total_24h": creed_total_24h,
                        "creed_blocked_24h": creed_blocked_24h,
                    }
                )
        except Exception as e:
            logger.error("Error listing external providers: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractors/providers", methods=["POST"])
    @admin_required
    def upsert_external_provider():
        """Add or update an external AI provider API key. Validates against contractor_providers table."""
        data = request.get_json() or {}
        provider = data.get("provider", "").strip().lower()
        api_key = data.get("api_key", "").strip()

        try:
            with get_db_cursor() as (conn, cur):
                # Validate provider exists in contractor_providers
                cur.execute(
                    "SELECT provider_key, is_cloud_proxy FROM contractor_providers WHERE provider_key = %s",
                    (provider,),
                )
                cp_row = cur.fetchone()
                if not cp_row:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Unknown provider: {provider}. Add it to Contractor Providers first.",
                            }
                        ),
                        400,
                    )

                # Cloud providers use OLLAMA_API_KEY from env
                if cp_row["is_cloud_proxy"]:
                    api_key = "OLLAMA_API_KEY"
                elif not api_key:
                    cur.execute(
                        "SELECT api_key_encrypted FROM external_api_keys WHERE provider = %s",
                        (provider,),
                    )
                    existing = cur.fetchone()
                    if not existing or not existing["api_key_encrypted"]:
                        return jsonify({"success": False, "error": "API key required"}), 400
                    api_key = existing["api_key_encrypted"]

                budget = data.get("monthly_budget_usd", 10.0)
                account_tier = data.get("account_tier", "free").strip().lower()
                valid_tiers = ("free", "pro", "pay_as_you_go", "enterprise", "max")
                if account_tier not in valid_tiers:
                    account_tier = "free"

                cur.execute(
                    """
                    INSERT INTO external_api_keys (provider, api_key_encrypted, monthly_budget_usd, account_tier, is_active)
                    VALUES (%s, %s, %s, %s, TRUE)
                    ON CONFLICT (provider) DO UPDATE SET
                        api_key_encrypted = %s, monthly_budget_usd = %s, account_tier = %s,
                        is_active = TRUE, updated_at = NOW()
                    RETURNING id, provider, is_active, monthly_budget_usd, account_tier
                """,
                    (provider, api_key, budget, account_tier, api_key, budget, account_tier),
                )
                row = cur.fetchone()

                # Invalidate external_providers cache
                try:
                    from ai_bridge.external_providers import invalidate_provider_cache

                    invalidate_provider_cache()
                except ImportError:
                    logger.warning("external_providers module not available for cache invalidation")

                return jsonify({"success": True, "provider": dict(row)})
        except Exception as e:
            logger.error("Error upserting external provider: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractors/providers/<provider>/toggle", methods=["POST"])
    @admin_required
    def toggle_external_provider(provider):
        """Enable/disable an external provider."""
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    "UPDATE external_api_keys SET is_active = NOT is_active, updated_at = NOW() WHERE provider = %s",
                    (provider,),
                )
                return jsonify({"success": True})
        except Exception as e:
            logger.error("Error toggling provider: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route(
        "/api/contractors/providers/<provider>/models/<path:model_name>/toggle",
        methods=["PUT"],
    )
    @login_required
    def toggle_provider_model(provider, model_name):
        """Enable/disable a specific model under a provider for routing."""
        data = request.get_json() or {}
        enabled = data.get("enabled")

        if enabled is None or not isinstance(enabled, bool):
            return jsonify({"success": False, "error": "'enabled' (boolean) required"}), 400

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                setting_key = f"model_disabled:{model_name}"
                disabled_value = "false" if enabled else "true"
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES (%s, %s, 'boolean', %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (setting_key, disabled_value, f"Model routing toggle for {model_name} (provider: {provider})"),
                )
                return jsonify({"success": True, "model": model_name, "enabled": enabled})
        except Exception as e:
            logger.error("Error toggling model: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractors/omniroute-quota", methods=["GET"])
    @login_required
    def get_omniroute_quota():
        """DS9 Phase 2 — latest OmniRoute quota snapshot per upstream provider.

        Mirrors the get_external_providers() shape: one entry per provider with
        its throttle rate, status band, and last-scan time. The Contractors
        dashboard card renders this; it is observation-only, no routing change.
        """
        try:
            from services.omniroute_quota_service import get_quota_status

            per_provider = get_quota_status()
            by_key = {}
            for p in per_provider:
                by_key[p["provider"]] = {
                    # Route through the provider lookup helpers users expect:
                    # the caller's front-end keys off the same provider names as
                    # the main providers list.
                    "display_name": p["provider"].replace("_", " ").title(),
                    "total_calls": p["total"],
                    "throttled_calls": p["throttled"],
                    "throttle_rate": p["rate"],
                    "status": p["status"],
                    "window_hours": p["window_hours"],
                    "last_scan_at": p["last_scan_at"],
                }
            return jsonify({"success": True, "providers": by_key})
        except Exception as e:
            logger.error("Error reading OmniRoute quota status: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractors/definitions", methods=["GET"])
    @login_required
    def list_contractor_providers():
        """List all contractor provider definitions (for UI dropdowns and admin)."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, provider_key, display_name, base_url, default_model,
                           auth_method, auth_env_var, is_cloud_proxy, tier_position,
                           models, rate_limits, is_active, created_at, updated_at
                    FROM contractor_providers
                    ORDER BY tier_position
                """
                )
                rows = cur.fetchall()
                providers = []
                for row in rows:
                    d = dict(row)
                    d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
                    d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
                    providers.append(d)
                return jsonify({"success": True, "providers": providers})
        except Exception as e:
            logger.error("Error listing contractor definitions: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractors/definitions", methods=["POST"])
    @admin_required
    def upsert_contractor_provider():
        """Create or update a contractor provider definition."""
        data = request.get_json() or {}
        provider_key = data.get("provider_key", "").strip().lower()
        if not provider_key:
            return jsonify({"success": False, "error": "provider_key is required"}), 400

        display_name = data.get("display_name", provider_key.replace("_", " ").title())
        base_url = data.get("base_url", "").strip()
        if not base_url:
            return jsonify({"success": False, "error": "base_url is required"}), 400

        default_model = data.get("default_model", "").strip() or None
        auth_method = data.get("auth_method", "api_key").strip()
        auth_env_var = data.get("auth_env_var", "").strip() or None
        is_cloud_proxy = bool(data.get("is_cloud_proxy", False))
        tier_position = int(data.get("tier_position", 99))
        models = data.get("models", [])
        rate_limits = data.get("rate_limits", {})
        is_active = bool(data.get("is_active", False))

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO contractor_providers
                        (provider_key, display_name, base_url, default_model, auth_method,
                         auth_env_var, is_cloud_proxy, tier_position, models, rate_limits, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        base_url = EXCLUDED.base_url,
                        default_model = EXCLUDED.default_model,
                        auth_method = EXCLUDED.auth_method,
                        auth_env_var = EXCLUDED.auth_env_var,
                        is_cloud_proxy = EXCLUDED.is_cloud_proxy,
                        tier_position = EXCLUDED.tier_position,
                        models = EXCLUDED.models,
                        rate_limits = EXCLUDED.rate_limits,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    RETURNING id, provider_key, display_name
                """,
                    (
                        provider_key,
                        display_name,
                        base_url,
                        default_model,
                        auth_method,
                        auth_env_var,
                        is_cloud_proxy,
                        tier_position,
                        json.dumps(models),
                        json.dumps(rate_limits),
                        is_active,
                    ),
                )
                row = cur.fetchone()

                # Invalidate external_providers cache
                try:
                    from ai_bridge.external_providers import invalidate_provider_cache

                    invalidate_provider_cache()
                except ImportError:
                    logger.warning("external_providers module not available for cache invalidation")

                return jsonify({"success": True, "provider": dict(row)})
        except Exception as e:
            logger.error("Error upserting contractor definition: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
