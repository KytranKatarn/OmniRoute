"""Repair Bay — Proposals tab routes.

Thin HTTP layer calling services.proposal_service for all business logic.
Migrated from proxy pattern in Project #103, Phase 2.
"""

import logging
import time

from flask import jsonify, request
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)

# Page cache for the Repairs tab list (mirrors the pr-reviews cache: a short
# TTL so repeat tab visits load instantly without re-serialising rows; a
# `bust` param skips it so mutations (approve/reject/execute) show instantly).
_proposals_cache: dict = {}
_PROPOSALS_CACHE_TTL = 30


def _legacy_proposal_execute(proposal_id):
    """Original proposals_execute body — handles non-compliance_fix proposals.

    Extracted 2026-04-11 so the compliance_fix branch can be added to the
    route handler without entangling the two code paths.
    """
    from services import proposal_service

    data = request.get_json(silent=True) or {}
    result = proposal_service.run_proposal(
        proposal_id,
        user_id=current_user.id,
        skip_backup=data.get("skip_backup", False),
        use_orchestrator=data.get("use_orchestrator", True),
        steps=data.get("steps"),
    )
    if not result.get("success"):
        code = 404 if "not found" in result.get("error", "").lower() else 400 if result.get("legacy") else 500
        return jsonify(result), code
    return jsonify(result)


