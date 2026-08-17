"""
Department HQ — Roster routes

Endpoints:
  GET  /api/roster         — All agents with filters (?department=, ?floor=, ?shift_state=, ?search=)
  POST /api/roster/assign  — Reassign agent to department {agent_id, department}
  POST /api/roster/shift   — Change shift state {agent_id, shift_state}

Public directory endpoints moved to /api/public/directory (public_api.py +
services/public_roster_service.py). Migration 332.

Uses the centralized agent_service for all agent operations.
"""

from flask import jsonify, request
from services.agent_service import (
    list_agents,
    get_agent,
    update_agent,
    DEPARTMENT_FLOOR_MAP,
    VALID_SHIFT_STATES,
)
from database import get_db_cursor

VALID_DEPARTMENTS = set(DEPARTMENT_FLOOR_MAP.keys())


def _compute_wellness(stress, mood):
    """Compute wellness badge color from stress_level and mood_intensity."""
    if stress is None and mood is None:
        return "green"
    s = float(stress) if stress is not None else 0.2
    m = float(mood) if mood is not None else 0.5
    if s >= 0.8 or m <= 0.1:
        return "red"
    if s >= 0.5 or m <= 0.3:
        return "yellow"
    return "green"


def _fetch_wellness_map():
    """Fetch latest emotional state per agent, return {agent_id: {wellness_status, stress_level}}."""
    wellness = {}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT ON (agent_id)
                    agent_id, stress_level, mood_intensity
                FROM agent_emotional_state
                ORDER BY agent_id, timestamp DESC
                """
            )
            for row in cur.fetchall():
                aid = row["agent_id"]
                stress = row["stress_level"]
                mood = row["mood_intensity"]
                wellness[aid] = {
                    "wellness_status": _compute_wellness(stress, mood),
                    "stress_level": float(stress) if stress is not None else 0.0,
                }
    except Exception:
        pass  # If table missing or query fails, all agents default to green
    return wellness


def register_roster_routes(bp, admin_required):
    """Register roster management routes on the blueprint."""

    @bp.route("/api/roster")
    @admin_required
    def api_roster():
        """List agents with optional filters."""
        department = request.args.get("department")
        floor = request.args.get("floor")
        shift_state = request.args.get("shift_state")
        search = request.args.get("search", "").strip() or None
        limit = min(int(request.args.get("limit", 200)), 500)
        offset = int(request.args.get("offset", 0))

        try:
            # Fetch all matching agents via service (service handles filtering)
            all_agents = list_agents(
                department=department,
                floor=floor,
                shift_state=shift_state,
                search=search,
                limit=limit + offset,  # fetch enough for offset pagination
            )

            # Exclude decommissioned agents from the roster listing — some carry
            # status='active' with shift_state='decommissioned' and leaked through
            # (#5706). An explicit ?shift_state=decommissioned filter still works.
            if shift_state != "decommissioned":
                all_agents = [a for a in all_agents if a.get("shift_state") != "decommissioned"]

            # True total via COUNT(*) with the SAME filters — len() of a
            # limit-capped fetch under-reports once the roster exceeds the cap.
            total = len(all_agents)
            try:
                count_conditions = ["a.status = %s"]
                count_params: list = ["active"]
                if department:
                    count_conditions.append("a.department = %s")
                    count_params.append(department)
                if floor:
                    count_conditions.append("a.floor = %s")
                    count_params.append(floor)
                if shift_state:
                    count_conditions.append("a.shift_state = %s")
                    count_params.append(shift_state)
                else:
                    count_conditions.append("a.shift_state != 'decommissioned'")
                if search:
                    count_conditions.append("(a.name ILIKE %s OR a.display_name ILIKE %s)")
                    count_params.extend([f"%{search}%", f"%{search}%"])
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT COUNT(*) AS total FROM agents a WHERE " + " AND ".join(count_conditions),
                        count_params,
                    )
                    row = cur.fetchone()
                    if row is not None:
                        total = row["total"]
            except Exception:
                pass  # fall back to the fetched-page count

            agents = all_agents[offset : offset + limit]

            # Fetch wellness data for all agents
            wellness_map = _fetch_wellness_map()

            # Trim to the fields the original endpoint returned
            trimmed = []
            for a in agents:
                w = wellness_map.get(a["id"], {})
                trimmed.append(
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "display_name": a["display_name"],
                        "department": a["department"],
                        "floor": a["floor"],
                        "is_department_ai": a["is_department_ai"],
                        "shift_state": a["shift_state"],
                        "model": a["model"],
                        "status": a["status"],
                        "title": a.get("title"),
                        "acronym": a.get("acronym"),
                        "acronym_expansion": a.get("acronym_expansion"),
                        "avatar_url": a.get("avatar_url"),
                        "avatar_updated_at": a.get("updated_at").isoformat() if a.get("updated_at") else None,
                        "bio": a.get("bio"),
                        "worker_type": a.get("worker_type"),
                        "wellness_status": w.get("wellness_status", "green"),
                        "stress_level": w.get("stress_level", 0.0),
                    }
                )

            # Add coordinator reservation status
            try:
                from services.department_coordinator import get_coordinator

                reserved = get_coordinator()._reserved_agents
                for agent in trimmed:
                    agent["is_reserved"] = agent.get("id") in reserved
            except Exception:
                pass

            return jsonify(
                {
                    "agents": trimmed,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/roster/assign", methods=["POST"])
    @admin_required
    def api_roster_assign():
        """Reassign an agent to a different department."""
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        department = data.get("department")

        if not agent_id or not department:
            return jsonify({"error": "agent_id and department are required"}), 400
        if department not in VALID_DEPARTMENTS:
            return jsonify({"error": f"Invalid department: {department}"}), 400

        try:
            # Verify agent exists
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            # update_agent auto-derives floor from department
            update_agent(agent_id, department=department)

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} reassigned to {department}",
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/roster/shift", methods=["POST"])
    @admin_required
    def api_roster_shift():
        """Change an agent's shift state."""
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        shift_state = data.get("shift_state")

        if not agent_id or not shift_state:
            return jsonify({"error": "agent_id and shift_state are required"}), 400
        if shift_state not in VALID_SHIFT_STATES:
            return jsonify({"error": f"Invalid shift_state: {shift_state}. Valid: {sorted(VALID_SHIFT_STATES)}"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            previous = agent["shift_state"]
            update_agent(agent_id, shift_state=shift_state)

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} shift changed to {shift_state}",
                    "previous": previous,
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/coordinator/status")
    @admin_required
    def api_coordinator_status():
        """Live coordinator status — reserved agents, loaded models, RAM."""
        from services.department_coordinator import get_coordinator

        coordinator = get_coordinator()
        status = coordinator.get_status()
        return jsonify({"success": True, **status})
