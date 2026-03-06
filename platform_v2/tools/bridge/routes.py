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
import subprocess
import sys
import time
import logging
from collections import deque
from datetime import datetime
from typing import Dict, List
from flask import Blueprint, render_template, jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
from rbac import require_permission, Permission
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_cursor
import requests

try:
    from ai_bridge.agent_performance_tracker import (
        get_agent_performance,
        update_agent_performance,
        get_top_performers,
        log_agent_action,
    )

    _HAS_PERFORMANCE_TRACKER = True
except ImportError:
    _HAS_PERFORMANCE_TRACKER = False

logger = logging.getLogger(__name__)

bridge_bp = Blueprint("bridge", __name__, url_prefix="/tools/bridge")

# Ollama tags cache (avoid hitting Ollama on every stats poll)
_ollama_tags_cache = {"models": [], "count": 0, "time": 0}
_OLLAMA_CACHE_TTL = 30  # seconds — matches stats poll interval


def _get_cached_ollama_tags():
    """Get Ollama model list with 30s cache"""
    now = time.time()
    if _ollama_tags_cache["time"] and (now - _ollama_tags_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_tags_cache["models"], _ollama_tags_cache["count"]
    try:
        host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        if not host.startswith("http"):
            host = f"http://{host}"
        resp = requests.get(f"{host}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_tags_cache["models"] = models
            _ollama_tags_cache["count"] = len(models)
            _ollama_tags_cache["time"] = now
            return models, len(models)
    except Exception:
        pass
    return _ollama_tags_cache["models"], _ollama_tags_cache["count"]


# Ollama ps cache (avoid hitting Ollama /api/ps on every poll)
_ollama_ps_cache = {"models": [], "time": 0}


def _get_cached_ollama_ps():
    """Get loaded Ollama models with 30s cache"""
    now = time.time()
    if _ollama_ps_cache["time"] and (now - _ollama_ps_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_ps_cache["models"]
    try:
        host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        if not host.startswith("http"):
            host = f"http://{host}"
        resp = requests.get(f"{host}/api/ps", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_ps_cache["models"] = models
            _ollama_ps_cache["time"] = now
            return models
    except Exception:
        pass
    return _ollama_ps_cache["models"]


# --- SSE Activity Event Queue ---
_activity_queue = deque(maxlen=200)


def push_agent_event(event_type, agent_id=None, data=None):
    """Push an event to the in-memory SSE queue."""
    evt = {
        "event_type": event_type,
        "agent_id": agent_id,
        "data": data or {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _activity_queue.appendleft(evt)


# ============================================================================
# STATION DEFINITIONS (Database-driven - 10 stations)
# ============================================================================


def get_stations_from_db():
    """Get all stations from database"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
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
        "modules": ["consciousness", "knowledge_base", "analytics"],
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
        "modules": ["dev_pipeline", "project_manager", "website_studio", "store_builder"],
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
@login_required
def get_bridge_stats():
    """Get overall Bridge statistics"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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

            # Get real LLM model counts from Ollama (cached)
            _, llm_total = _get_cached_ollama_tags()
            llm_online = llm_total

            # System load from active requests ratio (capped 0-100)
            active_requests = token_stats["total_requests"] if token_stats else 0
            system_load = min(int(active_requests / max(1, active_requests + 10) * 100), 100)

            return jsonify(
                {
                    "success": True,
                    "stats": {
                        "llm_status": {"online": llm_online, "total": llm_total},
                        "active_requests": active_requests,
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
@login_required
def get_stations():
    """Get all station configurations from database (10 stations)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Single query: stations + their assigned agents via LEFT JOIN + json_agg
            cur.execute(
                """
                SELECT bs.id, bs.station_code, bs.station_name, bs.full_name,
                       bs.description, bs.color, bs.icon, bs.default_llm,
                       bs.modules, bs.position_row, bs.position_order,
                       bs.max_primary, bs.max_auxiliary, bs.allow_overflow,
                       COALESCE(
                           json_agg(
                               json_build_object(
                                   'id', a.id,
                                   'name', a.name,
                                   'first_name', a.first_name,
                                   'last_name', a.last_name,
                                   'title', a.title,
                                   'avatar_url', a.avatar_url,
                                   'model', a.model,
                                   'assignment_type', sa.assignment_type
                               ) ORDER BY sa.priority
                           ) FILTER (WHERE a.id IS NOT NULL),
                           '[]'::json
                       ) as assigned_agents
                FROM bridge_stations bs
                LEFT JOIN station_assignments sa
                    ON sa.station_id = bs.id AND sa.is_active = TRUE
                LEFT JOIN agents a
                    ON sa.agent_id = a.id AND a.status = 'active'
                WHERE bs.is_active = TRUE
                GROUP BY bs.id, bs.station_code, bs.station_name, bs.full_name,
                         bs.description, bs.color, bs.icon, bs.default_llm,
                         bs.modules, bs.position_row, bs.position_order,
                         bs.max_primary, bs.max_auxiliary, bs.allow_overflow
                ORDER BY bs.position_row, bs.position_order
            """
            )
            db_stations = cur.fetchall()

            # Inline node coverage (avoids separate /api/stations/coverage call)
            cur.execute("SELECT * FROM v_station_node_coverage")
            coverage_rows = cur.fetchall()
            coverage_map = {c["station_code"]: c for c in coverage_rows}

            stations_data = []
            for station in db_stations:
                agents = station["assigned_agents"] or []
                primary_count = sum(1 for a in agents if a.get("assignment_type") == "primary")
                backup_count = sum(1 for a in agents if a.get("assignment_type") == "backup")

                cov = coverage_map.get(station["station_code"], {})
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
                        "assigned_agents": agents,
                        "primary_count": primary_count,
                        "backup_count": backup_count,
                        "total_agents": len(agents),
                        "max_primary": station.get("max_primary", 2),
                        "max_auxiliary": station.get("max_auxiliary", 1),
                        "allow_overflow": station.get("allow_overflow", True),
                        "status": "active",
                        "node_coverage": {
                            "total_nodes": cov.get("total_nodes", 0),
                            "primary_nodes": cov.get("primary_nodes", 0),
                            "backup_nodes": cov.get("backup_nodes", 0),
                        },
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "stations": stations_data,
                    "total_stations": len(stations_data),
                    "coverage_summary": {
                        "total_stations": len(coverage_rows),
                        "stations_with_nodes": len([c for c in coverage_rows if c["total_nodes"] > 0]),
                        "total_assignments": sum(c["total_nodes"] for c in coverage_rows),
                    },
                }
            )

    except Exception as e:
        logger.error(f"Error getting stations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/modules/metadata", methods=["POST"])
@login_required
def get_modules_metadata():
    """Get metadata for a list of module names (icon, route, description)"""
    from module_registry import get_enabled_modules

    data = request.get_json() or {}
    module_names = data.get("modules", [])

    registry = {m.id: m for m in get_enabled_modules()}
    # Build name-to-module lookup for fuzzy matching
    name_lookup = {}
    for m in get_enabled_modules():
        name_lookup[m.name.lower()] = m
        name_lookup[m.id.lower()] = m
        for tag in m.tags:
            if tag.lower() not in name_lookup:
                name_lookup[tag.lower()] = m

    results = []
    for name in module_names:
        mod = registry.get(name) or name_lookup.get(name.lower().replace(" ", "-")) or name_lookup.get(name.lower())
        if mod:
            results.append(
                {
                    "id": mod.id,
                    "name": mod.name,
                    "icon": mod.icon,
                    "route": mod.route,
                    "description": mod.description,
                    "category": mod.category.value if hasattr(mod.category, "value") else str(mod.category),
                }
            )
        else:
            results.append(
                {
                    "id": name,
                    "name": name.replace("-", " ").replace("_", " ").title(),
                    "icon": "box",
                    "route": None,
                    "description": "",
                    "category": "unknown",
                }
            )
    return jsonify({"success": True, "modules": results})


@bridge_bp.route("/api/stations/<station_code>")
@login_required
def get_station_detail(station_code):
    """Get detailed info for a specific station"""
    station_code = station_code.upper()

    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
    """Get list of available Ollama models with sizes"""
    try:
        response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {model["name"]: model.get("size", 0) for model in data.get("models", [])}
    except Exception as e:
        logger.error(f"Error getting Ollama models: {e}")
    return {}


# ============================================================================
# AGENTS API (for station assignment)
# ============================================================================


@bridge_bp.route("/api/agents")
@login_required
def get_bridge_agents():
    """Get agents available for station assignment"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
        with get_db_cursor() as (conn, cur):
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

    # Capture model transition info from request
    new_model = data.get("model", "").strip()
    num_gpu = int(data.get("num_gpu", 0))

    try:
        with get_db_cursor() as (conn, cur):
            # Get old model before update
            old_model = None
            if new_model:
                cur.execute("SELECT model FROM agents WHERE id = %s", (agent_id,))
                row = cur.fetchone()
                if row:
                    old_model = row["model"]

            cur.execute(
                f"UPDATE agents SET {', '.join(sets)} WHERE id = %s RETURNING id, name, first_name, last_name, model, status",
                params,
            )
            agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Agent not found"}), 404

            # Invalidate caches
            try:
                from ai_bridge.bridge_dispatcher import get_dispatcher

                get_dispatcher()._cache_time = 0
            except Exception:
                pass
            _profile_cache.pop(agent_id, None)

            # Model transition: auto-load new model, auto-unload orphaned old model
            model_ops = []
            if new_model and old_model and new_model != old_model:
                _ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "host.docker.internal")
                _ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
                ollama_url = f"http://{_ollama_host}:{_ollama_port}"

                # Check if old model is orphaned (no other agent uses it)
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM agents WHERE model = %s AND id != %s AND status = 'active'",
                    (old_model, agent_id),
                )
                old_count = cur.fetchone()["cnt"]
                if old_count == 0 and old_model:
                    # Unload orphaned model
                    try:
                        requests.post(
                            f"{ollama_url}/api/generate",
                            json={"model": old_model, "keep_alive": 0},
                            timeout=10,
                        )
                        model_ops.append(f"unloaded {old_model} (orphaned)")
                    except Exception:
                        model_ops.append(f"failed to unload {old_model}")

                # Load new model
                try:
                    requests.post(
                        f"{ollama_url}/api/generate",
                        json={
                            "model": new_model,
                            "prompt": "hi",
                            "options": {"num_gpu": num_gpu, "num_predict": 1},
                            "keep_alive": -1,
                            "stream": False,
                        },
                        timeout=300,
                    )
                    hw_label = "GPU" if num_gpu > 0 else "CPU"
                    model_ops.append(f"loaded {new_model} on {hw_label}")
                except Exception:
                    model_ops.append(f"failed to load {new_model}")

            result = {"success": True, "agent": dict(agent)}
            if model_ops:
                result["model_ops"] = model_ops
            return jsonify(result)
    except Exception as e:
        logger.error("update_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
@login_required
def delete_agent(agent_id):
    """Delete an agent (clears FK references first)"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id, name FROM agents WHERE id = %s", (agent_id,))
            agent = cur.fetchone()
            if not agent:
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

            try:
                from ai_bridge.bridge_dispatcher import get_dispatcher

                get_dispatcher()._cache_time = 0
            except Exception:
                pass

            return jsonify({"success": True, "message": f"Agent '{agent['name']}' deleted"})
    except Exception as e:
        logger.error("delete_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/toggle", methods=["POST"])
@login_required
def toggle_agent(agent_id):
    """Toggle agent active/paused"""
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
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
            if not result:
                return jsonify({"success": False, "error": "Agent not found"}), 404

            try:
                from ai_bridge.bridge_dispatcher import get_dispatcher

                get_dispatcher()._cache_time = 0
            except Exception:
                pass

            return jsonify({"success": True, "status": result[0]})
    except Exception as e:
        logger.error("toggle_agent error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/skills", methods=["GET"])
@login_required
def get_agent_skills(agent_id):
    """Get all skills for an agent"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
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
        with get_db_cursor() as (conn, cur):
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
            return jsonify({"success": True, "skill": dict(skill)})
    except Exception as e:
        logger.error("add_agent_skill error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/skills/<skill_id>", methods=["DELETE"])
@login_required
def delete_agent_skill(agent_id, skill_id):
    """Remove a skill from an agent"""
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                "DELETE FROM agent_skills WHERE id = %s AND agent_id = %s RETURNING skill_name",
                (skill_id, agent_id),
            )
            result = cur.fetchone()
            if not result:
                return jsonify({"success": False, "error": "Skill not found"}), 404
            return jsonify({"success": True, "message": f"Skill '{result[0]}' removed"})
    except Exception as e:
        logger.error("delete_agent_skill error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/assign-station", methods=["POST"])
@login_required
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
        with get_db_cursor() as (conn, cur):

            # Get station ID from code
            cur.execute(
                "SELECT id FROM bridge_stations WHERE station_code = %s",
                (station_code.upper(),),
            )
            station = cur.fetchone()
            if not station:
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
@login_required
def unassign_agent_from_station(agent_id):
    """Remove an agent from a station"""
    data = request.get_json() or {}
    station_code = data.get("station_code")

    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):

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

            affected = cur.rowcount

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
@login_required
def get_all_station_assignments():
    """Get all station assignments grouped by station"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
@login_required
def get_unassigned_agents():
    """Get agents not assigned to any station"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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

            return jsonify({"success": True, "agents": agents, "count": len(agents)})

    except Exception as e:
        logger.error(f"Error getting unassigned agents: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/config", methods=["GET"])
@login_required
def get_station_config(station_code):
    """Get station configuration"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
                return jsonify({"success": False, "error": "Station not found"}), 404

            # Convert datetime
            for key in ["created_at", "updated_at"]:
                if station.get(key):
                    station[key] = station[key].isoformat()

            return jsonify({"success": True, "station": station})

    except Exception as e:
        logger.error(f"Error getting station config: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/config", methods=["PUT"])
@login_required
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
        with get_db_cursor() as (conn, cur):

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
@login_required
def reorder_stations():
    """Reorder stations (drag-and-drop support)"""
    data = request.get_json() or {}
    order = data.get("order", [])  # List of {station_code, position_row, position_order}

    if not order:
        return jsonify({"success": False, "error": "order list required"}), 400

    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):

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

            return jsonify({"success": True, "message": f"Reordered {len(order)} stations"})

    except Exception as e:
        logger.error(f"Error reordering stations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
@login_required
def delete_assignment(assignment_id):
    """Delete a station assignment"""
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):

            cur.execute(
                """
                DELETE FROM station_assignments WHERE id = %s RETURNING id
            """,
                (assignment_id,),
            )

            deleted = cur.fetchone()

            if not deleted:
                return jsonify({"success": False, "error": "Assignment not found"}), 404

            return jsonify({"success": True, "message": "Assignment deleted"})

    except Exception as e:
        logger.error(f"Error deleting assignment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
@login_required
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
        with get_db_cursor() as (conn, cur):

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
@login_required
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
        with get_db_cursor() as (conn, cur):

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
                logger.info(
                    f"Bridge: {candidate['name']} at workload limit ({workload['assignment_count']} assignments)"
                )
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

            logger.info(f"Bridge: Assigned {candidate['name']} as additional_support to {station['station_name']}")

            # Add assignment type to candidate for caller
            candidate_dict = dict(candidate)
            candidate_dict["assignment_type"] = "additional_support"
            candidate_dict["assignment_id"] = assignment["id"]

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
@login_required
def release_station_support(station_code):
    """
    Release an agent from the additional_support slot.

    Called when module completes work or no longer needs support.
    This frees the agent for other stations.
    """
    data = request.get_json() or {}
    agent_id = data.get("agent_id")

    try:
        with get_db_cursor() as (conn, cur):

            # Get station
            cur.execute(
                """
                SELECT id FROM bridge_stations WHERE station_code = %s
            """,
                (station_code.upper(),),
            )
            station = cur.fetchone()

            if not station:
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
# LOUNGE (REST AREA) API - Phase 39
# ============================================================================


@bridge_bp.route("/api/lounge")
@login_required
def get_lounge_agents():
    """Get agents currently in lounge (resting)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT
                    a.id as agent_id,
                    a.name as agent_name,
                    a.display_name,
                    a.avatar_url,
                    a.department,
                    arc.id as rest_cycle_id,
                    arc.rest_type,
                    arc.reason as rest_reason,
                    arc.started_at as rest_started,
                    EXTRACT(EPOCH FROM (NOW() - arc.started_at)) / 3600 as hours_resting,
                    CASE WHEN arc.rest_type = 'forced' THEN TRUE ELSE FALSE END as is_locked,
                    arc.stress_at_start,
                    arc.energy_at_start
                FROM agent_rest_cycles arc
                JOIN agents a ON arc.agent_id = a.id
                WHERE arc.ended_at IS NULL
                AND a.status = 'active'
                ORDER BY arc.started_at DESC
            """
            )
            agents = cur.fetchall()

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

        with get_db_cursor() as (conn, cur):

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

            # Snapshot emotional state before rest
            cur.execute(
                "SELECT stress_level, energy_level FROM agent_emotional_state WHERE agent_id = %s",
                (agent_id,),
            )
            emo = cur.fetchone()
            stress_start = float(emo["stress_level"]) if emo else None
            energy_start = float(emo["energy_level"]) if emo else None

            # Start rest cycle
            cur.execute(
                """
                INSERT INTO agent_rest_cycles
                    (agent_id, rest_type, reason, started_at, stress_at_start, energy_at_start)
                VALUES (%s, %s, %s, NOW(), %s, %s)
                RETURNING id
            """,
                (agent_id, rest_type, reason, stress_start, energy_start),
            )

            rest_cycle_id = cur.fetchone()["id"]

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
        with get_db_cursor() as (conn, cur):

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

            # Snapshot emotional state on return
            cur.execute(
                "SELECT stress_level, energy_level FROM agent_emotional_state WHERE agent_id = %s",
                (agent_id,),
            )
            emo = cur.fetchone()
            stress_end = float(emo["stress_level"]) if emo else None
            energy_end = float(emo["energy_level"]) if emo else None

            # End rest cycle with emotional deltas
            cur.execute(
                """
                UPDATE agent_rest_cycles
                SET ended_at = NOW(),
                    stress_at_end = %s,
                    energy_at_end = %s
                WHERE id = %s
            """,
                (stress_end, energy_end, rest_cycle["id"]),
            )

            # Re-activate station assignment
            cur.execute(
                "UPDATE station_assignments SET is_active = TRUE WHERE agent_id = %s",
                (agent_id,),
            )

            return jsonify({"success": True, "message": "Agent returned from lounge"})

    except Exception as e:
        logger.error(f"Error returning agent from lounge: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TRAINING API - Crew Training Management
# ============================================================================


@bridge_bp.route("/api/training/active")
@login_required
def get_active_training():
    """Get all agents currently in training via the training room view"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute("SELECT * FROM v_training_room_agents")
            training = cur.fetchall()

            return jsonify({"success": True, "training": training})

    except Exception as e:
        logger.error(f"Error loading active training: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/assign", methods=["POST"])
@login_required
def assign_training():
    """Assign a training programme to an agent"""
    try:
        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        skill_name = data.get("skill_name")
        target_proficiency = data.get("target_proficiency")

        if not all([agent_id, skill_name, target_proficiency]):
            return (
                jsonify({"success": False, "error": "agent_id, skill_name, and target_proficiency are required"}),
                400,
            )

        target_proficiency = int(target_proficiency)
        if target_proficiency < 2 or target_proficiency > 5:
            return (
                jsonify({"success": False, "error": "target_proficiency must be between 2 and 5"}),
                400,
            )

        with get_db_cursor() as (conn, cur):

            # Validate agent exists and is active
            cur.execute(
                "SELECT id, name FROM agents WHERE id = %s AND status = 'active'",
                (agent_id,),
            )
            agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Agent not found or inactive"}), 404

            # Check for duplicate active training on the same skill
            cur.execute(
                """
                SELECT id FROM training_assignments
                WHERE agent_id = %s AND skill_name = %s
                AND status IN ('pending', 'in_progress')
            """,
                (agent_id, skill_name),
            )
            if cur.fetchone():
                return (
                    jsonify({"success": False, "error": "Agent already has active training for this skill"}),
                    409,
                )

            # Get current proficiency (default 1 if not found)
            cur.execute(
                """
                SELECT proficiency_level, skill_category
                FROM agent_skills
                WHERE agent_id = %s AND skill_name = %s
            """,
                (agent_id, skill_name),
            )
            skill_row = cur.fetchone()
            current_proficiency = skill_row["proficiency_level"] if skill_row else 1
            skill_category = skill_row["skill_category"] if skill_row else None

            if target_proficiency <= current_proficiency:
                return (
                    jsonify({"success": False, "error": "Target proficiency must exceed current level"}),
                    400,
                )

            # Create training assignment
            cur.execute(
                """
                INSERT INTO training_assignments
                    (agent_id, skill_name, skill_category, target_proficiency,
                     current_proficiency, status, started_at, created_by)
                VALUES (%s, %s, %s, %s, %s, 'in_progress', NOW(), %s)
                RETURNING id
            """,
                (agent_id, skill_name, skill_category, target_proficiency, current_proficiency, current_user.id),
            )
            training_id = cur.fetchone()["id"]

            return jsonify(
                {
                    "success": True,
                    "training_id": training_id,
                    "message": f"Training assigned: {agent['name']} → {skill_name} (level {current_proficiency}→{target_proficiency})",
                }
            )

    except Exception as e:
        logger.error(f"Error assigning training: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/<int:training_id>/cancel", methods=["POST"])
@login_required
def cancel_training(training_id):
    """Cancel an active or pending training assignment"""
    try:
        with get_db_cursor() as (conn, cur):

            cur.execute(
                """
                UPDATE training_assignments
                SET status = 'cancelled', completed_at = NOW()
                WHERE id = %s AND status IN ('pending', 'in_progress')
                RETURNING id
            """,
                (training_id,),
            )
            cancelled = cur.fetchone()

            if not cancelled:
                return (
                    jsonify({"success": False, "error": "Training not found or already completed/cancelled"}),
                    404,
                )

            return jsonify({"success": True, "message": "Training cancelled"})

    except Exception as e:
        logger.error(f"Error cancelling training: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/history")
@login_required
def get_training_history():
    """Get completed and cancelled training history"""
    try:
        limit = request.args.get("limit", 20, type=int)
        limit = min(limit, 100)

        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT
                    ta.id,
                    ta.agent_id,
                    a.name as agent_name,
                    a.avatar_url,
                    ta.skill_name,
                    ta.skill_category,
                    ta.current_proficiency,
                    ta.target_proficiency,
                    ta.status,
                    ta.started_at,
                    ta.completed_at,
                    ta.notes
                FROM training_assignments ta
                JOIN agents a ON ta.agent_id = a.id
                WHERE ta.status IN ('completed', 'cancelled')
                ORDER BY ta.completed_at DESC
                LIMIT %s
            """,
                (limit,),
            )
            history = cur.fetchall()

            return jsonify({"success": True, "history": history})

    except Exception as e:
        logger.error(f"Error loading training history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/recommendations")
@login_required
def get_training_recommendations():
    """Recommend training based on recent task failures"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT
                    tel.agent_id,
                    a.name as agent_name,
                    a.avatar_url,
                    tel.capability as skill_name,
                    COUNT(*) as failure_count,
                    COALESCE(ask.proficiency_level, 0) as current_proficiency,
                    ask.skill_category
                FROM task_execution_log tel
                JOIN agents a ON tel.agent_id = a.id
                LEFT JOIN agent_skills ask
                    ON tel.agent_id = ask.agent_id AND tel.capability = ask.skill_name
                WHERE tel.success = FALSE
                AND tel.created_at >= NOW() - INTERVAL '7 days'
                AND a.status = 'active'
                AND NOT EXISTS (
                    SELECT 1 FROM training_assignments ta
                    WHERE ta.agent_id = tel.agent_id
                    AND ta.skill_name = tel.capability
                    AND ta.status IN ('pending', 'in_progress')
                )
                GROUP BY tel.agent_id, a.name, a.avatar_url, tel.capability,
                         ask.proficiency_level, ask.skill_category
                HAVING COUNT(*) >= 3 AND COALESCE(ask.proficiency_level, 0) < 4
                ORDER BY COUNT(*) DESC
            """
            )
            recommendations = cur.fetchall()

            return jsonify({"success": True, "recommendations": recommendations})

    except Exception as e:
        logger.error(f"Error loading training recommendations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/templates")
@login_required
def list_training_templates():
    """List all skill training templates (proficiency-aware prompts)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT skill_name, level_tier, system_prompt_addon,
                          model_override, updated_at
                   FROM skill_training_templates
                   ORDER BY skill_name, level_tier"""
            )
            templates = cur.fetchall()
            return jsonify({"success": True, "templates": templates})
    except Exception as e:
        logger.error(f"Error listing training templates: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/training/templates", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def upsert_training_template():
    """Create or update a skill training template (admin only)."""
    data = request.get_json() or {}
    skill_name = (data.get("skill_name") or "").strip()
    level_tier = (data.get("level_tier") or "").strip()
    system_prompt_addon = (data.get("system_prompt_addon") or "").strip()
    model_override = (data.get("model_override") or "").strip() or None

    if not skill_name or not level_tier or not system_prompt_addon:
        return jsonify({"success": False, "error": "skill_name, level_tier, and system_prompt_addon required"}), 400

    if level_tier not in ("novice", "intermediate", "advanced"):
        return jsonify({"success": False, "error": "level_tier must be novice, intermediate, or advanced"}), 400

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO skill_training_templates
                       (skill_name, level_tier, system_prompt_addon, model_override)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
                       system_prompt_addon = EXCLUDED.system_prompt_addon,
                       model_override = EXCLUDED.model_override,
                       updated_at = NOW()
                   RETURNING skill_name, level_tier, system_prompt_addon,
                             model_override, updated_at""",
                (skill_name, level_tier, system_prompt_addon, model_override),
            )
            result = cur.fetchone()
            return jsonify({"success": True, "template": dict(result)})
    except Exception as e:
        logger.error(f"Error upserting training template: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LOUNGE WELLNESS & HISTORY API
# ============================================================================


@bridge_bp.route("/api/lounge/wellness")
@login_required
def get_lounge_wellness():
    """Crew wellness summary with burnout risk alerts"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # All active agents with emotional state
            cur.execute(
                """
                SELECT
                    a.id as agent_id,
                    a.name as agent_name,
                    COALESCE(a.first_name || ' ' || a.last_name, a.name) as full_name,
                    aes.stress_level,
                    aes.energy_level,
                    aes.current_mood
                FROM agents a
                LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
                WHERE a.status = 'active'
            """
            )
            agents = cur.fetchall()

            # Currently resting agent IDs
            cur.execute("SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL")
            resting_ids = {row["agent_id"] for row in cur.fetchall()}

            # Task volume per agent in last 48 hours
            cur.execute(
                """
                SELECT agent_id, COUNT(*) as task_count
                FROM task_execution_log
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                AND agent_id IS NOT NULL
                GROUP BY agent_id
            """
            )
            task_counts = {row["agent_id"]: row["task_count"] for row in cur.fetchall()}

            healthy = 0
            at_risk = 0
            resting = 0
            burnout_alerts = []

            for agent in agents:
                aid = agent["agent_id"]
                stress = float(agent["stress_level"]) if agent["stress_level"] is not None else 0.0
                energy = float(agent["energy_level"]) if agent["energy_level"] is not None else 1.0
                mood = agent["current_mood"] or "unknown"
                tasks_48h = task_counts.get(aid, 0)

                if aid in resting_ids:
                    resting += 1
                    continue

                # Burnout thresholds
                reasons = []
                if stress > 0.7:
                    reasons.append(f"High stress ({stress:.2f})")
                if energy < 0.3:
                    reasons.append(f"Low energy ({energy:.2f})")
                if tasks_48h >= 50:
                    reasons.append(f"High workload ({tasks_48h} tasks/48h)")

                if reasons:
                    at_risk += 1
                    burnout_alerts.append(
                        {
                            "agent_id": aid,
                            "agent_name": agent["agent_name"],
                            "full_name": agent["full_name"],
                            "stress": stress,
                            "energy": energy,
                            "mood": mood,
                            "tasks_48h": tasks_48h,
                            "reasons": reasons,
                        }
                    )
                else:
                    healthy += 1

            total = healthy + at_risk + resting

            return jsonify(
                {
                    "success": True,
                    "summary": {
                        "healthy": healthy,
                        "at_risk": at_risk,
                        "resting": resting,
                        "total": total,
                    },
                    "burnout_alerts": burnout_alerts,
                }
            )

    except Exception as e:
        logger.error(f"Error loading lounge wellness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/lounge/history")
@login_required
def get_lounge_history():
    """Past rest cycles with stress/energy deltas"""
    try:
        limit = request.args.get("limit", 20, type=int)
        limit = min(limit, 100)

        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT
                    arc.id,
                    arc.agent_id,
                    a.name as agent_name,
                    COALESCE(a.first_name || ' ' || a.last_name, a.name) as full_name,
                    arc.rest_type,
                    arc.reason,
                    arc.initiated_by,
                    arc.started_at,
                    arc.ended_at,
                    EXTRACT(EPOCH FROM (arc.ended_at - arc.started_at)) / 3600 as hours_rested,
                    arc.stress_at_start,
                    arc.energy_at_start,
                    arc.stress_at_end,
                    arc.energy_at_end
                FROM agent_rest_cycles arc
                JOIN agents a ON arc.agent_id = a.id
                WHERE arc.ended_at IS NOT NULL
                ORDER BY arc.ended_at DESC
                LIMIT %s
            """,
                (limit,),
            )
            history = cur.fetchall()

            return jsonify({"success": True, "history": history})

    except Exception as e:
        logger.error(f"Error loading lounge history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# IAAE COMPLIANCE CHECK API - Phase 39
# ============================================================================


@bridge_bp.route("/api/iaae/check-move/<int:agent_id>")
@login_required
def check_iaae_move_compliance(agent_id):
    """Check IAAE compliance before moving an agent"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
@login_required
def get_traffic_stats():
    """Get throughput stats from task_execution_log (rolling 24h window)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
@login_required
def get_agent_utilization():
    """Get real agent activity rate over 24h (agents that executed tasks / total active)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
@login_required
def get_live_models():
    """Get actual model count from live Ollama API"""
    models, count = _get_cached_ollama_tags()
    return jsonify({"success": True, "count": count, "models": [m["name"] for m in models]})


@bridge_bp.route("/api/iaae/overview")
@login_required
def get_iaae_overview():
    """Get real IAAE compliance and welfare metrics"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Agent welfare: stress and energy across active agents
            cur.execute(
                """
                SELECT es.stress_level, es.energy_level
                FROM agent_emotional_state es
                JOIN agents a ON a.id = es.agent_id
                WHERE a.status = 'active'
            """
            )
            welfare_rows = cur.fetchall()
            stress_vals = [r["stress_level"] for r in welfare_rows if r["stress_level"] is not None]
            energy_vals = [r["energy_level"] for r in welfare_rows if r["energy_level"] is not None]
            avg_stress = round(sum(stress_vals) / len(stress_vals), 2) if stress_vals else None
            avg_energy = round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None

            # Compliance = agents within ethical limits (stress <= 0.7, energy >= 0.3)
            monitored = [
                r for r in welfare_rows if r.get("stress_level") is not None or r.get("energy_level") is not None
            ]
            healthy = sum(
                1 for r in monitored if (r.get("stress_level") or 0) <= 0.7 and (r.get("energy_level") or 1) >= 0.3
            )
            compliance_pct = round(healthy / len(monitored) * 100, 1) if monitored else None

            # Governance events 24h
            cur.execute(
                """
                SELECT COUNT(*) as total
                FROM governance_audit_log
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
            """
            )
            gov_total = cur.fetchone()["total"] or 0

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
        with get_db_cursor(commit=False) as (conn, cur):

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
        with get_db_cursor(commit=False) as (conn, cur):

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

            # Fleet health aggregates
            stress_vals = [a["stress_level"] for a in agents if a.get("stress_level") is not None]
            energy_vals = [a["energy_level"] for a in agents if a.get("energy_level") is not None]
            avg_stress = round(sum(stress_vals) / len(stress_vals), 2) if stress_vals else None
            avg_energy = round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None
            high_stress = sum(1 for s in stress_vals if s > 0.7)

            total_gov = sum(gov_summary.values()) if gov_summary else 0

            # Compliance = agents within ethical limits (stress <= 0.7, energy >= 0.3)
            monitored = [a for a in agents if a.get("stress_level") is not None or a.get("energy_level") is not None]
            healthy_count = sum(
                1 for a in monitored if (a.get("stress_level") or 0) <= 0.7 and (a.get("energy_level") or 1) >= 0.3
            )
            compliance_pct = round(healthy_count / len(monitored) * 100, 1) if monitored else None

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
    """Vigil's Log: governance actions, IAAE welfare checks, and agent health."""
    try:
        events = []

        with get_db_cursor(commit=False) as (conn, cur):
            # 1. Governance audit events (excluding dev commits)
            cur.execute(
                """
                SELECT gal.id, gal.timestamp, gal.event_type, gal.event_category,
                       gal.action, gal.reason, gal.outcome,
                       gal.agent_id, a.name as agent_name,
                       a.first_name as agent_first_name
                FROM governance_audit_log gal
                LEFT JOIN agents a ON a.id = gal.agent_id
                WHERE gal.timestamp >= NOW() - INTERVAL '7 days'
                  AND gal.event_type != 'dev_commit'
                ORDER BY gal.timestamp DESC
                LIMIT 20
            """
            )
            for r in cur.fetchall():
                # Build readable label from event_type + action
                etype = (r["event_type"] or "").replace("_", " ")
                action = r["action"] or ""
                if action:
                    label = f"{etype} — {action}"
                else:
                    label = etype
                events.append(
                    {
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                        "event_category": r["event_category"] or "governance",
                        "label": label,
                        "agent_name": r["agent_first_name"] or r["agent_name"],
                        "severity": "warning" if r["event_category"] == "autonomy" else "info",
                    }
                )

            # 2. IAAE welfare scan — check current agent states against thresholds
            cur.execute(
                """
                SELECT DISTINCT ON (aes.agent_id)
                       aes.agent_id,
                       COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name,
                       aes.stress_level, aes.energy_level,
                       aes.current_mood, aes.timestamp
                FROM agent_emotional_state aes
                JOIN agents a ON a.id = aes.agent_id
                WHERE a.status = 'active'
                ORDER BY aes.agent_id, aes.timestamp DESC
            """
            )
            agent_states = cur.fetchall()

            # Get IAAE thresholds
            cur.execute(
                "SELECT threshold_type, warning_level, critical_level " "FROM iaae_thresholds WHERE is_active = true"
            )
            thresholds = {r["threshold_type"]: r for r in cur.fetchall()}

            stress_warn = float(thresholds.get("stress_high", {}).get("warning_level", 0.70))
            stress_crit = float(thresholds.get("stress_high", {}).get("critical_level", 0.85))
            energy_warn = float(thresholds.get("energy_low", {}).get("warning_level", 0.40))
            energy_crit = float(thresholds.get("energy_low", {}).get("critical_level", 0.30))

            for agent in agent_states:
                stress = float(agent["stress_level"] or 0)
                energy = float(agent["energy_level"] or 0)
                name = agent["agent_name"]
                ts = agent["timestamp"].isoformat() if agent["timestamp"] else None

                if stress >= stress_crit:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"stress critical ({stress:.0%})",
                            "agent_name": name,
                            "severity": "critical",
                        }
                    )
                elif stress >= stress_warn:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"stress elevated ({stress:.0%})",
                            "agent_name": name,
                            "severity": "warning",
                        }
                    )

                if energy <= energy_crit:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"energy critical ({energy:.0%})",
                            "agent_name": name,
                            "severity": "critical",
                        }
                    )
                elif energy <= energy_warn:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"energy low ({energy:.0%})",
                            "agent_name": name,
                            "severity": "warning",
                        }
                    )

            # 3. ARCHIE wellness check
            cur.execute(
                """
                SELECT current_mood, mood_intensity, timestamp
                FROM archie_emotional_state
                ORDER BY timestamp DESC LIMIT 1
            """
            )
            archie_state = cur.fetchone()
            if archie_state and archie_state["timestamp"]:
                events.append(
                    {
                        "timestamp": archie_state["timestamp"].isoformat(),
                        "event_category": "archie_wellness",
                        "label": f"ARCHIE mood: {archie_state['current_mood']}",
                        "agent_name": None,
                        "severity": "info",
                    }
                )

            # 4. Failed dispatches — Vigil flags task execution failures
            cur.execute(
                """
                SELECT tel.id, tel.created_at,
                       COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name) AS agent_name,
                       tel.module_source, tel.task_type, tel.capability,
                       tel.model_used, tel.error_message
                FROM task_execution_log tel
                LEFT JOIN agents a ON a.id = tel.agent_id
                WHERE tel.success = false
                  AND tel.created_at >= NOW() - INTERVAL '7 days'
                ORDER BY tel.created_at DESC
                LIMIT 15
            """
            )
            for r in cur.fetchall():
                module = r["module_source"] or ""
                cap = r["capability"] or r["task_type"] or ""
                detail = f"{module} / {cap}" if module and cap else module or cap
                err = r["error_message"] or "unknown error"
                # Truncate long error messages
                if len(err) > 80:
                    err = err[:77] + "..."
                events.append(
                    {
                        "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                        "event_category": "dispatch",
                        "label": f"dispatch failed — {detail}: {err}" if detail else f"dispatch failed — {err}",
                        "agent_name": r["agent_name"],
                        "severity": "warning",
                    }
                )

            # 5. Escalation events — model tier escalations
            cur.execute(
                """
                SELECT del.id, del.created_at, del.original_model,
                       del.escalated_model, del.escalated_provider,
                       del.capability, del.module_id, del.reason,
                       del.failure_count, del.success,
                       COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name
                FROM dispatch_escalation_log del
                LEFT JOIN agents a ON a.id = del.original_agent_id
                WHERE del.created_at >= NOW() - INTERVAL '7 days'
                ORDER BY del.created_at DESC
                LIMIT 10
            """
            )
            for r in cur.fetchall():
                reason = r["reason"] or "capability exceeded"
                if len(reason) > 60:
                    reason = reason[:57] + "..."
                events.append(
                    {
                        "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                        "event_category": "governance",
                        "label": f"Escalated from {r['original_model']} to {r['escalated_model']}: {reason}",
                        "agent_name": r["agent_name"],
                        "severity": "warning",
                    }
                )

        # Sort by timestamp descending
        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        return jsonify({"success": True, "events": events, "total": len(events)})
    except Exception as e:
        logger.error("get_iaae_enforcement_log error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/iaae/enforcement-log-full")
