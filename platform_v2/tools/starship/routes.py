"""
Starship Command — Fleet node management module.

Fleet owners see all their nodes. Node operators see their own ship.
Privacy controls let operators choose what to share with the fleet.
"""

import json
import os
import random
import secrets

from flask import Blueprint, render_template, jsonify, request, send_file
from flask_login import login_required, current_user
from database import get_db_cursor

# ── Node crew name pool (unique from Bridge agents) ──
# Each node gets random picks from this pool — never duplicating Bridge names
_STARSHIP_FIRST_NAMES = [
    "Ava",
    "Riku",
    "Leona",
    "Dex",
    "Freya",
    "Idris",
    "Yuna",
    "Soren",
    "Maren",
    "Cyrus",
    "Zola",
    "Kael",
    "Nori",
    "Raven",
    "Orion",
    "Isla",
    "Juno",
    "Thane",
    "Veda",
    "Atlas",
    "Lyra",
    "Reese",
    "Sage",
    "Kira",
    "Quinn",
    "Nova",
    "Wren",
    "Bodhi",
    "Cleo",
    "Inara",
    "Ronan",
    "Talia",
    "Ezra",
    "Mira",
    "Dash",
    "Ember",
    "Silas",
    "Rue",
    "Cassian",
    "Petra",
    "Zephyr",
    "Aiko",
    "Lux",
    "Orin",
    "Vesper",
    "Tamsin",
    "Hiro",
    "Sable",
]
_STARSHIP_LAST_NAMES = [
    "Voss",
    "Tanabe",
    "Okonkwo",
    "Reis",
    "Lindholm",
    "Zhao",
    "Adeyemi",
    "Frost",
    "Nakamura",
    "Volkov",
    "Reyes",
    "Strand",
    "Yamamoto",
    "Fischer",
    "Okafor",
    "Petrova",
    "Cortez",
    "Sato",
    "Johansson",
    "Mwangi",
    "Hale",
    "Nkosi",
    "Dubois",
    "Okoro",
    "Engström",
    "Takeda",
    "Guerrero",
    "Novak",
    "Andersen",
    "Kimura",
    "Ibarra",
    "Mori",
    "Asante",
    "Larsson",
    "Ramos",
    "Theron",
    "Hayashi",
    "Bakker",
    "Osei",
    "Kato",
    "Braun",
    "Diallo",
]


