"""Starbase Command — Agent routes (CRUD, skills, station assign/unassign, support)"""

import json
import os
import logging
from datetime import datetime
from typing import List
from flask import jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor, check_fleet_model_unique
import requests

from .helpers import OLLAMA_LOCAL_URL, _get_cached_ollama_ps

logger = logging.getLogger(__name__)

# Maps legacy station codes to department names for backward-compatible panel rendering.
# station_assignments table is DROPPED; agents.department is the source of truth.
LEGACY_STATION_DEPARTMENT = {
    "COMMAND": ["Executive Office"],
    "ANALYTICS": ["Analytics & Intelligence", "Finance & Accounting"],
    "CREATIVE": ["Creative & Design", "Marketing & Communications", "Documentation & Knowledge"],
    "ENGINEERING": ["Engineering & Technology", "Security & Compliance", "Research & Development"],
    "COMMUNICATIONS": ["Marketing & Communications"],
    "RESEARCH": ["Research & Development"],
    "SECURITY": ["Security & Compliance"],
    "LOGISTICS": ["Logistics & Supply Chain"],
    "DIPLOMATIC": ["Diplomatic & External Relations"],
    "OPERATIONS": ["Operations & Infrastructure"],
}

# Reverse map: department name -> legacy station code
DEPARTMENT_TO_STATION = {}
for _code, _depts in LEGACY_STATION_DEPARTMENT.items():
    for _dept in _depts:
        if _dept not in DEPARTMENT_TO_STATION:
            DEPARTMENT_TO_STATION[_dept] = _code

# Legacy station colors for backward-compatible rendering
LEGACY_STATION_COLORS = {
    "COMMAND": "#00e5ff",
    "ANALYTICS": "#8b5cf6",
    "CREATIVE": "#f472b6",
    "ENGINEERING": "#fbbf24",
    "COMMUNICATIONS": "#22d3ee",
    "RESEARCH": "#10b981",
    "SECURITY": "#ef4444",
    "LOGISTICS": "#f97316",
    "DIPLOMATIC": "#818cf8",
    "OPERATIONS": "#a3e635",
}