@login_required
def get_iaae_enforcement_log_full():
    """Vigil's Log — paginated full view with category filter."""
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(5, int(request.args.get("per_page", 20))))
        category_filter = request.args.get("filter", "all")
        events = []

        with get_db_cursor(commit=False) as (conn, cur):
            # 1. Governance audit events
            if category_filter in ("all", "governance", "autonomy"):
                cur.execute(
                    """
                    SELECT gal.id, gal.timestamp, gal.event_type, gal.event_category,
                           gal.action, gal.reason, gal.outcome,
                           gal.agent_id, a.name as agent_name,
                           a.first_name as agent_first_name
                    FROM governance_audit_log gal
                    LEFT JOIN agents a ON a.id = gal.agent_id
                    WHERE gal.timestamp >= NOW() - INTERVAL '30 days'
                      AND gal.event_type != 'dev_commit'
                    ORDER BY gal.timestamp DESC
                    LIMIT 200
                """
                )
                for r in cur.fetchall():
                    etype = (r["event_type"] or "").replace("_", " ")
                    action = r["action"] or ""
                    label = f"{etype} — {action}" if action else etype
                    cat = r["event_category"] or "governance"
                    if category_filter != "all" and cat != category_filter:
                        continue
                    events.append(
                        {
                            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                            "event_category": cat,
                            "label": label,
                            "agent_name": r["agent_first_name"] or r["agent_name"],
                            "severity": "warning" if cat == "autonomy" else "info",
                        }
                    )

            # 2. Welfare checks
            if category_filter in ("all", "welfare"):
                cur.execute(
                    """
                    SELECT DISTINCT ON (aes.agent_id)
                           aes.agent_id,
                           COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name,
                           aes.stress_level, aes.energy_level,
                           aes.current_mood, aes.timestamp
                    FROM agent_emotional_state aes
                    JOIN agents a ON a.id = aes.agent_id
                    WHERE a.status = 'active'
                    ORDER BY aes.agent_id, aes.timestamp DESC
                """
                )
                agent_states = cur.fetchall()

                cur.execute(
                    "SELECT threshold_type, warning_level, critical_level "
                    "FROM iaae_thresholds WHERE is_active = true"
                )
                thresholds = {r["threshold_type"]: r for r in cur.fetchall()}

                stress_warn = float(thresholds.get("stress_high", {}).get("warning_level", 0.70))
                stress_crit = float(thresholds.get("stress_high", {}).get("critical_level", 0.85))
                energy_warn = float(thresholds.get("energy_low", {}).get("warning_level", 0.40))
                energy_crit = float(thresholds.get("energy_low", {}).get("critical_level", 0.30))

                for agent in agent_states:
                    stress = float(agent["stress_level"] or 0)
                    energy = float(agent["energy_level"] or 0)
                    name = agent["agent_name"]
                    ts = agent["timestamp"].isoformat() if agent["timestamp"] else None

                    if stress >= stress_crit:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"stress critical ({stress:.0%})",
                                "agent_name": name,
                                "severity": "critical",
                            }
                        )
                    elif stress >= stress_warn:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"stress elevated ({stress:.0%})",
                                "agent_name": name,
                                "severity": "warning",
                            }
                        )

                    if energy <= energy_crit:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"energy critical ({energy:.0%})",
                                "agent_name": name,
                                "severity": "critical",
                            }
                        )
                    elif energy <= energy_warn:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"energy low ({energy:.0%})",
                                "agent_name": name,
                                "severity": "warning",
                            }
                        )

            # 3. ARCHIE wellness
            if category_filter in ("all", "archie_wellness"):
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, timestamp
                    FROM archie_emotional_state
                    ORDER BY timestamp DESC LIMIT 1
                """
                )
                archie_state = cur.fetchone()
                if archie_state and archie_state["timestamp"]:
                    events.append(
                        {
                            "timestamp": archie_state["timestamp"].isoformat(),
                            "event_category": "archie_wellness",
                            "label": f"ARCHIE mood: {archie_state['current_mood']}",
                            "agent_name": None,
                            "severity": "info",
                        }
                    )

            # 4. Failed dispatches
            if category_filter in ("all", "dispatch"):
                cur.execute(
                    """
                    SELECT tel.id, tel.created_at,
                           COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name)
                               AS agent_name,
                           tel.module_source, tel.task_type, tel.capability,
                           tel.model_used, tel.error_message
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE tel.success = false
                      AND tel.created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY tel.created_at DESC
                    LIMIT 200
                """
                )
                for r in cur.fetchall():
                    module = r["module_source"] or ""
                    cap = r["capability"] or r["task_type"] or ""
                    detail = f"{module} / {cap}" if module and cap else module or cap
                    err = r["error_message"] or "unknown error"
                    if len(err) > 100:
                        err = err[:97] + "..."
                    events.append(
                        {
                            "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                            "event_category": "dispatch",
                            "label": f"dispatch failed — {detail}: {err}" if detail else f"dispatch failed — {err}",
                            "agent_name": r["agent_name"],
                            "severity": "warning",
                        }
                    )

            # 5. Escalation events
            if category_filter in ("all", "governance"):
                cur.execute(
                    """
                    SELECT del.id, del.created_at, del.original_model,
                           del.escalated_model, del.escalated_provider,
                           del.capability, del.module_id, del.reason,
                           del.failure_count, del.success,
                           COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name
                    FROM dispatch_escalation_log del
                    LEFT JOIN agents a ON a.id = del.original_agent_id
                    WHERE del.created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY del.created_at DESC
                    LIMIT 50
                """
                )
                for r in cur.fetchall():
                    reason = r["reason"] or "capability exceeded"
                    if len(reason) > 80:
                        reason = reason[:77] + "..."
                    events.append(
                        {
                            "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                            "event_category": "governance",
                            "label": f"Escalated from {r['original_model']} to {r['escalated_model']}: {reason}",
                            "agent_name": r["agent_name"],
                            "severity": "warning",
                        }
                    )

        # Sort by timestamp descending
        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        total = len(events)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        start = (page - 1) * per_page
        paged = events[start : start + per_page]

        return jsonify(
            {
                "success": True,
                "events": paged,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            }
        )
    except Exception as e:
        logger.error("get_iaae_enforcement_log_full error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ARCHIE STATUS API
# ============================================================================


@bridge_bp.route("/api/archie/status")
@login_required
def get_archie_status():
    """Get A.R.C.H.I.E.'s current status and emotional state"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
