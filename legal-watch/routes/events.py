"""GET /api/events, /api/stats — legal event feed."""
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

        category = request.args.get("category")
        if category:
            clauses.append("category LIKE ?")
            params.append(f"%{category}%")

        keyword = request.args.get("keyword")
        if keyword:
            clauses.append("(title LIKE ? OR description LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        limit = min(int(request.args.get("limit", 50)), 500)
        offset = int(request.args.get("offset", 0))
        where = " AND ".join(clauses)
        sql = f"SELECT * FROM legal_events WHERE {where} ORDER BY published_date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@events_bp.route("/api/stats")
def get_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM legal_events").fetchone()["c"]
        regs = conn.execute("SELECT COUNT(*) as c FROM regulations").fetchone()["c"]
        news = conn.execute("SELECT COUNT(*) as c FROM legal_events WHERE event_type='news'").fetchone()["c"]
        gazette = conn.execute("SELECT COUNT(*) as c FROM legal_events WHERE event_type='regulation'").fetchone()["c"]
        return jsonify({
            "total_events": total,
            "regulations": regs,
            "legal_news": news,
            "gazette_items": gazette,
        })
    finally:
        conn.close()
