"""Dedicated hiring approval routes registered by approvals_routes."""

import logging
from flask import jsonify, request
from flask_login import current_user

logger = logging.getLogger(__name__)


def register_hire_approval_routes(bp, admin_required_decorator):
    @bp.route("/api/approvals/hire/<int:hire_id>/approve", methods=["POST"])
    @admin_required_decorator
    def approve_hire(hire_id: int):
        """Approve a hiring_candidates row via web UI.

        Delegates to hiring_service.approve_candidate and maps result.reason
        to HTTP status codes.
        """
        from services import hiring_service

        body = request.get_json(silent=True) or {}
        chosen_agent_id = body.get("chosen_agent_id")
        new_agent = body.get("new_agent")
        notes = body.get("notes", "") or ""
        # Reactivation needs an existing-agent pick; a net-new hire needs a spec.
        if new_agent is None and not isinstance(chosen_agent_id, int):
            return jsonify({"ok": False, "reason": "chosen_agent_id or new_agent required"}), 400

        result = hiring_service.approve_candidate(
            hire_id=hire_id,
            chosen_agent_id=chosen_agent_id if isinstance(chosen_agent_id, int) else None,
            decided_by_user_id=current_user.id,
            notes=notes,
            new_agent=new_agent if isinstance(new_agent, dict) else None,
        )

        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "candidate_not_in_shortlist": 400,
            "not_a_new_hire_candidate": 400,
            "name_required": 400,
            "model_required": 400,
            "name_exists": 409,
            "create_rejected": 400,
            "create_failed": 500,
            "model_missing": 409,
            "ollama_unreachable": 409,
            "transition_failed": 500,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status

    @bp.route("/api/approvals/hire/<int:hire_id>/suggest-name", methods=["POST"])
    @admin_required_decorator
    def suggest_hire_name(hire_id: int):
        """Generate a unique, job-fit acronym name for a net-new hire.

        The server reads the candidate's capability itself (nothing
        client-supplied to trust). Fail-soft: any error returns HTTP 200
        {ok: false} so the UI can fall back to manual typing — this never
        blocks approval.
        """
        from database import get_db_cursor
        from services import agent_identity_builder

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT capability FROM hiring_candidates WHERE id = %s", (hire_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "error": "hire_not_found"}), 404
            capability = row["capability"] if isinstance(row, dict) else row[0]
            result = agent_identity_builder.build_identity(capability)
            return jsonify({"ok": True, **result}), 200
        except Exception as exc:
            logger.warning("suggest_hire_name(%s) failed: %s", hire_id, exc)
            return jsonify({"ok": False, "error": "generation_failed"}), 200

    @bp.route("/api/approvals/hire/<int:hire_id>/generate-name", methods=["POST"])
    @admin_required_decorator
    def generate_hire_name_async(hire_id: int):
        """Kick off async name generation and return a job_id immediately.

        The sync suggest-name endpoint above can spin 6-23s (up to ~60s) holding a
        gunicorn worker; this returns instantly and the frontend polls
        ``generate-name/<job_id>``. Fail-soft: any error → 200 {ok:false} so the UI
        can fall back to the sync path / manual typing (#4969).
        """
        from database import get_db_cursor
        from services import hire_name_job_service

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT capability FROM hiring_candidates WHERE id = %s", (hire_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "error": "hire_not_found"}), 404
            capability = row["capability"] if isinstance(row, dict) else row[0]
            job_id = hire_name_job_service.create_job(hire_id, capability)
            return jsonify({"ok": True, "job_id": job_id, "status": "generating"}), 200
        except Exception as exc:
            logger.warning("generate_hire_name_async(%s) failed: %s", hire_id, exc)
            return jsonify({"ok": False, "error": "generation_failed"}), 200

    @bp.route("/api/approvals/hire/<int:hire_id>/generate-name/<job_id>", methods=["GET"])
    @admin_required_decorator
    def poll_hire_name_async(hire_id: int, job_id: str):
        """Poll an async name job. Returns {ok, status, ...identity}; status is
        generating|done|error. On ``done`` the identity fields are flattened into
        the response (name/expansion/title/bio/... — the SAME shape the sync
        suggest-name endpoint returns) so the frontend renders identically (#4969).
        """
        from services import hire_name_job_service

        try:
            job = hire_name_job_service.get_job(job_id)
            if not job:
                return jsonify({"ok": False, "error": "job_not_found"}), 404
            status = job.get("status")
            if status == "done":
                result = job.get("result") or {}
                return jsonify({"ok": True, "status": "done", **result}), 200
            if status == "error":
                return jsonify({"ok": True, "status": "error"}), 200
            return jsonify({"ok": True, "status": "generating"}), 200
        except Exception as exc:
            logger.warning("poll_hire_name_async(%s) failed: %s", job_id, exc)
            return jsonify({"ok": False, "error": "poll_failed"}), 200

    @bp.route("/api/approvals/hire/<int:hire_id>/reject", methods=["POST"])
    @admin_required_decorator
    def reject_hire(hire_id: int):
        """Reject a hiring_candidates row via web UI.

        Delegates to hiring_service.reject_candidate and maps result.reason
        to HTTP status codes.
        """
        from services import hiring_service

        body = request.get_json(silent=True) or {}
        notes = body.get("notes", "") or ""

        result = hiring_service.reject_candidate(
            hire_id=hire_id,
            decided_by_user_id=current_user.id,
            notes=notes,
        )
        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status