# LLM CONNECTIONS MONITOR (Phase 27)
# ============================================================================


@bridge_bp.route("/api/llm/status")
@login_required
def get_llm_status():
    """Get live LLM status from Ollama + external API key checks"""
    try:
        ollama_host = "host.docker.internal"
        ollama_port = 11434

        # 1. Check Ollama health
        status, latency = check_ollama_status(ollama_host, ollama_port)

        # 2. Get loaded models (currently in VRAM/RAM)
        loaded_models = []
        for m in _get_cached_ollama_ps():
            loaded_models.append(
                {
                    "name": m.get("name", "unknown"),
                    "size": m.get("size", 0),
                    "vram": m.get("size_vram", 0),
                    "expires": m.get("expires_at", ""),
                }
            )
        loaded_names = {m["name"] for m in loaded_models}

        # 3. Get all available models (dict of name -> size_bytes)
        available_models = get_ollama_models(ollama_host, ollama_port)

        # 3b. Get models in use — assigned to agents OR configured in active tiers
        assigned_models = set()
        try:
            with get_db_cursor(commit=False) as (aconn, acur):
                acur.execute("SELECT DISTINCT model FROM agents WHERE status = 'active' AND model IS NOT NULL")
                for row in acur.fetchall():
                    assigned_models.add(row["model"])
                acur.execute(
                    "SELECT DISTINCT model_name FROM model_tier_configs WHERE is_active = true AND model_name IS NOT NULL"
                )
                for row in acur.fetchall():
                    assigned_models.add(row["model_name"])
        except Exception:
            pass

        # 4. Build model list with status and size
        models = []
        for name, size_bytes in available_models.items():
            # Check assignment: match with or without :latest suffix
            is_assigned = name in assigned_models or name.split(":")[0] in {m.split(":")[0] for m in assigned_models}
            models.append(
                {
                    "name": name,
                    "provider": "ollama",
                    "status": "loaded" if name in loaded_names else "available",
                    "assigned": is_assigned,
                    "size": size_bytes,
                }
            )

        # 5. Check external AI providers — dynamic from contractor_providers + external_api_keys
        external = []
        try:
            with get_db_cursor(commit=False) as (pconn, pcur):
                pcur.execute(
                    """
                    SELECT cp.provider_key, cp.display_name, cp.is_cloud_proxy,
                           eak.is_active as key_active,
                           eak.monthly_budget_usd, eak.current_month_cost_usd,
                           CASE WHEN eak.api_key_encrypted IS NOT NULL AND eak.api_key_encrypted != ''
                                THEN TRUE ELSE FALSE END as has_key
                    FROM contractor_providers cp
                    LEFT JOIN external_api_keys eak ON cp.provider_key = eak.provider
                    WHERE cp.is_active = TRUE OR eak.is_active = TRUE
                    ORDER BY cp.tier_position
                    """
                )
                ollama_key = os.getenv("OLLAMA_API_KEY", "")
                for row in pcur.fetchall():
                    prov = row["provider_key"]
                    has_key = row["has_key"] if row["has_key"] is not None else False
                    is_active = row["key_active"] if row["key_active"] is not None else False

                    # Cloud proxy providers check env var
                    if row["is_cloud_proxy"]:
                        has_key = bool(ollama_key)
                        if not is_active:
                            is_active = has_key

                    if has_key and is_active:
                        prov_status = "active"
                    elif has_key:
                        prov_status = "configured"
                    else:
                        prov_status = "no_key"
                    entry = {
                        "name": row["display_name"],
                        "provider": prov,
                        "status": prov_status,
                    }
                    budget = row.get("monthly_budget_usd")
                    cost = row.get("current_month_cost_usd")
                    if budget and float(budget) > 0:
                        entry["budget_pct"] = round(float(cost or 0) / float(budget) * 100, 1)
                    external.append(entry)
        except Exception as e:
            logger.warning(f"Could not query contractor_providers: {e}")

        # 6. Get routing mode
        routing_mode = "full"
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
                row = cur.fetchone()
                if row:
                    routing_mode = row["value"]
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
        with get_db_cursor() as (conn, cur):

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
                return jsonify({"success": False, "error": "Node not found"}), 404

            if not verify_api_key(api_key, node["api_key_hash"]):
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
                    logger.debug(f"Synced {models_synced} models for node {node_id}")
                except Exception as e:
                    logger.warning(f"Model sync error for {node_id}: {e}")

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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>", methods=["PUT"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>", methods=["DELETE"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/select", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/request-complete", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/stats")
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
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/approve", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/reject", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/test", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# NODE STATION ASSIGNMENTS - Phase 31
# ============================================================================


@bridge_bp.route("/api/nodes/<node_id>/stations", methods=["GET"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/stations", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["DELETE"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<int:station_id>/nodes", methods=["GET"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/batch-nodes", methods=["POST"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/coverage", methods=["GET"])
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
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/select-for-station", methods=["POST"])
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
        with get_db_cursor(cursor_factory=None) as (conn, cur):

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

            return jsonify({"success": True, "bridge_enabled": enabled, "bridge_priority": priority})

    except Exception as e:
        logger.error(f"Toggle bridge sharing error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/models")
@login_required
def get_bridge_available_models():
    """Get all models available across bridge-enabled nodes, split local vs remote"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Get per-model detail with id, node_id, is_available for toggle support
            cur.execute(
                """
                SELECT m.id, m.node_id, n.node_name, m.model_name, m.model_family,
                       m.parameter_size, m.model_size_gb, m.is_available,
                       m.total_requests, m.avg_response_ms,
                       n.bridge_enabled, n.status as node_status
                FROM node_ollama_models m
                JOIN remote_nodes n ON m.node_id = n.node_id
                WHERE n.status = 'online' AND n.approval_status = 'approved'
                ORDER BY m.model_name
            """
            )
            all_models = cur.fetchall()

            # Get aggregated view for summary
            cur.execute(
                """
                SELECT * FROM v_bridge_available_models
            """
            )
            aggregated = cur.fetchall()

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

            # Get local Ollama models (this host)
            local_models = []
            try:
                ollama_host = os.environ.get("OLLAMA_HOST", "host.docker.internal")
                ollama_port = os.environ.get("OLLAMA_PORT", "11434")
                resp = requests.get(f"http://{ollama_host}:{ollama_port}/api/tags", timeout=5)
                if resp.status_code == 200:
                    for m in resp.json().get("models", []):
                        size_gb = round(m.get("size", 0) / 1e9, 1)
                        local_models.append(
                            {
                                "name": m["name"],
                                "family": m.get("details", {}).get("family", ""),
                                "parameter_size": m.get("details", {}).get("parameter_size", ""),
                                "size_gb": size_gb,
                            }
                        )
            except Exception:
                pass  # Local Ollama unreachable — just skip

            return jsonify(
                {
                    "success": True,
                    "models": aggregated,
                    "all_models": all_models,
                    "local_models": local_models,
                    "summary": summary,
                }
            )

    except Exception as e:
        logger.error(f"Get bridge models error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/nodes/<node_id>/models")
@login_required
def get_node_models(node_id):
    """Get Ollama models available on a specific node"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
                return jsonify({"success": False, "error": "Node not found"}), 404

            # Get models
            cur.execute(
                """
                SELECT id, model_name, model_family, parameter_size, model_size_gb,
                       is_available, total_requests, avg_response_ms, updated_at
                FROM node_ollama_models
                WHERE node_id = %s
                ORDER BY model_name
            """,
                (node_id,),
            )
            models = cur.fetchall()

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
        with get_db_cursor() as (conn, cur):

            # Get node info
            cur.execute(
                """
                SELECT vpn_ip, port, ollama_available FROM remote_nodes WHERE node_id = %s
            """,
                (node_id,),
            )
            node = cur.fetchone()

            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            if not node["ollama_available"]:
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


@bridge_bp.route("/api/nodes/<node_id>/models/<int:model_id>/toggle", methods=["PUT"])
@login_required
def toggle_model_availability(node_id, model_id):
    """Enable or disable a specific model on a node for bridge routing"""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)

    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):

            cur.execute(
                """
                UPDATE node_ollama_models
                SET is_available = %s, updated_at = NOW()
                WHERE id = %s AND node_id = %s
                RETURNING model_name
            """,
                (enabled, model_id, node_id),
            )

            result = cur.fetchone()
            if not result:
                return jsonify({"success": False, "error": "Model not found"}), 404

            return jsonify(
                {
                    "success": True,
                    "model_name": result[0],
                    "is_available": enabled,
                }
            )

    except Exception as e:
        logger.error(f"Toggle model availability error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/select-node", methods=["POST"])
@login_required
def select_node_for_model():
    """Select the best available node for a specific model"""
    data = request.get_json() or {}
    model_name = data.get("model_name")
    prefer_gpu = data.get("prefer_gpu", True)

    if not model_name:
        return jsonify({"success": False, "error": "model_name required"}), 400

    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT * FROM select_node_for_model(%s, %s) LIMIT 1
            """,
                (model_name, prefer_gpu),
            )
            node = cur.fetchone()

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
# DISPATCH ACTIVITY API (Project #91 — Phase 6)
# ============================================================================


@bridge_bp.route("/api/bridge/dispatch-status")
@login_required
def get_dispatch_status():
    """Get current BridgeDispatcher status: active agents, assignments, queue depth"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

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

            # Recent dispatch activity (rolling 24h + 1h)
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
            dispatch_stats_24h = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(*) as total_dispatches,
                       COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                       COUNT(CASE WHEN success = FALSE THEN 1 END) as failed
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """
            )
            dispatch_stats_1h = cur.fetchone()

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
                        "total_1h": dispatch_stats_1h["total_dispatches"],
                        "total_24h": dispatch_stats_24h["total_dispatches"],
                        "successful_1h": dispatch_stats_1h["successful"],
                        "successful_24h": dispatch_stats_24h["successful"],
                        "failed_1h": dispatch_stats_1h["failed"],
                        "failed_24h": dispatch_stats_24h["failed"],
                        "avg_duration_ms": round(float(dispatch_stats_24h["avg_duration_ms"]), 1),
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

        with get_db_cursor(commit=False) as (conn, cur):

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

        with get_db_cursor(commit=False) as (conn, cur):

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
                           bj.station_code,
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
                           bj.station_code,
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
                        "agent_callsign": j.get("agent_callsign") or "",
                        "station_code": j.get("station_code") or "",
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
        with get_db_cursor(commit=False) as (conn, cur):

            # Get the job
            cur.execute(
                """
                SELECT bj.id, bj.job_type, bj.module_source, bj.description,
                       bj.total_steps, bj.completed_steps, bj.failed_steps,
                       bj.status, bj.station_code,
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
                        "station_code": job.get("station_code") or "",
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


@bridge_bp.route("/api/bridge/agent-form-context")
@login_required
def get_agent_form_context():
    """Context data for the Add/Edit Agent modal — models, RAM, stations."""
    try:
        import psutil

        # RAM info
        mem = psutil.virtual_memory()
        ram = {
            "total_gb": round(mem.total / (1024**3), 1),
            "available_gb": round(mem.available / (1024**3), 1),
            "usage_pct": round(mem.percent, 1),
            "reserve_gb": 15,
        }
        if ram["available_gb"] > 25:
            ram["status"] = "green"
        elif ram["available_gb"] >= 15:
            ram["status"] = "amber"
        else:
            ram["status"] = "red"

        # All downloaded models (from /api/tags)
        all_models, _ = _get_cached_ollama_tags()
        # Currently loaded (from /api/ps) — track names + VRAM usage per model
        loaded_raw = _get_cached_ollama_ps()
        loaded_names = set()
        loaded_vram = {}  # model_name -> size_vram_gb
        for m in loaded_raw:
            n = m.get("name", "")
            loaded_names.add(n)
            short = n.replace(":latest", "") if n.endswith(":latest") else n
            loaded_names.add(short)
            vram_bytes = m.get("size_vram", 0)
            if vram_bytes and vram_bytes > 0:
                loaded_vram[n] = round(vram_bytes / (1024**3), 1)
                loaded_vram[short] = loaded_vram[n]

        models = []
        for m in all_models:
            name = m.get("name", "")
            short_name = name.replace(":latest", "") if name.endswith(":latest") else name
            size_gb = round(m.get("size", 0) / (1024**3), 1)
            family = m.get("details", {}).get("family", "")
            params = m.get("details", {}).get("parameter_size", "")
            is_loaded = name in loaded_names or short_name in loaded_names
            vram_gb = loaded_vram.get(name, loaded_vram.get(short_name, 0))
            models.append(
                {
                    "name": name,
                    "size_gb": size_gb,
                    "family": family,
                    "parameter_size": params,
                    "loaded": is_loaded,
                    "vram_gb": vram_gb,
                    "on_gpu": vram_gb > 0,
                }
            )
        models.sort(key=lambda x: (not x["loaded"], x["name"]))

        # Agents already using each model
        model_agents = {}
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            manifest = dispatcher.get_crew_manifest()
            for a in manifest:
                mdl = a.get("model", "")
                if mdl:
                    model_agents.setdefault(mdl, []).append(a.get("full_name") or a.get("name"))
        except Exception:
            pass

        # GPU status
        gpu = {"available": False}
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = [p.strip() for p in result.stdout.strip().split(",")]
                if len(parts) >= 4:
                    vram_total = round(float(parts[1]) / 1024, 1)
                    vram_used = round(float(parts[2]) / 1024, 1)
                    vram_free = round(float(parts[3]) / 1024, 1)
                    # Find which model occupies GPU (has size_vram > 0)
                    gpu_model = None
                    for pm in loaded_raw:
                        sv = pm.get("size_vram", 0)
                        if sv and sv > 0:
                            gpu_model = pm.get("name", "").replace(":latest", "")
                            break
                    gpu = {
                        "available": True,
                        "name": parts[0],
                        "vram_total_gb": vram_total,
                        "vram_used_gb": vram_used,
                        "vram_free_gb": vram_free,
                        "usage_pct": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                        "status": "red" if vram_free < 1.0 else ("amber" if vram_free < 2.0 else "green"),
                        "occupied_by": gpu_model,
                    }
        except Exception:
            pass

        # Media generation — local services + cloud contractors
        media_contractors = []
        try:
            # Cloud: from contractor_providers with image_gen/video_gen capability
            from ai_bridge.external_providers import get_providers_with_capability

            for cap in ("image_gen", "video_gen"):
                for prov in get_providers_with_capability(cap):
                    media_contractors.append(
                        {
                            "provider_key": prov["provider_key"],
                            "display_name": prov["display_name"],
                            "capability": cap,
                            "models": prov.get("models", []),
                            "is_free": prov.get("is_free_tier", False),
                            "has_key": True,
                            "is_active": True,
                            "location": "cloud",
                        }
                    )

            # Well-known media providers not yet configured
            existing_keys = {mc["provider_key"] for mc in media_contractors}
            potential = [
                {
                    "provider_key": "stability",
                    "display_name": "Stability AI",
                    "capability": "image_gen",
                    "models": [{"name": "stable-diffusion-3"}],
                    "is_free": False,
                },
                {
                    "provider_key": "replicate",
                    "display_name": "Replicate",
                    "capability": "image_gen",
                    "models": [{"name": "flux-pro"}],
                    "is_free": False,
                },
            ]
            for p in potential:
                if p["provider_key"] not in existing_keys:
                    media_contractors.append({**p, "has_key": False, "is_active": False, "location": "cloud"})
        except Exception:
            pass

        # Stations
        stations = []
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT station_code, station_name FROM bridge_stations WHERE is_active = TRUE ORDER BY station_name"
                )
                stations = [{"code": r["station_code"], "name": r["station_name"]} for r in cur.fetchall()]
        except Exception:
            pass

        return jsonify(
            {
                "success": True,
                "ram": ram,
                "gpu": gpu,
                "models": models,
                "model_agents": model_agents,
                "media_contractors": media_contractors,
                "stations": stations,
            }
        )
    except Exception as e:
        logger.error(f"Error getting agent form context: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/crew/manifest")
