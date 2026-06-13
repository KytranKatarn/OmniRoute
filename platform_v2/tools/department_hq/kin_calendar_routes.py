"""Department HQ — K.I.N. Shift Calendar endpoint (reactive state-timeline).

Per-agent shift state over a day, for the UI to assemble into an hour grid, from:
- shift_state_history  — deliberate transitions (migration 433),
- agents.shift_state   — current state (fallback before history accumulates),
- agent_rest_cycles    — the complete rest record (rest→active is reconstructable here),
- welfare:hardware_rest_window (system_config) — advisory 8PM-6AM ET band.

Owner decision 2026-06-13: reactive timeline (agents are wake-on-demand; no planned
roster), hardware-rest window advisory (not dispatcher-enforced).
"""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request
from database import get_db_cursor

_TZ = ZoneInfo("America/Toronto")


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def register_kin_calendar_routes(bp, admin_required):
    """Register the K.I.N. shift-calendar route."""

    @bp.route("/api/kin/shift-calendar")
    @admin_required
    def api_kin_shift_calendar():
        """Per-agent state timeline for a day (default today, America/Toronto)."""
        date_str = request.args.get("date")
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(_TZ).date()
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400

        day_start = datetime(day.year, day.month, day.day, tzinfo=_TZ)
        day_end = day_start + timedelta(days=1)
        ds = day_start.astimezone(timezone.utc)
        de = day_end.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        is_today = day == datetime.now(_TZ).date()

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, name, department, shift_state
                FROM agents
                WHERE worker_type = 'ai' AND status <> 'decommissioned'
                ORDER BY department, name
                """
            )
            agents = cur.fetchall() or []

            # Deliberate transitions within the day (cooldown/off_duty/barracked/manual);
            # reaper rest->active is covered by agent_rest_cycles below.
            cur.execute(
                """
                SELECT agent_id, from_state, to_state, reason, changed_at
                FROM shift_state_history
                WHERE changed_at >= %s AND changed_at < %s
                ORDER BY agent_id, changed_at
                """,
                (ds, de),
            )
            hist = {}
            for r in cur.fetchall() or []:
                hist.setdefault(r["agent_id"], []).append(
                    {
                        "at": _iso(r["changed_at"]),
                        "from": r["from_state"],
                        "to": r["to_state"],
                        "reason": r["reason"],
                    }
                )

            # Rest windows overlapping the day (open rests use NOW() as the end).
            cur.execute(
                """
                SELECT agent_id, started_at, ended_at, rest_type
                FROM agent_rest_cycles
                WHERE started_at < %s AND COALESCE(ended_at, NOW()) > %s
                ORDER BY agent_id, started_at
                """,
                (de, ds),
            )
            rests = {}
            for r in cur.fetchall() or []:
                rests.setdefault(r["agent_id"], []).append(
                    {
                        "start": _iso(r["started_at"]),
                        "end": _iso(r["ended_at"]),
                        "type": r["rest_type"],
                    }
                )

            # Interval-union compute hours — only meaningful for the current day.
            hours_map = {}
            if is_today:
                try:
                    from services.agent_load_service import real_compute_hours_today

                    for rec in real_compute_hours_today(cur).values():
                        hours_map[rec["agent_id"]] = round(rec.get("hours", 0) or 0, 1)
                except Exception:
                    pass

            cur.execute("SELECT value FROM system_config WHERE key = 'welfare:hardware_rest_window'")
            hw_row = cur.fetchone()

        hardware_rest = None
        if hw_row and hw_row["value"]:
            hardware_rest = hw_row["value"] if isinstance(hw_row["value"], dict) else json.loads(hw_row["value"])

        out = [
            {
                "id": a["id"],
                "name": a["name"],
                "department": a["department"],
                "current_state": a["shift_state"],
                "transitions": hist.get(a["id"], []),
                "rests": rests.get(a["id"], []),
                "hours_today": hours_map.get(a["id"]),
            }
            for a in agents
        ]

        return jsonify(
            {
                "date": day.isoformat(),
                "tz": "America/Toronto",
                "day_start": _iso(ds),
                "day_end": _iso(de),
                "now": _iso(now),
                "is_today": is_today,
                "hardware_rest": hardware_rest,
                "agents": out,
            }
        )
