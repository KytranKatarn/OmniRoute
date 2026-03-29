"""Starbase Command — Fleet & model routes.

DEPRECATED ENDPOINTS (301 stubs):
  /api/lounge, /api/agents/<id>/send-to-lounge, /api/agents/<id>/return-from-lounge,
  /api/training/*, /api/lounge/wellness, /api/lounge/history,
  /api/creed/check-move/<id>, /api/bridge/agent-form-context, /api/bridge/rotation-log
  → All moved to Department HQ.

REMOVED ENDPOINTS (not called by starbase.js):
  /api/cluster/models, /api/cluster/agents
  → Were fleet-wide inventory views; use Department HQ model management instead.

KEPT ENDPOINTS:
  /api/model-catalog          — slim DB lookup (no Ollama calls)
  /api/bridge/crew/manifest   — full implementation (complex capacity logic for Starbase UI)
  /api/bridge/fleet-mode      — full implementation (workday/weekend toggle)
  /api/bridge/model-control   — slim Ollama proxy (load/unload on hub or node)
"""

import os
import logging
import threading
from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
import requests

from services.agent_service import list_agents

from .helpers import (
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
        """Slim model catalog lookup — DB only, no Ollama calls."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT model_name, display_name, description, tier, category, size_gb, parameter_size "
                "FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
            )
            catalog = {m["model_name"]: dict(m) for m in cur.fetchall()}
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
                            "ram_security_gb": 0,
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
        """Toggle between workday (all models warm) and weekend (all unloaded)."""
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

            if mode == "weekend":

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

                def _warmup():
                    try:
                        from app import _warmup_ollama_models

                        _warmup_ollama_models()
                    except Exception as e:
                        logger.error(f"[FleetMode] Workday Ollama warmup error: {e}")

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
        """Model load/unload — primary implementation now in Department HQ.

        This is a slim proxy that calls Ollama directly for backward compat
        with starbase.js.  Supports hub and node targets.

        Body: { "model": "phi3.5:latest", "action": "load"|"unload", "node_id": null }
        """
        if not current_user.is_admin:
            return jsonify({"success": False, "error": "Admin access required"}), 403

        data = request.get_json() or {}
        model = data.get("model", "").strip()
        action = data.get("action", "").strip()
        node_db_id = data.get("node_id")

        if not model or action not in ("load", "unload"):
            return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

        # Determine Ollama target URL
        ollama_url = OLLAMA_LOCAL_URL
        target_name = "hub"

        if node_db_id:
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT hostname, port FROM remote_nodes WHERE id = %s AND is_active = true",
                        (int(node_db_id),),
                    )
                    node = cur.fetchone()
                    if not node:
                        return jsonify({"success": False, "error": "Node not found"}), 404
                    ollama_url = f"http://{node['hostname']}:{node['port']}"
                    target_name = f"node {node_db_id}"
            except Exception as e:
                return jsonify({"success": False, "error": f"Node lookup failed: {e}"}), 500

        if not ollama_url.startswith("http"):
            ollama_url = f"http://{ollama_url}"

        try:
            if action == "load":
                resp = requests.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": "", "keep_alive": "24h"},
                    timeout=300,
                )
            else:
                resp = requests.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "keep_alive": 0},
                    timeout=30,
                )

            if resp.ok:
                return jsonify({"success": True, "message": f"{model} {action}ed on {target_name}"})
            return jsonify({"success": False, "error": f"Ollama returned {resp.status_code}"}), 502
        except requests.Timeout:
            return jsonify({"success": False, "error": "Model load timed out (300s)"}), 504
        except Exception as e:
            logger.error(f"model_control error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
