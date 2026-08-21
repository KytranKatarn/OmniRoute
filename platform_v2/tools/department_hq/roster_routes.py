"""
Department HQ — Roster routes

Endpoints:
  GET  /api/roster         — All agents with filters (?department=, ?floor=, ?shift_state=, ?search=)
  POST /api/roster/assign  — Reassign agent to department {agent_id, department}
  POST /api/roster/shift   — Change shift state {agent_id, shift_state}

Public directory endpoints moved to /api/public/directory (public_api.py +
services/public_roster_service.py). Migration 332.

Uses the centralized agent_service for all agent operations.
"""

from flask import jsonify, request
from services.agent_service import (
    list_agents,
    count_agents,
    get_agent,
    update_agent,
    DEPARTMENT_FLOOR_MAP,
    VALID_SHIFT_STATES,
)
from database import get_db_cursor

VALID_DEPARTMENTS = set(DEPARTMENT_FLOOR_MAP.keys())


def _as_json_number(value):
    """Cast a DB numeric value (psycopg2 returns DECIMAL columns as
    decimal.Decimal, which Flask's jsonify serializes as a STRING) to a
    real JSON number, for columns the roster UI sorts numerically
    (performance_score, success_rate).

    NULL MUST survive as None — 17 of 140 agents have never been scored,
    and coercing None to 0.0 would render them as the fleet's WORST
    performers (a fabricated finding). Only cast when the value is present.
    """
    return float(value) if value is not None else None


def _compute_wellness(stress, mood):
    """Compute wellness badge color from stress_level and mood_intensity."""
    if stress is None and mood is None:
        return "green"
    s = float(stress) if stress is not None else 0.2
    m = float(mood) if mood is not None else 0.5
    if s >= 0.8 or m <= 0.1:
        return "red"
    if s >= 0.5 or m <= 0.3:
        return "yellow"
    return "green"


