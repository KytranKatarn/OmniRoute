"""
Model Management Routes — Migrated from Starbase crew_routes.py

Endpoints for model catalog, load/unload control, cluster inventory,
VRAM budget monitoring, and fleet mode toggling.

Pattern: register_model_routes(bp, admin_required) per ADR-045.
"""

import logging
import os

import requests
from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"


def _get_cached_ollama_tags():
    """Fetch loaded model tags from Ollama /api/tags with short timeout."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logger.warning("Failed to fetch Ollama tags: %s", e)
        return []


def _get_cached_ollama_ps():
    """Fetch currently running models from Ollama /api/ps with short timeout."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logger.warning("Failed to fetch Ollama ps: %s", e)
        return []


def register_model_routes(bp, admin_required):
    """Register model management routes on the Department HQ blueprint."""

    @bp.route("/api/models/catalog")
    @login_required
    @admin_required
    def api_model_catalog():
        """Model catalog from model_catalog table."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT model_name, display_name, description, tier, category, "
                    "size_gb, parameter_size "
                    "FROM model_catalog WHERE is_active = true "
                    "ORDER BY category, size_gb"
                )
                models = cur.fetchall()
                catalog = {m["model_name"]: dict(m) for m in models}
                return jsonify({"success": True, "catalog": catalog})
        except Exception as e:
            logger.error("Model catalog error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/models/control", methods=["POST"])
    @login_required
    @admin_required
    def api_model_control():
        """Load or unload an Ollama model on hub or a fleet node.

        Body: {model, action: "load"|"unload", num_gpu (optional), node_id (optional)}
        """
        try:
            data = request.get_json(force=True)
            model = data.get("model")
            action = data.get("action")
            num_gpu = data.get("num_gpu")
            node_id = data.get("node_id")

            if not model or action not in ("load", "unload"):
                return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

            # Determine target Ollama URL (hub or node)
            target_url = OLLAMA_URL
            if node_id:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT hostname, ollama_port FROM remote_nodes " "WHERE id = %s AND status = 'online'",
                        (node_id,),
                    )
                    node = cur.fetchone()
                    if not node:
                        return jsonify({"success": False, "error": f"Node {node_id} not found or offline"}), 404
                    node_host = node["hostname"]
                    node_port = node.get("ollama_port", 11434)
                    target_url = f"http://{node_host}:{node_port}"

            if action == "load":
                # Check if already loaded
                try:
                    ps_resp = requests.get(f"{target_url}/api/ps", timeout=5)
                    if ps_resp.ok:
                        running = ps_resp.json().get("models", [])
                        for m in running:
                            if m.get("name", "").startswith(model):
                                return jsonify(
                                    {"success": True, "message": f"{model} already loaded", "already_loaded": True}
                                )
                except Exception:
                    pass  # Proceed with load attempt

                # Use Bridge dispatcher for load
                try:
                    from tools.department_hq.services.bridge_dispatcher import get_dispatcher

                    dispatcher = get_dispatcher()
                    opts = {}
                    if num_gpu is not None:
                        opts["num_gpu"] = num_gpu
                    if node_id:
                        opts["node_id"] = node_id
                    dispatcher.ensure_model_ready(model, **opts)
                    return jsonify({"success": True, "message": f"{model} loaded successfully"})
                except Exception as e:
                    logger.error("Model load via dispatcher failed: %s", e)
                    # Fallback: direct Ollama generate with keep_alive
                    try:
                        payload = {"model": model, "keep_alive": "5m"}
                        if num_gpu is not None:
                            payload["options"] = {"num_gpu": num_gpu}
                        resp = requests.post(
                            f"{target_url}/api/generate",
                            json=payload,
                            timeout=300,
                        )
                        if resp.ok:
                            return jsonify({"success": True, "message": f"{model} loaded (fallback)"})
                        return jsonify({"success": False, "error": f"Load failed: {resp.status_code}"}), 500
                    except Exception as fallback_err:
                        return jsonify({"success": False, "error": f"Load failed: {fallback_err}"}), 500

            else:  # unload
                try:
                    resp = requests.post(
                        f"{target_url}/api/generate",
                        json={"model": model, "keep_alive": 0},
                        timeout=30,
                    )
                    if resp.ok:
                        return jsonify({"success": True, "message": f"{model} unloaded"})
                    return jsonify({"success": False, "error": f"Unload failed: {resp.status_code}"}), 500
                except Exception as e:
                    return jsonify({"success": False, "error": f"Unload failed: {e}"}), 500

        except Exception as e:
            logger.error("Model control error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/models/cluster")
    @login_required
    @admin_required
    def api_model_cluster():
        """Unified model inventory across hub + all online nodes."""
        try:
            cluster = {}

            # Hub models
            hub_tags = _get_cached_ollama_tags()
            hub_ps = _get_cached_ollama_ps()
            running_names = {m.get("name", "") for m in hub_ps}

            hub_models = []
            for m in hub_tags:
                name = m.get("name", m.get("model", ""))
                hub_models.append(
                    {
                        "name": name,
                        "size": m.get("size", 0),
                        "modified_at": m.get("modified_at", ""),
                        "running": name in running_names,
                        "details": m.get("details", {}),
                    }
                )
            cluster["hub"] = {
                "models": hub_models,
                "running": [dict(m) for m in hub_ps],
            }

            # Node models from DB
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT rn.id AS node_id, rn.node_name, rn.hostname, "
                    "nom.model_name, nom.model_size_gb, nom.is_available, nom.updated_at "
                    "FROM remote_nodes rn "
                    "LEFT JOIN node_ollama_models nom ON nom.node_id = rn.node_id "
                    "WHERE rn.is_active = true "
                    "ORDER BY rn.node_name, nom.model_name"
                )
                rows = cur.fetchall()

            nodes = {}
            for row in rows:
                nid = row["node_id"]
                if nid not in nodes:
                    nodes[nid] = {
                        "node_id": nid,
                        "display_name": row["node_name"],
                        "hostname": row["hostname"],
                        "models": [],
                    }
                if row["model_name"]:
                    nodes[nid]["models"].append(
                        {
                            "name": row["model_name"],
                            "size_gb": float(row["model_size_gb"] or 0),
                            "available": bool(row["is_available"]),
                            "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
                        }
                    )
            cluster["nodes"] = list(nodes.values())

            return jsonify({"success": True, "cluster": cluster})
        except Exception as e:
            logger.error("Model cluster error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/models/vram-budget")
    @login_required
    @admin_required
    def api_model_vram_budget():
        """Current VRAM/RAM usage from agent_models service."""
        try:
            from services.agent_models import check_vram_budget

            budget = check_vram_budget()
            return jsonify({"success": True, "budget": budget})
        except ImportError:
            return jsonify({"success": False, "error": "agent_models service not available"}), 500
        except Exception as e:
            logger.error("VRAM budget error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/models/fleet-mode", methods=["POST"])
    @login_required
    @admin_required
    def api_model_fleet_mode():
        """Toggle workday/weekend fleet mode.

        Body: {mode: "workday"|"weekend"}
        Workday: loads all agent-assigned models.
        Weekend: unloads all agent models to free resources.
        """
        try:
            data = request.get_json(force=True)
            mode = data.get("mode")

            if mode not in ("workday", "weekend"):
                return jsonify({"success": False, "error": "mode must be 'workday' or 'weekend'"}), 400

            # Get agent-assigned models
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT DISTINCT a.model_name FROM agents a "
                    "WHERE a.model_name IS NOT NULL AND a.is_active = true "
                    "AND a.shift_state IN ('active', 'deployed')"
                )
                agent_models = [row["model_name"] for row in cur.fetchall()]

            if not agent_models:
                return jsonify({"success": True, "message": "No agent models found", "affected": 0})

            results = []
            if mode == "workday":
                # Load all agent models
                for model_name in agent_models:
                    try:
                        resp = requests.post(
                            f"{OLLAMA_URL}/api/generate",
                            json={"model": model_name, "keep_alive": "5m"},
                            timeout=300,
                        )
                        results.append({"model": model_name, "success": resp.ok})
                    except Exception as e:
                        results.append({"model": model_name, "success": False, "error": str(e)})
            else:
                # Unload all agent models
                for model_name in agent_models:
                    try:
                        resp = requests.post(
                            f"{OLLAMA_URL}/api/generate",
                            json={"model": model_name, "keep_alive": 0},
                            timeout=30,
                        )
                        results.append({"model": model_name, "success": resp.ok})
                    except Exception as e:
                        results.append({"model": model_name, "success": False, "error": str(e)})

            succeeded = sum(1 for r in results if r["success"])
            return jsonify(
                {
                    "success": True,
                    "mode": mode,
                    "affected": len(agent_models),
                    "succeeded": succeeded,
                    "results": results,
                }
            )
        except Exception as e:
            logger.error("Fleet mode error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500