@login_required
def get_crew_manifest():
    """Get the live crew manifest — all agents with status, wellness, jobs, stats."""
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        manifest = dispatcher.get_crew_manifest()

        # RAM capacity from Ollama /api/ps + system memory
        capacity = None
        try:
            import os
            import psutil
            import requests as _req

            mem = psutil.virtual_memory()
            total_gb = round(mem.total / (1024**3), 1)
            available_gb = round(mem.available / (1024**3), 1)
            usage_pct = round(mem.percent, 1)
            reserve_gb = 15

            # Count loaded models + their RAM/VRAM from Ollama
            models_loaded = 0
            models_ram_gb = 0
            gpu_models = []
            cpu_models = []
            _ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "host.docker.internal")
            _ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
            try:
                ps_resp = _req.get(f"http://{_ollama_host}:{_ollama_port}/api/ps", timeout=5)
                if ps_resp.status_code == 200:
                    ps_models = ps_resp.json().get("models", [])
                    models_loaded = len(ps_models)
                    models_ram_gb = round(sum(m.get("size", 0) for m in ps_models) / (1024**3), 1)
                    for pm in ps_models:
                        pm_name = pm.get("name", "").replace(":latest", "")
                        pm_size = round(pm.get("size", 0) / (1024**3), 1)
                        pm_vram = pm.get("size_vram", 0)
                        if pm_vram and pm_vram > 0:
                            gpu_models.append(
                                {"name": pm_name, "size_gb": pm_size, "vram_gb": round(pm_vram / (1024**3), 1)}
                            )
                        else:
                            cpu_models.append({"name": pm_name, "size_gb": pm_size})
            except Exception:
                pass

            # GPU info from nvidia-smi
            gpu_info = None
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.total,memory.used,memory.free",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = [p.strip() for p in result.stdout.strip().split(",")]
                    if len(parts) >= 4:
                        vram_total = round(float(parts[1]) / 1024, 1)
                        vram_used = round(float(parts[2]) / 1024, 1)
                        vram_free = round(float(parts[3]) / 1024, 1)
                        gpu_status = "red" if vram_free < 1.0 else ("amber" if vram_free < 2.0 else "green")
                        gpu_info = {
                            "name": parts[0],
                            "vram_total_gb": vram_total,
                            "vram_used_gb": vram_used,
                            "vram_free_gb": vram_free,
                            "usage_pct": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                            "status": gpu_status,
                            "models": gpu_models,
                        }
            except Exception:
                pass

            if available_gb > 25:
                ram_status = "green"
            elif available_gb >= reserve_gb:
                ram_status = "amber"
            else:
                ram_status = "red"

            capacity = {
                "ram": {
                    "total_gb": total_gb,
                    "available_gb": available_gb,
                    "usage_pct": usage_pct,
                    "reserve_gb": reserve_gb,
                    "status": ram_status,
                },
                "gpu": gpu_info,
                "models_loaded": models_loaded,
                "models_ram_gb": models_ram_gb,
                "gpu_models": gpu_models,
                "cpu_models": cpu_models,
            }
        except Exception as cap_err:
            logger.debug(f"Could not get capacity info: {cap_err}")

        resp = {"success": True, "crew": manifest, "total": len(manifest)}
        if capacity:
            resp["capacity"] = capacity
        return jsonify(resp)
    except Exception as e:
        logger.error(f"Error getting crew manifest: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/model-control", methods=["POST"])
