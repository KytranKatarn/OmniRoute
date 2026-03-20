"""
A.R.C.H.I.E. EMPLOYEE DIRECTORY Routes
=======================================
Public business directory with org chart and employee profiles.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-20
"""

import json
import logging
from flask import Blueprint, render_template, jsonify, request, session
from flask_login import login_required
from database import get_db_cursor

from .helpers import derive_full_name, derive_email

logger = logging.getLogger(__name__)

bp = Blueprint(
    "directory_bp",
    __name__,
    template_folder="templates",
    url_prefix="",
)


# ============================================================================
# PAGE ROUTES
# ============================================================================


@bp.route("/directory")
def directory_public():
    """Public business directory — Human + AI employees."""
    authenticated = "user_id" in session
    return render_template("business/directory.html", authenticated=authenticated)


@bp.route("/tools/directory")
@login_required
def directory_authenticated():
    """Authenticated business directory view."""
    return render_template("business/directory.html", authenticated=True)


# ============================================================================
# API ROUTES
# ============================================================================


@bp.route("/api/directory")
def api_directory():
    """API endpoint for public business directory."""
    try:
        search = request.args.get("search", "")
        department = request.args.get("department", "")
        employee_type = request.args.get("type", "")

        where_clauses = ["status = 'active'"]
        params = []

        if search:
            where_clauses.append(
                "(first_name ILIKE %s OR last_name ILIKE %s" " OR title ILIKE %s OR department ILIKE %s)"
            )
            params.extend([f"%{search}%"] * 4)

        if department and department != "all":
            where_clauses.append("department = %s")
            params.append(department)

        if employee_type == "ai":
            where_clauses.append("worker_type IN ('internal', 'contract')")
        elif employee_type == "human":
            where_clauses.append("worker_type = 'human'")

        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT id, name, first_name, last_name,
                       COALESCE(first_name || ' ' || last_name, name) as full_name,
                       email, phone, title, department, pronouns, bio,
                       avatar_url, tier,
                       CASE WHEN worker_type IN ('internal','contract')
                            THEN 'AI' ELSE 'Human' END as employee_type,
                       worker_type, capabilities
                    FROM agents WHERE {' AND '.join(where_clauses)}
                    ORDER BY department, first_name""",
                params,
            )
            members = cur.fetchall()

        by_department = {}
        for m in members:
            md = dict(m)
            if md.get("capabilities"):
                try:
                    caps = (
                        md["capabilities"] if isinstance(md["capabilities"], dict) else json.loads(md["capabilities"])
                    )
                    md["specialties"] = caps.get("specialties", [])[:5]
                except Exception:
                    md["specialties"] = []
            else:
                md["specialties"] = []
            del md["capabilities"]
            dept = md["department"] or "General"
            by_department.setdefault(dept, []).append(md)

        ai_count = sum(1 for m in members if dict(m).get("employee_type") == "AI")
        human_count = sum(1 for m in members if dict(m).get("employee_type") == "Human")

        return jsonify(
            {
                "success": True,
                "members": [dict(m) for m in members],
                "by_department": by_department,
                "departments": sorted(by_department.keys()),
                "statistics": {
                    "total_members": len(members),
                    "total_departments": len(by_department),
                    "ai_count": ai_count,
                    "human_count": human_count,
                },
            }
        )
    except Exception as e:
        logger.error("Directory API error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/directory/<int:employee_id>")
def api_directory_employee(employee_id):
    """Get public details for a specific employee."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, name, first_name, last_name,
                      COALESCE(first_name || ' ' || last_name, name) as full_name,
                      email, phone, title, department, pronouns, bio,
                      avatar_url,
                      CASE WHEN worker_type IN ('internal','contract')
                           THEN 'AI' ELSE 'Human' END as employee_type,
                      capabilities
                   FROM agents WHERE id = %s AND status = 'active'""",
                (employee_id,),
            )
            emp = cur.fetchone()

        if not emp:
            return jsonify({"success": False, "error": "Employee not found"}), 404

        ed = dict(emp)
        if ed.get("capabilities"):
            try:
                caps = ed["capabilities"] if isinstance(ed["capabilities"], dict) else json.loads(ed["capabilities"])
                ed["specialties"] = caps.get("specialties", [])
                ed["tools"] = caps.get("tools", [])
            except Exception:
                ed["specialties"] = []
                ed["tools"] = []
        else:
            ed["specialties"] = []
            ed["tools"] = []
        del ed["capabilities"]

        # Generate extension from ID
        ed["extension"] = f"x{1000 + ed['id']}"

        return jsonify({"success": True, "employee": ed})
    except Exception as e:
        logger.error("Directory employee API error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/directory/org-chart")
def api_directory_org_chart():
    """Return org hierarchy from agents table with station assignments."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT a.id, a.name, a.first_name, a.last_name,
                      a.display_name, a.title, a.department,
                      a.avatar_url, a.reports_to_agent_id,
                      CASE WHEN a.worker_type IN ('internal','contract')
                           THEN 'AI' ELSE 'Human' END as employee_type,
                      bs.station_code
                   FROM agents a
                   LEFT JOIN station_assignments sa
                        ON sa.agent_id = a.id AND sa.is_active = true
                   LEFT JOIN bridge_stations bs
                        ON bs.id = sa.station_id
                   WHERE a.status = 'active'
                   ORDER BY a.department, a.first_name"""
            )
            agents = cur.fetchall()

        nodes = []
        for agent in agents:
            ad = dict(agent)
            ad["full_name"] = derive_full_name(ad)
            ad["email"] = derive_email(ad)
            nodes.append(ad)

        return jsonify({"success": True, "nodes": nodes})
    except Exception as e:
        logger.error("Org chart API error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
