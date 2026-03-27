"""GET /api/spending — spending records search."""
from flask import Blueprint, jsonify, request
from db import get_db

spending_bp = Blueprint("spending", __name__)


@spending_bp.route("/api/spending")
def get_spending():
    conn = get_db()
    try:
        clauses = ["1=1"]
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

        fiscal_year = request.args.get("fiscal_year")
        if fiscal_year:
            clauses.append("fiscal_year = ?")
            params.append(fiscal_year)

        category = request.args.get("category")
        if category:
            clauses.append("category = ?")
            params.append(category)

        min_amount = request.args.get("min_amount")
        if min_amount:
            clauses.append("amount >= ?")
            params.append(float(min_amount))

        limit = min(int(request.args.get("limit", 50)), 500)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM spending_records WHERE {where} "
            f"ORDER BY amount DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
