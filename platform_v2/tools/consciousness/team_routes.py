"""Team Routes -- Agent directory, performance, emotional state

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Team directory (/team)
- Agent listing, detail, performance, leaderboard
- Team awareness data (comprehensive agent+department stats)
- Emotional state and timeline
"""

import logging
import os
import traceback

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from flask import jsonify, render_template, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def _get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


def register_team_routes(bp, admin_required):
    """Register all team-related routes on the consciousness blueprint."""

    # ==================================================================
    # TEAM DIRECTORY
    # ==================================================================

    @bp.route("/team")
    @login_required
    @admin_required
    def team_awareness():
        """Team directory - all agents, performance, capabilities"""
        return render_template("team_awareness.html")

    # ==================================================================
    # AGENT LISTING & DETAILS
    # ==================================================================

    @bp.route("/team/agents", methods=["GET"])
    @login_required
    @admin_required
    def get_agents():
        """Get all agents with their capabilities and metrics"""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Query from agents table (the actual team members)
            cur.execute(
                """
                SELECT
                    a.id,
                    a.name,
                    a.first_name,
                    a.last_name,
                    a.title,
                    a.department,
                    a.worker_type,
                    a.status,
                    a.tier,
                    a.model,
                    a.total_tasks_completed as tasks_completed,
                    a.success_rate,
                    a.total_tokens_used as tokens_used,
                    a.total_cost,
                    a.last_used,
                    at.name as agent_type
                FROM agents a
                LEFT JOIN agent_types at ON a.type_id = at.id
                WHERE a.status = 'active'
                ORDER BY a.name
                LIMIT 50
            """
            )

            agents = cur.fetchall()

            # Convert to serializable format
            for agent in agents:
                if agent.get("last_used"):
                    agent["last_used"] = agent["last_used"].isoformat()
                # Ensure worker_type has a default
                if not agent.get("worker_type"):
                    agent["worker_type"] = "internal"
                # Calculate display name
                if agent.get("first_name") and agent.get("last_name"):
                    agent["full_name"] = f"{agent['first_name']} {agent['last_name']}"
                else:
                    agent["full_name"] = agent.get("name", "Unknown")
                # Ensure role fallback
                agent["role"] = agent.get("title") or agent.get("agent_type") or "Agent"
            return jsonify({"success": True, "agents": agents})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/team/agents/<int:agent_id>", methods=["GET"])
    @login_required
    @admin_required
    def get_agent_details(agent_id):
        """Get detailed information about a specific agent"""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT * FROM agent_profiles WHERE id = %s
            """,
                (agent_id,),
            )

            agent = cur.fetchone()

            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            # Get recent task executions
            cur.execute(
                """
                SELECT id, task_type, task_description, model_used,
                       tokens_used, duration_ms, success, created_at
                FROM task_execution_log
                WHERE agent_id = %s
                ORDER BY created_at DESC
                LIMIT 10
            """,
                (agent_id,),
            )

            recent_tasks = cur.fetchall()
            return jsonify({"agent": dict(agent), "recent_tasks": [dict(t) for t in recent_tasks]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # PERFORMANCE
    # ==================================================================

    @bp.route("/team/agents/<int:agent_id>/performance", methods=["GET"])
    @login_required
    @admin_required
    def get_agent_performance(agent_id):
        """Get agent performance metrics"""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    COUNT(*) as total_tasks,
                    COUNT(*) FILTER (WHERE success = true) as completed_tasks,
                    COUNT(*) FILTER (WHERE success = false) as failed_tasks,
                    AVG(duration_ms) / 1000.0 as avg_completion_seconds
                FROM task_execution_log
                WHERE agent_id = %s
            """,
                (agent_id,),
            )

            performance = cur.fetchone()
            return jsonify(performance)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/team/leaderboard", methods=["GET"])
    @login_required
    @admin_required
    def performance_leaderboard():
        """Get agent performance leaderboard"""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    ap.id,
                    ap.first_name || ' ' || ap.last_name as full_name,
                    ap.title,
                    COUNT(tel.id) as total_tasks,
                    COUNT(tel.id) FILTER (WHERE tel.success = true) as completed_tasks,
                    ROUND(AVG(CASE WHEN tel.success THEN 1.0 ELSE 0.0 END)::numeric, 2) as success_rate
                FROM agent_profiles ap
                LEFT JOIN task_execution_log tel ON ap.id = tel.agent_id
                WHERE ap.status = 'active'
                GROUP BY ap.id, ap.first_name, ap.last_name, ap.title
                ORDER BY success_rate DESC, completed_tasks DESC
                LIMIT 20
            """
            )

            leaderboard = [dict(r) for r in cur.fetchall()]
            return jsonify({"leaderboard": leaderboard})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # TEAM AWARENESS DATA (COMPREHENSIVE)
    # ==================================================================

    @bp.route("/team-awareness-data", methods=["GET"])
    @login_required
    @admin_required
    def get_team_awareness_data():
        """Get A.R.C.H.I.E.'s team awareness - all agents and their details (ENHANCED)"""
        print("🧠 [BACKEND] get_team_awareness_data called - COMPREHENSIVE MODE")

        conn = _get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Get all active agents with comprehensive details
            cur.execute(
                """
                SELECT
                    a.id, a.name, a.first_name, a.last_name, a.email,
                    a.title, a.department, a.pronouns, a.bio,
                    a.tier, a.model, a.status,
                    a.monthly_budget, a.total_cost, a.total_tokens_used,
                    a.last_used, a.created_at,
                    a.worker_type, a.requires_api_approval, a.api_provider,
                    a.cost_tier, a.api_enabled, a.api_key_configured,
                    at.name as agent_type, at.category as type_category
                FROM agents a
                LEFT JOIN agent_types at ON a.type_id = at.id
                WHERE a.status = 'active'
                ORDER BY a.department, a.first_name
            """
            )
            agents = cur.fetchall()

            # Get department summary
            cur.execute(
                """
                SELECT
                    department,
                    COUNT(*) as agent_count,
                    SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_count,
                    SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_count,
                    SUM(monthly_budget) as total_budget,
                    SUM(total_cost) as total_spent
                FROM agents
                WHERE status = 'active'
                GROUP BY department
                ORDER BY agent_count DESC
            """
            )
            departments = cur.fetchall()

            # Get overall statistics
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_agents,
                    COUNT(DISTINCT department) as total_departments,
                    SUM(monthly_budget) as total_budget,
                    SUM(total_cost) as total_cost,
                    SUM(total_tokens_used) as total_tokens,
                    COUNT(CASE WHEN last_used >= NOW() - INTERVAL '7 days' THEN 1 END) as active_last_week,
                    SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_agents,
                    SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_agents,
                    SUM(CASE WHEN worker_type = 'contract' AND api_enabled = TRUE THEN 1 ELSE 0 END) as contract_enabled,
                    SUM(CASE WHEN worker_type = 'contract' AND api_enabled = FALSE THEN 1 ELSE 0 END) as contract_disabled
                FROM agents
                WHERE status = 'active'
            """
            )
            stats = cur.fetchone()

            # Convert datetime objects to ISO format BEFORE building by_department
            for agent in agents:
                if agent["last_used"]:
                    agent["last_used"] = agent["last_used"].isoformat()
                if agent["created_at"]:
                    agent["created_at"] = agent["created_at"].isoformat()

            # Organize agents by department
            by_department = {}
            for agent in agents:
                dept = agent["department"] or "Unassigned"
                if dept not in by_department:
                    by_department[dept] = []
                by_department[dept].append(dict(agent))

            result = {
                "success": True,
                "team": {
                    "agents": [dict(a) for a in agents],
                    "by_department": by_department,
                    "departments": [dict(d) for d in departments],
                    "statistics": dict(stats),
                },
            }

            print(
                f"🧠 [BACKEND] Returning {stats['total_agents']} agents across {stats['total_departments']} departments"
            )
            return jsonify(result)

        except Exception as e:
            print("❌ [BACKEND] Error in get_team_awareness_data:")
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/team-awareness", methods=["GET"])
    @login_required
    @admin_required
    def get_team_awareness():
        """Get A.R.C.H.I.E.'s team awareness - all agents and their details"""
        print("🧠 [BACKEND] get_team_awareness called")

        conn = _get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Get all active agents
            cur.execute(
                """
                SELECT
                    a.id, a.name, a.first_name, a.last_name, a.email,
                    a.title, a.department, a.pronouns, a.bio,
                    a.tier, a.model, a.status,
                    a.monthly_budget, a.total_cost, a.total_tokens_used,
                    a.last_used, a.created_at,
                    a.worker_type, a.requires_api_approval, a.api_provider,
                    a.cost_tier, a.api_enabled, a.api_key_configured,
                    at.name as agent_type, at.category as type_category
                FROM agents a
                LEFT JOIN agent_types at ON a.type_id = at.id
                WHERE a.status = 'active'
                ORDER BY a.department, a.first_name
            """
            )
            agents = cur.fetchall()

            # Get department summary
            cur.execute(
                """
                SELECT
                    department,
                    COUNT(*) as agent_count,
                    SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_count,
                    SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_count,
                    SUM(monthly_budget) as total_budget,
                    SUM(total_cost) as total_spent
                FROM agents
                WHERE status = 'active'
                GROUP BY department
                ORDER BY agent_count DESC
            """
            )
            departments = cur.fetchall()

            # Get overall statistics
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_agents,
                    COUNT(DISTINCT department) as total_departments,
                    SUM(monthly_budget) as total_budget,
                    SUM(total_cost) as total_cost,
                    SUM(total_tokens_used) as total_tokens,
                    COUNT(CASE WHEN last_used >= NOW() - INTERVAL '7 days' THEN 1 END) as active_last_week,
                    SUM(CASE WHEN worker_type = 'internal' THEN 1 ELSE 0 END) as internal_agents,
                    SUM(CASE WHEN worker_type = 'contract' THEN 1 ELSE 0 END) as contract_agents,
                    SUM(CASE WHEN worker_type = 'contract' AND api_enabled = TRUE THEN 1 ELSE 0 END) as contract_enabled,
                    SUM(CASE WHEN worker_type = 'contract' AND api_enabled = FALSE THEN 1 ELSE 0 END) as contract_disabled
                FROM agents
                WHERE status = 'active'
            """
            )
            stats = cur.fetchone()

            # Convert datetime objects to ISO format BEFORE building by_department
            for agent in agents:
                if agent["last_used"]:
                    agent["last_used"] = agent["last_used"].isoformat()
                if agent["created_at"]:
                    agent["created_at"] = agent["created_at"].isoformat()

            # Organize agents by department
            by_department = {}
            for agent in agents:
                dept = agent["department"] or "Unassigned"
                if dept not in by_department:
                    by_department[dept] = []
                by_department[dept].append(dict(agent))

            result = {
                "success": True,
                "team": {
                    "agents": [dict(a) for a in agents],
                    "by_department": by_department,
                    "departments": [dict(d) for d in departments],
                    "statistics": dict(stats),
                },
            }

            print(
                f"🧠 [BACKEND] Returning {stats['total_agents']} agents across {stats['total_departments']} departments"
            )
            return jsonify(result)

        except Exception as e:
            print("❌ [BACKEND] Error in get_team_awareness:")
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # EMOTIONAL STATE
    # ==================================================================

    @bp.route("/emotions/timeline", methods=["GET"])
    @login_required
    @admin_required
    def get_emotional_timeline():
        """Get ARCHIE's emotional state over time with mood labels and stress data"""

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            days = request.args.get("days", 30, type=int)

            # Get emotional state history with mood labels
            cur.execute(
                """
                SELECT
                    DATE(timestamp) as date,
                    AVG(CASE WHEN current_mood = 'happy' THEN 1.0
                             WHEN current_mood = 'curious' THEN 0.8
                             WHEN current_mood = 'focused' THEN 0.6
                             WHEN current_mood = 'neutral' THEN 0.5
                             WHEN current_mood = 'confused' THEN 0.3
                             WHEN current_mood = 'frustrated' THEN 0.2
                             ELSE 0.5 END) as avg_mood_score,
                    AVG(mood_intensity) as avg_energy,
                    AVG(relationship_strength) as avg_confidence,
                    COUNT(*) as measurement_count,
                    MODE() WITHIN GROUP (ORDER BY current_mood) as dominant_mood
                FROM agent_emotional_state
                WHERE timestamp > NOW() - (%s * INTERVAL '1 day')
                GROUP BY DATE(timestamp)
                ORDER BY date ASC
            """,
                (days,),
            )
            timeline = cur.fetchall()

            # Get stress data from agent_emotional_state if available
            cur.execute(
                """
                SELECT
                    DATE(timestamp) as date,
                    AVG(stress_level) as avg_stress,
                    AVG(energy_level) as avg_agent_energy
                FROM agent_emotional_state
                WHERE timestamp > NOW() - (%s * INTERVAL '1 day')
                GROUP BY DATE(timestamp)
                ORDER BY date ASC
            """,
                (days,),
            )
            stress_data = {str(r["date"]): r for r in cur.fetchall()}

            # Merge stress data into timeline
            for entry in timeline:
                date_key = str(entry["date"])
                if date_key in stress_data:
                    entry["avg_stress"] = stress_data[date_key]["avg_stress"]
                    entry["avg_agent_energy"] = stress_data[date_key]["avg_agent_energy"]

            # Get current emotional state
            cur.execute(
                """
                SELECT id, timestamp, current_mood as mood, mood_intensity as energy,
                       relationship_strength as confidence, user_id, notes
                FROM agent_emotional_state
                ORDER BY timestamp DESC LIMIT 1
            """
            )
            current_state = cur.fetchone()
            return jsonify({"timeline": timeline, "current_state": current_state})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # TEAM ROSTER & AGENT PROFILE (Agent Command Center)
    # ==================================================================

    @bp.route("/api/team/roster")
    @login_required
    @admin_required
    def api_team_roster():
        """Agent roster with profiles, skills, emotions, station assignments."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT ap.id, ap.first_name, ap.last_name, ap.full_name,
                       ap.title, ap.department, ap.bio, ap.status, ap.agent_type,
                       ap.category, ap.model, ap.tier,
                       aes.current_mood, aes.mood_intensity, aes.energy_level,
                       aes.stress_level, aes.timestamp as mood_updated,
                       avp.profile_name as voice_profile, avp.engine as voice_engine,
                       avp.language as voice_language,
                       sa.id as assignment_id, bs.station_name, bs.station_code
                FROM agent_profiles ap
                LEFT JOIN agent_emotional_state aes ON aes.agent_id = ap.id
                LEFT JOIN agent_voice_profiles avp ON avp.agent_id = ap.id AND avp.is_active = true
                LEFT JOIN station_assignments sa ON sa.agent_id = ap.id AND sa.is_active = true
                LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
                ORDER BY ap.id
            """
            )
            agents = cur.fetchall()

            # Skills per agent
            cur.execute(
                """
                SELECT agent_id, skill_name, skill_category, proficiency_level
                FROM agent_skills ORDER BY agent_id, proficiency_level DESC
            """
            )
            skills_raw = cur.fetchall()

            skills_map = {}
            for s in skills_raw:
                aid = s["agent_id"]
                if aid not in skills_map:
                    skills_map[aid] = []
                skills_map[aid].append(
                    {
                        "name": s["skill_name"],
                        "category": s["skill_category"],
                        "level": s["proficiency_level"],
                    }
                )

            result = []
            for a in agents:
                agent = dict(a)
                agent["skills"] = skills_map.get(a["id"], [])
                agent["skill_count"] = len(agent["skills"])
                result.append(agent)
            return jsonify({"success": True, "agents": result})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/api/team/agents/<int:agent_id>/profile")
    @login_required
    @admin_required
    def api_agent_profile(agent_id):
        """Full agent personnel file for detail modal."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT * FROM agent_profiles WHERE id = %s", (agent_id,))
            agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Agent not found"}), 404

            # Identity traits (from agent_identity table, NOT agent_personalities)
            cur.execute(
                """
                SELECT identity_key, identity_value, confidence
                FROM agent_identity WHERE agent_id = %s ORDER BY identity_key
            """,
                (agent_id,),
            )
            identity = cur.fetchall()

            # Skills
            cur.execute(
                """
                SELECT skill_name, skill_category, proficiency_level, notes
                FROM agent_skills WHERE agent_id = %s ORDER BY proficiency_level DESC
            """,
                (agent_id,),
            )
            skills = cur.fetchall()

            # Emotional history (last 30) — timestamp column, NOT created_at
            cur.execute(
                """
                SELECT current_mood, mood_intensity, energy_level, stress_level,
                       trigger_event, timestamp
                FROM agent_emotional_state
                WHERE agent_id = %s ORDER BY timestamp DESC LIMIT 30
            """,
                (agent_id,),
            )
            emotions = cur.fetchall()

            # Voice profile
            cur.execute(
                """
                SELECT * FROM agent_voice_profiles
                WHERE agent_id = %s AND is_active = true
            """,
                (agent_id,),
            )
            voice = cur.fetchone()

            # Learning log
            cur.execute(
                """
                SELECT learned_from, skill_name, confidence, context_summary, created_at
                FROM agent_learning_log WHERE agent_id = %s ORDER BY created_at DESC LIMIT 20
            """,
                (agent_id,),
            )
            learning = cur.fetchall()

            # Rest cycles — started_at column, NOT timestamp
            cur.execute(
                """
                SELECT rest_type, started_at, ended_at, reason,
                       stress_at_start, energy_at_start
                FROM agent_rest_cycles WHERE agent_id = %s ORDER BY started_at DESC LIMIT 10
            """,
                (agent_id,),
            )
            rest = cur.fetchall()

            # Station assignment
            cur.execute(
                """
                SELECT sa.*, bs.station_name, bs.station_code, bs.color
                FROM station_assignments sa
                JOIN bridge_stations bs ON bs.id = sa.station_id
                WHERE sa.agent_id = %s AND sa.is_active = true
            """,
                (agent_id,),
            )
            station = cur.fetchone()
            return jsonify(
                {
                    "success": True,
                    "agent": dict(agent),
                    "identity": [dict(i) for i in identity],
                    "skills": [dict(s) for s in skills],
                    "emotions": [dict(e) for e in emotions],
                    "voice": dict(voice) if voice else None,
                    "learning": [dict(l) for l in learning],
                    "rest_cycles": [dict(r) for r in rest],
                    "station": dict(station) if station else None,
                }
            )
        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # EMOTIONAL STATE
    # ==================================================================

    @bp.route("/emotional-state", methods=["GET"])
    @login_required
    @admin_required
    def emotional_state():
        """Get current emotional state from agent_emotional_state table.
        Schema: id, agent_id, current_mood, mood_intensity, energy_level,
        stress_level, trigger_event, timestamp, previous_mood,
        mood_duration_minutes, metadata (JSONB)
        """
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Latest emotional state
            cur.execute(
                """
                SELECT id, agent_id, current_mood, mood_intensity,
                       energy_level, stress_level, trigger_event,
                       timestamp, previous_mood, mood_duration_minutes,
                       metadata
                FROM agent_emotional_state
                ORDER BY timestamp DESC
                LIMIT 1
            """
            )
            state = cur.fetchone()

            # Recent mood transitions (where mood actually changed)
            cur.execute(
                """
                SELECT current_mood, previous_mood, trigger_event,
                       mood_duration_minutes, timestamp
                FROM agent_emotional_state
                WHERE previous_mood IS NOT NULL
                  AND current_mood != previous_mood
                ORDER BY timestamp DESC
                LIMIT 10
            """
            )
            mood_transitions = cur.fetchall()

            # Mood distribution
            cur.execute(
                """
                SELECT current_mood, COUNT(*) as count
                FROM agent_emotional_state
                GROUP BY current_mood
                ORDER BY count DESC
            """
            )
            mood_distribution = cur.fetchall()

            # Data freshness
            cur.execute("SELECT COUNT(*) as cnt FROM agent_emotional_state")
            state_count = cur.fetchone()["cnt"]

            # Build response
            if state:
                result = {
                    "mood": state.get("current_mood", "neutral"),
                    "energy": float(state.get("energy_level") or 0.5),
                    "confidence": float(state.get("mood_intensity") or 0.5),
                    "stress": float(state.get("stress_level") or 0),
                    "trigger_event": state.get("trigger_event"),
                    "previous_mood": state.get("previous_mood"),
                    "timestamp": str(state["timestamp"]) if state.get("timestamp") else None,
                    "agent_id": state.get("agent_id"),
                    "metadata": state.get("metadata"),
                }
            else:
                result = {
                    "mood": "neutral",
                    "energy": 0.5,
                    "confidence": 0.5,
                    "stress": 0,
                }

            result["mood_transitions"] = [dict(t) for t in mood_transitions]
            result["mood_distribution"] = [dict(d) for d in mood_distribution]
            result["data_freshness"] = {
                "total_states": state_count,
            }
            result["computed"] = {
                "energy": result["energy"],
                "confidence": result["confidence"],
                "stress": result["stress"],
                "has_agent_data": state is not None,
            }

            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
