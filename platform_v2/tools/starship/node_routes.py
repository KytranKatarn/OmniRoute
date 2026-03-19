"""
Starship Command — Node routes.

Node status, settings, setup/onboarding, station commands.
Extracted from routes.py for maintainability.
"""

import json
import logging
import os
import secrets

from flask import jsonify, request, send_file, Response
from flask_login import current_user
from database import get_db_cursor

from .helpers import (
    _get_node_for_user,
    _get_node_for_user_by_int_id,
    _get_user_nodes,
    _compute_node_status,
    HEARTBEAT_TIMEOUT_SECONDS,
    LATEST_NODE_VERSION,
)

logger = logging.getLogger(__name__)

# Path to node client distribution package
NODE_CLIENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "node_client",
)


def register_node_routes(bp, auth_decorator):
    """Register node-related routes on the starship blueprint."""

    # ========================================================================
    # NODE STATUS / SETTINGS / CATALOG
    # ========================================================================

    @bp.route("/api/nodes/<node_id>/status")
    @auth_decorator
    def api_node_status(node_id):
        """Get detailed status for a specific node including version, stations, agents."""
        user_id = current_user.id
        try:
            node = _get_node_for_user(node_id, user_id)
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            with get_db_cursor() as (conn, cur):
                # Models with full metadata
                cur.execute(
                    """
                    SELECT model_name, model_size_gb, is_available,
                           context_length, quantization, model_family,
                           parameter_size, capabilities,
                           total_requests, avg_response_ms
                    FROM node_ollama_models
                    WHERE node_id = %s
                    ORDER BY is_available DESC, model_name
                    """,
                    (node["node_id"],),
                )
                models = cur.fetchall()

                # Job stats (bridge_jobs doesn't track per-node yet)
                stats = {"total_jobs": 0, "completed_jobs": 0, "failed_jobs": 0}

                # Latest heartbeat metrics
                cur.execute(
                    """
                    SELECT cpu_usage, memory_usage, gpu_usage, current_load
                    FROM node_heartbeats
                    WHERE node_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (node.get("id") or 0,),
                )
                latest_hb = cur.fetchone()

                # All stations with agent counts (real agents from node_agents table)
                cur.execute(
                    """
                    SELECT bs.id, bs.station_code, bs.station_name, bs.color, bs.icon,
                           bs.default_llm,
                           CASE WHEN nsa.id IS NOT NULL THEN true ELSE false END as assigned,
                           nsa.is_active as station_active,
                           (SELECT COUNT(*) FROM node_agents na
                            WHERE na.node_id = %s AND na.status = 'active'
                            AND bs.station_code = ANY(na.station_codes)) as agent_count
                    FROM bridge_stations bs
                    LEFT JOIN node_station_assignments nsa
                        ON nsa.station_id = bs.id AND nsa.node_id = %s
                    WHERE bs.is_active = true
                    ORDER BY bs.position_row, bs.position_order
                    """,
                    (node.get("id") or 0, node.get("id") or 0),
                )
                stations = cur.fetchall()

                # Build station color lookup
                station_color_map = {}
                for s in stations:
                    station_color_map[s["station_code"]] = s["color"]

                # Node-specific agents from node_agents table
                cur.execute(
                    """
                    SELECT na.id, na.name, na.display_name, na.first_name,
                           na.last_name, na.model, na.status, na.title,
                           na.station_codes, na.is_allowed
                    FROM node_agents na
                    WHERE na.node_id = %s AND na.status = 'active'
                    ORDER BY na.display_name
                    """,
                    (node.get("id") or 0,),
                )
                agents_raw = cur.fetchall()

                # Attach station colors from the lookup
                agents = []
                for a in agents_raw:
                    codes = a["station_codes"] or []
                    colors = [station_color_map.get(c, "#666") for c in codes]
                    agents.append(
                        {
                            "id": a["id"],
                            "name": a["name"],
                            "display_name": a["display_name"],
                            "model": a["model"],
                            "status": a["status"],
                            "title": a["title"],
                            "station_codes": codes,
                            "station_colors": colors,
                            "allowed": a["is_allowed"],
                        }
                    )

            # Version check
            client_ver = node.get("client_version", "1.0.0") or "1.0.0"
            update_available = client_ver < LATEST_NODE_VERSION

            # If node is offline, zero out live metrics
            computed_status = _compute_node_status(node)
            if computed_status == "offline":
                latest_hb = None

            # Compute model totals
            total_model_size = sum(float(m["model_size_gb"]) for m in models if m["model_size_gb"])
            available_count = sum(1 for m in models if m["is_available"])
            assigned_stations = sum(1 for s in stations if s["assigned"])
            active_stations = sum(1 for s in stations if s["assigned"] and s["station_active"])

            return jsonify(
                {
                    "success": True,
                    "agent_count": len(agents),
                    "node": {
                        "db_id": node.get("id") or 0,
                        "node_id": node["node_id"],
                        "node_name": node["node_name"],
                        "status": _compute_node_status(node),
                        "deployment_mode": node["deployment_mode"],
                        "bridge_priority": node["bridge_priority"],
                        "last_heartbeat": node["last_heartbeat"].isoformat() if node["last_heartbeat"] else None,
                        "privacy_settings": node.get("privacy_settings", {}),
                        "client_version": client_ver,
                    },
                    "version": {
                        "current": client_ver,
                        "latest": LATEST_NODE_VERSION,
                        "update_available": update_available,
                    },
                    "hardware": {
                        "cpu_model": node["cpu_model"],
                        "cpu_cores": node["cpu_cores"],
                        "ram_gb": float(node["ram_gb"]) if node["ram_gb"] else None,
                        "gpu_model": node["gpu_model"],
                        "gpu_vram_gb": float(node["gpu_vram_gb"]) if node["gpu_vram_gb"] else None,
                        "disk_gb": float(node["disk_gb"]) if node["disk_gb"] else None,
                    },
                    "live_metrics": {
                        "cpu_usage": float(latest_hb["cpu_usage"]) if latest_hb and latest_hb["cpu_usage"] else 0,
                        "memory_usage": (
                            float(latest_hb["memory_usage"]) if latest_hb and latest_hb["memory_usage"] else 0
                        ),
                        "gpu_usage": float(latest_hb["gpu_usage"]) if latest_hb and latest_hb["gpu_usage"] else 0,
                        "current_load": (
                            float(latest_hb["current_load"]) if latest_hb and latest_hb["current_load"] else 0
                        ),
                    },
                    "models": [
                        {
                            "model_name": m["model_name"],
                            "model_size_gb": float(m["model_size_gb"]) if m["model_size_gb"] else None,
                            "is_available": m["is_available"],
                            "context_length": m["context_length"],
                            "quantization": m["quantization"],
                            "model_family": m["model_family"],
                            "parameter_size": m["parameter_size"],
                            "capabilities": m["capabilities"] or [],
                            "total_requests": m["total_requests"] or 0,
                            "avg_response_ms": m["avg_response_ms"],
                        }
                        for m in models
                    ],
                    "model_summary": {
                        "total": len(models),
                        "available": available_count,
                        "total_size_gb": round(total_model_size, 1),
                    },
                    "stations": [
                        {
                            "id": s["id"],
                            "station_code": s["station_code"],
                            "station_name": s["station_name"],
                            "color": s["color"],
                            "icon": s["icon"],
                            "default_llm": s["default_llm"],
                            "assigned": s["assigned"],
                            "active": s["station_active"] if s["station_active"] is not None else False,
                            "agent_count": s["agent_count"],
                        }
                        for s in stations
                    ],
                    "station_summary": {
                        "total": assigned_stations,
                        "active": active_stations,
                    },
                    "agents": agents,
                    "stats": {
                        "total_jobs": stats["total_jobs"],
                        "completed_jobs": stats["completed_jobs"],
                        "failed_jobs": stats["failed_jobs"],
                    },
                }
            )
        except Exception as e:
            logger.exception("Failed to get node status for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/settings", methods=["PUT"])
    @auth_decorator
    def api_update_node_settings(node_id):
        """Update node name, deployment mode, and priority (inline edit from STATUS tab)."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        data = request.get_json() or {}

        updates = []
        params = []
        if "node_name" in data:
            name = data["node_name"].strip()
            if not name or len(name) > 100:
                return jsonify({"success": False, "error": "Invalid name"}), 400
            updates.append("node_name = %s")
            params.append(name)
        if "deployment_mode" in data:
            mode = data["deployment_mode"]
            if mode not in ("starship", "satellite", "outpost"):
                return jsonify({"success": False, "error": "Invalid mode"}), 400
            updates.append("deployment_mode = %s")
            params.append(mode)
        if "bridge_priority" in data:
            try:
                prio = int(data["bridge_priority"])
                prio = max(0, min(100, prio))
            except (ValueError, TypeError):
                return jsonify({"success": False, "error": "Invalid priority"}), 400
            updates.append("bridge_priority = %s")
            params.append(prio)

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        params.append(node_id)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE remote_nodes SET " + ", ".join(updates) + " WHERE node_id = %s",
                params,
            )
        return jsonify({"success": True})

    @bp.route("/api/model-catalog")
    @auth_decorator
    def api_model_catalog():
        """Return the curated model catalog for browsing and selection."""
        category = request.args.get("category")
        with get_db_cursor() as (conn, cur):
            if category:
                cur.execute(
                    "SELECT id, name, COALESCE(description, '') as description, category, size_gb, quantization, is_active FROM model_catalog WHERE is_active = true AND category = %s ORDER BY size_gb",
                    (category,),
                )
            else:
                cur.execute(
                    "SELECT id, name, COALESCE(description, '') as description, category, size_gb, quantization, is_active FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
                )
            models = cur.fetchall()
            return jsonify({"success": True, "models": [dict(m) for m in models]})

    # ========================================================================
    # NODE SETUP / ONBOARDING
    # ========================================================================

    @bp.route("/api/request-node", methods=["POST"])
    @auth_decorator
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
                    RETURNING id, node_id, node_name
                    """,
                    (node_id, node_name, user_id, setup_token),
                )
                row = cur.fetchone()

            # Build config for the node
            hub_url = os.getenv(
                "STARSHIP_HUB_URL",
                "https://archie.kytranempowerment.com",
            )
            config = {
                "node_id": node_id,
                "node_name": node_name,
                "setup_token": setup_token,
                "starbase_url": f"http://{starbase_host}:{starbase_port}",
                "deployment_mode": "starship",
                "heartbeat_interval": 30,
                "hub_url": hub_url,
            }

            return jsonify(
                {
                    "success": True,
                    "node_id": row["node_id"],
                    "node_name": row["node_name"],
                    "db_id": row["id"],
                    "setup_token": setup_token,
                    "config": config,
                }
            )
        except Exception as e:
            logger.exception("Failed to request new node")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/setup-instructions/<node_id>")
    @auth_decorator
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

    @bp.route("/install")
    def starship_install_script():
        """Serve OS-appropriate install script authenticated by setup token."""
        token = request.args.get("token", "").strip()
        if not token:
            return Response(
                "Error: missing token parameter\n",
                mimetype="text/plain",
                status=400,
            )

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT node_id, node_name, setup_token FROM remote_nodes WHERE setup_token = %s",
                (token,),
            )
            node = cur.fetchone()
            if not node:
                return Response(
                    "Error: invalid or expired token\n",
                    mimetype="text/plain",
                    status=403,
                )

        hub_url = os.environ.get("STARSHIP_HUB_URL", "https://archie.kytranempowerment.com")
        node_id = node["node_id"]

        ua = (request.headers.get("User-Agent") or "").lower()
        is_powershell = "powershell" in ua or "windowspowershell" in ua

        if is_powershell:
            script = _generate_powershell_installer(hub_url, node_id, token)
            return Response(script, mimetype="text/plain", status=200)
        else:
            script = _generate_bash_installer(hub_url, node_id, token)
            return Response(script, mimetype="text/plain", status=200)

    @bp.route("/api/nodes/<node_id>/request-update", methods=["POST"])
    @auth_decorator
    def api_request_update(node_id):
        """Request a node to self-update on its next heartbeat."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE remote_nodes
                SET update_requested = true, update_requested_at = NOW()
                WHERE node_id = %s
                """,
                (node_id,),
            )
        return jsonify({"success": True, "message": "Update will be pushed on next heartbeat"})

    @bp.route("/download/node-package")
    @auth_decorator
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

    # ========================================================================
    # STATION COMMANDS
    # ========================================================================

    @bp.route("/api/station-commands", methods=["GET"])
    @auth_decorator
    def api_get_station_commands():
        """Get all station commands, optionally filtered by station."""
        station_code = request.args.get("station_code")

        with get_db_cursor() as (conn, cur):
            if station_code:
                cur.execute(
                    """
                    SELECT sc.*, bs.station_code
                    FROM station_commands sc
                    JOIN bridge_stations bs ON bs.id = sc.station_id
                    WHERE bs.station_code = %s AND sc.is_active = true
                    ORDER BY sc.command_name
                    """,
                    (station_code,),
                )
            else:
                cur.execute(
                    """
                    SELECT sc.*, bs.station_code
                    FROM station_commands sc
                    JOIN bridge_stations bs ON bs.id = sc.station_id
                    WHERE sc.is_active = true
                    ORDER BY bs.station_code, sc.command_name
                    """
                )
            commands = cur.fetchall()

        return jsonify({"commands": [dict(c) for c in commands]})

    @bp.route("/api/station-commands/execute", methods=["POST"])
    @auth_decorator
    def api_execute_station_command():
        """Execute a station command via Smart Relay triage flow."""
        data = request.get_json()
        command_id = data.get("command_id")
        prompt = data.get("prompt", "")

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT sc.*, bs.station_code
                FROM station_commands sc
                JOIN bridge_stations bs ON bs.id = sc.station_id
                WHERE sc.id = %s AND sc.is_active = true
                """,
                (command_id,),
            )
            command = cur.fetchone()

        if not command:
            return jsonify({"error": "Command not found"}), 404

        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()

        result = dispatcher.request_work(
            capability=command["capability"],
            prompt=prompt or command["description"],
            module_id="station_command",
        )

        return jsonify(
            {
                "command": command["command_name"],
                "station": command["station_code"],
                "result": result,
            }
        )

    # ========================================================================
    # FLEET-WIDE STATS (VRAM / RAM per node)
    # ========================================================================

    @bp.route("/api/fleet-stats")
    @auth_decorator
    def api_fleet_stats():
        """Return live VRAM/RAM usage per node for fleet overview."""
        user_id = current_user.id
        try:
            with get_db_cursor() as (conn, cur):
                # All nodes visible to this user with hardware specs
                cur.execute(
                    """
                    SELECT rn.id, rn.node_id, rn.node_name, rn.hostname, rn.port,
                           rn.status, rn.is_active, rn.last_heartbeat,
                           rn.ram_gb, rn.gpu_model, rn.gpu_vram_gb,
                           rn.cpu_model, rn.cpu_cores, rn.deployment_mode,
                           -- Latest heartbeat metrics (correlated subquery)
                           hb.cpu_usage, hb.memory_usage, hb.gpu_usage, hb.current_load,
                           -- Active agent count on this node
                           (SELECT COUNT(*) FROM node_agents na
                            WHERE na.node_id = rn.id AND na.status = 'active') AS agent_count,
                           -- Loaded model count from node_ollama_models
                           (SELECT COUNT(*) FROM node_ollama_models nom
                            WHERE nom.node_id = rn.node_id AND nom.is_available = true) AS models_loaded
                    FROM remote_nodes rn
                    LEFT JOIN LATERAL (
                        SELECT cpu_usage, memory_usage, gpu_usage, current_load
                        FROM node_heartbeats nh
                        WHERE nh.node_id = rn.id
                        ORDER BY nh.created_at DESC
                        LIMIT 1
                    ) hb ON true
                    WHERE rn.registered_by = %s OR rn.registered_by IS NULL
                    ORDER BY rn.bridge_priority DESC, rn.node_name
                    """,
                    (user_id,),
                )
                nodes_raw = cur.fetchall()

                # For VRAM used, sum model sizes from node_ollama_models
                node_vram_used = {}
                if nodes_raw:
                    node_ids = [n["node_id"] for n in nodes_raw]
                    cur.execute(
                        """
                        SELECT node_id, COALESCE(SUM(model_size_gb), 0) AS total_vram_used
                        FROM node_ollama_models
                        WHERE node_id = ANY(%s) AND is_available = true
                        GROUP BY node_id
                        """,
                        (node_ids,),
                    )
                    for row in cur.fetchall():
                        node_vram_used[row["node_id"]] = float(row["total_vram_used"])

            nodes = []
            for n in nodes_raw:
                computed_status = _compute_node_status(n)
                ram_total = float(n["ram_gb"]) if n["ram_gb"] else 0
                vram_total = float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else 0
                mem_pct = float(n["memory_usage"]) if n["memory_usage"] and computed_status != "offline" else 0
                cpu_pct = float(n["cpu_usage"]) if n["cpu_usage"] and computed_status != "offline" else 0
                gpu_pct = float(n["gpu_usage"]) if n["gpu_usage"] and computed_status != "offline" else 0

                ram_used = round(ram_total * mem_pct / 100, 1) if ram_total else 0
                vram_used = round(node_vram_used.get(n["node_id"], 0), 1)

                nodes.append(
                    {
                        "node_id": n["node_id"],
                        "node_name": n["node_name"],
                        "hostname": n["hostname"],
                        "status": computed_status,
                        "deployment_mode": n["deployment_mode"],
                        "ram_total": ram_total,
                        "ram_used": ram_used,
                        "vram_total": vram_total,
                        "vram_used": vram_used,
                        "agent_count": n["agent_count"] or 0,
                        "models_loaded": n["models_loaded"] or 0,
                        "cpu_usage": round(cpu_pct, 1),
                        "gpu_usage": round(gpu_pct, 1),
                        "gpu_model": n["gpu_model"],
                        "cpu_model": n["cpu_model"],
                        "cpu_cores": n["cpu_cores"],
                    }
                )

            # Fleet totals
            total_ram = sum(nd["ram_total"] for nd in nodes)
            total_ram_used = sum(nd["ram_used"] for nd in nodes)
            total_vram = sum(nd["vram_total"] for nd in nodes)
            total_vram_used = sum(nd["vram_used"] for nd in nodes)
            total_agents = sum(nd["agent_count"] for nd in nodes)
            total_models = sum(nd["models_loaded"] for nd in nodes)

            return jsonify(
                {
                    "success": True,
                    "fleet_totals": {
                        "node_count": len(nodes),
                        "online_count": sum(1 for nd in nodes if nd["status"] != "offline"),
                        "ram_total": round(total_ram, 1),
                        "ram_used": round(total_ram_used, 1),
                        "vram_total": round(total_vram, 1),
                        "vram_used": round(total_vram_used, 1),
                        "agent_count": total_agents,
                        "models_loaded": total_models,
                    },
                    "nodes": nodes,
                }
            )
        except Exception as e:
            logger.error(f"Fleet stats error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # ONE-CLICK SETUP SCRIPT DOWNLOADS
    # ========================================================================

    @bp.route("/api/nodes/<node_id>/setup-script")
    @auth_decorator
    def api_node_setup_script(node_id):
        """Download a customized setup/update script for an existing node."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        os_type = request.args.get("os", "linux").lower()
        hub_url = os.environ.get("STARSHIP_HUB_URL", "https://archie.kytranempowerment.com")
        token = node.get("setup_token", "")
        node_name = node.get("node_name", "Starship Node")

        if os_type == "windows":
            script = _generate_setup_ps1(hub_url, node_id, token, node_name)
            return Response(
                script,
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.ps1"'},
            )
        else:
            script = _generate_setup_sh(hub_url, node_id, token, node_name)
            return Response(
                script,
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.sh"'},
            )

    @bp.route("/api/nodes/new-setup-script")
    @auth_decorator
    def api_new_node_setup_script():
        """Auto-register a NEW node and return a downloadable setup script.

        For the one-line curl/powershell flow: registers a pending node,
        then returns the install script with credentials baked in.
        """
        import psycopg2

        user_id = current_user.id
        os_type = request.args.get("os", "linux").lower()
        node_name = request.args.get("name", "").strip()

        # Generate unique node ID and setup token
        node_id = f"starship_{secrets.token_hex(8)}"
        setup_token = secrets.token_urlsafe(32)
        if not node_name:
            node_name = f"Starship-{secrets.token_hex(3).upper()}"

        hub_url = os.environ.get("STARSHIP_HUB_URL", "https://archie.kytranempowerment.com")

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
                    RETURNING id, node_id, node_name
                    """,
                    (node_id, node_name, user_id, setup_token),
                )
                cur.fetchone()

            if os_type == "windows":
                script = _generate_setup_ps1(hub_url, node_id, setup_token, node_name)
                return Response(
                    script,
                    mimetype="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.ps1"'},
                )
            else:
                script = _generate_setup_sh(hub_url, node_id, setup_token, node_name)
                return Response(
                    script,
                    mimetype="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.sh"'},
                )
        except Exception as e:
            logger.exception("Failed to create new node setup script")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/disconnect", methods=["DELETE"])
    @auth_decorator
    def api_disconnect_node(node_id):
        """Disconnect a node from the fleet. Returns deployed agents to barracks."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        if node["deployment_mode"] == "starbase":
            return jsonify({"success": False, "error": "Cannot disconnect the Starbase"}), 400

        try:
            node_db_id = node["id"]
            with get_db_cursor(commit=True) as (conn, cur):
                # Return deployed agents to barracks
                cur.execute(
                    """UPDATE agents SET shift_state = 'barracked'
                       WHERE id IN (
                           SELECT hub_agent_id FROM node_agents
                           WHERE node_id = %s AND hub_agent_id IS NOT NULL
                       ) AND shift_state = 'deployed'""",
                    (node_db_id,),
                )
                returned = cur.rowcount

                # Delete node agents
                cur.execute("DELETE FROM node_agents WHERE node_id = %s", (node_db_id,))

                # Delete station assignments
                cur.execute(
                    "DELETE FROM node_station_assignments WHERE node_id = %s",
                    (node_db_id,),
                )

                # Delete heartbeat history
                cur.execute("DELETE FROM node_heartbeats WHERE node_id = %s", (node_db_id,))

                # Delete the node itself
                cur.execute("DELETE FROM remote_nodes WHERE id = %s", (node_db_id,))

                # Log notification
                cur.execute(
                    """INSERT INTO system_notifications (type, title, message, created_at)
                       VALUES ('warning', 'Node Disconnected',
                               %s, NOW())""",
                    (f"Node {node['node_name']} disconnected from fleet. {returned} agents returned to barracks.",),
                )

            logger.info(f"Node {node['node_name']} disconnected — {returned} agents returned to barracks")
            return jsonify(
                {
                    "success": True,
                    "message": f"Node disconnected. {returned} agents returned to barracks.",
                    "agents_returned": returned,
                }
            )
        except Exception as e:
            logger.error(f"Failed to disconnect node {node_id}: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500


# ============================================================================
# PRIVATE HELPERS (installer generators)
# ============================================================================


def _generate_setup_sh(hub_url, node_id, token, node_name):
    """Generate a self-contained bash heartbeat script. No Python, no Docker required.
    The script IS the heartbeat — it registers, collects hw info, and loops forever."""
    return f"""#!/bin/bash
