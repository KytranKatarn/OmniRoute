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

# Fleet-agents cache (60s TTL)
_fleet_cache = {"data": None, "expires": 0}
FLEET_CACHE_TTL = 60

# Overflow-activations cache (30s TTL)
_overflow_cache = {"data": None, "expires": 0}
OVERFLOW_CACHE_TTL = 30


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

    @bp.route("/api/creed/fleet-agents")
    def creed_fleet_agents():
        """Fleet-aware agent roster across all cluster nodes + hub.

        Returns agents grouped by node_name with welfare state and overflow bid
        counts.  Hub-only agents use node_name='hub'.  Cached 60s.
        No auth required — aggregate data only.
        """
        now = time.time()
        if _fleet_cache["data"] and now < _fleet_cache["expires"]:
            return jsonify(_fleet_cache["data"])

        try:
            data = _build_fleet_agents()
            _fleet_cache["data"] = data
            _fleet_cache["expires"] = now + FLEET_CACHE_TTL
            return jsonify(data)
        except Exception as e:
            logger.error("Failed to build C.R.E.E.D. fleet-agents: %s", e)
            return jsonify({"success": False, "error": "Fleet data unavailable"}), 500

    @bp.route("/api/creed/overflow-activations")
    def creed_overflow_activations():
        """Last 50 overflow skill governance events from audit log.

        Covers: overflow_skill_activated, overflow_skill_deactivated,
        overflow_welfare_blocked, overflow_mass_activation.
        Cached 30s.  No auth required.
        """
        now = time.time()
        if _overflow_cache["data"] and now < _overflow_cache["expires"]:
            return jsonify(_overflow_cache["data"])

        try:
            data = _build_overflow_activations()
            _overflow_cache["data"] = data
            _overflow_cache["expires"] = now + OVERFLOW_CACHE_TTL
            return jsonify(data)
        except Exception as e:
            logger.error("Failed to build C.R.E.E.D. overflow-activations: %s", e)
            return jsonify({"success": False, "error": "Overflow data unavailable"}), 500


def _build_fleet_agents():
    """Build fleet agent roster grouped by node."""
    with get_db_cursor() as (conn, cur):
        # Fleet agents (stationed on remote nodes)
        # Use DISTINCT ON subquery for emotional state — agent_emotional_state is a
        # time-series table with thousands of rows per agent; joining directly fans out.
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.department, a.shift_state,
                   rn.node_name, rn.mesh_ip,
                   COALESCE(ae.stress_level, 0.0)  AS stress_level,
                   COALESCE(ae.energy_level, 0.8)  AS energy_level,
                   ae.current_mood,
                   EXISTS(
                       SELECT 1 FROM agent_rest_cycles rc
                       WHERE rc.agent_id = a.id AND rc.ended_at IS NULL
                   ) AS in_rest,
                   COUNT(os.id) FILTER (WHERE os.enabled = TRUE)  AS active_overflow_bids,
                   COUNT(os.id)                                     AS total_overflow_bids
            FROM node_agents na
            JOIN agents a ON a.id = na.hub_agent_id
            JOIN remote_nodes rn ON rn.id = na.node_id
            LEFT JOIN (
                SELECT DISTINCT ON (agent_id)
                       agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
                ORDER BY agent_id, id DESC
            ) ae ON ae.agent_id = a.id
            LEFT JOIN agent_overflow_skills os ON os.agent_id = a.id
            WHERE a.worker_type = 'ai'
              AND na.status = 'active'
            GROUP BY a.id, rn.node_name, rn.mesh_ip,
                     ae.stress_level, ae.energy_level, ae.current_mood
            ORDER BY rn.node_name, a.department
        """
        )
        fleet_rows = cur.fetchall() or []

        # Hub-only AI agents (not in node_agents at all)
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.department, a.shift_state,
                   COALESCE(ae.stress_level, 0.0) AS stress_level,
                   COALESCE(ae.energy_level, 0.8) AS energy_level,
                   ae.current_mood,
                   EXISTS(
                       SELECT 1 FROM agent_rest_cycles rc
                       WHERE rc.agent_id = a.id AND rc.ended_at IS NULL
                   ) AS in_rest,
                   COUNT(os.id) FILTER (WHERE os.enabled = TRUE) AS active_overflow_bids,
                   COUNT(os.id)                                    AS total_overflow_bids
            FROM agents a
            LEFT JOIN (
                SELECT DISTINCT ON (agent_id)
                       agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
                ORDER BY agent_id, id DESC
            ) ae ON ae.agent_id = a.id
            LEFT JOIN agent_overflow_skills os ON os.agent_id = a.id
            WHERE a.worker_type = 'ai'
              AND a.shift_state NOT IN ('decommissioned')
              AND a.id NOT IN (
                  SELECT hub_agent_id FROM node_agents WHERE status = 'active'
              )
            GROUP BY a.id, ae.stress_level, ae.energy_level, ae.current_mood
            ORDER BY a.department
        """
        )
        hub_rows = cur.fetchall() or []

    # Group by node
    nodes: dict = {}

    def _add_row(row, node_name, mesh_ip=None):
        if node_name not in nodes:
            nodes[node_name] = {
                "node_name": node_name,
                "mesh_ip": mesh_ip,
                "agents": [],
                "online_count": 0,
                "in_rest_count": 0,
                "avg_stress": 0.0,
                "active_overflow_bids": 0,
                "status": "green",
            }
        stress = float(row["stress_level"])
        nodes[node_name]["agents"].append(
            {
                "id": row["id"],
                "name": row["name"],
                "display_name": row["display_name"],
                "department": row["department"],
                "shift_state": row["shift_state"],
                "stress_level": round(stress, 3),
                "energy_level": round(float(row["energy_level"]), 3),
                "current_mood": row["current_mood"],
                "in_rest": bool(row["in_rest"]),
                "active_overflow_bids": row["active_overflow_bids"] or 0,
                "total_overflow_bids": row["total_overflow_bids"] or 0,
            }
        )
        if row["shift_state"] in ("active", "deployed", "working"):
            nodes[node_name]["online_count"] += 1
        if row["in_rest"]:
            nodes[node_name]["in_rest_count"] += 1
        nodes[node_name]["active_overflow_bids"] += row["active_overflow_bids"] or 0

    for row in fleet_rows:
        _add_row(row, row["node_name"], row["mesh_ip"])
    for row in hub_rows:
        _add_row(row, "hub", "100.64.0.4")

    # Compute avg_stress + color per node
    node_list = []
    for nd in nodes.values():
        if nd["agents"]:
            nd["avg_stress"] = round(sum(a["stress_level"] for a in nd["agents"]) / len(nd["agents"]), 3)
        avg = nd["avg_stress"]
        nd["status"] = "red" if avg >= 0.7 else ("yellow" if avg >= 0.4 else "green")
        node_list.append(nd)

    # Hub first, then alphabetical
    node_list.sort(key=lambda n: (0 if n["node_name"] == "hub" else 1, n["node_name"]))

    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nodes": node_list,
        "total_nodes": len(node_list),
        "total_agents": sum(len(n["agents"]) for n in node_list),
    }


