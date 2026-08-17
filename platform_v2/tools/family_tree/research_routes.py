"""Family Tree — Research queue routes."""

from flask import jsonify, request
from flask_login import current_user, login_required
from psycopg2.extras import Json

from database import get_db_cursor


def register_research_routes(bp, admin_required):
    """Register research queue endpoints on the blueprint."""

    @bp.route("/api/research/queue")
    @login_required
    def api_research_queue():
        sql = """
            SELECT rq.*, fp.first_name, fp.last_name
            FROM family_research_queue rq
            LEFT JOIN family_persons fp ON fp.id = rq.person_id
            WHERE rq.user_id = %(user_id)s
            ORDER BY rq.created_at DESC
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"user_id": current_user.id})
            rows = [dict(r) for r in cur.fetchall()]
        return jsonify(rows)

    @bp.route("/api/research/start", methods=["POST"])
    @login_required
    def api_research_start():
        data = request.get_json(silent=True) or {}
        person_id = data.get("person_id")
        research_type = data.get("research_type", "").strip()

        if not person_id or not research_type:
            return jsonify({"error": "person_id and research_type are required"}), 400

        # #5343: 'queued', not 'pending' — the table's CHECK constraint allows
        # (queued, searching, found_matches, reviewed, no_results). 'pending'
        # violated it, so EVERY Start-Research click 500'd since inception and
        # the queue was empty not from disuse but because enqueueing itself
        # failed (proven live 2026-08-17 in a ROLLBACK probe).
        sql = """
            INSERT INTO family_research_queue (user_id, person_id, research_type, status)
            VALUES (%(user_id)s, %(person_id)s, %(research_type)s, 'queued')
            RETURNING *
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                sql,
                {
                    "user_id": current_user.id,
                    "person_id": person_id,
                    "research_type": research_type,
                },
            )
            row = cur.fetchone()
        if row is None:
            return jsonify({"error": "Failed to queue research"}), 500
        return jsonify(dict(row)), 201

    @bp.route("/api/research/<int:research_id>/accept", methods=["POST"])
    @login_required
    def api_research_accept(research_id):
        sql = """
            UPDATE family_research_queue
            SET status = 'reviewed'
            WHERE id = %(id)s AND user_id = %(user_id)s
            RETURNING *
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql, {"id": research_id, "user_id": current_user.id})
            row = cur.fetchone()
        if row is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))

    @bp.route("/api/research/<int:queue_id>/analyze", methods=["POST"])
    @login_required
    def api_research_analyze(queue_id):
        """Run AI analysis on research results via S.C.R.O.L.L. agent."""
        from tools.family_tree.services.research_service import analyze_research_results

        # Fetch the queue entry and verify ownership
        sql_queue = """
            SELECT rq.*, fp.first_name, fp.last_name, fp.birth_date,
                   fp.birth_place, fp.death_date, fp.death_place
            FROM family_research_queue rq
            LEFT JOIN family_persons fp ON fp.id = rq.person_id
            WHERE rq.id = %(id)s AND rq.user_id = %(user_id)s
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql_queue, {"id": queue_id, "user_id": current_user.id})
            row = cur.fetchone()

        if row is None:
            return jsonify({"error": "Research queue entry not found"}), 404

        row = dict(row)
        raw_results = row.get("results")
        if not raw_results:
            return jsonify({"error": "No research results to analyze"}), 400

        # Parse results — stored as JSONB
        if isinstance(raw_results, str):
            try:
                import json as _json

                raw_results = _json.loads(raw_results)
            except (ValueError, TypeError):
                return jsonify({"error": "Could not parse stored results"}), 400

        # Build person context from the joined person record
        person_context = {
            "first_name": row.get("first_name", ""),
            "last_name": row.get("last_name", ""),
            "birth_date": str(row.get("birth_date", "") or ""),
            "birth_place": row.get("birth_place", ""),
            "death_date": str(row.get("death_date", "") or ""),
            "death_place": row.get("death_place", ""),
        }

        analysis = analyze_research_results(raw_results, person_context)
        return jsonify(analysis)

    @bp.route("/api/research/<int:research_id>/reject", methods=["POST"])
    @login_required
    def api_research_reject(research_id):
        sql = """
            UPDATE family_research_queue
            SET status = 'reviewed',
                results = COALESCE(results, '{}'::jsonb) || %(flag)s::jsonb
            WHERE id = %(id)s AND user_id = %(user_id)s
            RETURNING *
        """
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                sql,
                {
                    "id": research_id,
                    "user_id": current_user.id,
                    "flag": Json({"rejected": True}),
                },
            )
            row = cur.fetchone()
        if row is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
