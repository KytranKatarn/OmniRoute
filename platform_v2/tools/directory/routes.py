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
from services.agent_service import list_agents_public, get_agent, get_skills

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
    "https://api.kytranempowerment.com",
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
        search = request.args.get("search", "") or None
        department = request.args.get("department", "") or None
        employee_type = request.args.get("type", "") or None
        agent_type = request.args.get("agent_type", "all")

        is_dept_ai = None
        if agent_type == "ai":
            is_dept_ai = True
        elif agent_type == "human":
            is_dept_ai = False

        members = list_agents_public(
            department=department,
            search=search,
            is_department_ai=is_dept_ai,
            agent_type=employee_type,
        )

        authenticated = "user_id" in session

        by_department = {}
        for md in members:
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
            md.pop("capabilities", None)
            if not authenticated:
                md.pop("employee_type", None)
                md.pop("worker_type", None)
            dept = md.get("department") or "General"
            by_department.setdefault(dept, []).append(md)

        ai_count = sum(1 for m in members if m.get("is_department_ai"))
        human_count = len(members) - ai_count

        return jsonify(
            {
                "success": True,
                "members": members,
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
        agent = get_agent(employee_id)
        if not agent or agent.get("status") != "active":
            return jsonify({"success": False, "error": "Employee not found"}), 404

        ed = {
            "id": agent["id"],
            "name": agent.get("name"),
            "first_name": agent.get("first_name"),
            "last_name": agent.get("last_name"),
            "full_name": derive_full_name(agent),
            "email": derive_email(agent),
            "phone": agent.get("phone"),
            "title": agent.get("title"),
            "department": agent.get("department"),
            "pronouns": agent.get("pronouns"),
            "bio": agent.get("bio"),
            "avatar_url": agent.get("avatar_url"),
            "performance_score": agent.get("performance_score"),
            "is_department_ai": agent.get("is_department_ai"),
        }

        # Employee type
        worker_type = agent.get("worker_type", "")
        if worker_type in ("internal", "contract"):
            ed["employee_type"] = "AI"
        else:
            ed["employee_type"] = "Human"

        # Skills via agent_service
        ed["skills"] = get_skills(employee_id)

        # Manager lookup
        manager_id = agent.get("reports_to_agent_id")
        if manager_id:
            mgr = get_agent(manager_id)
            ed["reports_to"] = {"id": mgr["id"], "full_name": derive_full_name(mgr)} if mgr else None
        else:
            ed["reports_to"] = None

        # Parse capabilities for specialties/tools
        caps = agent.get("capabilities")
        if caps:
            try:
                caps = caps if isinstance(caps, dict) else json.loads(caps)
                ed["specialties"] = caps.get("specialties", [])
                ed["tools"] = caps.get("tools", [])
            except Exception:
                ed["specialties"] = []
                ed["tools"] = []
        else:
            ed["specialties"] = []
            ed["tools"] = []

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
    try:
        from tools.department_hq.services.bridge_dispatcher import get_dispatcher

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
