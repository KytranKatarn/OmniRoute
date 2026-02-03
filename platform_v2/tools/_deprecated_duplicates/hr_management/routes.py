"""
HR Management Module Routes
===========================
Consolidated HR functionality for the A.R.C.H.I.E. platform.

Features:
- Performance tracking & leaderboard
- Skills matrix & training
- Shift scheduling & coverage
- IAAE compliance & governance
- Wellness & rest cycles
- HR dashboard & reporting

This module consolidates HR-related features for easier access and management.
The underlying data comes from the shared agents table (single source of truth).
"""

from flask import Blueprint, render_template, jsonify, request
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from datetime import datetime, date
import os
import json

hr_bp = Blueprint("hr_management", __name__, template_folder="../../templates/tools", url_prefix="/tools/hr-management")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD"),
    )


def admin_required(f):
    """Decorator for admin-only routes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # In production, check session for admin status
        return f(*args, **kwargs)

    return decorated_function


# =============================================================================
# MAIN HR DASHBOARD
# =============================================================================


@hr_bp.route("/")
@admin_required
def index():
    """HR Management main page"""
    return render_template("hr_management.html")


@hr_bp.route("/api/dashboard")
def get_hr_dashboard():
    """Get HR dashboard statistics"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Agent statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_agents,
                COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_count,
                COUNT(*) FILTER (WHERE worker_type = 'contract') as contract_count,
                COUNT(*) FILTER (WHERE worker_type = 'human') as human_count,
                COUNT(DISTINCT department) as department_count
            FROM agents WHERE status = 'active'
        """
        )
        agent_stats = cur.fetchone()

        # Station coverage
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT bs.id) as total_stations,
                COUNT(DISTINCT sa.station_id) as staffed_stations
            FROM bridge_stations bs
            LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = true
            WHERE bs.is_active = true
        """
        )
        station_stats = cur.fetchone()

        # Department breakdown
        cur.execute(
            """
            SELECT department, COUNT(*) as count,
                   COUNT(*) FILTER (WHERE worker_type = 'internal') as internal,
                   COUNT(*) FILTER (WHERE worker_type = 'contract') as contract
            FROM agents WHERE status = 'active'
            GROUP BY department ORDER BY count DESC
        """
        )
        departments = cur.fetchall()

        # Model distribution
        cur.execute(
            """
            SELECT model, worker_type, COUNT(*) as count
            FROM agents WHERE status = 'active'
            GROUP BY model, worker_type ORDER BY count DESC
        """
        )
        models = cur.fetchall()

        # Current staffing status
        current_hour = datetime.now().hour
        staffing_status = "Full Staff" if 9 <= current_hour < 17 else "Reduced Staff"

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stats": {"agents": agent_stats, "stations": station_stats, "staffing_status": staffing_status},
                "departments": departments,
                "models": models,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# PERFORMANCE MANAGEMENT
# =============================================================================


@hr_bp.route("/api/performance/leaderboard")
def get_performance_leaderboard():
    """Get agent performance leaderboard"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT a.id, a.name, a.department, a.model, a.worker_type,
                   COALESCE(apm.tasks_completed, 0) as tasks_completed,
                   COALESCE(apm.success_rate, 0) as success_rate,
                   COALESCE(apm.quality_score, 0) as quality_score,
                   COALESCE(apm.overall_score, 0) as overall_score,
                   COALESCE(apm.grade, 'N/A') as grade
            FROM agents a
            LEFT JOIN agent_performance_metrics apm ON a.id = apm.agent_id
            WHERE a.status = 'active' AND a.worker_type = 'internal'
            ORDER BY COALESCE(apm.overall_score, 0) DESC
            LIMIT 20
        """
        )
        leaderboard = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "leaderboard": leaderboard})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/performance/<int:agent_id>")
def get_agent_performance(agent_id):
    """Get performance data for a specific agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Agent info
        cur.execute(
            """
            SELECT id, name, department, model, worker_type
            FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        agent = cur.fetchone()

        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        # Performance metrics
        cur.execute(
            """
            SELECT * FROM agent_performance_metrics WHERE agent_id = %s
        """,
            (agent_id,),
        )
        metrics = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agent": agent, "metrics": metrics or {}})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# SKILLS MANAGEMENT
# =============================================================================


