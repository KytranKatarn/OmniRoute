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

# SaaS module to station mapping for agent recommendations
MODULE_STATION_MAP = {
    "store-builder": ["OPERATIONS", "ANALYTICS"],
    "media-hub": ["CREATIVE", "OPERATIONS"],
    "email-manager": ["OPERATIONS"],
    "invoicing": ["OPERATIONS", "ANALYTICS"],
    "website-studio": ["CREATIVE", "ENGINEERING"],
    "crm": ["OPERATIONS", "ANALYTICS"],
    "social-media": ["CREATIVE", "OPERATIONS"],
    "content-studio": ["CREATIVE"],
    "dev-pipeline": ["ENGINEERING", "QA"],
    "fitness": ["ANALYTICS", "OPERATIONS"],
    "therapy": ["ANALYTICS", "RESEARCH"],
    "game-studio": ["CREATIVE", "ENGINEERING"],
    "media-studio": ["CREATIVE"],
    "scheduler": ["OPERATIONS"],
    "call-center": ["OPERATIONS"],
    "task-planner": ["OPERATIONS", "ANALYTICS"],
    "stockbot": ["ANALYTICS", "RESEARCH"],
}

# Approximate model sizes in GB for efficiency scoring
MODEL_SIZE_HINTS = {
    "qwen2.5:0.5b": 0.4,
    "qwen2.5:1.5b": 1.0,
    "qwen2.5:3b": 2.0,
    "qwen2.5:7b": 4.7,
    "qwen2.5:14b": 9.0,
    "qwen2.5:32b": 20.0,
    "qwen2.5:72b": 47.0,
    "qwen3:0.6b": 0.4,
    "qwen3:1.7b": 1.1,
    "qwen3:4b": 2.6,
    "qwen3:8b": 5.2,
    "qwen3:14b": 9.2,
    "qwen3:32b": 20.0,
    "llama3.2:1b": 0.7,
    "llama3.2:3b": 2.0,
    "llama3.1:8b": 4.9,
    "llama3.1:70b": 43.0,
    "phi3.5:3.8b": 2.2,
    "phi4:14b": 9.1,
    "gemma2:2b": 1.6,
    "gemma2:9b": 5.4,
    "gemma2:27b": 16.0,
    "mistral:7b": 4.1,
    "codellama:7b": 3.8,
    "deepseek-r1:1.5b": 1.1,
    "deepseek-r1:7b": 4.7,
    "deepseek-r1:8b": 4.9,
    "deepseek-r1:14b": 9.0,
    "deepseek-r1:32b": 20.0,
    "nomic-embed-text": 0.3,
    "granite3.2-vision:2b": 1.5,
}

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
        assigned_stations = sum(1 for s in stations if s["assigned"])
        active_stations = sum(1 for s in stations if s["assigned"] and s["station_active"])

        return jsonify(
            {
                "success": True,
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
            (json.dumps(settings), node_id),
        )
    return jsonify({"success": True, "privacy_settings": settings})


@starship_bp.route("/api/nodes/<int:node_id>/privacy", methods=["GET", "POST"])
@login_required
def api_node_privacy(node_id):
    """Get or update node privacy settings (mesh sharing controls)."""
    import psycopg2

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id, privacy_settings FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        node = cur.fetchone()
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        if request.method == "GET":
            return jsonify({"success": True, "privacy": node["privacy_settings"] or {}})

        data = request.get_json() or {}
        settings = node["privacy_settings"] or {}

        if "share_agents" in data:
            settings["share_agents"] = bool(data["share_agents"])
        if "max_shared_jobs" in data:
            settings["max_shared_jobs"] = max(1, min(5, int(data["max_shared_jobs"])))

        # local_first is always True
        settings["local_first"] = True

        cur.execute(
            "UPDATE remote_nodes SET privacy_settings = %s WHERE id = %s",
            (json.dumps(settings), node_id),
        )

        return jsonify({"success": True, "privacy": settings})


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
# NODE STATION TERMINALS (StationOps-compatible live data)
# ============================================================================


@starship_bp.route("/api/nodes/<int:node_id>/stations-live")
@login_required
def api_node_stations_live(node_id):
    """Return node crew in StationOps-compatible format for LCARS terminal rendering."""
    with get_db_cursor() as (conn, cur):
        # Get node info (need string node_id for mesh_agent_loans lookup)
        cur.execute("SELECT id, node_id FROM remote_nodes WHERE id = %s", (node_id,))
        node = cur.fetchone()
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        node_str_id = node["node_id"]

        # Get enabled stations for this node
        cur.execute(
            """
            SELECT bs.station_code, bs.station_name, bs.color, bs.icon,
                   bs.max_primary, bs.max_auxiliary
            FROM node_station_assignments nsa
            JOIN bridge_stations bs ON bs.id = nsa.station_id
            WHERE nsa.node_id = %s AND nsa.is_active = true
            ORDER BY bs.position_row, bs.position_order
            """,
            (node_id,),
        )
        enabled_stations = cur.fetchall()

        stations = []
        for st in enabled_stations:
            code = st["station_code"]
            max_primary = st.get("max_primary") or 2
            max_aux = st.get("max_auxiliary") or 1

            # Primary/secondary agents for this station
            cur.execute(
                """
                SELECT na.id, na.name, na.display_name, na.title,
                       na.model, na.status
                FROM node_agents na
                WHERE na.node_id = %s AND na.status = 'active'
                  AND %s = ANY(na.station_codes)
                ORDER BY na.id
                LIMIT %s
                """,
                (node_id, code, max_primary),
            )
            crew_rows = cur.fetchall()

            assigned_agents = []
            assignment_labels = ["primary", "secondary"]
            for i, agent in enumerate(crew_rows):
                display = agent["display_name"] or agent["name"] or "Unknown"
                parts = display.split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ""
                label = assignment_labels[i] if i < len(assignment_labels) else "crew"
                assigned_agents.append(
                    {
                        "first_name": first_name,
                        "last_name": last_name,
                        "name": agent["name"],
                        "title": agent["title"] or label,
                        "assignment_type": label,
                        "status": "active" if agent["status"] == "active" else "paused",
                    }
                )

            # Mesh-loaned agents (auxiliary slot)
            cur.execute(
                """
                SELECT mal.id, na.name, na.display_name, na.title,
                       mal.task_description
                FROM mesh_agent_loans mal
                LEFT JOIN node_agents na ON na.id = mal.agent_id
                WHERE mal.target_node_id = %s AND mal.status = 'active'
                LIMIT %s
                """,
                (node_str_id, max_aux),
            )
            loan_rows = cur.fetchall()

            assists = []
            for loan in loan_rows:
                display = loan["display_name"] or loan["name"] or "Mesh Helper"
                parts = display.split(" ", 1)
                assists.append(
                    {
                        "first_name": parts[0],
                        "last_name": parts[1] if len(parts) > 1 else "",
                        "name": loan["name"] or "mesh-assist",
                        "title": "MESH ASSIST",
                        "assignment_type": "auxiliary",
                        "status": "active",
                    }
                )

            stations.append(
                {
                    "code": code,
                    "station_name": st["station_name"],
                    "color": st["color"],
                    "max_primary": max_primary,
                    "max_auxiliary": max_aux,
                    "assigned_agents": assigned_agents,
                    "assists": assists,
                    "contractors": [],
                    "jobs": [],
                }
            )

        return jsonify({"success": True, "stations": stations})


@starship_bp.route("/api/model-catalog")
@login_required
def api_model_catalog():
    """Return the curated model catalog for browsing and selection."""
    category = request.args.get("category")
    with get_db_cursor() as (conn, cur):
        if category:
            cur.execute(
                "SELECT * FROM model_catalog WHERE is_active = true AND category = %s ORDER BY size_gb",
                (category,),
            )
        else:
            cur.execute("SELECT * FROM model_catalog WHERE is_active = true ORDER BY category, size_gb")
        models = cur.fetchall()
        return jsonify({"success": True, "models": [dict(m) for m in models]})


@starship_bp.route("/api/nodes/<int:node_id>/crew-manifest")
@login_required
def api_node_crew_manifest(node_id):
    """Return node agents in Bridge manifest-compatible format for rich card rendering."""
    with get_db_cursor() as (conn, cur):
        # Get all node agents
        cur.execute(
            """
            SELECT na.id as agent_id, na.name, na.display_name as full_name,
                   na.title, na.model, na.status,
                   na.station_codes, na.is_allowed as allowed
            FROM node_agents na
            WHERE na.node_id = %s
            ORDER BY na.name
            """,
            (node_id,),
        )
        agents = cur.fetchall()

        # Get node's Ollama models for LLM readiness check
        cur.execute(
            "SELECT node_id FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        node_row = cur.fetchone()
        if not node_row:
            return jsonify({"success": False, "error": "Node not found"}), 404

        # Get available models on this node
        cur.execute(
            """
            SELECT model_name, is_available
            FROM node_ollama_models
            WHERE node_id = %s
            """,
            (node_row["node_id"],),
        )
        models = cur.fetchall()
        available_models = {m["model_name"].split(":")[0].lower() for m in models if m["is_available"]}
        available_exact = {m["model_name"] for m in models if m["is_available"]}

        # Get station colors
        cur.execute("SELECT station_code, color FROM bridge_stations")
        station_colors = {s["station_code"]: s["color"] for s in cur.fetchall()}

        manifest = []
        for a in agents:
            agent_model = a["model"] or ""
            agent_base = agent_model.split(":")[0].lower()

            # Determine LLM readiness
            if agent_model in available_exact or agent_base in available_models:
                llm_status = "loaded"
            else:
                llm_status = "barracked"

            codes = a["station_codes"] or []
            colors = [station_colors.get(c, "#00e5ff") for c in codes]

            manifest.append(
                {
                    "agent_id": a["agent_id"],
                    "name": a["name"],
                    "full_name": a["full_name"] or a["name"],
                    "title": a["title"] or "",
                    "model": agent_model,
                    "status": "active" if a["status"] == "active" else "idle",
                    "llm_status": llm_status,
                    "station": codes[0] if codes else "UNASSIGNED",
                    "station_codes": codes,
                    "station_colors": colors,
                    "allowed": bool(a["allowed"]) if a["allowed"] is not None else True,
                    "wellness": {"stress": 0, "energy": 1.0, "mood": "ready"},
                    "stats_24h": {"dispatches": 0, "success_rate": 0},
                    "current_job": None,
                }
            )

        return jsonify({"success": True, "crew": manifest})


@starship_bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>/profile")
@login_required
def api_node_agent_profile(node_id, agent_id):
    """Get full agent profile — proxies to hub agent via hub_agent_id."""
    try:
        with get_db_cursor() as (conn, cur):
            # Get hub_agent_id from node_agents
            cur.execute(
                "SELECT hub_agent_id FROM node_agents WHERE id = %s AND node_id = %s",
                (agent_id, node_id),
            )
            na = cur.fetchone()
            if not na or not na["hub_agent_id"]:
                return jsonify({"success": False, "error": "Agent not linked to hub"}), 404
            hub_id = na["hub_agent_id"]

            # Agent details (same query pattern as Bridge)
            cur.execute(
                """
                SELECT a.id, a.name, a.first_name, a.last_name, a.title,
                       a.department, a.bio, a.model, a.status, a.avatar_url,
                       a.pronouns, a.worker_type, a.cost_tier, a.capabilities,
                       a.created_at, a.last_used,
                       bs.station_code, bs.station_name, bs.color as station_color
                FROM agents a
                LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
                LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
                WHERE a.id = %s
                """,
                (hub_id,),
            )
            agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Hub agent not found"}), 404
            for k in ["created_at", "last_used"]:
                if agent.get(k):
                    agent[k] = agent[k].isoformat()

            # Skills
            cur.execute(
                """
                SELECT skill_name, skill_category, proficiency_level, notes
                FROM agent_skills WHERE agent_id = %s
                ORDER BY proficiency_level DESC, skill_name
                """,
                (hub_id,),
            )
            skills = cur.fetchall()

            # Emotional state (latest)
            cur.execute(
                """
                SELECT current_mood, mood_intensity, stress_level, energy_level,
                       trigger_event, timestamp
                FROM agent_emotional_state WHERE agent_id = %s
                ORDER BY timestamp DESC LIMIT 1
                """,
                (hub_id,),
            )
            emotional = cur.fetchone()
            if emotional and emotional.get("timestamp"):
                emotional["timestamp"] = emotional["timestamp"].isoformat()

            # Performance (24h)
            cur.execute(
                """
                SELECT COUNT(*) as tasks_24h,
                       COUNT(*) FILTER (WHERE success = TRUE) as completed,
                       COUNT(*) FILTER (WHERE success = FALSE) as failed,
                       COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                FROM task_execution_log
                WHERE agent_id = %s AND created_at >= NOW() - INTERVAL '24 hours'
                """,
                (hub_id,),
            )
            perf = cur.fetchone()

            # Identity traits
            cur.execute(
                """
                SELECT identity_key, identity_value, confidence
                FROM agent_identity WHERE agent_id = %s ORDER BY identity_key
                """,
                (hub_id,),
            )
            identity = cur.fetchall()

            # Voice profile
            cur.execute(
                """
                SELECT profile_name, engine, language, speaker
                FROM agent_voice_profiles
                WHERE agent_id = %s AND is_active = true LIMIT 1
                """,
                (hub_id,),
            )
            voice = cur.fetchone()

            # Emotional history (last 10)
            cur.execute(
                """
                SELECT current_mood, mood_intensity, energy_level, stress_level,
                       trigger_event, timestamp
                FROM agent_emotional_state
                WHERE agent_id = %s ORDER BY timestamp DESC LIMIT 10
                """,
                (hub_id,),
            )
            emotional_history = cur.fetchall()
            for eh in emotional_history:
                if eh.get("timestamp"):
                    eh["timestamp"] = eh["timestamp"].isoformat()

            # Rest cycles (last 5)
            cur.execute(
                """
                SELECT rest_type, started_at, ended_at, reason,
                       stress_at_start, energy_at_start
                FROM agent_rest_cycles WHERE agent_id = %s
                ORDER BY started_at DESC LIMIT 5
                """,
                (hub_id,),
            )
            rest_cycles = cur.fetchall()
            for rc in rest_cycles:
                for k in ["started_at", "ended_at"]:
                    if rc.get(k):
                        rc[k] = rc[k].isoformat()

            # Memory highlights (top 5)
            cur.execute(
                """
                SELECT memory_type, content, importance_score, source_module, created_at
                FROM agent_memory
                WHERE agent_id = %s AND is_deleted = FALSE
                ORDER BY importance_score DESC NULLS LAST LIMIT 5
                """,
                (hub_id,),
            )
            memories = cur.fetchall()
            for m in memories:
                if m.get("created_at"):
                    m["created_at"] = m["created_at"].isoformat()

            return jsonify(
                {
                    "success": True,
                    "agent": dict(agent),
                    "skills": [dict(s) for s in skills],
                    "emotional_state": dict(emotional) if emotional else None,
                    "emotional_history": [dict(eh) for eh in emotional_history],
                    "identity": [dict(i) for i in identity],
                    "voice": dict(voice) if voice else None,
                    "rest_cycles": [dict(rc) for rc in rest_cycles],
                    "performance_24h": {
                        "tasks": perf["tasks_24h"],
                        "completed": perf["completed"],
                        "failed": perf["failed"],
                        "avg_duration_ms": round(float(perf["avg_duration_ms"]), 1),
                    },
                    "memories": [dict(m) for m in memories],
                }
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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


# ============================================================================
# AGENT RECOMMENDATIONS & CREW MANAGEMENT
# ============================================================================


def _add_single_agent_to_node(node_int_id, node_id_str, agent_id):
    """Add a single cloneable Bridge agent to a node's crew.

    Uses the same name pools and deterministic seeding as _generate_node_crew.
    Returns (success: bool, message: str, agent_data: dict or None).
    """
    with get_db_cursor(commit=True) as (conn, cur):
        # Fetch the Bridge agent — must be cloneable
        cur.execute(
            """
            SELECT id, name, title, model, system_prompt, capabilities,
                   array_agg(DISTINCT bs.station_code) as station_codes
            FROM agents a
            JOIN station_assignments sa ON sa.agent_id = a.id
            JOIN bridge_stations bs ON bs.id = sa.station_id
            WHERE a.id = %s AND a.is_cloneable = true AND a.status = 'active'
            GROUP BY a.id
            """,
            (agent_id,),
        )
        agent = cur.fetchone()
        if not agent:
            return False, "Agent not found or not cloneable", None

        # Check not already on this node
        cur.execute(
            "SELECT id FROM node_agents WHERE node_id = %s AND source_agent_id = %s",
            (node_int_id, agent_id),
        )
        if cur.fetchone():
            return False, "Agent already on this node", None

        # Get all used name combos to avoid dupes
        cur.execute("SELECT first_name, last_name FROM node_agents")
        used_names = {(r["first_name"], r["last_name"]) for r in cur.fetchall()}

        cur.execute("SELECT first_name, last_name FROM agents WHERE first_name IS NOT NULL")
        for r in cur.fetchall():
            used_names.add((r["first_name"], r["last_name"]))

        # Deterministic seed matching _generate_node_crew
        rng = random.Random(node_id_str)
        firsts = list(_STARSHIP_FIRST_NAMES)
        lasts = list(_STARSHIP_LAST_NAMES)
        rng.shuffle(firsts)
        rng.shuffle(lasts)

        # Find unused combo
        fname, lname = None, None
        fi, li = 0, 0
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
            RETURNING id, display_name, name, model, title, station_codes
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
        row = cur.fetchone()
        if not row:
            return False, "Insert conflict — agent may already exist", None

        return (
            True,
            "Agent added",
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "name": row["name"],
                "model": row["model"],
                "title": row["title"],
                "station_codes": row["station_codes"],
            },
        )


def get_agent_recommendations(node_int_id):
    """Score and rank cloneable agents for a node based on station overlap,
    job volume, success rate, and model efficiency.

    Returns dict with recommendations, station_suggestions, enabled_stations,
    and existing_crew_count.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        # 1. Node's enabled stations
        cur.execute(
            """
            SELECT bs.station_code
            FROM node_station_assignments nsa
            JOIN bridge_stations bs ON bs.id = nsa.station_id
            WHERE nsa.node_id = %s AND nsa.is_active = true
            """,
            (node_int_id,),
        )
        enabled_stations = {r["station_code"] for r in cur.fetchall()}

        # 2. Existing crew (source_agent_id set)
        cur.execute(
            """
            SELECT source_agent_id FROM node_agents
            WHERE node_id = %s AND source_agent_id IS NOT NULL
            """,
            (node_int_id,),
        )
        existing_crew_ids = {r["source_agent_id"] for r in cur.fetchall()}

        # 3. All cloneable agents with their stations
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.title, a.model,
                   array_agg(DISTINCT bs.station_code) as station_codes
            FROM agents a
            JOIN station_assignments sa ON sa.agent_id = a.id
            JOIN bridge_stations bs ON bs.id = sa.station_id
            WHERE a.is_cloneable = true AND a.status = 'active'
            GROUP BY a.id
            """
        )
        cloneable_agents = cur.fetchall()

        # 4. Job stats from last 30 days
        cur.execute(
            """
            SELECT agent_name,
                   COUNT(*) as job_count,
                   COUNT(*) FILTER (WHERE success = true) as success_count
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY agent_name
            """
        )
        job_stats = {}
        max_job_count = 1
        for r in cur.fetchall():
            job_stats[r["agent_name"]] = {
                "job_count": r["job_count"],
                "success_count": r["success_count"],
            }
            if r["job_count"] > max_job_count:
                max_job_count = r["job_count"]

    # Score each candidate
    recommendations = []
    for agent in cloneable_agents:
        if agent["id"] in existing_crew_ids:
            continue

        agent_stations = set(agent["station_codes"] or [])

        # station_match (40%): overlap with enabled stations
        if agent_stations:
            matching = len(agent_stations & enabled_stations)
            station_match = matching / len(agent_stations)
        else:
            station_match = 0.0

        # job_volume (30%): popularity
        stats = job_stats.get(agent["name"], {})
        jc = stats.get("job_count", 0)
        job_volume = jc / max_job_count if max_job_count > 0 else 0.0

        # success_rate (20%): reliability
        if jc > 0:
            success_rate = stats.get("success_count", 0) / jc
        else:
            success_rate = 0.5  # default

        # model_efficiency (10%): smaller = better
        model_name = (agent["model"] or "").lower()
        model_size = MODEL_SIZE_HINTS.get(model_name, None)
        if model_size is None:
            # Try partial match
            for hint_name, hint_size in MODEL_SIZE_HINTS.items():
                if hint_name in model_name or model_name in hint_name:
                    model_size = hint_size
                    break
        if model_size is None:
            model_size = 5.0  # assume mid-size
        # Invert: 0.3GB -> ~1.0, 47GB -> ~0.01
        model_efficiency = min(1.0, 1.0 / (1.0 + model_size * 0.2))

        score = station_match * 0.4 + job_volume * 0.3 + success_rate * 0.2 + model_efficiency * 0.1

        if score > 0.1:
            recommendations.append(
                {
                    "agent_id": agent["id"],
                    "name": agent["name"],
                    "display_name": agent["display_name"],
                    "title": agent["title"],
                    "model": agent["model"],
                    "station_codes": agent["station_codes"],
                    "score": round(score, 3),
                    "breakdown": {
                        "station_match": round(station_match, 3),
                        "job_volume": round(job_volume, 3),
                        "success_rate": round(success_rate, 3),
                        "model_efficiency": round(model_efficiency, 3),
                    },
                }
            )

    recommendations.sort(key=lambda r: r["score"], reverse=True)

    # Station suggestions: modules imply stations the node hasn't enabled
    station_suggestions = []
    all_suggested = set()
    for module, stations in MODULE_STATION_MAP.items():
        for st in stations:
            if st not in enabled_stations and st not in all_suggested:
                station_suggestions.append(
                    {
                        "station_code": st,
                        "reason": f"Recommended for {module} module",
                    }
                )
                all_suggested.add(st)

    return {
        "recommendations": recommendations,
        "station_suggestions": station_suggestions,
        "enabled_stations": sorted(enabled_stations),
        "existing_crew_count": len(existing_crew_ids),
    }


@starship_bp.route("/api/nodes/<int:node_id>/recommendations")
@login_required
def api_get_recommendations(node_id):
    """Get agent recommendations for a node."""
    try:
        result = get_agent_recommendations(node_id)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/nodes/<int:node_id>/agents/add", methods=["POST"])
@login_required
def api_add_agent_to_node(node_id):
    """Add a single cloneable agent to a node's crew."""
    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"success": False, "error": "agent_id required"}), 400

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id, node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404
            node_id_str = node["node_id"]

        ok, msg, agent_data = _add_single_agent_to_node(node_id, node_id_str, agent_id)
        if ok:
            return jsonify({"success": True, "message": msg, "agent": agent_data})
        else:
            return jsonify({"success": False, "error": msg}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>", methods=["DELETE"])
@login_required
def api_remove_agent_from_node(node_id, agent_id):
    """Remove an agent from a node's crew."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM node_agents WHERE node_id = %s AND id = %s RETURNING id",
                (node_id, agent_id),
            )
            deleted = cur.fetchone()
            if not deleted:
                return jsonify({"success": False, "error": "Agent not found on this node"}), 404
        return jsonify({"success": True, "message": "Agent removed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# OTA PUSH — AGENT CONFIG & CODE UPDATES
# ============================================================================


@starship_bp.route("/api/nodes/<int:node_id>/push-config", methods=["POST"])
@login_required
def api_push_agent_config(node_id):
    """Push current agent configuration to a node via mesh_sync_log."""
    import psycopg2

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Get the string node_id from remote_nodes
            cur.execute(
                "SELECT id, node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404
            node_id_str = node["node_id"]

            # Build crew manifest from node_agents
            cur.execute(
                """
                SELECT na.name, na.display_name, na.title, na.model,
                       na.system_prompt, na.capabilities, na.station_codes,
                       na.is_allowed, na.status
                FROM node_agents na
                WHERE na.node_id = %s AND na.status = 'active'
                ORDER BY na.display_name
                """,
                (node_id,),
            )
            agents = cur.fetchall()

            crew_manifest = []
            for a in agents:
                crew_manifest.append(
                    {
                        "name": a["name"],
                        "display_name": a["display_name"],
                        "title": a["title"],
                        "model": a["model"],
                        "system_prompt": a["system_prompt"],
                        "capabilities": a["capabilities"],
                        "station_codes": a["station_codes"],
                        "is_allowed": a["is_allowed"],
                        "status": a["status"],
                    }
                )

            payload = {"agents": crew_manifest, "agent_count": len(crew_manifest)}

            cur.execute(
                """
                INSERT INTO mesh_sync_log
                    (node_id, sync_type, payload, status, sent_at)
                VALUES (%s, 'agent_config', %s, 'sent', NOW())
                RETURNING id
                """,
                (node_id_str, json.dumps(payload)),
            )
            sync_row = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "sync_id": sync_row["id"],
                "agent_count": len(crew_manifest),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/nodes/<int:node_id>/pull-model", methods=["POST"])
@login_required
def api_pull_model(node_id):
    """Queue a model pull on a node via mesh_sync_log."""
    data = request.get_json()
    model_name = data.get("model_name") if data else None
    if not model_name:
        return jsonify({"success": False, "error": "model_name required"}), 400

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT id, node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            node_id_str = node["node_id"]

            cur.execute(
                """
                INSERT INTO mesh_sync_log
                    (node_id, sync_type, payload, status, sent_at)
                VALUES (%s, 'model_pull', %s, 'sent', NOW())
                RETURNING id
                """,
                (node_id_str, json.dumps({"model_name": model_name})),
            )
            sync_row = cur.fetchone()

        return jsonify({"success": True, "sync_id": sync_row["id"], "model": model_name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/nodes/<int:node_id>/push-update", methods=["POST"])
@login_required
def api_push_code_update(node_id):
    """Push a code update request to a node."""
    import psycopg2

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Get the string node_id
            cur.execute(
                "SELECT id, node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404
            node_id_str = node["node_id"]

            # Get latest deployment package
            cur.execute(
                """
                SELECT id, package_name, version_tag, file_path, created_at
                FROM deployment_packages
                ORDER BY created_at DESC LIMIT 1
                """
            )
            pkg = cur.fetchone()
            version = pkg["version_tag"] if pkg else LATEST_NODE_VERSION

            # Flag node for update
            cur.execute(
                """
                UPDATE remote_nodes
                SET update_requested = true, update_requested_at = NOW()
                WHERE id = %s
                """,
                (node_id,),
            )

            # Log to mesh_sync_log
            payload = {
                "version": version,
                "package_name": pkg["package_name"] if pkg else None,
                "file_path": pkg["file_path"] if pkg else None,
            }
            cur.execute(
                """
                INSERT INTO mesh_sync_log
                    (node_id, sync_type, payload, status, sent_at)
                VALUES (%s, 'code_update', %s, 'sent', NOW())
                RETURNING id
                """,
                (node_id_str, json.dumps(payload)),
            )
            sync_row = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "sync_id": sync_row["id"],
                "version": version,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@starship_bp.route("/api/nodes/<int:node_id>/sync-log")
@login_required
def api_get_sync_log(node_id):
    """Get recent sync log entries for a node."""
    try:
        with get_db_cursor() as (conn, cur):
            # Get the string node_id
            cur.execute(
                "SELECT node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404
            node_id_str = node["node_id"]

            cur.execute(
                """
                SELECT id, sync_type, status, sent_at, acknowledged_at,
                       error_message
                FROM mesh_sync_log
                WHERE node_id = %s
                ORDER BY sent_at DESC
                LIMIT 10
                """,
                (node_id_str,),
            )
            rows = cur.fetchall()

        logs = []
        for r in rows:
            logs.append(
                {
                    "id": r["id"],
                    "sync_type": r["sync_type"],
                    "status": r["status"],
                    "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                    "acknowledged_at": r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
                    "error_message": r["error_message"],
                }
            )

        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
