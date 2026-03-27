"""GET /api/events and /api/stats — unified civic event feed."""
from flask import Blueprint, jsonify, request
from db import get_db

events_bp = Blueprint("events", __name__)


@events_bp.route("/api/events")
def get_events():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        event_type = request.args.get("type")
        if event_type:
            types = event_type.split(",")
            placeholders = ",".join("?" for _ in types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(types)

        level = request.args.get("level")
        if level:
            clauses.append("level = ?")
            params.append(level)

        region = request.args.get("region")
        if region:
            clauses.append("(jurisdiction LIKE ? OR jurisdiction LIKE ?)")
            params.extend([f"%{region}%", f"%{region}%"])

        timespan = request.args.get("timespan", "30d")
        days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(timespan, 30)
        clauses.append(f"event_date >= date('now', '-{days} days')")

        limit = min(int(request.args.get("limit", 100)), 500)
        offset = int(request.args.get("offset", 0))

        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM civic_events WHERE {where} "
            f"ORDER BY event_date DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@events_bp.route("/api/stats")
def get_stats():
    conn = get_db()
    try:
        contracts = conn.execute(
            "SELECT COUNT(*) as c FROM civic_events WHERE event_type='contract'"
        ).fetchone()["c"]
        bills_active = conn.execute(
            "SELECT COUNT(*) as c FROM parliament_bills WHERE status NOT IN ('defeated', 'royal_assent')"
        ).fetchone()["c"]
        votes_recent = conn.execute(
            "SELECT COUNT(*) as c FROM parliament_votes WHERE vote_date >= date('now', '-30 days')"
        ).fetchone()["c"]
        spending_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM spending_records"
        ).fetchone()["total"]

        return jsonify({
            "contracts": contracts,
            "bills_active": bills_active,
            "votes_recent": votes_recent,
            "spending_total": spending_total,
        })
    finally:
        conn.close()