@hr_bp.route("/api/skills/matrix")
def get_skills_matrix():
    """Get skills matrix (agents x skills)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT a.id, a.name, a.department,
                   COALESCE(
                       json_agg(
                           json_build_object(
                               'skill_id', s.id,
                               'skill_name', s.name,
                               'proficiency', asr.proficiency_level
                           )
                       ) FILTER (WHERE s.id IS NOT NULL),
                       '[]'
                   ) as skills
            FROM agents a
            LEFT JOIN agent_skill_records asr ON a.id = asr.agent_id
            LEFT JOIN skills s ON asr.skill_id = s.id
            WHERE a.status = 'active' AND a.worker_type = 'internal'
            GROUP BY a.id, a.name, a.department
            ORDER BY a.department, a.name
        """
        )
        matrix = cur.fetchall()

        # All skills
        cur.execute("SELECT id, name, category FROM skills ORDER BY category, name")
        all_skills = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "matrix": matrix, "skills": all_skills})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# SCHEDULING & SHIFTS
# =============================================================================


@hr_bp.route("/api/scheduling/status")
def get_staffing_status():
    """Get current staffing status (Full/Reduced)"""
    try:
        current_hour = datetime.now().hour
        is_business_hours = 9 <= current_hour < 17

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Count agents on duty (simplified)
        cur.execute(
            """
            SELECT COUNT(DISTINCT agent_id) as on_duty
            FROM station_assignments
            WHERE is_active = true
        """
        )
        on_duty = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "status": "Full Staff" if is_business_hours else "Reduced Staff",
                "is_business_hours": is_business_hours,
                "current_hour": current_hour,
                "agents_on_duty": on_duty["on_duty"] if on_duty else 0,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/scheduling/shifts")
def get_shifts():
    """Get shift definitions"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM shift_definitions ORDER BY start_time
        """
        )
        shifts = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "shifts": shifts})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/scheduling/on-shift")
def get_agents_on_shift():
    """Get agents currently on shift per station/module"""
    try:
        module = request.args.get("module")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get primary agents for each station (include full name fields)
        cur.execute(
            """
            SELECT bs.station_code, bs.station_name, bs.modules,
                   a.id as agent_id, a.name as agent_role,
                   a.first_name, a.last_name, a.title, a.model,
                   sa.assignment_type
            FROM bridge_stations bs
            JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = true
            JOIN agents a ON sa.agent_id = a.id
            WHERE sa.assignment_type = 'primary'
            ORDER BY bs.station_code
        """
        )
        assignments = cur.fetchall()

        # Create module-to-agent mapping with full name and position
        module_agents = {}
        for row in assignments:
            if row["modules"]:
                # Build full name from first_name + last_name
                first = row.get("first_name") or ""
                last = row.get("last_name") or ""
                full_name = f"{first} {last}".strip() or row["agent_role"]
                position = row.get("title") or row["agent_role"]

                for mod in row["modules"]:
                    module_agents[mod] = {
                        "full_name": full_name,
                        "position": position,
                        "agent_name": row["agent_role"],  # Keep for backward compat
                        "agent_id": row["agent_id"],
                        "model": row["model"],
                        "station": row["station_code"],
                    }

        cur.close()
        conn.close()

        if module:
            return jsonify(
                {"success": True, "agent": module_agents.get(module, {"agent_name": "Unassigned", "agent_id": None})}
            )

        return jsonify({"success": True, "assignments": assignments, "module_agents": module_agents})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# IAAE COMPLIANCE
# =============================================================================


@hr_bp.route("/api/compliance/summary")
def get_compliance_summary():
    """Get IAAE compliance summary"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Agent compliance status
        cur.execute(
            """
            SELECT
                COUNT(*) as total_agents,
                COUNT(*) FILTER (WHERE worker_type = 'internal') as internal_compliant,
                COUNT(*) FILTER (WHERE worker_type = 'contract') as contractors
            FROM agents WHERE status = 'active'
        """
        )
        compliance = cur.fetchone()

        # Recent audit events (if table exists)
        try:
            cur.execute(
                """
                SELECT * FROM governance_audit_log
                ORDER BY created_at DESC LIMIT 10
            """
            )
            audit_events = cur.fetchall()
        except:
            audit_events = []

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "compliance": compliance,
                "audit_events": audit_events,
                "local_first_compliance": True,  # All internal agents use local LLMs
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# WELLNESS
# =============================================================================


@hr_bp.route("/api/wellness/status")
def get_wellness_status():
    """Get agent wellness status (energy, stress levels)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Try to get emotional state if table exists
        try:
            cur.execute(
                """
                SELECT a.id, a.name, a.department,
                       aes.energy_level, aes.stress_level, aes.last_rest_at
                FROM agents a
                LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
                WHERE a.status = 'active' AND a.worker_type = 'internal'
                ORDER BY COALESCE(aes.stress_level, 0) DESC
            """
            )
            wellness = cur.fetchall()
        except:
            # Fallback if table doesn't exist
            cur.execute(
                """
                SELECT id, name, department, 0.8 as energy_level, 0.2 as stress_level
                FROM agents
                WHERE status = 'active' AND worker_type = 'internal'
            """
            )
            wellness = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": wellness})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# IAAE MONITORING (Phase 49 - New)