# ============================================================
#  A.R.C.H.I.E. STARSHIP NODE — Self-Contained Heartbeat
#  Node: {node_name} ({node_id})
#  Hub:  {hub_url}
#  Just bash + curl. No Python. No Docker. No admin.
# ============================================================

CLIENT_VERSION="3.0.0"
HUB_URL="{hub_url}"
NODE_ID="{node_id}"
API_KEY="{token}"
NODE_NAME="{node_name}"
INSTALL_DIR="$HOME/archie-node"
HEARTBEAT_INTERVAL=30
FAIL_COUNT=0

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║  A.R.C.H.I.E. STARSHIP NODE                 ║"
echo "  ║  Self-Contained Heartbeat Client v$CLIENT_VERSION       ║"
echo "  ║  Node: {node_name}"
echo "  ║  Hub:  {hub_url}"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

command -v curl >/dev/null 2>&1 || {{ echo "ERROR: curl is required."; exit 1; }}

# ── Step 1: Create install directory ──
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
echo "[1/5] Install dir: $INSTALL_DIR"

# ── Step 2: Register with hub ──
echo "[2/5] Registering with hub..."
REG_RESPONSE=$(curl -sS -X POST "$HUB_URL/tools/starbase/api/nodes/register" \\
    -H "Content-Type: application/json" \\
    -d "{{\\"node_id\\": \\"$NODE_ID\\", \\"api_key\\": \\"$API_KEY\\", \\"node_name\\": \\"$NODE_NAME\\"}}" 2>/dev/null) || true

