"""
A.R.C.H.I.E. BRIDGE Routes
==========================
Central command center for all AI/LLM operations.
Provides visual monitoring and station-based workflow.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-16
"""

import hashlib
import json
import os
import sys
import time
import logging
from collections import deque
from datetime import datetime
from typing import Dict, List
from flask import Blueprint, render_template, jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

logger = logging.getLogger(__name__)

bridge_bp = Blueprint("bridge", __name__, url_prefix="/tools/bridge")


# Database connection helper
def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# --- SSE Activity Event Queue ---
_activity_queue = deque(maxlen=200)


def push_agent_event(event_type, agent_id=None, data=None):
    """Push an event to the in-memory SSE queue and persist to DB."""
    evt = {
        "event_type": event_type,
        "agent_id": agent_id,
        "data": data or {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _activity_queue.appendleft(evt)
    # Persist to DB (fire-and-forget)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO agent_activity_events (event_type, agent_id, data) VALUES (%s, %s, %s)",
            (event_type, agent_id, json.dumps(data or {})),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Failed to persist activity event: %s", e)


# ============================================================================
# STATION DEFINITIONS (Database-driven - 10 stations)
# ============================================================================


def get_stations_from_db():
    """Get all stations from database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT station_code, station_name, full_name, description,
                   color, icon, default_llm, modules, position_row, position_order
            FROM bridge_stations
            WHERE is_active = TRUE
            ORDER BY position_row, position_order
        """
        )
        stations = cur.fetchall()
        cur.close()
        conn.close()
        return {s["station_code"]: dict(s) for s in stations}
    except Exception as e:
        logger.error(f"Error loading stations from DB: {e}")
        return {}


# Fallback stations if DB unavailable (6 consolidated stations — Project #91)
STATIONS_FALLBACK = {
    "COMMAND": {
        "station_name": "Command",
        "full_name": "A.R.C.H.I.E. Command & Dispatch",
        "color": "#00FFFF",
        "icon": "🎯",
        "default_llm": "dolphin3-8k:latest",
        "modules": ["archie_core", "archie_chat", "bridge", "team_management", "security_network"],
    },
    "ANALYTICS": {
        "station_name": "Analytics",
        "full_name": "Analytics & Intelligence Hub",
        "color": "#FF00FF",
        "icon": "📊",
        "default_llm": "qwen25-classify",
        "modules": ["consciousness", "knowledge_base", "analytics", "improvements_lab"],
    },
    "RESEARCH": {
        "station_name": "Research",
        "full_name": "Research & Knowledge Center",
        "color": "#8B5CF6",
        "icon": "🔬",
        "default_llm": "qwen3-coder-cpu:latest",
        "modules": ["obsidian_vault", "api_docs", "dev_hq"],
    },
    "OPERATIONS": {
        "station_name": "Operations",
        "full_name": "Operations & Communications Center",
        "color": "#FFAA00",
        "icon": "📡",
        "default_llm": "dolphin3-8k:latest",
        "modules": [
            "system_operations",
            "backup_manager",
            "saas_manager",
            "email_manager",
            "automations",
            "scheduler",
            "autonomy",
        ],
    },
    "ENGINEERING": {
        "station_name": "Engineering",
        "full_name": "Engineering & Development Lab",
        "color": "#0EA5E9",
        "icon": "⚙️",
        "default_llm": "qwen3-coder-cpu:latest",
        "modules": ["code_sentinel", "sandbox_manager", "project_manager", "website_studio", "store_builder"],
    },
    "CREATIVE": {
        "station_name": "Creative",
        "full_name": "Creative & Wellness Studio",
        "color": "#F472B6",
        "icon": "🎨",
        "default_llm": "dolphin3-8k:latest",
        "modules": [
            "content_studio",
            "social_media",
            "media_hub",
            "crm",
            "call_center",
            "invoicing",
            "fitness",
            "therapy",
            "doc",
        ],
    },
}

# LLM Connection definitions
LLM_CONNECTIONS = {
    "ollama_local": {
        "name": "Ollama (Local Hub)",
        "type": "local",
        "host": "host.docker.internal",
        "port": 11434,
        "models": [
            "dolphin3-8k:latest",
            "qwen3-coder-cpu:latest",
            "arctic-embed-cpu",
            "qwen25-classify",
            "minicpm-v-cpu",
        ],
        "cost": "FREE",
    },
    "claude_api": {
        "name": "Claude API",
        "type": "api",
        "host": "api.anthropic.com",
        "port": 443,
        "models": ["claude-sonnet-4", "claude-opus-4"],
        "cost": "PAID",
    },
    "openai_api": {
        "name": "OpenAI API",
        "type": "api",
        "host": "api.openai.com",
        "port": 443,
        "models": ["gpt-4", "gpt-4-turbo", "gpt-4o"],
        "cost": "PAID",
    },
    "grok_api": {
        "name": "Grok API",
        "type": "api",
        "host": "api.x.ai",
        "port": 443,
        "models": ["grok-beta"],
        "cost": "PAID",
    },
    "gemini_api": {
        "name": "Gemini API",
        "type": "api",
        "host": "generativelanguage.googleapis.com",
        "port": 443,
        "models": ["gemini-2.0-flash"],
        "cost": "PAID",
    },
}


# ============================================================================
# MAIN BRIDGE PAGE
# ============================================================================


@bridge_bp.route("/")
@login_required
def bridge_dashboard():
    """Render the main Bridge command center"""
    deployment_mode = os.getenv("DEPLOYMENT_MODE", "hub")
    if deployment_mode == "business_node":
        return render_template(
            "tools/bridge_hub.html",
            deployment_mode=deployment_mode,
            node_id=os.getenv("NODE_ID", ""),
            hub_url=os.getenv("HUB_URL", ""),
        )
    else:
        # Hub and default: full command center with stations, agents, crew + mesh
        return render_template("tools/bridge.html", deployment_mode=deployment_mode)


# ============================================================================
# BRIDGE STATS API
# ============================================================================


@bridge_bp.route("/api/stats")
def get_bridge_stats():
    """Get overall Bridge statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get active agents count
        cur.execute(
            """
            SELECT COUNT(*) as active_agents
            FROM agents
            WHERE status = 'active'
        """
        )
        agent_stats = cur.fetchone()

        # Get recent token usage (last 24h)
        cur.execute(
            """
            SELECT
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                COUNT(*) as total_requests
            FROM token_usage_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """
        )
        token_stats = cur.fetchone()

        # Get A.R.C.H.I.E.'s emotional state
        cur.execute(
            """
            SELECT current_mood, mood_intensity, relationship_strength
            FROM archie_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        emotional_state = cur.fetchone() or {
            "current_mood": "supportive",
            "mood_intensity": 0.85,
            "relationship_strength": 0.90,
        }

        cur.close()
        conn.close()

        # Calculate system load (simulated for now)
        import random

        system_load = random.randint(25, 45)

        return jsonify(
            {
                "success": True,
                "stats": {
                    "llm_status": {"online": 5, "total": 6},
                    "active_requests": (token_stats["total_requests"] if token_stats else 0),
                    "system_load": system_load,
                    "active_agents": agent_stats["active_agents"] if agent_stats else 0,
                    "tokens_24h": token_stats["total_tokens"] if token_stats else 0,
                },
                "archie": {
                    "mood": emotional_state["current_mood"],
                    "energy": (
                        float(emotional_state["mood_intensity"]) if emotional_state.get("mood_intensity") else 0.85
                    ),
                    "relationship": (
                        float(emotional_state["relationship_strength"])
                        if emotional_state.get("relationship_strength")
                        else 0.90
                    ),
                    "status": "Active",
                },
                "captain": {"name": "Kytran", "role": "Admin", "status": "On Duty"},
            }
        )

    except Exception as e:
        logger.error(f"Error getting bridge stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATIONS API
# ============================================================================


@bridge_bp.route("/api/stations")
def get_stations():
    """Get all station configurations from database (10 stations)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get all stations from database
        cur.execute(
            """
            SELECT id, station_code, station_name, full_name, description,
                   color, icon, default_llm, modules, position_row, position_order
            FROM bridge_stations
            WHERE is_active = TRUE
            ORDER BY position_row, position_order
        """
        )
        db_stations = cur.fetchall()

        stations_data = []
        for station in db_stations:
            # Get assigned agents for this station (include full name fields)
            cur.execute(
                """
                SELECT a.id, a.name, a.first_name, a.last_name, a.title,
                       a.avatar_url, a.model, sa.assignment_type
                FROM station_assignments sa
                JOIN agents a ON sa.agent_id = a.id
                WHERE sa.station_id = %s AND sa.is_active = TRUE AND a.status = 'active'
                ORDER BY sa.priority
            """,
                (station["id"],),
            )
            assigned_agents = cur.fetchall()

            # Get agent count by type
            primary_agents = [a for a in assigned_agents if a["assignment_type"] == "primary"]
            backup_agents = [a for a in assigned_agents if a["assignment_type"] == "backup"]

            stations_data.append(
                {
                    "id": station["id"],
                    "code": station["station_code"],
                    "name": station["station_name"],
                    "full_name": station["full_name"],
                    "description": station["description"],
                    "color": station["color"],
                    "icon": station["icon"],
                    "default_llm": station["default_llm"],
                    "modules": station["modules"] or [],
                    "position_row": station["position_row"],
                    "position_order": station["position_order"],
                    "assigned_agents": assigned_agents,
                    "primary_count": len(primary_agents),
                    "backup_count": len(backup_agents),
                    "total_agents": len(assigned_agents),
                    "status": "active",
                }
            )

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stations": stations_data,
                "total_stations": len(stations_data),
            }
        )

    except Exception as e:
        logger.error(f"Error getting stations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>")
def get_station_detail(station_code):
    """Get detailed info for a specific station"""
    station_code = station_code.upper()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get station from database
        cur.execute(
            """
            SELECT id, station_code, station_name, full_name, description,
                   color, icon, default_llm, modules, position_row, position_order
            FROM bridge_stations
            WHERE station_code = %s AND is_active = TRUE
        """,
            (station_code,),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": f"Station {station_code} not found"}),
                404,
            )

        # Get assigned agents with full details
        cur.execute(
            """
            SELECT a.id, a.name, a.first_name, a.last_name, a.title, a.avatar_url,
                   a.model, a.department, a.tier, a.status, a.worker_type,
                   sa.assignment_type, sa.shift_preference, sa.priority
            FROM station_assignments sa
            JOIN agents a ON sa.agent_id = a.id
            WHERE sa.station_id = %s AND sa.is_active = TRUE
            ORDER BY sa.priority
        """,
            (station["id"],),
        )
        assigned_agents = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "station": {
                    "id": station["id"],
                    "code": station["station_code"],
                    "name": station["station_name"],
                    "full_name": station["full_name"],
                    "description": station["description"],
                    "color": station["color"],
                    "icon": station["icon"],
                    "default_llm": station["default_llm"],
                    "modules": station["modules"] or [],
                    "assigned_agents": assigned_agents,
                    "total_agents": len(assigned_agents),
                },
            }
        )

    except Exception as e:
        logger.error(f"Error getting station detail: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LLM CONNECTIONS API
# ============================================================================


@bridge_bp.route("/api/connections")
def get_llm_connections():
    """Get all LLM connection statuses"""
    connections = []

    for conn_id, conn_info in LLM_CONNECTIONS.items():
        # Check if connection is available
        status = "unknown"
        latency = None

        if conn_info["type"] == "local":
            # Check Ollama
            status, latency = check_ollama_status(conn_info["host"], conn_info["port"])
        elif conn_info["type"] == "api":
            # Check if API key is configured
            status = check_api_key_status(conn_id)

        connections.append(
            {
                "id": conn_id,
                "name": conn_info["name"],
                "type": conn_info["type"],
                "host": conn_info["host"],
                "port": conn_info["port"],
                "models": conn_info["models"],
                "cost": conn_info["cost"],
                "status": status,
                "latency_ms": latency,
            }
        )

    return jsonify({"success": True, "connections": connections})


@bridge_bp.route("/api/connections/<connection_id>/health")
def check_connection_health(connection_id):
    """Check health of a specific LLM connection"""
    if connection_id not in LLM_CONNECTIONS:
        return (
            jsonify({"success": False, "error": f"Connection {connection_id} not found"}),
            404,
        )

    conn_info = LLM_CONNECTIONS[connection_id]

    if conn_info["type"] == "local":
        status, latency = check_ollama_status(conn_info["host"], conn_info["port"])
        available_models = get_ollama_models(conn_info["host"], conn_info["port"]) if status == "online" else []
    else:
        status = check_api_key_status(connection_id)
        latency = None
        available_models = conn_info["models"] if status == "configured" else []

    return jsonify(
        {
            "success": True,
            "connection": {
                "id": connection_id,
                "name": conn_info["name"],
                "status": status,
                "latency_ms": latency,
                "available_models": available_models,
            },
        }
    )


def check_ollama_status(host, port):
    """Check if Ollama is running and responsive"""
    try:
        import time

        start = time.time()
        response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
        latency = int((time.time() - start) * 1000)

        if response.status_code == 200:
            return "online", latency
        else:
            return "degraded", latency
    except requests.exceptions.Timeout:
        return "timeout", None
    except requests.exceptions.ConnectionError:
        return "offline", None
    except Exception as e:
        logger.error(f"Error checking Ollama: {e}")
        return "error", None


def get_ollama_models(host, port):
    """Get list of available Ollama models"""
    try:
        response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
    except Exception as e:
        logger.error(f"Error getting Ollama models: {e}")
    return []


def check_api_key_status(connection_id):
    """Check if API key is configured for a connection"""
    key_mapping = {
        "claude_api": "ANTHROPIC_API_KEY",
        "openai_api": "OPENAI_API_KEY",
        "grok_api": "GROK_API_KEY",
        "gemini_api": "GOOGLE_API_KEY",
    }

    env_var = key_mapping.get(connection_id)
    if env_var and os.getenv(env_var):
        return "configured"
    return "not_configured"


# ============================================================================
# AGENTS API (for station assignment)
# ============================================================================


@bridge_bp.route("/api/agents")
def get_bridge_agents():
    """Get agents available for station assignment"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id, name, title, department, status,
                avatar_url, model, system_prompt, tier,
                capabilities
            FROM agents
            WHERE status IN ('active', 'idle', 'busy')
            ORDER BY name
        """
        )
        agents = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": agents})

    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents", methods=["POST"])
@login_required
def create_agent():
    """Create a new agent"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    model = data.get("model")
    if not model:
        return jsonify({"success": False, "error": "Model is required"}), 400

    first_name = data.get("first_name") or model.split(":")[0].replace("-", " ").title()
    last_name = data.get("last_name", "Agent")
    title = data.get("title", f"{model} Specialist")
    department = data.get("department", "AI Operations")
    worker_type = data.get("worker_type", "ai")
    bio = data.get("bio", f"AI agent powered by {model}.")
    system_prompt = data.get(
        "system_prompt",
        f"You are {first_name}, an AI assistant powered by {model}.",
    )
    temperature = data.get("temperature", 0.7)
    max_tokens = data.get("max_tokens", 4096)
    capabilities = data.get("capabilities")
    if isinstance(capabilities, list):
        capabilities = json.dumps(capabilities)
    name = f"{first_name} {last_name}".strip()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO agents (
                name, first_name, last_name, title, department, worker_type,
                model, temperature, max_tokens, system_prompt, bio,
                status, capabilities, created_at, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,NOW(),NOW())
            RETURNING id, name, first_name, last_name, model
        """,
            (
                name,
                first_name,
                last_name,
                title,
                department,
                worker_type,
                model,
                temperature,
                max_tokens,
                system_prompt,
                bio,
                capabilities,
            ),
        )
        agent = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "agent": dict(agent)})
    except Exception as e:
        logger.error("create_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>", methods=["PUT", "PATCH"])
@login_required
def update_agent(agent_id):
    """Update agent profile fields"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data"}), 400

    editable = [
        "name",
        "first_name",
        "last_name",
        "title",
        "department",
        "bio",
        "model",
        "system_prompt",
        "temperature",
        "max_tokens",
        "pronouns",
        "worker_type",
    ]
    sets = []
    params = []
    for field in editable:
        if field in data:
            sets.append(f"{field} = %s")
            params.append(data[field])

    if not sets:
        return jsonify({"success": False, "error": "No valid fields"}), 400

    sets.append("updated_at = NOW()")
    params.append(agent_id)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"UPDATE agents SET {', '.join(sets)} WHERE id = %s RETURNING id, name, first_name, last_name, model, status",
            params,
        )
        agent = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404
        return jsonify({"success": True, "agent": dict(agent)})
    except Exception as e:
        logger.error("update_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
@login_required
def delete_agent(agent_id):
    """Delete an agent (clears FK references first)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name FROM agents WHERE id = %s", (agent_id,))
        agent = cur.fetchone()
        if not agent:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Clear FK references
        cur.execute(
            "UPDATE unified_projects SET created_by_agent_id = NULL WHERE created_by_agent_id = %s",
            (agent_id,),
        )
        cur.execute(
            "UPDATE unified_tasks SET assigned_agent_id = NULL WHERE assigned_agent_id = %s",
            (agent_id,),
        )
        cur.execute(
            "UPDATE unified_tasks SET created_by_agent_id = NULL WHERE created_by_agent_id = %s",
            (agent_id,),
        )
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": f"Agent '{agent['name']}' deleted"})
    except Exception as e:
        logger.error("delete_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/toggle", methods=["POST"])
@login_required
def toggle_agent(agent_id):
    """Toggle agent active/paused"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE agents
            SET status = CASE WHEN status = 'active' THEN 'paused' ELSE 'active' END,
                updated_at = NOW()
            WHERE id = %s RETURNING status
        """,
            (agent_id,),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not result:
            return jsonify({"success": False, "error": "Agent not found"}), 404
        return jsonify({"success": True, "status": result[0]})
    except Exception as e:
        logger.error("toggle_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/skills", methods=["GET"])
@login_required
def get_agent_skills(agent_id):
    """Get all skills for an agent"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, skill_name, skill_category, proficiency_level, notes,
                   created_at, updated_at
            FROM agent_skills WHERE agent_id = %s
            ORDER BY proficiency_level DESC, skill_name
        """,
            (agent_id,),
        )
        skills = cur.fetchall()
        cur.close()
        conn.close()
        for s in skills:
            for k in ["created_at", "updated_at"]:
                if s.get(k):
                    s[k] = s[k].isoformat()
        return jsonify({"success": True, "skills": skills})
    except Exception as e:
        logger.error("get_agent_skills error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/skills", methods=["POST"])
@login_required
def add_agent_skill(agent_id):
    """Add or upsert a skill for an agent"""
    import uuid as _uuid

    data = request.get_json()
    skill_name = data.get("skill_name")
    if not skill_name:
        return jsonify({"success": False, "error": "skill_name required"}), 400

    proficiency = max(1, min(5, int(data.get("proficiency_level", 3))))
    category = data.get("skill_category", "general")
    notes = data.get("notes", "")

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO agent_skills
                (id, agent_id, skill_name, skill_category, proficiency_level, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (agent_id, skill_name) DO UPDATE SET
                proficiency_level = EXCLUDED.proficiency_level,
                skill_category = EXCLUDED.skill_category,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            RETURNING id, skill_name, skill_category, proficiency_level
        """,
            (str(_uuid.uuid4()), agent_id, skill_name.lower().replace(" ", "_"), category, proficiency, notes),
        )
        skill = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "skill": dict(skill)})
    except Exception as e:
        logger.error("add_agent_skill error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/skills/<skill_id>", methods=["DELETE"])
