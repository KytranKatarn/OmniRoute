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

    @bp.route("/api/pushes/<path:branch>/create-pr", methods=["POST"])
    @login_required
    @admin_required
    def pushes_create_pr(branch):
        """Push a pending branch's local commits and open a PR for it.

        Pushed commits live ONLY in REPO_PATH (never on origin). Steps:
          1. validate the branch is in the scan result with pending status;
          2. read those commits out of the live checkout into a scratch clone
             (the fetch is read-only on the host tree);
          3. push the scratch clone to origin;
          4. open a PR via the GitHub API.
        """
        try:
            from .services.pending_push_service import (
                scan_pending_pushes,
                pending_commit_subjects,
            )
            from .services.github_service import push_pending_branch, create_pr

            rows = {r["branch"]: r for r in scan_pending_pushes()}
            row = rows.get(branch)
            if row is None:
                return jsonify({"success": False, "error": f"branch '{branch}' not found in scan"}), 404

            if row["commits_ahead"] <= 0:
                return (
                    jsonify({"success": False, "error": "no unpushed commits — nothing to PR"}),
                    400,
                )

            push = push_pending_branch(branch)
            if not push.get("success"):
                return jsonify({"success": False, "error": push.get("error", "push failed")}), 502

            subjects = pending_commit_subjects(branch)
            title = (subjects[0] if subjects else row.get("last_commit_subject") or f"Merge {branch}")[:72]
            body_lines = [
                f"Pending push: `{branch}` — {row['commits_ahead']} commits ahead of origin.",
            ]
            if subjects:
                body_lines += ["", "**Commits:**"] + [f"- {s}" for s in subjects]

            pr = create_pr(branch, title, "\n".join(body_lines))
            if not pr.get("success"):
                return jsonify({"success": False, "error": pr.get("error", "PR creation failed")}), 502

            return jsonify(
                {
                    "success": True,
                    "pr_url": pr["pr_url"],
                    "pr_number": pr["pr_number"],
                    "branch": branch,
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