if echo "$REG_RESPONSE" | grep -q '"api_key"'; then
    REG_KEY=$(echo "$REG_RESPONSE" | grep -o '"api_key"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$REG_KEY" ]; then API_KEY="$REG_KEY"; fi
    echo "  Registered successfully."
else
    echo "  Using pre-assigned credentials."
fi

# ── Step 3: Write config.json ──
echo "[3/5] Writing config.json..."
cat > "$INSTALL_DIR/config.json" << CONFIGEOF
{{
    "node_id": "$NODE_ID",
    "node_name": "$NODE_NAME",
    "api_key": "$API_KEY",
    "hub_url": "$HUB_URL",
    "deployment_mode": "starship",
    "heartbeat_interval": $HEARTBEAT_INTERVAL,
    "client_version": "$CLIENT_VERSION"
}}
CONFIGEOF

# ── Step 4: Detect hardware ──
echo "[4/5] Detecting hardware..."
CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || echo "Unknown")
RAM_GB=$(awk '/MemTotal/{{printf "%.1f", $2/1048576}}' /proc/meminfo 2>/dev/null || echo "0")
GPU_MODEL="None"
GPU_VRAM="0"
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_MODEL=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "None")
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    GPU_VRAM=$(echo "scale=1; $GPU_VRAM/1024" | bc 2>/dev/null || echo "0")
fi
echo "  CPU: $CPU_MODEL | RAM: ${{RAM_GB}}GB | GPU: $GPU_MODEL (${{GPU_VRAM}}GB)"