@login_required
def delete_agent_skill(agent_id, skill_id):
    """Remove a skill from an agent"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM agent_skills WHERE id = %s AND agent_id = %s RETURNING skill_name",
            (skill_id, agent_id),
        )
        result = cur.fetchone()
        if not result:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Skill not found"}), 404
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": f"Skill '{result[0]}' removed"})
    except Exception as e:
        logger.error("delete_agent_skill error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/assign-station", methods=["POST"])
def assign_agent_to_station(agent_id):
    """Assign an agent to a station"""
    data = request.get_json() or {}
    station_code = data.get("station_code")
    assignment_type = data.get("assignment_type", "primary")  # primary, backup, relief
    shift_preference = data.get("shift_preference", "any")  # alpha, beta, gamma, any
    priority = data.get("priority", 10)
    notes = data.get("notes", "")

    if not station_code:
        return jsonify({"success": False, "error": "station_code required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get station ID from code
        cur.execute(
            "SELECT id FROM bridge_stations WHERE station_code = %s",
            (station_code.upper(),),
        )
        station = cur.fetchone()
        if not station:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": f"Station {station_code} not found"}),
                404,
            )

        station_id = station["id"]

        # Check if assignment already exists
        cur.execute(
            """
            SELECT id FROM station_assignments
            WHERE station_id = %s AND agent_id = %s
        """,
            (station_id, agent_id),
        )
        existing = cur.fetchone()

        if existing:
            # Update existing assignment
            cur.execute(
                """
                UPDATE station_assignments
                SET assignment_type = %s, shift_preference = %s, priority = %s,
                    notes = %s, is_active = TRUE, assigned_at = NOW()
                WHERE id = %s
                RETURNING id
            """,
                (assignment_type, shift_preference, priority, notes, existing["id"]),
            )
        else:
            # Create new assignment
            cur.execute(
                """
                INSERT INTO station_assignments
                (station_id, agent_id, assignment_type, shift_preference, priority, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    station_id,
                    agent_id,
                    assignment_type,
                    shift_preference,
                    priority,
                    notes,
                ),
            )

        assignment_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "assignment_id": assignment_id,
                "message": f"Agent assigned to {station_code} as {assignment_type}",
            }
        )

    except Exception as e:
        logger.error(f"Error assigning agent: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/unassign-station", methods=["POST"])
def unassign_agent_from_station(agent_id):
    """Remove an agent from a station"""
    data = request.get_json() or {}
    station_code = data.get("station_code")

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if station_code:
            # Unassign from specific station
            cur.execute(
                """
                UPDATE station_assignments sa
                SET is_active = FALSE
                FROM bridge_stations bs
                WHERE sa.station_id = bs.id
                  AND bs.station_code = %s
                  AND sa.agent_id = %s
            """,
                (station_code.upper(), agent_id),
            )
        else:
            # Unassign from all stations
            cur.execute(
                """
                UPDATE station_assignments
                SET is_active = FALSE
                WHERE agent_id = %s
            """,
                (agent_id,),
            )

        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": f'Agent unassigned from {station_code if station_code else "all stations"}',
                "affected": affected,
            }
        )

    except Exception as e:
        logger.error(f"Error unassigning agent: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATION ASSIGNMENTS API (Phase 28)
# ============================================================================


@bridge_bp.route("/api/stations/assignments")
def get_all_station_assignments():
    """Get all station assignments grouped by station"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                bs.id as station_id,
                bs.station_code,
                bs.station_name,
                bs.color,
                bs.icon,
                json_agg(
                    json_build_object(
                        'assignment_id', sa.id,
                        'agent_id', a.id,
                        'agent_name', a.name,
                        'first_name', a.first_name,
                        'last_name', a.last_name,
                        'agent_title', a.title,
                        'agent_avatar', a.avatar_url,
                        'agent_model', a.model,
                        'agent_status', a.status,
                        'assignment_type', sa.assignment_type,
                        'role_type', COALESCE(sa.role_type, 'standard'),
                        'is_fixed', COALESCE(sa.is_fixed, FALSE),
                        'department', a.department,
                        'shift_preference', sa.shift_preference,
                        'priority', sa.priority,
                        'assigned_at', sa.assigned_at
                    ) ORDER BY sa.is_fixed DESC, sa.priority, sa.assignment_type
                ) FILTER (WHERE sa.id IS NOT NULL) as agents
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
            LEFT JOIN agents a ON sa.agent_id = a.id
            WHERE bs.is_active = TRUE
            GROUP BY bs.id, bs.station_code, bs.station_name, bs.color, bs.icon, bs.position_row, bs.position_order
            ORDER BY bs.position_row, bs.position_order
        """
        )
        stations = cur.fetchall()

        cur.close()
        conn.close()

        # Convert datetime in nested JSON
        for station in stations:
            if station["agents"]:
                for agent in station["agents"]:
                    if agent.get("assigned_at"):
                        agent["assigned_at"] = (
                            agent["assigned_at"].isoformat()
                            if hasattr(agent["assigned_at"], "isoformat")
                            else str(agent["assigned_at"])
                        )

        return jsonify({"success": True, "stations": stations})

    except Exception as e:
        logger.error(f"Error getting assignments: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/unassigned-agents")
def get_unassigned_agents():
    """Get agents not assigned to any station"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT a.id, a.name, a.title, a.department, a.status,
                   a.avatar_url, a.model, a.tier, a.capabilities
            FROM agents a
            WHERE a.status IN ('active', 'idle', 'busy')
              AND NOT EXISTS (
                  SELECT 1 FROM station_assignments sa
                  WHERE sa.agent_id = a.id AND sa.is_active = TRUE
              )
            ORDER BY a.name
        """
        )
        agents = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": agents, "count": len(agents)})

    except Exception as e:
        logger.error(f"Error getting unassigned agents: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/config", methods=["GET"])
def get_station_config(station_code):
    """Get station configuration"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, station_code, station_name, full_name, description,
                   color, icon, default_llm, modules, position_row, position_order,
                   is_active, created_at, updated_at
            FROM bridge_stations
            WHERE station_code = %s
        """,
            (station_code.upper(),),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Station not found"}), 404

        cur.close()
        conn.close()

        # Convert datetime
        for key in ["created_at", "updated_at"]:
            if station.get(key):
                station[key] = station[key].isoformat()

        return jsonify({"success": True, "station": station})

    except Exception as e:
        logger.error(f"Error getting station config: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/config", methods=["PUT"])
def update_station_config(station_code):
    """Update station configuration"""
    data = request.get_json() or {}

    allowed_fields = [
        "station_name",
        "full_name",
        "description",
        "color",
        "icon",
        "default_llm",
        "modules",
        "position_row",
        "position_order",
        "is_active",
    ]

    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"success": False, "error": "No valid fields to update"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build dynamic update query
        set_clauses = [f"{k} = %s" for k in updates.keys()]
        values = list(updates.values())
        values.append(station_code.upper())

        cur.execute(
            f"""
            UPDATE bridge_stations
            SET {', '.join(set_clauses)}, updated_at = NOW()
            WHERE station_code = %s
            RETURNING id, station_code, station_name
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not updated:
            return jsonify({"success": False, "error": "Station not found"}), 404

        return jsonify(
            {
                "success": True,
                "station": updated,
                "message": f"Station {station_code} updated",
            }
        )

    except Exception as e:
        logger.error(f"Error updating station: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/reorder", methods=["POST"])
def reorder_stations():
    """Reorder stations (drag-and-drop support)"""
    data = request.get_json() or {}
    order = data.get("order", [])  # List of {station_code, position_row, position_order}

    if not order:
        return jsonify({"success": False, "error": "order list required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        for item in order:
            cur.execute(
                """
                UPDATE bridge_stations
                SET position_row = %s, position_order = %s, updated_at = NOW()
                WHERE station_code = %s
            """,
                (
                    item.get("position_row", 0),
                    item.get("position_order", 0),
                    item["station_code"].upper(),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": f"Reordered {len(order)} stations"})

    except Exception as e:
        logger.error(f"Error reordering stations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
def delete_assignment(assignment_id):
    """Delete a station assignment"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM station_assignments WHERE id = %s RETURNING id
        """,
            (assignment_id,),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Assignment not found"}), 404

        return jsonify({"success": True, "message": "Assignment deleted"})

    except Exception as e:
        logger.error(f"Error deleting assignment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
def update_assignment(assignment_id):
    """Update a station assignment"""
    data = request.get_json() or {}

    allowed_fields = [
        "assignment_type",
        "shift_preference",
        "priority",
        "notes",
        "is_active",
    ]
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"success": False, "error": "No valid fields to update"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        set_clauses = [f"{k} = %s" for k in updates.keys()]
        values = list(updates.values())
        values.append(assignment_id)

        cur.execute(
            f"""
            UPDATE station_assignments
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, station_id, agent_id, assignment_type
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not updated:
            return jsonify({"success": False, "error": "Assignment not found"}), 404

        return jsonify({"success": True, "assignment": updated})

    except Exception as e:
        logger.error(f"Error updating assignment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ADDITIONAL SUPPORT REQUEST API
# ============================================================================


@bridge_bp.route("/api/stations/<station_code>/request-support", methods=["POST"])
def request_station_support(station_code):
    """
    Handle additional support requests from modules.

    When a module needs capability beyond its assigned team (primary + secondary),
    it requests support here. The Bridge checks the additional_support slot and
    Archie HR determines if support can be allocated.

    Flow:
    1. Module requests support with task_type and capability_needed
    2. Bridge checks if additional_support slot is available
    3. If slot is empty, Bridge/Archie HR finds a suitable agent
    4. Agent is temporarily assigned to additional_support slot
    5. Module receives the support agent details

    Workload tracking ensures AI compliance standards (no overworking agents).
    """
    data = request.get_json() or {}
    task_type = data.get("task_type", "general")
    capability_needed = data.get("capability_needed", "general capability")
    requesting_module = data.get("requesting_module", "unknown")

    logger.info(f"Bridge: Support request from {requesting_module} - {task_type} needs {capability_needed}")

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Step 1: Get station info
        cur.execute(
            """
            SELECT id, station_name FROM bridge_stations
            WHERE station_code = %s AND is_active = TRUE
        """,
            (station_code.upper(),),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "message": f"Station {station_code} not found"}),
                404,
            )

        # Step 2: Check if additional_support slot is already filled
        cur.execute(
            """
            SELECT a.id, a.name, a.model, a.tier, a.title
            FROM station_assignments sa
            JOIN agents a ON sa.agent_id = a.id
            WHERE sa.station_id = %s
            AND sa.assignment_type = 'additional_support'
            AND sa.is_active = TRUE
            AND a.status = 'active'
        """,
            (station["id"],),
        )
        existing_support = cur.fetchone()

        if existing_support:
            # Support slot already filled - return existing support agent
            cur.close()
            conn.close()
            logger.info(f"Bridge: Support slot already filled with {existing_support['name']}")
            return jsonify(
                {
                    "success": True,
                    "agent": dict(existing_support),
                    "message": "Support agent already assigned",
                    "slot_status": "occupied",
                }
            )

        # Step 3: Find a suitable agent for the requested capability
        # This is where Archie HR logic would go in the future
        # For now, we look for fast coders not already assigned to this station

        # Define capability keywords and their model mappings
        # Bridge interprets the capability_needed string to find appropriate agents
        fast_coder_models = [
            "qwen25-classify",
            "dolphin3-8k:latest",
            "qwen3-coder-cpu:latest",
        ]  # noqa: F841

        # Determine what kind of agent is needed based on capability description
        capability_lower = capability_needed.lower() if capability_needed else ""
        target_models = []

        if "fast" in capability_lower or "speed" in capability_lower or "batch" in capability_lower:
            # Need a fast classifier/tagger
            target_models = ["qwen25-classify", "dolphin3-8k:latest"]
            logger.info(f"Bridge: Looking for fast models: {target_models}")
        elif "thorough" in capability_lower or "security" in capability_lower or "deep" in capability_lower:
            # Need a thorough/security agent - will use tier-based search
            target_models = []
            logger.info("Bridge: Looking for high-tier agent")

        # Find available agent with required capability
        if target_models:
            model_placeholders = ",".join(["%s"] * len(target_models))
            cur.execute(
                f"""
                SELECT a.id, a.name, a.model, a.tier, a.title, a.avatar_url
                FROM agents a
                WHERE a.status = 'active'
                AND a.model IN ({model_placeholders})
                AND a.id NOT IN (
                    SELECT agent_id FROM station_assignments
                    WHERE station_id = %s AND is_active = TRUE
                )
                ORDER BY a.tier DESC
                LIMIT 1
            """,
                (*target_models, station["id"]),
            )
        else:
            # For tier-based requirements, find high-tier agents
            cur.execute(
                """
                SELECT a.id, a.name, a.model, a.tier, a.title, a.avatar_url
                FROM agents a
                WHERE a.status = 'active'
                AND a.tier >= 2
                AND a.id NOT IN (
                    SELECT agent_id FROM station_assignments
                    WHERE station_id = %s AND is_active = TRUE
                )
                ORDER BY a.tier DESC
                LIMIT 1
            """,
                (station["id"],),
            )

        candidate = cur.fetchone()

        if not candidate:
            cur.close()
            conn.close()
            logger.info(f"Bridge: No suitable agent available for {capability_needed}")
            return jsonify(
                {
                    "success": False,
                    "message": f"No agent available with {capability_needed}",
                    "slot_status": "no_candidates",
                }
            )

        # Step 4: Check workload compliance (simplified for now)
        # TODO: Full workload tracking for AI compliance
        cur.execute(
            """
            SELECT COUNT(*) as assignment_count
            FROM station_assignments
            WHERE agent_id = %s AND is_active = TRUE
        """,
            (candidate["id"],),
        )
        workload = cur.fetchone()

        if workload["assignment_count"] >= 3:
            cur.close()
            conn.close()
            logger.info(f"Bridge: {candidate['name']} at workload limit ({workload['assignment_count']} assignments)")
            return jsonify(
                {
                    "success": False,
                    "message": f"{candidate['name']} is at workload capacity",
                    "slot_status": "workload_limit",
                }
            )

        # Step 5: Assign to additional_support slot
        cur.execute(
            """
            INSERT INTO station_assignments
            (station_id, agent_id, assignment_type, priority, notes, is_active)
            VALUES (%s, %s, 'additional_support', 99, %s, TRUE)
            RETURNING id
        """,
            (
                station["id"],
                candidate["id"],
                f"Support for {requesting_module}: {task_type}",
            ),
        )

        assignment = cur.fetchone()
        conn.commit()

        logger.info(f"Bridge: Assigned {candidate['name']} as additional_support to {station['station_name']}")

        # Add assignment type to candidate for caller
        candidate_dict = dict(candidate)
        candidate_dict["assignment_type"] = "additional_support"
        candidate_dict["assignment_id"] = assignment["id"]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "agent": candidate_dict,
                "message": f"{candidate['name']} assigned as additional support",
                "slot_status": "assigned",
            }
        )

    except Exception as e:
        logger.error(f"Bridge: Error processing support request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/release-support", methods=["POST"])
def release_station_support(station_code):
    """
    Release an agent from the additional_support slot.

    Called when module completes work or no longer needs support.
    This frees the agent for other stations.
    """
    data = request.get_json() or {}
    agent_id = data.get("agent_id")

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get station
        cur.execute(
            """
            SELECT id FROM bridge_stations WHERE station_code = %s
        """,
            (station_code.upper(),),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Station not found"}), 404

        # Remove from additional_support slot
        if agent_id:
            cur.execute(
                """
                DELETE FROM station_assignments
                WHERE station_id = %s AND agent_id = %s AND assignment_type = 'additional_support'
                RETURNING id
            """,
                (station["id"], agent_id),
            )
        else:
            # Release all support assignments for this station
            cur.execute(
                """
                DELETE FROM station_assignments
                WHERE station_id = %s AND assignment_type = 'additional_support'
                RETURNING id
            """,
                (station["id"],),
            )

        deleted = cur.fetchall()
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Bridge: Released {len(deleted)} support assignment(s) from {station_code}")

        return jsonify(
            {
                "success": True,
                "released_count": len(deleted),
                "message": f"Released {len(deleted)} support assignment(s)",
            }
        )

    except Exception as e:
        logger.error(f"Bridge: Error releasing support: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TRAINING ROOM API - Phase 39
# ============================================================================


@bridge_bp.route("/api/training")
@login_required
def get_training_agents():
    """Get agents currently in training"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                a.avatar_url,
                a.department,
                ta.id as training_id,
                ta.skill_name,
                ta.skill_category,
                ta.current_proficiency,
                ta.target_proficiency,
                ta.status as training_status,
                ta.started_at as training_started,
                EXTRACT(EPOCH FROM (NOW() - ta.started_at)) / 3600 as hours_training,
                ta.notes as training_notes
            FROM training_assignments ta
            JOIN agents a ON ta.agent_id = a.id
            WHERE ta.status IN ('pending', 'in_progress')
            AND a.status = 'active'
            ORDER BY ta.started_at DESC
        """
        )
        agents = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": agents})

    except Exception as e:
        logger.error(f"Error loading training agents: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/skills")
@login_required
def get_training_skills():
    """Get available skills for training assignment"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT DISTINCT skill_name as name, skill_category as category
            FROM agent_skills
            ORDER BY skill_category, skill_name
        """
        )
        skills = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "skills": skills})

    except Exception as e:
        logger.error(f"Error loading skills: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/assign", methods=["POST"])
