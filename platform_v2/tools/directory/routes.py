"""
A.R.C.H.I.E. EMPLOYEE DIRECTORY Routes
=======================================
Public business directory with org chart and employee profiles.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-20
"""

import json
import logging
from flask import Blueprint, render_template, jsonify, request, session, make_response
from flask_login import login_required
from database import get_db_cursor

from .helpers import derive_full_name, derive_email, map_agent_status

logger = logging.getLogger(__name__)

bp = Blueprint(
    "directory_bp",
    __name__,
    template_folder="templates",
    url_prefix="",
)


ALLOWED_ORIGINS = [
    "https://www.kytranempowerment.com",
    "https://kytranempowerment.com",
    "https://archie.kytranempowerment.com",
    "http://localhost",
]


@bp.before_request
def handle_preflight():
    """Handle CORS preflight (OPTIONS) for Private Network Access."""
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            resp = make_response("", 204)
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Allow-Private-Network"] = "true"
            resp.headers["Access-Control-Max-Age"] = "3600"
            return resp


@bp.after_request
def add_cors_headers(response):
    """Allow cross-origin requests from the public www site."""
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# ============================================================================
# PAGE ROUTES
# ============================================================================


@bp.route("/directory")
def directory_public():
    """Public business directory — Human + AI employees."""
    authenticated = "user_id" in session
    if authenticated:
        return render_template("directory.html", authenticated=True)
    return render_template("directory_public.html", authenticated=False)


@bp.route("/tools/directory")
@login_required
def directory_authenticated():
    """Authenticated business directory view."""
    return render_template("directory.html", authenticated=True)


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
        agent_type = request.args.get("agent_type", "all")

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

        if agent_type == "ai":
            where_clauses.append("is_department_ai = true")
        elif agent_type == "human":
            where_clauses.append("(is_department_ai = false OR is_department_ai IS NULL)")

        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT id, name, first_name, last_name,
                       COALESCE(first_name || ' ' || last_name, name) as full_name,
                       email, phone, title, department, pronouns, bio,
                       avatar_url, tier, is_department_ai,
                       CASE WHEN worker_type IN ('internal','contract')
                            THEN 'AI' ELSE 'Human' END as employee_type,
                       worker_type, capabilities
                    FROM agents WHERE {' AND '.join(where_clauses)}
                    ORDER BY department, first_name""",
                params,
            )
            members = cur.fetchall()

        # Check if request is from an authenticated session
        authenticated = "user_id" in session

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
            # Strip internal-only fields from public responses
            if not authenticated:
                md.pop("employee_type", None)
                md.pop("worker_type", None)
            dept = md["department"] or "General"
            by_department.setdefault(dept, []).append(md)

        ai_count = sum(1 for m in members if dict(m).get("is_department_ai"))
        human_count = len(members) - ai_count
        stats = {
            "total_members": len(members),
            "total_departments": len(by_department),
            "ai_count": ai_count,
            "human_count": human_count,
        }

        return jsonify(
            {
                "success": True,
                "members": [dict(m) for m in members],
                "by_department": by_department,
                "departments": sorted(by_department.keys()),
                "statistics": stats,
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
                      avatar_url, performance_score, reports_to_agent_id,
                      is_department_ai,
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

            # Fetch all skills
            cur.execute(
                """SELECT skill_name, skill_category, proficiency_level
                   FROM agent_skills
                   WHERE agent_id = %s
                   ORDER BY proficiency_level DESC""",
                (employee_id,),
            )
            ed["skills"] = [dict(row) for row in cur.fetchall()]

            # Fetch manager info if reports_to_agent_id is set
            manager_id = ed.pop("reports_to_agent_id", None)
            if manager_id:
                cur.execute(
                    """SELECT id,
                          COALESCE(first_name || ' ' || last_name, display_name, name) as full_name
                       FROM agents WHERE id = %s""",
                    (manager_id,),
                )
                mgr = cur.fetchone()
                ed["reports_to"] = dict(mgr) if mgr else None
            else:
                ed["reports_to"] = None

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

        # Strip internal-only fields from public responses
        if "user_id" not in session:
            ed.pop("employee_type", None)

        return jsonify({"success": True, "employee": ed})
    except Exception as e:
        logger.error("Directory employee API error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/directory/live-status")
def api_directory_live_status():
    """Public live-status endpoint — lightweight agent availability from Bridge roster.

    Returns per-agent: status label, online flag, mood, department.
    No internal details (model, hardware, jobs, stats) are exposed.
    """
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))

    try:
        from bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        manifest = dispatcher.get_crew_manifest()
    except Exception as e:
        logger.error("Live status — Bridge unavailable: %s", e)
        manifest = []

    agents = {}
    online_count = 0
    for member in manifest:
        agent_id = member.get("agent_id") or member.get("id")
        if not agent_id:
            continue
        mapped = map_agent_status(member)
        if mapped["is_online"]:
            online_count += 1
        agents[str(agent_id)] = {
            "status": mapped["status"],
            "is_online": mapped["is_online"],
            "chat_available": mapped["chat_available"],
            "mood": member.get("wellness", {}).get("mood", "neutral"),
            "department": member.get("title", ""),
        }

    return jsonify(
        {
            "success": True,
            "agents": agents,
            "summary": {
                "total": len(agents),
                "online": online_count,
            },
        }
    )


@bp.route("/api/directory/org-chart")
def api_directory_org_chart():
    """Return org hierarchy grouped by corporate department with skill ratings."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT a.id, a.name, a.first_name, a.last_name,
                      a.display_name, a.title, a.department,
                      a.avatar_url, a.reports_to_agent_id, a.is_department_ai,
                      CASE WHEN a.worker_type IN ('internal','contract')
                           THEN 'AI' ELSE 'Human' END as employee_type,
                      a.worker_type,
                      (SELECT json_agg(json_build_object(
                                'skill', s.skill_name,
                                'level', s.proficiency_level))
                       FROM (SELECT skill_name, proficiency_level
                             FROM agent_skills
                             WHERE agent_id = a.id
                             ORDER BY proficiency_level DESC
                             LIMIT 3) s
                      ) as top_skills
                   FROM agents a
                   WHERE a.status = 'active'
                   ORDER BY a.department, a.first_name"""
            )
            agents = cur.fetchall()

            # Determine which agents have direct reports
            cur.execute(
                """SELECT DISTINCT reports_to_agent_id
                   FROM agents
                   WHERE reports_to_agent_id IS NOT NULL AND status = 'active'"""
            )
            manager_ids = {row["reports_to_agent_id"] for row in cur.fetchall()}

        authenticated = "user_id" in session
        nodes = []
        for agent in agents:
            ad = dict(agent)
            ad["name"] = derive_full_name(ad)
            ad["email"] = derive_email(ad)
            ad["reports_to"] = ad.pop("reports_to_agent_id", None)
            ad["is_head"] = ad["id"] in manager_ids
            ad["top_skills"] = ad["top_skills"] or []
            if not authenticated:
                ad.pop("employee_type", None)
                ad.pop("worker_type", None)
            nodes.append(ad)

        return jsonify({"success": True, "nodes": nodes})
    except Exception as e:
        logger.error("Org chart API error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
