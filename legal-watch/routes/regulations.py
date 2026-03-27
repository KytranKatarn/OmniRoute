"""GET /api/regulations — Canada Gazette regulations."""
from flask import Blueprint, jsonify, request
from db import get_db

regulations_bp = Blueprint("regulations", __name__)


@regulations_bp.route("/api/regulations")
def get_regulations():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        reg_type = request.args.get("type")
        if reg_type:
            clauses.append("reg_type = ?")
            params.append(reg_type)

        department = request.args.get("department")
        if department:
            clauses.append("department LIKE ?")
            params.append(f"%{department}%")

        keyword = request.args.get("keyword")
        if keyword:
            clauses.append("(title LIKE ? OR description LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        limit = min(int(request.args.get("limit", 50)), 500)
        where = " AND ".join(clauses)
        sql = f"SELECT * FROM regulations WHERE {where} ORDER BY published_date DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