@login_required
def model_control():
    """Load or unload an Ollama model (admin only).

    Body: { "model": "phi3.5:latest", "action": "load"|"unload", "num_gpu": 0 }
    """
    try:
        if not current_user.is_admin:
            return jsonify({"success": False, "error": "Admin access required"}), 403

        data = request.get_json()
        model_name = (data or {}).get("model", "").strip()
        action = (data or {}).get("action", "").strip()
        num_gpu = int((data or {}).get("num_gpu", 0))

        if not model_name or action not in ("load", "unload"):
            return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

        _ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "host.docker.internal")
        _ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
        ollama_url = f"http://{_ollama_host}:{_ollama_port}"

        if action == "unload":
            # Unload: send generate with keep_alive=0
            resp = requests.post(
                f"{ollama_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=10,
            )
            if resp.status_code == 200:
                return jsonify({"success": True, "message": f"{model_name} unloaded"})
            return jsonify({"success": False, "error": f"Ollama returned {resp.status_code}"}), 502

        # action == "load"
        # Check swap limit: count models currently loaded
        try:
            ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=5)
            loaded_count = len(ps_resp.json().get("models", [])) if ps_resp.status_code == 200 else 0
            already_loaded = False
            for m in ps_resp.json().get("models", []) if ps_resp.status_code == 200 else []:
                if m.get("name", "") == model_name or m.get("name", "").replace(":latest", "") == model_name.replace(
                    ":latest", ""
                ):
                    already_loaded = True
                    break
            if already_loaded:
                return jsonify({"success": True, "message": f"{model_name} already loaded"})
        except Exception:
            loaded_count = 0

        # Load: send generate with keep_alive=-1
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model_name,
                "prompt": "hi",
                "options": {"num_gpu": num_gpu, "num_predict": 1},
                "keep_alive": -1,
                "stream": False,
            },
            timeout=300,
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("error"):
                return jsonify({"success": False, "error": result["error"][:300]}), 502
            return jsonify({"success": True, "message": f"{model_name} loaded"})
        return jsonify({"success": False, "error": f"Ollama returned {resp.status_code}: {resp.text[:200]}"}), 502

    except requests.Timeout:
        return jsonify({"success": False, "error": "Model load timed out (300s) — try a smaller model"}), 504
    except Exception as e:
        logger.error(f"model_control error: {e}")
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

        with get_db_cursor() as (conn, cur):

            # Verify agent exists
            cur.execute("SELECT id, name FROM agents WHERE id = %s AND status = 'active'", (agent_id,))
            agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Agent not found or inactive"}), 404

            # Verify station exists
            cur.execute(
                "SELECT id, station_name FROM bridge_stations WHERE station_code = %s AND is_active = TRUE",
                (new_station_code,),
            )
            station = cur.fetchone()
            if not station:
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
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
            row = cur.fetchone()
            return jsonify({"success": True, "routing_mode": row["value"] if row else "full"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/routing-mode", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def set_routing_mode():
    """Set bridge routing mode: local_only, local_cloud, or full."""
    data = request.get_json() or {}
    mode = data.get("routing_mode", "full")
    if mode not in ("local_only", "local_cloud", "full"):
        return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                VALUES ('routing_mode', %s, 'string', 'Bridge routing mode', NOW())
                ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
            """,
                (mode, mode),
            )
            logger.info(f"[Bridge] Routing mode changed to: {mode}")
            return jsonify({"success": True, "routing_mode": mode})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/escalation-mode", methods=["GET"])
@login_required
def get_escalation_mode():
    """Get current bridge escalation mode."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_mode'")
            row = cur.fetchone()
            return jsonify({"success": True, "escalation_mode": row["value"] if row else "auto"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/escalation-mode", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def set_escalation_mode():
    """Set bridge escalation mode: auto, ask_first, or local_only."""
    data = request.get_json() or {}
    mode = data.get("escalation_mode", "auto")
    if mode not in ("auto", "ask_first", "local_only"):
        return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                VALUES ('escalation_mode', %s, 'string', 'Throughput escalation mode', NOW())
                ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
            """,
                (mode, mode),
            )
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
        with get_db_cursor(commit=False) as (conn, cur):
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
    """List external AI providers with 24h stats, model breakdowns, and tier positions.
    All provider metadata now comes from the contractor_providers table (dynamic)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # 1. Fetch all contractor_providers (single source of truth)
            cur.execute(
                """
                SELECT provider_key, display_name, base_url, default_model,
                       auth_method, auth_env_var, is_cloud_proxy, tier_position,
                       models, rate_limits, is_active
                FROM contractor_providers
                ORDER BY tier_position
            """
            )
            cp_rows = cur.fetchall()
            contractor_providers = {row["provider_key"]: dict(row) for row in cp_rows}

            # 2. Fetch DB-managed API keys from external_api_keys
            cur.execute(
                """
                SELECT id, provider, is_active, monthly_budget_usd, current_month_cost_usd,
                       budget_reset_day, account_tier, created_at, updated_at,
                       CASE WHEN api_key_encrypted IS NOT NULL AND api_key_encrypted != ''
                            THEN '****' || RIGHT(api_key_encrypted, 4) ELSE NULL END as key_hint
                FROM external_api_keys
                ORDER BY provider
            """
            )
            db_keys = {row["provider"]: dict(row) for row in cur.fetchall()}

            # 3. Fetch 24h usage stats grouped by model
            cur.execute(
                """
                SELECT model_name, provider,
                       COUNT(*) as requests,
                       COALESCE(SUM(cost_usd), 0) as cost,
                       COALESCE(AVG(response_ms), 0) as avg_latency_ms,
                       ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                             / NULLIF(COUNT(*), 0), 1) as success_rate
                FROM cloud_model_usage
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY model_name, provider
            """
            )
            stats_by_model = {}
            for row in cur.fetchall():
                stats_by_model[row["model_name"]] = {
                    "requests": row["requests"],
                    "cost": float(row["cost"]),
                    "avg_latency_ms": round(float(row["avg_latency_ms"]), 1),
                    "success_rate": float(row["success_rate"]) if row["success_rate"] is not None else 100.0,
                }

            # 3b. Session (2h) and weekly (7d) usage windows
            cur.execute(
                """
                SELECT model_name,
                       COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '2 hours') as session_requests,
                       COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as weekly_requests
                FROM cloud_model_usage
                GROUP BY model_name
            """
            )
            usage_windows = {}
            for row in cur.fetchall():
                usage_windows[row["model_name"]] = {
                    "session_2h": row["session_requests"],
                    "weekly_7d": row["weekly_requests"],
                }

            # 3c. All-time usage stats
            cur.execute(
                """
                SELECT model_name,
                       COUNT(*) as requests,
                       COALESCE(SUM(cost_usd), 0) as cost,
                       COALESCE(AVG(response_ms), 0) as avg_latency_ms,
                       ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                             / NULLIF(COUNT(*), 0), 1) as success_rate,
                       MIN(created_at) as first_used,
                       MAX(created_at) as last_used
                FROM cloud_model_usage
                GROUP BY model_name
            """
            )
            alltime_by_model = {}
            for row in cur.fetchall():
                alltime_by_model[row["model_name"]] = {
                    "requests": row["requests"],
                    "cost": float(row["cost"]),
                    "avg_latency_ms": round(float(row["avg_latency_ms"]), 1),
                    "success_rate": float(row["success_rate"]) if row["success_rate"] is not None else 100.0,
                    "first_used": row["first_used"].isoformat() if row["first_used"] else None,
                    "last_used": row["last_used"].isoformat() if row["last_used"] else None,
                }

            # 4. Per-model disabled state from platform_settings
            cur.execute(
                """
                SELECT key, value FROM platform_settings
                WHERE key LIKE 'model_disabled:%%'
            """
            )
            disabled_models = set()
            for row in cur.fetchall():
                model_name = row["key"].replace("model_disabled:", "", 1)
                if row["value"].lower() == "true":
                    disabled_models.add(model_name)

            # 5. IAAE governance events from last 24h
            cur.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN outcome = 'blocked' THEN 1 ELSE 0 END) as blocked
                FROM governance_audit_log
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
            """
            )
            iaae_row = cur.fetchone()
            iaae_total_24h = iaae_row["total"] if iaae_row else 0
            iaae_blocked_24h = iaae_row["blocked"] if iaae_row and iaae_row["blocked"] else 0

            # 6. Ollama cloud API key check
            ollama_api_key_set = bool(os.environ.get("OLLAMA_API_KEY", "").strip())

            # 7. Build unified response — iterate all contractor_providers
            result = []
            for provider_key, cp in contractor_providers.items():
                db_row = db_keys.get(provider_key)
                models_def = cp.get("models") or []
                if isinstance(models_def, str):
                    models_def = json.loads(models_def)
                rate_limits_def = cp.get("rate_limits") or {}
                if isinstance(rate_limits_def, str):
                    rate_limits_def = json.loads(rate_limits_def)
                tier_pos = cp.get("tier_position", 99)

                # Determine active state + budget
                account_tier = db_row.get("account_tier", "free") if db_row else "free"
                rate_limits = rate_limits_def.get(account_tier, rate_limits_def.get("free", {}))

                if cp.get("is_cloud_proxy"):
                    is_active = db_row["is_active"] if db_row else (cp.get("is_active", False) and ollama_api_key_set)
                    auth_method = "OLLAMA_API_KEY env var"
                    source = "cloud_config"
                else:
                    is_active = db_row["is_active"] if db_row else False
                    auth_method = (cp.get("auth_method") or "api_key").replace("_", " ").title()
                    source = "db"

                monthly_budget = (
                    float(db_row["monthly_budget_usd"]) if db_row and db_row.get("monthly_budget_usd") else 0.0
                )
                current_cost = (
                    float(db_row["current_month_cost_usd"]) if db_row and db_row.get("current_month_cost_usd") else 0.0
                )
                budget_pct = round((current_cost / monthly_budget) * 100, 1) if monthly_budget > 0 else 0.0

                # Build per-model output
                provider_requests = 0
                provider_cost = 0.0
                provider_latency_sum = 0.0
                provider_success_sum = 0.0
                provider_models_with_stats = 0

                models_out = []
                tier_positions = {}
                for m in models_def:
                    m_name = m["name"]
                    m_stats = stats_by_model.get(
                        m_name,
                        {"requests": 0, "cost": 0.0, "avg_latency_ms": 0.0, "success_rate": 100.0},
                    )
                    m_alltime = alltime_by_model.get(m_name, None)
                    m_windows = usage_windows.get(m_name, None)
                    if m_windows and rate_limits:
                        m_windows["session_limit"] = rate_limits.get("session_limit")
                        m_windows["weekly_limit"] = rate_limits.get("weekly_limit")
                    elif rate_limits:
                        m_windows = {
                            "session_2h": 0,
                            "weekly_7d": 0,
                            "session_limit": rate_limits.get("session_limit"),
                            "weekly_limit": rate_limits.get("weekly_limit"),
                        }
                    models_out.append(
                        {
                            "name": m_name,
                            "tier": provider_key,
                            "tier_position": tier_pos,
                            "enabled": m_name not in disabled_models,
                            "stats_24h": m_stats,
                            "stats_alltime": m_alltime,
                            "usage_windows": m_windows,
                        }
                    )
                    tier_positions[m_name] = tier_pos

                    provider_requests += m_stats["requests"]
                    provider_cost += m_stats["cost"]
                    if m_stats["requests"] > 0:
                        provider_latency_sum += m_stats["avg_latency_ms"]
                        provider_success_sum += m_stats["success_rate"]
                        provider_models_with_stats += 1

                avg_latency = (
                    round(provider_latency_sum / provider_models_with_stats, 1)
                    if provider_models_with_stats > 0
                    else 0.0
                )
                avg_success = (
                    round(provider_success_sum / provider_models_with_stats, 1)
                    if provider_models_with_stats > 0
                    else 100.0
                )

                # Use DB cost if available, else aggregated
                if not current_cost and provider_cost > 0:
                    current_cost = round(provider_cost, 6)
                    budget_pct = round((current_cost / monthly_budget) * 100, 1) if monthly_budget > 0 else 0.0

                entry = {
                    "provider": provider_key,
                    "display_name": cp.get("display_name", provider_key),
                    "is_active": is_active,
                    "account_tier": account_tier,
                    "monthly_budget_usd": monthly_budget,
                    "current_month_cost_usd": current_cost,
                    "budget_pct": budget_pct,
                    "source": source,
                    "auth_method": auth_method,
                    "key_hint": db_row.get("key_hint") if db_row else None,
                    "tier_positions": tier_positions,
                    "tier_position": tier_pos,
                    "is_cloud_proxy": cp.get("is_cloud_proxy", False),
                    "stats_24h": {
                        "requests": provider_requests,
                        "cost": round(provider_cost, 6),
                        "success_rate": avg_success,
                        "avg_latency_ms": avg_latency,
                    },
                    "models": models_out,
                }
                result.append(entry)

            return jsonify(
                {
                    "success": True,
                    "providers": result,
                    "iaae_total_24h": iaae_total_24h,
                    "iaae_blocked_24h": iaae_blocked_24h,
                }
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/external-providers", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def upsert_external_provider():
    """Add or update an external AI provider API key. Validates against contractor_providers table."""
    data = request.get_json() or {}
    provider = data.get("provider", "").strip().lower()
    api_key = data.get("api_key", "").strip()

    try:
        with get_db_cursor() as (conn, cur):
            # Validate provider exists in contractor_providers
            cur.execute(
                "SELECT provider_key, is_cloud_proxy FROM contractor_providers WHERE provider_key = %s",
                (provider,),
            )
            cp_row = cur.fetchone()
            if not cp_row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Unknown provider: {provider}. Add it to Contractor Providers first.",
                        }
                    ),
                    400,
                )

            # Cloud providers use OLLAMA_API_KEY from env
            if cp_row["is_cloud_proxy"]:
                api_key = "OLLAMA_API_KEY"
            elif not api_key:
                # Check if key already exists (edit mode — keep existing)
                cur.execute(
                    "SELECT api_key_encrypted FROM external_api_keys WHERE provider = %s",
                    (provider,),
                )
                existing = cur.fetchone()
                if not existing or not existing["api_key_encrypted"]:
                    return jsonify({"success": False, "error": "API key required"}), 400
                api_key = existing["api_key_encrypted"]

            budget = data.get("monthly_budget_usd", 10.0)
            account_tier = data.get("account_tier", "free").strip().lower()
            valid_tiers = ("free", "pro", "pay_as_you_go", "enterprise", "max")
            if account_tier not in valid_tiers:
                account_tier = "free"

            cur.execute(
                """
                INSERT INTO external_api_keys (provider, api_key_encrypted, monthly_budget_usd, account_tier, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (provider) DO UPDATE SET
                    api_key_encrypted = %s, monthly_budget_usd = %s, account_tier = %s,
                    is_active = TRUE, updated_at = NOW()
                RETURNING id, provider, is_active, monthly_budget_usd, account_tier
            """,
                (provider, api_key, budget, account_tier, api_key, budget, account_tier),
            )
            row = cur.fetchone()

            # Invalidate external_providers cache
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))
                from external_providers import invalidate_provider_cache

                invalidate_provider_cache()
            except ImportError:
                pass

            return jsonify({"success": True, "provider": dict(row)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/external-providers/<provider>/toggle", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def toggle_external_provider(provider):
    """Enable/disable an external provider."""
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                "UPDATE external_api_keys SET is_active = NOT is_active, updated_at = NOW() WHERE provider = %s",
                (provider,),
            )
            return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route(
    "/api/external-providers/<provider>/models/<path:model_name>/toggle",
    methods=["PUT"],
)
@login_required
def toggle_provider_model(provider, model_name):
    """Enable/disable a specific model under a provider for routing."""
    data = request.get_json() or {}
    enabled = data.get("enabled")

    if enabled is None or not isinstance(enabled, bool):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Request body must include 'enabled' (boolean)",
                }
            ),
            400,
        )

    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            setting_key = f"model_disabled:{model_name}"
            # Store as disabled flag: enabled=True means NOT disabled, so value="false"
            disabled_value = "false" if enabled else "true"
            cur.execute(
                """
                INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                VALUES (%s, %s, 'boolean', %s, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = NOW()
                """,
                (
                    setting_key,
                    disabled_value,
                    f"Model routing toggle for {model_name} (provider: {provider})",
                ),
            )
            return jsonify({"success": True, "model": model_name, "enabled": enabled})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# CONTRACTOR PROVIDER DEFINITIONS API (dynamic provider management)
# ============================================================================


@bridge_bp.route("/api/contractor-providers", methods=["GET"])
@login_required
def list_contractor_providers():
    """List all contractor provider definitions (for UI dropdowns and admin)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, provider_key, display_name, base_url, default_model,
                       auth_method, auth_env_var, is_cloud_proxy, tier_position,
                       models, rate_limits, is_active, created_at, updated_at
                FROM contractor_providers
                ORDER BY tier_position
            """
            )
            rows = cur.fetchall()
            providers = []
            for row in rows:
                d = dict(row)
                d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
                d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
                providers.append(d)
            return jsonify({"success": True, "providers": providers})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/contractor-providers", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def upsert_contractor_provider():
    """Create or update a contractor provider definition."""
    data = request.get_json() or {}
    provider_key = data.get("provider_key", "").strip().lower()
    if not provider_key:
        return jsonify({"success": False, "error": "provider_key is required"}), 400

    display_name = data.get("display_name", provider_key.replace("_", " ").title())
    base_url = data.get("base_url", "").strip()
    if not base_url:
        return jsonify({"success": False, "error": "base_url is required"}), 400

    default_model = data.get("default_model", "").strip() or None
    auth_method = data.get("auth_method", "api_key").strip()
    auth_env_var = data.get("auth_env_var", "").strip() or None
    is_cloud_proxy = bool(data.get("is_cloud_proxy", False))
    tier_position = int(data.get("tier_position", 99))
    models = data.get("models", [])
    rate_limits = data.get("rate_limits", {})
    is_active = bool(data.get("is_active", False))

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO contractor_providers
                    (provider_key, display_name, base_url, default_model, auth_method,
                     auth_env_var, is_cloud_proxy, tier_position, models, rate_limits, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (provider_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    base_url = EXCLUDED.base_url,
                    default_model = EXCLUDED.default_model,
                    auth_method = EXCLUDED.auth_method,
                    auth_env_var = EXCLUDED.auth_env_var,
                    is_cloud_proxy = EXCLUDED.is_cloud_proxy,
                    tier_position = EXCLUDED.tier_position,
                    models = EXCLUDED.models,
                    rate_limits = EXCLUDED.rate_limits,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                RETURNING id, provider_key, display_name
            """,
                (
                    provider_key,
                    display_name,
                    base_url,
                    default_model,
                    auth_method,
                    auth_env_var,
                    is_cloud_proxy,
                    tier_position,
                    json.dumps(models),
                    json.dumps(rate_limits),
                    is_active,
                ),
            )
            row = cur.fetchone()

            # Invalidate external_providers cache
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))
                from external_providers import invalidate_provider_cache

                invalidate_provider_cache()
            except ImportError:
                pass

            return jsonify({"success": True, "provider": dict(row)})
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
    """Return last 50 dispatch events from task_execution_log."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT tel.id, 'task' AS source,
                       COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name) AS agent_name,
                       tel.module_source, tel.task_type, tel.capability,
                       tel.model_used, tel.success, tel.created_at
                FROM task_execution_log tel
                LEFT JOIN agents a ON a.id = tel.agent_id
                ORDER BY tel.created_at DESC
                LIMIT 50
            """
            )
            events = cur.fetchall()
            for ev in events:
                ev["created_at"] = ev["created_at"].isoformat() + "Z" if ev["created_at"] else None
            return jsonify(events)
    except Exception as e:
        logger.error("activity_history error: %s", e)
        return jsonify([])