@login_required
def assign_training():
    """Assign an agent to skill training"""
    try:
        data = request.get_json()
        agent_id = data.get("agent_id")
        skill_name = data.get("skill_name")
        target_proficiency = data.get("target_proficiency", 3)
        notes = data.get("notes", "")

        if not agent_id or not skill_name:
            return (
                jsonify({"success": False, "error": "Agent ID and skill name required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get skill category
        cur.execute(
            "SELECT DISTINCT skill_category FROM agent_skills WHERE skill_name = %s LIMIT 1",
            (skill_name,),
        )
        skill_row = cur.fetchone()
        skill_category = skill_row["skill_category"] if skill_row else "General"

        # Get current proficiency if exists
        cur.execute(
            """
            SELECT proficiency_level FROM agent_skills
            WHERE agent_id = %s AND skill_name = %s
        """,
            (agent_id, skill_name),
        )
        existing = cur.fetchone()
        current_proficiency = existing["proficiency_level"] if existing else 1

        # Remove from station assignment if any
        cur.execute(
            "UPDATE station_assignments SET is_active = FALSE WHERE agent_id = %s AND is_active = TRUE",
            (agent_id,),
        )

        # Insert training assignment
        cur.execute(
            """
            INSERT INTO training_assignments
            (agent_id, skill_name, skill_category, target_proficiency, current_proficiency, status, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, 'in_progress', %s, %s)
            RETURNING id
        """,
            (
                agent_id,
                skill_name,
                skill_category,
                target_proficiency,
                current_proficiency,
                notes,
                current_user.id if current_user else None,
            ),
        )

        training_id = cur.fetchone()["id"]

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "training_id": training_id,
                "message": f"Agent assigned to {skill_name} training",
            }
        )

    except Exception as e:
        logger.error(f"Error assigning training: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/<int:training_id>/complete", methods=["POST"])
@login_required
def complete_training(training_id):
    """Complete or cancel a training assignment"""
    try:
        data = request.get_json()
        status = data.get("status", "completed")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get training details
        cur.execute(
            "SELECT agent_id, skill_name, target_proficiency FROM training_assignments WHERE id = %s",
            (training_id,),
        )
        training = cur.fetchone()

        if not training:
            return jsonify({"success": False, "error": "Training not found"}), 404

        # Update training status
        cur.execute(
            """
            UPDATE training_assignments
            SET status = %s, completed_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """,
            (status, training_id),
        )

        # If completed, update agent skill
        if status == "completed":
            cur.execute(
                """
                INSERT INTO agent_skills (agent_id, skill_name, proficiency_level)
                VALUES (%s, %s, %s)
                ON CONFLICT (agent_id, skill_name) DO UPDATE
                SET proficiency_level = GREATEST(agent_skills.proficiency_level, EXCLUDED.proficiency_level),
                    updated_at = NOW()
            """,
                (
                    training["agent_id"],
                    training["skill_name"],
                    training["target_proficiency"],
                ),
            )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": f"Training {status}"})

    except Exception as e:
        logger.error(f"Error completing training: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LOUNGE (REST AREA) API - Phase 39
# ============================================================================


@bridge_bp.route("/api/lounge")
@login_required
def get_lounge_agents():
    """Get agents currently in lounge (resting)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                a.avatar_url,
                a.department,
                arc.id as rest_cycle_id,
                arc.rest_type,
                arc.reason as rest_reason,
                arc.started_at as rest_started,
                EXTRACT(EPOCH FROM (NOW() - arc.started_at)) / 3600 as hours_resting,
                CASE WHEN arc.rest_type = 'forced' THEN TRUE ELSE FALSE END as is_locked
            FROM agent_rest_cycles arc
            JOIN agents a ON arc.agent_id = a.id
            WHERE arc.ended_at IS NULL
            AND a.status = 'active'
            ORDER BY arc.started_at DESC
        """
        )
        agents = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": agents})

    except Exception as e:
        logger.error(f"Error loading lounge agents: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/send-to-lounge", methods=["POST"])
@login_required
def send_agent_to_lounge(agent_id):
    """Send an agent to lounge (start rest cycle)"""
    try:
        data = request.get_json() or {}
        rest_type = data.get("rest_type", "voluntary")
        reason = data.get("reason", "Sent to lounge via Bridge")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Remove from station assignment if any
        cur.execute(
            "UPDATE station_assignments SET is_active = FALSE WHERE agent_id = %s AND is_active = TRUE",
            (agent_id,),
        )

        # Cancel any active training
        cur.execute(
            "UPDATE training_assignments SET status = 'cancelled' "
            "WHERE agent_id = %s AND status IN ('pending', 'in_progress')",
            (agent_id,),
        )

        # Start rest cycle
        cur.execute(
            """
            INSERT INTO agent_rest_cycles (agent_id, rest_type, reason, started_at)
            VALUES (%s, %s, %s, NOW())
            RETURNING id
        """,
            (agent_id, rest_type, reason),
        )

        rest_cycle_id = cur.fetchone()["id"]

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "rest_cycle_id": rest_cycle_id,
                "message": "Agent sent to lounge",
            }
        )

    except Exception as e:
        logger.error(f"Error sending agent to lounge: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/return-from-lounge", methods=["POST"])
@login_required
def return_agent_from_lounge(agent_id):
    """Return an agent from lounge (end rest cycle)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if agent is in forced rest
        cur.execute(
            """
            SELECT id, rest_type FROM agent_rest_cycles
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )
        rest_cycle = cur.fetchone()

        if not rest_cycle:
            return jsonify({"success": False, "error": "Agent is not in lounge"}), 400

        if rest_cycle["rest_type"] == "forced":
            return (
                jsonify({"success": False, "error": "Cannot return agent from forced rest"}),
                403,
            )

        # End rest cycle
        cur.execute(
            """
            UPDATE agent_rest_cycles
            SET ended_at = NOW()
            WHERE id = %s
        """,
            (rest_cycle["id"],),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Agent returned from lounge"})

    except Exception as e:
        logger.error(f"Error returning agent from lounge: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# IAAE COMPLIANCE CHECK API - Phase 39
# ============================================================================


@bridge_bp.route("/api/iaae/check-move/<int:agent_id>")
@login_required
def check_iaae_move_compliance(agent_id):
    """Check IAAE compliance before moving an agent"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        warnings = []
        allowed = True
        can_override = True

        # Get agent emotional state
        cur.execute(
            """
            SELECT stress_level, energy_level
            FROM agent_emotional_state
            WHERE agent_id = %s
        """,
            (agent_id,),
        )
        emotional_state = cur.fetchone()

        if emotional_state:
            if emotional_state["stress_level"] and emotional_state["stress_level"] > 0.7:
                warnings.append(f"High stress level ({round(emotional_state['stress_level'] * 100)}%)")

            if emotional_state["energy_level"] and emotional_state["energy_level"] < 0.3:
                warnings.append(f"Low energy level ({round(emotional_state['energy_level'] * 100)}%)")

        # Check if in forced rest
        cur.execute(
            """
            SELECT rest_type FROM agent_rest_cycles
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )
        rest_cycle = cur.fetchone()

        if rest_cycle and rest_cycle["rest_type"] == "forced":
            allowed = False
            can_override = False
            warnings.append("Agent is in forced rest - cannot be moved")

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "allowed": allowed,
                "can_override": can_override,
                "warnings": warnings,
            }
        )

    except Exception as e:
        logger.error(f"Error checking IAAE compliance: {e}")
        return jsonify({"success": True, "allowed": True, "warnings": []})  # Fail open


# ============================================================================
# TOKEN USAGE / TRAFFIC API
# ============================================================================


@bridge_bp.route("/api/traffic")
def get_traffic_stats():
    """Get throughput stats from task_execution_log (rolling 24h window)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT COUNT(*) as total_24h
            FROM task_execution_log
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """
        )
        row = cur.fetchone()
        total_24h = row["total_24h"] if row else 0
        requests_per_minute = round(total_24h / 1440.0, 1)

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "requests_per_minute": requests_per_minute,
                "total_24h": total_24h,
            }
        )

    except Exception as e:
        logger.error(f"Error getting traffic stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agent-utilization")
def get_agent_utilization():
    """Get real agent activity rate over 24h (agents that executed tasks / total active)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                (SELECT COUNT(DISTINCT agent_id) FROM task_execution_log
                 WHERE created_at >= NOW() - INTERVAL '24 hours' AND agent_id IS NOT NULL) as active_agents,
                (SELECT COUNT(*) FROM agents WHERE status = 'active') as total_agents
        """
        )
        row = cur.fetchone()
        active = row["active_agents"] or 0
        total = row["total_agents"] or 0
        utilization_pct = round(active / total * 100) if total > 0 else 0

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "active_agents": active,
                "total_agents": total,
                "utilization_pct": utilization_pct,
            }
        )

    except Exception as e:
        logger.error(f"Error getting agent utilization: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/models/live")
def get_live_models():
    """Get actual model count from live Ollama API"""
    try:
        resp = requests.get("http://host.docker.internal:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return jsonify(
                {
                    "success": True,
                    "count": len(models),
                    "models": [m["name"] for m in models],
                }
            )
        return jsonify({"success": False, "error": "Ollama not responding"}), 502

    except Exception as e:
        logger.error(f"Error getting live models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/iaae/overview")
def get_iaae_overview():
    """Get real IAAE compliance and welfare metrics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Compliance: tasks approved vs total reviewed in 24h
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE event_category = 'task_approved') as approved,
                COUNT(*) as total
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '24 hours'
        """
        )
        gov = cur.fetchone()
        gov_total = gov["total"] or 0
        gov_approved = gov["approved"] or 0
        compliance_pct = round(gov_approved / gov_total * 100, 1) if gov_total > 0 else None

        # Agent welfare: average stress and energy across active agents
        cur.execute(
            """
            SELECT AVG(es.stress_level) as avg_stress, AVG(es.energy_level) as avg_energy
            FROM agent_emotional_state es
            JOIN agents a ON a.id = es.agent_id
            WHERE a.status = 'active'
        """
        )
        welfare = cur.fetchone()
        avg_stress = round(float(welfare["avg_stress"]), 2) if welfare and welfare["avg_stress"] is not None else None
        avg_energy = round(float(welfare["avg_energy"]), 2) if welfare and welfare["avg_energy"] is not None else None

        # Agents currently at rest
        cur.execute(
            """
            SELECT COUNT(*) as count
            FROM agent_rest_cycles
            WHERE ended_at IS NULL
        """
        )
        rest_row = cur.fetchone()
        agents_at_rest = rest_row["count"] or 0

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "compliance_pct": compliance_pct,
                "avg_stress": avg_stress,
                "avg_energy": avg_energy,
                "agents_at_rest": agents_at_rest,
                "governance_events_24h": gov_total,
            }
        )

    except Exception as e:
        logger.error(f"Error getting IAAE overview: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/workload")
@login_required
def get_agent_workload():
    """Per-agent workload: 24h tasks, tokens, daily caps, risk levels."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.id, a.name, a.first_name, a.last_name, a.status,
                COALESCE(ab.task_queue_limit, 50) as daily_cap,
                COALESCE(ab.token_limit_per_day, 500000) as token_cap,
                COUNT(tel.id) as tasks_24h,
                COUNT(tel.id) FILTER (WHERE tel.success = TRUE) as completed_24h,
                COUNT(tel.id) FILTER (WHERE tel.success = FALSE) as failed_24h,
                COALESCE(AVG(tel.duration_ms), 0) as avg_duration_ms,
                COALESCE(SUM(tel.tokens_used), 0) as tokens_used_24h
            FROM agents a
            LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
            LEFT JOIN task_execution_log tel ON tel.agent_id = a.id
                AND tel.created_at >= NOW() - INTERVAL '24 hours'
            WHERE a.status IN ('active', 'busy', 'idle', 'working')
            GROUP BY a.id, a.name, a.first_name, a.last_name, a.status,
                     ab.task_queue_limit, ab.token_limit_per_day
            ORDER BY tasks_24h DESC
        """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        agents = []
        total_tasks = 0
        at_risk = 0
        for r in rows:
            daily_cap = int(r["daily_cap"]) or 50
            token_cap = int(r["token_cap"]) or 500000
            tasks = int(r["tasks_24h"])
            tokens = int(r["tokens_used_24h"])
            workload_pct = min(round(tasks / daily_cap * 100, 1), 100) if daily_cap > 0 else 0
            token_pct = min(round(tokens / token_cap * 100, 1), 100) if token_cap > 0 else 0

            if workload_pct >= 100:
                risk = "overloaded"
            elif workload_pct >= 80:
                risk = "critical"
            elif workload_pct >= 60:
                risk = "elevated"
            else:
                risk = "healthy"

            if risk in ("critical", "overloaded"):
                at_risk += 1
            total_tasks += tasks

            agents.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "first_name": r.get("first_name"),
                    "last_name": r.get("last_name"),
                    "status": r["status"],
                    "daily_cap": daily_cap,
                    "token_cap": token_cap,
                    "tasks_24h": tasks,
                    "completed_24h": int(r["completed_24h"]),
                    "failed_24h": int(r["failed_24h"]),
                    "avg_duration_ms": round(float(r["avg_duration_ms"]), 1),
                    "tokens_used_24h": tokens,
                    "workload_pct": workload_pct,
                    "token_usage_pct": token_pct,
                    "risk_level": risk,
                }
            )

        return jsonify(
            {
                "success": True,
                "agents": agents,
                "summary": {
                    "total_agents": len(agents),
                    "total_tasks_24h": total_tasks,
                    "agents_at_risk": at_risk,
                },
            }
        )
    except Exception as e:
        logger.error("get_agent_workload error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/welfare")
