"""Read-only visibility for pending hiring candidates (spec B).

These live in `hiring_candidates`, NOT `autonomy_approval_queue` — looking for
them in the approvals queue returns nothing and reads as "no pending hires".
"""

from flask import jsonify

from database import get_db_cursor

PENDING_SQL = """
    SELECT id, capability, gap_reason, precheck_status, precheck_message,
           narrative, proposed_at,
           ROUND(EXTRACT(EPOCH FROM (now() - proposed_at)) / 3600.0)::int AS age_hours
      FROM hiring_candidates
     WHERE status = 'pending'
     ORDER BY proposed_at DESC
     LIMIT 50
"""

COUNT_SQL = "SELECT COUNT(*) AS n FROM hiring_candidates WHERE status = 'pending'"


def register_hiring_routes(bp, admin_required):
    @bp.route("/api/hiring/pending")
    @admin_required
    def api_hiring_pending():
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(PENDING_SQL)
                rows = [dict(r) for r in cur.fetchall()]
                cur.execute(COUNT_SQL)
                total = cur.fetchone()["n"]
            for r in rows:
                r["proposed_at"] = r["proposed_at"].isoformat() if r["proposed_at"] else None
            return jsonify({"candidates": rows, "count": total})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
