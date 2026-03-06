"""
Starship Command — Fleet node management module.

Fleet owners see all their nodes. Node operators see their own ship.
Privacy controls let operators choose what to share with the fleet.
"""

import json
import os
import secrets

from flask import Blueprint, render_template, jsonify, request, send_file
from flask_login import login_required, current_user
from database import get_db_cursor

starship_bp = Blueprint(
    "starship",
    __name__,
    url_prefix="/tools/starship",
    template_folder="templates",
)


def _get_user_nodes(user_id):
    """Get all starship nodes owned by this user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT node_id, node_name, deployment_mode, hostname, port,
                   status, is_active, bridge_enabled, bridge_priority,
                   gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                   approval_status, last_heartbeat,
                   COALESCE(privacy_settings, '{}'::jsonb) as privacy_settings
            FROM remote_nodes
            WHERE user_id = %s
            ORDER BY bridge_priority DESC, node_name
            """,
            (user_id,),
        )
        return cur.fetchall()


def _get_node_for_user(node_id, user_id, require_owner=True):
    """Get a specific node, optionally verifying ownership."""
    with get_db_cursor() as (conn, cur):
        if require_owner:
            cur.execute(
                "SELECT * FROM remote_nodes WHERE node_id = %s AND user_id = %s",
                (node_id, user_id),
            )
        else:
            cur.execute("SELECT * FROM remote_nodes WHERE node_id = %s", (node_id,))
        return cur.fetchone()


# ============================================================================
# MAIN PAGE
# ============================================================================


@starship_bp.route("/")
@login_required
def starship_dashboard():
    user_id = current_user.id
    nodes = []
    try:
        nodes = _get_user_nodes(user_id)
    except Exception:
        pass
    is_admin = getattr(current_user, "is_admin", False)
    return render_template(
        "tools/starship/starship.html",
        nodes=nodes,
        is_admin=is_admin,
    )


# ============================================================================
# FLEET API
# ============================================================================


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
                    "status": n["status"],
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