def _fetch_wellness_map():
    """Fetch latest emotional state per agent, return {agent_id: {wellness_status, stress_level}}."""
    wellness = {}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT ON (agent_id)
                    agent_id, stress_level, mood_intensity
                FROM agent_emotional_state
                ORDER BY agent_id, timestamp DESC
                """
            )
            for row in cur.fetchall():
                aid = row["agent_id"]
                stress = row["stress_level"]
                mood = row["mood_intensity"]
                wellness[aid] = {
                    "wellness_status": _compute_wellness(stress, mood),
                    "stress_level": float(stress) if stress is not None else 0.0,
                }
    except Exception:
        pass  # If table missing or query fails, all agents default to green
    return wellness


def _apply_bulk_shift(agent_ids, shift_state):
    """Apply a shift change to N agents, reporting EACH outcome.

    An aggregate-only count is what makes a half-applied batch read as a
    success. One agent's failure never aborts the others.
    """
    results = []
    for agent_id in agent_ids:
        try:
            agent = get_agent(agent_id)
            if not agent:
                results.append({"agent_id": agent_id, "name": None, "ok": False, "error": "Agent not found"})
                continue
            previous = agent["shift_state"]
            update_agent(agent_id, shift_state=shift_state)
            results.append({"agent_id": agent_id, "name": agent["name"], "ok": True, "previous": previous})
        except Exception as e:
            results.append({"agent_id": agent_id, "name": None, "ok": False, "error": str(e)})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "failed_count": len(results) - ok}


def register_roster_routes(bp, admin_required):
    """Register roster management routes on the blueprint."""

    @bp.route("/api/roster")
    @admin_required
    def api_roster():
        """List agents with optional filters."""
        limit = min(int(request.args.get("limit", 200)), 500)
        offset = int(request.args.get("offset", 0))

        try:
            filters = dict(
                department=request.args.get("department"),
                floor=request.args.get("floor"),
                shift_state=request.args.get("shift_state"),
                worker_type=request.args.get("worker_type"),
                search=request.args.get("search", "").strip() or None,
            )

            # Fetch all matching agents via service (service handles filtering)
            all_agents = list_agents(limit=limit + offset, **filters)  # fetch enough for offset pagination

            # True total via COUNT(*) with the SAME filters as list_agents —
            # both go through _agent_filter_sql so they can never disagree
            # (spec A §8; the decommissioned-exclusion in #5706 is enforced
            # there too, so no separate Python-side filter is needed here).
            total = count_agents(**filters)

            agents = all_agents[offset : offset + limit]

            # Fetch wellness data for all agents
            wellness_map = _fetch_wellness_map()

            # Trim to the fields the original endpoint returned
            trimmed = []
            for a in agents:
                w = wellness_map.get(a["id"], {})
                trimmed.append(
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "display_name": a["display_name"],
                        "department": a["department"],
                        "floor": a["floor"],
                        "is_department_ai": a["is_department_ai"],
                        "shift_state": a["shift_state"],
                        "model": a["model"],
                        "status": a["status"],
                        "title": a.get("title"),
                        "acronym": a.get("acronym"),
                        "acronym_expansion": a.get("acronym_expansion"),
                        "avatar_url": a.get("avatar_url"),
                        "avatar_updated_at": a.get("updated_at").isoformat() if a.get("updated_at") else None,
                        "bio": a.get("bio"),
                        "worker_type": a.get("worker_type"),
                        # DECIMAL columns come back from psycopg2 as
                        # decimal.Decimal, which jsonify serializes as a
                        # STRING ("99.98"), not a JSON number — the roster's
                        # ascending/descending sort then compares them
                        # lexicographically ("100.00" < "5.50" < "99.98"),
                        # silently returning the wrong "worst performer".
                        # _as_json_number() casts to a real float and keeps
                        # NULL as NULL (never coerced to 0 — see its
                        # docstring for why that would fabricate a finding).
                        "performance_score": _as_json_number(a.get("performance_score")),
                        "success_rate": _as_json_number(a.get("success_rate")),
                        "total_tasks_completed": a.get("total_tasks_completed"),
                        "wellness_status": w.get("wellness_status", "green"),
                        "stress_level": w.get("stress_level", 0.0),
                    }
                )

            # Add coordinator reservation status
            try:
                from services.department_coordinator import get_coordinator

                reserved = get_coordinator()._reserved_agents
                for agent in trimmed:
                    agent["is_reserved"] = agent.get("id") in reserved
            except Exception:
                pass

            return jsonify(
                {
                    "agents": trimmed,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/roster/assign", methods=["POST"])
    @admin_required
    def api_roster_assign():
        """Reassign an agent to a different department."""
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        department = data.get("department")

        if not agent_id or not department:
            return jsonify({"error": "agent_id and department are required"}), 400
        if department not in VALID_DEPARTMENTS:
            return jsonify({"error": f"Invalid department: {department}"}), 400

        try:
            # Verify agent exists
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            # update_agent auto-derives floor from department
            update_agent(agent_id, department=department)

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} reassigned to {department}",
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/roster/shift", methods=["POST"])
    @admin_required
    def api_roster_shift():
        """Change an agent's shift state."""
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        shift_state = data.get("shift_state")

        if not agent_id or not shift_state:
            return jsonify({"error": "agent_id and shift_state are required"}), 400
        if shift_state not in VALID_SHIFT_STATES:
            return jsonify({"error": f"Invalid shift_state: {shift_state}. Valid: {sorted(VALID_SHIFT_STATES)}"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            previous = agent["shift_state"]
            update_agent(agent_id, shift_state=shift_state)

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} shift changed to {shift_state}",
                    "previous": previous,
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/roster/bulk-shift", methods=["POST"])
    @admin_required
    def api_roster_bulk_shift():
        """Change shift state for multiple agents, reporting each outcome."""
        data = request.get_json(silent=True) or {}
        agent_ids = data.get("agent_ids") or []
        shift_state = data.get("shift_state")
        if not agent_ids or not shift_state:
            return jsonify({"error": "agent_ids and shift_state are required"}), 400
        if shift_state not in VALID_SHIFT_STATES:
            return jsonify({"error": f"Invalid shift_state: {shift_state}"}), 400
        if len(agent_ids) > 100:
            return jsonify({"error": "Refusing a batch over 100 agents"}), 400
        out = _apply_bulk_shift(agent_ids, shift_state)
        out["success"] = True
        return jsonify(out)

    @bp.route("/api/coordinator/status")
    @admin_required
    def api_coordinator_status():
        """Live coordinator status — reserved agents, loaded models, RAM."""
        from services.department_coordinator import get_coordinator

        coordinator = get_coordinator()
        status = coordinator.get_status()
        return jsonify({"success": True, **status})

    @bp.route("/api/roster/agent", methods=["POST"])
    @admin_required
    def api_roster_create_agent():
        """Create a new agent via the full lifecycle (fields + skills + side effects)."""
        from services.agent_lifecycle import create_agent_full

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"ok": False, "error": "request body must be a JSON object"}), 400

        fields = data.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        skills = data.get("skills")
        if not isinstance(skills, list):
            skills = []
        side_effects = data.get("side_effects")
        if not isinstance(side_effects, dict):
            side_effects = {}

        for required in ("name", "display_name", "department", "model"):
            if not fields.get(required):
                return jsonify({"ok": False, "error": "%s is required" % required}), 400
        if fields["department"] not in VALID_DEPARTMENTS:
            return jsonify({"ok": False, "error": "Invalid department: %s" % fields["department"]}), 400
        if fields.get("worker_type") not in ("ai", "internal", "contractor"):
            return jsonify({"ok": False, "error": "worker_type must be ai, internal or contractor"}), 400
        if not skills:
            return jsonify({"ok": False, "error": "At least one skill is required"}), 400

        try:
            out = create_agent_full(fields, skills, side_effects)
            return (jsonify(out), 201) if out["ok"] else (jsonify(out), 400)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
