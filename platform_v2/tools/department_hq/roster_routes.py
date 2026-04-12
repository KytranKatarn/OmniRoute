"""
Department HQ — Roster routes

Endpoints:
  GET  /api/roster        — All agents with filters (?department=, ?floor=, ?shift_state=, ?search=)
  POST /api/roster/assign — Reassign agent to department {agent_id, department}
  POST /api/roster/shift  — Change shift state {agent_id, shift_state}

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

VALID_DEPARTMENTS = set(DEPARTMENT_FLOOR_MAP.keys())


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

            # Apply offset pagination on the result
            total = len(all_agents)
            agents = all_agents[offset : offset + limit]

            # Trim to the fields the original endpoint returned
            trimmed = []
            for a in agents:
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
                        "acronym_expansion": a.get("acronym_expansion"),
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