@starship_bp.route("/api/nodes/<node_id>/status")
@login_required
def api_node_status(node_id):
    """Get detailed status for a specific node."""
    user_id = current_user.id
    try:
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        # Get models for this node
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT model_name, model_size_gb, is_loaded, is_available,
                       context_length, quantization
                FROM node_ollama_models
                WHERE node_id = %s
                ORDER BY model_name
                """,
                (node_id,),
            )
            models = cur.fetchall()

            # Get job stats
            cur.execute(
                """
                SELECT COUNT(*) as total_jobs,
                       COUNT(*) FILTER (WHERE status = 'completed') as completed_jobs,
                       COUNT(*) FILTER (WHERE status = 'failed') as failed_jobs
                FROM bridge_jobs
                WHERE node_id = %s
                """,
                (node_id,),
            )
            stats = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "node": {
                    "node_id": node["node_id"],
                    "node_name": node["node_name"],
                    "status": node["status"],
                    "deployment_mode": node["deployment_mode"],
                    "bridge_priority": node["bridge_priority"],
                    "last_heartbeat": node["last_heartbeat"].isoformat() if node["last_heartbeat"] else None,
                    "privacy_settings": node.get("privacy_settings", {}),
                },
                "hardware": {
                    "cpu_model": node["cpu_model"],
                    "cpu_cores": node["cpu_cores"],
                    "ram_gb": float(node["ram_gb"]) if node["ram_gb"] else None,
                    "gpu_model": node["gpu_model"],
                    "gpu_vram_gb": float(node["gpu_vram_gb"]) if node["gpu_vram_gb"] else None,
                    "disk_gb": float(node["disk_gb"]) if node["disk_gb"] else None,
                },
                "models": [
                    {
                        "model_name": m["model_name"],
                        "model_size_gb": float(m["model_size_gb"]) if m["model_size_gb"] else None,
                        "is_loaded": m["is_loaded"],
                        "is_available": m["is_available"],
                        "context_length": m["context_length"],
                        "quantization": m["quantization"],
                    }
                    for m in models
                ],
                "stats": {
                    "total_jobs": stats["total_jobs"],
                    "completed_jobs": stats["completed_jobs"],
                    "failed_jobs": stats["failed_jobs"],
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/nodes/<node_id>/profile", methods=["POST"])
@login_required
def api_update_profile(node_id):
    """Update node display name."""
    user_id = current_user.id
    node = _get_node_for_user(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404

    data = request.get_json() or {}
    display_name = data.get("display_name", "").strip()
    if not display_name:
        return jsonify({"success": False, "error": "Name required"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE remote_nodes SET node_name = %s WHERE node_id = %s",
            (display_name, node_id),
        )
    return jsonify({"success": True})


@starship_bp.route("/api/nodes/<node_id>/privacy", methods=["POST"])
@login_required
def api_update_privacy(node_id):
    """Update privacy settings for a node."""
    user_id = current_user.id
    node = _get_node_for_user(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404

    import psycopg2

    data = request.get_json() or {}
    settings = {
        "share_hardware": data.get("share_hardware", True),
        "share_models": data.get("share_models", True),
        "share_job_stats": data.get("share_job_stats", True),
        "share_hostname": data.get("share_hostname", False),
        "local_data_only": data.get("local_data_only", False),
    }

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE remote_nodes SET privacy_settings = %s WHERE node_id = %s",
            (psycopg2.Json(settings), node_id),
        )
    return jsonify({"success": True, "privacy_settings": settings})


# ============================================================================
# NODE SETUP / ONBOARDING
# ============================================================================

NODE_CLIENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "node_client",
)


@starship_bp.route("/api/request-node", methods=["POST"])
@login_required
def api_request_node():
    """Generate a setup token and pre-register a pending node for this user."""
    import psycopg2

    user_id = current_user.id
    data = request.get_json() or {}
    node_name = data.get("node_name", "").strip() or f"Starship-{secrets.token_hex(3).upper()}"

    # Generate unique node ID and setup token
    node_id = f"starship_{secrets.token_hex(8)}"
    setup_token = secrets.token_urlsafe(32)

    # Get starbase hostname for the config
    starbase_host = os.getenv("STARBASE_HOST", request.host.split(":")[0])
    starbase_port = os.getenv("STARBASE_PORT", "3000")

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO remote_nodes (
                    node_id, node_name, deployment_mode, status,
                    is_active, bridge_enabled, bridge_priority,
                    approval_status, user_id, setup_token,
                    privacy_settings
                ) VALUES (
                    %s, %s, 'starship', 'pending',
                    false, false, 50,
                    'pending', %s, %s,
                    '{}'::jsonb
                )
                RETURNING node_id, node_name
                """,
                (node_id, node_name, user_id, setup_token),
            )
            row = cur.fetchone()

        # Build config for the node
        config = {
            "node_id": node_id,
            "node_name": node_name,
            "setup_token": setup_token,
            "starbase_url": f"http://{starbase_host}:{starbase_port}",
            "deployment_mode": "starship",
            "heartbeat_interval": 30,
        }

        return jsonify(
            {
                "success": True,
                "node_id": row["node_id"],
                "node_name": row["node_name"],
                "setup_token": setup_token,
                "config": config,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/setup-instructions/<node_id>")
@login_required
def api_setup_instructions(node_id):
    """Get setup instructions and config for a pending node."""
    user_id = current_user.id
    node = _get_node_for_user(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404

    starbase_host = os.getenv("STARBASE_HOST", request.host.split(":")[0])
    starbase_port = os.getenv("STARBASE_PORT", "3000")

    config = {
        "node_id": node["node_id"],
        "node_name": node["node_name"],
        "setup_token": node.get("setup_token", ""),
        "starbase_url": f"http://{starbase_host}:{starbase_port}",
        "deployment_mode": "starship",
        "heartbeat_interval": 30,
    }

    return jsonify({"success": True, "config": config})


@starship_bp.route("/download/node-package")
@login_required
def download_node_package():
    """Download the starship node package (tar.gz)."""
    package_path = os.path.join(NODE_CLIENT_DIR, "archie-node-latest.tar.gz")
    if os.path.exists(package_path):
        return send_file(
            package_path,
            as_attachment=True,
            download_name="archie-starship-node.tar.gz",
        )
    return jsonify({"success": False, "error": "Package not found"}), 404
