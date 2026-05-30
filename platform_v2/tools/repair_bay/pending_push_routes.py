"""
Repair Bay — Pending Push routes.

Exposes the git-scan data from pending_push_service. Consumed by the Pushes
tab in repair_bay.html and (future) the MCP tool list_pending_pushes.
"""

from flask import jsonify
from flask_login import login_required


def register_pending_push_routes(bp, admin_required):
    from .services.pending_push_service import summarize

    @bp.route("/api/pushes/summary")
    @login_required
    @admin_required
    def pushes_summary():
        """Return the branches-pending-push summary."""
        try:
            return jsonify({"success": True, **summarize()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
