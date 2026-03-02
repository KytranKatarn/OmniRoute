"""Dev Pipeline — Proposals tab routes.

Proxies to Improvements Lab's existing route functions, re-mounted under
the dev_pipeline blueprint at /api/proposals/*.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_proposal_routes(bp, admin_required):
    """Register proposal-related routes on the dev_pipeline blueprint."""

    def _imp():
        from tools.improvements import routes as imp

        return imp

    # ---- Core Proposal CRUD ----

    @bp.route("/api/proposals")
    @login_required
    @admin_required
    def proposals_list():
        return _imp().improvements_get_proposals()

    @bp.route("/api/proposals/<int:proposal_id>")
    @login_required
    @admin_required
    def proposals_get(proposal_id):
        return _imp().improvements_get_proposal(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def proposals_delete(proposal_id):
        return _imp().improvements_delete_proposal(proposal_id)

    # ---- Approval / Rejection ----

    @bp.route("/api/proposals/<int:proposal_id>/approve", methods=["POST"])
    @login_required
    @admin_required
    def proposals_approve(proposal_id):
        return _imp().improvements_approve_proposal(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/reject", methods=["POST"])
    @login_required
    @admin_required
    def proposals_reject(proposal_id):
        return _imp().improvements_reject_proposal(proposal_id)

    # ---- Execution ----

    @bp.route("/api/proposals/<int:proposal_id>/execute", methods=["POST"])
    @login_required
    @admin_required
    def proposals_execute(proposal_id):
        return _imp().improvements_execute_proposal(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/regenerate-plan", methods=["POST"])
    @login_required
    @admin_required
    def proposals_regenerate_plan(proposal_id):
        return _imp().improvements_regenerate_plan(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/retry", methods=["POST"])
    @login_required
    @admin_required
    def proposals_retry(proposal_id):
        return _imp().improvements_retry_failed_proposal(proposal_id)

    # ---- Escalation ----

    @bp.route("/api/proposals/<int:proposal_id>/escalate", methods=["POST"])
    @login_required
    @admin_required
    def proposals_escalate(proposal_id):
        return _imp().improvements_escalate_proposal(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/archive", methods=["POST"])
    @login_required
    @admin_required
    def proposals_archive(proposal_id):
        return _imp().improvements_archive_proposal(proposal_id)

    # ---- Deploy ----

    @bp.route("/api/proposals/<int:proposal_id>/deploy-to-production", methods=["POST"])
    @login_required
    @admin_required
    def proposals_deploy(proposal_id):
        return _imp().deploy_proposal_manager(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/restore", methods=["POST"])
    @login_required
    @admin_required
    def proposals_restore(proposal_id):
        return _imp().improvements_restore_proposal(proposal_id)

    @bp.route("/api/proposals/<int:proposal_id>/backups")
    @login_required
    @admin_required
    def proposals_backups(proposal_id):
        return _imp().improvements_get_backups(proposal_id)

    # ---- Stats ----

    @bp.route("/api/proposals/stats")
    @login_required
    @admin_required
    def proposals_stats():
        return _imp().get_improvement_stats()

    @bp.route("/api/proposals/stuck")
    @login_required
    @admin_required
    def proposals_stuck():
        return _imp().get_stuck_proposals()
