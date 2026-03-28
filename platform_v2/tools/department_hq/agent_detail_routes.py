"""
Department HQ — Agent Detail routes

Endpoints:
  GET  /api/agent/<id>/profile     — Full agent profile (agent + skills + welfare + performance)
  GET  /api/agent/<id>/skills      — Agent skills list
  POST /api/agent/<id>/skills      — Add/update a skill {skill_name, level, category}
  GET  /api/agent/<id>/welfare     — Agent welfare metrics
  POST /api/agent/<id>/shift       — Change shift state {shift_state}
  POST /api/agent/<id>/department  — Reassign department {department}

Uses the centralized agent_service for all operations.
"""

from flask import jsonify, request
from services.agent_service import (
    get_agent,
    get_skills,
    get_welfare,
    get_performance,
    update_agent,
    add_skill,
    DEPARTMENT_FLOOR_MAP,
    VALID_SHIFT_STATES,
)


def register_agent_detail_routes(bp, admin_required):
    """Register agent detail management routes on the blueprint."""

    @bp.route("/api/agent/<int:agent_id>/profile")
    @admin_required
    def api_agent_profile(agent_id):
        """Full agent profile: agent data + skills + welfare + performance."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            skills = get_skills(agent_id)
            welfare = get_welfare(agent_id)
            perf = get_performance(agent_id)

            # Sanitize agent dict for JSON (remove non-serializable fields)
            agent_data = {
                "id": agent["id"],
                "name": agent["name"],
                "display_name": agent["display_name"],
                "department": agent["department"],
                "floor": agent["floor"],
                "model": agent["model"],
                "status": agent["status"],
                "shift_state": agent["shift_state"],
                "is_department_ai": agent.get("is_department_ai", False),
                "temperature": float(agent.get("temperature") or 0.7),
                "max_tokens": agent.get("max_tokens", 2048),
                "system_prompt": agent.get("system_prompt", ""),
                "title": agent.get("title", ""),
                "avatar_url": agent.get("avatar_url", ""),
                "capabilities": agent.get("capabilities"),
                "stress_level": float(agent.get("stress_level") or 0),
                "energy_level": float(agent.get("energy_level") or 0.5),
                "current_mood": agent.get("current_mood", "neutral"),
                "mood_intensity": float(agent.get("mood_intensity") or 0.5),
            }

            # Welfare as separate object (may differ from agent join data)
            welfare_data = None
            if welfare:
                welfare_data = {
                    "stress_level": float(welfare.get("stress_level") or 0),
                    "energy_level": float(welfare.get("energy_level") or 0.5),
                    "current_mood": welfare.get("current_mood", "neutral"),
                    "mood_intensity": float(welfare.get("mood_intensity") or 0.5),
                }

            return jsonify(
                {
                    "agent": agent_data,
                    "skills": skills,
                    "welfare": welfare_data,
                    "performance": perf,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/skills")
    @admin_required
    def api_agent_skills(agent_id):
        """Get agent's skills."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            skills = get_skills(agent_id)
            return jsonify({"agent_id": agent_id, "skills": skills})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/skills", methods=["POST"])
    @admin_required
    def api_agent_add_skill(agent_id):
        """Add or update a skill for an agent."""
        data = request.get_json(silent=True) or {}
        skill_name = data.get("skill_name", "").strip()
        level = data.get("level", 1)
        category = data.get("category", "general")

        if not skill_name:
            return jsonify({"error": "skill_name is required"}), 400
        if not isinstance(level, int) or level < 1 or level > 5:
            return jsonify({"error": "level must be 1-5"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            add_skill(agent_id, skill_name, level=level, category=category)
            return jsonify(
                {
                    "success": True,
                    "message": f"Skill '{skill_name}' set to level {level}",
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/welfare")
    @admin_required
    def api_agent_welfare(agent_id):
        """Get agent's welfare metrics."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            welfare = get_welfare(agent_id)
            return jsonify({"agent_id": agent_id, "welfare": welfare})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/shift", methods=["POST"])
    @admin_required
    def api_agent_shift(agent_id):
        """Change agent shift state."""
        data = request.get_json(silent=True) or {}
        shift_state = data.get("shift_state")

        if not shift_state:
            return jsonify({"error": "shift_state is required"}), 400
        if shift_state not in VALID_SHIFT_STATES:
            return (
                jsonify({"error": f"Invalid shift_state: {shift_state}. Valid: {sorted(VALID_SHIFT_STATES)}"}),
                400,
            )

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

    @bp.route("/api/agent/<int:agent_id>/department", methods=["POST"])
    @admin_required
    def api_agent_department(agent_id):
        """Reassign agent to a different department."""
        data = request.get_json(silent=True) or {}
        department = data.get("department")

        if not department:
            return jsonify({"error": "department is required"}), 400
        if department not in DEPARTMENT_FLOOR_MAP:
            return jsonify({"error": f"Invalid department: {department}"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            previous = agent["department"]
            update_agent(agent_id, department=department)
            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} moved to {department}",
                    "previous": previous,
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
