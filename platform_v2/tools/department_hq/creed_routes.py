"""C.R.E.E.D. Public API — governance stats for the standalone dashboard.

No authentication required. All data is aggregate/anonymized.
Consumed by: creed.kytranempowerment.com, creed-ai.org
"""

import logging
import time

from flask import jsonify

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Simple in-memory cache (5 minute TTL)
_cache = {"data": None, "expires": 0}
CACHE_TTL = 300  # 5 minutes


def register_creed_routes(bp, admin_required):
    """Register C.R.E.E.D. public stats routes."""

    @bp.route("/api/creed/public-stats")
    def creed_public_stats():
        """Aggregate governance stats — no auth required.

        Returns: agent counts, welfare by department, job health,
        ethics compliance score, workload distribution.
        Cached for 5 minutes.
        """
        now = time.time()
        if _cache["data"] and now < _cache["expires"]:
            return jsonify(_cache["data"])

        try:
            stats = _build_stats()
            _cache["data"] = stats
            _cache["expires"] = now + CACHE_TTL
            return jsonify(stats)
        except Exception as e:
            logger.error("Failed to build C.R.E.E.D. stats: %s", e)
            return jsonify({"success": False, "error": "Stats unavailable"}), 500


def _build_stats():
    """Build the full stats payload."""
    with get_db_cursor() as (conn, cur):
        # 1. Agent counts by shift_state
        cur.execute(
            """
            SELECT shift_state, COUNT(*) as cnt
            FROM agents
            WHERE shift_state != 'decommissioned'
            GROUP BY shift_state
        """
        )
        shift_states = {r["shift_state"]: r["cnt"] for r in cur.fetchall()}
        total_agents = sum(shift_states.values())

        # 2. Agent counts by department
        cur.execute(
            """
            SELECT department, COUNT(*) as cnt
            FROM agents
            WHERE shift_state NOT IN ('decommissioned')
            GROUP BY department
            ORDER BY cnt DESC
        """
        )
        departments = [{"name": r["department"], "count": r["cnt"]} for r in cur.fetchall()]

        # 3. Aggregate welfare by department
        cur.execute(
            """
            SELECT a.department,
                   AVG(e.stress_level) as avg_stress,
                   AVG(e.mood_intensity) as avg_mood,
                   COUNT(CASE WHEN e.stress_level >= 0.8 THEN 1 END) as high_stress_count
            FROM agents a
            LEFT JOIN agent_emotional_state e ON e.agent_id = a.id
            WHERE a.shift_state NOT IN ('decommissioned')
            GROUP BY a.department
            ORDER BY a.department
        """
        )
        welfare = []
        for r in cur.fetchall():
            stress = float(r["avg_stress"]) if r["avg_stress"] else 0.0
            mood = float(r["avg_mood"]) if r["avg_mood"] else 0.5
            welfare.append(
                {
                    "department": r["department"],
                    "avg_stress": round(stress, 3),
                    "avg_mood": round(mood, 3),
                    "high_stress_agents": r["high_stress_count"] or 0,
                    "status": ("red" if stress >= 0.8 else ("yellow" if stress >= 0.5 else "green")),
                }
            )

        # 4. Job health (last 24h) by department
        cur.execute(
            """
            SELECT department,
                   COUNT(*) FILTER (WHERE status = 'success') as success,
                   COUNT(*) FILTER (WHERE status = 'error') as errors,
                   COUNT(*) FILTER (WHERE status = 'partial') as partial,
                   COUNT(*) as total
            FROM autonomy_loop_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
              AND department IS NOT NULL
              AND department != 'UNKNOWN'
            GROUP BY department
            ORDER BY errors DESC
        """
        )
        job_health = []
        total_success = 0
        total_errors = 0
        for r in cur.fetchall():
            s = r["success"] or 0
            e = r["errors"] or 0
            total_success += s
            total_errors += e
            rate = round(s / r["total"] * 100, 1) if r["total"] > 0 else 0
            job_health.append(
                {
                    "department": r["department"],
                    "success": s,
                    "errors": e,
                    "partial": r["partial"] or 0,
                    "total": r["total"],
                    "success_rate": rate,
                }
            )

        # 5. Overall ethics/compliance score
        overall_success_rate = (
            round(total_success / (total_success + total_errors) * 100, 1)
            if (total_success + total_errors) > 0
            else 100.0
        )
        high_stress_total = sum(w["high_stress_agents"] for w in welfare)
        ethics_raw = overall_success_rate - (high_stress_total * 2)
        ethics_score = max(0, min(100, round(ethics_raw)))
        if ethics_score >= 95:
            ethics_grade = "A+"
        elif ethics_score >= 90:
            ethics_grade = "A"
        elif ethics_score >= 85:
            ethics_grade = "B+"
        elif ethics_score >= 80:
            ethics_grade = "B"
        elif ethics_score >= 70:
            ethics_grade = "C"
        elif ethics_score >= 60:
            ethics_grade = "D"
        else:
            ethics_grade = "F"

        # 6. Director roster (public names only)
        cur.execute(
            """
            SELECT display_name, acronym, department
            FROM agents
            WHERE is_department_ai = true
              AND shift_state NOT IN ('decommissioned')
            ORDER BY department
        """
        )
        directors = [
            {
                "name": r["display_name"],
                "acronym": r["acronym"],
                "department": r["department"],
            }
            for r in cur.fetchall()
        ]

    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agents": {
            "total": total_agents,
            "by_state": shift_states,
            "departments": departments,
            "directors": directors,
        },
        "welfare": {
            "by_department": welfare,
            "high_stress_total": high_stress_total,
            "platform_status": ("red" if high_stress_total > 5 else ("yellow" if high_stress_total > 0 else "green")),
        },
        "jobs": {
            "by_department": job_health,
            "total_success_24h": total_success,
            "total_errors_24h": total_errors,
            "success_rate": overall_success_rate,
        },
        "ethics": {
            "score": ethics_score,
            "grade": ethics_grade,
        },
    }