def register_proposal_routes(bp, admin_required):
    """Register proposal-related routes on the repair_bay blueprint."""

    from services import proposal_service

    # ---- Core Proposal CRUD ----

    @bp.route("/api/proposals")
    @login_required
    @admin_required
    def proposals_list():
        status = request.args.get("status", None)
        q = request.args.get("q", "").strip()
        limit = request.args.get("limit", 50, type=int)
        page = request.args.get("page", 1, type=int)
        bust = request.args.get("bust")

        if not q:
            # Cached path only for unfiltered pagination — a live q must always
            # hit the DB so search never reads stale rows (mirrors pr-reviews).
            cache_key = f"{status}:{q}:{page}:{limit}"
            now = time.time()
            if not bust and cache_key in _proposals_cache:
                ts, data = _proposals_cache[cache_key]
                if now - ts < _PROPOSALS_CACHE_TTL:
                    return jsonify({"success": True, **data, "cached": True})

        offset = max(0, (page - 1) * limit)
        result = proposal_service.list_proposals_page(status=status, q=q or None, limit=limit, offset=offset)
        if not result.get("success"):
            return jsonify(result), 500
        if not q and not bust:
            _proposals_cache[cache_key] = (time.time(), result)
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>")
    @login_required
    @admin_required
    def proposals_get(proposal_id):
        result = proposal_service.get_proposal(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        from services.repair_submission import metadata, progress

        proposal = result["proposal"]
        if metadata(proposal.get("metadata")).get("source") == "code_health_audit":
            proposal["repair_progress"] = progress(proposal)
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def proposals_delete(proposal_id):
        result = proposal_service.delete_proposal(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 400
            return jsonify(result), code
        return jsonify(result)

    # ---- Approval / Rejection ----

    @bp.route("/api/proposals/<int:proposal_id>/approve", methods=["POST"])
    @login_required
    @admin_required
    def proposals_approve(proposal_id):
        result = proposal_service.approve_proposal(proposal_id, user_id=current_user.id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>/reject", methods=["POST"])
    @login_required
    @admin_required
    def proposals_reject(proposal_id):
        data = request.get_json() or {}
        reason = data.get("reason", "Rejected by user")
        result = proposal_service.reject_proposal(proposal_id, reason=reason)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>/retry-fix", methods=["POST"])
    @login_required
    @admin_required
    def proposals_retry_fix(proposal_id):
        from services.audit_pipeline import request_audit_fix_retry

        data = request.get_json(silent=True) or {}
        result = request_audit_fix_retry(proposal_id, reason=data.get("reason", "Requested repair retry"))
        if not result.get("success"):
            return jsonify(result), 422
        from services.work_control_service import is_enabled

        result["worker_enabled"] = is_enabled("code_health_backlog_drain", default=False)
        _proposals_cache.clear()
        return jsonify(result), 202

    @bp.route("/api/proposals/<int:proposal_id>/plan-repair", methods=["POST"])
    @login_required
    @admin_required
    def proposals_plan_repair(proposal_id):
        from services.planned_repair_service import request_planned_work

        result = request_planned_work(proposal_id, requested_by=current_user.get_id())
        _proposals_cache.clear()
        return jsonify(result), (200 if result.get("already_queued") else 202) if result.get("success") else 422

    @bp.route("/api/proposals/<int:proposal_id>/planned-replacement", methods=["POST"])
    @login_required
    @admin_required
    def proposals_planned_replacement(proposal_id):
        from services.planned_repair_closed import request_replacement

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(success=False, error="Invalid replacement request"), 422
        result = request_replacement(
            proposal_id, current_user.get_id(), data.get("task_id"), data.get("pr_number"), data.get("head_sha")
        )
        _proposals_cache.clear()
        return jsonify(result), 200 if result.get("success") else 422

    @bp.route("/api/proposals/<int:proposal_id>/planned-recovery", methods=["POST"])
    @login_required
    @admin_required
    def proposals_planned_recovery(proposal_id):
        from services.planned_repair_recovery import recover_planned_work

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(success=False, error="Invalid recovery request"), 422
        result = recover_planned_work(proposal_id, current_user.get_id(), data.get("action"), data.get("task_id"))
        _proposals_cache.clear()
        return jsonify(result), (202 if result.get("queued") else 200) if result.get("success") else 422

    @bp.route("/api/proposals/<int:proposal_id>/submit-patch", methods=["POST"])
    @login_required
    @admin_required
    def proposals_submit_patch(proposal_id):
        from services.repair_submission import request_submission

        result = request_submission(proposal_id)
        _proposals_cache.clear()
        return jsonify(result), 202 if result.get("success") else 422

    @bp.route("/api/proposals/<int:proposal_id>/repair-progress")
    @login_required
    @admin_required
    def proposals_repair_progress(proposal_id):
        from services.repair_submission import progress

        result = proposal_service.get_proposal(proposal_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify({"success": True, "progress": progress(result["proposal"])})

    @bp.route("/api/proposals/<int:proposal_id>/verify-completion", methods=["POST"])
    @login_required
    @admin_required
    def proposals_verify_completion(proposal_id):
        from services.repair_submission import verify_completion

        result = verify_completion(proposal_id)
        _proposals_cache.clear()
        return jsonify(result), 200 if result.get("success") else 422

    # ---- Execution ----

    @bp.route("/api/proposals/<int:proposal_id>/execute", methods=["POST"])
    @login_required
    @admin_required
    def proposals_execute(proposal_id):
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT category FROM improvement_proposals WHERE id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "not found"}), 404

        category = row["category"] if isinstance(row, dict) else row[0]

        if category == "compliance_fix":
            from tools.security_network.compliance_safe_exec import _safe_execute_fix

            result = _safe_execute_fix(proposal_id, user_id=current_user.id)
            status_code = 200 if result.get("success") else 500
            return jsonify(result), status_code

        # Non-compliance proposals use the legacy path
        return _legacy_proposal_execute(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/compliance-action", methods=["POST"])
    @login_required
    @admin_required
    def proposals_compliance_action(proposal_id):
        """Handle the three Repair Bay compliance card buttons.

        Body: {"action": "apply_once" | "apply_and_allow" | "exempt"}
        """
        from database import get_db_cursor
        from tools.security_network import compliance_service
        from tools.security_network.compliance_safe_exec import _safe_execute_fix

        action = (request.get_json(silent=True) or {}).get("action")
        if action not in ("apply_once", "apply_and_allow", "exempt"):
            return jsonify({"success": False, "error": "bad action"}), 400

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT category, metadata FROM improvement_proposals
                   WHERE id = %s""",
                (proposal_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "not found"}), 404

        cat = row["category"] if isinstance(row, dict) else row[0]
        if cat != "compliance_fix":
            return jsonify({"success": False, "error": "not a compliance_fix proposal"}), 400

        meta_raw = row["metadata"] if isinstance(row, dict) else row[1]
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        rule_id = meta.get("rule_id")
        if not rule_id:
            return jsonify({"success": False, "error": "proposal missing rule_id"}), 500

        if action == "exempt":
            compliance_service.set_rule_auto_approval(
                rule_id, "exempt", current_user.id, "exempted via Repair Bay card"
            )
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE improvement_proposals
                       SET status = 'resolved',
                           reviewed_at = NOW(),
                           metadata = metadata || '{"resolved_by":"exempt"}'::jsonb
                       WHERE id = %s""",
                    (proposal_id,),
                )
            return jsonify({"success": True, "action": "exempt", "rule_id": rule_id})

        if action == "apply_and_allow":
            compliance_service.set_rule_auto_approval(rule_id, "allow", current_user.id, "approved via Repair Bay")

        result = _safe_execute_fix(proposal_id, user_id=current_user.id)
        result["action"] = action
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code

    @bp.route("/api/proposals/<int:proposal_id>/regenerate-plan", methods=["POST"])
    @login_required
    @admin_required
    def proposals_regenerate_plan(proposal_id):
        result = proposal_service.regenerate_plan(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>/retry", methods=["POST"])
    @login_required
    @admin_required
    def proposals_retry(proposal_id):
        result = proposal_service.retry_proposal(proposal_id, user_id=current_user.id)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    # ---- Escalation ----

    @bp.route("/api/proposals/<int:proposal_id>/escalate", methods=["POST"])
    @login_required
    @admin_required
    def proposals_escalate(proposal_id):
        result = proposal_service.escalate_proposal(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>/archive", methods=["POST"])
    @login_required
    @admin_required
    def proposals_archive(proposal_id):
        result = proposal_service.archive_proposal(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    # ---- Deploy ----

    @bp.route("/api/proposals/<int:proposal_id>/deploy-to-production", methods=["POST"])
    @login_required
    @admin_required
    def proposals_deploy(proposal_id):
        # Spec 2026-08-26 §6.3: the deploy action is ship_as_pr — sandbox gate
        # (previously bypassed by this button) + branch + PR. The route path is
        # unchanged so the existing UI button keeps working; the governed merge
        # is what applies code. deploy_to_production (the #5808 no-op) is no
        # longer reachable from any route.
        result = proposal_service.ship_as_pr(proposal_id)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>/restore", methods=["POST"])
    @login_required
    @admin_required
    def proposals_restore(proposal_id):
        result = proposal_service.restore_proposal(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>/backups")
    @login_required
    @admin_required
    def proposals_backups(proposal_id):
        return jsonify(proposal_service.get_backups(proposal_id))

    # ---- Stats ----

    @bp.route("/api/proposals/stats")
    @login_required
    @admin_required
    def proposals_stats():
        result = proposal_service.get_stats()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/proposals/stuck")
    @login_required
    @admin_required
    def proposals_stuck():
        result = proposal_service.get_stuck()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)
