"""Starbase Command — Node routes (remote nodes, approval, station assignments)"""

import hashlib
from hmac import compare_digest
import json
import os
import time
import logging
from datetime import datetime
from flask import jsonify, request, Response
from flask_login import login_required, current_user
from rbac import require_permission, Permission
import psycopg2
from database import get_db_cursor
import requests

from .helpers import DEFAULT_NODE_PORT, DEFAULT_CLIENT_VERSION, LATEST_CLIENT_VERSION

logger = logging.getLogger(__name__)


def register_node_routes(bp, admin_required):
    """Register node-related routes on the bridge blueprint."""

    # ============================================================================
    # REMOTE NODES API - Phase 29
    # ============================================================================

    import secrets  # noqa: E402 (hashlib already imported at top)

    def generate_node_id():
        """Generate a unique node ID"""
        return f"node_{secrets.token_hex(8)}"

    def hash_api_key(api_key):
        """Hash an API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def verify_api_key(api_key, stored_hash):
        """Verify an API key against stored hash (constant-time comparison)"""
        return compare_digest(hash_api_key(api_key), stored_hash)

    @bp.route("/api/nodes")
    @login_required
    def get_all_nodes():
        """Get all registered remote nodes"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                status_filter = request.args.get("status", "all")
                approval_filter = request.args.get("approval", "all")
                active_only = request.args.get("active", "true").lower() == "true"

                query = """
                    SELECT rn.id, rn.node_id, rn.node_name, rn.description, rn.vpn_ip, rn.hostname, rn.port,
                           rn.status, rn.last_heartbeat, rn.last_error, rn.error_count,
                           rn.client_version, rn.gpu_available, rn.gpu_model, rn.gpu_vram_gb,
                           rn.cpu_cores, rn.cpu_model, rn.ram_gb, rn.disk_gb, rn.os_info, rn.ollama_available,
                           rn.priority, rn.weight, rn.max_concurrent, rn.current_load,
                           rn.total_requests, rn.successful_requests, rn.failed_requests, rn.avg_latency_ms,
                           rn.tags, rn.is_active, rn.created_at, rn.updated_at,
                           rn.approval_status, rn.approved_by, rn.approved_at,
                           rn.bridge_enabled, rn.bridge_priority, rn.last_model_sync,
                           o.name AS org_name, o.id AS org_id
                    FROM remote_nodes rn
                    LEFT JOIN organizations o ON o.node_id = rn.node_id
                    WHERE 1=1
                """
                params = []

                if active_only:
                    query += " AND rn.is_active = TRUE"

                if status_filter != "all":
                    query += " AND rn.status = %s"
                    params.append(status_filter)

                if approval_filter != "all":
                    query += " AND rn.approval_status = %s"
                    params.append(approval_filter)

                query += " ORDER BY CASE rn.approval_status WHEN 'pending' THEN 0 ELSE 1 END, rn.priority, rn.node_name"

                cur.execute(query, params)
                nodes = cur.fetchall()

                # Get summary stats including approval counts
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'online' AND approval_status = 'approved') as online,
                        COUNT(*) FILTER (WHERE status = 'offline' AND approval_status = 'approved') as offline,
                        COUNT(*) FILTER (WHERE status = 'degraded' AND approval_status = 'approved') as degraded,
                        COUNT(*) FILTER (WHERE approval_status = 'pending') as pending,
                        COUNT(*) FILTER (WHERE approval_status = 'approved') as approved,
                        COUNT(*) FILTER (WHERE approval_status = 'rejected') as rejected,
                        SUM(current_load) FILTER (WHERE approval_status = 'approved') as total_load,
                        SUM(max_concurrent) FILTER (WHERE approval_status = 'approved') as total_capacity
                    FROM remote_nodes
                    WHERE is_active = TRUE
                """
                )
                summary = cur.fetchone()

                # Convert datetime
                for node in nodes:
                    for key in ["last_heartbeat", "created_at", "updated_at", "approved_at"]:
                        if node.get(key):
                            node[key] = node[key].isoformat()

                return jsonify({"success": True, "nodes": nodes, "summary": summary})

        except Exception as e:
            logger.error(f"Error getting nodes: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/install.sh", methods=["GET"])
    def get_node_install_script():
        """Serve the node installation script"""
        import os

        script_path = "/mnt/archie_brain/node_client/install.sh"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="install.sh"',
                },
            )
        else:
            return "Install script not found", 404

    @bp.route("/api/nodes/install.ps1", methods=["GET"])
    def get_node_install_script_windows():
        """Serve the Windows PowerShell installation script"""
        import os

        script_path = "/mnt/archie_brain/node_client/install.ps1"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="install.ps1"',
                },
            )
        else:
            return "Install script not found", 404

    @bp.route("/api/nodes/heartbeat.ps1", methods=["GET"])
    def get_node_heartbeat_script_windows():
        """Serve the Windows PowerShell heartbeat script"""
        import os

        script_path = "/mnt/archie_brain/node_client/heartbeat.ps1"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="heartbeat.ps1"',
                },
            )
        else:
            return "Heartbeat script not found", 404

    @bp.route("/api/nodes/update.ps1", methods=["GET"])
    def get_node_update_script_windows():
        """Serve the Windows PowerShell update script"""
        import os

        script_path = "/mnt/archie_brain/node_client/update.ps1"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="update.ps1"',
                },
            )
        else:
            return "Update script not found", 404

    @bp.route("/api/nodes/heartbeat.sh", methods=["GET"])
    def get_node_heartbeat_script_linux():
        """Serve the Linux heartbeat script"""
        import os

        script_path = "/mnt/archie_brain/node_client/heartbeat.sh"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="heartbeat.sh"',
                },
            )
        else:
            return "Heartbeat script not found", 404

    @bp.route("/api/nodes/docker-compose.node.yml", methods=["GET"])
    def get_node_docker_compose():
        """Serve the node Docker Compose template"""
        script_path = "/mnt/archie_brain/node_client/docker-compose.node.yml"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/yaml",
                headers={"Content-Disposition": "attachment; filename=docker-compose.node.yml"},
            )
        return (
            jsonify({"success": False, "error": "Docker Compose template not found"}),
            404,
        )

    @bp.route("/api/nodes/deploy-node.ps1", methods=["GET"])
    def get_node_deploy_script():
        """Serve the Windows deploy script (no auth needed)"""
        script_path = "/mnt/archie_brain/node_client/deploy-node.ps1"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            content = content.replace("http://192.168.1.200:3000", server_url)

            from flask import Response

            return Response(
                content,
                mimetype="text/plain",
                headers={"Content-Disposition": "attachment; filename=deploy-node.ps1"},
            )
        return jsonify({"success": False, "error": "Deploy script not found"}), 404

    @bp.route("/api/nodes/node_sync.py", methods=["GET"])
    def get_node_sync_service():
        """Serve the node sync service script"""
        script_path = "/mnt/archie_brain/node_client/node_sync.py"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-python",
                headers={"Content-Disposition": "attachment; filename=node_sync.py"},
            )
        return jsonify({"success": False, "error": "Sync service script not found"}), 404

    @bp.route("/api/nodes/Dockerfile.node", methods=["GET"])
    def get_node_dockerfile():
        """Serve the node Dockerfile"""
        script_path = "/mnt/archie_brain/node_client/Dockerfile.node"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/plain",
                headers={"Content-Disposition": "attachment; filename=Dockerfile.node"},
            )
        return jsonify({"success": False, "error": "Dockerfile.node not found"}), 404

    @bp.route("/api/nodes/node_api.py", methods=["GET"])
    def get_node_api_service():
        """Serve the node API service script"""
        script_path = "/mnt/archie_brain/node_client/node_api.py"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-python",
                headers={"Content-Disposition": "attachment; filename=node_api.py"},
            )
        return jsonify({"success": False, "error": "node_api.py not found"}), 404

    @bp.route("/api/nodes/migrations/<filename>", methods=["GET"])
    def get_node_migration(filename):
        """Serve node migration SQL files"""
        import re

        # Sanitize filename — only allow typical migration filenames
        if not re.match(r"^[0-9a-zA-Z_\-]+\.sql$", filename):
            return jsonify({"success": False, "error": "Invalid filename"}), 400
        script_path = f"/mnt/archie_brain/node_client/migrations/{filename}"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="application/sql",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        return jsonify({"success": False, "error": f"Migration {filename} not found"}), 404

    @bp.route("/api/nodes/archie-node-latest.tar.gz", methods=["GET"])
    def serve_node_image():
        """Serve the pre-built node Docker image tarball (legacy fallback)"""
        from flask import send_file

        # Check multiple locations: node_client dir (mounted in container) and /tmp (host builds)
        tarball_paths = [
            "/mnt/archie_brain/node_client/archie-node-latest.tar.gz",
            "/tmp/archie-node-latest.tar.gz",
        ]
        tarball_path = None
        for path in tarball_paths:
            if os.path.isfile(path):
                tarball_path = path
                break
        if tarball_path is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Node image not built yet. Nodes now build locally from Dockerfile.node.",
                    }
                ),
                404,
            )
        return send_file(
            tarball_path,
            mimetype="application/gzip",
            as_attachment=True,
            download_name="archie-node-latest.tar.gz",
        )

    @bp.route("/api/nodes/client-package", methods=["GET"])
    def get_node_client_package():
        """Serve the node client package as a tarball"""
        import os
        import tarfile
        import io

        node_client_dir = "/mnt/archie_brain/node_client"

        if not os.path.exists(node_client_dir):
            return (
                jsonify({"success": False, "error": "Node client package not found"}),
                404,
            )

        try:
            # Create tarball in memory
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
                for filename in os.listdir(node_client_dir):
                    # Skip certain files
                    if filename.startswith(".") and filename not in [".env.example"]:
                        continue
                    if filename == "__pycache__":
                        continue

                    filepath = os.path.join(node_client_dir, filename)
                    if os.path.isfile(filepath):
                        tar.add(filepath, arcname=filename)

            tar_buffer.seek(0)

            return (
                tar_buffer.read(),
                200,
                {
                    "Content-Type": "application/gzip",
                    "Content-Disposition": 'attachment; filename="archie-node-client.tar.gz"',
                },
            )

        except Exception as e:
            logger.error(f"Error creating client package: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    def calculate_max_concurrent(ram_gb: float, cpu_cores: int, gpu_vram_gb: float = 0) -> int:
        """
        Calculate recommended max_concurrent tasks based on hardware.
        Formula:
        - Base: 1 task per 4GB RAM (LLMs need memory)
        - CPU bonus: +1 per 8 cores (parallel processing)
        - GPU bonus: +2 if VRAM >= 8GB, +4 if VRAM >= 16GB (GPU acceleration)
        - Minimum: 2, Maximum: 20
        """
        base = int((ram_gb or 8) / 4)  # 1 per 4GB RAM
        cpu_bonus = int((cpu_cores or 4) / 8)  # +1 per 8 cores
        gpu_bonus = 0
        if gpu_vram_gb:
            if gpu_vram_gb >= 16:
                gpu_bonus = 4
            elif gpu_vram_gb >= 8:
                gpu_bonus = 2

        total = base + cpu_bonus + gpu_bonus
        return max(2, min(20, total))  # Clamp between 2 and 20

    @bp.route("/api/nodes/register", methods=["POST"])
    def register_node():
        """Register a new remote node"""
        data = request.get_json() or {}

        required = ["node_name"]
        for field in required:
            if not data.get(field):
                return jsonify({"success": False, "error": f"{field} is required"}), 400

        # Validate hardware fields if provided
        if "ram_gb" in data and data["ram_gb"] is not None:
            try:
                ram = float(data["ram_gb"])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "ram_gb must be a number"}), 400
            if ram <= 0:
                return jsonify({"success": False, "error": "ram_gb must be positive"}), 400

        if "cpu_cores" in data and data["cpu_cores"] is not None:
            try:
                cores = int(data["cpu_cores"])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "cpu_cores must be an integer"}), 400
            if cores <= 0:
                return jsonify({"success": False, "error": "cpu_cores must be positive"}), 400

        try:
            with get_db_cursor() as (conn, cur):

                # Generate node ID and API key
                node_id = generate_node_id()
                api_key = secrets.token_urlsafe(32)
                api_key_hash = hash_api_key(api_key)

                cur.execute(
                    """
                    INSERT INTO remote_nodes (
                        node_id, node_name, description, vpn_ip, hostname, port,
                        api_key_hash, client_version, gpu_available, gpu_model,
                        gpu_vram_gb, cpu_cores, cpu_model, ram_gb, disk_gb, os_info,
                        ollama_available, foocus_available, comfyui_available, auto1111_available,
                        docker_available, docker_version, nvidia_docker, wsl_available,
                        foocus_port, comfyui_port, auto1111_port,
                        iaae_compliant, priority, weight, max_concurrent, tags,
                        approval_status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id, node_id, node_name, approval_status
                """,
                    (
                        node_id,
                        data.get("node_name"),
                        data.get("description"),
                        data.get("vpn_ip"),
                        data.get("hostname"),
                        data.get("port", DEFAULT_NODE_PORT),
                        api_key_hash,
                        data.get("client_version", DEFAULT_CLIENT_VERSION),
                        data.get("gpu_available", False),
                        data.get("gpu_model"),
                        data.get("gpu_vram_gb"),
                        data.get("cpu_cores"),
                        data.get("cpu_model"),
                        data.get("ram_gb"),
                        data.get("disk_gb"),
                        data.get("os_info"),
                        data.get("ollama_available", False),
                        data.get("foocus_available", False),
                        data.get("comfyui_available", False),
                        data.get("auto1111_available", False),
                        data.get("docker_available", False),
                        data.get("docker_version"),
                        data.get("nvidia_docker", False),
                        data.get("wsl_available", False),
                        # AI Service ports for dynamic routing (Phase 72)
                        data.get("foocus_port", 7865),
                        data.get("comfyui_port", 8188),
                        data.get("auto1111_port", 7860),
                        data.get("iaae_compliant", True),
                        data.get("priority", 10),
                        data.get("weight", 100),
                        # Smart max_concurrent based on hardware (or use provided value)
                        data.get("max_concurrent")
                        or calculate_max_concurrent(
                            data.get("ram_gb", 8),
                            data.get("cpu_cores", 4),
                            data.get("gpu_vram_gb", 0),
                        ),
                        data.get("tags", []),
                        "pending",  # New nodes start as pending
                    ),
                )

                node = cur.fetchone()

                # Calculate the actual max_concurrent that was stored
                calculated_max = data.get("max_concurrent") or calculate_max_concurrent(
                    data.get("ram_gb", 8), data.get("cpu_cores", 4), data.get("gpu_vram_gb", 0)
                )

                # Return config settings for the node client
                return jsonify(
                    {
                        "success": True,
                        "node_id": node["node_id"],
                        "api_key": api_key,  # Only returned once at registration!
                        "approval_status": node["approval_status"],
                        "config": {
                            "heartbeat_interval": 30,
                            "capability_interval": 300,
                            "max_concurrent": calculated_max,
                            "log_level": "INFO",
                        },
                        "message": (
                            "Node registered. Awaiting admin approval."
                            if node["approval_status"] == "pending"
                            else "Node registered successfully."
                        ),
                        "hardware_recommendation": (
                            f'Based on {data.get("ram_gb", 8)}GB RAM, '
                            f'{data.get("cpu_cores", 4)} cores, '
                            f"recommended max_concurrent: {calculated_max}"
                        ),
                    }
                )

        except Exception as e:
            logger.error(f"Error registering node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/heartbeat", methods=["POST"])
    def node_heartbeat(node_id):
        """Receive heartbeat from a remote node"""
        data = request.get_json() or {}
        api_key = request.headers.get("X-Node-API-Key")

        if not api_key:
            return jsonify({"success": False, "error": "API key required"}), 401

        try:
            with get_db_cursor() as (conn, cur):

                # Verify node and API key
                cur.execute(
                    """
                    SELECT id, api_key_hash, min_required_version
                    FROM remote_nodes WHERE node_id = %s AND is_active = TRUE AND approval_status = 'approved'
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                if not verify_api_key(api_key, node["api_key_hash"]):
                    return jsonify({"success": False, "error": "Invalid API key"}), 401

                # Version check
                client_version = data.get("client_version", DEFAULT_CLIENT_VERSION)
                # Simple version comparison (could be more sophisticated)

                # Determine status
                status = "online"
                if data.get("error"):
                    status = "degraded"

                # Update node status including AI service availability
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET status = %s,
                        last_heartbeat = NOW(),
                        current_load = %s,
                        client_version = %s,
                        cpu_cores = COALESCE(%s, cpu_cores),
                        cpu_model = COALESCE(%s, cpu_model),
                        ram_gb = COALESCE(%s, ram_gb),
                        gpu_available = COALESCE(%s, gpu_available),
                        gpu_model = COALESCE(%s, gpu_model),
                        gpu_vram_gb = COALESCE(%s, gpu_vram_gb),
                        -- AI Service availability (Phase 72)
                        ollama_available = COALESCE(%s, ollama_available),
                        foocus_available = COALESCE(%s, foocus_available),
                        comfyui_available = COALESCE(%s, comfyui_available),
                        auto1111_available = COALESCE(%s, auto1111_available),
                        foocus_port = COALESCE(%s, foocus_port),
                        comfyui_port = COALESCE(%s, comfyui_port),
                        auto1111_port = COALESCE(%s, auto1111_port),
                        last_error = %s,
                        error_count = CASE WHEN %s IS NOT NULL THEN error_count + 1 ELSE 0 END
                    WHERE id = %s
                """,
                    (
                        status,
                        data.get("current_load", 0),
                        client_version,
                        data.get("cpu_cores"),
                        data.get("cpu_model"),
                        data.get("ram_gb"),
                        data.get("gpu_available"),
                        data.get("gpu_model"),
                        data.get("gpu_vram_gb"),
                        # AI Services
                        data.get("ollama_online"),
                        data.get("foocus_available"),
                        data.get("comfyui_available"),
                        data.get("auto1111_available"),
                        data.get("foocus_port"),
                        data.get("comfyui_port"),
                        data.get("auto1111_port"),
                        data.get("error"),
                        data.get("error"),
                        node["id"],
                    ),
                )

                # Log heartbeat
                cur.execute(
                    """
                    INSERT INTO node_heartbeats (
                        node_id, status, latency_ms, cpu_usage, memory_usage,
                        gpu_usage, current_load, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        node["id"],
                        status,
                        data.get("latency_ms"),
                        data.get("cpu_usage"),
                        data.get("memory_usage"),
                        data.get("gpu_usage"),
                        data.get("current_load", 0),
                        psycopg2.extras.Json(data.get("details", {})),
                    ),
                )

                # Sync Ollama models if provided (Phase 70: Node Model Discovery)
                models_synced = 0
                ollama_models_payload = None

                # Support both flat (ollama_models) and nested (ollama.available_models) formats
                if data.get("ollama_models") and data.get("ollama_online"):
                    ollama_models_payload = data["ollama_models"]
                elif "ollama" in data:
                    ollama_data = data["ollama"]
                    available = ollama_data.get("available_models", [])
                    if available:
                        ollama_models_payload = available

                if ollama_models_payload:
                    try:
                        cur.execute("SAVEPOINT model_sync")
                        cur.execute(
                            """
                            SELECT sync_node_models(%s, %s::jsonb)
                        """,
                            (node_id, psycopg2.extras.Json(ollama_models_payload)),
                        )
                        result = cur.fetchone()
                        models_synced = result[0] if result else 0
                        logger.debug(f"Synced {models_synced} models for node {node_id}")

                        # Mark models no longer available
                        if ollama_models_payload:
                            available_names = [
                                m.get("name", m.get("model", "")) for m in ollama_models_payload if isinstance(m, dict)
                            ]
                            if available_names:
                                cur.execute(
                                    """
                                    UPDATE node_ollama_models SET is_available = false
                                    WHERE node_id = %s AND model_name != ALL(%s::text[])
                                """,
                                    (node_id, available_names),
                                )
                        cur.execute("RELEASE SAVEPOINT model_sync")
                    except Exception as e:
                        logger.warning(f"Model sync error for {node_id}: {e}")
                        cur.execute("ROLLBACK TO SAVEPOINT model_sync")

                # Store idle agents in node metadata (for mesh dispatcher)
                idle_agents = data.get("idle_agents")
                if idle_agents is not None:
                    try:
                        cur.execute(
                            """
                            UPDATE remote_nodes
                            SET metadata = COALESCE(metadata, '{}'::jsonb)
                                || jsonb_build_object('idle_agents', %s::jsonb)
                            WHERE node_id = %s
                            """,
                            (json.dumps(idle_agents), node_id),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store idle_agents for {node_id}: {e}")

                # Process completed jobs from node (Fleet Coordination)
                completed_jobs = data.get("completed_jobs", [])
                for job in completed_jobs:
                    try:
                        cur.execute(
                            """
                            INSERT INTO task_execution_log
                                (agent_name, station_code, capability,
                                 module_source, success, duration_ms, created_at)
                            VALUES (%s, %s, %s, 'remote', %s, %s, NOW())
                        """,
                            (
                                job.get("agent_name"),
                                job.get("station_code", "UNKNOWN"),
                                job.get("capability"),
                                job.get("success", False),
                                job.get("duration_ms", 0),
                            ),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log completed job: {e}")

                # Update fleet agent cache with node welfare data
                agent_welfare = data.get("agent_welfare", {})
                if agent_welfare:
                    try:
                        from ai_bridge.bridge_dispatcher import get_dispatcher

                        dispatcher = get_dispatcher()
                        for agent_name, welfare in agent_welfare.items():
                            cache_key = f"fleet:{node_id}:{agent_name}"
                            if cache_key in dispatcher._agent_cache:
                                dispatcher._agent_cache[cache_key].update(
                                    {
                                        "stress": welfare.get("stress", 0.0),
                                        "energy": welfare.get("energy", 1.0),
                                        "shift_state": welfare.get("shift_state", "active"),
                                        "task_count": welfare.get("task_count", 0),
                                        "model_loaded": welfare.get("model_loaded", False),
                                    }
                                )
                    except Exception as e:
                        logger.warning(f"Failed to update fleet welfare cache: {e}")

                # Check if update was requested for this node
                cur.execute(
                    "SELECT update_requested FROM remote_nodes WHERE id = %s",
                    (node["id"],),
                )
                update_row = cur.fetchone()
                update_requested = update_row["update_requested"] if update_row else False

                response = {
                    "success": True,
                    "status": status,
                    "message": "Heartbeat received",
                    "models_synced": models_synced,
                }

                if update_requested:
                    response["update_available"] = True
                    response["update_url"] = f"/tools/starship/download/node-package"
                    response["latest_version"] = LATEST_CLIENT_VERSION
                    # Clear the flag so we only signal once
                    cur.execute(
                        "UPDATE remote_nodes SET update_requested = false WHERE id = %s",
                        (node["id"],),
                    )

                return jsonify(response)

        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>")
    @login_required
    def get_node_detail(node_id):
        """Get detailed info about a specific node"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT * FROM remote_nodes WHERE node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get capabilities
                cur.execute(
                    """
                    SELECT provider, model_name, is_available, avg_tokens_per_sec,
                           max_context_length, priority
                    FROM node_capabilities
                    WHERE node_id = %s
                    ORDER BY provider, model_name
                """,
                    (node["id"],),
                )
                capabilities = cur.fetchall()

                # Get recent heartbeats
                cur.execute(
                    """
                    SELECT status, latency_ms, cpu_usage, memory_usage, gpu_usage,
                           current_load, created_at
                    FROM node_heartbeats
                    WHERE node_id = %s
                    ORDER BY created_at DESC
                    LIMIT 50
                """,
                    (node["id"],),
                )
                heartbeats = cur.fetchall()

                # Convert datetime
                for key in ["last_heartbeat", "created_at", "updated_at"]:
                    if node.get(key):
                        node[key] = node[key].isoformat()

                for hb in heartbeats:
                    if hb.get("created_at"):
                        hb["created_at"] = hb["created_at"].isoformat()

                # Remove sensitive data
                node.pop("api_key_hash", None)

                return jsonify(
                    {
                        "success": True,
                        "node": node,
                        "capabilities": capabilities,
                        "heartbeats": heartbeats,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>", methods=["PUT"])
    @login_required
    def update_node(node_id):
        """Update a remote node configuration"""
        data = request.get_json() or {}

        allowed_fields = [
            "node_name",
            "description",
            "vpn_ip",
            "hostname",
            "port",
            "priority",
            "weight",
            "max_concurrent",
            "tags",
            "is_active",
            "min_required_version",
        ]
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            return jsonify({"success": False, "error": "No valid fields to update"}), 400

        try:
            with get_db_cursor() as (conn, cur):

                set_clauses = [f"{k} = %s" for k in updates.keys()]
                values = list(updates.values())
                values.append(node_id)

                cur.execute(
                    f"""
                    UPDATE remote_nodes
                    SET {', '.join(set_clauses)}
                    WHERE node_id = %s
                    RETURNING id, node_id, node_name
                """,
                    values,
                )

                updated = cur.fetchone()

                if not updated:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                return jsonify({"success": True, "node": updated})

        except Exception as e:
            logger.error(f"Error updating node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>", methods=["DELETE"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def delete_node(node_id):
        """Delete a remote node"""
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):

                cur.execute(
                    """
                    DELETE FROM remote_nodes WHERE node_id = %s RETURNING id
                """,
                    (node_id,),
                )

                deleted = cur.fetchone()

                if not deleted:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                return jsonify({"success": True, "message": f"Node {node_id} deleted"})

        except Exception as e:
            logger.error(f"Error deleting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/capabilities", methods=["POST"])
    def update_node_capabilities(node_id):
        """Update capabilities for a node (called by node client)"""
        data = request.get_json() or {}
        api_key = request.headers.get("X-Node-API-Key")
        capabilities = data.get("capabilities", [])

        if not api_key:
            return jsonify({"success": False, "error": "API key required"}), 401

        try:
            with get_db_cursor() as (conn, cur):

                # Verify node
                cur.execute(
                    """
                    SELECT id, api_key_hash FROM remote_nodes
                    WHERE node_id = %s AND is_active = TRUE
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node or not verify_api_key(api_key, node["api_key_hash"]):
                    return jsonify({"success": False, "error": "Unauthorized"}), 401

                # Clear old capabilities and insert new
                cur.execute("DELETE FROM node_capabilities WHERE node_id = %s", (node["id"],))

                for cap in capabilities:
                    cur.execute(
                        """
                        INSERT INTO node_capabilities (
                            node_id, provider, model_name, is_available,
                            avg_tokens_per_sec, max_context_length, priority
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            node["id"],
                            cap.get("provider", "ollama"),
                            cap.get("model_name"),
                            cap.get("is_available", True),
                            cap.get("avg_tokens_per_sec"),
                            cap.get("max_context_length"),
                            cap.get("priority", 10),
                        ),
                    )

                return jsonify({"success": True, "message": f"Updated {len(capabilities)} capabilities"})

        except Exception as e:
            logger.error(f"Error updating capabilities: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/select", methods=["POST"])
    @login_required
    def select_node_for_request():
        """Select the best node for a request (load balancing)"""
        data = request.get_json() or {}
        model_name = data.get("model")
        provider = data.get("provider", "ollama")

        try:
            with get_db_cursor() as (conn, cur):

                # Find available nodes with the requested capability
                cur.execute(
                    """
                    SELECT
                        rn.id, rn.node_id, rn.node_name, rn.vpn_ip, rn.hostname, rn.port,
                        rn.priority, rn.weight, rn.current_load, rn.max_concurrent,
                        nc.avg_tokens_per_sec
                    FROM remote_nodes rn
                    JOIN node_capabilities nc ON rn.id = nc.node_id
                    WHERE rn.status = 'online'
                      AND rn.is_active = TRUE
                      AND rn.current_load < rn.max_concurrent
                      AND nc.provider = %s
                      AND nc.model_name = %s
                      AND nc.is_available = TRUE
                    ORDER BY
                        rn.priority ASC,
                        (rn.current_load::float / NULLIF(rn.max_concurrent, 0)) ASC,
                        rn.weight DESC
                    LIMIT 1
                """,
                    (provider, model_name),
                )

                node = cur.fetchone()

                if not node:
                    # Fallback: return local if no remote nodes available
                    return jsonify(
                        {
                            "success": True,
                            "node": None,
                            "use_local": True,
                            "message": "No remote nodes available, use local",
                        }
                    )

                # Increment load counter
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET current_load = current_load + 1
                    WHERE id = %s
                """,
                    (node["id"],),
                )

                return jsonify(
                    {
                        "success": True,
                        "node": {
                            "node_id": node["node_id"],
                            "name": node["node_name"],
                            "host": node["vpn_ip"] or node["hostname"],
                            "port": node["port"],
                        },
                        "use_local": False,
                    }
                )

        except Exception as e:
            logger.error(f"Error selecting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/request-complete", methods=["POST"])
    def node_request_complete(node_id):
        """Mark a request as complete (decrement load)"""
        data = request.get_json() or {}

        try:
            with get_db_cursor() as (conn, cur):

                # Get node
                cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Decrement load and update stats
                success = data.get("success", True)
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET current_load = GREATEST(0, current_load - 1),
                        total_requests = total_requests + 1,
                        successful_requests = successful_requests + %s,
                        failed_requests = failed_requests + %s
                    WHERE id = %s
                """,
                    (1 if success else 0, 0 if success else 1, node["id"]),
                )

                # Log request
                cur.execute(
                    """
                    INSERT INTO node_requests (
                        node_id, request_type, model_name, tokens_in, tokens_out,
                        latency_ms, status, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        node["id"],
                        data.get("request_type", "completion"),
                        data.get("model"),
                        data.get("tokens_in"),
                        data.get("tokens_out"),
                        data.get("latency_ms"),
                        "success" if success else "failed",
                        data.get("error"),
                    ),
                )

                return jsonify({"success": True})

        except Exception as e:
            logger.error(f"Error completing request: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/stats")
    @login_required
    def get_node_stats():
        """Get aggregate stats across all nodes"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Overall stats
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_nodes,
                        COUNT(*) FILTER (WHERE status = 'online') as online_nodes,
                        SUM(current_load) as total_current_load,
                        SUM(max_concurrent) as total_capacity,
                        SUM(total_requests) as total_requests,
                        SUM(successful_requests) as successful_requests,
                        AVG(avg_latency_ms) as avg_latency
                    FROM remote_nodes
                    WHERE is_active = TRUE
                """
                )
                overall = cur.fetchone()

                # By provider
                cur.execute(
                    """
                    SELECT
                        nc.provider,
                        COUNT(DISTINCT nc.node_id) as node_count,
                        COUNT(*) as model_count,
                        COUNT(*) FILTER (WHERE nc.is_available) as available_models
                    FROM node_capabilities nc
                    JOIN remote_nodes rn ON nc.node_id = rn.id
                    WHERE rn.is_active = TRUE
                    GROUP BY nc.provider
                """
                )
                by_provider = cur.fetchall()

                # Recent requests (last hour)
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'success') as successful,
                        AVG(latency_ms) as avg_latency
                    FROM node_requests
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """
                )
                recent = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "overall": overall,
                        "by_provider": by_provider,
                        "recent_hour": recent,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # NODE APPROVAL & MANAGEMENT - Phase 29+ Enhancement
    # ============================================================================

    @bp.route("/api/nodes/<node_id>/status", methods=["GET"])
    def get_node_status(node_id):
        """Get node approval status (for polling during install)"""
        api_key = request.headers.get("X-Node-API-Key")

        if not api_key:
            return jsonify({"error": "API key required"}), 401

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Verify API key matches node
                cur.execute(
                    """
                    SELECT node_id, node_name, approval_status, status
                    FROM remote_nodes
                    WHERE node_id = %s AND api_key_hash = %s
                """,
                    (node_id, hash_api_key(api_key)),
                )

                node = cur.fetchone()

                if not node:
                    return jsonify({"error": "Invalid node or API key"}), 401

                return jsonify(
                    {
                        "node_id": node["node_id"],
                        "node_name": node["node_name"],
                        "approval_status": node["approval_status"],
                        "status": node["status"],
                    }
                )

        except Exception as e:
            logger.error(f"Error getting node status: {e}")
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/approve", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def approve_node(node_id):
        """Approve a pending node registration"""
        try:
            with get_db_cursor() as (conn, cur):

                # Get current user ID from Flask-Login session
                user_id = current_user.id if current_user.is_authenticated else None

                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET approval_status = 'approved',
                        approved_by = %s,
                        approved_at = NOW()
                    WHERE node_id = %s AND approval_status = 'pending'
                    RETURNING node_id, node_name, approval_status
                """,
                    (user_id, node_id),
                )

                node = cur.fetchone()

                if not node:
                    return (
                        jsonify({"success": False, "error": "Node not found or already processed"}),
                        404,
                    )

                return jsonify(
                    {
                        "success": True,
                        "node_id": node["node_id"],
                        "node_name": node["node_name"],
                        "approval_status": node["approval_status"],
                        "message": f"Node '{node['node_name']}' approved successfully",
                    }
                )

        except Exception as e:
            logger.error(f"Error approving node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/reject", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def reject_node(node_id):
        """Reject a pending node registration"""
        data = request.get_json() or {}
        reason = data.get("reason", "No reason provided")

        try:
            with get_db_cursor() as (conn, cur):

                # Get current user ID from Flask-Login session
                user_id = current_user.id if current_user.is_authenticated else None

                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET approval_status = 'rejected',
                        approved_by = %s,
                        approved_at = NOW(),
                        last_error = %s,
                        is_active = FALSE
                    WHERE node_id = %s AND approval_status = 'pending'
                    RETURNING node_id, node_name, approval_status
                """,
                    (user_id, f"Rejected: {reason}", node_id),
                )

                node = cur.fetchone()

                if not node:
                    return (
                        jsonify({"success": False, "error": "Node not found or already processed"}),
                        404,
                    )

                return jsonify(
                    {
                        "success": True,
                        "node_id": node["node_id"],
                        "node_name": node["node_name"],
                        "approval_status": node["approval_status"],
                        "message": f"Node '{node['node_name']}' rejected",
                    }
                )

        except Exception as e:
            logger.error(f"Error rejecting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/test", methods=["POST"])
    @login_required
    def test_node_connection(node_id):
        """Test connectivity to a remote node's Ollama instance"""
        import time

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT node_id, node_name, vpn_ip, hostname, port
                    FROM remote_nodes
                    WHERE node_id = %s AND is_active = TRUE
                """,
                    (node_id,),
                )

                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Build endpoint URL
                host = node["vpn_ip"] or node["hostname"]
                port = node["port"] or DEFAULT_NODE_PORT
                url = f"http://{host}:{port}/api/tags"

                # Test connection with timing
                start_time = time.time()
                try:
                    import requests as req

                    resp = req.get(url, timeout=10)
                    latency_ms = int((time.time() - start_time) * 1000)

                    if resp.status_code == 200:
                        models = resp.json().get("models", [])
                        return jsonify(
                            {
                                "success": True,
                                "node_id": node_id,
                                "node_name": node["node_name"],
                                "reachable": True,
                                "latency_ms": latency_ms,
                                "ollama_status": "online",
                                "models_count": len(models),
                                "models": [m.get("name") for m in models[:10]],  # First 10 models
                            }
                        )
                    else:
                        return jsonify(
                            {
                                "success": True,
                                "node_id": node_id,
                                "reachable": True,
                                "latency_ms": latency_ms,
                                "ollama_status": "error",
                                "error": f"Ollama returned status {resp.status_code}",
                            }
                        )
                except req.exceptions.Timeout:
                    return jsonify(
                        {
                            "success": True,
                            "node_id": node_id,
                            "reachable": False,
                            "latency_ms": 10000,
                            "error": "Connection timed out",
                        }
                    )
                except req.exceptions.ConnectionError as e:
                    logger.error(f"Node connection failed: {e}")
                    return jsonify(
                        {
                            "success": True,
                            "node_id": node_id,
                            "reachable": False,
                            "latency_ms": None,
                            "error": "Connection failed",
                        }
                    )

        except Exception as e:
            logger.error(f"Error testing node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/health-history", methods=["GET"])
    @login_required
    def get_node_health_history(node_id):
        """Get health history for a node (for charts)"""
        hours = request.args.get("hours", 24, type=int)

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get node internal ID
                cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get heartbeat history
                cur.execute(
                    """
                    SELECT
                        DATE_TRUNC('hour', created_at) as hour,
                        AVG(cpu_usage) as avg_cpu,
                        AVG(memory_usage) as avg_memory,
                        AVG(gpu_usage) as avg_gpu,
                        AVG(latency_ms) as avg_latency,
                        COUNT(*) as heartbeat_count,
                        COUNT(*) FILTER (WHERE status = 'online') as online_count
                    FROM node_heartbeats
                    WHERE node_id = %s
                      AND created_at > NOW() - (%s * INTERVAL '1 hour')
                    GROUP BY DATE_TRUNC('hour', created_at)
                    ORDER BY hour
                """,
                    (node["id"], int(hours)),
                )

                history = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "node_id": node_id,
                        "hours": hours,
                        "data_points": len(history),
                        "history": history,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting health history: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/health")
    @login_required
    def get_node_health(node_id):
        """Get latest heartbeat health data for a specific node."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT rn.status, rn.last_heartbeat, rn.current_load, rn.max_concurrent,
                           rn.cpu_cores, rn.ram_gb, rn.gpu_model, rn.gpu_vram_gb,
                           rn.deployment_mode, rn.bridge_priority
                    FROM remote_nodes rn
                    WHERE rn.node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            # Convert datetime for JSON serialization
            health = dict(node)
            if health.get("last_heartbeat"):
                health["last_heartbeat"] = health["last_heartbeat"].isoformat()

            return jsonify({"success": True, "node_id": node_id, "health": health})

        except Exception as e:
            logger.error(f"Error getting node health: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/dispatch-test", methods=["POST"])
    @login_required
    def dispatch_test_to_node(node_id):
        """Send a connectivity test to a specific node's Ollama."""
        import time as _time

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT vpn_ip, hostname, port FROM remote_nodes
                    WHERE node_id = %s AND is_active = true
                """,
                    (node_id,),
                )
                node = cur.fetchone()

            if not node:
                return jsonify({"success": False, "error": "Node not found or inactive"}), 404

            host = node["vpn_ip"] or node["hostname"]
            port = node["port"] or DEFAULT_NODE_PORT
            ollama_url = f"http://{host}:{port}"
            start = _time.time()
            resp = requests.get(f"{ollama_url}/api/tags", timeout=10)
            latency_ms = round((_time.time() - start) * 1000)
            data = resp.json()
            model_count = len(data.get("models", []))

            return jsonify(
                {
                    "success": True,
                    "node_id": node_id,
                    "latency_ms": latency_ms,
                    "model_count": model_count,
                    "ollama_url": ollama_url,
                }
            )

        except requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "Connection timed out"}), 504
        except requests.exceptions.ConnectionError:
            return jsonify({"success": False, "error": "Connection refused"}), 502
        except Exception as e:
            logger.error(f"Error dispatch-testing node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # NODE STATION ASSIGNMENTS - Phase 31
    # ============================================================================

    @bp.route("/api/nodes/<node_id>/stations", methods=["GET"])
    @login_required
    def get_node_stations(node_id):
        """Get all station assignments for a node"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get node internal ID
                cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get station assignments with station details
                cur.execute(
                    """
                    SELECT
                        nsa.id AS assignment_id,
                        nsa.station_id,
                        bs.station_code,
                        bs.station_name,
                        bs.color AS station_color,
                        nsa.role,
                        nsa.priority,
                        nsa.shift_preference,
                        nsa.max_concurrent,
                        nsa.is_active,
                        nsa.assigned_at,
                        nsa.notes
                    FROM node_station_assignments nsa
                    JOIN bridge_stations bs ON nsa.station_id = bs.id
                    WHERE nsa.node_id = %s
                    ORDER BY nsa.priority ASC, bs.station_name ASC
                """,
                    (node["id"],),
                )

                assignments = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "node_id": node_id,
                        "node_name": node["node_name"],
                        "assignment_count": len(assignments),
                        "assignments": assignments,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting node stations: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/stations", methods=["POST"])
    @login_required
    def assign_node_to_station(node_id):
        """Assign a node to a station"""
        data = request.get_json() or {}

        if not data.get("station_id"):
            return jsonify({"success": False, "error": "station_id is required"}), 400

        try:
            with get_db_cursor() as (conn, cur):

                # Get node internal ID
                cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Verify station exists
                cur.execute(
                    "SELECT id, station_name FROM bridge_stations WHERE id = %s",
                    (data["station_id"],),
                )
                station = cur.fetchone()

                if not station:
                    return jsonify({"success": False, "error": "Station not found"}), 404

                # Check if assignment already exists
                cur.execute(
                    """
                    SELECT id FROM node_station_assignments
                    WHERE node_id = %s AND station_id = %s
                """,
                    (node["id"], data["station_id"]),
                )

                if cur.fetchone():
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Node is already assigned to this station",
                            }
                        ),
                        400,
                    )

                # Create assignment
                cur.execute(
                    """
                    INSERT INTO node_station_assignments (
                        node_id, station_id, role, priority, shift_preference,
                        max_concurrent, notes, assigned_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, role, priority, assigned_at
                """,
                    (
                        node["id"],
                        data["station_id"],
                        data.get("role", "worker"),
                        data.get("priority", 10),
                        data.get("shift_preference", "any"),
                        data.get("max_concurrent", 5),
                        data.get("notes"),
                        current_user.id if current_user.is_authenticated else None,
                    ),
                )

                assignment = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "message": f"Node '{node['node_name']}' assigned to station '{station['station_name']}'",
                        "assignment": {
                            "id": assignment["id"],
                            "node_id": node_id,
                            "node_name": node["node_name"],
                            "station_id": data["station_id"],
                            "station_name": station["station_name"],
                            "role": assignment["role"],
                            "priority": assignment["priority"],
                            "assigned_at": (
                                assignment["assigned_at"].isoformat() if assignment["assigned_at"] else None
                            ),
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error assigning node to station: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["PUT"])
    @login_required
    def update_node_station_assignment(node_id, station_id):
        """Update a node's station assignment (role, priority, etc.)"""
        data = request.get_json() or {}

        try:
            with get_db_cursor() as (conn, cur):

                # Get node internal ID
                cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Check if assignment exists
                cur.execute(
                    """
                    SELECT nsa.id, bs.station_name
                    FROM node_station_assignments nsa
                    JOIN bridge_stations bs ON nsa.station_id = bs.id
                    WHERE nsa.node_id = %s AND nsa.station_id = %s
                """,
                    (node["id"], station_id),
                )
                assignment = cur.fetchone()

                if not assignment:
                    return jsonify({"success": False, "error": "Assignment not found"}), 404

                # Build update query dynamically
                update_fields = []
                update_values = []

                if "role" in data:
                    if data["role"] not in ["primary", "backup", "relief", "worker"]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "Invalid role. Must be: primary, backup, relief, or worker",
                                }
                            ),
                            400,
                        )
                    update_fields.append("role = %s")
                    update_values.append(data["role"])

                if "priority" in data:
                    update_fields.append("priority = %s")
                    update_values.append(data["priority"])

                if "shift_preference" in data:
                    if data["shift_preference"] not in ["alpha", "beta", "gamma", "any"]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "Invalid shift_preference. Must be: alpha, beta, gamma, or any",
                                }
                            ),
                            400,
                        )
                    update_fields.append("shift_preference = %s")
                    update_values.append(data["shift_preference"])

                if "max_concurrent" in data:
                    update_fields.append("max_concurrent = %s")
                    update_values.append(data["max_concurrent"])

                if "is_active" in data:
                    update_fields.append("is_active = %s")
                    update_values.append(data["is_active"])

                if "notes" in data:
                    update_fields.append("notes = %s")
                    update_values.append(data["notes"])

                if not update_fields:
                    return jsonify({"success": False, "error": "No fields to update"}), 400

                # Execute update
                update_values.append(assignment["id"])
                cur.execute(
                    f"""
                    UPDATE node_station_assignments
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                    RETURNING id, role, priority, shift_preference, max_concurrent, is_active
                """,
                    tuple(update_values),
                )

                updated = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "message": (
                            f"Assignment updated for node '{node['node_name']}' "
                            f"at station '{assignment['station_name']}'"
                        ),
                        "assignment": {
                            "node_id": node_id,
                            "station_id": station_id,
                            "station_name": assignment["station_name"],
                            **updated,
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error updating station assignment: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["DELETE"])
    @login_required
    def remove_node_from_station(node_id, station_id):
        """Remove a node from a station"""
        try:
            with get_db_cursor() as (conn, cur):

                # Get node internal ID
                cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get station name for response
                cur.execute("SELECT station_name FROM bridge_stations WHERE id = %s", (station_id,))
                station = cur.fetchone()

                # Delete assignment
                cur.execute(
                    """
                    DELETE FROM node_station_assignments
                    WHERE node_id = %s AND station_id = %s
                    RETURNING id
                """,
                    (node["id"], station_id),
                )

                deleted = cur.fetchone()

                if not deleted:
                    return jsonify({"success": False, "error": "Assignment not found"}), 404

                return jsonify(
                    {
                        "success": True,
                        "message": (
                            f"Node '{node['node_name']}' removed from station "
                            f"'{station['station_name'] if station else station_id}'"
                        ),
                    }
                )

        except Exception as e:
            logger.error(f"Error removing node from station: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<int:station_id>/nodes", methods=["GET"])
    @login_required
    def get_station_nodes(station_id):
        """Get all nodes assigned to a station"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Verify station exists
                cur.execute(
                    "SELECT id, station_code, station_name, color FROM bridge_stations WHERE id = %s",
                    (station_id,),
                )
                station = cur.fetchone()

                if not station:
                    return jsonify({"success": False, "error": "Station not found"}), 404

                # Get assigned nodes with details
                cur.execute(
                    """
                    SELECT
                        rn.node_id,
                        rn.node_name,
                        rn.status,
                        rn.hostname,
                        rn.cpu_cores,
                        rn.ram_gb,
                        rn.gpu_model,
                        rn.ollama_available,
                        rn.docker_available,
                        rn.current_load,
                        rn.max_concurrent,
                        nsa.role,
                        nsa.priority,
                        nsa.shift_preference,
                        nsa.is_active AS assignment_active,
                        nsa.assigned_at
                    FROM node_station_assignments nsa
                    JOIN remote_nodes rn ON nsa.node_id = rn.id
                    WHERE nsa.station_id = %s
                    ORDER BY
                        CASE nsa.role
                            WHEN 'primary' THEN 1
                            WHEN 'backup' THEN 2
                            WHEN 'relief' THEN 3
                            ELSE 4
                        END,
                        nsa.priority ASC
                """,
                    (station_id,),
                )

                nodes = cur.fetchall()

                # Categorize by role
                by_role = {
                    "primary": [n for n in nodes if n["role"] == "primary"],
                    "backup": [n for n in nodes if n["role"] == "backup"],
                    "relief": [n for n in nodes if n["role"] == "relief"],
                    "worker": [n for n in nodes if n["role"] == "worker"],
                }

                return jsonify(
                    {
                        "success": True,
                        "station": station,
                        "node_count": len(nodes),
                        "by_role": {
                            "primary": len(by_role["primary"]),
                            "backup": len(by_role["backup"]),
                            "relief": len(by_role["relief"]),
                            "worker": len(by_role["worker"]),
                        },
                        "nodes": nodes,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting station nodes: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/batch-nodes", methods=["POST"])
    @login_required
    def get_batch_station_nodes():
        """Get nodes for multiple stations in one query"""
        data = request.get_json() or {}
        station_ids = data.get("station_ids", [])
        if not station_ids:
            return jsonify({"success": True, "stations": {}})

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        nsa.station_id,
                        rn.node_id, rn.node_name, rn.status, rn.hostname,
                        rn.cpu_cores, rn.ram_gb, rn.gpu_model,
                        rn.ollama_available, rn.docker_available,
                        rn.current_load, rn.max_concurrent,
                        nsa.role, nsa.priority, nsa.shift_preference,
                        nsa.is_active AS assignment_active, nsa.assigned_at
                    FROM node_station_assignments nsa
                    JOIN remote_nodes rn ON nsa.node_id = rn.id
                    WHERE nsa.station_id = ANY(%s)
                    ORDER BY nsa.station_id,
                        CASE nsa.role
                            WHEN 'primary' THEN 1 WHEN 'backup' THEN 2
                            WHEN 'relief' THEN 3 ELSE 4
                        END, nsa.priority ASC
                """,
                    (station_ids,),
                )

                nodes = cur.fetchall()

                # Group by station_id
                by_station = {}
                for n in nodes:
                    sid = str(n["station_id"])
                    if sid not in by_station:
                        by_station[sid] = []
                    by_station[sid].append(n)

                return jsonify({"success": True, "stations": by_station})
        except Exception as e:
            logger.error(f"Error batch fetching nodes: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/coverage", methods=["GET"])
    @login_required
    def get_all_station_coverage():
        """Get node coverage summary for all stations"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT * FROM v_station_node_coverage
                """
                )

                coverage = cur.fetchall()

                # Calculate summary
                total_assignments = sum(c["total_nodes"] for c in coverage)
                stations_with_nodes = len([c for c in coverage if c["total_nodes"] > 0])
                stations_without_primary = len([c for c in coverage if c["primary_nodes"] == 0])

                return jsonify(
                    {
                        "success": True,
                        "summary": {
                            "total_stations": len(coverage),
                            "stations_with_nodes": stations_with_nodes,
                            "stations_without_primary": stations_without_primary,
                            "total_assignments": total_assignments,
                        },
                        "coverage": coverage,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting station coverage: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/select-for-station", methods=["POST"])
    @login_required
    def select_node_for_station_api():
        """Select the best available node for a station task"""
        data = request.get_json() or {}

        if not data.get("station_id"):
            return jsonify({"success": False, "error": "station_id is required"}), 400

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                urgency = data.get("urgency", "normal")

                cur.execute(
                    """
                    SELECT * FROM select_node_for_station(%s, %s)
                """,
                    (data["station_id"], urgency),
                )

                nodes = cur.fetchall()

                if not nodes:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "No available nodes for this station",
                                "suggestion": "Assign nodes to this station or ensure assigned nodes are online",
                            }
                        ),
                        404,
                    )

                # Return best node (first in sorted list)
                best_node = nodes[0]

                return jsonify(
                    {
                        "success": True,
                        "selected_node": best_node,
                        "alternatives": nodes[1:] if len(nodes) > 1 else [],
                        "selection_criteria": {
                            "urgency": urgency,
                            "station_id": data["station_id"],
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error selecting node for station: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500