def register_agent_routes(bp, admin_required):
    """Register agent-related routes on the bridge blueprint."""

    # ============================================================================
    # AGENTS API (for station assignment)
    # ============================================================================

    @bp.route("/api/agents")
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents", methods=["POST"])
    @login_required
    @admin_required
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

        # Validate temperature and max_tokens
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "temperature must be a number"}), 400
        if not (0 <= temperature <= 2):
            return jsonify({"success": False, "error": "temperature must be between 0 and 2"}), 400

        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "max_tokens must be an integer"}), 400
        if not (100 <= max_tokens <= 32000):
            return jsonify({"success": False, "error": "max_tokens must be between 100 and 32000"}), 400

        capabilities = data.get("capabilities")
        if isinstance(capabilities, list):
            capabilities = json.dumps(capabilities)
        name = f"{first_name} {last_name}".strip()

        try:
            with get_db_cursor() as (conn, cur):
                # Fleet-wide unique model constraint
                is_unique, conflict = check_fleet_model_unique(cur, model)
                if not is_unique:
                    return jsonify({"success": False, "error": conflict}), 409

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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>", methods=["PUT", "PATCH"])
    @login_required
    @admin_required
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

        # Validate temperature and max_tokens if provided
        if "temperature" in data:
            try:
                t = float(data["temperature"])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "temperature must be a number"}), 400
            if not (0 <= t <= 2):
                return jsonify({"success": False, "error": "temperature must be between 0 and 2"}), 400

        if "max_tokens" in data:
            try:
                mt = int(data["max_tokens"])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "max_tokens must be an integer"}), 400
            if not (100 <= mt <= 32000):
                return jsonify({"success": False, "error": "max_tokens must be between 100 and 32000"}), 400

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

                    # Fleet-wide unique model constraint (skip if model unchanged)
                    if new_model != old_model:
                        is_unique, conflict = check_fleet_model_unique(cur, new_model, exclude_agent_id=agent_id)
                        if not is_unique:
                            return jsonify({"success": False, "error": conflict}), 409

                cur.execute(
                    "UPDATE agents SET "
                    + ", ".join(sets)
                    + " WHERE id = %s RETURNING id, name, first_name, last_name, model, status",
                    params,
                )
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"success": False, "error": "Agent not found"}), 404

                # Invalidate caches
                try:
                    from ai_bridge.bridge_dispatcher import get_dispatcher

                    get_dispatcher()._cache_time = 0
                except Exception as e:
                    logger.warning("Failed to invalidate dispatcher cache: %s", e)
                _profile_cache.pop(agent_id, None)

                # Model transition: auto-load new model, auto-unload orphaned old model
                model_ops = []
                if new_model and old_model and new_model != old_model:
                    ollama_url = OLLAMA_LOCAL_URL

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
                        except Exception as e:
                            logger.warning("Failed to unload model %s: %s", old_model, e)
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
                    except Exception as e:
                        logger.warning("Failed to load model %s: %s", new_model, e)
                        model_ops.append(f"failed to load {new_model}")

                result = {"success": True, "agent": dict(agent)}
                if model_ops:
                    result["model_ops"] = model_ops
                return jsonify(result)
        except Exception as e:
            logger.error("update_agent error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
    @login_required
    @admin_required
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
                except Exception as e:
                    logger.warning("Failed to invalidate dispatcher cache after delete: %s", e)

                return jsonify({"success": True, "message": f"Agent '{agent['name']}' deleted"})
        except Exception as e:
            logger.error("delete_agent error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/toggle", methods=["POST"])
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
                except Exception as e:
                    logger.warning("Failed to invalidate dispatcher cache after toggle: %s", e)

                return jsonify({"success": True, "status": result[0]})
        except Exception as e:
            logger.error("toggle_agent error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/skills", methods=["GET"])
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/skills", methods=["POST"])
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/skills/<skill_id>", methods=["DELETE"])
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/assign-station", methods=["POST"])
    @login_required
    def assign_agent_to_station(agent_id):
        """Assign an agent to a department (legacy station_code maps to department)."""
        data = request.get_json() or {}
        station_code = data.get("station_code")
        department = data.get("department")

        # Accept either department name directly or legacy station_code
        if not department and station_code:
            depts = LEGACY_STATION_DEPARTMENT.get(station_code.upper(), [])
            department = depts[0] if depts else None
        if not department:
            return jsonify({"success": False, "error": "department or station_code required"}), 400

        try:
            with get_db_cursor() as (conn, cur):
                # Block: agent must be active
                cur.execute(
                    "SELECT name, status, department as current_dept FROM agents WHERE id = %s",
                    (agent_id,),
                )
                agent_row = cur.fetchone()
                if not agent_row:
                    return jsonify({"success": False, "error": "Agent not found"}), 404
                if agent_row["status"] != "active":
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": (
                                    f"{agent_row['name']} is {agent_row['status']} "
                                    f"— only active agents can be reassigned"
                                ),
                            }
                        ),
                        400,
                    )

                # Block: cannot reassign fixed agents (ARCHIE at Executive Office, VIGIL at Security)
                fixed_agents = {"A.R.C.H.I.E.", "V.I.G.I.L."}
                if agent_row["name"] in fixed_agents:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Agent has a fixed department assignment ({agent_row['current_dept']}) and cannot be moved",
                            }
                        ),
                        400,
                    )

                # Update agents.department directly
                cur.execute(
                    "UPDATE agents SET department = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                    (department, agent_id),
                )
                updated = cur.fetchone()
                legacy_code = DEPARTMENT_TO_STATION.get(department, "UNKNOWN")

                return jsonify(
                    {
                        "success": True,
                        "agent_id": updated["id"],
                        "message": f"Agent assigned to {department} (station {legacy_code})",
                    }
                )

        except Exception as e:
            logger.error(f"Error assigning agent: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/unassign-station", methods=["POST"])
    @login_required
    def unassign_agent_from_station(agent_id):
        """Unassign agent — sets department to 'Unassigned' (legacy station_assignments removed)."""
        data = request.get_json() or {}
        station_code = data.get("station_code")  # accepted for backward compat but ignored

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "UPDATE agents SET department = 'Unassigned', updated_at = NOW() WHERE id = %s RETURNING id",
                    (agent_id,),
                )
                updated = cur.fetchone()
                if not updated:
                    return jsonify({"success": False, "error": "Agent not found"}), 404

                return jsonify(
                    {
                        "success": True,
                        "message": f'Agent unassigned from {station_code if station_code else "department"}',
                        "affected": 1,
                    }
                )

        except Exception as e:
            logger.error(f"Error unassigning agent: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # STATION ASSIGNMENTS API (Phase 28)
    # ============================================================================

    @bp.route("/api/stations/assignments")
    @login_required
    def get_all_station_assignments():
        """Get all department assignments grouped by legacy station code.

        station_assignments table is DROPPED. This now queries agents.department
        and maps back to legacy station codes for backward-compatible panel rendering.
        """
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT a.id, a.name, a.first_name, a.last_name, a.title,
                           a.avatar_url, a.model, a.status, a.department, a.floor,
                           a.tier
                    FROM agents a
                    WHERE a.status IN ('active', 'idle', 'busy', 'deployed')
                    ORDER BY a.department, a.name
                    """
                )
                all_agents = cur.fetchall()

                # Build station groupings from LEGACY_STATION_DEPARTMENT
                stations = []
                for code, depts in LEGACY_STATION_DEPARTMENT.items():
                    dept_agents = [a for a in all_agents if a["department"] in depts]
                    agent_list = [
                        {
                            "agent_id": a["id"],
                            "agent_name": a["name"],
                            "first_name": a["first_name"],
                            "last_name": a["last_name"],
                            "agent_title": a["title"],
                            "agent_avatar": a["avatar_url"],
                            "agent_model": a["model"],
                            "agent_status": a["status"],
                            "assignment_type": "primary",
                            "role_type": "standard",
                            "is_fixed": False,
                            "department": a["department"],
                            "shift_preference": "any",
                            "priority": 10,
                            "assigned_at": None,
                        }
                        for a in dept_agents
                    ] or None
                    stations.append(
                        {
                            "station_code": code,
                            "station_name": code.title(),
                            "color": LEGACY_STATION_COLORS.get(code, "#888"),
                            "icon": None,
                            "agents": agent_list,
                        }
                    )

                return jsonify({"success": True, "stations": stations})

        except Exception as e:
            logger.error(f"Error getting assignments: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/unassigned-agents")
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
                      AND (a.department IS NULL OR a.department = 'Unassigned')
                    ORDER BY a.name
                """
                )
                agents = cur.fetchall()

                return jsonify({"success": True, "agents": agents, "count": len(agents)})

        except Exception as e:
            logger.error(f"Error getting unassigned agents: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<station_code>/config", methods=["GET"])
    @login_required
    def get_station_config(station_code):
        """Get station configuration (department-based, legacy station code accepted)."""
        code = station_code.upper()
        depts = LEGACY_STATION_DEPARTMENT.get(code)
        if not depts:
            return jsonify({"success": False, "error": "Station not found"}), 404

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Count agents in mapped departments
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM agents WHERE department = ANY(%s) AND status IN ('active','idle','busy')",
                    (depts,),
                )
                cnt = cur.fetchone()["cnt"]

                station = {
                    "station_code": code,
                    "station_name": code.title(),
                    "full_name": code.title(),
                    "description": f"Departments: {', '.join(depts)}",
                    "color": LEGACY_STATION_COLORS.get(code, "#888"),
                    "icon": None,
                    "departments": depts,
                    "agent_count": cnt,
                    "is_active": True,
                }
                return jsonify({"success": True, "station": station})

        except Exception as e:
            logger.error(f"Error getting station config: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<station_code>/config", methods=["PUT"])
    @login_required
    @admin_required
    def update_station_config(station_code):
        """Update station configuration — DEPRECATED.

        bridge_stations is deprecated. Station config is now derived from
        agents.department. This endpoint is a no-op stub for backward compat.
        """
        return jsonify(
            {
                "success": True,
                "station": {"station_code": station_code.upper()},
                "message": f"Station {station_code} config is now department-based (no-op)",
            }
        )

    @bp.route("/api/stations/reorder", methods=["POST"])
    @login_required
    def reorder_stations():
        """Reorder stations — DEPRECATED (station order is now fixed by department layout)."""
        return jsonify({"success": True, "message": "Station reorder is deprecated (department-based layout)"})

    @bp.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
    @login_required
    def delete_assignment(assignment_id):
        """Delete a station assignment — DEPRECATED (station_assignments table dropped).

        Now interprets assignment_id as agent_id and sets department to Unassigned.
        """
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "UPDATE agents SET department = 'Unassigned', updated_at = NOW() WHERE id = %s RETURNING id",
                    (assignment_id,),
                )
                deleted = cur.fetchone()
                if not deleted:
                    return jsonify({"success": False, "error": "Agent not found"}), 404
                return jsonify({"success": True, "message": "Agent unassigned from department"})

        except Exception as e:
            logger.error(f"Error deleting assignment: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
    @login_required
    def update_assignment(assignment_id):
        """Update a station assignment — DEPRECATED (station_assignments table dropped).

        Now interprets assignment_id as agent_id. Only department update is supported.
        """
        data = request.get_json() or {}
        department = data.get("department")

        if not department:
            return jsonify({"success": False, "error": "department field required"}), 400

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "UPDATE agents SET department = %s, updated_at = NOW() WHERE id = %s RETURNING id, department",
                    (department, assignment_id),
                )
                updated = cur.fetchone()
                if not updated:
                    return jsonify({"success": False, "error": "Agent not found"}), 404
                return jsonify({"success": True, "assignment": dict(updated)})

        except Exception as e:
            logger.error(f"Error updating assignment: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # ADDITIONAL SUPPORT REQUEST API
    # ============================================================================

    @bp.route("/api/stations/<station_code>/request-support", methods=["POST"])
    @login_required
    def request_station_support(station_code):
        """
        Handle additional support requests from modules.

        Rewritten for department-based routing (station_assignments dropped).
        Finds an available agent outside the mapped departments for this station code.
        """
        data = request.get_json() or {}
        task_type = data.get("task_type", "general")
        capability_needed = data.get("capability_needed", "general capability")
        requesting_module = data.get("requesting_module", "unknown")

        code = station_code.upper()
        depts = LEGACY_STATION_DEPARTMENT.get(code)
        if not depts:
            return jsonify({"success": False, "message": f"Station {station_code} not found"}), 404

        logger.info(f"Bridge: Support request from {requesting_module} - {task_type} needs {capability_needed}")

        try:
            with get_db_cursor() as (conn, cur):

                # Step 1: Ensure station has at least one agent in mapped departments
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM agents WHERE department = ANY(%s) AND status = 'active'",
                    (depts,),
                )
                assigned_count = cur.fetchone()["cnt"]
                if assigned_count == 0:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": "Station has no crew assigned. At least one agent must be in department before auxiliary support.",
                                "slot_status": "primary_incomplete",
                            }
                        ),
                        400,
                    )

                # Step 2: Find a suitable agent outside the mapped departments
                capability_lower = capability_needed.lower() if capability_needed else ""
                target_models = []

                if "fast" in capability_lower or "speed" in capability_lower or "batch" in capability_lower:
                    target_models = ["qwen25-classify", "dolphin3-8k:latest"]
                elif "thorough" in capability_lower or "security" in capability_lower or "deep" in capability_lower:
                    target_models = []

                if target_models:
                    model_placeholders = ",".join(["%s"] * len(target_models))
                    cur.execute(
                        f"""
                        SELECT a.id, a.name, a.model, a.tier, a.title, a.avatar_url
                        FROM agents a
                        WHERE a.status = 'active'
                        AND a.model IN ({model_placeholders})
                        AND a.department != ALL(%s)
                        ORDER BY a.tier DESC
                        LIMIT 1
                    """,
                        (*target_models, depts),
                    )
                else:
                    cur.execute(
                        """
                        SELECT a.id, a.name, a.model, a.tier, a.title, a.avatar_url
                        FROM agents a
                        WHERE a.status = 'active'
                        AND a.tier >= 2
                        AND a.department != ALL(%s)
                        ORDER BY a.tier DESC
                        LIMIT 1
                    """,
                        (depts,),
                    )

                candidate = cur.fetchone()

                if not candidate:
                    return jsonify(
                        {
                            "success": False,
                            "message": f"No agent available with {capability_needed}",
                            "slot_status": "no_candidates",
                        }
                    )

                # Step 3: Check workload compliance (active jobs only — no station_assignments)
                cur.execute(
                    "SELECT COUNT(*) as active_jobs FROM bridge_jobs WHERE agent_name = %s AND status = 'in_progress'",
                    (candidate["name"],),
                )
                job_workload = cur.fetchone()

                if job_workload["active_jobs"] >= 3:
                    logger.info(f"Bridge: {candidate['name']} has too many active jobs ({job_workload['active_jobs']})")
                    return jsonify(
                        {
                            "success": False,
                            "message": f"{candidate['name']} has {job_workload['active_jobs']} active jobs (max 3)",
                            "slot_status": "workload_limit",
                        }
                    )

                logger.info(f"Bridge: Found support candidate {candidate['name']} for {code}")

                candidate_dict = dict(candidate)
                candidate_dict["assignment_type"] = "additional_support"

                return jsonify(
                    {
                        "success": True,
                        "agent": candidate_dict,
                        "message": f"{candidate['name']} available as additional support",
                        "slot_status": "assigned",
                    }
                )

        except Exception as e:
            logger.error(f"Bridge: Error processing support request: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<station_code>/release-support", methods=["POST"])
    @login_required
    def release_station_support(station_code):
        """Release support — DEPRECATED stub (station_assignments dropped).

        Support is now ephemeral (no persistent assignment row to delete).
        """
        code = station_code.upper()
        logger.info(f"Bridge: Release support called for {code} (no-op, department-based)")

        return jsonify(
            {
                "success": True,
                "released_count": 0,
                "message": "Support release is now implicit (department-based routing)",
            }
        )

    # ============================================================================
    # SKILL GAP / AGENT CREATION ENDPOINTS
    # ============================================================================

    @bp.route("/api/dispatch/agent-gaps")
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
                    g["station"] = ad.get("department", ad.get("station_code", "unknown"))
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
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/agents/create-from-gap", methods=["POST"])
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
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/dispatch/multi-agent-sessions")
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

    @bp.route("/api/dispatch/multi-agent-sessions/<session_id>")
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
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/dispatch/fleet-metrics")
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