# ============================================================================
# STATION ACTIONS — DB-driven action registry for Bridge ACTN tab
# ============================================================================


@bridge_bp.route("/api/station-actions")
@login_required
def get_station_actions():
    """Return registered station actions, filtered by station_code or module_source."""
    try:
        station_code = request.args.get("station_code")
        module_source = request.args.get("module_source")

        with get_db_cursor(commit=False) as (conn, cur):
            if station_code:
                # Support comma-separated station codes (zones map to multiple stations)
                codes = [c.strip() for c in station_code.split(",") if c.strip()]
                cur.execute(
                    """
                    SELECT id, action_key, station_code, module_source, label,
                           description, icon, color_class, sort_order,
                           http_method, endpoint_path, params_schema,
                           creates_job, job_type, requires_admin, test_config
                    FROM station_actions
                    WHERE station_code = ANY(%s) AND is_active = TRUE
                    ORDER BY sort_order, label
                    """,
                    (codes,),
                )
            elif module_source:
                cur.execute(
                    """
                    SELECT id, action_key, station_code, module_source, label,
                           description, icon, color_class, sort_order,
                           http_method, endpoint_path, params_schema,
                           creates_job, job_type, requires_admin, test_config
                    FROM station_actions
                    WHERE module_source = %s AND is_active = TRUE
                    ORDER BY sort_order, label
                    """,
                    (module_source,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, action_key, station_code, module_source, label,
                           description, icon, color_class, sort_order,
                           http_method, endpoint_path, params_schema,
                           creates_job, job_type, requires_admin, test_config
                    FROM station_actions
                    WHERE is_active = TRUE
                    ORDER BY station_code, sort_order, label
                    """
                )

            actions = cur.fetchall()
            # Ensure params_schema is always a list
            for a in actions:
                if a.get("params_schema") is None:
                    a["params_schema"] = []

        return jsonify({"success": True, "actions": actions, "count": len(actions)})
    except Exception as e:
        logger.error("station_actions error: %s", e)
        return jsonify({"success": True, "actions": [], "count": 0})


# ---------------------------------------------------------------------------
# Benchmark endpoints (Project #110)
# ---------------------------------------------------------------------------
@bridge_bp.route("/api/benchmarks/start", methods=["POST"])
@login_required
def start_benchmark():
    """Start a benchmark run for an action_key."""
    try:
        from services.benchmark_service import start_benchmark as _start

        data = request.get_json() or {}
        action_key = data.get("action_key")
        if not action_key:
            return jsonify({"success": False, "error": "action_key required"}), 400

        user_id = current_user.id if current_user.is_authenticated else None
        include_contractors = data.get("include_contractors", False)
        result = _start(action_key, user_id=user_id, include_contractors=include_contractors)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error("benchmark start error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/active")
@login_required
def get_active_benchmark():
    """Return the currently running benchmark, if any."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, action_key, station_code, total_agents,
                       completed_agents, failed_agents, status, started_at
                FROM action_benchmark_runs
                WHERE status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": True, "active": False})
            return jsonify(
                {
                    "success": True,
                    "active": True,
                    "run": {
                        "id": row["id"],
                        "action_key": row["action_key"],
                        "station_code": row["station_code"],
                        "total_agents": row["total_agents"],
                        "completed_agents": row["completed_agents"],
                        "failed_agents": row["failed_agents"],
                        "status": row["status"],
                        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    },
                }
            )
    except Exception as e:
        logger.error("active benchmark check error: %s", e)
        return jsonify({"success": True, "active": False})


@bridge_bp.route("/api/benchmarks/<int:run_id>/status")
@login_required
def get_benchmark_status(run_id):
    """Lightweight progress poll — no pool checkout, direct connection."""
    import psycopg2

    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=os.environ.get("DB_PORT", "5432"),
            database=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT completed_agents, failed_agents, total_agents, status " "FROM action_benchmark_runs WHERE id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify(
            {
                "success": True,
                "run": {
                    "completed_agents": row[0],
                    "failed_agents": row[1],
                    "total_agents": row[2],
                    "status": row[3],
                },
            }
        )
    except Exception as e:
        return jsonify({"success": True, "run": {"status": "running", "completed_agents": 0, "failed_agents": 0}})
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@bridge_bp.route("/api/benchmarks/<int:run_id>")
@login_required
def get_benchmark(run_id):
    """Get benchmark run info + ranked leaderboard."""
    try:
        from services.benchmark_service import get_benchmark_results

        data = get_benchmark_results(run_id)
        if not data:
            return jsonify({"success": False, "error": "Run not found"}), 404

        # Serialize datetimes
        run = data["run"]
        for key in ("started_at", "completed_at"):
            if run.get(key):
                run[key] = run[key].isoformat() if hasattr(run[key], "isoformat") else str(run[key])

        for r in data["results"]:
            if r.get("tested_at"):
                r["tested_at"] = (
                    r["tested_at"].isoformat() if hasattr(r["tested_at"], "isoformat") else str(r["tested_at"])
                )

        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error("benchmark get error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/<int:run_id>/skill-updates")
@login_required
def get_benchmark_skill_updates(run_id):
    """Get skill adjustments made by a specific benchmark run."""
    try:
        from services.benchmark_service import get_skill_updates

        data = get_skill_updates(run_id)
        return jsonify({"success": True, **(data or {})})
    except Exception as e:
        logger.error("benchmark skill-updates error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/<int:run_id>/pick", methods=["POST"])
@login_required
def set_benchmark_pick(run_id):
    """Mark an agent as the human-picked best for a benchmark run."""
    try:
        data = request.get_json(force=True)
        agent_name = data.get("agent_name")
        if not agent_name:
            return jsonify({"success": False, "error": "agent_name required"}), 400

        with get_db_cursor() as (conn, cur):
            # Clear previous picks for this run
            cur.execute(
                "UPDATE action_benchmark_results SET is_human_pick = FALSE WHERE run_id = %s",
                (run_id,),
            )
            # Set the new pick
            cur.execute(
                "UPDATE action_benchmark_results SET is_human_pick = TRUE WHERE run_id = %s AND agent_name = %s",
                (run_id, agent_name),
            )

            # Also boost picked agent's skill proficiency to 5 (Expert)
            try:
                cur.execute("SELECT test_config FROM action_benchmark_runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
                if row:
                    import json as _json

                    tc = row.get("test_config") if isinstance(row, dict) else row[0]
                    if isinstance(tc, str):
                        tc = _json.loads(tc)
                    capability = (tc or {}).get("capability", "general")
                    cur.execute("SELECT skill_name FROM capability_skill_map WHERE capability = %s", (capability,))
                    mapping = cur.fetchone()
                    skill_name = (
                        (mapping.get("skill_name") if isinstance(mapping, dict) else mapping[0])
                        if mapping
                        else capability
                    )
                    cur.execute(
                        "SELECT agent_id FROM action_benchmark_results WHERE run_id = %s AND agent_name = %s",
                        (run_id, agent_name),
                    )
                    ar = cur.fetchone()
                    if ar:
                        agent_id = ar.get("agent_id") if isinstance(ar, dict) else ar[0]
                        cur.execute(
                            """INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, updated_at)
                            VALUES (%s, %s, 'human_pick', %s, NOW())
                            ON CONFLICT (agent_id, skill_name) DO UPDATE
                                SET proficiency_level = EXCLUDED.proficiency_level, updated_at = NOW()""",
                            (agent_id, skill_name, 5),
                        )
            except Exception as e:
                logger.warning("Human pick skill boost failed: %s", e)

        return jsonify({"success": True, "agent_name": agent_name})
    except Exception as e:
        logger.error("set_benchmark_pick error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/latest/<path:action_key>")
@login_required
def get_latest_benchmark(action_key):
    """Get the most recent completed benchmark for an action."""
    try:
        from services.benchmark_service import get_latest_benchmark as _latest

        data = _latest(action_key)
        if not data:
            return jsonify({"success": False, "error": "No benchmarks found"}), 404

        # Serialize datetimes
        run = data["run"]
        for key in ("started_at", "completed_at"):
            if run.get(key):
                run[key] = run[key].isoformat() if hasattr(run[key], "isoformat") else str(run[key])

        for r in data["results"]:
            if r.get("tested_at"):
                r["tested_at"] = (
                    r["tested_at"].isoformat() if hasattr(r["tested_at"], "isoformat") else str(r["tested_at"])
                )

        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error("benchmark latest error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Benchmark Recommendations
# ---------------------------------------------------------------------------


@bridge_bp.route("/api/benchmarks/recommendations")
@login_required
def get_recommendations():
    """List benchmark recommendations (optional ?station=X&status=pending)."""
    try:
        from services.benchmark_service import get_station_recommendations

        station = request.args.get("station")
        status = request.args.get("status", "pending")
        recs = get_station_recommendations(station_code=station, status=status)
        return jsonify({"success": True, "recommendations": recs})
    except Exception as e:
        logger.error("get recommendations error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/recommendations/generate", methods=["POST"])
@login_required
def generate_recommendations():
    """Trigger recommendation generation for all or a specific station."""
    try:
        from services.benchmark_service import generate_station_recommendations

        data = request.get_json(force=True) if request.is_json else {}
        station = data.get("station_code")
        recs = generate_station_recommendations(station_code=station)
        return jsonify(
            {
                "success": True,
                "generated": len(recs),
                "recommendations": recs,
            }
        )
    except Exception as e:
        logger.error("generate recommendations error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/recommendations/<int:rec_id>/resolve", methods=["POST"])
@login_required
def resolve_recommendation_route(rec_id):
    """Approve or reject a recommendation. Body: {approved: bool}."""
    try:
        from services.benchmark_service import resolve_recommendation

        data = request.get_json(force=True)
        approved = data.get("approved", False)
        user_id = current_user.id if current_user.is_authenticated else None
        result = resolve_recommendation(rec_id, approved=approved, user_id=user_id)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error("resolve recommendation error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/station-summary")
@login_required
def get_benchmark_station_summary():
    """Per-station summary: current agent, top 3, human pick, latest date."""
    try:
        from services.benchmark_service import get_station_summary

        summaries = get_station_summary()
        return jsonify({"success": True, "stations": summaries})
    except Exception as e:
        logger.error("station summary error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/score-matrix")
@login_required
def get_score_matrix_route():
    """Return agent×station score grid for heatmap display."""
    try:
        from services.benchmark_service import get_score_matrix

        matrix = get_score_matrix()
        return jsonify({"success": True, **matrix})
    except Exception as e:
        logger.error("score matrix error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/placement/generate", methods=["POST"])
@login_required
def generate_placement_route():
    """Generate optimal agent placement plan (not auto-applied)."""
    try:
        from services.benchmark_service import generate_optimal_placement

        plan = generate_optimal_placement()
        return jsonify({"success": True, **plan})
    except Exception as e:
        logger.error("generate placement error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/benchmarks/placement/apply", methods=["POST"])
@login_required
def apply_placement_route():
    """Apply an approved placement plan."""
    try:
        from services.benchmark_service import apply_placement

        data = request.get_json(force=True)
        user_id = current_user.id if current_user.is_authenticated else None
        result = apply_placement(data, user_id=user_id)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error("apply placement error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/bridge/resources")
@login_required
def get_bridge_resources():
    """System resource overview from host monitor + Ollama model roster.

    Pulls real GPU data from host_monitor_data.json (same source as System Ops),
    shows all available vs loaded Ollama models, Ollama config limits, and
    capacity analysis for how many more models can fit in RAM.
    """
    try:
        import psutil

        # ── Real GPU data from host monitor ──
        gpu_data = {
            "name": "Unknown",
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "utilization_pct": 0,
            "temperature": None,
            "driver": None,
        }
        try:
            host_monitor_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "host_monitor_data.json",
            )
            with open(host_monitor_path) as f:
                import json as _json

                hm = _json.load(f)
            gpus = hm.get("gpu", [])
            if gpus and isinstance(gpus, list) and len(gpus) > 0:
                g = gpus[0]
                gpu_data = {
                    "name": g.get("model", "Unknown"),
                    "vram_total_mb": g.get("vram_total_mb", 0),
                    "vram_used_mb": g.get("vram_used_mb", 0),
                    "utilization_pct": g.get("utilization_percent", 0),
                    "temperature": g.get("temperature"),
                    "driver": g.get("driver"),
                }
            # CPU model from host monitor
            cpu_model = hm.get("cpu", {}).get("model", "")
        except Exception:
            cpu_model = ""

        # ── Ollama: loaded models ──
        loaded_models = _get_cached_ollama_ps()
        ollama_loaded = []
        model_ram_used = 0
        model_vram_used = 0
        for m in loaded_models:
            size_bytes = m.get("size", 0)
            vram_bytes = m.get("size_vram", 0)
            ram_bytes = size_bytes - vram_bytes
            device = "gpu" if vram_bytes and vram_bytes > 0 else "cpu"
            if device == "gpu":
                model_vram_used += vram_bytes
            model_ram_used += max(ram_bytes, 0)
            ollama_loaded.append(
                {
                    "name": m.get("name", "unknown"),
                    "size_gb": round(size_bytes / (1024**3), 1) if size_bytes else 0,
                    "ram_gb": round(max(ram_bytes, 0) / (1024**3), 1),
                    "vram_gb": round(vram_bytes / (1024**3), 1) if vram_bytes else 0,
                    "device": device,
                }
            )

        # ── Ollama: all available models ──
        all_models, model_count = _get_cached_ollama_tags()
        ollama_available = []
        unloaded_total_gb = 0
        loaded_names = {m["name"] for m in ollama_loaded}
        for m in all_models:
            name = m.get("name", "unknown")
            size_gb = round(m.get("size", 0) / (1024**3), 1)
            is_cloud = ":cloud" in name
            is_loaded = name in loaded_names
            ollama_available.append(
                {
                    "name": name,
                    "size_gb": size_gb,
                    "loaded": is_loaded,
                    "cloud": is_cloud,
                }
            )
            if not is_loaded and not is_cloud and size_gb > 0:
                unloaded_total_gb += size_gb

        # ── System stats ──
        cpu_pct = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        ram_available_gb = round(ram.available / (1024**3), 1)

        # ── Ollama config (read from systemd override on host) ──
        ollama_config = {
            "max_loaded_models": 20,
            "keep_alive": "24h",
            "num_parallel": 4,
            "num_cpu": psutil.cpu_count(),
            "cpu_pct": 70,
        }
        try:
            conf_path = "/etc/systemd/system/ollama.service.d/override.conf"
            if os.path.exists(conf_path):
                with open(conf_path) as _f:
                    for line in _f:
                        if "OLLAMA_MAX_LOADED_MODELS" in line:
                            val = line.split("=")[-1].strip().rstrip('"')
                            ollama_config["max_loaded_models"] = int(val)
                        elif "OLLAMA_KEEP_ALIVE" in line:
                            ollama_config["keep_alive"] = line.split("=")[-1].strip().rstrip('"')
                        elif "OLLAMA_NUM_PARALLEL" in line:
                            val = line.split("=")[-1].strip().rstrip('"')
                            ollama_config["num_parallel"] = int(val)
                        elif "OLLAMA_NUM_CPU" in line:
                            val = line.split("=")[-1].strip().rstrip('"')
                            ollama_config["num_cpu"] = int(val)
                            total = psutil.cpu_count()
                            ollama_config["cpu_pct"] = round(int(val) / total * 100) if total else 70
        except Exception:
            pass

        # ── Capacity analysis ──
        local_unloaded = [m for m in ollama_available if not m["loaded"] and not m["cloud"] and m["size_gb"] > 0]
        # Sort by size ascending (load small models first)
        local_unloaded.sort(key=lambda m: m["size_gb"])
        can_fit = []
        remaining_ram = ram_available_gb
        remaining_slots = ollama_config["max_loaded_models"] - len(ollama_loaded)
        for m in local_unloaded:
            if remaining_slots <= 0:
                break
            if m["size_gb"] <= remaining_ram:
                can_fit.append(m["name"])
                remaining_ram -= m["size_gb"]
                remaining_slots -= 1

        result = {
            "gpu": gpu_data,
            "cpu": {
                "model": cpu_model,
                "cores": psutil.cpu_count(),
                "usage_pct": round(cpu_pct, 1),
            },
            "ram": {
                "total_gb": round(ram.total / (1024**3), 1),
                "used_gb": round(ram.used / (1024**3), 1),
                "available_gb": ram_available_gb,
                "pct": ram.percent,
                "models_ram_gb": round(model_ram_used / (1024**3), 1),
            },
            "ollama_config": ollama_config,
            "ollama_loaded": ollama_loaded,
            "ollama_available": ollama_available,
            "capacity": {
                "loaded_count": len(ollama_loaded),
                "available_count": model_count,
                "local_count": sum(1 for m in ollama_available if not m["cloud"]),
                "cloud_count": sum(1 for m in ollama_available if m["cloud"]),
                "max_slots": ollama_config["max_loaded_models"],
                "free_slots": max(0, ollama_config["max_loaded_models"] - len(ollama_loaded)),
                "unloaded_total_gb": round(unloaded_total_gb, 1),
                "ram_available_gb": ram_available_gb,
                "can_fit_more": remaining_slots > 0 and ram_available_gb > 1,
                "could_load": can_fit,
            },
        }
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error("resources error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/dispatch")
@login_required
def get_station_dispatch(station_code):
    """Get recent dispatch activity for a station using capability_station attribution."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT tel.id, 'task' AS source,
                       COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name) AS agent_name,
                       tel.module_source, tel.task_type, tel.capability,
                       tel.model_used, tel.success, tel.created_at,
                       tel.duration_ms
                FROM task_execution_log tel
                LEFT JOIN agents a ON a.id = tel.agent_id
                WHERE (
                    tel.request_metadata->>'capability_station' = %s
                    OR (tel.request_metadata->>'capability_station' IS NULL AND tel.station_code = %s)
                )
                ORDER BY tel.created_at DESC
                LIMIT 20
            """,
                (station_code, station_code),
            )
            events = cur.fetchall()
            for ev in events:
                ev["created_at"] = ev["created_at"].isoformat() + "Z" if ev["created_at"] else None
            return jsonify(events)
    except Exception as e:
        logger.error("station_dispatch error: %s", e)
        return jsonify([])


@bridge_bp.route("/api/stations/<station_code>/metrics")
@login_required
def get_station_metrics(station_code):
    """Get performance metrics for a station (24h window).

    Uses task_execution_log with capability_station metadata to attribute
    work to the station it was done FOR — including cross-station helpers
    and cloud contractors.
    """
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Query task_execution_log using capability_station metadata
            # for correct attribution of cross-station + contractor work.
            # Fallback to station_code for older entries without the field.
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    COALESCE(AVG(duration_ms), 0)::int AS avg_response_ms,
                    COALESCE(SUM(tokens_used), 0) AS total_tokens,
                    CASE WHEN COUNT(*) > 0
                        THEN ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1)
                        ELSE 0
                    END AS success_rate
                FROM task_execution_log
                WHERE (
                    request_metadata->>'capability_station' = %s
                    OR (request_metadata->>'capability_station' IS NULL AND station_code = %s)
                )
                AND created_at > NOW() - INTERVAL '24 hours'
                """,
                (station_code, station_code),
            )
            stats = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "metrics": {
                        "requests_24h": stats["total_requests"],
                        "avg_response_ms": stats["avg_response_ms"],
                        "tokens_24h": int(stats["total_tokens"]),
                        "success_rate": float(stats["success_rate"]),
                    },
                }
            )
    except Exception as e:
        logger.error(f"Error getting station metrics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/stations/<station_code>/module-preview/<module_id>")
@login_required
def get_module_preview(station_code, module_id):
    """Get preview data for a module in station context"""
    from module_registry import get_module_by_id

    mod = get_module_by_id(module_id)
    if not mod:
        return jsonify({"success": False, "error": "Module not found"}), 404

    result = {
        "id": mod.id,
        "name": mod.name,
        "icon": mod.icon,
        "route": mod.route,
        "description": mod.description,
        "version": mod.version,
        "category": mod.category.value if hasattr(mod.category, "value") else str(mod.category),
        "tags": mod.tags,
        "stats": {},
    }

    # Module-specific stat queries (best-effort)
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            if module_id == "email-manager":
                cur.execute("SELECT COUNT(*) AS count FROM email_messages WHERE created_at > NOW() - INTERVAL '7 days'")
                r = cur.fetchone()
                if r:
                    result["stats"]["emails_7d"] = r["count"]
            elif module_id == "backup-manager":
                cur.execute("SELECT COUNT(*) AS count FROM backup_history WHERE status = 'completed'")
                r = cur.fetchone()
                if r:
                    result["stats"]["completed_backups"] = r["count"]
            elif module_id == "bridge":
                cur.execute(
                    "SELECT COUNT(*) AS count FROM task_execution_log WHERE created_at > NOW() - INTERVAL '24 hours'"
                )
                r = cur.fetchone()
                if r:
                    result["stats"]["interactions_24h"] = r["count"]
            elif module_id == "consciousness":
                cur.execute("SELECT COUNT(*) AS count FROM knowledge_base WHERE status = 'active'")
                r = cur.fetchone()
                if r:
                    result["stats"]["active_entries"] = r["count"]
    except Exception:
        pass  # Stats are optional — don't fail if table doesn't exist

    return jsonify({"success": True, "module": result})


@bridge_bp.route("/api/agents/<int:agent_id>/executions")
@login_required
def agent_executions(agent_id):
    """Recent execution history for a specific agent via orchestration_steps."""
    limit = request.args.get("limit", 10, type=int)
    try:
        with get_db_cursor(commit=False) as (conn, cur):
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
        with get_db_cursor(commit=False) as (conn, cur):
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
            if state:
                state["timestamp"] = state["timestamp"].isoformat() if state.get("timestamp") else None
            if rest:
                rest["started_at"] = rest["started_at"].isoformat() if rest.get("started_at") else None
                rest["ended_at"] = rest["ended_at"].isoformat() if rest.get("ended_at") else None
            return jsonify({"emotional_state": state, "last_rest": rest})
    except Exception as e:
        logger.error("agent_emotional_state_detail error: %s", e)
        return jsonify({"emotional_state": None, "last_rest": None})


_profile_cache = {}  # agent_id -> (timestamp, response_dict)
_profile_cache_ttl = 30  # seconds


@bridge_bp.route("/api/agents/<int:agent_id>/profile")
@login_required
def agent_profile(agent_id):
    """Aggregated agent profile: details, skills, emotional state, performance, memory."""
    # Server-side cache: return cached if fresh
    import time as _time

    cached = _profile_cache.get(agent_id)
    if cached and (_time.time() - cached[0]) < _profile_cache_ttl:
        return jsonify(cached[1])

    try:
        with get_db_cursor(commit=False) as (conn, cur):

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
                return jsonify({"success": False, "error": "Agent not found"}), 404

            for k in ["created_at", "last_used"]:
                if agent.get(k):
                    agent[k] = agent[k].isoformat()

            # Skills (with degradation count from learning log — LATERAL to avoid duplicates)
            cur.execute(
                """
                SELECT s.id, s.skill_name, s.skill_category, s.proficiency_level, s.notes,
                       COALESCE(ll.degradation_count, 0) as degradation_count
                FROM agent_skills s
                LEFT JOIN LATERAL (
                    SELECT degradation_count
                    FROM agent_learning_log
                    WHERE agent_id = s.agent_id AND skill_name = s.skill_name
                    ORDER BY confidence DESC
                    LIMIT 1
                ) ll ON true
                WHERE s.agent_id = %s
                ORDER BY s.proficiency_level DESC, s.skill_name
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

            result = {
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
            _profile_cache[agent_id] = (_time.time(), result)
            return jsonify(result)

    except Exception as e:
        logger.error("agent_profile error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# --- Agent Memory CRUD ---


@bridge_bp.route("/api/agents/<int:agent_id>/memory", methods=["GET"])
@login_required
def get_agent_memories(agent_id):
    """Get agent memories with pagination and filters"""
    try:
        # Pagination
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        offset = (page - 1) * per_page

        # Filters
        memory_type = request.args.get("memory_type")
        include_deleted = request.args.get("include_deleted", "false").lower() == "true"
        search = request.args.get("search")

        # Build query
        conditions = ["agent_id = %s"]
        params = [agent_id]

        if not include_deleted:
            conditions.append("is_deleted = FALSE")

        if memory_type:
            conditions.append("memory_type = %s")
            params.append(memory_type)

        if search:
            conditions.append("(content ILIKE %s OR memory_type ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = " AND ".join(conditions)

        with get_db_cursor(commit=False) as (conn, cur):
            # Get total count
            cur.execute(f"SELECT COUNT(*) FROM agent_memory WHERE {where_clause}", params)
            total = cur.fetchone()["count"]

            # Get memories
            cur.execute(
                f"""
                SELECT id, agent_id, memory_type, content, importance_score,
                       context, source_module, emotional_valence,
                       is_deleted, deleted_at, deleted_by, deletion_reason,
                       created_at, last_accessed, access_count,
                       decay_immunity, reinforcement_count
                FROM agent_memory
                WHERE {where_clause}
                ORDER BY importance_score DESC NULLS LAST, created_at DESC
                LIMIT %s OFFSET %s
            """,
                params + [per_page, offset],
            )

            memories = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": [dict(m) for m in memories],
                "count": len(memories),
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )
    except Exception as e:
        logger.error("get_agent_memories error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/memory", methods=["POST"])
@login_required
def create_agent_memory(agent_id):
    """Create new agent memory"""
    try:
        data = request.get_json()

        if not data.get("content"):
            return (
                jsonify({"success": False, "error": "content is required"}),
                400,
            )

        with get_db_cursor(commit=True) as (conn, cur):
            # Verify agent exists
            cur.execute("SELECT id FROM agents WHERE id = %s", (agent_id,))
            if not cur.fetchone():
                return jsonify({"success": False, "error": "Agent not found"}), 404

            cur.execute(
                """
                INSERT INTO agent_memory (agent_id, memory_type, content, importance_score, context, source_module)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, agent_id, memory_type, content, importance_score, context, source_module, created_at
            """,
                (
                    agent_id,
                    data.get("memory_type", "general"),
                    data["content"],
                    data.get("importance_score", 0.5),
                    json.dumps(data["context"]) if isinstance(data.get("context"), dict) else data.get("context"),
                    data.get("source_module"),
                ),
            )

            memory = cur.fetchone()

            # Log governance event
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, user_id, action, target_table, target_id, new_value, outcome)
                VALUES ('memory_created', 'data_management', %s, %s, 'create_memory', 'agent_memory', %s, %s, 'success')
            """,
                (
                    agent_id,
                    current_user.id,
                    memory["id"],
                    json.dumps(dict(memory), default=str),
                ),
            )

        return jsonify(
            {
                "success": True,
                "data": dict(memory),
                "message": "Memory created successfully",
            }
        )
    except Exception as e:
        logger.error("create_agent_memory error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["GET"])
@login_required
def get_agent_memory(agent_id, memory_id):
    """Get specific agent memory"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT * FROM agent_memory
                WHERE id = %s AND agent_id = %s
            """,
                (memory_id, agent_id),
            )

            memory = cur.fetchone()

        if not memory:
            return jsonify({"success": False, "error": "Memory not found"}), 404

        return jsonify({"success": True, "data": dict(memory)})
    except Exception as e:
        logger.error("get_agent_memory error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["PUT"])
@login_required
def update_agent_memory(agent_id, memory_id):
    """Update agent memory"""
    try:
        data = request.get_json()

        with get_db_cursor(commit=True) as (conn, cur):
            # Get old value for audit
            cur.execute(
                "SELECT * FROM agent_memory WHERE id = %s AND agent_id = %s",
                (memory_id, agent_id),
            )
            old_memory = cur.fetchone()

            if not old_memory:
                return jsonify({"success": False, "error": "Memory not found"}), 404

            # Build update
            updates = []
            params = []

            if "content" in data:
                updates.append("content = %s")
                params.append(data["content"])

            if "importance_score" in data:
                updates.append("importance_score = %s")
                params.append(data["importance_score"])

            if "context" in data:
                updates.append("context = %s")
                params.append(json.dumps(data["context"]) if isinstance(data["context"], dict) else data["context"])

            if "memory_type" in data:
                updates.append("memory_type = %s")
                params.append(data["memory_type"])

            if "emotional_valence" in data:
                updates.append("emotional_valence = %s")
                params.append(data["emotional_valence"])

            if "source_module" in data:
                updates.append("source_module = %s")
                params.append(data["source_module"])

            if not updates:
                return jsonify({"success": False, "error": "No fields to update"}), 400

            updates.append("last_accessed = NOW()")
            params.extend([memory_id, agent_id])

            cur.execute(
                f"""
                UPDATE agent_memory SET {', '.join(updates)}
                WHERE id = %s AND agent_id = %s
                RETURNING *
            """,
                params,
            )

            updated = cur.fetchone()

            # Log governance event
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, user_id,
                 action, target_table, target_id, old_value,
                 new_value, outcome)
                VALUES ('memory_updated', 'data_management', %s, %s, 'update_memory', 'agent_memory', %s, %s, %s, 'success')
            """,
                (
                    agent_id,
                    current_user.id,
                    memory_id,
                    json.dumps(dict(old_memory), default=str),
                    json.dumps(dict(updated), default=str),
                ),
            )

        return jsonify(
            {
                "success": True,
                "data": dict(updated),
                "message": "Memory updated successfully",
            }
        )
    except Exception as e:
        logger.error("update_agent_memory error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>", methods=["DELETE"])
@login_required
def delete_agent_memory(agent_id, memory_id):
    """Soft delete agent memory using database function"""
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "Manual deletion by admin")

        with get_db_cursor(commit=True) as (conn, cur):
            # Use the database soft_delete function
            try:
                cur.execute(
                    "SELECT soft_delete_agent_memory(%s, %s, %s) as deleted",
                    (memory_id, current_user.id, reason),
                )
                result = cur.fetchone()

                if not result or not result["deleted"]:
                    return (
                        jsonify({"success": False, "error": "Memory not found or already deleted"}),
                        404,
                    )
            except Exception:
                # Fallback: manual soft delete if DB function doesn't exist
                cur.execute(
                    """
                    UPDATE agent_memory
                    SET is_deleted = TRUE, deleted_at = NOW(), deleted_by = %s, deletion_reason = %s
                    WHERE id = %s AND agent_id = %s AND is_deleted = FALSE
                    RETURNING id
                """,
                    (current_user.id, reason, memory_id, agent_id),
                )
                deleted = cur.fetchone()
                if not deleted:
                    return (
                        jsonify({"success": False, "error": "Memory not found or already deleted"}),
                        404,
                    )

        return jsonify({"success": True, "message": "Memory soft-deleted successfully"})
    except Exception as e:
        logger.error("delete_agent_memory error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bridge_bp.route("/api/agents/<int:agent_id>/memory/<int:memory_id>/restore", methods=["POST"])
@login_required
def restore_agent_memory(agent_id, memory_id):
    """Restore soft-deleted agent memory"""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE agent_memory
                SET is_deleted = FALSE, deleted_at = NULL, deleted_by = NULL, deletion_reason = NULL
                WHERE id = %s AND agent_id = %s AND is_deleted = TRUE
                RETURNING *
            """,
                (memory_id, agent_id),
            )

            restored = cur.fetchone()

            if not restored:
                return (
                    jsonify({"success": False, "error": "Memory not found or not deleted"}),
                    404,
                )

            # Log governance event
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, user_id, action, target_table, target_id, outcome)
                VALUES ('memory_restored', 'data_management', %s, %s, 'restore_memory', 'agent_memory', %s, 'success')
            """,
                (agent_id, current_user.id, memory_id),
            )

        return jsonify(
            {
                "success": True,
                "data": dict(restored),
                "message": "Memory restored successfully",
            }
        )
    except Exception as e:
        logger.error("restore_agent_memory error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# --- Agent Performance ---


@bridge_bp.route("/api/agents/<int:agent_id>/performance", methods=["GET"])
@login_required
def get_agent_performance_data(agent_id):
    """Get performance metrics for an agent."""
    if not _HAS_PERFORMANCE_TRACKER:
        return jsonify({"success": False, "error": "Performance tracker not available"}), 501
    performance = get_agent_performance(agent_id)
    if performance is None:
        return jsonify({"success": False, "error": "No performance data"}), 404
    return jsonify({"success": True, "performance": performance})


@bridge_bp.route("/api/agents/<int:agent_id>/performance/update", methods=["POST"])
@login_required
def update_agent_performance_metrics(agent_id):
    """Recalculate performance metrics for an agent."""
    if not _HAS_PERFORMANCE_TRACKER:
        return jsonify({"success": False, "error": "Performance tracker not available"}), 501
    success = update_agent_performance(agent_id)
    return jsonify({"success": success, "message": f"Performance metrics updated for agent #{agent_id}"})


@bridge_bp.route("/api/agents/performance/leaderboard", methods=["GET"])
@login_required
def get_performance_leaderboard():
    """Get top performing agents."""
    if not _HAS_PERFORMANCE_TRACKER:
        return jsonify({"success": False, "error": "Performance tracker not available"}), 501
    limit = request.args.get("limit", 10, type=int)
    leaderboard = get_top_performers(limit=limit)
    return jsonify({"success": True, "leaderboard": leaderboard})


@bridge_bp.route("/api/agents/<int:agent_id>/work-history", methods=["GET"])
@login_required
def get_agent_work_history(agent_id):
    """Get work history: proposals, discussions, stats."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Improvement proposals
            cur.execute(
                """
                SELECT id, title, status, category, priority,
                       proposed_at, deployed_at, test_status, escalation_status
                FROM improvement_proposals
                WHERE assigned_agent_id = %s OR contractor_agent_id = %s
                ORDER BY proposed_at DESC LIMIT 20
            """,
                (agent_id, agent_id),
            )
            proposals = [dict(r) for r in cur.fetchall()]

            # Discussions
            cur.execute(
                """
                SELECT DISTINCT d.id, d.topic, d.status, d.created_at,
                       (SELECT COUNT(*) FROM agent_discussion_messages
                        WHERE discussion_id = d.id AND agent_id = %s) as message_count
                FROM agent_discussions d
                JOIN agent_discussion_messages m ON d.id = m.discussion_id
                WHERE m.agent_id = %s
                ORDER BY d.created_at DESC LIMIT 10
            """,
                (agent_id, agent_id),
            )
            discussions = [dict(r) for r in cur.fetchall()]

            # Performance stats
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE assigned_agent_id = %s) as proposals_assigned,
                    COUNT(*) FILTER (WHERE assigned_agent_id = %s AND status = 'deployed') as proposals_deployed,
                    COUNT(*) FILTER (WHERE contractor_agent_id = %s) as contractor_consultations,
                    COUNT(*) FILTER (WHERE contractor_agent_id = %s AND status = 'deployed') as contractor_successes
                FROM improvement_proposals
            """,
                (agent_id, agent_id, agent_id, agent_id),
            )
            row = cur.fetchone()
            stats = dict(row) if row else {}

            # Serialize datetimes for JSON
            for p in proposals:
                for k in ("proposed_at", "deployed_at"):
                    if p.get(k) and hasattr(p[k], "isoformat"):
                        p[k] = p[k].isoformat()
            for d in discussions:
                if d.get("created_at") and hasattr(d["created_at"], "isoformat"):
                    d["created_at"] = d["created_at"].isoformat()

            return jsonify(
                {
                    "success": True,
                    "proposals": proposals,
                    "discussions": discussions,
                    "stats": stats,
                }
            )
    except Exception as e:
        logger.error(f"Error getting work history for agent {agent_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SKILL GAP / AGENT CREATION ENDPOINTS
# ============================================================================


@bridge_bp.route("/api/dispatch/agent-gaps")
@login_required
def get_agent_gaps():
    """List recent agent creation requests (skill gaps)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, action_data, status, reason, created_at,
                       approved_at, rejected_reason
                FROM autonomy_approval_queue
                WHERE action_type = 'create_agent'
                ORDER BY created_at DESC
                LIMIT 20
            """
            )
            gaps = [dict(r) for r in cur.fetchall()]
            for g in gaps:
                ad = g.get("action_data") or {}
                if isinstance(ad, str):
                    try:
                        ad = json.loads(ad)
                    except Exception:
                        ad = {}
                g["capability"] = ad.get("capability", "unknown")
                g["station"] = ad.get("station_code", "unknown")
                g["suggested_name"] = ad.get("suggested_name", "")
                if g.get("created_at") and hasattr(g["created_at"], "isoformat"):
                    g["created_at"] = g["created_at"].isoformat()
                if g.get("approved_at") and hasattr(g["approved_at"], "isoformat"):
                    g["approved_at"] = g["approved_at"].isoformat()
                # Remove raw action_data from response
                g.pop("action_data", None)
            return jsonify({"gaps": gaps})
    except Exception as e:
        logger.error(f"Error getting agent gaps: {e}")
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/agents/create-from-gap", methods=["POST"])
@login_required
def create_agent_from_gap():
    """Manually approve and create an agent from a skill gap request."""
    if not current_user.is_admin:
        return jsonify({"error": "Admin only"}), 403
    data = request.get_json() or {}
    approval_id = data.get("approval_id")
    if not approval_id:
        return jsonify({"error": "approval_id required"}), 400
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                SELECT id, action_data, status FROM autonomy_approval_queue
                WHERE id = %s AND action_type = 'create_agent'
            """,
                (approval_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Request not found"}), 404
            row = dict(row)
            if row["status"] != "pending":
                return jsonify({"error": f"Request already {row['status']}"}), 400

            # Execute creation via dispatcher
            try:
                from ai_bridge.bridge_dispatcher import get_dispatcher

                dispatcher = get_dispatcher()
                ad = row["action_data"]
                if isinstance(ad, str):
                    ad = json.loads(ad)
                agent_id = dispatcher._create_agent_from_approval(ad)
            except Exception as disp_err:
                logger.error(f"Dispatcher creation failed: {disp_err}")
                return jsonify({"error": f"Creation failed: {disp_err}"}), 500

            if agent_id:
                cur.execute(
                    """
                    UPDATE autonomy_approval_queue
                    SET status = 'executed', approved_by = %s, approved_at = NOW(),
                        executed_at = NOW(),
                        execution_result = %s::jsonb
                    WHERE id = %s
                """,
                    (
                        current_user.id,
                        json.dumps({"agent_id": agent_id, "source": "manual"}),
                        approval_id,
                    ),
                )
                return jsonify({"success": True, "agent_id": agent_id})
            else:
                return jsonify({"error": "Agent creation returned None"}), 500
    except Exception as e:
        logger.error(f"Error creating agent from gap: {e}")
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/dispatch/multi-agent-sessions")
@login_required
def multi_agent_sessions():
    """Paginated list of multi-agent orchestration sessions."""
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    offset = (page - 1) * per_page
    try:
        with get_db_cursor(commit=False) as (conn, cur):
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
        with get_db_cursor(commit=False) as (conn, cur):
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
            return jsonify({"session": session, "steps": steps})
    except Exception as e:
        logger.error("multi_agent_session_detail error: %s", e)
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/dispatch/fleet-metrics")
@login_required
def fleet_metrics():
    """Aggregate fleet metrics for Mission Control."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Active vs total agents
            cur.execute(
                "SELECT COUNT(*) AS total," " COUNT(*) FILTER (WHERE status = 'active') AS active" " FROM agents"
            )
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
            ps_models = _get_cached_ollama_ps()
            if ps_models:
                gpu_model = ps_models[0].get("name", "unknown")
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
# CROSS-STATION DISPATCH ANALYTICS
# ============================================================================


