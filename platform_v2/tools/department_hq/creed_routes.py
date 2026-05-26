"""C.R.E.E.D. Public API — governance stats for the standalone dashboard.

No authentication required except /api/creed/audit-export (admin only).
All data is aggregate/anonymised unless explicitly noted.
Consumed by: creed.kytranempowerment.com, creed-ai.org
"""

import csv
import io
import json
import logging
import time

from flask import jsonify, request

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ── Cache singletons ─────────────────────────────────────────────────────────
_cache = {"data": None, "expires": 0}
CACHE_TTL = 300  # 5 min

_fleet_cache = {"data": None, "expires": 0}
FLEET_CACHE_TTL = 60  # 60 s

_overflow_cache = {"data": None, "expires": 0}
OVERFLOW_CACHE_TTL = 30  # 30 s

_trend_cache: dict = {}  # keyed by days int → {"data": ..., "expires": float}
TREND_CACHE_TTL = 300  # 5 min

# Welfare thresholds
_TOKEN_DAY_LIMIT = 100_000


# ── Route registration ────────────────────────────────────────────────────────


def register_creed_routes(bp, admin_required):
    """Register all C.R.E.E.D. public API routes."""

    @bp.route("/api/creed/public-stats")
    def creed_public_stats():
        """Aggregate governance stats — no auth required.
        Returns agent counts, welfare by department, job health,
        ethics score (global + per-department), welfare blocks honored,
        rest compliance, workload distribution.  Cached 5 min.
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

        Each agent now includes welfare_score (0-100):
          (1-stress)*40 + energy*30 + (30 if tokens_24h <= 100k else 0)
        Cached 60 s.  No auth required.
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
        """Last 50 overflow skill governance events.  Cached 30 s.  No auth."""
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

    @bp.route("/api/creed/ethics-trend")
    def creed_ethics_trend():
        """Per-department ethics score history for sparkline charts.

        Query param: ?days=30 (default 30, min 7, max 90).
        Returns list of {snapshot_date, department, score, grade, avg_stress}.
        Cached 5 min per days value.  No auth required.
        """
        days = request.args.get("days", 30, type=int)
        days = min(max(days, 7), 90)
        now = time.time()
        cached = _trend_cache.get(days)
        if cached and now < cached["expires"]:
            return jsonify(cached["data"])
        try:
            data = _build_ethics_trend(days)
            _trend_cache[days] = {"data": data, "expires": now + TREND_CACHE_TTL}
            return jsonify(data)
        except Exception as e:
            logger.error("Failed to build ethics trend: %s", e)
            return jsonify({"success": False, "error": "Trend data unavailable"}), 500

    @bp.route("/api/creed/audit-export")
    @admin_required
    def creed_audit_export():
        """Export governance_audit_log + ethics snapshots for a date range.

        Query params:
          start   — ISO date (default: 30 days ago)
          end     — ISO date (default: today)
          format  — 'json' (default) or 'csv'

        Admin auth required — contains raw governance event data.
        """
        start = request.args.get("start", "")
        end = request.args.get("end", "")
        fmt = request.args.get("format", "json").lower()
        try:
            data = _build_audit_export(start or None, end or None)
            if fmt == "csv":
                return _audit_export_csv(data)
            return jsonify(data)
        except Exception as e:
            logger.error("Failed to build audit export: %s", e)
            return jsonify({"success": False, "error": "Export failed"}), 500

    @bp.route("/api/creed/governance-report-data")
    def creed_governance_report_data():
        """Latest quarterly governance report data for the standalone renderer.

        Query param: ?quarter=2026-Q2 (default: latest available).
        No auth — aggregate summary data only.
        """
        quarter = request.args.get("quarter", "")
        try:
            data = _build_governance_report_data(quarter or None)
            return jsonify(data)
        except Exception as e:
            logger.error("Failed to build governance report data: %s", e)
            return jsonify({"success": False, "error": "Report unavailable"}), 500


# ── Fleet agents ─────────────────────────────────────────────────────────────


def _build_fleet_agents():
    """Build fleet agent roster grouped by node.

    Each agent includes welfare_score = (1-stress)*40 + energy*30 +
    (30 if 24h tokens <= 100k else 0).
    """
    tok_subquery = """
        LEFT JOIN (
            SELECT agent_id, COALESCE(SUM(tokens_used), 0) AS tokens_24h
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY agent_id
        ) tok ON tok.agent_id = a.id
    """

    with get_db_cursor() as (conn, cur):
        # Fleet agents (stationed on remote nodes)
        cur.execute(
            f"""
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
                   COUNT(os.id)                                     AS total_overflow_bids,
                   COALESCE(tok.tokens_24h, 0)                     AS tokens_24h
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
            {tok_subquery}
            WHERE a.worker_type = 'ai'
              AND na.status = 'active'
            GROUP BY a.id, rn.node_name, rn.mesh_ip,
                     ae.stress_level, ae.energy_level, ae.current_mood,
                     tok.tokens_24h
            ORDER BY rn.node_name, a.department
            """
        )
        fleet_rows = cur.fetchall() or []

        # Hub-only AI agents
        cur.execute(
            f"""
            SELECT a.id, a.name, a.display_name, a.department, a.shift_state,
                   COALESCE(ae.stress_level, 0.0) AS stress_level,
                   COALESCE(ae.energy_level, 0.8) AS energy_level,
                   ae.current_mood,
                   EXISTS(
                       SELECT 1 FROM agent_rest_cycles rc
                       WHERE rc.agent_id = a.id AND rc.ended_at IS NULL
                   ) AS in_rest,
                   COUNT(os.id) FILTER (WHERE os.enabled = TRUE) AS active_overflow_bids,
                   COUNT(os.id)                                    AS total_overflow_bids,
                   COALESCE(tok.tokens_24h, 0)                    AS tokens_24h
            FROM agents a
            LEFT JOIN (
                SELECT DISTINCT ON (agent_id)
                       agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
                ORDER BY agent_id, id DESC
            ) ae ON ae.agent_id = a.id
            LEFT JOIN agent_overflow_skills os ON os.agent_id = a.id
            {tok_subquery}
            WHERE a.worker_type = 'ai'
              AND a.shift_state NOT IN ('decommissioned')
              AND a.id NOT IN (
                  SELECT hub_agent_id FROM node_agents WHERE status = 'active'
              )
            GROUP BY a.id, ae.stress_level, ae.energy_level, ae.current_mood,
                     tok.tokens_24h
            ORDER BY a.department
            """
        )
        hub_rows = cur.fetchall() or []

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
                "avg_welfare_score": 0.0,
                "active_overflow_bids": 0,
                "status": "green",
            }
        stress = float(row["stress_level"])
        energy = float(row["energy_level"])
        tokens_24h = int(row.get("tokens_24h") or 0)
        not_overloaded = tokens_24h <= _TOKEN_DAY_LIMIT
        welfare_score = round((1 - stress) * 40 + energy * 30 + (30 if not_overloaded else 0))
        nodes[node_name]["agents"].append(
            {
                "id": row["id"],
                "name": row["name"],
                "display_name": row["display_name"],
                "department": row["department"],
                "shift_state": row["shift_state"],
                "stress_level": round(stress, 3),
                "energy_level": round(energy, 3),
                "current_mood": row["current_mood"],
                "in_rest": bool(row["in_rest"]),
                "active_overflow_bids": row["active_overflow_bids"] or 0,
                "total_overflow_bids": row["total_overflow_bids"] or 0,
                "tokens_24h": tokens_24h,
                "welfare_score": welfare_score,
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

    node_list = []
    for nd in nodes.values():
        if nd["agents"]:
            nd["avg_stress"] = round(sum(a["stress_level"] for a in nd["agents"]) / len(nd["agents"]), 3)
            nd["avg_welfare_score"] = round(sum(a["welfare_score"] for a in nd["agents"]) / len(nd["agents"]), 1)
        avg = nd["avg_stress"]
        nd["status"] = "red" if avg >= 0.7 else ("yellow" if avg >= 0.4 else "green")
        node_list.append(nd)

    node_list.sort(key=lambda n: (0 if n["node_name"] == "hub" else 1, n["node_name"]))

    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nodes": node_list,
        "total_nodes": len(node_list),
        "total_agents": sum(len(n["agents"]) for n in node_list),
    }


# ── Overflow activations ─────────────────────────────────────────────────────


def _build_overflow_activations():
    """Return last 50 overflow governance events from audit log."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT gal.id, gal.event_type, gal.agent_id,
                   a.name AS agent_name, a.display_name,
                   gal.old_value, gal.new_value,
                   gal.reason, gal.outcome, gal.timestamp
            FROM governance_audit_log gal
            LEFT JOIN agents a ON a.id = gal.agent_id
            WHERE gal.event_type IN (
                'overflow_skill_activated', 'overflow_skill_deactivated',
                'overflow_welfare_blocked', 'overflow_mass_activation'
            )
            ORDER BY gal.timestamp DESC
            LIMIT 50
            """
        )
        rows = cur.fetchall() or []

    events = [
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
        for r in rows
    ]

    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "events": events,
        "count": len(events),
    }


# ── Ethics trend ─────────────────────────────────────────────────────────────


def _build_ethics_trend(days: int = 30):
    """Return per-department ethics score history for sparkline rendering."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT snapshot_date::text, department, score, grade,
                   avg_stress, welfare_status
            FROM creed_ethics_snapshots
            WHERE snapshot_date >= CURRENT_DATE - (%s || ' days')::interval
            ORDER BY snapshot_date, department
            """,
            (str(days),),
        )
        rows = cur.fetchall() or []

        # Department list for context
        cur.execute(
            """
            SELECT DISTINCT department FROM creed_ethics_snapshots
            ORDER BY department
            """
        )
        dept_rows = cur.fetchall() or []

    snapshots = [
        {
            "date": r["snapshot_date"],
            "department": r["department"],
            "score": r["score"],
            "grade": r["grade"],
            "avg_stress": float(r["avg_stress"]),
            "welfare_status": r["welfare_status"],
        }
        for r in rows
    ]

    # Group by department for convenience
    by_dept: dict = {}
    for s in snapshots:
        by_dept.setdefault(s["department"], []).append(s)

    departments = [r["department"] for r in dept_rows]

    return {
        "success": True,
        "days": days,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "snapshots": snapshots,
        "by_department": by_dept,
        "departments": departments,
        "total_snapshots": len(snapshots),
    }


# ── Audit export ─────────────────────────────────────────────────────────────


def _build_audit_export(start: str | None = None, end: str | None = None):
    """Return governance_audit_log + ethics snapshots for a date range."""
    with get_db_cursor() as (conn, cur):
        # Governance events
        cur.execute(
            """
            SELECT gal.id, gal.event_type, gal.event_category, gal.action,
                   gal.agent_id, a.name AS agent_name, gal.target_table,
                   gal.reason, gal.outcome,
                   gal.old_value, gal.new_value,
                   gal.timestamp::text AS ts
            FROM governance_audit_log gal
            LEFT JOIN agents a ON a.id = gal.agent_id
            WHERE (%(start)s IS NULL OR gal.timestamp::date >= %(start)s::date)
              AND (%(end)s   IS NULL OR gal.timestamp::date <= %(end)s::date)
            ORDER BY gal.timestamp DESC
            LIMIT 5000
            """,
            {"start": start, "end": end},
        )
        events = [dict(r) for r in (cur.fetchall() or [])]

        # Ethics snapshots
        cur.execute(
            """
            SELECT snapshot_date::text, department, score, grade,
                   success_rate, high_stress_agents, avg_stress, welfare_status
            FROM creed_ethics_snapshots
            WHERE (%(start)s IS NULL OR snapshot_date >= %(start)s::date)
              AND (%(end)s   IS NULL OR snapshot_date <= %(end)s::date)
            ORDER BY snapshot_date DESC, department
            """,
            {"start": start, "end": end},
        )
        snapshots = [dict(r) for r in (cur.fetchall() or [])]

    # Sanitise non-serialisable values
    for ev in events:
        for k in ("old_value", "new_value"):
            v = ev.get(k)
            if v is not None and not isinstance(v, (str, int, float, bool)):
                ev[k] = json.dumps(v)

    return {
        "success": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start": start,
        "end": end,
        "governance_events": events,
        "ethics_snapshots": snapshots,
        "event_count": len(events),
        "snapshot_count": len(snapshots),
    }


def _audit_export_csv(data: dict):
    """Convert audit export data to CSV download response."""
    from flask import make_response

    output = io.StringIO()
    w = csv.writer(output)

    # Section 1: governance events
    w.writerow(["# GOVERNANCE EVENTS"])
    w.writerow(
        [
            "id",
            "timestamp",
            "event_type",
            "event_category",
            "action",
            "agent_id",
            "agent_name",
            "target_table",
            "reason",
            "outcome",
        ]
    )
    for ev in data.get("governance_events", []):
        w.writerow(
            [
                ev.get("id"),
                ev.get("ts"),
                ev.get("event_type"),
                ev.get("event_category"),
                ev.get("action"),
                ev.get("agent_id"),
                ev.get("agent_name"),
                ev.get("target_table"),
                ev.get("reason"),
                ev.get("outcome"),
            ]
        )

    w.writerow([])
    w.writerow(["# ETHICS SNAPSHOTS"])
    w.writerow(
        [
            "snapshot_date",
            "department",
            "score",
            "grade",
            "success_rate",
            "high_stress_agents",
            "avg_stress",
            "welfare_status",
        ]
    )
    for sn in data.get("ethics_snapshots", []):
        w.writerow(
            [
                sn.get("snapshot_date"),
                sn.get("department"),
                sn.get("score"),
                sn.get("grade"),
                sn.get("success_rate"),
                sn.get("high_stress_agents"),
                sn.get("avg_stress"),
                sn.get("welfare_status"),
            ]
        )

    resp = make_response(output.getvalue())
    fname = f"creed-audit-{data.get('start', '')}-{data.get('end', '')}.csv"
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f"attachment; filename={fname}"
    return resp


# ── Governance report data ────────────────────────────────────────────────────


def _build_governance_report_data(quarter: str | None = None):
    """Return the latest (or specified) quarterly governance report from DB cache."""
    with get_db_cursor() as (conn, cur):
        if quarter:
            cur.execute(
                "SELECT quarter, report_json, created_at::text FROM creed_governance_reports " "WHERE quarter = %s",
                (quarter,),
            )
        else:
            cur.execute(
                "SELECT quarter, report_json, created_at::text FROM creed_governance_reports "
                "ORDER BY created_at DESC LIMIT 1"
            )
        row = cur.fetchone()
        if not row:
            # Also return a list of available quarters
            cur.execute("SELECT quarter, created_at::text FROM creed_governance_reports ORDER BY created_at DESC")
            available = [dict(r) for r in (cur.fetchall() or [])]
            return {
                "success": False,
                "error": "No governance report available yet. Reports are generated quarterly.",
                "available_quarters": available,
            }

        # List available quarters
        cur.execute("SELECT quarter, created_at::text FROM creed_governance_reports ORDER BY created_at DESC")
        available = [dict(r) for r in (cur.fetchall() or [])]

    payload = row["report_json"] if isinstance(row["report_json"], dict) else json.loads(row["report_json"])
    return {
        "success": True,
        "quarter": row["quarter"],
        "generated_at": row["created_at"],
        "available_quarters": available,
        "report": payload,
    }


# ── Public stats ─────────────────────────────────────────────────────────────


def _ethics_grade(sc: int) -> str:
    if sc >= 95:
        return "A+"
    if sc >= 90:
        return "A"
    if sc >= 85:
        return "B+"
    if sc >= 80:
        return "B"
    if sc >= 70:
        return "C"
    if sc >= 60:
        return "D"
    return "F"


def _build_stats():
    """Build the full public-stats payload."""
    with get_db_cursor() as (conn, cur):
        # 1. Agent counts by shift_state
        cur.execute(
            """
            SELECT shift_state, COUNT(*) AS cnt
            FROM agents
            WHERE shift_state != 'decommissioned'
            GROUP BY shift_state
            """
        )
        shift_states = {r["shift_state"]: r["cnt"] for r in cur.fetchall()}
        total_agents = sum(shift_states.values())

        # 1b. Agents currently in a rest cycle
        cur.execute("SELECT COUNT(*) AS cnt FROM agent_rest_cycles WHERE ended_at IS NULL")
        in_rest_count = int((cur.fetchone() or {}).get("cnt") or 0)

        # 2. Agent counts by department
        cur.execute(
            """
            SELECT department, COUNT(*) AS cnt
            FROM agents
            WHERE shift_state NOT IN ('decommissioned')
            GROUP BY department
            ORDER BY cnt DESC
            """
        )
        departments = [{"name": r["department"], "count": r["cnt"]} for r in cur.fetchall()]

        # 3. Aggregate welfare by department (LATERAL — avoids time-series fan-out)
        cur.execute(
            """
            SELECT a.department,
                   AVG(ae.stress_level)                                  AS avg_stress,
                   AVG(ae.mood_intensity)                                AS avg_mood,
                   COUNT(CASE WHEN ae.stress_level >= 0.8 THEN 1 END)   AS high_stress_count
            FROM agents a
            JOIN LATERAL (
                SELECT stress_level, mood_intensity
                FROM agent_emotional_state
                WHERE agent_id = a.id
                ORDER BY id DESC LIMIT 1
            ) ae ON true
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
                    "status": "red" if stress >= 0.8 else ("yellow" if stress >= 0.5 else "green"),
                }
            )

        # 3b. Welfare snapshot trend (last 7 days)
        cur.execute(
            """
            SELECT a.name, a.department,
                   ws.flag,
                   COUNT(*) AS flag_days,
                   ROUND(AVG(ws.avg_stress)::numeric, 3) AS avg_stress_trend
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
                   COUNT(*) FILTER (WHERE status = 'success') AS success,
                   COUNT(*) FILTER (WHERE status = 'error')   AS errors,
                   COUNT(*) FILTER (WHERE status = 'partial') AS partial,
                   COUNT(*)                                    AS total
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

        # 5. Welfare blocks honored (last 30 days)
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM governance_audit_log
            WHERE event_type = 'overflow_welfare_blocked'
              AND timestamp > NOW() - INTERVAL '30 days'
            """
        )
        blocks_row = cur.fetchone()
        welfare_blocks_30d = int((blocks_row or {}).get("cnt") or 0)

        # 6. Rest cycle compliance (last 7 days, AI agents not decommissioned/barracked)
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT a.id)      AS total_active,
                COUNT(DISTINCT arc.agent_id) AS completed_rest
            FROM agents a
            LEFT JOIN agent_rest_cycles arc
                   ON arc.agent_id = a.id
                  AND arc.started_at > NOW() - INTERVAL '7 days'
                  AND arc.ended_at IS NOT NULL
            WHERE a.worker_type = 'ai'
              AND a.shift_state NOT IN ('decommissioned', 'barracked')
            """
        )
        rest_row = dict(cur.fetchone() or {})
        total_active_agents = int(rest_row.get("total_active") or 0)
        completed_rest = int(rest_row.get("completed_rest") or 0)
        rest_compliance_pct = round(completed_rest / total_active_agents * 100, 1) if total_active_agents > 0 else 0.0

        # 7. Director roster (public names)
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
            {"name": r["display_name"], "acronym": r["acronym"], "department": r["department"]} for r in cur.fetchall()
        ]

    # 8. Overall ethics score
    overall_success_rate = (
        round(total_success / (total_success + total_errors) * 100, 1) if (total_success + total_errors) > 0 else 100.0
    )
    high_stress_total = sum(w["high_stress_agents"] for w in welfare)
    ethics_raw = overall_success_rate - (high_stress_total * 2)
    ethics_score = max(0, min(100, round(ethics_raw)))
    ethics_grade = _ethics_grade(ethics_score)

    # 9. Per-department ethics breakdown
    welfare_by_dept = {w["department"]: w for w in welfare}
    jobs_by_dept = {j["department"]: j for j in job_health}
    all_depts = set(welfare_by_dept) | set(jobs_by_dept)
    dept_ethics_list = []
    for dept in sorted(all_depts):
        wf = welfare_by_dept.get(dept, {})
        jh = jobs_by_dept.get(dept, {})
        dept_sr = round(jh["success"] / jh["total"] * 100, 1) if jh.get("total", 0) > 0 else 100.0
        dept_hs = wf.get("high_stress_agents", 0)
        dept_raw = dept_sr - (dept_hs * 2)
        dept_score = max(0, min(100, round(dept_raw)))
        dept_ethics_list.append(
            {
                "department": dept,
                "score": dept_score,
                "grade": _ethics_grade(dept_score),
                "success_rate": dept_sr,
                "high_stress_agents": dept_hs,
                "avg_stress": wf.get("avg_stress", 0.0),
                "welfare_status": wf.get("status", "green"),
            }
        )
    dept_ethics_list.sort(key=lambda x: x["score"])  # worst first

    return {
        "success": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agents": {
            "total": total_agents,
            "in_rest": in_rest_count,
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
            "blocks_honored_30d": welfare_blocks_30d,
            "rest_compliance_pct": rest_compliance_pct,
            "rest_compliance_agents": completed_rest,
            "rest_compliance_total": total_active_agents,
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
            "by_department": dept_ethics_list,
        },
    }
