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

logger = logging.getLogger(__name__)


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
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/agents", methods=["POST"])
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
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/agents/<int:agent_id>", methods=["PUT", "PATCH"])
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

                    # Fleet-wide unique model constraint (skip if model unchanged)
                    if new_model != old_model:
                        is_unique, conflict = check_fleet_model_unique(cur, new_model, exclude_agent_id=agent_id)
                        if not is_unique:
                            return jsonify({"success": False, "error": conflict}), 409

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
                    _ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
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

    @bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
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
                except Exception:
                    pass

                return jsonify({"success": True, "status": result[0]})
        except Exception as e:
            logger.error("toggle_agent error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/agents/<int:agent_id>/assign-station", methods=["POST"])
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

                # Block: agent must be active (not paused, resting, etc.)
                cur.execute(
                    "SELECT name, status FROM agents WHERE id = %s",
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
                                    f"— only active agents can be assigned to stations"
                                ),
                            }
                        ),
                        400,
                    )

                # Block: cannot reassign fixed agents (ARCHIE, Vigil at COMMAND)
                cur.execute(
                    "SELECT bs.station_code FROM station_assignments sa "
                    "JOIN bridge_stations bs ON bs.id = sa.station_id "
                    "WHERE sa.agent_id = %s AND sa.is_fixed = TRUE AND sa.is_active = TRUE",
                    (agent_id,),
                )
                fixed_row = cur.fetchone()
                if fixed_row:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Agent has a fixed assignment at {fixed_row['station_code']} and cannot be moved",
                            }
                        ),
                        400,
                    )

                # Enforce station capacity limits
                cur.execute(
                    "SELECT max_primary, max_auxiliary FROM bridge_stations WHERE id = %s",
                    (station_id,),
                )
                limits = cur.fetchone()
                if limits and assignment_type == "primary":
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM station_assignments "
                        "WHERE station_id = %s AND assignment_type = 'primary' "
                        "AND is_active = TRUE AND agent_id != %s",
                        (station_id, agent_id),
                    )
                    if cur.fetchone()["cnt"] >= limits["max_primary"]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Station at max primary capacity ({limits['max_primary']})",
                                }
                            ),
                            400,
                        )
                elif limits and assignment_type in ("auxiliary", "backup", "relief"):
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM station_assignments "
                        "WHERE station_id = %s AND assignment_type IN ('auxiliary', 'backup', 'relief') "
                        "AND is_active = TRUE AND agent_id != %s",
                        (station_id, agent_id),
                    )
                    if cur.fetchone()["cnt"] >= limits["max_auxiliary"]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Station at max auxiliary capacity ({limits['max_auxiliary']})",
                                }
                            ),
                            400,
                        )

                # 1-station rule: deactivate agent's existing assignment elsewhere
                cur.execute(
                    "UPDATE station_assignments SET is_active = FALSE "
                    "WHERE agent_id = %s AND is_active = TRUE AND is_fixed = FALSE "
                    "AND station_id != %s",
                    (agent_id, station_id),
                )

                # Check if assignment already exists at this station
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

    @bp.route("/api/agents/<int:agent_id>/unassign-station", methods=["POST"])
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

    @bp.route("/api/stations/assignments")
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

    @bp.route("/api/stations/<station_code>/config", methods=["GET"])
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

    @bp.route("/api/stations/<station_code>/config", methods=["PUT"])
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

    @bp.route("/api/stations/reorder", methods=["POST"])
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

    @bp.route("/api/assignments/<int:assignment_id>", methods=["DELETE"])
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

    @bp.route("/api/assignments/<int:assignment_id>", methods=["PUT"])
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

    @bp.route("/api/stations/<station_code>/request-support", methods=["POST"])
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

                # Step 2: Enforce 3-slot model (assigned crew + 1 Auxiliary)
                # Rule: All assigned crew must exist before auxiliary is allowed
                cur.execute(
                    "SELECT max_primary, max_auxiliary FROM bridge_stations WHERE id = %s",
                    (station["id"],),
                )
                limits = cur.fetchone()
                max_aux = limits["max_auxiliary"] if limits else 1

                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM station_assignments
                    WHERE station_id = %s AND assignment_type = 'primary' AND is_active = TRUE
                """,
                    (station["id"],),
                )
                assigned_count = cur.fetchone()["cnt"]
                if assigned_count == 0:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": (
                                    "Station has no crew assigned. "
                                    "At least one agent must be assigned before auxiliary support."
                                ),
                                "slot_status": "primary_incomplete",
                            }
                        ),
                        400,
                    )

                # Count ALL auxiliary-type assignments (auxiliary + additional_support)
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM station_assignments
                    WHERE station_id = %s
                    AND assignment_type IN ('auxiliary', 'additional_support', 'backup', 'relief')
                    AND is_active = TRUE
                """,
                    (station["id"],),
                )
                current_aux = cur.fetchone()["cnt"]

                # Also count running cross-station jobs targeting this station
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM bridge_jobs
                    WHERE status = 'running'
                    AND metadata->>'is_cross_station' = 'true'
                    AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                    AND (
                        metadata->>'module_station' = %s
                        OR metadata->>'dispatch_station' = %s
                    )
                """,
                    (station_code.upper(), station_code.upper()),
                )
                cross_station_aux = cur.fetchone()["cnt"]
                total_aux = current_aux + cross_station_aux

                if total_aux >= max_aux:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": f"Station at max auxiliary capacity ({total_aux}/{max_aux})",
                                "slot_status": "aux_full",
                            }
                        ),
                        400,
                    )

                # Step 2b: Check if additional_support slot is already filled
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

                # Step 4: Check workload compliance (station assignments + active jobs)
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

                # Check active bridge_jobs to prevent agent overloading
                cur.execute(
                    """
                    SELECT COUNT(*) as active_jobs
                    FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'in_progress'
                """,
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

    @bp.route("/api/stations/<station_code>/release-support", methods=["POST"])
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
            return jsonify({"error": str(e)}), 500

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
            return jsonify({"error": str(e)}), 500

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
