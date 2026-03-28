"""Starbase Command — Fleet & model routes.

Retains fleet infrastructure endpoints: model catalog, crew manifest (fleet
capacity), fleet mode, model control, cluster models/agents.

Agent roster management (lounge, training, wellness, C.R.E.E.D. move-check,
rotation log) has moved to Department HQ — redirect stubs are provided so
existing URL references return a helpful 301 instead of a 404.
"""

import os
import logging
from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
import requests

from services.agent_service import list_agents, get_agent
from services.agent_models import get_loaded_models, check_vram_budget
from services.agent_dispatch import get_fleet_roster

from .helpers import (
    _get_cached_ollama_tags,
    _get_cached_ollama_ps,
    _get_cached_hw_capacity,
    OLLAMA_LOCAL_URL,
)

logger = logging.getLogger(__name__)

_MOVED_MSG = "Agent roster management moved to Department HQ."
_REDIRECT = "/tools/department-hq"


def register_crew_routes(bp, admin_required):
    """Register fleet/model routes + deprecated roster redirect stubs."""

    # ========================================================================
    # DEPRECATED — redirect stubs for endpoints moved to Department HQ
    # ========================================================================

    @bp.route("/api/lounge", methods=["GET"])
    @login_required
    def get_lounge_agents():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>/send-to-lounge", methods=["POST"])
    @login_required
    def send_agent_to_lounge(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>/return-from-lounge", methods=["POST"])
    @login_required
    def return_agent_from_lounge(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/training/active", methods=["GET"])
    @login_required
    def get_active_training():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/training/assign", methods=["POST"])
    @login_required
    def assign_training():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/training/<int:training_id>/cancel", methods=["POST"])
    @login_required
    def cancel_training(training_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/training/history", methods=["GET"])
    @login_required
    def get_training_history():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/training/recommendations", methods=["GET"])
    @login_required
    def get_training_recommendations():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/training/templates", methods=["GET", "POST"])
    @login_required
    def training_templates():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/lounge/wellness", methods=["GET"])
    @login_required
    def get_lounge_wellness():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/lounge/history", methods=["GET"])
    @login_required
    def get_lounge_history():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/creed/check-move/<int:agent_id>", methods=["GET"])
    @login_required
    def check_creed_move_compliance(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/bridge/agent-form-context", methods=["GET"])
    @login_required
    def get_agent_form_context():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/bridge/rotation-log", methods=["GET"])
    @login_required
    def get_rotation_log():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    # ========================================================================
    # KEPT — Fleet & model infrastructure endpoints
    # ========================================================================

    @bp.route("/api/model-catalog")
    @login_required
    def api_model_catalog():
        """Return model catalog for enriched model dropdowns."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT model_name, display_name, description, tier, category, size_gb, parameter_size "
                "FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
            )
            models = cur.fetchall()
            catalog = {m["model_name"]: dict(m) for m in models}
            return jsonify({"success": True, "catalog": catalog})

    @bp.route("/api/bridge/crew/manifest")
    @login_required
    def get_crew_manifest():
        """Get the live crew manifest — all agents with status, wellness, jobs, stats."""
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            manifest = dispatcher.get_crew_manifest()

            # Hardware capacity (cached — nvidia-smi + psutil + Ollama model breakdown)
            capacity = None
            try:
                capacity = _get_cached_hw_capacity()
            except Exception as cap_err:
                logger.debug(f"Could not get capacity info: {cap_err}")

            # Merge workload data (daily caps, token usage, risk levels)
            workload_map = {}
            try:
                with get_db_cursor(commit=False) as (wconn, wcur):
                    wcur.execute(
                        """
                        SELECT a.id,
                            COALESCE(ab.task_queue_limit, 50) as daily_cap,
                            COALESCE(ab.token_limit_per_day, 500000) as token_cap,
                            COUNT(tel.id) as tasks_24h,
                            COALESCE(SUM(tel.tokens_used), 0) as tokens_used_24h
                        FROM agents a
                        LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
                        LEFT JOIN task_execution_log tel ON tel.agent_id = a.id
                            AND tel.created_at >= NOW() - INTERVAL '24 hours'
                        WHERE a.status = 'active'
                        GROUP BY a.id, ab.task_queue_limit, ab.token_limit_per_day
                    """
                    )
                    for r in wcur.fetchall():
                        daily_cap = int(r["daily_cap"]) or 50
                        token_cap = int(r["token_cap"]) or 500000
                        tasks = int(r["tasks_24h"])
                        tokens = int(r["tokens_used_24h"])
                        wl_pct = min(round(tasks / daily_cap * 100, 1), 100) if daily_cap > 0 else 0
                        tk_pct = min(round(tokens / token_cap * 100, 1), 100) if token_cap > 0 else 0
                        risk = (
                            "overloaded"
                            if wl_pct >= 100
                            else "critical" if wl_pct >= 80 else "elevated" if wl_pct >= 60 else "healthy"
                        )
                        workload_map[r["id"]] = {
                            "daily_cap": daily_cap,
                            "token_cap": token_cap,
                            "tasks_24h": tasks,
                            "tokens_used_24h": tokens,
                            "workload_pct": wl_pct,
                            "token_usage_pct": tk_pct,
                            "risk_level": risk,
                        }
            except Exception as e:
                logger.warning(f"[crew] Failed to compute agent workload metrics: {e}")

            # Attach workload to each crew member
            for member in manifest:
                wl = workload_map.get(member.get("agent_id") or member.get("id"), {})
                member["workload"] = wl

            # Add shift_state to each manifest entry (from agent_service)
            try:
                all_agents = list_agents(limit=500)
                shift_states = {a["id"]: a.get("shift_state") or "active" for a in all_agents}
                for entry in manifest:
                    entry["shift_state"] = shift_states.get(entry.get("agent_id") or entry.get("id"), "active")
            except Exception as e:
                logger.warning(f"[crew] Failed to fetch agent shift states: {e}")

            # Fleet overview counts
            shift_counts = {
                "active": 0,
                "deployed": 0,
                "barracked": 0,
                "winding_down": 0,
                "cooldown": 0,
                "off_duty": 0,
                "reserves": 0,
            }
            for entry in manifest:
                # Skip fleet: prefixed agents (node copies)
                if entry.get("name", "").startswith("fleet:"):
                    continue
                state = entry.get("shift_state", "active")
                if state in shift_counts:
                    shift_counts[state] += 1
            shift_counts["reserves"] = shift_counts["barracked"]

            # Get fleet mode (workday/weekend)
            fleet_mode = "workday"
            try:
                with get_db_cursor(commit=False) as (_fconn, _fcur):
                    _fcur.execute("SELECT value FROM system_config WHERE key = 'fleet_mode'")
                    _frow = _fcur.fetchone()
                    if _frow:
                        fleet_mode = _frow["value"]
            except Exception as e:
                logger.warning(f"[crew] Failed to read fleet mode from system_config: {e}")

            # Node fleet capacity (GPU/RAM for each online node)
            node_capacities = []
            try:
                with get_db_cursor(commit=False) as (nconn, ncur):
                    ncur.execute(
                        """SELECT rn.id, rn.node_id, rn.node_name, rn.hostname, rn.port,
                                  rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb, rn.cpu_cores,
                                  (SELECT COUNT(*) FROM node_agents na WHERE na.node_id = rn.id AND na.status = 'active') as agent_count
                           FROM remote_nodes rn
                           WHERE rn.is_active = true AND rn.deployment_mode != 'starbase'
                             AND (rn.last_heartbeat > NOW() - INTERVAL '2 minutes')"""
                    )
                    for node in ncur.fetchall():
                        import requests as _req

                        node_url = f"http://{node['hostname']}:{node['port']}"
                        vram_total = float(node["gpu_vram_gb"]) if node["gpu_vram_gb"] else 0
                        ram_total = float(node["ram_gb"]) if node["ram_gb"] else 0

                        node_cap = {
                            "node_id": node["node_id"],
                            "node_name": node["node_name"],
                            "gpu_model": node["gpu_model"],
                            "gpu_vram_gb": vram_total,
                            "gpu_vram_used_gb": 0,
                            "gpu_vram_free_gb": vram_total,
                            "ram_gb": ram_total,
                            "ram_used_gb": 0,
                            "ram_free_gb": ram_total,
                            "ram_agent_budget_gb": round(ram_total * 0.80, 1),
                            "ram_swap_buffer_gb": round(ram_total * 0.05, 1),
                            "ram_reserve_gb": round(ram_total * 0.15, 1),
                            "ram_security_gb": 0,  # Nodes don't need security reserve — managed from hub
                            "models_ram_gb": 0,
                            "cpu_cores": node["cpu_cores"] or 0,
                            "agent_count": node["agent_count"],
                            "models_installed": [],
                            "models_loaded": [],
                            "models_loaded_count": 0,
                            "models_installed_count": 0,
                        }

                        # Fetch installed models (/api/tags)
                        try:
                            tags_resp = _req.get(f"{node_url}/api/tags", timeout=3)
                            if tags_resp.status_code == 200:
                                for m in tags_resp.json().get("models", []):
                                    node_cap["models_installed"].append(
                                        {
                                            "name": m["name"],
                                            "size_gb": round(m.get("size", 0) / 1e9, 1),
                                        }
                                    )
                                node_cap["models_installed_count"] = len(node_cap["models_installed"])
                        except Exception as e:
                            logger.warning("Failed to fetch node installed models: %s", e)

                        # Fetch loaded models (/api/ps) — live VRAM/RAM usage
                        try:
                            ps_resp = _req.get(f"{node_url}/api/ps", timeout=3)
                            if ps_resp.status_code == 200:
                                vram_used = 0
                                ram_used = 0
                                for m in ps_resp.json().get("models", []):
                                    size_vram = m.get("size_vram", 0)
                                    size_total = m.get("size", 0)
                                    size_ram = size_total - size_vram
                                    vram_used += size_vram
                                    ram_used += size_ram
                                    node_cap["models_loaded"].append(
                                        {
                                            "name": m["name"],
                                            "size_gb": round(size_total / 1e9, 1),
                                            "vram_gb": round(size_vram / 1e9, 1),
                                            "ram_gb": round(size_ram / 1e9, 1),
                                        }
                                    )
                                node_cap["gpu_vram_used_gb"] = round(vram_used / 1e9, 1)
                                node_cap["gpu_vram_free_gb"] = round(max(0, vram_total - vram_used / 1e9), 1)
                                node_cap["ram_used_gb"] = round(ram_used / 1e9, 1)
                                node_cap["ram_free_gb"] = round(max(0, ram_total - ram_used / 1e9), 1)
                                node_cap["models_ram_gb"] = round((vram_used + ram_used) / 1e9, 1)
                                node_cap["models_loaded_count"] = len(node_cap["models_loaded"])
                        except Exception as e:
                            logger.warning("Failed to fetch node loaded models: %s", e)

                        node_capacities.append(node_cap)
            except Exception as nc_err:
                logger.debug(f"Node capacity fetch failed: {nc_err}")

            resp = {
                "success": True,
                "crew": manifest,
                "total": len(manifest),
                "fleet_mode": fleet_mode,
                "fleet_overview": shift_counts,
                "node_capacities": node_capacities,
            }
            if capacity:
                resp["capacity"] = capacity
            return jsonify(resp)
        except Exception as e:
            logger.error(f"Error getting crew manifest: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/fleet-mode", methods=["POST"])
    @login_required
    def toggle_fleet_mode():
        """Toggle between workday (all models warm) and weekend (all unloaded).

        Body: { "mode": "workday"|"weekend" }
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            data = request.get_json() or {}
            mode = data.get("mode", "").strip().lower()
            if mode not in ("workday", "weekend"):
                return jsonify({"success": False, "error": "mode must be 'workday' or 'weekend'"}), 400

            # Save to system_config
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_config (key, value, description, updated_at)
                       VALUES ('fleet_mode', %s, 'Fleet operating mode: workday (warm) or weekend (unloaded)', NOW())
                       ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()""",
                    (mode, mode),
                )

            ollama_url = OLLAMA_LOCAL_URL

            import threading

            if mode == "weekend":
                # Unload all Ollama models + free ComfyUI VRAM
                def _unload_all():
                    try:
                        from ai_bridge.bridge_dispatcher import get_dispatcher

                        _dispatcher = get_dispatcher()
                        ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
                        if ps_resp.status_code == 200:
                            for m in ps_resp.json().get("models", []):
                                mname = m.get("name", "")
                                result = _dispatcher.unload_model(mname)
                                if result.get("success"):
                                    logger.info(f"[FleetMode] Weekend: unloaded {mname}")
                                else:
                                    logger.warning(
                                        f"[FleetMode] Weekend: failed to unload {mname}: {result.get('message')}"
                                    )
                    except Exception as e:
                        logger.error(f"[FleetMode] Weekend Ollama unload error: {e}")

                    # Free ComfyUI VRAM
                    try:
                        comfyui_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
                        requests.post(
                            f"{comfyui_host}/free",
                            json={"unload_models": True},
                            timeout=10,
                        )
                        logger.info("[FleetMode] Weekend: freed ComfyUI VRAM")
                    except Exception as e:
                        logger.warning(f"[FleetMode] Weekend ComfyUI free error: {e}")

                t = threading.Thread(target=_unload_all, daemon=True, name="fleet-weekend")
                t.start()
                return jsonify({"success": True, "mode": "weekend", "message": "Unloading all models..."})
            else:
                # Workday: trigger Ollama warmup + ComfyUI warmup
                def _warmup():
                    try:
                        from app import _warmup_ollama_models

                        _warmup_ollama_models()
                    except Exception as e:
                        logger.error(f"[FleetMode] Workday Ollama warmup error: {e}")

                    # ComfyUI warmup after Ollama
                    try:
                        from ai_bridge.comfyui_service import get_comfyui_service

                        svc = get_comfyui_service()
                        svc.warmup()
                    except Exception as e:
                        logger.warning(f"[FleetMode] Workday ComfyUI warmup error: {e}")

                t = threading.Thread(target=_warmup, daemon=True, name="fleet-workday")
                t.start()
                return jsonify({"success": True, "mode": "workday", "message": "Warming up all models..."})

        except Exception as e:
            logger.error(f"Error toggling fleet mode: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/model-control", methods=["POST"])
    @login_required
    def model_control():
        """Load or unload an Ollama model on hub or fleet node.

        Body: { "model": "phi3.5:latest", "action": "load"|"unload", "num_gpu": 0, "node_id": null }
        node_id: if provided, routes to that node's Ollama. If null/absent, uses hub Ollama.
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            data = request.get_json()
            model_name = (data or {}).get("model", "").strip()
            action = (data or {}).get("action", "").strip()
            num_gpu = int((data or {}).get("num_gpu", 0))
            node_db_id = (data or {}).get("node_id")

            if not model_name or action not in ("load", "unload"):
                return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

            # Determine Ollama target — hub or node
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            target_host = None
            target_name = "hub"

            if node_db_id:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT hostname, port FROM remote_nodes WHERE id = %s AND is_active = true",
                        (int(node_db_id),),
                    )
                    node = cur.fetchone()
                    if not node:
                        return jsonify({"success": False, "error": "Node not found"}), 404
                    target_host = {"hostname": node["hostname"], "port": node["port"], "node_db_id": int(node_db_id)}
                    target_name = f"node {node_db_id}"

            if action == "unload":
                # Unload via Bridge dispatcher
                result = dispatcher.unload_model(model_name, target_host=target_host)
                if result.get("success"):
                    return jsonify({"success": True, "message": f"{model_name} unloaded"})
                return jsonify({"success": False, "error": result.get("message", "Unload failed")}), 502

            # action == "load"
            # Check if already loaded (GET /api/ps is acceptable per ADR-013)
            ollama_url = f"http://{target_host['hostname']}:{target_host['port']}" if target_host else OLLAMA_LOCAL_URL
            try:
                ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=5)
                if ps_resp.status_code == 200:
                    for m in ps_resp.json().get("models", []):
                        if m.get("name", "") == model_name or m.get("name", "").replace(
                            ":latest", ""
                        ) == model_name.replace(":latest", ""):
                            return jsonify({"success": True, "message": f"{model_name} already loaded"})
            except Exception as e:
                logger.warning(f"[crew] Failed to check loaded models from Ollama: {e}")

            # Load via Bridge dispatcher ensure_model_ready
            result = dispatcher.ensure_model_ready("model_control", model_name, target_host=target_host)
            if result.get("ready"):
                return jsonify(
                    {
                        "success": True,
                        "message": f"{model_name} loaded on {target_name} (tier: {result.get('tier', 'unknown')})",
                    }
                )
            return jsonify({"success": False, "error": f"Failed to load {model_name} on {target_name}"}), 502

        except requests.Timeout:
            return jsonify({"success": False, "error": "Model load timed out (300s) — try a smaller model"}), 504
        except Exception as e:
            logger.error(f"model_control error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # CLUSTER MODEL INVENTORY — unified view of all Ollama models across hub+nodes
    # ========================================================================

    @bp.route("/api/cluster/models")
    @login_required
    def cluster_models():
        """Return a unified inventory of all Ollama models across the cluster.

        Combines hub models (from Ollama /api/tags + /api/ps) with node models
        (from node_ollama_models table, synced via heartbeat).
        """
        try:
            # --- Hub models ---
            hub_tags, _ = _get_cached_ollama_tags()
            hub_ps = _get_cached_ollama_ps()

            # Build a map of loaded model names with VRAM info
            loaded_map = {}
            for pm in hub_ps:
                key = pm.get("name", "").replace(":latest", "")
                vram_bytes = pm.get("size_vram", 0)
                loaded_map[key] = {
                    "loaded": True,
                    "vram_gb": round(vram_bytes / (1024**3), 2) if vram_bytes else 0,
                    "size_bytes": pm.get("size", 0),
                }

            hub_models = []
            hub_loaded_count = 0
            hub_vram_total = 0.0
            for tag in hub_tags:
                name = tag.get("name", "").replace(":latest", "")
                size = tag.get("size", 0)
                loaded_info = loaded_map.get(name, {})
                is_loaded = loaded_info.get("loaded", False)
                vram_gb = loaded_info.get("vram_gb", 0)
                if is_loaded:
                    hub_loaded_count += 1
                    hub_vram_total += vram_gb
                hub_models.append(
                    {
                        "name": name,
                        "size": size,
                        "size_gb": round(size / (1024**3), 2) if size else 0,
                        "loaded": is_loaded,
                        "vram_gb": vram_gb,
                    }
                )

            hub_hostname = os.getenv("HUB_HOSTNAME", "192.168.1.200")
            hub_data = {
                "hostname": hub_hostname,
                "models": hub_models,
                "model_count": len(hub_models),
                "loaded_count": hub_loaded_count,
                "vram_used_gb": round(hub_vram_total, 2),
            }

            # --- Node models (from DB — synced via heartbeat) ---
            nodes_data = []
            node_total_models = 0
            node_loaded_count = 0
            try:
                with get_db_cursor(commit=False) as (conn, cur):
                    cur.execute(
                        """SELECT node_id, node_name, hostname, port, status
                           FROM remote_nodes
                           WHERE is_active = true
                           ORDER BY node_name"""
                    )
                    nodes = cur.fetchall()

                    for node in nodes:
                        nid = node["node_id"]
                        cur.execute(
                            """SELECT model_name, model_size_gb, is_available,
                                      parameter_size, quantization, model_family
                               FROM node_ollama_models
                               WHERE node_id = %s
                               ORDER BY model_name""",
                            (nid,),
                        )
                        rows = cur.fetchall()

                        n_models = []
                        for r in rows:
                            size_gb = float(r["model_size_gb"]) if r["model_size_gb"] else 0
                            n_models.append(
                                {
                                    "name": r["model_name"],
                                    "size": int(size_gb * (1024**3)) if size_gb else 0,
                                    "size_gb": round(size_gb, 2),
                                    "loaded": bool(r["is_available"]),
                                    "parameter_size": r["parameter_size"],
                                    "quantization": r["quantization"],
                                    "family": r["model_family"],
                                }
                            )

                        n_loaded = sum(1 for m in n_models if m["loaded"])
                        node_total_models += len(n_models)
                        node_loaded_count += n_loaded

                        nodes_data.append(
                            {
                                "node_id": nid,
                                "node_name": node["node_name"],
                                "hostname": node["hostname"],
                                "port": node["port"],
                                "status": node["status"],
                                "models": n_models,
                                "model_count": len(n_models),
                                "loaded_count": n_loaded,
                            }
                        )
            except Exception as e:
                logger.warning("cluster_models: failed to fetch node models: %s", e)

            # --- Cluster totals ---
            all_model_names = set(m["name"] for m in hub_models)
            for nd in nodes_data:
                for m in nd["models"]:
                    all_model_names.add(m["name"])

            total_models = len(hub_models) + node_total_models
            total_loaded = hub_loaded_count + node_loaded_count

            return jsonify(
                {
                    "success": True,
                    "hub": hub_data,
                    "nodes": nodes_data,
                    "cluster_totals": {
                        "total_models": total_models,
                        "unique_models": len(all_model_names),
                        "loaded_models": total_loaded,
                        "total_vram_used_gb": round(hub_vram_total, 2),
                        "hub_model_count": len(hub_models),
                        "node_model_count": node_total_models,
                        "node_count": len(nodes_data),
                    },
                }
            )

        except Exception as e:
            logger.error("cluster_models error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # UNIFIED CLUSTER AGENTS — fleet-wide agent view with deployment status
    # ========================================================================

    @bp.route("/api/cluster/agents")
    @login_required
    def cluster_agents():
        """Return ALL agents across hub + fleet with location and status.

        Uses agent_service.list_agents and agent_dispatch.get_fleet_roster
        instead of raw SQL.  Also checks bridge_jobs for running jobs and
        Ollama for loaded-model status.
        """
        try:
            # -- Loaded models on the hub (to flag model_loaded) --
            hub_ps = _get_cached_ollama_ps()
            loaded_models = set()
            for pm in hub_ps:
                name = pm.get("name", "").replace(":latest", "")
                loaded_models.add(name)

            # -- Fleet roster: hub agents + node-deployed agents --
            roster = get_fleet_roster()
            hub_agents = roster.get("hub", [])
            node_agents = roster.get("nodes", [])

            # Build a set of deployed agent IDs with their node info
            deployed_map = {}
            for na in node_agents:
                deployed_map[na["id"]] = {
                    "node_name": na.get("node_name"),
                    "hostname": na.get("hostname"),
                }

            # -- Current active jobs per agent (still needs DB — bridge_jobs is not agent data) --
            active_jobs = {}
            try:
                with get_db_cursor(commit=False) as (conn, cur):
                    cur.execute(
                        """SELECT DISTINCT ON (bj.agent_name) bj.agent_name, bj.description
                           FROM bridge_jobs bj
                           WHERE bj.status IN ('running', 'in_progress', 'pending')
                           ORDER BY bj.agent_name, bj.created_at DESC"""
                    )
                    for row in cur.fetchall():
                        active_jobs[row["agent_name"]] = row["description"]
            except Exception as e:
                logger.warning("cluster_agents: failed to fetch active jobs: %s", e)

            # -- Node online status (for model_loaded check on deployed agents) --
            node_online = set()
            try:
                with get_db_cursor(commit=False) as (conn, cur):
                    cur.execute("SELECT node_name FROM remote_nodes WHERE is_active = true AND status = 'online'")
                    node_online = {r["node_name"] for r in cur.fetchall()}
            except Exception as e:
                logger.warning("cluster_agents: failed to fetch node status: %s", e)

            # -- Combine all active agents from service --
            all_agents = list_agents(limit=500)

            agents_list = []
            summary = {
                "total": 0,
                "hub_active": 0,
                "hub_barracked": 0,
                "deployed": 0,
                "off_duty": 0,
            }

            for agent in all_agents:
                shift = agent.get("shift_state") or "active"
                agent_id = agent["id"]
                is_deployed = agent_id in deployed_map
                model_name = (agent.get("model") or "").replace(":latest", "")

                location = "hub"
                node_name = None
                if is_deployed:
                    location = deployed_map[agent_id].get("node_name") or "node"
                    node_name = deployed_map[agent_id].get("node_name")

                # Model loaded check
                model_loaded = False
                if is_deployed:
                    model_loaded = node_name in node_online if node_name else False
                else:
                    model_loaded = model_name in loaded_models

                agents_list.append(
                    {
                        "id": agent_id,
                        "name": agent.get("name"),
                        "display_name": agent.get("display_name") or agent.get("name"),
                        "location": location,
                        "node_name": node_name,
                        "shift_state": shift,
                        "station_code": agent.get("department"),
                        "department": agent.get("department"),
                        "model": agent.get("model"),
                        "model_loaded": model_loaded,
                        "current_job": active_jobs.get(agent.get("name")),
                        "title": agent.get("title"),
                        "avatar_url": agent.get("avatar_url"),
                        "assignment_type": "primary",
                    }
                )

                # Summary counts
                summary["total"] += 1
                if shift == "deployed" or is_deployed:
                    summary["deployed"] += 1
                elif shift == "barracked":
                    summary["hub_barracked"] += 1
                elif shift in ("off_duty", "winding_down", "cooldown"):
                    summary["off_duty"] += 1
                else:
                    summary["hub_active"] += 1

            return jsonify(
                {
                    "success": True,
                    "agents": agents_list,
                    "summary": summary,
                }
            )

        except Exception as e:
            logger.error("cluster_agents error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
