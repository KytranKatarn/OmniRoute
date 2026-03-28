"""
Department HQ — Overview + Org Chart routes

Endpoints:
  GET /                — Render the single-page template
  GET /api/overview    — Floor summary with department counts, agent counts, health
  GET /api/org-chart   — Floors -> departments -> AI Director + staff list
"""

from functools import wraps
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor

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
            with get_db_cursor(commit=False) as (conn, cur):
                # Agents per department with shift breakdown
                cur.execute(
                    """
                    SELECT department, floor,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE shift_state = 'active') AS active,
                           COUNT(*) FILTER (WHERE shift_state = 'deployed') AS deployed,
                           COUNT(*) FILTER (WHERE shift_state = 'barracked') AS barracked,
                           COUNT(*) FILTER (WHERE is_department_ai = true) AS directors
                    FROM agents
                    WHERE department IS NOT NULL
                    GROUP BY department, floor
                    ORDER BY floor, department
                """
                )
                dept_rows = cur.fetchall()

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
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, name, display_name, department, floor,
                           is_department_ai, shift_state, model, status
                    FROM agents
                    WHERE department IS NOT NULL
                    ORDER BY floor, department, is_department_ai DESC, display_name
                """
                )
                agents = cur.fetchall()

            # Organize into hierarchy
            floors = {}
            for agent in agents:
                fl = agent["floor"] or "UNKNOWN"
                dept = agent["department"]

                if fl not in floors:
                    floors[fl] = {"floor": fl, "departments": {}}
                if dept not in floors[fl]["departments"]:
                    floors[fl]["departments"][dept] = {
                        "department": dept,
                        "director": None,
                        "staff": [],
                    }

                agent_data = {
                    "id": agent["id"],
                    "name": agent["name"],
                    "display_name": agent["display_name"],
                    "shift_state": agent["shift_state"],
                    "model": agent["model"],
                    "status": agent["status"],
                    "is_director": agent["is_department_ai"],
                }

                if agent["is_department_ai"]:
                    floors[fl]["departments"][dept]["director"] = agent_data
                else:
                    floors[fl]["departments"][dept]["staff"].append(agent_data)

            # Convert dept dicts to lists for JSON
            result = {}
            for fl_name, fl_data in floors.items():
                result[fl_name] = {
                    "floor": fl_name,
                    "departments": list(fl_data["departments"].values()),
                }

            return jsonify({"floors": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
