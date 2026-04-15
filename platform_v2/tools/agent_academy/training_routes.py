"""
Agent Academy — Training Routes

Skill progression, training programs, gap analysis.
"""

import logging

from flask import jsonify, request
from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_training_routes(bp, admin_required):
    """Register training API routes on the blueprint."""

    @bp.route("/api/training/status")
    @admin_required
    def training_status():
        """Per-department training status — agents grouped by skill level 1-5."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT a.department, a.id AS agent_id, a.name, a.display_name,
                          a.shift_state, s.skill_name, s.proficiency_level, s.skill_category
                   FROM agents a
                   LEFT JOIN agent_skills s ON s.agent_id = a.id
                   WHERE a.status = 'active'
                   ORDER BY a.department, a.display_name, s.skill_name"""
            )
            rows = [dict(r) for r in cur.fetchall()]

        # Group by department
        departments = {}
        for row in rows:
            dept = row["department"] or "Unassigned"
            if dept not in departments:
                departments[dept] = {"agents": {}, "skill_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}
            aid = row["agent_id"]
            if aid not in departments[dept]["agents"]:
                departments[dept]["agents"][aid] = {
                    "id": aid,
                    "name": row["name"],
                    "display_name": row["display_name"],
                    "shift_state": row["shift_state"],
                    "skills": [],
                }
            if row["skill_name"]:
                departments[dept]["agents"][aid]["skills"].append(
                    {
                        "name": row["skill_name"],
                        "level": row["proficiency_level"],
                        "category": row["skill_category"],
                    }
                )
                level = row["proficiency_level"] or 1
                if 1 <= level <= 5:
                    departments[dept]["skill_distribution"][level] += 1

        # Convert agents dict to list
        for dept in departments:
            departments[dept]["agents"] = list(departments[dept]["agents"].values())

        return jsonify({"departments": departments})

    @bp.route("/api/training/gaps")
    @admin_required
    def training_gaps():
        """Skills gaps: capabilities with no Lv4+ agents."""
        with get_db_cursor() as (conn, cur):
            # All known skills
            cur.execute(
                """SELECT DISTINCT skill_name, skill_category,
                          MAX(proficiency_level) AS max_level,
                          COUNT(DISTINCT agent_id) AS agent_count
                   FROM agent_skills
                   GROUP BY skill_name, skill_category
                   ORDER BY MAX(proficiency_level) ASC, skill_name"""
            )
            all_skills = [dict(r) for r in cur.fetchall()]

        gaps = []
        covered = []
        for skill in all_skills:
            entry = {
                "skill_name": skill["skill_name"],
                "category": skill["skill_category"],
                "max_level": skill["max_level"],
                "agent_count": skill["agent_count"],
            }
            if (skill["max_level"] or 0) < 4:
                gaps.append(entry)
            else:
                covered.append(entry)

        return jsonify(
            {
                "gaps": gaps,
                "covered": covered,
                "total_skills": len(all_skills),
                "gap_count": len(gaps),
            }
        )

    @bp.route("/api/training/assign", methods=["POST"])
    @admin_required
    def assign_training():
        """Assign training to an agent.

        Body: {agent_id, skill_name, target_level}
        Creates a learning record tracking the training assignment.
        """
        data = request.get_json(force=True)
        agent_id = data.get("agent_id")
        skill_name = data.get("skill_name", "")
        target_level = data.get("target_level", 3)

        if not agent_id or not skill_name:
            return jsonify({"error": "agent_id and skill_name required"}), 400

        from services.agent_service import get_agent, get_skills

        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        # Get current skill level
        skills = get_skills(agent_id)
        current_level = 0
        for s in skills:
            if s.get("skill_name") == skill_name:
                current_level = s.get("proficiency_level", 0)
                break

        # Create training record in agent_learning_records
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO agent_learning_records
                   (agent_id, learning_type, subject, lesson_learned,
                    confidence_before, confidence_after, source_type)
                   VALUES (%s, 'training_assignment', %s, %s, %s, %s, 'academy')
                   RETURNING id""",
                (
                    agent_id,
                    skill_name,
                    f"Training assigned: {skill_name} from Lv{current_level} to Lv{target_level}",
                    round(current_level / 5.0, 2) if current_level else 0.0,
                    round(target_level / 5.0, 2),
                ),
            )
            record_id = cur.fetchone()["id"]

        return jsonify(
            {
                "record_id": record_id,
                "agent_id": agent_id,
                "agent_name": agent.get("display_name") or agent.get("name"),
                "skill_name": skill_name,
                "current_level": current_level,
                "target_level": target_level,
            }
        )

    @bp.route("/api/training/records")
    @admin_required
    def training_records():
        """Recent training assignment records."""
        limit = request.args.get("limit", 20, type=int)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT lr.id, lr.agent_id, a.name, a.display_name, a.department,
                          lr.subject AS skill_name, lr.lesson_learned,
                          lr.confidence_before, lr.confidence_after,
                          lr.learned_at, lr.effectiveness_score
                   FROM agent_learning_records lr
                   JOIN agents a ON a.id = lr.agent_id
                   WHERE lr.learning_type = 'training_assignment'
                   ORDER BY lr.learned_at DESC
                   LIMIT %s""",
                (limit,),
            )
            records = []
            for row in cur.fetchall():
                r = dict(row)
                r["learned_at"] = str(r["learned_at"]) if r["learned_at"] else None
                r["confidence_before"] = float(r["confidence_before"]) if r["confidence_before"] else None
                r["confidence_after"] = float(r["confidence_after"]) if r["confidence_after"] else None
                r["effectiveness_score"] = float(r["effectiveness_score"]) if r["effectiveness_score"] else None
                records.append(r)

        return jsonify({"records": records})

    @bp.route("/api/training/growth/<int:agent_id>")
    @admin_required
    def agent_growth(agent_id):
        """Track agent growth over time — real dispatch metrics by week."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT
                       DATE_TRUNC('week', created_at) AS week,
                       COUNT(*) AS total_dispatches,
                       COUNT(*) FILTER (WHERE success = true) AS successes,
                       ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)::numeric, 2) AS success_rate,
                       ROUND(AVG(duration_ms)::numeric) AS avg_duration_ms
                   FROM task_execution_log
                   WHERE agent_id = %s
                   GROUP BY week
                   ORDER BY week DESC
                   LIMIT 12""",
                (agent_id,),
            )
            weeks = []
            for row in cur.fetchall():
                r = dict(row)
                r["week"] = str(r["week"]) if r["week"] else None
                weeks.append(r)

        return jsonify({"success": True, "agent_id": agent_id, "growth": weeks})

    @bp.route("/api/training/capability-matrix")
    @admin_required
    def capability_matrix():
        """Department requirements vs agent capabilities — gap analysis matrix."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT dcp.department, dcp.floor, dcp.required_capabilities
                   FROM department_capability_profiles dcp
                   ORDER BY dcp.department"""
            )
            departments = [dict(r) for r in cur.fetchall()]

            for dept in departments:
                caps = dept.get("required_capabilities") or []
                cur.execute(
                    """SELECT a.id, a.name, a.display_name
                       FROM agents a
                       WHERE a.department = %s AND a.worker_type = 'ai'
                         AND a.shift_state = 'active'""",
                    (dept["department"],),
                )
                agents = [dict(r) for r in cur.fetchall()]

                for agent in agents:
                    cur.execute(
                        """SELECT capability, score
                           FROM agent_competency_scores
                           WHERE agent_id = %s""",
                        (agent["id"],),
                    )
                    agent["scores"] = {r["capability"]: float(r["score"]) for r in cur.fetchall()}
                    agent["gaps"] = [c for c in caps if c not in agent["scores"]]

                dept["agents"] = agents
                dept["coverage"] = (
                    round(
                        sum(1 for a in agents for c in caps if a["scores"].get(c, 0) >= 0.5)
                        / max(len(agents) * len(caps), 1),
                        2,
                    )
                    if caps
                    else 0
                )

        return jsonify({"success": True, "matrix": departments})
