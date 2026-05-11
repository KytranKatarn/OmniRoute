"""Revenue Sprint standup counter — reads/writes system_config, no migration."""

import json
from datetime import date, timedelta

from flask import jsonify, render_template, request
from flask_login import login_required, current_user

from tools.revenue_standup import revenue_standup_bp
from database import get_db_cursor


def _key(d: date) -> str:
    return f"revenue_standup_{d.isoformat()}"


def _read(d: date) -> dict:
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT value FROM system_config WHERE key = %s", (_key(d),))
        row = cur.fetchone()
    if row:
        try:
            return json.loads(row["value"])
        except Exception:
            return {}
    return {"leads": 0, "demos_sched": 0, "demos_done": 0, "contracts": 0, "notes": ""}


def _write(d: date, data: dict) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO system_config (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (_key(d), json.dumps(data)),
        )


@revenue_standup_bp.route("/")
@login_required
def index():
    if not current_user.is_admin:
        return "Admin only", 403
    today = date.today()
    days = []
    for i in range(7):
        d = today - timedelta(days=i)
        row = _read(d)
        row["date"] = d.isoformat()
        row["is_today"] = d == today
        days.append(row)
    return render_template("tools/revenue_standup.html", today=_read(today), history=days)


@revenue_standup_bp.route("/api/standup", methods=["GET"])
@login_required
def get_standup():
    if not current_user.is_admin:
        return jsonify({"error": "Admin only"}), 403
    d = date.today()
    return jsonify({"success": True, "date": d.isoformat(), "data": _read(d)})


@revenue_standup_bp.route("/api/standup", methods=["POST"])
@login_required
def update_standup():
    if not current_user.is_admin:
        return jsonify({"error": "Admin only"}), 403
    body = request.get_json(silent=True) or {}
    d_str = body.get("date", date.today().isoformat())
    try:
        d = date.fromisoformat(d_str)
    except ValueError:
        d = date.today()
    current = _read(d)
    for field in ("leads", "demos_sched", "demos_done", "contracts"):
        if field in body:
            current[field] = max(0, int(body[field]))
    if "notes" in body:
        current["notes"] = str(body["notes"])[:500]
    _write(d, current)
    return jsonify({"success": True, "date": d.isoformat(), "data": current})
