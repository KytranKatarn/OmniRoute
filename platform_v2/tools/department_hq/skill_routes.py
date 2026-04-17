"""
Department HQ — Skill routes

Endpoints:
  GET  /api/skills/list              — All active skills
  GET  /api/skills/<skill_name>      — Single skill detail
  POST /api/skills/<skill_name>/execute — Execute a skill via Bridge dispatch
  GET  /api/skills/departments       — Skills grouped by department
"""

from flask import jsonify, request as req
from database import get_db_cursor


def register_skill_routes(bp, admin_required):
    """Register skill API routes on the department_hq blueprint."""

    @bp.route("/api/skills/list")
    @admin_required
    def list_skills():
        """Return all active platform skills ordered by tier then name."""
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM platform_skills WHERE status = 'active' " "ORDER BY tier, skill_name")
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])

    @bp.route("/api/skills/<skill_name>")
    @admin_required
    def get_skill(skill_name):
        """Return a single skill by skill_name."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM platform_skills WHERE skill_name = %s",
                (skill_name,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404
            return jsonify(dict(row))

    @bp.route("/api/skills/<skill_name>/execute", methods=["POST"])
    @admin_required
    def execute_skill(skill_name):
        """Execute a skill: build prompt from template, dispatch via Bridge."""
        data = req.get_json(silent=True) or {}
        user_input = data.get("input", "")
        context = data.get("context", "")

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT * FROM platform_skills " "WHERE skill_name = %s AND status = 'active'",
                (skill_name,),
            )
            skill = cur.fetchone()
            if not skill:
                return jsonify({"error": f"Skill '{skill_name}' not found"}), 404

            # Increment usage counter
            cur.execute(
                "UPDATE platform_skills SET usage_count = usage_count + 1 " "WHERE id = %s",
                (skill["id"],),
            )

        # Build prompt from template
        prompt = skill["prompt_template"].replace("{input}", user_input).replace("{context}", context)

        # Dispatch via Bridge
        try:
            from .services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            result = dispatcher.request_work(
                capability=skill["capability"],
                prompt=prompt,
                module_id=f"skill_{skill_name}",
                system_prompt=skill.get("system_prompt") or None,
            )
            return jsonify(
                {
                    "success": bool(result and getattr(result, "response", "")),
                    "response": getattr(result, "response", "") if result else "",
                    "agent": getattr(result, "agent_name", "") if result else "",
                    "skill": skill_name,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e), "skill": skill_name}), 500

    @bp.route("/api/skills/departments")
    @admin_required
    def skills_by_department():
        """Return skills grouped by department with counts."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT department, "
                "array_agg(skill_name ORDER BY tier, skill_name) as skills, "
                "count(*) as count "
                "FROM platform_skills WHERE status = 'active' "
                "GROUP BY department ORDER BY department"
            )
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
