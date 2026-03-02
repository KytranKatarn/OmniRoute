"""Dev Pipeline — Scan tab routes.

Proxies to Code Sentinel's existing route functions, re-mounted under
the dev_pipeline blueprint at /api/scan/*.

This avoids duplicating 1,500 lines of scan logic — Code Sentinel
remains the backend, Dev Pipeline is the unified frontend.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_scan_routes(bp, admin_required):
    """Register scan-related routes on the dev_pipeline blueprint."""

    # Lazy import to avoid circular dependencies at module load
    def _get_sentinel():
        from tools.code_sentinel import routes as sentinel

        return sentinel

    @bp.route("/api/scan/status")
    @login_required
    def scan_status():
        """Scan module health check."""
        s = _get_sentinel()
        ai = s.check_ollama_status()
        return jsonify(
            {
                "success": True,
                "bridge_routing": s.BRIDGE_ROUTING_AVAILABLE,
                "ollama": ai,
            }
        )

    @bp.route("/api/scan/stats")
    @login_required
    @admin_required
    def scan_stats():
        """Get scan statistics (proxies to Code Sentinel)."""
        return _get_sentinel().get_health_stats()

    @bp.route("/api/scan/run", methods=["POST"])
    @login_required
    @admin_required
    def scan_run():
        """Scan a single file (proxies to Code Sentinel scan_file)."""
        return _get_sentinel().scan_file()

    @bp.route("/api/scan/batch", methods=["POST"])
    @login_required
    @admin_required
    def scan_batch():
        """Batch scan files (proxies to Code Sentinel batch_scan_files)."""
        return _get_sentinel().batch_scan_files()

    @bp.route("/api/scan/history")
    @login_required
    @admin_required
    def scan_history():
        """Get scan history (proxies to Code Sentinel)."""
        return _get_sentinel().get_scan_history()

    @bp.route("/api/scan/issues")
    @login_required
    @admin_required
    def scan_issues():
        """Get issues list (proxies to Code Sentinel)."""
        return _get_sentinel().get_issues()

    @bp.route("/api/scan/issues/<int:issue_id>/fix", methods=["POST"])
    @login_required
    @admin_required
    def scan_fix_issue(issue_id):
        """Mark issue as fixed (proxies to Code Sentinel)."""
        return _get_sentinel().mark_issue_fixed(issue_id)

    @bp.route("/api/scan/fixes")
    @login_required
    @admin_required
    def scan_fixes():
        """Get fixes list (proxies to Code Sentinel)."""
        return _get_sentinel().get_fixes()

    @bp.route("/api/scan/files")
    @login_required
    @admin_required
    def scan_files():
        """Get file health data (proxies to Code Sentinel)."""
        return _get_sentinel().get_file_health()

    @bp.route("/api/scan/directory")
    @login_required
    @admin_required
    def scan_directory():
        """Browse directory for scanning (proxies to Code Sentinel)."""
        return _get_sentinel().get_directory_files()

    @bp.route("/api/scan/multi-agent/nodes")
    @login_required
    @admin_required
    def scan_review_nodes():
        """Get review nodes (proxies to Code Sentinel)."""
        return _get_sentinel().get_review_nodes()

    @bp.route("/api/scan/multi-agent/agents")
    @login_required
    @admin_required
    def scan_review_agents():
        """List review agents (proxies to Code Sentinel)."""
        return _get_sentinel().list_review_agents()

    @bp.route("/api/scan/multi-agent/review", methods=["POST"])
    @login_required
    @admin_required
    def scan_start_review():
        """Start multi-agent review (proxies to Code Sentinel)."""
        return _get_sentinel().start_multi_agent_review()

    @bp.route("/api/scan/multi-agent/review/<review_id>")
    @login_required
    @admin_required
    def scan_get_review(review_id):
        """Get review status (proxies to Code Sentinel)."""
        return _get_sentinel().get_multi_agent_review(review_id)