def _generate_node_crew(node_int_id, node_id):
    """Generate unique crew for a node based on its active stations.

    Clones roles from Bridge agents but assigns fresh names.
    Only creates agents for stations the node has enabled.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        # Get Bridge agents assigned to this node's active stations
        cur.execute(
            """
            SELECT DISTINCT a.id, a.name, a.title, a.model, a.system_prompt,
                   a.capabilities,
                   array_agg(DISTINCT bs.station_code) as station_codes
            FROM agents a
            JOIN station_assignments sa ON sa.agent_id = a.id
            JOIN bridge_stations bs ON bs.id = sa.station_id
            JOIN node_station_assignments nsa ON nsa.station_id = bs.id
                AND nsa.node_id = %s AND nsa.is_active = true
            WHERE a.status = 'active'
                AND a.is_cloneable = true
            GROUP BY a.id
            """,
            (node_int_id,),
        )
        bridge_agents = cur.fetchall()
        if not bridge_agents:
            return

        # Get existing node agent names to avoid dupes
        cur.execute(
            "SELECT source_agent_id FROM node_agents WHERE node_id = %s",
            (node_int_id,),
        )
        existing = {r["source_agent_id"] for r in cur.fetchall()}

        # Get ALL used first+last combos across all nodes to guarantee uniqueness
        cur.execute("SELECT first_name, last_name FROM node_agents")
        used_names = {(r["first_name"], r["last_name"]) for r in cur.fetchall()}

        # Also exclude Bridge agent names
        cur.execute("SELECT first_name, last_name FROM agents WHERE first_name IS NOT NULL")
        for r in cur.fetchall():
            used_names.add((r["first_name"], r["last_name"]))

        rng = random.Random(node_id)  # deterministic seed per node
        firsts = list(_STARSHIP_FIRST_NAMES)
        lasts = list(_STARSHIP_LAST_NAMES)
        rng.shuffle(firsts)
        rng.shuffle(lasts)

        fi, li = 0, 0
        for agent in bridge_agents:
            if agent["id"] in existing:
                # Already has a node agent for this role — update station_codes
                cur.execute(
                    """
                    UPDATE node_agents SET station_codes = %s, updated_at = now()
                    WHERE node_id = %s AND source_agent_id = %s
                    """,
                    (agent["station_codes"], node_int_id, agent["id"]),
                )
                continue

            # Pick a unique name combo
            fname, lname = None, None
            attempts = 0
            while attempts < 200:
                f = firsts[fi % len(firsts)]
                l = lasts[li % len(lasts)]
                fi += 1
                if (fi % len(firsts)) == 0:
                    li += 1
                attempts += 1
                if (f, l) not in used_names:
                    fname, lname = f, l
                    used_names.add((f, l))
                    break

            if not fname:
                fname = f"Agent-{node_int_id}-{agent['id']}"
                lname = ""

            codename = agent["name"]
            display = f"{fname} {lname} ({codename})" if lname else f"{fname} ({codename})"

            cur.execute(
                """
                INSERT INTO node_agents
                    (node_id, source_agent_id, name, first_name, last_name,
                     display_name, title, model, system_prompt, capabilities,
                     station_codes, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                ON CONFLICT (node_id, name) DO NOTHING
                """,
                (
                    node_int_id,
                    agent["id"],
                    codename,
                    fname,
                    lname,
                    display,
                    agent["title"],
                    agent["model"],
                    agent["system_prompt"],
                    json.dumps(agent["capabilities"]) if agent["capabilities"] else None,
                    agent["station_codes"],
                ),
            )


starship_bp = Blueprint(
    "starship",
    __name__,
    url_prefix="/tools/starship",
    template_folder="templates",
)


HEARTBEAT_TIMEOUT_SECONDS = 120  # 2 minutes — node heartbeats every 30s


def _compute_node_status(node):
    """Compute real status based on heartbeat freshness."""
    from datetime import datetime, timezone

    if not node.get("last_heartbeat"):
        return "offline"
    hb = node["last_heartbeat"]
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - hb).total_seconds()
    if age > HEARTBEAT_TIMEOUT_SECONDS:
        return "offline"
    return node.get("status", "online")


def _get_user_nodes(user_id):
    """Get all starship nodes owned by this user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, node_id, node_name, deployment_mode, hostname, port,
                   status, is_active, bridge_enabled, bridge_priority,
                   gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                   approval_status, last_heartbeat, client_version,
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
        raw_nodes = _get_user_nodes(user_id)
        for n in raw_nodes:
            d = dict(n)
            d["status"] = _compute_node_status(n)
            nodes.append(d)
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


# Current node package version (update this when releasing new packages)
LATEST_NODE_VERSION = "1.1.2"


@starship_bp.route("/api/nodes/<node_id>/status")
@login_required
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
                (node_id,),
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

            # Ensure node crew exists before counting
            _generate_node_crew(node.get("id") or 0, node["node_id"])

            # All stations with agent counts
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
        active_stations = sum(1 for s in stations if s["assigned"] and s["station_active"])

        return jsonify(
            {
                "success": True,
                "node": {
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
                    "memory_usage": float(latest_hb["memory_usage"]) if latest_hb and latest_hb["memory_usage"] else 0,
                    "gpu_usage": float(latest_hb["gpu_usage"]) if latest_hb and latest_hb["gpu_usage"] else 0,
                    "current_load": float(latest_hb["current_load"]) if latest_hb and latest_hb["current_load"] else 0,
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
                    "total": len(stations),
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
# AGENT & STATION CONTROLS
# ============================================================================


@starship_bp.route("/api/nodes/<node_id>/agent-access", methods=["POST"])
@login_required
def api_toggle_agent_access(node_id):
    """Toggle whether an agent is allowed to run on this node."""
    user_id = current_user.id
    node = _get_node_for_user(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404

    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    is_allowed = data.get("is_allowed", True)

    if not agent_id:
        return jsonify({"success": False, "error": "agent_id required"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE node_agents SET is_allowed = %s, updated_at = now()
            WHERE id = %s AND node_id = (
                SELECT id FROM remote_nodes WHERE node_id = %s
            )
            """,
            (is_allowed, agent_id, node_id),
        )
    return jsonify({"success": True, "agent_id": agent_id, "is_allowed": is_allowed})


@starship_bp.route("/api/nodes/<node_id>/station-toggle", methods=["POST"])
@login_required
def api_toggle_station(node_id):
    """Toggle a station assignment on/off for this node."""
    user_id = current_user.id
    node = _get_node_for_user(node_id, user_id)
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404

    data = request.get_json() or {}
    station_id = data.get("station_id")
    enabled = data.get("enabled", True)

    if not station_id:
        return jsonify({"success": False, "error": "station_id required"}), 400

    node_db_id = node.get("id") or 0
    with get_db_cursor(commit=True) as (conn, cur):
        if enabled:
            cur.execute(
                """
                INSERT INTO node_station_assignments (node_id, station_id, is_active)
                VALUES (%s, %s, true)
                ON CONFLICT (node_id, station_id)
                DO UPDATE SET is_active = true
                """,
                (node_db_id, station_id),
            )
        else:
            cur.execute(
                """
                UPDATE node_station_assignments
                SET is_active = false
                WHERE node_id = %s AND station_id = %s
                """,
                (node_db_id, station_id),
            )
    return jsonify({"success": True, "station_id": station_id, "enabled": enabled})


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


@starship_bp.route("/api/nodes/<node_id>/request-update", methods=["POST"])
@login_required
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
