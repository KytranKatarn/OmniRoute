"""
Department HQ — Overview + Org Chart routes

Endpoints:
  GET /                — Render the single-page template
  GET /api/overview    — Floor summary with department counts, agent counts, health
  GET /api/org-chart   — Floors -> departments -> AI Director + staff list

Uses the centralized agent_service for agent data; keeps minimal SQL
only for non-agent tables (dept_work_sessions, bridge_jobs).
"""

from functools import wraps
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
from services.agent_service import get_department_summary, get_org_chart

# ---------------------------------------------------------------------------
# Admin guard (same pattern as consciousness module)
# ---------------------------------------------------------------------------


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated


def register_routes(bp, _admin_required=None):
    """Register overview and org-chart routes on the blueprint."""
    guard = _admin_required or admin_required

    # ------------------------------------------------------------------
    # Page render
    # ------------------------------------------------------------------
    @bp.route("/")
    @guard
    def index():
        return render_template("department_hq.html")

    # ------------------------------------------------------------------
    # Overview API
    # ------------------------------------------------------------------
    @bp.route("/api/overview")
    @guard
    def api_overview():
        """Floor summary: department counts, agent counts, active sessions, health."""
        try:
            # Agent counts per department from centralized service
            dept_rows = get_department_summary()

            # Supplementary data that lives outside agents table — keep minimal SQL
            with get_db_cursor(commit=False) as (conn, cur):
                # Active work sessions per department
                cur.execute(
                    """
                    SELECT department, COUNT(*) AS active_sessions
                    FROM dept_work_sessions
                    WHERE status = 'active'
                    GROUP BY department
                """
                )
                session_rows = cur.fetchall()
                session_map = {r["department"]: r["active_sessions"] for r in session_rows}

                # Recent bridge jobs (last 24h) per department via agent lookup
                cur.execute(
                    """
                    SELECT a.department,
                           COUNT(*) AS jobs_24h,
                           COUNT(*) FILTER (WHERE bj.status = 'completed') AS completed_24h,
                           COUNT(*) FILTER (WHERE bj.status = 'failed') AS failed_24h
                    FROM bridge_jobs bj
                    JOIN agents a ON a.name = bj.agent_name
                    WHERE bj.created_at >= NOW() - INTERVAL '24 hours'
                      AND a.department IS NOT NULL
                    GROUP BY a.department
                """
                )
                job_rows = cur.fetchall()
                job_map = {r["department"]: dict(r) for r in job_rows}

            # Build floor summary
            floors = {}
            for row in dept_rows:
                fl = row["floor"] or "UNKNOWN"
                if fl not in floors:
                    floors[fl] = {
                        "floor": fl,
                        "departments": [],
                        "total_agents": 0,
                        "active_agents": 0,
                    }
                dept_name = row["department"]
                dept_info = {
                    "department": dept_name,
                    "total_agents": row["total"],
                    "active": row["active"],
                    "deployed": row["deployed"],
                    "barracked": row["barracked"],
                    "directors": row["directors"],
                    "active_sessions": session_map.get(dept_name, 0),
                    "jobs_24h": job_map.get(dept_name, {}).get("jobs_24h", 0),
                    "completed_24h": job_map.get(dept_name, {}).get("completed_24h", 0),
                    "failed_24h": job_map.get(dept_name, {}).get("failed_24h", 0),
                }
                floors[fl]["departments"].append(dept_info)
                floors[fl]["total_agents"] += row["total"]
                floors[fl]["active_agents"] += row["active"]

            # Overall totals
            total_agents = sum(f["total_agents"] for f in floors.values())
            active_agents = sum(f["active_agents"] for f in floors.values())
            total_departments = sum(len(f["departments"]) for f in floors.values())

            return jsonify(
                {
                    "floors": floors,
                    "totals": {
                        "agents": total_agents,
                        "active": active_agents,
                        "departments": total_departments,
                        "floors": len(floors),
                    },
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # Org Chart API
    # ------------------------------------------------------------------
    @bp.route("/api/org-chart")
    @guard
    def api_org_chart():
        """Hierarchical org chart: floors -> departments -> director + staff."""
        try:
            org = get_org_chart()

            # Transform service output into the JSON shape the frontend expects:
            # { floors: { FLOOR: { floor, departments: [{ department, director, staff }] } } }
            result = {}
            for fl_name, departments in org.items():
                dept_list = []
                for dept_name, dept_data in departments.items():
                    director = dept_data.get("director")
                    staff = dept_data.get("staff", [])

                    # Normalize agent dicts to the fields the frontend uses
                    def _agent_view(a):
                        return {
                            "id": a["id"],
                            "name": a["name"],
                            "display_name": a["display_name"],
                            "shift_state": a["shift_state"],
                            "model": a["model"],
                            "status": a["status"],
                            "is_director": a.get("is_department_ai", False),
                        }

                    dept_list.append(
                        {
                            "department": dept_name,
                            "director": _agent_view(director) if director else None,
                            "staff": [_agent_view(s) for s in staff],
                        }
                    )

                result[fl_name] = {
                    "floor": fl_name,
                    "departments": dept_list,
                }

            return jsonify({"floors": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
