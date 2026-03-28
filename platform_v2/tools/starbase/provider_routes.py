"""Starbase Command — Provider routes (ComfyUI, routing mode, external providers, contractors, model routing)"""

import json
import os
import sys
import logging
from datetime import datetime
from typing import List
from flask import jsonify, request
from flask_login import login_required, current_user
from rbac import require_permission, Permission
from database import get_db_cursor
import psycopg2
import requests

from .helpers import OLLAMA_LOCAL_URL, DEFAULT_NODE_PORT

logger = logging.getLogger(__name__)


def register_provider_routes(bp, admin_required):
    """Register provider-related routes on the bridge blueprint."""

    # ============================================================================
    # MINING POOL INTEGRATION - Phase 30
    # ============================================================================
    # BRIDGE MODEL ROUTING - Phase 70
    # ============================================================================

    @bp.route("/api/nodes/<node_id>/bridge-sharing", methods=["PUT"])
    @login_required
    def toggle_bridge_sharing(node_id):
        """Enable or disable a node's model sharing with Bridge"""
        data = request.get_json() or {}
        enabled = data.get("enabled", False)
        priority = data.get("priority", 50)

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):

                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET bridge_enabled = %s,
                        bridge_priority = %s,
                        updated_at = NOW()
                    WHERE node_id = %s
                    RETURNING node_name
                """,
                    (enabled, priority, node_id),
                )

                result = cur.fetchone()
                if not result:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Log to governance audit
                cur.execute(
                    """
                    INSERT INTO governance_audit_log (
                        event_type, event_category, agent_id, action, new_value, reason, outcome
                    ) VALUES (
                        'node_bridge_sharing', 'autonomy', NULL, %s, %s, %s, 'success'
                    )
                """,
                    (
                        "enable" if enabled else "disable",
                        f'{{"node_id": "{node_id}", "priority": {priority}}}',
                        f"Bridge sharing {'enabled' if enabled else 'disabled'} for node {result[0]}",
                    ),
                )

                return jsonify({"success": True, "bridge_enabled": enabled, "bridge_priority": priority})

        except Exception as e:
            logger.error(f"Toggle bridge sharing error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/models")
    @login_required
    def get_bridge_available_models():
        """Get all models available across bridge-enabled nodes, split local vs remote"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get per-model detail with id, node_id, is_available for toggle support
                cur.execute(
                    """
                    SELECT m.id, m.node_id, n.node_name, m.model_name, m.model_family,
                           m.parameter_size, m.model_size_gb, m.is_available,
                           m.total_requests, m.avg_response_ms,
                           n.bridge_enabled, n.status as node_status
                    FROM node_ollama_models m
                    JOIN remote_nodes n ON m.node_id = n.node_id
                    WHERE n.status = 'online' AND n.approval_status = 'approved'
                    ORDER BY m.model_name
                """
                )
                all_models = cur.fetchall()

                # Get aggregated view for summary
                cur.execute(
                    """
                    SELECT * FROM v_bridge_available_models
                """
                )
                aggregated = cur.fetchall()

                # Get summary stats
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT m.model_name) as total_models,
                        COUNT(DISTINCT n.node_id) as total_nodes,
                        SUM(m.total_requests) as total_requests
                    FROM node_ollama_models m
                    JOIN remote_nodes n ON m.node_id = n.node_id
                    WHERE n.bridge_enabled = true AND n.status = 'online'
                """
                )
                summary = cur.fetchone()

                # Get local Ollama models (this host)
                local_models = []
                try:
                    _oh = os.environ.get("OLLAMA_HOST", OLLAMA_LOCAL_URL)
                    if not _oh.startswith("http"):
                        _oh = f"http://{_oh}"
                    resp = requests.get(f"{_oh}/api/tags", timeout=5)
                    if resp.status_code == 200:
                        for m in resp.json().get("models", []):
                            size_gb = round(m.get("size", 0) / 1e9, 1)
                            local_models.append(
                                {
                                    "name": m["name"],
                                    "family": m.get("details", {}).get("family", ""),
                                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                                    "size_gb": size_gb,
                                }
                            )
                except Exception:
                    pass  # Local Ollama unreachable — just skip

                return jsonify(
                    {
                        "success": True,
                        "models": aggregated,
                        "all_models": all_models,
                        "local_models": local_models,
                        "summary": summary,
                    }
                )

        except Exception as e:
            logger.error(f"Get bridge models error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/models")
    @login_required
    def get_node_models(node_id):
        """Get Ollama models available on a specific node"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get node info
                cur.execute(
                    """
                    SELECT node_name, bridge_enabled, bridge_priority, last_model_sync, status
                    FROM remote_nodes WHERE node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get models
                cur.execute(
                    """
                    SELECT id, model_name, model_family, parameter_size, model_size_gb,
                           is_available, total_requests, avg_response_ms,
                           context_length, quantization, updated_at
                    FROM node_ollama_models
                    WHERE node_id = %s
                    ORDER BY model_name
                """,
                    (node_id,),
                )
                models = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "node": node,
                        "models": models,
                        "model_count": len(models),
                    }
                )

        except Exception as e:
            logger.error(f"Get node models error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/models/sync", methods=["POST"])
    @login_required
    def sync_node_models_api(node_id):
        """Manually trigger model sync for a node (fetches from node's Ollama)"""
        try:
            with get_db_cursor() as (conn, cur):

                # Get node info
                cur.execute(
                    """
                    SELECT vpn_ip, port, ollama_available FROM remote_nodes WHERE node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                if not node["ollama_available"]:
                    return (
                        jsonify({"success": False, "error": "Node does not have Ollama"}),
                        400,
                    )

                # Fetch models from node's Ollama
                import requests as req

                ollama_url = f"http://{node['vpn_ip']}:{node.get('port', DEFAULT_NODE_PORT)}/api/tags"

                try:
                    resp = req.get(ollama_url, timeout=10)
                    if resp.status_code != 200:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Ollama returned {resp.status_code}",
                                }
                            ),
                            502,
                        )

                    models = resp.json().get("models", [])

                except req.exceptions.RequestException as e:
                    return (
                        jsonify({"success": False, "error": f"Cannot reach node Ollama: {e}"}),
                        502,
                    )

                # Sync models using database function
                cur.execute(
                    """
                    SELECT sync_node_models(%s, %s::jsonb)
                """,
                    (node_id, psycopg2.extras.Json(models)),
                )
                result = cur.fetchone()
                models_synced = result[0] if result else 0

                return jsonify(
                    {
                        "success": True,
                        "models_synced": models_synced,
                        "message": f"Synced {models_synced} models from node",
                    }
                )

        except Exception as e:
            logger.error(f"Manual model sync error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/models/<int:model_id>/toggle", methods=["PUT"])
    @login_required
    def toggle_model_availability(node_id, model_id):
        """Enable or disable a specific model on a node for bridge routing"""
        data = request.get_json() or {}
        enabled = data.get("enabled", True)

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):

                cur.execute(
                    """
                    UPDATE node_ollama_models
                    SET is_available = %s, updated_at = NOW()
                    WHERE id = %s AND node_id = %s
                    RETURNING model_name
                """,
                    (enabled, model_id, node_id),
                )

                result = cur.fetchone()
                if not result:
                    return jsonify({"success": False, "error": "Model not found"}), 404

                return jsonify(
                    {
                        "success": True,
                        "model_name": result[0],
                        "is_available": enabled,
                    }
                )

        except Exception as e:
            logger.error(f"Toggle model availability error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/select-node", methods=["POST"])
    @login_required
    def select_node_for_model():
        """Select the best available node for a specific model"""
        data = request.get_json() or {}
        model_name = data.get("model_name")
        prefer_gpu = data.get("prefer_gpu", True)

        if not model_name:
            return jsonify({"success": False, "error": "model_name required"}), 400

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT * FROM select_node_for_model(%s, %s) LIMIT 1
                """,
                    (model_name, prefer_gpu),
                )
                node = cur.fetchone()

                if not node:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"No bridge-enabled node has model {model_name}",
                            }
                        ),
                        404,
                    )

                return jsonify(
                    {
                        "success": True,
                        "node": node,
                        "ollama_url": f"http://{node['vpn_ip']}:{node['port']}",
                    }
                )

        except Exception as e:
            logger.error(f"Select node for model error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # COMFYUI MODEL CONTROL
    # ============================================================================

    @bp.route("/api/bridge/comfyui/models")
    @login_required
    def comfyui_models():
        """List ComfyUI checkpoint models and current service status."""
        try:
            from ai_bridge.comfyui_service import get_comfyui_service

            svc = get_comfyui_service()
            healthy = svc.health_check()
            if not healthy:
                return jsonify(
                    {
                        "success": True,
                        "online": False,
                        "models": [],
                        "queue": {"running": 0, "pending": 0},
                    }
                )

            models_data = svc.get_models()
            queue = svc.get_queue_status()
            stats = svc.get_system_stats()

            # Determine which model is currently loaded in VRAM
            loaded_model = None
            vram_used_gb = 0
            if stats:
                devices = stats.get("devices", [])
                for dev in devices:
                    if dev.get("type") == "cuda":
                        alloc = dev.get("vram_total", 0) - dev.get("vram_free", 0)
                        vram_used_gb = round(alloc / (1024**3), 2)
                        # If significant VRAM allocated, a model is loaded
                        if vram_used_gb > 0.5:
                            loaded_model = models_data.get("current")

            return jsonify(
                {
                    "success": True,
                    "online": True,
                    "models": models_data.get("installed", []),
                    "current_model": loaded_model,
                    "vram_used_gb": vram_used_gb,
                    "queue": {
                        "running": queue.get("running", 0),
                        "pending": queue.get("pending", 0),
                    },
                }
            )
        except Exception as e:
            logger.error(f"comfyui_models error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/comfyui/control", methods=["POST"])
    @login_required
    def comfyui_control():
        """Load (warmup) or unload a ComfyUI checkpoint model.

        Body: { "model": "sd_xl_base_1.0.safetensors", "action": "load"|"unload" }
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            from ai_bridge.comfyui_service import get_comfyui_service

            svc = get_comfyui_service()
            if not svc.health_check():
                return jsonify({"success": False, "error": "ComfyUI is offline"}), 503

            data = request.get_json() or {}
            model_name = data.get("model", "").strip()
            action = data.get("action", "").strip()

            if not model_name or action not in ("load", "unload"):
                return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

            comfyui_host = svc.host

            if action == "unload":
                # Free all models from VRAM
                resp = requests.post(
                    f"{comfyui_host}/free",
                    json={"unload_models": True},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return jsonify({"success": True, "message": "ComfyUI VRAM freed"})
                return jsonify({"success": False, "error": f"ComfyUI returned {resp.status_code}"}), 502

            # action == "load" — warmup the checkpoint via minimal generation
            logger.info(f"ComfyUI model load requested: {model_name}")
            ok = svc.warmup(model=model_name)
            if ok:
                return jsonify({"success": True, "message": f"{model_name} loaded into VRAM"})
            return jsonify({"success": False, "error": f"Failed to warmup {model_name}"}), 502

        except requests.Timeout:
            return jsonify({"success": False, "error": "ComfyUI warmup timed out"}), 504
        except Exception as e:
            logger.error(f"comfyui_control error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/reassign", methods=["POST"])
    @login_required
    def reassign_agent():
        """Manually reassign an agent to a different department (admin only).

        Accepts station_code (mapped via LEGACY_STATION_DEPARTMENT) or department name.
        station_assignments table is DROPPED — updates agents.department directly.
        """
        from .helpers import LEGACY_STATION_DEPARTMENT, DEPARTMENT_TO_STATION

        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            data = request.get_json() or {}
            agent_id = data.get("agent_id")
            new_station_code = data.get("station_code")
            department = data.get("department")

            # Map station_code to department if needed
            if not department and new_station_code:
                depts = LEGACY_STATION_DEPARTMENT.get(new_station_code.upper(), [])
                department = depts[0] if depts else None

            if not agent_id or not department:
                return jsonify({"success": False, "error": "agent_id and (station_code or department) required"}), 400

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT id, name FROM agents WHERE id = %s AND status = 'active'", (agent_id,))
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"success": False, "error": "Agent not found or inactive"}), 404

                cur.execute(
                    "UPDATE agents SET department = %s, updated_at = NOW() WHERE id = %s",
                    (department, agent_id),
                )

                logger.info(f"Agent {agent['name']} reassigned to {department} by {current_user.username}")

                return jsonify(
                    {
                        "success": True,
                        "message": f"{agent['name']} reassigned to {department}",
                        "agent_id": agent_id,
                        "station_code": DEPARTMENT_TO_STATION.get(department, new_station_code or ""),
                        "department": department,
                    }
                )

        except Exception as e:
            logger.error(f"Error reassigning agent: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # ROUTING MODE & ESCALATION LOG API
    # ============================================================================

    @bp.route("/api/routing-mode", methods=["GET"])
    @login_required
    def get_routing_mode():
        """Get current bridge routing mode."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
                row = cur.fetchone()
                return jsonify({"success": True, "routing_mode": row["value"] if row else "full"})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/routing-mode", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def set_routing_mode():
        """Set bridge routing mode: local_only, local_cloud, or full."""
        data = request.get_json() or {}
        mode = data.get("routing_mode", "full")
        if mode not in ("local_only", "local_cloud", "full"):
            return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES ('routing_mode', %s, 'string', 'Bridge routing mode', NOW())
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
                """,
                    (mode, mode),
                )
                logger.info(f"[Bridge] Routing mode changed to: {mode}")
                return jsonify({"success": True, "routing_mode": mode})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/escalation-mode", methods=["GET"])
    @login_required
    def get_escalation_mode():
        """Get current bridge escalation mode."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_mode'")
                row = cur.fetchone()
                return jsonify({"success": True, "escalation_mode": row["value"] if row else "auto"})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/escalation-mode", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def set_escalation_mode():
        """Set bridge escalation mode: auto, ask_first, or local_only."""
        data = request.get_json() or {}
        mode = data.get("escalation_mode", "auto")
        if mode not in ("auto", "ask_first", "local_only"):
            return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES ('escalation_mode', %s, 'string', 'Throughput escalation mode', NOW())
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
                """,
                    (mode, mode),
                )
                logger.info(f"[Bridge] Escalation mode changed to: {mode}")
                return jsonify({"success": True, "escalation_mode": mode})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/escalation-log", methods=["GET"])
    @login_required
    def get_escalation_log():
        """Get recent escalation events."""
        limit = request.args.get("limit", 20, type=int)
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT del.*, a.name as agent_name
                    FROM dispatch_escalation_log del
                    LEFT JOIN agents a ON a.id = del.original_agent_id
                    ORDER BY del.created_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                rows = cur.fetchall()
                # Convert datetime objects for JSON serialization
                result = []
                for r in rows:
                    d = dict(r)
                    for k, v in d.items():
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    result.append(d)
                return jsonify({"success": True, "escalations": result})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # EXTERNAL PROVIDER KEY MANAGEMENT
    # ============================================================================

    @bp.route("/api/external-providers", methods=["GET"])
    @login_required
    def get_external_providers():
        """List external AI providers with 24h stats, model breakdowns, and tier positions.
        All provider metadata now comes from the contractor_providers table (dynamic)."""
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/external-providers", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
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
                    # Check if key already exists (edit mode — keep existing)
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
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))
                    from external_providers import invalidate_provider_cache

                    invalidate_provider_cache()
                except ImportError:
                    logger.warning("external_providers module not available for cache invalidation")

                return jsonify({"success": True, "provider": dict(row)})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/external-providers/<provider>/toggle", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route(
        "/api/external-providers/<provider>/models/<path:model_name>/toggle",
        methods=["PUT"],
    )
    @login_required
    def toggle_provider_model(provider, model_name):
        """Enable/disable a specific model under a provider for routing."""
        data = request.get_json() or {}
        enabled = data.get("enabled")

        if enabled is None or not isinstance(enabled, bool):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Request body must include 'enabled' (boolean)",
                    }
                ),
                400,
            )

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                setting_key = f"model_disabled:{model_name}"
                # Store as disabled flag: enabled=True means NOT disabled, so value="false"
                disabled_value = "false" if enabled else "true"
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES (%s, %s, 'boolean', %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (
                        setting_key,
                        disabled_value,
                        f"Model routing toggle for {model_name} (provider: {provider})",
                    ),
                )
                return jsonify({"success": True, "model": model_name, "enabled": enabled})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # CONTRACTOR PROVIDER DEFINITIONS API (dynamic provider management)
    # ============================================================================

    @bp.route("/api/contractor-providers", methods=["GET"])
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractor-providers", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
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
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))
                    from external_providers import invalidate_provider_cache

                    invalidate_provider_cache()
                except ImportError:
                    logger.warning("external_providers module not available for cache invalidation")

                return jsonify({"success": True, "provider": dict(row)})
        except Exception as e:
            return jsonify({"success": False, "error": "Internal server error"}), 500
