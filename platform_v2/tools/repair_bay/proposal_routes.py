"""Repair Bay — Proposals tab routes.

Thin HTTP layer calling services.proposal_service for all business logic.
Migrated from proxy pattern in Project #103, Phase 2.
"""

import logging

from flask import jsonify, request, session
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def register_proposal_routes(bp, admin_required):
    """Register proposal-related routes on the repair_bay blueprint."""

    from services import proposal_service

    # ---- Core Proposal CRUD ----

    @bp.route("/api/proposals")
    @login_required
    @admin_required
    def proposals_list():
        status = request.args.get("status", None)
        result = proposal_service.list_proposals(status=status)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/proposals/<int:proposal_id>")
    @login_required
    @admin_required
    def proposals_get(proposal_id):
        result = proposal_service.get_proposal(proposal_id)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
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

    # ---- Execution ----

    @bp.route("/api/proposals/<int:proposal_id>/execute", methods=["POST"])
    @login_required
    @admin_required
    def proposals_execute(proposal_id):
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
        result = proposal_service.deploy_to_production(proposal_id)
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