# ── Step 5: Detect Ollama + auto-start ──
OLLAMA_ONLINE="false"
OLLAMA_MODELS="[]"
check_ollama() {{
    local resp
    resp=$(curl -sS --max-time 3 "http://localhost:11434/api/tags" 2>/dev/null) || return
    if echo "$resp" | grep -q '"models"'; then
        OLLAMA_ONLINE="true"
        OLLAMA_MODELS=$(echo "$resp" | grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4 | \\
            awk 'BEGIN{{printf "["}} NR>1{{printf ","}} {{printf "\\"%s\\"", $0}} END{{printf "]"}}')
    else
        OLLAMA_ONLINE="false"; OLLAMA_MODELS="[]"
    fi
}}
check_ollama
echo "  Ollama: $OLLAMA_ONLINE"

echo "[5/5] Setting up auto-start..."
SCRIPT_PATH=$(readlink -f "$0")
if command -v systemctl >/dev/null 2>&1; then
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/archie-node.service" << SVCEOF
[Unit]
Description=A.R.C.H.I.E. Starship Node Heartbeat
After=network-online.target
[Service]
ExecStart=/bin/bash $SCRIPT_PATH
Restart=always
RestartSec=10
[Install]
WantedBy=default.target
SVCEOF
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable archie-node.service 2>/dev/null || true
    echo "  Systemd user service installed."