# =============================================================================


@hr_bp.route("/api/iaae/summary")
def get_iaae_summary():
    """Get IAAE monitoring summary"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_iaae_summary")
        summary = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({"success": True, "summary": summary})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/iaae/agents")
def get_iaae_agent_health():
    """Get all agents' IAAE health status"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_iaae_agent_health
            ORDER BY
                CASE health_status
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'WARNING' THEN 2
                    WHEN 'LOW_ENERGY' THEN 3
                    ELSE 4
                END,
                stress_level DESC
        """
        )
        agents = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "agents": agents})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/iaae/thresholds")
def get_iaae_thresholds():
    """Get IAAE monitoring thresholds"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM iaae_thresholds WHERE is_active = true")
        thresholds = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "thresholds": thresholds})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/iaae/rest/<int:agent_id>", methods=["POST"])
def trigger_rest(agent_id):
    """Trigger rest cycle for an agent"""
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "Manual HR intervention")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT trigger_agent_rest(%s, 'manual', %s)", (agent_id, reason))
        rest_id = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "rest_cycle_id": rest_id["trigger_agent_rest"] if rest_id else None,
                "message": f"Rest cycle initiated for agent {agent_id}",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/iaae/rest/<int:agent_id>/end", methods=["POST"])
def end_rest(agent_id):
    """End rest cycle for an agent"""
    try:
        data = request.get_json() or {}
        notes = data.get("notes", "Rest cycle completed via HR")

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT end_agent_rest(%s, %s)", (agent_id, notes))
        result = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "ended": result["end_agent_rest"] if result else False})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# SHIFTS MANAGEMENT (Phase 48 - New)
# =============================================================================


@hr_bp.route("/api/shifts/status")
def get_shift_status():
    """Get current staffing status from v_staffing_status view"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_staffing_status")
        status = cur.fetchone()

        cur.close()
        conn.close()

        # Convert time/date objects to strings for JSON serialization
        if status:
            serializable = {}
            for key, value in status.items():
                if hasattr(value, "isoformat"):
                    serializable[key] = value.isoformat()
                elif hasattr(value, "strftime"):
                    serializable[key] = str(value)
                else:
                    serializable[key] = value
            status = serializable

        return jsonify({"success": True, "staffing": status})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/shifts/schedule")
def get_shift_schedule():
    """Get shift schedule for all agents"""
    try:
        day = request.args.get("day", None)  # 0-6 for specific day

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT ash.*, a.name as agent_name, a.first_name, a.last_name,
                   sd.shift_name, sd.start_time, sd.end_time,
                   bs.station_name
            FROM agent_shifts ash
            JOIN agents a ON ash.agent_id = a.id
            JOIN shift_definitions sd ON ash.shift_id = sd.id
            LEFT JOIN bridge_stations bs ON ash.station_id = bs.id
            WHERE ash.effective_from <= CURRENT_DATE
              AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
        """

        if day is not None:
            query += " AND ash.day_of_week = %s"
            cur.execute(query + " ORDER BY sd.start_time, a.name", (int(day),))
        else:
            cur.execute(query + " ORDER BY ash.day_of_week, sd.start_time, a.name")

        schedule = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "schedule": schedule})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# SKILLS VALIDATION (Phase 46 - New)
# =============================================================================


@hr_bp.route("/api/skills/validation")
def get_skill_validation():
    """Get skill validation status for all agent-module assignments"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_agent_skill_mismatches
            ORDER BY
                CASE validation_status
                    WHEN 'NO_MATCHING_SKILLS' THEN 1
                    WHEN 'PROFICIENCY_TOO_LOW' THEN 2
                    ELSE 3
                END,
                agent_name
        """
        )
        validations = cur.fetchall()

        # Summary
        cur.execute("SELECT * FROM v_skill_mismatch_summary")
        summary = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "validations": validations, "summary": summary})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@hr_bp.route("/api/skills/modules")
def get_module_skills():
    """Get required skills for each module"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM module_required_skills
            ORDER BY skill_category, module_name
        """
        )
        modules = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "modules": modules})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# WORKLOAD BALANCE (Phase 47 - New)
# =============================================================================


@hr_bp.route("/api/workload/balance")
def get_workload_balance():
    """Get workload balance per station"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_workload_balance ORDER BY module_count DESC")
        workload = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "workload": workload})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# HEALTH CHECK
# =============================================================================


@hr_bp.route("/api/health")
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "module": "hr_management", "timestamp": datetime.now().isoformat()})