def _build_overflow_activations():
    """Return last 50 overflow governance events from audit log."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT gal.id,
                   gal.event_type,
                   gal.agent_id,
                   a.name        AS agent_name,
                   a.display_name,
                   gal.old_value,
                   gal.new_value,
                   gal.reason,
                   gal.outcome,
                   gal.timestamp
            FROM governance_audit_log gal
            LEFT JOIN agents a ON a.id = gal.agent_id
            WHERE gal.event_type IN (
                'overflow_skill_activated',
                'overflow_skill_deactivated',
                'overflow_welfare_blocked',
                'overflow_mass_activation'
            )
            ORDER BY gal.timestamp DESC
            LIMIT 50
        """
        )
        rows = cur.fetchall() or []

    events = []
    for r in rows:
        events.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "agent_id": r["agent_id"],
                "agent_name": r["agent_name"] or "Unknown",
                "display_name": r["display_name"] or r["agent_name"] or "Unknown",
                "old_value": r["old_value"],
                "new_value": r["new_value"],
                "reason": r["reason"],
                "outcome": r["outcome"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            }
        )

    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "events": events,
        "count": len(events),
    }


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

        # 3b. Welfare snapshot trend (last 7 days) — agents with persistent flags
        cur.execute(
            """
            SELECT a.name, a.department,
                   ws.flag,
                   COUNT(*) as flag_days,
                   ROUND(AVG(ws.avg_stress)::numeric, 3) as avg_stress_trend
            FROM agent_welfare_snapshots ws
            JOIN agents a ON a.id = ws.agent_id
            WHERE ws.snapshot_date >= CURRENT_DATE - INTERVAL '7 days'
              AND ws.flag IS NOT NULL
              AND ws.flag NOT IN ('healthy', 'starving_no_llm')
            GROUP BY a.name, a.department, ws.flag
            HAVING COUNT(*) >= 2
            ORDER BY flag_days DESC, avg_stress_trend DESC
            LIMIT 20
        """
        )
        welfare_alerts = [
            {
                "agent": r["name"],
                "department": r["department"],
                "flag": r["flag"],
                "days_flagged": r["flag_days"],
                "avg_stress_trend": float(r["avg_stress_trend"] or 0),
            }
            for r in cur.fetchall()
        ]

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
            "persistent_alerts": welfare_alerts,
            "persistent_alert_count": len(welfare_alerts),
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