@bridge_bp.route("/api/dispatch/cross-station-analytics")
@login_required
def cross_station_analytics():
    """Cross-station dispatch analytics for ARCHIE/Vigil evaluation."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY cross_station_dispatch_summary")
            cur.execute("SELECT * FROM cross_station_dispatch_summary ORDER BY dispatch_count DESC")
            cross_dispatches = cur.fetchall()
            cur.execute("SELECT * FROM station_borrowing_summary")
            borrowing = cur.fetchall()
        return jsonify(success=True, cross_dispatches=cross_dispatches, borrowing=borrowing)
    except Exception as e:
        logger.error(f"cross_station_analytics error: {e}")
        return jsonify(success=False, error=str(e)), 500


@bridge_bp.route("/api/dispatch/reassignment-recommendations")
@login_required
def reassignment_recommendations():
    """Suggest agent reassignments based on cross-station dispatch patterns."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT home_station, dispatch_station, capability, module_source,
                       dispatch_count, success_rate
                FROM cross_station_dispatch_summary
                WHERE dispatch_count >= 5
                ORDER BY dispatch_count DESC LIMIT 20
            """
            )
            frequent = cur.fetchall()

            recommendations = []
            for row in frequent:
                cur.execute(
                    """
                    SELECT a.id, a.name, a.display_name, ask.skill_name,
                           ask.proficiency_level, sa.assignment_type
                    FROM agents a
                    JOIN agent_skills ask ON ask.agent_id = a.id
                    LEFT JOIN station_assignments sa
                        ON sa.agent_id = a.id AND sa.is_active = true
                    LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
                    WHERE ask.skill_name ILIKE %s
                      AND (bs.station_code IS NULL OR bs.station_code != %s)
                    ORDER BY ask.proficiency_level DESC LIMIT 3
                """,
                    (f"%{row['capability']}%", row["home_station"]),
                )
                candidates = cur.fetchall()
                if candidates:
                    recommendations.append(
                        {
                            "pattern": dict(row),
                            "candidates": [dict(c) for c in candidates],
                        }
                    )
        return jsonify(success=True, recommendations=recommendations)
    except Exception as e:
        logger.error(f"reassignment_recommendations error: {e}")
        return jsonify(success=False, error=str(e)), 500


# ============================================================================
# MESH CLUSTER API ROUTES
# ============================================================================
try:
    from tools.bridge.mesh_routes import register_mesh_routes

    register_mesh_routes(bridge_bp)
except ImportError as e:
    logger.warning(f"Mesh routes not loaded: {e}")