@login_required
def get_agent_welfare():
    """Aggregate welfare: emotional state, rest cycles, refusals, governance."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Latest emotional state per agent (using DISTINCT ON)
        cur.execute(
            """
            SELECT DISTINCT ON (a.id)
                a.id, a.name, a.first_name, a.last_name,
                es.current_mood as mood, es.mood_intensity as intensity,
                es.energy_level, es.stress_level, es.timestamp as last_check
            FROM agents a
            LEFT JOIN agent_emotional_state es ON es.agent_id = a.id
            WHERE a.status IN ('active', 'busy', 'idle', 'working', 'resting')
            ORDER BY a.id, es.timestamp DESC NULLS LAST
        """
        )
        agents = cur.fetchall()
        for a in agents:
            if a.get("last_check"):
                a["last_check"] = a["last_check"].isoformat()
            for k in ["intensity", "energy_level", "stress_level"]:
                if a.get(k) is not None:
                    a[k] = float(a[k])

        # Agents currently at rest
        cur.execute(
            """
            SELECT a.id, a.name, arc.reason, arc.started_at, arc.initiated_by
            FROM agent_rest_cycles arc
            JOIN agents a ON a.id = arc.agent_id
            WHERE arc.ended_at IS NULL
        """
        )
        resting = cur.fetchall()
        for r in resting:
            if r.get("started_at"):
                r["started_at"] = r["started_at"].isoformat()

        # Recent refusals (24h)
        cur.execute(
            """
            SELECT a.id, a.name, trl.refusal_reason as reason,
                   trl.task_type, trl.was_overridden, trl.timestamp
            FROM task_refusal_log trl
            JOIN agents a ON a.id = trl.agent_id
            WHERE trl.timestamp >= NOW() - INTERVAL '24 hours'
            ORDER BY trl.timestamp DESC
            LIMIT 20
        """
        )
        refusals = cur.fetchall()
        for r in refusals:
            if r.get("timestamp"):
                r["timestamp"] = r["timestamp"].isoformat()

        # Governance events (24h)
        cur.execute(
            """
            SELECT event_category, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '24 hours'
            GROUP BY event_category
        """
        )
        gov_rows = cur.fetchall()
        gov_summary = {}
        for g in gov_rows:
            gov_summary[g["event_category"]] = g["count"]

        cur.close()
        conn.close()

        # Fleet health aggregates
        stress_vals = [a["stress_level"] for a in agents if a.get("stress_level") is not None]
        energy_vals = [a["energy_level"] for a in agents if a.get("energy_level") is not None]
        avg_stress = round(sum(stress_vals) / len(stress_vals), 2) if stress_vals else None
        avg_energy = round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None
        high_stress = sum(1 for s in stress_vals if s > 0.7)

        total_gov = sum(gov_summary.values()) if gov_summary else 0
        approved = gov_summary.get("task_approved", 0)
        compliance_pct = round(approved / total_gov * 100, 1) if total_gov > 0 else None

        return jsonify(
            {
                "success": True,
                "agents": agents,
                "agents_at_rest": resting,
                "recent_refusals": refusals,
                "governance_summary": gov_summary,
                "fleet_health": {
                    "avg_stress": avg_stress,
                    "avg_energy": avg_energy,
                    "agents_at_risk": high_stress,
                    "agents_resting": len(resting),
                    "compliance_pct": compliance_pct,
                    "total_governance_events": total_gov,
                },
            }
        )
    except Exception as e:
        logger.error("get_agent_welfare error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/iaae/enforcement-log")
@login_required
def get_iaae_enforcement_log():
    """Vigil enforcement log: governance actions in the last 7 days."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT gal.id, gal.timestamp, gal.event_type, gal.event_category,
                   gal.action, gal.reason, gal.outcome,
                   gal.agent_id, a.name as agent_name,
                   a.first_name as agent_first_name
            FROM governance_audit_log gal
            LEFT JOIN agents a ON a.id = gal.agent_id
            WHERE gal.timestamp >= NOW() - INTERVAL '7 days'
            ORDER BY gal.timestamp DESC
            LIMIT 50
        """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for r in rows:
            if r.get("timestamp"):
                r["timestamp"] = r["timestamp"].isoformat()

        return jsonify({"success": True, "events": rows, "total": len(rows)})
    except Exception as e:
        logger.error("get_iaae_enforcement_log error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ARCHIE STATUS API
# ============================================================================


@bridge_bp.route("/api/archie/status")
def get_archie_status():
    """Get A.R.C.H.I.E.'s current status and emotional state"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get core identity
        cur.execute(
            """
            SELECT name, role, personality_profile
            FROM archie_core_identity
            LIMIT 1
        """
        )
        identity = cur.fetchone()

        # Get emotional state
        cur.execute(
            """
            SELECT
                current_mood, mood_intensity, relationship_strength, timestamp
            FROM archie_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """
        )
        emotional = cur.fetchone()

        # Get personality traits
        cur.execute(
            """
            SELECT trait_name, trait_value, description
            FROM archie_personality
            ORDER BY updated_at DESC
            LIMIT 5
        """
        )
        traits = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "archie": {
                    "identity": identity or {"name": "A.R.C.H.I.E.", "role": "AI Co-founder"},
                    "emotional_state": emotional
                    or {
                        "current_mood": "supportive",
                        "mood_intensity": 0.85,
                        "relationship_strength": 0.90,
                    },
                    "top_traits": traits or [],
                    "station": "COMMS",
                    "status": "Active",
                },
            }
        )

    except Exception as e:
        logger.error(f"Error getting ARCHIE status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MODULE NAVIGATION
# ============================================================================


@bridge_bp.route("/api/modules")
def get_module_mapping():
    """Get mapping of modules to stations for navigation"""
    modules = []

    # Get stations from database, fallback to hardcoded
    stations = get_stations_from_db() or STATIONS_FALLBACK

    for station_code, station_info in stations.items():
        station_modules = station_info.get("modules", [])
        if isinstance(station_modules, list):
            for module in station_modules:
                modules.append(
                    {
                        "module": module,
                        "station": station_code,
                        "station_color": station_info.get("color", "#00FFFF"),
                    }
                )

    return jsonify({"success": True, "modules": modules})


# ============================================================================
# LLM CONNECTIONS MONITOR (Phase 27)
# ============================================================================


@bridge_bp.route("/api/llm/status")
def get_llm_status():
    """Get live LLM status from Ollama + external API key checks"""
    try:
        ollama_host = "host.docker.internal"
        ollama_port = 11434

        # 1. Check Ollama health
        status, latency = check_ollama_status(ollama_host, ollama_port)

        # 2. Get loaded models (currently in VRAM/RAM)
        loaded_models = []
        try:
            resp = requests.get(f"http://{ollama_host}:{ollama_port}/api/ps", timeout=5)
            if resp.ok:
                for m in resp.json().get("models", []):
                    loaded_models.append(
                        {
                            "name": m.get("name", "unknown"),
                            "size": m.get("size", 0),
                            "vram": m.get("size_vram", 0),
                            "expires": m.get("expires_at", ""),
                        }
                    )
        except Exception:
            pass
        loaded_names = {m["name"] for m in loaded_models}

        # 3. Get all available models
        available_models = get_ollama_models(ollama_host, ollama_port)

        # 4. Build model list with status
        models = []
        for name in available_models:
            models.append(
                {
                    "name": name,
                    "provider": "ollama",
                    "status": "loaded" if name in loaded_names else "available",
                }
            )

        # 5. Check external API keys
        external = []
        for conn_id, label in [
            ("claude_api", "Claude API"),
            ("openai_api", "OpenAI"),
            ("grok_api", "Grok"),
        ]:
            key_status = check_api_key_status(conn_id)
            external.append(
                {
                    "name": label,
                    "provider": conn_id.replace("_api", ""),
                    "status": "configured" if key_status else "no_key",
                }
            )

        # 6. Get routing mode
        routing_mode = "full"
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
            row = cur.fetchone()
            if row:
                routing_mode = row["value"]
            cur.close()
            conn.close()
        except Exception:
            pass

        return jsonify(
            {
                "success": True,
                "ollama_status": status,
                "ollama_latency_ms": latency,
                "loaded_models": loaded_models,
                "models": models,
                "external": external,
                "routing_mode": routing_mode,
                "total_available": len(available_models),
                "total_loaded": len(loaded_models),
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"LLM status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/llm/check", methods=["POST"])
def trigger_llm_check():
    """Trigger immediate health check of all LLM connections"""
    try:
        from llm_monitor import check_now

        results = check_now()

        return jsonify(
            {
                "success": True,
                "results": results,
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"LLM check error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/llm/alerts")
def get_llm_alerts():
    """Get recent LLM alerts"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        acknowledged = request.args.get("acknowledged", "false").lower() == "true"

        cur.execute(
            """
            SELECT a.id, a.alert_type, a.severity, a.message, a.details,
                   a.acknowledged, a.created_at,
                   c.provider, c.model_name, c.display_name
            FROM llm_alerts a
            JOIN llm_connections c ON a.connection_id = c.id
            WHERE a.acknowledged = %s
            ORDER BY a.created_at DESC
            LIMIT 50
        """,
            (acknowledged,),
        )
        alerts = cur.fetchall()

        cur.close()
        conn.close()

        # Convert datetime
        for a in alerts:
            if a.get("created_at"):
                a["created_at"] = a["created_at"].isoformat()

        return jsonify({"success": True, "alerts": alerts})

    except Exception as e:
        logger.error(f"LLM alerts error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/llm/alerts/<int:alert_id>/acknowledge", methods=["POST"])
def acknowledge_llm_alert(alert_id):
    """Acknowledge an LLM alert"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE llm_alerts
            SET acknowledged = TRUE, acknowledged_at = NOW()
            WHERE id = %s
        """,
            (alert_id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Acknowledge alert error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/llm/history/<int:connection_id>")
def get_llm_history(connection_id):
    """Get connection history for charts"""
    try:
        hours = request.args.get("hours", 24, type=int)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT check_time, status, latency_ms, error_message
            FROM llm_connection_history
            WHERE connection_id = %s
              AND check_time > NOW() - INTERVAL '%s hours'
            ORDER BY check_time DESC
            LIMIT 500
        """,
            (connection_id, hours),
        )
        history = cur.fetchall()

        cur.close()
        conn.close()

        # Convert datetime
        for h in history:
            if h.get("check_time"):
                h["check_time"] = h["check_time"].isoformat()

        return jsonify({"success": True, "history": history})

    except Exception as e:
        logger.error(f"LLM history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
    """Verify an API key against stored hash"""
    return hash_api_key(api_key) == stored_hash


@bridge_bp.route("/api/nodes")
def get_all_nodes():
    """Get all registered remote nodes"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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

        cur.close()
        conn.close()

        # Convert datetime
        for node in nodes:
            for key in ["last_heartbeat", "created_at", "updated_at", "approved_at"]:
                if node.get(key):
                    node[key] = node[key].isoformat()

        return jsonify({"success": True, "nodes": nodes, "summary": summary})

    except Exception as e:
        logger.error(f"Error getting nodes: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/install.sh", methods=["GET"])
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


@bridge_bp.route("/api/nodes/install.ps1", methods=["GET"])
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


@bridge_bp.route("/api/nodes/heartbeat.ps1", methods=["GET"])
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


@bridge_bp.route("/api/nodes/heartbeat.sh", methods=["GET"])
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


@bridge_bp.route("/api/nodes/docker-compose.node.yml", methods=["GET"])
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


@bridge_bp.route("/api/nodes/node_sync.py", methods=["GET"])
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


@bridge_bp.route("/api/nodes/archie-node-latest.tar.gz", methods=["GET"])
def serve_node_image():
    """Serve the pre-built node Docker image tarball"""
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
                    "error": "Node image not built yet. Run: "
                    "docker save archie-node:latest | gzip > /mnt/archie_brain/node_client/archie-node-latest.tar.gz",
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


@bridge_bp.route("/api/nodes/client-package", methods=["GET"])
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
        return jsonify({"success": False, "error": str(e)}), 500


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


@bridge_bp.route("/api/nodes/register", methods=["POST"])
def register_node():
    """Register a new remote node"""
    data = request.get_json() or {}

    required = ["node_name"]
    for field in required:
        if not data.get(field):
            return jsonify({"success": False, "error": f"{field} is required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
                data.get("port", 11434),
                api_key_hash,
                data.get("client_version", "1.0.0"),
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
        conn.commit()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/heartbeat", methods=["POST"])
def node_heartbeat(node_id):
    """Receive heartbeat from a remote node"""
    data = request.get_json() or {}
    api_key = request.headers.get("X-Node-API-Key")

    if not api_key:
        return jsonify({"success": False, "error": "API key required"}), 401

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify node and API key
        cur.execute(
            """
            SELECT id, api_key_hash, min_required_version
            FROM remote_nodes WHERE node_id = %s AND is_active = TRUE
        """,
            (node_id,),
        )
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Node not found"}), 404

        if not verify_api_key(api_key, node["api_key_hash"]):
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invalid API key"}), 401

        # Version check
        client_version = data.get("client_version", "1.0.0")
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
                ram_gb = COALESCE(%s, ram_gb),
                gpu_available = COALESCE(%s, gpu_available),
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
                data.get("ram_gb"),
                data.get("gpu_available"),
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

        conn.commit()

        # Sync Ollama models if provided (Phase 70: Node Model Discovery)
        models_synced = 0
        if data.get("ollama_models") and data.get("ollama_online"):
            try:
                cur.execute(
                    """
                    SELECT sync_node_models(%s, %s::jsonb)
                """,
                    (node_id, psycopg2.extras.Json(data["ollama_models"])),
                )
                result = cur.fetchone()
                models_synced = result[0] if result else 0
                conn.commit()
                logger.debug(f"Synced {models_synced} models for node {node_id}")
            except Exception as e:
                logger.warning(f"Model sync error for {node_id}: {e}")

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "status": status,
                "message": "Heartbeat received",
                "models_synced": models_synced,
            }
        )

    except Exception as e:
        logger.error(f"Heartbeat error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>")
def get_node_detail(node_id):
    """Get detailed info about a specific node"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM remote_nodes WHERE node_id = %s
        """,
            (node_id,),
        )
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
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

        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>", methods=["PUT"])
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
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
        conn.commit()
        cur.close()
        conn.close()

        if not updated:
            return jsonify({"success": False, "error": "Node not found"}), 404

        return jsonify({"success": True, "node": updated})

    except Exception as e:
        logger.error(f"Error updating node: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>", methods=["DELETE"])
def delete_node(node_id):
    """Delete a remote node"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM remote_nodes WHERE node_id = %s RETURNING id
        """,
            (node_id,),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Node not found"}), 404

        return jsonify({"success": True, "message": f"Node {node_id} deleted"})

    except Exception as e:
        logger.error(f"Error deleting node: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/capabilities", methods=["POST"])
def update_node_capabilities(node_id):
    """Update capabilities for a node (called by node client)"""
    data = request.get_json() or {}
    api_key = request.headers.get("X-Node-API-Key")
    capabilities = data.get("capabilities", [])

    if not api_key:
        return jsonify({"success": False, "error": "API key required"}), 401

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
            cur.close()
            conn.close()
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

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": f"Updated {len(capabilities)} capabilities"})

    except Exception as e:
        logger.error(f"Error updating capabilities: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/select", methods=["POST"])
def select_node_for_request():
    """Select the best node for a request (load balancing)"""
    data = request.get_json() or {}
    model_name = data.get("model")
    provider = data.get("provider", "ollama")

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
            cur.close()
            conn.close()
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

        conn.commit()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/request-complete", methods=["POST"])
def node_request_complete(node_id):
    """Mark a request as complete (decrement load)"""
    data = request.get_json() or {}

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node
        cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s", (node_id,))
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
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

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Error completing request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/stats")
def get_node_stats():
    """Get aggregate stats across all nodes"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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

        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# NODE APPROVAL & MANAGEMENT - Phase 29+ Enhancement
# ============================================================================


@bridge_bp.route("/api/nodes/<node_id>/status", methods=["GET"])
def get_node_status(node_id):
    """Get node approval status (for polling during install)"""
    api_key = request.headers.get("X-Node-API-Key")

    if not api_key:
        return jsonify({"error": "API key required"}), 401

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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
        cur.close()
        conn.close()

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
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/approve", methods=["POST"])
def approve_node(node_id):
    """Approve a pending node registration"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current user ID (if available from session)
        user_id = None
        if hasattr(request, "user") and request.user:
            user_id = request.user.get("id")

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
        conn.commit()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/reject", methods=["POST"])
def reject_node(node_id):
    """Reject a pending node registration"""
    data = request.get_json() or {}
    reason = data.get("reason", "No reason provided")

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current user ID
        user_id = None
        if hasattr(request, "user") and request.user:
            user_id = request.user.get("id")

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
        conn.commit()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/test", methods=["POST"])
def test_node_connection(node_id):
    """Test connectivity to a remote node's Ollama instance"""
    import time

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT node_id, node_name, vpn_ip, hostname, port
            FROM remote_nodes
            WHERE node_id = %s AND is_active = TRUE
        """,
            (node_id,),
        )

        node = cur.fetchone()
        cur.close()
        conn.close()

        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        # Build endpoint URL
        host = node["vpn_ip"] or node["hostname"]
        port = node["port"] or 11434
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
            return jsonify(
                {
                    "success": True,
                    "node_id": node_id,
                    "reachable": False,
                    "latency_ms": None,
                    "error": f"Connection failed: {str(e)}",
                }
            )

    except Exception as e:
        logger.error(f"Error testing node: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/health-history", methods=["GET"])
def get_node_health_history(node_id):
    """Get health history for a node (for charts)"""
    hours = request.args.get("hours", 24, type=int)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node internal ID
        cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s", (node_id,))
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
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
              AND created_at > NOW() - INTERVAL '%s hours'
            GROUP BY DATE_TRUNC('hour', created_at)
            ORDER BY hour
        """,
            (node["id"], hours),
        )

        history = cur.fetchall()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# NODE STATION ASSIGNMENTS - Phase 31
# ============================================================================


@bridge_bp.route("/api/nodes/<node_id>/stations", methods=["GET"])
def get_node_stations(node_id):
    """Get all station assignments for a node"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node internal ID
        cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
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
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/stations", methods=["POST"])
@login_required
def assign_node_to_station(node_id):
    """Assign a node to a station"""
    data = request.get_json() or {}

    if not data.get("station_id"):
        return jsonify({"success": False, "error": "station_id is required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node internal ID
        cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Node not found"}), 404

        # Verify station exists
        cur.execute(
            "SELECT id, station_name FROM bridge_stations WHERE id = %s",
            (data["station_id"],),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
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
            cur.close()
            conn.close()
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
        conn.commit()
        cur.close()
        conn.close()

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
                    "assigned_at": (assignment["assigned_at"].isoformat() if assignment["assigned_at"] else None),
                },
            }
        )

    except Exception as e:
        logger.error(f"Error assigning node to station: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["PUT"])
@login_required
def update_node_station_assignment(node_id, station_id):
    """Update a node's station assignment (role, priority, etc.)"""
    data = request.get_json() or {}

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node internal ID
        cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
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
            cur.close()
            conn.close()
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
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": (
                    f"Assignment updated for node '{node['node_name']}' " f"at station '{assignment['station_name']}'"
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["DELETE"])
@login_required
def remove_node_from_station(node_id, station_id):
    """Remove a node from a station"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node internal ID
        cur.execute("SELECT id, node_name FROM remote_nodes WHERE node_id = %s", (node_id,))
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
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
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Assignment not found"}), 404

        conn.commit()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<int:station_id>/nodes", methods=["GET"])
def get_station_nodes(station_id):
    """Get all nodes assigned to a station"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify station exists
        cur.execute(
            "SELECT id, station_code, station_name, color FROM bridge_stations WHERE id = %s",
            (station_id,),
        )
        station = cur.fetchone()

        if not station:
            cur.close()
            conn.close()
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
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/coverage", methods=["GET"])
def get_all_station_coverage():
    """Get node coverage summary for all stations"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_station_node_coverage
        """
        )

        coverage = cur.fetchall()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/select-for-station", methods=["POST"])
def select_node_for_station_api():
    """Select the best available node for a station task"""
    data = request.get_json() or {}

    if not data.get("station_id"):
        return jsonify({"success": False, "error": "station_id is required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        urgency = data.get("urgency", "normal")

        cur.execute(
            """
            SELECT * FROM select_node_for_station(%s, %s)
        """,
            (data["station_id"], urgency),
        )

        nodes = cur.fetchall()
        cur.close()
        conn.close()

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
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MINING POOL INTEGRATION - Phase 30
# ============================================================================
# BRIDGE MODEL ROUTING - Phase 70
# ============================================================================


@bridge_bp.route("/api/nodes/<node_id>/bridge-sharing", methods=["PUT"])
@login_required
def toggle_bridge_sharing(node_id):
    """Enable or disable a node's model sharing with Bridge"""
    data = request.get_json() or {}
    enabled = data.get("enabled", False)
    priority = data.get("priority", 50)

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE remote_nodes
            SET bridge_enabled = %s,
                bridge_priority = %s,
                updated_at = NOW()
            WHERE node_id = %s
            RETURNING node_name
        """,
            (enabled, priority, node_id),
        )

        result = cur.fetchone()
        if not result:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Node not found"}), 404

        # Log to governance audit
        cur.execute(
            """
            INSERT INTO governance_audit_log (
                event_type, event_category, agent_id, action, new_value, reason, outcome
            ) VALUES (
                'node_bridge_sharing', 'autonomy', NULL, %s, %s, %s, 'success'
            )
        """,
            (
                "enable" if enabled else "disable",
                f'{{"node_id": "{node_id}", "priority": {priority}}}',
                f"Bridge sharing {'enabled' if enabled else 'disabled'} for node {result[0]}",
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "bridge_enabled": enabled, "bridge_priority": priority})

    except Exception as e:
        logger.error(f"Toggle bridge sharing error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/models")
def get_bridge_available_models():
    """Get all models available across bridge-enabled nodes"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_bridge_available_models
        """
        )
        models = cur.fetchall()

        # Get summary stats
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT m.model_name) as total_models,
                COUNT(DISTINCT n.node_id) as total_nodes,
                SUM(m.total_requests) as total_requests
            FROM node_ollama_models m
            JOIN remote_nodes n ON m.node_id = n.node_id
            WHERE n.bridge_enabled = true AND n.status = 'online'
        """
        )
        summary = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({"success": True, "models": models, "summary": summary})

    except Exception as e:
        logger.error(f"Get bridge models error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/models")
def get_node_models(node_id):
    """Get Ollama models available on a specific node"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node info
        cur.execute(
            """
            SELECT node_name, bridge_enabled, bridge_priority, last_model_sync, status
            FROM remote_nodes WHERE node_id = %s
        """,
            (node_id,),
        )
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Node not found"}), 404

        # Get models
        cur.execute(
            """
            SELECT model_name, model_family, parameter_size, model_size_gb,
                   is_available, total_requests, avg_response_ms, updated_at
            FROM node_ollama_models
            WHERE node_id = %s
            ORDER BY model_name
        """,
            (node_id,),
        )
        models = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "node": node,
                "models": models,
                "model_count": len(models),
            }
        )

    except Exception as e:
        logger.error(f"Get node models error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/models/sync", methods=["POST"])
@login_required
def sync_node_models_api(node_id):
    """Manually trigger model sync for a node (fetches from node's Ollama)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get node info
        cur.execute(
            """
            SELECT vpn_ip, port, ollama_available FROM remote_nodes WHERE node_id = %s
        """,
            (node_id,),
        )
        node = cur.fetchone()

        if not node:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Node not found"}), 404

        if not node["ollama_available"]:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Node does not have Ollama"}),
                400,
            )

        # Fetch models from node's Ollama
        import requests as req

        ollama_url = f"http://{node['vpn_ip']}:{node.get('port', 11434)}/api/tags"

        try:
            resp = req.get(ollama_url, timeout=10)
            if resp.status_code != 200:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Ollama returned {resp.status_code}",
                        }
                    ),
                    502,
                )

            models = resp.json().get("models", [])

        except req.exceptions.RequestException as e:
            return (
                jsonify({"success": False, "error": f"Cannot reach node Ollama: {e}"}),
                502,
            )

        # Sync models using database function
        cur.execute(
            """
            SELECT sync_node_models(%s, %s::jsonb)
        """,
            (node_id, psycopg2.extras.Json(models)),
        )
        result = cur.fetchone()
        models_synced = result[0] if result else 0

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "models_synced": models_synced,
                "message": f"Synced {models_synced} models from node",
            }
        )

    except Exception as e:
        logger.error(f"Manual model sync error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/select-node", methods=["POST"])
