"""
Starship Command — Fleet node management module.

Starbase (hub) overview + fleet node management.
2 tabs: FLEET, OPERATIONS.
"""

import logging

from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from database import get_db_cursor

from .helpers import _get_user_nodes, _compute_node_status

logger = logging.getLogger(__name__)

starship_bp = Blueprint(
    "starship",
    __name__,
    template_folder="templates",
    url_prefix="/tools/starship",
)


@starship_bp.route("/")
@login_required
def starship_dashboard():
    user_id = current_user.id
    is_admin = getattr(current_user, "is_admin", False)

    # User's own nodes (for FLEET/OPERATIONS management)
    nodes = []
    try:
        raw_nodes = _get_user_nodes(user_id)
        for n in raw_nodes:
            d = dict(n)
            d["status"] = _compute_node_status(n)
            nodes.append(d)
    except Exception:
        pass

    # All active nodes (public — for docked fleet strip, visible to everyone)
    fleet_nodes = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT rn.node_id, rn.node_name, rn.deployment_mode, rn.status,
                          rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb, rn.last_heartbeat,
                          u.username as owner_name
                   FROM remote_nodes rn
                   LEFT JOIN users u ON u.id = rn.registered_by
                   WHERE rn.is_active = true
                   ORDER BY rn.bridge_priority DESC, rn.node_name"""
            )
            for n in cur.fetchall():
                d = dict(n)
                d["status"] = _compute_node_status(n)
                fleet_nodes.append(d)
    except Exception:
        pass

    return render_template(
        "tools/starship/starship.html",
        nodes=nodes,
        fleet_nodes=fleet_nodes,
        is_admin=is_admin,
        is_owner=len(nodes) > 0,
    )


@starship_bp.route("/api/nodes")
@login_required
def api_list_nodes():
    """List all nodes owned by current user."""
    user_id = current_user.id
    try:
        nodes = _get_user_nodes(user_id)
        result = []
        for n in nodes:
            result.append(
                {
                    "node_id": n["node_id"],
                    "node_name": n["node_name"],
                    "deployment_mode": n["deployment_mode"],
                    "hostname": n["hostname"],
                    "status": _compute_node_status(n),
                    "is_active": n["is_active"],
                    "bridge_enabled": n["bridge_enabled"],
                    "bridge_priority": n["bridge_priority"],
                    "approval_status": n["approval_status"],
                    "gpu_model": n["gpu_model"],
                    "gpu_vram_gb": float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else None,
                    "cpu_model": n["cpu_model"],
                    "cpu_cores": n["cpu_cores"],
                    "ram_gb": float(n["ram_gb"]) if n["ram_gb"] else None,
                    "disk_gb": float(n["disk_gb"]) if n["disk_gb"] else None,
                    "last_heartbeat": n["last_heartbeat"].isoformat() if n["last_heartbeat"] else None,
                    "privacy_settings": n["privacy_settings"],
                }
            )
        return jsonify({"success": True, "nodes": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/fleet-agents")
@login_required
def api_fleet_agents():
    """Public endpoint — agent counts per node for docked fleet strip."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT rn.node_id,
                          (SELECT COUNT(*) FROM node_agents na
                           WHERE na.node_id = rn.id AND na.status = 'active') as agent_count
                   FROM remote_nodes rn
                   WHERE rn.is_active = true AND rn.deployment_mode != 'starbase'"""
            )
            nodes = [{"node_id": r["node_id"], "agent_count": r["agent_count"]} for r in cur.fetchall()]
        return jsonify({"success": True, "nodes": nodes})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/starbase-stats")
@login_required
def api_starbase_stats():
    """Hero Starbase stats — real data from dispatcher + DB."""
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        manifest = dispatcher.get_crew_manifest()

        active_agents = sum(1 for a in manifest if a.get("status") == "active")
        loaded_models = sum(1 for a in manifest if a.get("llm_status") == "loaded")
        active_jobs = sum(1 for a in manifest if a.get("current_job"))

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) as cnt FROM remote_nodes WHERE is_active = true")
            node_count = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT COUNT(*) as cnt FROM remote_nodes
                   WHERE is_active = true
                   AND (last_heartbeat > NOW() - INTERVAL '2 minutes'
                        OR deployment_mode = 'starbase')"""
            )
            online_count = cur.fetchone()["cnt"]

        return jsonify(
            {
                "success": True,
                "total_agents": len(manifest),
                "active_agents": active_agents,
                "loaded_models": loaded_models,
                "active_jobs": active_jobs,
                "total_nodes": node_count,
                "online_nodes": online_count,
            }
        )
    except Exception as e:
        logger.error(f"Starbase stats error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