else
    (crontab -l 2>/dev/null | grep -v "archie-node"; echo "@reboot /bin/bash $SCRIPT_PATH") | crontab - 2>/dev/null || true
    echo "  Cron @reboot entry added."
fi

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║  NODE ONLINE — Sending heartbeats            ║"
echo "  ║  Node ID: $NODE_ID"
echo "  ║  Config:  $INSTALL_DIR/config.json"
echo "  ║  Press Ctrl+C to stop                        ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── Heartbeat loop ──
get_interval() {{
    if [ "$FAIL_COUNT" -ge 10 ]; then echo 30; FAIL_COUNT=0
    elif [ "$FAIL_COUNT" -ge 5 ]; then echo 120
    elif [ "$FAIL_COUNT" -ge 3 ]; then echo 60
    else echo $HEARTBEAT_INTERVAL; fi
}}

while true; do
    CPU_USAGE=$(awk '{{u=$2+$4; t=$2+$4+$5}} NR==1{{ou=u;ot=t}} NR==2{{printf "%.1f", (u-ou)/(t-ot)*100}}' \\
        <(grep '^cpu ' /proc/stat; sleep 1; grep '^cpu ' /proc/stat) 2>/dev/null || echo "0")
    MEM_USAGE=$(awk '/MemTotal/{{t=$2}} /MemAvailable/{{a=$2}} END{{printf "%.1f", (t-a)/t*100}}' /proc/meminfo 2>/dev/null || echo "0")
    GPU_USAGE="0"
    if command -v nvidia-smi >/dev/null 2>&1; then
        GPU_USAGE=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    fi
    check_ollama

    PAYLOAD="{{\\"node_id\\": \\"$NODE_ID\\", \\"api_key\\": \\"$API_KEY\\", \\"status\\": \\"online\\", \
\\"cpu_usage\\": $CPU_USAGE, \\"memory_usage\\": $MEM_USAGE, \\"gpu_usage\\": $GPU_USAGE, \
\\"ollama_online\\": $OLLAMA_ONLINE, \\"ollama_models\\": $OLLAMA_MODELS, \
\\"client_version\\": \\"$CLIENT_VERSION\\", \\"cpu_model\\": \\"$CPU_MODEL\\", \
\\"ram_gb\\": $RAM_GB, \\"gpu_model\\": \\"$GPU_MODEL\\", \\"gpu_vram_gb\\": $GPU_VRAM}}"

    RESPONSE=$(curl -sS -X POST "$HUB_URL/tools/starbase/api/nodes/heartbeat" \\
        -H "Content-Type: application/json" -H "X-Node-API-Key: $API_KEY" \\
        -d "$PAYLOAD" --max-time 10 2>/dev/null) || RESPONSE=""

    if echo "$RESPONSE" | grep -q '"status"'; then
        FAIL_COUNT=0
        if echo "$RESPONSE" | grep -q '"update_available"[[:space:]]*:[[:space:]]*true'; then
            echo "[$(date +%H:%M:%S)] Update available — re-downloading script..."
            curl -sS "$HUB_URL/tools/starship/download/setup-sh/$NODE_ID" -o "$SCRIPT_PATH.new" 2>/dev/null && \\
                mv "$SCRIPT_PATH.new" "$SCRIPT_PATH" && chmod +x "$SCRIPT_PATH" && \\
                exec bash "$SCRIPT_PATH"
        fi
        echo "[$(date +%H:%M:%S)] Heartbeat OK | CPU:${{CPU_USAGE}}% MEM:${{MEM_USAGE}}% GPU:${{GPU_USAGE}}% Ollama:$OLLAMA_ONLINE"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "[$(date +%H:%M:%S)] Heartbeat FAILED ($FAIL_COUNT) — retrying in $(get_interval)s"
    fi

    sleep $(get_interval)
