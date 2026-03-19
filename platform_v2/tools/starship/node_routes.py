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
            return jsonify({"success": False, "error": str(e)}), 500

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
                f"UPDATE remote_nodes SET {', '.join(updates)} WHERE node_id = %s",
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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# PRIVATE HELPERS (installer generators)
# ============================================================================


def _generate_bash_installer(hub_url, node_id, token):
    """Generate bash install script with credentials injected."""
    return f"""#!/bin/bash
set -e
echo "=== A.R.C.H.I.E. Starship Node Installer ==="
echo "Hub: {hub_url}"
echo "Node: {node_id}"

# Download node package
curl -fsSL "{hub_url}/starship/download/node-package" -o archie-node.tar.gz

# Extract
mkdir -p archie-node && tar xzf archie-node.tar.gz -C archie-node --strip-components=1
cd archie-node

# Write .env
cat > .env << 'ENVEOF'
HUB_URL={hub_url}
NODE_ID={node_id}
HUB_API_KEY={token}
ENVEOF

# Detect timezone
if [ -f /etc/timezone ]; then
    TZ=$(cat /etc/timezone)
elif [ -L /etc/localtime ]; then
    TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
else
    TZ="UTC"
fi
echo "NODE_TIMEZONE=$TZ" >> .env

echo "Starting containers..."
docker compose -f docker-compose.node.yml up -d

echo ""
echo "=== Installation complete ==="
echo "Node API: http://localhost:3001/health"
"""


def _generate_powershell_installer(hub_url, node_id, token):
    """Generate PowerShell install script with credentials injected."""
    return f"""# A.R.C.H.I.E. Starship Node Installer
Write-Host "=== A.R.C.H.I.E. Starship Node Installer ===" -ForegroundColor Cyan
Write-Host "Hub: {hub_url}"
Write-Host "Node: {node_id}"

# Download node package
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri "{hub_url}/starship/download/node-package" -OutFile archie-node.tar.gz

# Extract
New-Item -ItemType Directory -Force -Path archie-node | Out-Null
tar xzf archie-node.tar.gz -C archie-node --strip-components=1
Set-Location archie-node

# Write .env
@"
HUB_URL={hub_url}
NODE_ID={node_id}
HUB_API_KEY={token}
NODE_TIMEZONE=$((Get-TimeZone).Id)
"@ | Set-Content .env

Write-Host "Starting containers..." -ForegroundColor Yellow
docker compose -f docker-compose.node.yml up -d

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host "Node API: http://localhost:3001/health"
"""
