"""
Business Module - Public Routes
================================
Public-facing business directory and company pages.
No authentication required for viewing.
"""

from flask import Blueprint, render_template, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
import json

business_bp = Blueprint("business", __name__, url_prefix="/business")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


@business_bp.route("/directory")
def directory():
    """Public business directory - Human + AI employees"""
    return render_template("business/directory.html")


@business_bp.route("/api/directory")
def api_directory():
    """API endpoint for public business directory"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        search = request.args.get("search", "")
        department = request.args.get("department", "")
        employee_type = request.args.get("type", "")  # 'ai', 'human', or 'all'

        # Build query with filters
        where_clauses = ["status = 'active'", "visibility IN ('public', 'dashboard')"]
        params = []

        if search:
            where_clauses.append(
                """(
                first_name ILIKE %s OR
                last_name ILIKE %s OR
                title ILIKE %s OR
                department ILIKE %s
            )"""
            )
            search_pattern = f"%{search}%"
            params.extend([search_pattern] * 4)

        if department and department != "all":
            where_clauses.append("department = %s")
            params.append(department)

        if employee_type == "ai":
            where_clauses.append("worker_type IN ('internal', 'contract')")
        elif employee_type == "human":
            where_clauses.append("worker_type = 'human'")

        where_clause = " AND ".join(where_clauses)

        cur.execute(
            f"""
            SELECT
                id, name, first_name, last_name,
                COALESCE(first_name || ' ' || last_name, name) as full_name,
                email, phone, title, department, pronouns, bio,
                avatar_url, tier,
                CASE
                    WHEN worker_type IN ('internal', 'contract') THEN 'AI'
                    ELSE 'Human'
                END as employee_type,
                worker_type,
                capabilities
            FROM agents
            WHERE {where_clause}
            ORDER BY department, first_name
        """,
            params,
        )

        members = cur.fetchall()

        # Organize by department
        by_department = {}
        departments = set()

        for member in members:
            member_dict = dict(member)

            # Parse capabilities for specialties
            if member_dict.get("capabilities"):
                try:
                    if isinstance(member_dict["capabilities"], str):
                        caps = json.loads(member_dict["capabilities"])
                    else:
                        caps = member_dict["capabilities"]
                    member_dict["specialties"] = caps.get("specialties", [])[:5]
                except Exception:
                    member_dict["specialties"] = []
            else:
                member_dict["specialties"] = []

            # Remove capabilities from public response
            del member_dict["capabilities"]

            dept = member_dict["department"] or "General"
            departments.add(dept)

            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(member_dict)

        cur.close()
        conn.close()

        # Count by type
        ai_count = len([m for m in members if dict(m).get("employee_type") == "AI"])
        human_count = len([m for m in members if dict(m).get("employee_type") == "Human"])

        return jsonify(
            {
                "success": True,
                "members": [dict(m) for m in members],
                "by_department": by_department,
                "departments": sorted(list(departments)),
                "statistics": {
                    "total_members": len(members),
                    "total_departments": len(departments),
                    "ai_count": ai_count,
                    "human_count": human_count,
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@business_bp.route("/api/directory/<int:employee_id>")
def get_employee(employee_id):
    """Get public details for a specific employee"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id, name, first_name, last_name,
                COALESCE(first_name || ' ' || last_name, name) as full_name,
                email, title, department, pronouns, bio,
                avatar_url,
                CASE
                    WHEN worker_type IN ('internal', 'contract') THEN 'AI'
                    ELSE 'Human'
                END as employee_type,
                capabilities
            FROM agents
            WHERE id = %s AND status = 'active'
            AND visibility IN ('public', 'dashboard')
        """,
            (employee_id,),
        )

        employee = cur.fetchone()
        cur.close()
        conn.close()

        if not employee:
            return jsonify({"success": False, "error": "Employee not found"}), 404

        employee_dict = dict(employee)

        # Parse capabilities for specialties
        if employee_dict.get("capabilities"):
            try:
                if isinstance(employee_dict["capabilities"], str):
                    caps = json.loads(employee_dict["capabilities"])
                else:
                    caps = employee_dict["capabilities"]
                employee_dict["specialties"] = caps.get("specialties", [])
                employee_dict["tools"] = caps.get("tools", [])
            except Exception:
                employee_dict["specialties"] = []
                employee_dict["tools"] = []

        # Remove internal capabilities field
        del employee_dict["capabilities"]

        return jsonify({"success": True, "employee": employee_dict})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