def select_node_for_model():
    """Select the best available node for a specific model"""
    data = request.get_json() or {}
    model_name = data.get("model_name")
    prefer_gpu = data.get("prefer_gpu", True)

    if not model_name:
        return jsonify({"success": False, "error": "model_name required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM select_node_for_model(%s, %s) LIMIT 1
        """,
            (model_name, prefer_gpu),
        )
        node = cur.fetchone()

        cur.close()
        conn.close()

        if not node:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"No bridge-enabled node has model {model_name}",
                    }
                ),
                404,
            )

        return jsonify(
            {
                "success": True,
                "node": node,
                "ollama_url": f"http://{node['vpn_ip']}:{node['port']}",
            }
        )

    except Exception as e:
        logger.error(f"Select node for model error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MINING RESOURCE SCHEDULER - Phase 65
# ============================================================================

# Resource scheduler modes
SCHEDULER_MODES = {
    "ai_priority": {
        "ai_weight": 80,
        "mining_weight": 20,
        "description": "Prioritize AI workloads",
    },
    "mining_priority": {
        "ai_weight": 20,
        "mining_weight": 80,
        "description": "Prioritize mining",
    },
    "balanced": {
        "ai_weight": 50,
        "mining_weight": 50,
        "description": "Equal resource split",
    },
    "ai_only": {
        "ai_weight": 100,
        "mining_weight": 0,
        "description": "AI workloads only",
    },
    "mining_only": {"ai_weight": 0, "mining_weight": 100, "description": "Mining only"},
    "dynamic": {
        "ai_weight": -1,
        "mining_weight": -1,
        "description": "Auto-adjust based on demand",
    },
}


@bridge_bp.route("/api/mining/scheduler")
def get_scheduler_status():
    """Get current resource scheduler status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if scheduler config exists
        cur.execute(
            """
            SELECT * FROM resource_scheduler_config
            ORDER BY updated_at DESC LIMIT 1
        """
        )
        config = cur.fetchone()

        # Get current resource usage
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN task_type = 'ai' THEN 1 ELSE 0 END) as ai_tasks,
                SUM(CASE WHEN task_type = 'mining' THEN 1 ELSE 0 END) as mining_tasks,
                COUNT(*) as total_tasks
            FROM resource_allocation
            WHERE is_active = TRUE
        """
        )
        usage = cur.fetchone()

        cur.close()
        conn.close()

        if not config:
            config = {
                "mode": "balanced",
                "ai_weight": 50,
                "mining_weight": 50,
                "gpu_for_mining": True,
                "cpu_for_ai": True,
            }

        return jsonify(
            {
                "success": True,
                "config": config,
                "usage": usage or {"ai_tasks": 0, "mining_tasks": 0, "total_tasks": 0},
                "modes": SCHEDULER_MODES,
            }
        )

    except Exception:
        # Table might not exist yet - return defaults
        return jsonify(
            {
                "success": True,
                "config": {
                    "mode": "balanced",
                    "ai_weight": 50,
                    "mining_weight": 50,
                    "gpu_for_mining": True,
                    "cpu_for_ai": True,
                },
                "usage": {"ai_tasks": 0, "mining_tasks": 0, "total_tasks": 0},
                "modes": SCHEDULER_MODES,
                "note": "Using defaults - scheduler tables not yet created",
            }
        )


@bridge_bp.route("/api/mining/scheduler", methods=["PUT"])
def update_scheduler_config():
    """Update resource scheduler configuration"""
    data = request.get_json() or {}
    mode = data.get("mode", "balanced")

    if mode not in SCHEDULER_MODES and mode != "custom":
        return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get weights from mode or custom values
        if mode == "custom":
            ai_weight = data.get("ai_weight", 50)
            mining_weight = data.get("mining_weight", 50)
        else:
            ai_weight = SCHEDULER_MODES[mode]["ai_weight"]
            mining_weight = SCHEDULER_MODES[mode]["mining_weight"]

        # Upsert config
        cur.execute(
            """
            INSERT INTO resource_scheduler_config (
                id, mode, ai_weight, mining_weight, gpu_for_mining, cpu_for_ai, updated_at
            ) VALUES (1, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                mode = EXCLUDED.mode,
                ai_weight = EXCLUDED.ai_weight,
                mining_weight = EXCLUDED.mining_weight,
                gpu_for_mining = EXCLUDED.gpu_for_mining,
                cpu_for_ai = EXCLUDED.cpu_for_ai,
                updated_at = NOW()
            RETURNING *
        """,
            (
                mode,
                ai_weight,
                mining_weight,
                data.get("gpu_for_mining", True),
                data.get("cpu_for_ai", True),
            ),
        )

        config = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "config": config,
                "message": f"Scheduler updated to {mode} mode",
            }
        )

    except Exception as e:
        logger.error(f"Error updating scheduler: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/mining/contributors")
def get_contributors():
    """Get mining pool contributors and their rewards"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                c.id, c.wallet_address, c.display_name, c.contributor_type,
                c.total_hashrate_contributed, c.total_blocks_found,
                c.total_rewards_earned, c.pending_rewards,
                c.ai_credits_earned, c.last_contribution,
                c.is_active, c.created_at
            FROM mining_contributors c
            WHERE c.is_active = TRUE
            ORDER BY c.total_rewards_earned DESC
            LIMIT 100
        """
        )
        contributors = cur.fetchall()

        # Get summary
        cur.execute(
            """
            SELECT
                COUNT(*) as total_contributors,
                SUM(total_hashrate_contributed) as total_hashrate,
                SUM(total_rewards_earned) as total_paid,
                SUM(pending_rewards) as total_pending
            FROM mining_contributors
            WHERE is_active = TRUE
        """
        )
        summary = cur.fetchone()

        cur.close()
        conn.close()

        # Convert datetime
        for c in contributors:
            for key in ["last_contribution", "created_at"]:
                if c.get(key):
                    c[key] = c[key].isoformat()

        return jsonify({"success": True, "contributors": contributors, "summary": summary})

    except Exception:
        # Tables might not exist
        return jsonify(
            {
                "success": True,
                "contributors": [],
                "summary": {
                    "total_contributors": 0,
                    "total_hashrate": 0,
                    "total_paid": 0,
                    "total_pending": 0,
                },
                "note": "Contributor tables not yet created",
            }
        )


@bridge_bp.route("/api/mining/contributors/register", methods=["POST"])
def register_contributor():
    """Register a new mining contributor"""
    data = request.get_json() or {}

    if not data.get("wallet_address"):
        return jsonify({"success": False, "error": "wallet_address required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO mining_contributors (
                wallet_address, display_name, contributor_type
            ) VALUES (%s, %s, %s)
            ON CONFLICT (wallet_address) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, mining_contributors.display_name),
                is_active = TRUE
            RETURNING id, wallet_address, display_name
        """,
            (
                data.get("wallet_address"),
                data.get("display_name"),
                data.get("contributor_type", "miner"),
            ),
        )

        contributor = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "contributor": contributor,
                "message": "Contributor registered",
            }
        )

    except Exception as e:
        logger.error(f"Error registering contributor: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/mining/rewards/<wallet>")
def get_contributor_rewards(wallet):
    """Get reward history for a contributor"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get contributor
        cur.execute(
            """
            SELECT * FROM mining_contributors WHERE wallet_address = %s
        """,
            (wallet,),
        )
        contributor = cur.fetchone()

        if not contributor:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Contributor not found"}), 404

        # Get reward history
        cur.execute(
            """
            SELECT
                reward_type, amount, ai_credits, block_height,
                txid, status, created_at
            FROM contributor_rewards
            WHERE contributor_id = %s
            ORDER BY created_at DESC
            LIMIT 50
        """,
            (contributor["id"],),
        )
        rewards = cur.fetchall()

        cur.close()
        conn.close()

        # Convert datetime
        for key in ["last_contribution", "created_at"]:
            if contributor.get(key):
                contributor[key] = contributor[key].isoformat()

        for r in rewards:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()

        return jsonify({"success": True, "contributor": contributor, "rewards": rewards})

    except Exception as e:
        logger.error(f"Error getting rewards: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/mining/allocate", methods=["POST"])
def allocate_resource():
    """Allocate a resource for AI or mining task"""
    data = request.get_json() or {}
    task_type = data.get("task_type")  # 'ai' or 'mining'
    resource_type = data.get("resource_type")  # 'gpu', 'cpu'
    node_id = data.get("node_id")

    if task_type not in ["ai", "mining"]:
        return (
            jsonify({"success": False, "error": "task_type must be ai or mining"}),
            400,
        )

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check scheduler config
        cur.execute("SELECT * FROM resource_scheduler_config WHERE id = 1")
        config = cur.fetchone()

        if not config:
            config = {"mode": "balanced", "ai_weight": 50, "mining_weight": 50}

        # Check current allocation
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN task_type = 'ai' THEN 1 ELSE 0 END) as ai_count,
                SUM(CASE WHEN task_type = 'mining' THEN 1 ELSE 0 END) as mining_count
            FROM resource_allocation
            WHERE is_active = TRUE
        """
        )
        current = cur.fetchone() or {"ai_count": 0, "mining_count": 0}

        # Dynamic mode: adjust based on demand
        if config["mode"] == "dynamic":
            # Simple demand-based logic
            total = (current["ai_count"] or 0) + (current["mining_count"] or 0) + 1
            if task_type == "ai":
                allowed = True  # AI always gets priority in dynamic mode
            else:
                # Mining only if AI load is low
                allowed = (current["ai_count"] or 0) < 5
        else:
            # Weight-based allocation
            total = (current["ai_count"] or 0) + (current["mining_count"] or 0)
            if total == 0:
                allowed = True
            else:
                current_ratio = ((current["ai_count"] or 0) / total) * 100 if total > 0 else 50
                if task_type == "ai":
                    allowed = current_ratio <= config["ai_weight"] or config["ai_weight"] == 100
                else:
                    allowed = (100 - current_ratio) <= config["mining_weight"] or config["mining_weight"] == 100

        if not allowed:
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Resource limit reached for {task_type} tasks",
                        "config": config,
                    }
                ),
                429,
            )

        # Create allocation
        cur.execute(
            """
            INSERT INTO resource_allocation (
                task_type, resource_type, node_id, allocated_at
            ) VALUES (%s, %s, %s, NOW())
            RETURNING id
        """,
            (task_type, resource_type, node_id),
        )

        allocation = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "allocation_id": allocation["id"],
                "message": f"Resource allocated for {task_type}",
            }
        )

    except Exception as e:
        logger.error(f"Error allocating resource: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/mining/release/<int:allocation_id>", methods=["POST"])
def release_resource(allocation_id):
    """Release an allocated resource"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE resource_allocation
            SET is_active = FALSE, released_at = NOW()
            WHERE id = %s
        """,
            (allocation_id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Resource released"})

    except Exception as e:
        logger.error(f"Error releasing resource: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/mining/pool-stats")
def get_pool_integration_stats():
    """Get mining pool stats integrated with Bridge"""
    pool_api_url = os.environ.get("POOL_API_URL", "http://localhost:8080")

    try:
        # Try to get real pool stats
        response = requests.get(f"{pool_api_url}/api/stats", timeout=5)
        if response.status_code == 200:
            pool_stats = response.json()
        else:
            pool_stats = None
    except Exception:
        pool_stats = None

    # Get Bridge node stats
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) as total_nodes,
                COUNT(*) FILTER (WHERE status = 'online') as online_nodes,
                COUNT(*) FILTER (WHERE gpu_available = TRUE) as gpu_nodes
            FROM remote_nodes
            WHERE is_active = TRUE
        """
        )
        node_stats = cur.fetchone()

        cur.close()
        conn.close()
    except Exception:
        node_stats = {"total_nodes": 0, "online_nodes": 0, "gpu_nodes": 0}

    return jsonify(
        {
            "success": True,
            "pool": pool_stats or {"hashrate": 0, "miners": 0, "blocks_found": 0, "connected": False},
            "bridge_nodes": node_stats,
            "integration_status": "active" if pool_stats else "pool_offline",
        }
    )


# ============================================================================
# IDE INTEGRATION API (Merged from cursor_integration module)
# Provides MCP Protocol support, IDE REST API, code completion for external IDEs
# ============================================================================

# Add paths for imports
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    from archie_bridge import archie_bridge

    AI_BRIDGE_AVAILABLE = True
except ImportError:
    AI_BRIDGE_AVAILABLE = False
    logger.warning("AI Bridge not available for IDE integration")


# In-memory session store for connected IDEs
connected_ides = {}
context_cache = {}


class IDESession:
    """Represents a connected IDE session"""

    def __init__(self, session_id: str, ide_type: str, workspace_path: str):
        self.session_id = session_id
        self.ide_type = ide_type  # 'cursor', 'opencode', 'vscode'
        self.workspace_path = workspace_path
        self.connected_at = datetime.now()
        self.last_activity = datetime.now()
        self.open_files = []
        self.cursor_position = {}  # {file: {line, column}}
        self.context = {}

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "ide_type": self.ide_type,
            "workspace_path": self.workspace_path,
            "connected_at": self.connected_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "open_files": self.open_files,
            "cursor_position": self.cursor_position,
            "active": (datetime.now() - self.last_activity).seconds < 300,
        }


@bridge_bp.route("/ide")
@login_required
def ide_dashboard():
    """IDE Integration dashboard"""
    return render_template("tools/ide_integration.html")


@bridge_bp.route("/api/ide/status")
def ide_status():
    """API status endpoint for IDE integration health checks"""
    active_sessions = sum(1 for s in connected_ides.values() if (datetime.now() - s.last_activity).seconds < 300)
    return jsonify(
        {
            "module": "ide_integration",
            "status": "operational",
            "healthy": True,
            "version": "2.0.0",
            "features": {
                "mcp_protocol": True,
                "websocket_bridge": True,
                "context_sharing": True,
                "code_actions": True,
                "ai_bridge": AI_BRIDGE_AVAILABLE,
            },
            "connections": {"total": len(connected_ides), "active": active_sessions},
        }
    )


@bridge_bp.route("/api/ide/connect", methods=["POST"])
def connect_ide():
    """
    Register a new IDE connection

    Expected payload:
    {
        "ide_type": "cursor" | "opencode" | "vscode",
        "workspace_path": "/path/to/project",
        "client_id": "unique-client-id",
        "capabilities": ["completion", "diagnostics", "hover"]
    }
    """
    try:
        data = request.get_json() or {}

        ide_type = data.get("ide_type", "cursor")
        workspace_path = data.get("workspace_path", "")
        client_id = data.get("client_id", "")
        capabilities = data.get("capabilities", [])

        # Generate session ID
        session_id = hashlib.sha256(f"{client_id}{workspace_path}{datetime.now().isoformat()}".encode()).hexdigest()[
            :16
        ]

        # Create session
        ide_session = IDESession(session_id, ide_type, workspace_path)
        connected_ides[session_id] = ide_session

        # Log connection
        logger.info(f"IDE connected: {ide_type} at {workspace_path} (session: {session_id})")

        # Store in database for persistence
        _log_ide_connection(session_id, ide_type, workspace_path, capabilities)

        return jsonify(
            {
                "success": True,
                "session_id": session_id,
                "message": f"{ide_type.upper()} connected successfully",
                "endpoints": {
                    "context": f"/tools/bridge/api/ide/context/{session_id}",
                    "complete": f"/tools/bridge/api/ide/complete/{session_id}",
                    "actions": f"/tools/bridge/api/ide/actions/{session_id}",
                    "diagnostics": f"/tools/bridge/api/ide/diagnostics/{session_id}",
                    "disconnect": f"/tools/bridge/api/ide/disconnect/{session_id}",
                },
            }
        )

    except Exception as e:
        logger.error(f"IDE connection error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/ide/disconnect/<session_id>", methods=["POST"])
def disconnect_ide(session_id):
    """Disconnect an IDE session"""
    if session_id in connected_ides:
        del connected_ides[session_id]
        logger.info(f"IDE disconnected: {session_id}")
        return jsonify({"success": True, "message": "Disconnected"})
    return jsonify({"success": False, "error": "Session not found"}), 404


@bridge_bp.route("/api/ide/sessions")
@login_required
def list_ide_sessions():
    """List all connected IDE sessions"""
    sessions = [s.to_dict() for s in connected_ides.values()]
    return jsonify({"success": True, "sessions": sessions, "total": len(sessions)})


@bridge_bp.route("/api/ide/context/<session_id>", methods=["GET", "POST"])
def ide_context_api(session_id):
    """Get or update context for an IDE session"""
    if session_id not in connected_ides:
        return jsonify({"success": False, "error": "Session not found"}), 404

    ide_session = connected_ides[session_id]
    ide_session.last_activity = datetime.now()

    if request.method == "POST":
        data = request.get_json() or {}

        # Update session context
        if "open_files" in data:
            ide_session.open_files = data["open_files"]
        if "active_file" in data:
            ide_session.context["active_file"] = data["active_file"]
        if "cursor_position" in data:
            active_file = data.get("active_file", "")
            ide_session.cursor_position[active_file] = data["cursor_position"]
        if "selection" in data:
            ide_session.context["selection"] = data["selection"]
        if "visible_range" in data:
            ide_session.context["visible_range"] = data["visible_range"]

        return jsonify({"success": True, "message": "Context updated"})

    else:  # GET
        return jsonify({"success": True, "context": ide_session.to_dict()})


@bridge_bp.route("/api/ide/complete/<session_id>", methods=["POST"])
def ide_code_completion(session_id):
    """Get AI-powered code completions"""
    if session_id not in connected_ides:
        return jsonify({"success": False, "error": "Session not found"}), 404

    if not AI_BRIDGE_AVAILABLE:
        return jsonify({"success": False, "error": "AI Bridge not available"}), 503

    try:
        data = request.get_json() or {}
        file_path = data.get("file_path", "")
        prefix = data.get("prefix", "")
        suffix = data.get("suffix", "")

        # Build completion prompt
        language = _detect_language(file_path)

        prompt = f"""Complete the following {language} code. Only provide the completion, no explanation.

