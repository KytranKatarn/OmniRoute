"""
Department HQ — Roster routes

Endpoints:
  GET  /api/roster        — All agents with filters (?department=, ?floor=, ?shift_state=, ?search=)
  POST /api/roster/assign — Reassign agent to department {agent_id, department}
  POST /api/roster/shift  — Change shift state {agent_id, shift_state}
"""

from flask import jsonify, request
from database import get_db_cursor

VALID_SHIFT_STATES = {"active", "deployed", "barracked", "off_duty", "winding_down", "cooldown"}

VALID_DEPARTMENTS = {
    "Executive Office",
    "Operations & Infrastructure",
    "Logistics & Supply Chain",
    "Finance & Accounting",
    "Engineering & Technology",
    "Security & Compliance",
    "Research & Development",
    "Creative & Design",
    "Marketing & Communications",
    "Documentation & Knowledge",
    "Customer Success & Support",
    "Human Resources & Culture",
    "Medical & Wellness",
    "Legal & Regulatory",
    "Diplomatic & External Relations",
    "Analytics & Intelligence",
}


def register_roster_routes(bp, admin_required):
    """Register roster management routes on the blueprint."""

    @bp.route("/api/roster")
    @admin_required
    def api_roster():
        """List agents with optional filters."""
        department = request.args.get("department")
        floor = request.args.get("floor")
        shift_state = request.args.get("shift_state")
        search = request.args.get("search", "").strip()
        limit = min(int(request.args.get("limit", 200)), 500)
        offset = int(request.args.get("offset", 0))

        try:
            conditions = ["department IS NOT NULL"]
            params = []

            if department:
                conditions.append("department = %s")
                params.append(department)
            if floor:
                conditions.append("floor = %s")
                params.append(floor)
            if shift_state:
                conditions.append("shift_state = %s")
                params.append(shift_state)
            if search:
                conditions.append("(LOWER(name) LIKE %s OR LOWER(display_name) LIKE %s OR LOWER(department) LIKE %s)")
                like = f"%{search.lower()}%"
                params.extend([like, like, like])

            where = " AND ".join(conditions)

            with get_db_cursor(commit=False) as (conn, cur):
                # Count total
                cur.execute(f"SELECT COUNT(*) AS cnt FROM agents WHERE {where}", params)
                total = cur.fetchone()["cnt"]

                # Fetch page
                cur.execute(
                    f"""
                    SELECT id, name, display_name, department, floor,
                           is_department_ai, shift_state, model, status
                    FROM agents
                    WHERE {where}
                    ORDER BY floor, department, is_department_ai DESC, display_name
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                agents = cur.fetchall()

            return jsonify(
                {
                    "agents": [dict(a) for a in agents],
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
            with get_db_cursor(commit=True) as (conn, cur):
                # Verify agent exists
                cur.execute("SELECT id, name, department FROM agents WHERE id = %s", [agent_id])
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"error": "Agent not found"}), 404

                # Look up the floor for the target department
                cur.execute(
                    "SELECT floor FROM agents WHERE department = %s LIMIT 1",
                    [department],
                )
                floor_row = cur.fetchone()
                floor = floor_row["floor"] if floor_row else None

                # Update
                cur.execute(
                    """
                    UPDATE agents
                    SET department = %s, floor = %s
                    WHERE id = %s
                    """,
                    [department, floor, agent_id],
                )

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} reassigned to {department}",
                }
            )
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
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("SELECT id, name, shift_state FROM agents WHERE id = %s", [agent_id])
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"error": "Agent not found"}), 404

                cur.execute(
                    "UPDATE agents SET shift_state = %s WHERE id = %s",
                    [shift_state, agent_id],
                )

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} shift changed to {shift_state}",
                    "previous": agent["shift_state"],
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500
