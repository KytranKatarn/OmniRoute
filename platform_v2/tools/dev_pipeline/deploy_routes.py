"""Dev Pipeline — Deploy tab routes.

Thin HTTP layer calling services.proposal_service for deployment data.
Migrated from direct DB queries in Project #103, Phase 2.
"""

import logging

from flask import jsonify
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_deploy_routes(bp, admin_required):
    """Register deployment-related routes on the dev_pipeline blueprint."""

    from services import proposal_service

    @bp.route("/api/deploy/history")
    @login_required
    @admin_required
    def deploy_history():
        """Unified deployment history."""
        result = proposal_service.get_deploy_history()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/deploy/ready")
    @login_required
    @admin_required
    def deploy_ready():
        """Proposals ready to deploy (status = tested)."""
        result = proposal_service.get_deploy_ready()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)