File: {file_path}

Code before cursor:
```{language}
{prefix[-500:] if len(prefix) > 500 else prefix}
```

Code after cursor:
```{language}
{suffix[:200] if len(suffix) > 200 else suffix}
```

Provide the code completion (just the code, nothing else):"""

        # Get completion from AI
        from ai_bridge.bridge_dispatcher import get_dispatcher

        _disp = get_dispatcher()
        _completion_model = _disp.get_model_for_capability("code") if _disp else ""
        result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False, force_model=_completion_model or None)

        if result.get("success"):
            completion = result["response"].strip()
            # Clean up completion
            if completion.startswith("```"):
                completion = completion.split("\n", 1)[1] if "\n" in completion else completion
            if completion.endswith("```"):
                completion = completion.rsplit("```", 1)[0]

            return jsonify(
                {
                    "success": True,
                    "completions": [
                        {
                            "text": completion.strip(),
                            "kind": "text",
                            "detail": "A.R.C.H.I.E. suggestion",
                        }
                    ],
                }
            )
        else:
            return jsonify({"success": False, "error": result.get("error", "Completion failed")})

    except Exception as e:
        logger.error(f"Completion error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/ide/actions/<session_id>", methods=["POST"])
def ide_code_actions(session_id):
    """Get available code actions for a selection"""
    if session_id not in connected_ides:
        return jsonify({"success": False, "error": "Session not found"}), 404

    try:
        data = request.get_json() or {}
        file_path = data.get("file_path", "")
        content = data.get("content", "")
        selection = data.get("selection", {})
        diagnostics = data.get("diagnostics", [])

        actions = []

        # Extract selected code
        if selection and content:
            lines = content.split("\n")
            start_line = selection.get("start", {}).get("line", 0)
            end_line = selection.get("end", {}).get("line", start_line)
            selected_lines = lines[start_line : end_line + 1]
            selected_code = "\n".join(selected_lines)

            # Add context-aware actions
            language = _detect_language(file_path)

            actions.extend(
                [
                    {
                        "title": "Explain this code",
                        "kind": "archie.explain",
                        "command": "archie.explain",
                        "arguments": {"code": selected_code, "language": language},
                    },
                    {
                        "title": "Refactor with A.R.C.H.I.E.",
                        "kind": "archie.refactor",
                        "command": "archie.refactor",
                        "arguments": {"code": selected_code, "language": language},
                    },
                    {
                        "title": "Add documentation",
                        "kind": "archie.document",
                        "command": "archie.document",
                        "arguments": {"code": selected_code, "language": language},
                    },
                    {
                        "title": "Generate tests",
                        "kind": "archie.test",
                        "command": "archie.test",
                        "arguments": {"code": selected_code, "language": language},
                    },
                ]
            )

            # Add fix actions for diagnostics
            for diag in diagnostics:
                if diag.get("severity") in ["error", "warning"]:
                    actions.append(
                        {
                            "title": f"Fix: {diag.get('message', 'Issue')[:50]}",
                            "kind": "archie.fix",
                            "command": "archie.fix",
                            "arguments": {
                                "code": selected_code,
                                "diagnostic": diag,
                                "language": language,
                            },
                            "isPreferred": True,
                        }
                    )

        return jsonify({"success": True, "actions": actions})

    except Exception as e:
        logger.error(f"Code actions error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/ide/actions/<session_id>/execute", methods=["POST"])
def ide_execute_action(session_id):
    """Execute a code action"""
    if session_id not in connected_ides:
        return jsonify({"success": False, "error": "Session not found"}), 404

    if not AI_BRIDGE_AVAILABLE:
        return jsonify({"success": False, "error": "AI Bridge not available"}), 503

    try:
        data = request.get_json() or {}
        action = data.get("action", "")
        args = data.get("arguments", {})
        code = args.get("code", "")
        language = args.get("language", "python")

        # Build prompt based on action
        if action == "archie.explain":
            prompt = f"""Explain this {language} code clearly and concisely:

```{language}
{code}
```

Provide a brief explanation of what the code does, any important patterns used, and potential considerations."""

        elif action == "archie.refactor":
            prompt = f"""Refactor this {language} code to improve readability, performance, or maintainability:

```{language}
{code}
```

Provide the refactored code with brief comments explaining the improvements. Only output the improved code."""

        elif action == "archie.document":
            prompt = f"""Add comprehensive documentation to this {language} code:

```{language}
{code}
```

Add docstrings, type hints, and inline comments where appropriate. Output only the documented code."""

        elif action == "archie.test":
            prompt = f"""Generate unit tests for this {language} code:

```{language}
{code}
```

Create comprehensive test cases. Use pytest for Python, jest for JS."""

        elif action == "archie.fix":
            diagnostic = args.get("diagnostic", {})
            prompt = f"""Fix this {language} code issue:

Issue: {diagnostic.get('message', 'Unknown issue')}
Severity: {diagnostic.get('severity', 'warning')}

Code:
```{language}
{code}
```

Provide the corrected code only, no explanations."""

        else:
            return (
                jsonify({"success": False, "error": f"Unknown action: {action}"}),
                400,
            )

        # Execute with AI
        from ai_bridge.bridge_dispatcher import get_dispatcher

        _disp = get_dispatcher()
        _action_model = _disp.get_model_for_capability("code") if _disp else ""
        result = archie_bridge(prompt=prompt, user_id=1, enable_memory=True, force_model=_action_model or None)

        if result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "result": result["response"],
                    "model": result.get("model", "unknown"),
                }
            )
        else:
            return jsonify({"success": False, "error": result.get("error", "Action failed")})

    except Exception as e:
        logger.error(f"Action execution error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/ide/diagnostics/<session_id>", methods=["POST"])
def ide_get_diagnostics(session_id):
    """Get AI-powered diagnostics for a file"""
    if session_id not in connected_ides:
        return jsonify({"success": False, "error": "Session not found"}), 404

    try:
        data = request.get_json() or {}
        file_path = data.get("file_path", "")
        content = data.get("content", "")

        # Get static analysis diagnostics
        diagnostics = _static_analysis(file_path, content)

        return jsonify({"success": True, "diagnostics": diagnostics, "file_path": file_path})

    except Exception as e:
        logger.error(f"Diagnostics error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# MCP Protocol Endpoints


@bridge_bp.route("/mcp/manifest")
def mcp_manifest():
    """MCP Protocol manifest for AI assistants"""
    return jsonify(
        {
            "name": "A.R.C.H.I.E. IDE Integration",
            "version": "2.0.0",
            "description": "AI-powered code assistance from A.R.C.H.I.E.",
            "tools": [
                {
                    "name": "archie_search",
                    "description": "Search A.R.C.H.I.E. knowledge base for code patterns and solutions",
                    "parameters": {"query": {"type": "string", "description": "Search query"}},
                },
                {
                    "name": "archie_complete",
                    "description": "Get code completion suggestions",
                    "parameters": {
                        "prefix": {
                            "type": "string",
                            "description": "Code before cursor",
                        },
                        "suffix": {
                            "type": "string",
                            "description": "Code after cursor",
                        },
                        "language": {
                            "type": "string",
                            "description": "Programming language",
                        },
                    },
                },
                {
                    "name": "archie_explain",
                    "description": "Explain code functionality",
                    "parameters": {"code": {"type": "string", "description": "Code to explain"}},
                },
                {
                    "name": "archie_fix",
                    "description": "Fix code issues",
                    "parameters": {
                        "code": {"type": "string", "description": "Code to fix"},
                        "issue": {"type": "string", "description": "Issue description"},
                    },
                },
            ],
            "resources": [
                {
                    "name": "knowledge_base",
                    "description": "A.R.C.H.I.E. unified knowledge base",
                    "uri": "/tools/bridge/mcp/knowledge",
                }
            ],
        }
    )


@bridge_bp.route("/mcp/tools/<tool_name>", methods=["POST"])
def mcp_tool(tool_name):
    """Execute an MCP tool"""
    try:
        data = request.get_json() or {}

        if tool_name == "archie_search":
            query = data.get("query", "")
            results = _search_knowledge_base(query)
            return jsonify({"success": True, "results": results})

        elif tool_name == "archie_complete":
            prefix = data.get("prefix", "")
            suffix = data.get("suffix", "")  # noqa: F841
            language = data.get("language", "python")

            if not AI_BRIDGE_AVAILABLE:
                return jsonify({"success": False, "error": "AI not available"})

            prompt = f"Complete this {language} code:\n\n{prefix[-300:]}"
            result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False)

            if result.get("success"):
                return jsonify({"success": True, "completion": result["response"]})
            return jsonify({"success": False, "error": "Completion failed"})

        elif tool_name == "archie_explain":
            code = data.get("code", "")
            if not AI_BRIDGE_AVAILABLE:
                return jsonify({"success": False, "error": "AI not available"})

            prompt = f"Explain this code concisely:\n\n```\n{code}\n```"
            result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False)

            if result.get("success"):
                return jsonify({"success": True, "explanation": result["response"]})
            return jsonify({"success": False, "error": "Explanation failed"})

        elif tool_name == "archie_fix":
            code = data.get("code", "")
            issue = data.get("issue", "")
            if not AI_BRIDGE_AVAILABLE:
                return jsonify({"success": False, "error": "AI not available"})

            prompt = f"Fix this code issue:\n\nIssue: {issue}\n\n```\n{code}\n```\n\nProvide only the fixed code."
            result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False)

            if result.get("success"):
                return jsonify({"success": True, "fixed_code": result["response"]})
            return jsonify({"success": False, "error": "Fix failed"})

        else:
            return (
                jsonify({"success": False, "error": f"Unknown tool: {tool_name}"}),
                404,
            )

    except Exception as e:
        logger.error(f"MCP tool error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/mcp/knowledge")
def mcp_knowledge():
    """Access knowledge base via MCP"""
    query = request.args.get("query", "")
    limit = request.args.get("limit", 10, type=int)

    results = _search_knowledge_base(query, limit=limit)
    return jsonify({"success": True, "results": results, "total": len(results)})


# IDE Helper Functions


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension"""
    ext = os.path.splitext(file_path)[1].lower()
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
    }
    return lang_map.get(ext, "text")


def _search_knowledge_base(query: str, limit: int = 10) -> List[Dict]:
    """Search A.R.C.H.I.E.'s knowledge base"""
    if not query:
        return []

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, title, content, knowledge_type, importance_score,
                   ts_rank(search_vector, plainto_tsquery('english', %s)) as rank
            FROM knowledge_base
            WHERE search_vector @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC, importance_score DESC
            LIMIT %s
        """,
            (query, query, limit),
        )

        results = cur.fetchall()
        cur.close()
        conn.close()

        return [dict(r) for r in results]

    except Exception as e:
        logger.warning(f"Knowledge search error: {e}")
        return []


def _static_analysis(file_path: str, content: str) -> List[Dict]:
    """Perform basic static analysis"""
    import re

    diagnostics = []
    lines = content.split("\n")
    language = _detect_language(file_path)

    if language == "python":
        for i, line in enumerate(lines):
            # Bare except
            if re.search(r"except\s*:", line):
                diagnostics.append(
                    {
                        "line": i,
                        "column": line.index("except"),
                        "severity": "warning",
                        "message": "Bare except clause catches all exceptions",
                        "source": "archie-lint",
                    }
                )

            # Print statements
            if re.search(r"^\s*print\s*\(", line):
                diagnostics.append(
                    {
                        "line": i,
                        "column": line.index("print"),
                        "severity": "info",
                        "message": "Consider using logging instead of print",
                        "source": "archie-lint",
                    }
                )

            # TODO/FIXME
            match = re.search(r"#\s*(TODO|FIXME|XXX)", line, re.IGNORECASE)
            if match:
                diagnostics.append(
                    {
                        "line": i,
                        "column": match.start(),
                        "severity": "info",
                        "message": f"{match.group(1)} found",
                        "source": "archie-lint",
                    }
                )

    elif language in ("javascript", "typescript"):
        for i, line in enumerate(lines):
            # console.log
            if "console.log" in line:
                diagnostics.append(
                    {
                        "line": i,
                        "column": line.index("console"),
                        "severity": "info",
                        "message": "Remove console.log before production",
                        "source": "archie-lint",
                    }
                )

            # var usage
            if re.search(r"\bvar\s+", line):
                diagnostics.append(
                    {
                        "line": i,
                        "column": line.index("var"),
                        "severity": "warning",
                        "message": "Use const or let instead of var",
                        "source": "archie-lint",
                    }
                )

    return diagnostics


def _log_ide_connection(session_id: str, ide_type: str, workspace_path: str, capabilities: List[str]):
    """Log IDE connection to database"""
    import json as json_module

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Ensure table exists
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ide_connections (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(50) UNIQUE,
                ide_type VARCHAR(50),
                workspace_path TEXT,
                capabilities JSONB,
                connected_at TIMESTAMP DEFAULT NOW(),
                last_activity TIMESTAMP DEFAULT NOW(),
                disconnected_at TIMESTAMP
            )
        """
        )

        cur.execute(
            """
            INSERT INTO ide_connections (session_id, ide_type, workspace_path, capabilities)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE
            SET last_activity = NOW()
        """,
            (session_id, ide_type, workspace_path, json_module.dumps(capabilities)),
        )

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        logger.warning(f"Failed to log IDE connection: {e}")


# ============================================================================
# AGENT TRAINING API (Merged from fine_tuning module)
# Provides model training interface, datasets, training jobs, model deployment
# ============================================================================


@bridge_bp.route("/training")
@login_required
def training_dashboard():
    """AI Model Training dashboard"""
    return render_template("tools/fine_tuning.html")


@bridge_bp.route("/api/training/status")
@login_required
def training_status():
    """API endpoint for training module health check"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ft_base_models WHERE is_available = TRUE")
        model_count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify(
            {
                "module": "agent_training",
                "status": "active",
                "healthy": True,
                "available_models": model_count,
                "message": "AI Training module operational",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "module": "agent_training",
                "status": "error",
                "healthy": False,
                "message": str(e),
            }
        )


@bridge_bp.route("/api/training/stats")
@login_required
def get_training_stats():
    """Get user's training statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_ft_user_stats WHERE user_id = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Get active jobs
        cur.execute(
            """
            SELECT COUNT(*) FROM ft_training_jobs
            WHERE user_id = %s AND status IN ('queued', 'preparing', 'training')
        """,
            (current_user.id,),
        )
        active_jobs = cur.fetchone()["count"]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_datasets": stats["total_datasets"] if stats else 0,
                    "total_jobs": stats["total_jobs"] if stats else 0,
                    "completed_jobs": stats["completed_jobs"] if stats else 0,
                    "active_jobs": active_jobs,
                    "total_models": stats["total_models"] if stats else 0,
                    "deployed_models": stats["deployed_models"] if stats else 0,
                },
            }
        )
    except Exception as e:
        logger.error(f"Failed to get training stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/base-models")
@login_required
def get_training_base_models():
    """Get available base models for fine-tuning"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM ft_base_models
            WHERE is_available = TRUE AND supports_fine_tuning = TRUE
            ORDER BY provider, parameters
        """
        )
        models = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "models": models})
    except Exception as e:
        logger.error(f"Failed to get base models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/datasets")
@login_required
def get_training_datasets():
    """Get user's training datasets"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, description, dataset_type, source_type,
                   total_samples, train_samples, validation_samples,
                   status, size_bytes, created_at, updated_at
            FROM ft_datasets
            WHERE user_id = %s
            ORDER BY created_at DESC
        """,
            (current_user.id,),
        )
        datasets = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "datasets": datasets})
    except Exception as e:
        logger.error(f"Failed to get datasets: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/datasets", methods=["POST"])
