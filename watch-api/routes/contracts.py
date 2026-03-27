"""GET /api/contracts — filtered contract search."""
from flask import Blueprint, jsonify, request
from db import get_db

contracts_bp = Blueprint("contracts", __name__)


@contracts_bp.route("/api/contracts")
def get_contracts():
    conn = get_db()
    try:
        clauses = ["event_type = 'contract'"]
        params = []

        level = request.args.get("level")
        if level:
            clauses.append("level = ?")
            params.append(level)

        jurisdiction = request.args.get("jurisdiction")
        if jurisdiction:
            clauses.append("jurisdiction LIKE ?")
            params.append(f"%{jurisdiction}%")

        department = request.args.get("department")
        if department:
            clauses.append("department LIKE ?")
            params.append(f"%{department}%")

        min_amount = request.args.get("min_amount")
        if min_amount:
            clauses.append("amount >= ?")
            params.append(float(min_amount))

        max_amount = request.args.get("max_amount")
        if max_amount:
            clauses.append("amount <= ?")
            params.append(float(max_amount))

        timespan = request.args.get("timespan", "30d")
        days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(timespan, 30)
        clauses.append(f"event_date >= date('now', '-{days} days')")

        limit = min(int(request.args.get("limit", 50)), 500)
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