done
"""


def _generate_setup_ps1(hub_url, node_id, token, node_name):
    """Generate a self-contained PowerShell heartbeat script. No Python, no Docker,
    no admin, no scheduled tasks. The script IS the heartbeat — runs in a while loop.
    Pure PowerShell that ships with every Windows machine."""
    return f"""# ============================================================
#  A.R.C.H.I.E. STARSHIP NODE — Self-Contained Heartbeat
#  Node: {node_name} ({node_id})
#  Hub:  {hub_url}
#  Pure PowerShell. No Python. No Docker. No admin rights.
# ============================================================

$ClientVersion = "3.0.0"
$HubUrl        = "{hub_url}"
$NodeId        = "{node_id}"
$ApiKey        = "{token}"
$NodeName      = "{node_name}"
$InstallDir    = "$env:USERPROFILE\\archie-node"
$HBInterval    = 30
$FailCount     = 0
$ProgressPreference = 'SilentlyContinue'

# ── Banner ──
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║  A.R.C.H.I.E. STARSHIP NODE                 ║" -ForegroundColor Cyan
Write-Host "  ║  Self-Contained Heartbeat Client v$ClientVersion       ║" -ForegroundColor Cyan
Write-Host "  ║  Node: {node_name}" -ForegroundColor Cyan
Write-Host "  ║  Hub:  {hub_url}" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Install directory ──
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir
Write-Host "[1/6] Install dir: $InstallDir" -ForegroundColor Yellow