@login_required
def create_training_dataset():
    """Create a new training dataset"""
    try:
        data = request.get_json() or {}
        name = data.get("name", "").strip()
        description = data.get("description", "")
        dataset_type = data.get("type", "conversation")

        if not name:
            return jsonify({"success": False, "error": "Dataset name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO ft_datasets (user_id, name, description, dataset_type, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id, name, description, dataset_type, status, created_at
        """,
            (current_user.id, name, description, dataset_type),
        )

        dataset = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "dataset": dataset,
                "message": "Dataset created successfully",
            }
        )
    except psycopg2.errors.UniqueViolation:
        return (
            jsonify({"success": False, "error": "Dataset with this name already exists"}),
            400,
        )
    except Exception as e:
        logger.error(f"Failed to create dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/datasets/<int:dataset_id>")
@login_required
def get_training_dataset(dataset_id):
    """Get dataset details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM ft_datasets
            WHERE id = %s AND user_id = %s
        """,
            (dataset_id, current_user.id),
        )
        dataset = cur.fetchone()

        cur.close()
        conn.close()

        if not dataset:
            return jsonify({"success": False, "error": "Dataset not found"}), 404

        return jsonify({"success": True, "dataset": dataset})
    except Exception as e:
        logger.error(f"Failed to get dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/datasets/<int:dataset_id>/upload", methods=["POST"])
@login_required
def upload_training_data(dataset_id):
    """Upload data to a dataset (JSONL format)"""
    try:
        data = request.get_json() or {}
        samples = data.get("samples", [])

        if not samples:
            return jsonify({"success": False, "error": "No samples provided"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute(
            "SELECT id FROM ft_datasets WHERE id = %s AND user_id = %s",
            (dataset_id, current_user.id),
        )
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Dataset not found"}), 404

        # Update dataset with samples
        import json as json_module

        total = len(samples)
        train_count = int(total * 0.8)
        val_count = int(total * 0.1)
        test_count = total - train_count - val_count

        cur.execute(
            """
            UPDATE ft_datasets
            SET total_samples = %s, train_samples = %s, validation_samples = %s,
                test_samples = %s, sample_data = %s, status = 'ready', updated_at = NOW()
            WHERE id = %s
            RETURNING id, total_samples, status
        """,
            (
                total,
                train_count,
                val_count,
                test_count,
                json_module.dumps(samples[:5]),
                dataset_id,
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "dataset": result,
                "message": f"Uploaded {total} samples successfully",
            }
        )
    except Exception as e:
        logger.error(f"Failed to upload dataset data: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/datasets/<int:dataset_id>", methods=["DELETE"])
@login_required
def delete_training_dataset(dataset_id):
    """Delete a training dataset"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM ft_datasets
            WHERE id = %s AND user_id = %s
            RETURNING id
        """,
            (dataset_id, current_user.id),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Dataset not found"}), 404

        return jsonify({"success": True, "message": "Dataset deleted successfully"})
    except Exception as e:
        logger.error(f"Failed to delete dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/jobs")
@login_required
def get_training_jobs():
    """Get user's training jobs"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT j.*, m.model_name as base_model_name, d.name as dataset_name
            FROM ft_training_jobs j
            LEFT JOIN ft_base_models m ON j.base_model_id = m.id
            LEFT JOIN ft_datasets d ON j.dataset_id = d.id
            WHERE j.user_id = %s
            ORDER BY j.created_at DESC
        """,
            (current_user.id,),
        )
        jobs = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "jobs": jobs})
    except Exception as e:
        logger.error(f"Failed to get training jobs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/jobs", methods=["POST"])
@login_required
def create_training_job():
    """Create a new training job"""
    try:
        data = request.get_json() or {}

        job_name = data.get("name", "").strip()
        base_model_id = data.get("base_model_id")
        dataset_id = data.get("dataset_id")
        training_method = data.get("training_method", "lora")
        epochs = data.get("epochs", 3)
        batch_size = data.get("batch_size", 4)
        learning_rate = data.get("learning_rate", 2e-5)

        if not job_name:
            return jsonify({"success": False, "error": "Job name is required"}), 400
        if not base_model_id:
            return jsonify({"success": False, "error": "Base model is required"}), 400
        if not dataset_id:
            return jsonify({"success": False, "error": "Dataset is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify dataset ownership and readiness
        cur.execute(
            """
            SELECT id, total_samples FROM ft_datasets
            WHERE id = %s AND user_id = %s AND status = 'ready'
        """,
            (dataset_id, current_user.id),
        )
        dataset = cur.fetchone()
        if not dataset:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Dataset not found or not ready"}),
                400,
            )

        # Calculate total steps
        total_steps = (dataset["total_samples"] // batch_size) * epochs

        cur.execute(
            """
            INSERT INTO ft_training_jobs
            (user_id, job_name, base_model_id, dataset_id, training_method,
             epochs, batch_size, learning_rate, total_steps, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')
            RETURNING id, job_name, status, created_at
        """,
            (
                current_user.id,
                job_name,
                base_model_id,
                dataset_id,
                training_method,
                epochs,
                batch_size,
                learning_rate,
                total_steps,
            ),
        )

        job = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "job": job, "message": "Training job created and queued"})
    except Exception as e:
        logger.error(f"Failed to create training job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/jobs/<int:job_id>")
@login_required
def get_training_job(job_id):
    """Get training job details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT j.*, m.model_name as base_model_name, m.model_id as base_model_id_str,
                   d.name as dataset_name, d.total_samples
            FROM ft_training_jobs j
            LEFT JOIN ft_base_models m ON j.base_model_id = m.id
            LEFT JOIN ft_datasets d ON j.dataset_id = d.id
            WHERE j.id = %s AND j.user_id = %s
        """,
            (job_id, current_user.id),
        )
        job = cur.fetchone()

        cur.close()
        conn.close()

        if not job:
            return jsonify({"success": False, "error": "Job not found"}), 404

        return jsonify({"success": True, "job": job})
    except Exception as e:
        logger.error(f"Failed to get training job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/jobs/<int:job_id>/start", methods=["POST"])
@login_required
def start_training_job(job_id):
    """Start a queued training job"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE ft_training_jobs
            SET status = 'preparing', started_at = NOW(), updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status = 'queued'
            RETURNING id, status
        """,
            (job_id, current_user.id),
        )

        job = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not job:
            return (
                jsonify({"success": False, "error": "Job not found or already started"}),
                404,
            )

        return jsonify({"success": True, "job": job, "message": "Training job started"})
    except Exception as e:
        logger.error(f"Failed to start training job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel_training_job(job_id):
    """Cancel a running training job"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE ft_training_jobs
            SET status = 'cancelled', updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status IN ('queued', 'preparing', 'training')
            RETURNING id, status
        """,
            (job_id, current_user.id),
        )

        job = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not job:
            return (
                jsonify({"success": False, "error": "Job not found or cannot be cancelled"}),
                404,
            )

        return jsonify({"success": True, "job": job, "message": "Training job cancelled"})
    except Exception as e:
        logger.error(f"Failed to cancel training job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/models")
@login_required
def get_trained_models():
    """Get user's fine-tuned models"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT m.*, b.model_name as base_model_name, j.job_name as training_job_name
            FROM ft_models m
            LEFT JOIN ft_base_models b ON m.base_model_id = b.id
            LEFT JOIN ft_training_jobs j ON m.training_job_id = j.id
            WHERE m.user_id = %s
            ORDER BY m.created_at DESC
        """,
            (current_user.id,),
        )
        models = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "models": models})
    except Exception as e:
        logger.error(f"Failed to get trained models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/models/<int:model_id>")
@login_required
def get_trained_model(model_id):
    """Get trained model details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT m.*, b.model_name as base_model_name, j.job_name as training_job_name
            FROM ft_models m
            LEFT JOIN ft_base_models b ON m.base_model_id = b.id
            LEFT JOIN ft_training_jobs j ON m.training_job_id = j.id
            WHERE m.id = %s AND m.user_id = %s
        """,
            (model_id, current_user.id),
        )
        model = cur.fetchone()

        cur.close()
        conn.close()

        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        return jsonify({"success": True, "model": model})
    except Exception as e:
        logger.error(f"Failed to get trained model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/models/<int:model_id>/deploy", methods=["POST"])
@login_required
def deploy_trained_model(model_id):
    """Deploy a fine-tuned model to Ollama"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE ft_models
            SET is_deployed = TRUE, status = 'deployed', updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status = 'ready'
            RETURNING id, model_name, model_id as ollama_model_id
        """,
            (model_id, current_user.id),
        )

        model = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not model:
            return (
                jsonify({"success": False, "error": "Model not found or not ready"}),
                404,
            )

        return jsonify(
            {
                "success": True,
                "model": model,
                "message": f"Model {model['model_name']} deployed successfully",
            }
        )
    except Exception as e:
        logger.error(f"Failed to deploy model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/models/<int:model_id>", methods=["DELETE"])
@login_required
def delete_trained_model(model_id):
    """Delete a fine-tuned model"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM ft_models
            WHERE id = %s AND user_id = %s
            RETURNING id
        """,
            (model_id, current_user.id),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Model not found"}), 404

        return jsonify({"success": True, "message": "Model deleted successfully"})
    except Exception as e:
        logger.error(f"Failed to delete model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/models/<int:model_id>/test", methods=["POST"])
@login_required
def test_trained_model(model_id):
    """Test a fine-tuned model with a prompt"""
    try:
        data = request.get_json() or {}
        prompt = data.get("prompt", "").strip()

        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT model_id, model_name, is_deployed
            FROM ft_models
            WHERE id = %s AND user_id = %s
        """,
            (model_id, current_user.id),
        )
        model = cur.fetchone()

        cur.close()
        conn.close()

        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        # Use AI bridge if model is deployed
        if model["is_deployed"] and AI_BRIDGE_AVAILABLE:
            result = archie_bridge(
                prompt=prompt,
                user_id=current_user.id,
                enable_memory=False,
                force_model=model["model_id"],
            )
            if result.get("success"):
                return jsonify(
                    {
                        "success": True,
                        "response": result["response"],
                        "model": model["model_name"],
                    }
                )

        # Demo response for non-deployed models
        demo_response = f"[Demo] Response from {model['model_name']} to: {prompt[:50]}..."

        return jsonify(
            {
                "success": True,
                "response": demo_response,
                "model": model["model_name"],
                "note": "Demo response - deploy model for real inference",
            }
        )
    except Exception as e:
        logger.error(f"Failed to test model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DISPATCH ACTIVITY API (Project #91 — Phase 6)
# ============================================================================


@bridge_bp.route("/api/bridge/dispatch-status")
@login_required
def get_dispatch_status():
    """Get current BridgeDispatcher status: active agents, assignments, queue depth"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Active agents with their station assignments
        cur.execute(
            """
            SELECT a.id, a.name, a.first_name, a.last_name, a.title, a.model,
                   a.status, a.avatar_url,
                   bs.station_code, bs.station_name, bs.color,
                   sa.assignment_type
            FROM agents a
            LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
            LEFT JOIN bridge_stations bs ON bs.id = sa.station_id AND bs.is_active = TRUE
            WHERE a.status = 'active'
            ORDER BY bs.position_row, bs.position_order, a.name
        """
        )
        agents = cur.fetchall()

        # Recent dispatch activity (rolling 24h)
        cur.execute(
            """
            SELECT COUNT(*) as total_dispatches,
                   COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                   COUNT(CASE WHEN success = FALSE THEN 1 END) as failed,
                   COALESCE(AVG(duration_ms), 0) as avg_duration_ms
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """
        )
        dispatch_stats = cur.fetchone()

        # Active tasks (in-progress right now — last 2 minutes)
        cur.execute(
            """
            SELECT tel.id, a.name as agent_name, tel.module_source,
                   tel.task_type, tel.model_used, tel.created_at
            FROM task_execution_log tel
            LEFT JOIN agents a ON a.id = tel.agent_id
            WHERE tel.created_at > NOW() - INTERVAL '2 minutes'
                  AND tel.success IS NULL
            ORDER BY tel.created_at DESC
            LIMIT 10
        """
        )
        active_tasks = cur.fetchall()

        # Per-station dispatch counts (last 24h)
        cur.execute(
            """
            SELECT bs.station_code, bs.station_name, bs.color,
                   COUNT(tel.id) as dispatch_count,
                   COALESCE(AVG(tel.duration_ms), 0) as avg_ms
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON sa.station_id = bs.id AND sa.is_active = TRUE
            LEFT JOIN task_execution_log tel ON tel.agent_id = sa.agent_id
                  AND tel.created_at > NOW() - INTERVAL '24 hours'
            WHERE bs.is_active = TRUE
            GROUP BY bs.station_code, bs.station_name, bs.color
            ORDER BY dispatch_count DESC
        """
        )
        station_activity = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "agents": [
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "first_name": a.get("first_name"),
                        "last_name": a.get("last_name"),
                        "title": a["title"],
                        "model": a["model"],
                        "status": a["status"],
                        "avatar_url": a.get("avatar_url"),
                        "station_code": a.get("station_code"),
                        "station_name": a.get("station_name"),
                        "station_color": a.get("color"),
                        "assignment_type": a.get("assignment_type"),
                    }
                    for a in agents
                ],
                "dispatch_stats": {
                    "total_1h": dispatch_stats["total_dispatches"],
                    "total_24h": dispatch_stats["total_dispatches"],
                    "successful_1h": dispatch_stats["successful"],
                    "successful_24h": dispatch_stats["successful"],
                    "failed_1h": dispatch_stats["failed"],
                    "failed_24h": dispatch_stats["failed"],
                    "avg_duration_ms": round(float(dispatch_stats["avg_duration_ms"]), 1),
                },
                "active_tasks": [
                    {
                        "id": t["id"],
                        "agent_name": t["agent_name"],
                        "module": t["module_source"],
                        "task_type": t["task_type"],
                        "model": t["model_used"],
                        "started": t["created_at"].isoformat() if t["created_at"] else None,
                    }
                    for t in active_tasks
                ],
                "station_activity": [
                    {
                        "station_code": s["station_code"],
                        "station_name": s["station_name"],
                        "color": s["color"],
                        "dispatch_count": s["dispatch_count"],
                        "avg_ms": round(float(s["avg_ms"]), 1),
                    }
                    for s in station_activity
                ],
            }
        )

    except Exception as e:
        logger.error(f"Error getting dispatch status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/dispatch-history")
@login_required
def get_dispatch_history():
    """Get recent task execution history for the Bridge dispatch panel"""
    try:
        limit = request.args.get("limit", 50, type=int)
        limit = min(limit, 200)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT tel.id,
                   COALESCE(
                       NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                       a.name,
                       tel.agent_name
                   ) as agent_display_name,
                   COALESCE(a.name, tel.agent_name) as agent_callsign,
                   a.avatar_url,
                   tel.module_source, tel.task_type, tel.capability,
                   tel.model_used, tel.duration_ms, tel.success,
                   tel.error_message, tel.created_at,
                   bs.station_code, bs.color as station_color
            FROM task_execution_log tel
            LEFT JOIN agents a ON a.id = tel.agent_id
            LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
            LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
            WHERE tel.created_at > NOW() - INTERVAL '24 hours'
            ORDER BY tel.created_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        history = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "history": [
                    {
                        "id": h["id"],
                        "agent_name": h["agent_display_name"] or h.get("agent_callsign") or "Unknown",
                        "avatar_url": h.get("avatar_url"),
                        "module": h["module_source"],
                        "task_type": h["task_type"],
                        "capability": h.get("capability"),
                        "model": h["model_used"],
                        "duration_ms": h["duration_ms"],
                        "success": h["success"],
                        "error": h.get("error_message"),
                        "timestamp": h["created_at"].isoformat() if h["created_at"] else None,
                        "station_code": h.get("station_code"),
                        "station_color": h.get("station_color"),
                    }
                    for h in history
                ],
                "total": len(history),
            }
        )

    except Exception as e:
        logger.error(f"Error getting dispatch history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# BRIDGE JOBS — Workload tracking for multi-step operations
# ============================================================================


@bridge_bp.route("/api/bridge/jobs")
@login_required
def get_bridge_jobs():
    """Get active and recent bridge jobs with progress info."""
    try:
        limit = request.args.get("limit", 20, type=int)
        limit = min(limit, 100)
        status_filter = request.args.get("status")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if status_filter:
            cur.execute(
                """
                SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                       bj.total_steps, bj.completed_steps, bj.failed_steps,
                       bj.status,
                       COALESCE(
                           NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                           a.name,
                           bj.agent_name
                       ) as agent_display_name,
                       bj.agent_name as agent_callsign,
                       bj.metadata,
                       bj.created_at, bj.updated_at, bj.completed_at
                FROM bridge_jobs bj
                LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
                WHERE bj.status = %s
                ORDER BY bj.created_at DESC
                LIMIT %s
                """,
                (status_filter, limit),
            )
        else:
            cur.execute(
                """
                SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                       bj.total_steps, bj.completed_steps, bj.failed_steps,
                       bj.status,
                       COALESCE(
                           NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                           a.name,
                           bj.agent_name
                       ) as agent_display_name,
                       bj.agent_name as agent_callsign,
                       bj.metadata,
                       bj.created_at, bj.updated_at, bj.completed_at
                FROM bridge_jobs bj
                LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
                ORDER BY
                    CASE bj.status
                        WHEN 'running' THEN 0
                        WHEN 'pending' THEN 1
                        ELSE 2
                    END,
                    bj.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        jobs = cur.fetchall()
        cur.close()
        conn.close()

        now = datetime.utcnow()
        result = []
        for j in jobs:
            total = j["total_steps"] or 1
            completed = j["completed_steps"] or 0
            progress_pct = round((completed / total) * 100, 1) if total > 0 else 0

            # Estimate ETA for running jobs
            eta_seconds = None
            if j["status"] == "running" and completed > 0 and j["created_at"]:
                elapsed = (now - j["created_at"].replace(tzinfo=None)).total_seconds()
                per_step = elapsed / completed
                remaining = total - completed
                eta_seconds = int(per_step * remaining)

            result.append(
                {
                    "id": j["id"],
                    "job_type": j["job_type"],
                    "module_source": j["module_source"],
                    "description": j["description"],
                    "total_steps": total,
                    "completed_steps": completed,
                    "failed_steps": j["failed_steps"] or 0,
                    "status": j["status"],
                    "agent_name": j.get("agent_display_name") or j.get("agent_callsign") or "Unknown",
                    "metadata": j["metadata"] or {},
                    "progress_pct": progress_pct,
                    "eta_seconds": eta_seconds,
                    "created_at": j["created_at"].isoformat() if j["created_at"] else None,
                    "updated_at": j["updated_at"].isoformat() if j["updated_at"] else None,
                    "completed_at": j["completed_at"].isoformat() if j["completed_at"] else None,
                }
            )

        return jsonify({"success": True, "jobs": result, "total": len(result)})

    except Exception as e:
        logger.error(f"Error getting bridge jobs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/jobs/<int:job_id>")
@login_required
def get_bridge_job_detail(job_id):
    """Get single bridge job detail with linked execution log entries."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the job
        cur.execute(
            """
            SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                   bj.total_steps, bj.completed_steps, bj.failed_steps,
                   bj.status,
                   COALESCE(
                       NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                       a.name,
                       bj.agent_name
                   ) as agent_display_name,
                   bj.metadata,
                   bj.created_at, bj.updated_at, bj.completed_at
            FROM bridge_jobs bj
            LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
            WHERE bj.id = %s
            """,
            (job_id,),
        )
        job = cur.fetchone()
        if not job:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Job not found"}), 404

        # Get linked execution log entries
        cur.execute(
            """
            SELECT tel.id,
                   COALESCE(
                       NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                       a.name,
                       tel.agent_name
                   ) as agent_name,
                   tel.capability,
                   tel.model_used, tel.duration_ms, tel.success,
                   tel.error_message, tel.created_at
            FROM task_execution_log tel
            LEFT JOIN agents a ON a.id = tel.agent_id
            WHERE tel.job_id = %s
            ORDER BY tel.created_at
            """,
            (job_id,),
        )
        executions = cur.fetchall()
        cur.close()
        conn.close()

        total = job["total_steps"] or 1
        completed = job["completed_steps"] or 0
        progress_pct = round((completed / total) * 100, 1) if total > 0 else 0

        return jsonify(
            {
                "success": True,
                "job": {
                    "id": job["id"],
                    "job_type": job["job_type"],
                    "module_source": job["module_source"],
                    "description": job["description"],
                    "total_steps": total,
                    "completed_steps": completed,
                    "failed_steps": job["failed_steps"] or 0,
                    "status": job["status"],
                    "agent_name": job.get("agent_display_name") or "Unknown",
                    "metadata": job["metadata"] or {},
                    "progress_pct": progress_pct,
                    "created_at": job["created_at"].isoformat() if job["created_at"] else None,
                    "updated_at": job["updated_at"].isoformat() if job["updated_at"] else None,
                    "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
                },
                "executions": [
                    {
                        "id": e["id"],
                        "agent_name": e["agent_name"],
                        "capability": e["capability"],
                        "model": e["model_used"],
                        "duration_ms": e["duration_ms"],
                        "success": e["success"],
                        "error": e.get("error_message"),
                        "timestamp": e["created_at"].isoformat() if e["created_at"] else None,
                    }
                    for e in executions
                ],
            }
        )

    except Exception as e:
        logger.error(f"Error getting bridge job detail: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# CREW MANIFEST — Live agent roster with status/wellness/jobs/stats
# ============================================================================


@bridge_bp.route("/api/bridge/crew/manifest")
@login_required
def get_crew_manifest():
    """Get the live crew manifest — all agents with status, wellness, jobs, stats."""
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        manifest = dispatcher.get_crew_manifest()

        return jsonify({"success": True, "crew": manifest, "total": len(manifest)})
    except Exception as e:
        logger.error(f"Error getting crew manifest: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/reassign", methods=["POST"])
@login_required
def reassign_agent():
    """Manually reassign an agent to a different station (admin only)"""
    try:
        if not current_user.is_admin:
            return jsonify({"success": False, "error": "Admin access required"}), 403

        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        new_station_code = data.get("station_code")

        if not agent_id or not new_station_code:
            return jsonify({"success": False, "error": "agent_id and station_code required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify agent exists
        cur.execute("SELECT id, name FROM agents WHERE id = %s AND status = 'active'", (agent_id,))
        agent = cur.fetchone()
        if not agent:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent not found or inactive"}), 404

        # Verify station exists
        cur.execute(
            "SELECT id, station_name FROM bridge_stations WHERE station_code = %s AND is_active = TRUE",
            (new_station_code,),
        )
        station = cur.fetchone()
        if not station:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Station not found or inactive"}), 404

        # Deactivate old assignments
        cur.execute(
            "UPDATE station_assignments SET is_active = FALSE WHERE agent_id = %s AND is_active = TRUE",
            (agent_id,),
        )

        # Create new assignment
        cur.execute(
            """
            INSERT INTO station_assignments (agent_id, station_id, assignment_type, is_active, priority)
            VALUES (%s, %s, 'primary', TRUE, 1)
            ON CONFLICT (agent_id, station_id) DO UPDATE SET is_active = TRUE, assignment_type = 'primary'
        """,
            (agent_id, station["id"]),
        )

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Agent {agent['name']} reassigned to {station['station_name']} by {current_user.username}")

        return jsonify(
            {
                "success": True,
                "message": f"{agent['name']} reassigned to {station['station_name']}",
                "agent_id": agent_id,
                "station_code": new_station_code,
            }
        )

    except Exception as e:
        logger.error(f"Error reassigning agent: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ROUTING MODE & ESCALATION LOG API
# ============================================================================


@bridge_bp.route("/api/routing-mode", methods=["GET"])
@login_required
def get_routing_mode():
    """Get current bridge routing mode."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"success": True, "routing_mode": row["value"] if row else "full"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/routing-mode", methods=["POST"])
@login_required
def set_routing_mode():
    """Set bridge routing mode: local_only, local_cloud, or full."""
    data = request.get_json() or {}
    mode = data.get("routing_mode", "full")
    if mode not in ("local_only", "local_cloud", "full"):
        return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO platform_settings (key, value, value_type, description, updated_at)
            VALUES ('routing_mode', %s, 'string', 'Bridge routing mode', NOW())
            ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
        """,
            (mode, mode),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[Bridge] Routing mode changed to: {mode}")
        return jsonify({"success": True, "routing_mode": mode})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/escalation-mode", methods=["GET"])
@login_required
def get_escalation_mode():
    """Get current bridge escalation mode."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_mode'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"success": True, "escalation_mode": row["value"] if row else "auto"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/escalation-mode", methods=["POST"])
@login_required
def set_escalation_mode():
    """Set bridge escalation mode: auto, ask_first, or local_only."""
    data = request.get_json() or {}
    mode = data.get("escalation_mode", "auto")
    if mode not in ("auto", "ask_first", "local_only"):
        return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO platform_settings (key, value, value_type, description, updated_at)
            VALUES ('escalation_mode', %s, 'string', 'Throughput escalation mode', NOW())
            ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
        """,
            (mode, mode),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[Bridge] Escalation mode changed to: {mode}")
        return jsonify({"success": True, "escalation_mode": mode})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/escalation-log", methods=["GET"])
@login_required
def get_escalation_log():
    """Get recent escalation events."""
    limit = request.args.get("limit", 20, type=int)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT del.*, a.name as agent_name
            FROM dispatch_escalation_log del
            LEFT JOIN agents a ON a.id = del.original_agent_id
            ORDER BY del.created_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Convert datetime objects for JSON serialization
        result = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            result.append(d)
        return jsonify({"success": True, "escalations": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# EXTERNAL PROVIDER KEY MANAGEMENT
# ============================================================================


@bridge_bp.route("/api/external-providers", methods=["GET"])
@login_required
def get_external_providers():
    """List external AI providers and their status (keys masked)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, provider, is_active, monthly_budget_usd, current_month_cost_usd,
                   budget_reset_day, created_at, updated_at,
                   CASE WHEN api_key_encrypted IS NOT NULL AND api_key_encrypted != ''
                        THEN '****' || RIGHT(api_key_encrypted, 4) ELSE NULL END as key_hint
            FROM external_api_keys
            ORDER BY provider
        """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            result.append(d)
        return jsonify({"success": True, "providers": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/external-providers", methods=["POST"])
@login_required
def upsert_external_provider():
    """Add or update an external AI provider API key."""
    data = request.get_json() or {}
    provider = data.get("provider", "").strip().lower()
    api_key = data.get("api_key", "").strip()

    if provider not in ("openai", "perplexity", "xai"):
        return jsonify({"success": False, "error": f"Unknown provider: {provider}"}), 400
    if not api_key:
        return jsonify({"success": False, "error": "API key required"}), 400

    budget = data.get("monthly_budget_usd", 10.0)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO external_api_keys (provider, api_key_encrypted, monthly_budget_usd, is_active)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (provider) DO UPDATE SET
                api_key_encrypted = %s, monthly_budget_usd = %s, is_active = TRUE, updated_at = NOW()
            RETURNING id, provider, is_active, monthly_budget_usd
        """,
            (provider, api_key, budget, api_key, budget),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "provider": dict(row)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/external-providers/<provider>/toggle", methods=["POST"])
@login_required
def toggle_external_provider(provider):
    """Enable/disable an external provider."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE external_api_keys SET is_active = NOT is_active, updated_at = NOW() WHERE provider = %s",
            (provider,),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DASHBOARD AGENT BADGE API
# ============================================================================


@bridge_bp.route("/api/dashboard/module-agents", methods=["GET"])
@login_required
def get_module_agents():
    """Get assigned agent info for all active modules (for dashboard badges)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                bs.station_code,
                UNNEST(bs.modules) as module_id,
                a.name as agent_codename,
                a.first_name,
                a.display_name,
                a.model,
                a.status as agent_status
            FROM bridge_stations bs
            JOIN station_assignments sa ON sa.station_id = bs.id AND sa.is_active = TRUE
            JOIN agents a ON a.id = sa.agent_id AND a.status = 'active'
            WHERE bs.is_active = TRUE
            ORDER BY bs.station_code
        """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        module_agents = {}
        for row in rows:
            mid = row["module_id"]
            if mid not in module_agents:
                module_agents[mid] = {
                    "agent_codename": row["agent_codename"],
                    "first_name": row["first_name"] or row["agent_codename"],
                    "display_name": row["display_name"] or row["agent_codename"],
                    "station_code": row["station_code"],
                    "status": row["agent_status"],
                }

        return jsonify({"success": True, "module_agents": module_agents})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Phase 6: Mission Control — SSE + Activity Endpoints
# ============================================================================


@bridge_bp.route("/api/dispatch/stream")
@login_required
def activity_stream():
    """SSE endpoint for real-time agent activity events."""

    def generate():
        last_sent_time = datetime.utcnow().isoformat() + "Z"
        while True:
            new_events = [e for e in _activity_queue if e["created_at"] > last_sent_time]
            for evt in reversed(new_events):
                yield "event: {}\ndata: {}\n\n".format(evt["event_type"], json.dumps(evt))
                last_sent_time = evt["created_at"]
            yield ": heartbeat\n\n"
            time.sleep(5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bridge_bp.route("/api/dispatch/activity-history")
@login_required
def activity_history():
    """Return last 50 activity events for initial page load."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT e.id, e.event_type, e.agent_id, e.data, e.created_at,
                   a.name AS agent_name, a.display_name
            FROM agent_activity_events e
            LEFT JOIN agents a ON a.id = e.agent_id
            ORDER BY e.created_at DESC
            LIMIT 50
        """
        )
        events = cur.fetchall()
        cur.close()
        conn.close()
        for ev in events:
            ev["created_at"] = ev["created_at"].isoformat() if ev["created_at"] else None
        return jsonify(events)
    except Exception as e:
        logger.error("activity_history error: %s", e)
        return jsonify([])


@bridge_bp.route("/api/agents/<int:agent_id>/executions")
@login_required
def agent_executions(agent_id):
    """Recent execution history for a specific agent via orchestration_steps."""
    limit = request.args.get("limit", 10, type=int)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Sessions where this agent participated (via steps)
        cur.execute(
            """
            SELECT DISTINCT ON (os.id)
                   os.id, os.session_id, os.status,
                   os.total_duration_ms, os.total_steps,
                   os.created_at, os.completed_at,
                   st.model_used,
                   (SELECT COUNT(*) FROM orchestration_steps s2
                    WHERE s2.session_id = os.id) AS step_count
            FROM orchestration_sessions os
            JOIN orchestration_steps st ON st.session_id = os.id
                AND st.agent_id = %s
            ORDER BY os.id DESC, st.id DESC
            LIMIT %s
        """,
            (agent_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for r in rows:
            r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
            r["completed_at"] = r["completed_at"].isoformat() if r.get("completed_at") else None
            # Convert UUID to string for JSON serialization
            if r.get("session_id"):
                r["session_id"] = str(r["session_id"])
        return jsonify(rows)
    except Exception as e:
        logger.error("agent_executions error: %s", e)
        return jsonify([])


@bridge_bp.route("/api/agents/<int:agent_id>/emotional-state")
@login_required
def agent_emotional_state_detail(agent_id):
    """Current emotional state for a specific agent."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT current_mood, mood_intensity, stress_level, energy_level,
                   previous_mood, trigger_event, timestamp, metadata
            FROM agent_emotional_state
            WHERE agent_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """,
            (agent_id,),
        )
        state = cur.fetchone()
        # Also get last rest cycle
        cur.execute(
            """
            SELECT rest_type, started_at, ended_at, reason, initiated_by
            FROM agent_rest_cycles
            WHERE agent_id = %s
            ORDER BY started_at DESC
            LIMIT 1
        """,
            (agent_id,),
        )
        rest = cur.fetchone()
        cur.close()
        conn.close()
        if state:
            state["timestamp"] = state["timestamp"].isoformat() if state.get("timestamp") else None
        if rest:
            rest["started_at"] = rest["started_at"].isoformat() if rest.get("started_at") else None
            rest["ended_at"] = rest["ended_at"].isoformat() if rest.get("ended_at") else None
        return jsonify({"emotional_state": state, "last_rest": rest})
    except Exception as e:
        logger.error("agent_emotional_state_detail error: %s", e)
        return jsonify({"emotional_state": None, "last_rest": None})


@bridge_bp.route("/api/agents/<int:agent_id>/profile")
@login_required
def agent_profile(agent_id):
    """Aggregated agent profile: details, skills, emotional state, performance, memory."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Agent details
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
            (agent_id,),
        )
        agent = cur.fetchone()
        if not agent:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Agent not found"}), 404

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
            (agent_id,),
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
            (agent_id,),
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
            (agent_id,),
        )
        perf = cur.fetchone()

        # Recent tasks (last 10)
        cur.execute(
            """
            SELECT id, module_source, task_type, capability, model_used,
                   duration_ms, success, error_message, created_at
            FROM task_execution_log
            WHERE agent_id = %s
            ORDER BY created_at DESC LIMIT 10
        """,
            (agent_id,),
        )
        recent = cur.fetchall()
        for r in recent:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()

        # Memory highlights (top 5 by importance)
        cur.execute(
            """
            SELECT memory_type, content, importance_score, source_module, created_at
            FROM agent_memory
            WHERE agent_id = %s AND is_deleted = FALSE
            ORDER BY importance_score DESC NULLS LAST
            LIMIT 5
        """,
            (agent_id,),
        )
        memories = cur.fetchall()
        for m in memories:
            if m.get("created_at"):
                m["created_at"] = m["created_at"].isoformat()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "agent": agent,
                "skills": skills,
                "emotional_state": emotional,
                "performance_24h": {
                    "tasks": perf["tasks_24h"],
                    "completed": perf["completed"],
                    "failed": perf["failed"],
                    "avg_duration_ms": round(float(perf["avg_duration_ms"]), 1),
                },
                "recent_tasks": recent,
                "memories": memories,
            }
        )

    except Exception as e:
        logger.error("agent_profile error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/dispatch/multi-agent-sessions")
