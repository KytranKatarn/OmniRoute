"""GET /api/parliament/* — bills, votes, debates."""
from flask import Blueprint, jsonify, request
from db import get_db

parliament_bp = Blueprint("parliament", __name__)


@parliament_bp.route("/api/parliament/bills")
def get_bills():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        status = request.args.get("status")
        if status:
            clauses.append("status = ?")
            params.append(status)

        keyword = request.args.get("keyword")
        if keyword:
            clauses.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        limit = min(int(request.args.get("limit", 20)), 100)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM parliament_bills WHERE {where} "
            f"ORDER BY last_activity_date DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@parliament_bp.route("/api/parliament/votes")
def get_votes():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        bill = request.args.get("bill")
        if bill:
            clauses.append("bill_number = ?")
            params.append(bill)

        recent = request.args.get("recent")
        if recent == "true":
            clauses.append("vote_date >= date('now', '-30 days')")

        limit = min(int(request.args.get("limit", 20)), 100)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM parliament_votes WHERE {where} "
            f"ORDER BY vote_date DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
