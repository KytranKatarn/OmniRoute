"""
Agent Academy — Competency Routes

Per-agent capability testing against department profiles,
department readiness scorecards, and competency scoring.

Decision #441 — LLM Ecosystem Redesign Phase 5
"""

import logging

from flask import jsonify, request
from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_competency_routes(bp, admin_required):
    """Register competency testing API routes on the blueprint."""

    @bp.route("/api/competency/test", methods=["POST"])
    @admin_required
    def run_competency_test():
        """Test an agent against their department's required capabilities.

        POST body: { "agent_id": int } or { "department": string }
        Returns test results per capability with scores.
        """
        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        department = data.get("department")

        if not agent_id and not department:
            return jsonify({"success": False, "error": "Provide agent_id or department"}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            # Get agents to test
            if agent_id:
                cur.execute(
                    """SELECT a.id, a.name, a.department, a.model
                       FROM agents a
                       WHERE a.id = %s AND a.worker_type = 'ai'""",
                    (agent_id,),
                )
                agents = [dict(r) for r in cur.fetchall()]
            else:
                cur.execute(
                    """SELECT a.id, a.name, a.department, a.model
                       FROM agents a
                       WHERE a.department = %s AND a.worker_type = 'ai'
                         AND a.shift_state = 'active'""",
                    (department,),
                )
                agents = [dict(r) for r in cur.fetchall()]

            if not agents:
                return jsonify({"success": False, "error": "No matching AI agents found"}), 404

            # Get department capabilities for the first agent's department
            dept = agents[0]["department"]
            cur.execute(
                """SELECT required_capabilities
                   FROM department_capability_profiles
                   WHERE department = %s""",
                (dept,),
            )
            row = cur.fetchone()
            if not row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"No capability profile for department '{dept}'",
                        }
                    ),
                    404,
                )

            required_caps = row["required_capabilities"] or []

            # Score each agent against each required capability using dispatch history
            results = []
            for agent in agents:
                agent_scores = []
                for cap in required_caps:
                    # Calculate score from real dispatch success rate
                    cur.execute(
                        """SELECT
                               COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE success = true) AS successes,
                               AVG(duration_ms) AS avg_duration
                           FROM task_execution_log
                           WHERE agent_id = %s AND capability = %s
                             AND created_at >= NOW() - INTERVAL '30 days'""",
                        (agent["id"], cap),
                    )
                    stats = dict(cur.fetchone())
                    total = stats["total"] or 0
                    successes = stats["successes"] or 0

                    if total > 0:
                        score = round(successes / total, 2)
                    else:
                        score = 0.0  # untested

                    # Upsert competency score
                    cur.execute(
                        """INSERT INTO agent_competency_scores
                               (agent_id, capability, score, test_count, last_tested, source)
                           VALUES (%s, %s, %s, %s, NOW(), 'benchmark')
                           ON CONFLICT (agent_id, capability)
                           DO UPDATE SET score = EXCLUDED.score,
                                         test_count = agent_competency_scores.test_count + 1,
                                         last_tested = NOW()""",
                        (agent["id"], cap, score, total),
                    )

                    agent_scores.append(
                        {
                            "capability": cap,
                            "score": score,
                            "dispatches": total,
                            "successes": successes,
                            "avg_duration_ms": round(stats["avg_duration"] or 0),
                        }
                    )

                results.append(
                    {
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "department": dept,
                        "scores": agent_scores,
                        "avg_score": (
                            round(sum(s["score"] for s in agent_scores) / len(agent_scores), 2) if agent_scores else 0
                        ),
                    }
                )

            return jsonify({"success": True, "results": results})

    @bp.route("/api/competency/readiness")
    @admin_required
    def department_readiness():
        """Department readiness scorecard — per-department capability coverage."""
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM v_department_readiness")
            departments = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "departments": departments})

    @bp.route("/api/competency/scores/<int:agent_id>")
    @admin_required
    def agent_scores(agent_id):
        """Get all competency scores for a specific agent."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT acs.capability, acs.score, acs.test_count,
                          acs.last_tested, acs.source
                   FROM agent_competency_scores acs
                   WHERE acs.agent_id = %s
                   ORDER BY acs.score ASC""",
                (agent_id,),
            )
            scores = [dict(r) for r in cur.fetchall()]

            # Also get department requirements for gap analysis
            cur.execute(
                """SELECT dcp.required_capabilities
                   FROM department_capability_profiles dcp
                   JOIN agents a ON a.department = dcp.department
                   WHERE a.id = %s""",
                (agent_id,),
            )
            row = cur.fetchone()
            required = row["required_capabilities"] if row else []

            # Identify gaps
            scored_caps = {s["capability"] for s in scores}
            gaps = [cap for cap in required if cap not in scored_caps]

            return jsonify(
                {
                    "success": True,
                    "agent_id": agent_id,
                    "scores": scores,
                    "required_capabilities": required,
                    "gaps": gaps,
                }
            )