@login_required
def multi_agent_sessions():
    """Paginated list of multi-agent orchestration sessions."""
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    offset = (page - 1) * per_page
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Multi-agent sessions have multiple agent steps
        cur.execute(
            """
            SELECT os.id, os.session_id, os.status,
                   os.total_duration_ms, os.total_steps,
                   os.created_at, os.completed_at,
                   os.metadata,
                   (SELECT COUNT(DISTINCT st.agent_id) FROM orchestration_steps st
                    WHERE st.session_id = os.id AND st.agent_id IS NOT NULL) AS agent_count,
                   (SELECT COUNT(*) FROM orchestration_steps st
                    WHERE st.session_id = os.id) AS step_count
            FROM orchestration_sessions os
            WHERE os.total_steps > 3
            ORDER BY os.created_at DESC
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )
        sessions = cur.fetchall()
        # Total count
        cur.execute("SELECT COUNT(*) AS total FROM orchestration_sessions WHERE total_steps > 3")
        total = cur.fetchone()["total"]
        cur.close()
        conn.close()
        for s in sessions:
            s["created_at"] = s["created_at"].isoformat() if s.get("created_at") else None
            s["completed_at"] = s["completed_at"].isoformat() if s.get("completed_at") else None
            if s.get("session_id"):
                s["session_id"] = str(s["session_id"])
        return jsonify({"sessions": sessions, "total": total, "page": page, "per_page": per_page})
    except Exception as e:
        logger.error("multi_agent_sessions error: %s", e)
        return jsonify({"sessions": [], "total": 0, "page": page, "per_page": per_page})


@bridge_bp.route("/api/dispatch/multi-agent-sessions/<session_id>")
@login_required
def multi_agent_session_detail(session_id):
    """Full detail for a multi-agent session with steps."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Session info — match by UUID or integer id
        cur.execute(
            """
            SELECT os.id, os.session_id, os.status,
                   os.total_duration_ms, os.total_steps,
                   os.created_at, os.completed_at, os.metadata
            FROM orchestration_sessions os
            WHERE os.session_id::text = %s OR os.id::text = %s
        """,
            (session_id, session_id),
        )
        session = cur.fetchone()
        if not session:
            return jsonify({"error": "Session not found"}), 404
        session["created_at"] = session["created_at"].isoformat() if session.get("created_at") else None
        session["completed_at"] = session["completed_at"].isoformat() if session.get("completed_at") else None
        if session.get("session_id"):
            session["session_id"] = str(session["session_id"])
        # Steps
        cur.execute(
            """
            SELECT st.id, st.step_type, st.step_order, st.step_data,
                   st.duration_ms, st.success, st.agent_id, st.model_used,
                   a.name AS agent_name, a.display_name
            FROM orchestration_steps st
            LEFT JOIN agents a ON a.id = st.agent_id
            WHERE st.session_id = %s
            ORDER BY st.step_order ASC, st.id ASC
        """,
            (session["id"],),
        )
        steps = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"session": session, "steps": steps})
    except Exception as e:
        logger.error("multi_agent_session_detail error: %s", e)
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/dispatch/fleet-metrics")
@login_required
def fleet_metrics():
    """Aggregate fleet metrics for Mission Control."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Active vs total agents
        cur.execute("SELECT COUNT(*) AS total," " COUNT(*) FILTER (WHERE status = 'active') AS active" " FROM agents")
        agents_row = cur.fetchone()
        # Tasks this hour
        cur.execute(
            """
            SELECT COUNT(*) AS count,
                   AVG(total_duration_ms) AS avg_duration,
                   COUNT(*) FILTER (WHERE status = 'failed') AS errors
            FROM orchestration_sessions
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """
        )
        tasks = cur.fetchone()
        # GPU model (loaded Ollama model)
        gpu_model = None
        try:
            resp = requests.get("http://host.docker.internal:11434/api/ps", timeout=3)
            if resp.ok:
                models = resp.json().get("models", [])
                if models:
                    gpu_model = models[0].get("name", "unknown")
        except Exception:
            pass
        # Top agent today (via orchestration_steps linkage)
        cur.execute(
            """
            SELECT a.name AS agent_name, a.display_name, COUNT(*) AS task_count
            FROM orchestration_steps st
            JOIN agents a ON a.id = st.agent_id
            WHERE st.created_at > CURRENT_DATE
              AND st.step_type = 'execute'
            GROUP BY a.id, a.name, a.display_name
            ORDER BY task_count DESC
            LIMIT 1
        """
        )
        top = cur.fetchone()
        cur.close()
        conn.close()
        total_tasks = tasks["count"] or 0
        error_count = tasks["errors"] or 0
        return jsonify(
            {
                "active_agents": agents_row["active"] or 0,
                "total_agents": agents_row["total"] or 0,
                "tasks_this_hour": total_tasks,
                "avg_duration_ms": round(float(tasks["avg_duration"] or 0)),
                "error_rate": round((error_count / total_tasks * 100) if total_tasks > 0 else 0, 1),
                "gpu_model": gpu_model,
                "top_agent": top,
            }
        )
    except Exception as e:
        logger.error("fleet_metrics error: %s", e)
        return jsonify(
            {
                "active_agents": 0,
                "total_agents": 0,
                "tasks_this_hour": 0,
                "avg_duration_ms": 0,
                "error_rate": 0,
                "gpu_model": None,
                "top_agent": None,
            }
        )


# ============================================================================
# MESH CLUSTER API ROUTES
# ============================================================================
try:
    from tools.bridge.mesh_routes import register_mesh_routes

    register_mesh_routes(bridge_bp)
except ImportError as e:
    logger.warning(f"Mesh routes not loaded: {e}")
