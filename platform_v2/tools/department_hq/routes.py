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
from flask_login import current_user
from database import get_db_cursor
from services.agent_service import get_department_summary, get_org_chart

# ---------------------------------------------------------------------------
# Admin guard (same pattern as consciousness module)
# ---------------------------------------------------------------------------


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Return 401 JSON for unauthenticated API requests — never redirect,
        # so fetch() doesn't silently follow a 302 to the login HTML page.
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
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
    # Overview Stats API (Executive Bridge command center)
    # ------------------------------------------------------------------
    @bp.route("/api/overview-stats")
    @guard
    def api_overview_stats():
        """Aggregated command center stats for Overview redesign."""
        result = {}

        # Hero stats
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                # Agents by shift state — exclude decommissioned (82 retired rows
                # were inflating the Overview "Agents" total to 156 vs ~74 live).
                cur.execute(
                    "SELECT shift_state, COUNT(*) FROM agents "
                    "WHERE shift_state != 'decommissioned' GROUP BY shift_state"
                )
                shifts = {r[0]: r[1] for r in cur.fetchall()}
                result["agents"] = {
                    "total": sum(shifts.values()),
                    "active": shifts.get("active", 0),
                    "barracked": shifts.get("barracked", 0),
                    "winding_down": shifts.get("winding_down", 0),
                }

                # Bridge jobs 24h
                # Unified dispatch health (task_execution_log + bridge_jobs) via
                # the shared helper — was bridge_jobs-only with rate=completed/total
                # (incl. in-flight), so it read ~53% while the DHQ panel read ~100%.
                # Now identical to the DHQ DISPATCH METRICS + Consciousness numbers.
                from services.dispatch_health_service import dispatch_health

                _dh = dispatch_health(24)
                result["jobs_24h"] = {
                    "total": _dh["total"],
                    "completed": _dh["success"],
                    "failed": _dh["failed"],
                    "pending": _dh["pending"],
                    "success_rate": _dh["success_rate"],
                }

                # Knowledge base
                cur.execute("SELECT COUNT(*) FROM knowledge_base")
                kb_total = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL")
                kb_embedded = cur.fetchone()[0]
                result["knowledge"] = {
                    "total": kb_total,
                    "embedded": kb_embedded,
                    "coverage": round(kb_embedded / kb_total * 100, 1) if kb_total > 0 else 0,
                }

                # Code scan findings
                cur.execute("SELECT COUNT(*), SUM(issues_found), SUM(security_issues) FROM code_scans")
                row = cur.fetchone()
                result["scans"] = {
                    "total_scans": row[0] or 0,
                    "total_issues": int(row[1] or 0),
                    "security_issues": int(row[2] or 0),
                }

                # Ollama models loaded
                try:
                    import requests as req

                    ollama = req.get("http://host.docker.internal:11434/api/ps", timeout=3)
                    if ollama.ok:
                        models = ollama.json().get("models", [])
                        result["ollama"] = {"models_loaded": len(models)}
                    else:
                        result["ollama"] = {"models_loaded": "?"}
                except Exception:
                    result["ollama"] = {"models_loaded": "?"}

                # QA active suites
                cur.execute("SELECT COUNT(*) FROM qa_test_suites WHERE is_active = true")
                result["qa"] = {"active_suites": cur.fetchone()[0]}

        except Exception as exc:
            result["error"] = str(exc)[:200]

        # Attention items — each probe is isolated in its own try/except with a
        # rollback so one failed query cannot abort the shared transaction and
        # blank the remaining probes (#5706).
        attention = []
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                # High-stress agents (stress > 0.7). The welfare source of truth
                # is agent_emotional_state (SINGULAR) — agents has NO stress_level
                # column; the old probe errored and blanked the whole panel.
                try:
                    cur.execute(
                        """
                        SELECT a.display_name, a.name, ae.stress_level, a.department
                        FROM agents a
                        JOIN LATERAL (
                            SELECT stress_level
                            FROM agent_emotional_state
                            WHERE agent_id = a.id
                            ORDER BY timestamp DESC
                            LIMIT 1
                        ) ae ON TRUE
                        WHERE a.shift_state = 'active' AND ae.stress_level > 0.7
                        ORDER BY ae.stress_level DESC LIMIT 5
                    """
                    )
                    for r in cur.fetchall():
                        attention.append(
                            {
                                "level": "warn",
                                "text": f"{r[0] or r[1]} — Stress: {int(r[2]*100)}%",
                                "link_tab": "roster",
                                "category": "welfare",
                            }
                        )
                except Exception:
                    conn.rollback()

                # Failed agent loop jobs (last 24h)
                try:
                    cur.execute(
                        """
                        SELECT job_name, COUNT(*) as fails
                        FROM autonomy_loop_log
                        WHERE status IN ('error', 'failed') AND created_at > NOW() - INTERVAL '24 hours'
                        GROUP BY job_name
                        HAVING COUNT(*) >= 3
                        ORDER BY fails DESC LIMIT 5
                    """
                    )
                    for r in cur.fetchall():
                        attention.append(
                            {
                                "level": "error",
                                "text": f"Job '{r[0]}' failed {r[1]}x in 24h",
                                "link_tab": "dispatch",
                                "category": "jobs",
                            }
                        )
                except Exception:
                    conn.rollback()

                # Failed QA runs — QA lives in Repair Bay, not a DHQ tab
                try:
                    cur.execute(
                        """
                        SELECT s.name, r.passed, r.failed
                        FROM qa_test_runs r JOIN qa_test_suites s ON s.id = r.suite_id
                        WHERE r.status = 'failed' AND r.started_at > NOW() - INTERVAL '24 hours'
                        ORDER BY r.started_at DESC LIMIT 3
                    """
                    )
                    for r in cur.fetchall():
                        attention.append(
                            {
                                "level": "warn",
                                "text": f"QA '{r[0]}' — {r[1]} pass, {r[2]} fail",
                                "link_url": "/tools/repair-bay",
                                "link_label": "Repair Bay",
                                "category": "qa",
                            }
                        )
                except Exception:
                    conn.rollback()

                # Security issues from scans — surfaced in Repair Bay Diagnose
                try:
                    cur.execute("SELECT SUM(security_issues) FROM code_scans WHERE security_issues > 0")
                    sec = cur.fetchone()[0]
                    if sec and sec > 0:
                        attention.append(
                            {
                                "level": "warn" if sec < 50 else "error",
                                "text": f"{int(sec)} security issues across code scans",
                                "link_url": "/tools/repair-bay",
                                "link_label": "Repair Bay",
                                "category": "security",
                            }
                        )
                except Exception:
                    conn.rollback()
        except Exception:
            pass

        result["attention"] = sorted(attention, key=lambda x: {"error": 0, "warn": 1, "info": 2}.get(x.get("level"), 3))

        # Department summary (condensed by floor)
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    """
                    SELECT floor, COUNT(*) as agents,
                           COUNT(*) FILTER (WHERE shift_state = 'active') as active,
                           COUNT(DISTINCT department) as depts
                    FROM agents
                    WHERE shift_state != 'decommissioned'
                    GROUP BY floor
                    ORDER BY CASE floor
                        WHEN 'BRIDGE' THEN 1 WHEN 'OPERATIONS' THEN 2
                        WHEN 'ENGINEERING' THEN 3 WHEN 'CREATIVE' THEN 4
                        WHEN 'SERVICES' THEN 5 ELSE 6 END
                """
                )
                result["floors"] = [
                    {"name": r[0], "agents": r[1], "active": r[2], "departments": r[3]} for r in cur.fetchall()
                ]
        except Exception:
            result["floors"] = []

        return jsonify(result)

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
                            "title": a.get("title"),
                            "acronym": a.get("acronym"),
                            "acronym_expansion": a.get("acronym_expansion"),
                            "avatar_url": a.get("avatar_url"),
                            "worker_type": a.get("worker_type"),
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