# ── Step 2: Register with hub ──
Write-Host "[2/6] Registering with hub..." -ForegroundColor Yellow
try {{
    $regBody = @{{ node_id = $NodeId; api_key = $ApiKey; node_name = $NodeName }} | ConvertTo-Json
    $regResp = Invoke-RestMethod -Uri "$HubUrl/tools/starbase/api/nodes/register" -Method POST `
        -ContentType "application/json" -Body $regBody -TimeoutSec 10
    if ($regResp.api_key) {{ $ApiKey = $regResp.api_key }}
    Write-Host "  Registered successfully." -ForegroundColor Green
}} catch {{
    Write-Host "  Using pre-assigned credentials." -ForegroundColor Yellow
}}

# ── Step 3: Write config.json ──
Write-Host "[3/6] Writing config.json..." -ForegroundColor Yellow
@{{
    node_id            = $NodeId
    node_name          = $NodeName
    api_key            = $ApiKey
    hub_url            = $HubUrl
    deployment_mode    = "starship"
    heartbeat_interval = $HBInterval
    client_version     = $ClientVersion
}} | ConvertTo-Json | Set-Content -Path "$InstallDir\\config.json" -Encoding UTF8

# ── Step 4: Detect hardware ──
Write-Host "[4/6] Detecting hardware..." -ForegroundColor Yellow
$cpuInfo  = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$osInfo   = Get-CimInstance Win32_OperatingSystem
$ramGB    = [math]::Round($osInfo.TotalVisibleMemorySize / 1MB, 1)
$gpuModel = "None"; $gpuVram = 0
try {{
    $nv = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null
    if ($nv) {{
        $parts    = $nv -split ","
        $gpuModel = $parts[0].Trim()
        $gpuVram  = [math]::Round([double]$parts[1].Trim() / 1024, 1)
    }}
}} catch {{}}
Write-Host "  CPU: $cpuInfo | RAM: ${{ramGB}}GB | GPU: $gpuModel (${{gpuVram}}GB)" -ForegroundColor Gray

# ── Step 5: Detect Ollama ──
Write-Host "[5/6] Checking for Ollama..." -ForegroundColor Yellow
function Get-OllamaStatus {{
    try {{
        $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
        $models = @($resp.models | ForEach-Object {{ $_.name }})
        return @{{ online = $true; models = $models }}
    }} catch {{
        return @{{ online = $false; models = @() }}
    }}
}}
$ollama = Get-OllamaStatus
Write-Host "  Ollama: $(if ($ollama.online) {{ 'ONLINE (' + $ollama.models.Count + ' models)' }} else {{ 'OFFLINE' }})" -ForegroundColor Gray

# ── Step 6: Startup shortcut (non-admin) ──
Write-Host "[6/6] Setting up auto-start..." -ForegroundColor Yellow
$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath) {{
    try {{
        $startupDir = [IO.Path]::Combine($env:APPDATA, "Microsoft\\Windows\\Start Menu\\Programs\\Startup")
        $lnkPath    = "$startupDir\\ARCHIE-Node.lnk"
        $shell      = New-Object -ComObject WScript.Shell
        $shortcut   = $shell.CreateShortcut($lnkPath)
        $shortcut.TargetPath       = "powershell.exe"
        $shortcut.Arguments        = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.WindowStyle      = 7
        $shortcut.Save()
        Write-Host "  Auto-start on login enabled." -ForegroundColor Green
    }} catch {{
        Write-Host "  Could not create startup shortcut (non-critical)." -ForegroundColor Yellow
    }}
}} else {{
    Write-Host "  Run from a saved .ps1 file for auto-start." -ForegroundColor Yellow
}}

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║  NODE ONLINE — Sending heartbeats            ║" -ForegroundColor Green
Write-Host "  ║  Node ID: $NodeId" -ForegroundColor Green
Write-Host "  ║  Config:  $InstallDir\\config.json" -ForegroundColor Green
Write-Host "  ║  Press Ctrl+C to stop                        ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

# ── Heartbeat loop ──
function Get-Interval {{
    if ($script:FailCount -ge 10) {{ $script:FailCount = 0; return 30 }}
    if ($script:FailCount -ge 5)  {{ return 120 }}
    if ($script:FailCount -ge 3)  {{ return 60 }}
    return $HBInterval
}}

while ($true) {{
    $cpuUsage = [math]::Round((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average, 1)
    $os       = Get-CimInstance Win32_OperatingSystem
    $memUsage = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize * 100, 1)
    $gpuUsage = 0
    try {{ $gpuUsage = [int](& nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>$null) }} catch {{}}
    $ollama = Get-OllamaStatus

    $payload = @{{
        node_id        = $NodeId
        api_key        = $ApiKey
        status         = "online"
        cpu_usage      = $cpuUsage
        memory_usage   = $memUsage
        gpu_usage      = $gpuUsage
        ollama_online  = $ollama.online
        ollama_models  = $ollama.models
        client_version = $ClientVersion
        cpu_model      = $cpuInfo
        ram_gb         = $ramGB
        gpu_model      = $gpuModel
        gpu_vram_gb    = $gpuVram
    }} | ConvertTo-Json -Depth 3

    try {{
        $resp = Invoke-RestMethod -Uri "$HubUrl/tools/starbase/api/nodes/heartbeat" -Method POST `
            -ContentType "application/json" -Body $payload `
            -Headers @{{ "X-Node-API-Key" = $ApiKey }} -TimeoutSec 10
        $FailCount = 0
        $ts = Get-Date -Format "HH:mm:ss"

        if ($resp.update_available -eq $true -and $scriptPath) {{
            Write-Host "[$ts] Update available - re-downloading script..." -ForegroundColor Magenta
            try {{
                Invoke-WebRequest -Uri "$HubUrl/tools/starship/download/setup-ps1/$NodeId" `
                    -OutFile "$scriptPath.new" -UseBasicParsing
                Move-Item -Force "$scriptPath.new" $scriptPath
                Write-Host "[$ts] Restarting with updated script..." -ForegroundColor Magenta
                Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$scriptPath`""
                exit 0
            }} catch {{
                Write-Host "[$ts] Update failed: $_" -ForegroundColor Red
            }}
        }}

        Write-Host "[$ts] Heartbeat OK | CPU:${{cpuUsage}}% MEM:${{memUsage}}% GPU:${{gpuUsage}}% Ollama:$(if($ollama.online){{'ON'}}else{{'OFF'}})" -ForegroundColor DarkGray
    }} catch {{
        $FailCount++
        $ts = Get-Date -Format "HH:mm:ss"
        Write-Host "[$ts] Heartbeat FAILED ($FailCount) - retrying in $(Get-Interval)s" -ForegroundColor Red
    }}

    Start-Sleep -Seconds (Get-Interval)
}}
"""


def _generate_bash_installer(hub_url, node_id, token):
    """Generate self-contained bash heartbeat (alias for _generate_setup_sh without node_name)."""
    return _generate_setup_sh(hub_url, node_id, token, node_id)


def _generate_powershell_installer(hub_url, node_id, token):
    """Generate self-contained PowerShell heartbeat (alias for _generate_setup_ps1 without node_name)."""
    return _generate_setup_ps1(hub_url, node_id, token, node_id)
