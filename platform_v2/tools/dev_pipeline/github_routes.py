"""F.O.R.G.E. GitHub Routes — PR management, issue tracking, health check.

Full-cycle Optimization & Regenerative GitHub Engine (Project #188).
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_github_routes(bp, admin_required):
    """Register all F.O.R.G.E. GitHub routes on the dev_pipeline blueprint."""

    @bp.route("/api/forge/health", methods=["GET"])
    @login_required
    @admin_required
    def forge_health():
        """F.O.R.G.E. health check — GitHub auth + repo access."""
        from .services.github_service import health_check, ensure_labels

        result = health_check()
        if result.get("success"):
            ensure_labels()
        return jsonify(result)

    @bp.route("/api/forge/prs", methods=["GET"])
    @login_required
    @admin_required
    def forge_list_prs():
        """List all F.O.R.G.E. pipeline PRs."""
        from .services.github_service import list_pipeline_prs

        state = request.args.get("state", "open")
        return jsonify(list_pipeline_prs(state))

    @bp.route("/api/forge/prs/<int:pr_number>", methods=["GET"])
    @login_required
    @admin_required
    def forge_pr_status(pr_number):
        """Get detailed PR status including reviews and checks."""
        from .services.github_service import get_pr_status

        return jsonify(get_pr_status(pr_number))

    @bp.route("/api/forge/prs/<int:pr_number>/merge", methods=["POST"])
    @login_required
    @admin_required
    def forge_merge_pr(pr_number):
        """Merge a pipeline PR (admin approval required)."""
        from .services.github_service import merge_pr

        data = request.get_json() or {}
        method = data.get("method", "squash")
        if method not in ("squash", "merge", "rebase"):
            return jsonify({"success": False, "error": "Invalid merge method"}), 400

        result = merge_pr(pr_number, method)
        if result.get("success"):
            logger.info(f"[FORGE] PR #{pr_number} merged via {method}")
        return jsonify(result)

    @bp.route("/api/forge/prs/<int:pr_number>/comment", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_comment(pr_number):
        """Add a comment to a pipeline PR."""
        from .services.github_service import add_pr_comment

        data = request.get_json() or {}
        body = data.get("body", "").strip()
        if not body:
            return jsonify({"success": False, "error": "Comment body required"}), 400
        return jsonify(add_pr_comment(pr_number, body))

    @bp.route("/api/forge/branch", methods=["POST"])
    @login_required
    @admin_required
    def forge_create_branch():
        """Create a F.O.R.G.E. pipeline branch."""
        from .services.github_service import create_branch

        data = request.get_json() or {}
        branch_name = data.get("branch", "").strip()
        if not branch_name:
            return jsonify({"success": False, "error": "Branch name required"}), 400
        if not branch_name.startswith("archie/"):
            branch_name = f"archie/forge/{branch_name}"
        return jsonify(create_branch(branch_name))

    @bp.route("/api/forge/push", methods=["POST"])
    @login_required
    @admin_required
    def forge_push_changes():
        """Push changes to a pipeline branch."""
        from .services.github_service import push_changes

        data = request.get_json() or {}
        branch = data.get("branch", "").strip()
        files = data.get("files", [])
        message = data.get("message", "").strip()
        if not branch or not files or not message:
            return (
                jsonify({"success": False, "error": "branch, files, and message required"}),
                400,
            )
        return jsonify(push_changes(branch, files, message))

    @bp.route("/api/forge/issues", methods=["POST"])
    @login_required
    @admin_required
    def forge_create_issue():
        """Create a GitHub issue from a scan finding."""
        from .services.github_service import create_issue, find_existing_issue

        data = request.get_json() or {}
        title = data.get("title", "").strip()
        body = data.get("body", "").strip()
        severity = data.get("severity", "high")
        file_path = data.get("file_path", "")
        issue_type = data.get("issue_type", "")

        if not title or not body:
            return jsonify({"success": False, "error": "Title and body required"}), 400

        # Dedup check
        if file_path and issue_type:
            existing = find_existing_issue(file_path, issue_type)
            if existing:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Duplicate issue",
                            "existing_issue": existing,
                        }
                    ),
                    409,
                )

        return jsonify(create_issue(title, body, severity=severity))

    @bp.route("/api/forge/issues/<int:issue_number>/close", methods=["POST"])
    @login_required
    @admin_required
    def forge_close_issue(issue_number):
        """Close a GitHub issue."""
        from .services.github_service import close_issue

        data = request.get_json() or {}
        comment = data.get("comment")
        return jsonify(close_issue(issue_number, comment))

    @bp.route("/api/forge/stats", methods=["GET"])
    @login_required
    @admin_required
    def forge_stats():
        """F.O.R.G.E. pipeline statistics."""
        from .services.github_service import list_pipeline_prs

        open_prs = list_pipeline_prs("open")
        merged_prs = list_pipeline_prs("merged")

        return jsonify(
            {
                "success": True,
                "open_prs": open_prs.get("count", 0),
                "merged_prs": merged_prs.get("count", 0),
                "total_prs": open_prs.get("count", 0) + merged_prs.get("count", 0),
            }
        )
