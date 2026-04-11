"""F.O.R.G.E. GitHub Routes — PR management, issue tracking, webhooks.

Full-cycle Optimization & Regenerative GitHub Engine (Project #188).
"""

import hashlib
import hmac
import json
import logging
import os
from database import _get_db_password
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def _get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def register_github_routes(bp, admin_required):
    """Register all F.O.R.G.E. GitHub routes on the repair_bay blueprint."""

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
        """List open/closed PRs enriched with mergeable + review + check status.

        Used by the Repair Bay Reviews tab. Returns ALL PRs (not label-filtered)
        so admins can see every PR at a glance. The pipeline-label-only variant
        is still available via list_pipeline_prs() for F.O.R.G.E.-specific views.
        """
        from .services.github_service import list_all_prs_enriched

        state = request.args.get("state", "open")
        return jsonify(list_all_prs_enriched(state))

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
        """F.O.R.G.E. comprehensive pipeline statistics."""
        from .services.github_service import list_pipeline_prs, health_check

        conn = None
        cur = None
        try:
            # GitHub PR stats
            open_prs = list_pipeline_prs("open")
            merged_prs = list_pipeline_prs("merged")
            gh_health = health_check()

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Proposal stats
            cur.execute(
                """SELECT status, COUNT(*) as count
                   FROM improvement_proposals
                   GROUP BY status ORDER BY count DESC"""
            )
            proposal_stats = {r["status"]: r["count"] for r in cur.fetchall()}

            # Review stats
            cur.execute(
                """SELECT review_status, review_source, COUNT(*) as count
                   FROM forge_reviews
                   GROUP BY review_status, review_source
                   ORDER BY count DESC"""
            )
            review_stats = [dict(r) for r in cur.fetchall()]

            # Recent activity (last 7 days)
            cur.execute(
                """SELECT DATE(created_at) as day, COUNT(*) as reviews
                   FROM forge_reviews
                   WHERE created_at > NOW() - interval '7 days'
                   GROUP BY DATE(created_at) ORDER BY day"""
            )
            daily_reviews = [dict(r) for r in cur.fetchall()]

            # Deployment stats
            cur.execute(
                """SELECT status, COUNT(*) as count
                   FROM improvement_deployments
                   GROUP BY status"""
            )
            deploy_stats = {r["status"]: r["count"] for r in cur.fetchall()}

            # Self-healing stats (from autonomy loop log).
            # NB: the old schema was agent_loop_cycles with cycle_type/
            # success_count/error_count/timestamp — that table was renamed
            # to autonomy_loop_log with job_name/items_processed/items_failed/
            # created_at during the autonomy module rework. Project #242
            # follow-up fix.
            cur.execute(
                """SELECT job_name AS cycle_type,
                          COALESCE(SUM(items_processed), 0) AS successes,
                          COALESCE(SUM(items_failed), 0) AS errors
                   FROM autonomy_loop_log
                   WHERE job_name IN ('skill_analyzer', 'github_auto_pull', 'forge_self_heal')
                     AND created_at > NOW() - interval '7 days'
                   GROUP BY job_name"""
            )
            healing_stats = {r["cycle_type"]: dict(r) for r in cur.fetchall()}

            return jsonify(
                {
                    "success": True,
                    "github": {
                        "authenticated": gh_health.get("authenticated", False),
                        "open_prs": open_prs.get("count", 0),
                        "merged_prs": merged_prs.get("count", 0),
                    },
                    "proposals": proposal_stats,
                    "reviews": review_stats,
                    "daily_activity": daily_reviews,
                    "deployments": deploy_stats,
                    "self_healing": healing_stats,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # WEBHOOK — receives GitHub/CodeRabbit review events
    # ==================================================================

    @bp.route("/api/forge/webhook", methods=["POST"])
    def forge_webhook():
        """Receive GitHub webhook events (no auth — verified by signature).

        Handles:
        - pull_request_review: CodeRabbit approvals/changes_requested
        - pull_request_review_comment: individual review comments
        - pull_request: PR state changes (merged, closed)
        """
        # Verify webhook signature — reject if misconfigured or unsigned
        webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
        if not webhook_secret:
            return jsonify({"error": "Webhook secret not configured"}), 500
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not signature:
            return jsonify({"error": "Missing webhook signature"}), 401
        expected = (
            "sha256="
            + hmac.new(
                webhook_secret.encode(),
                request.data,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            return jsonify({"error": "Invalid signature"}), 401

        event_type = request.headers.get("X-GitHub-Event", "")
        payload = request.get_json(silent=True) or {}

        # Only process events for F.O.R.G.E. PRs
        pr_data = payload.get("pull_request", {})
        pr_labels = [l.get("name", "") for l in pr_data.get("labels", [])]
        if "archie-forge" not in pr_labels:
            return jsonify({"success": True, "skipped": "not a forge PR"})

        pr_number = pr_data.get("number") or payload.get("number")
        if not pr_number:
            return jsonify({"success": True, "skipped": "no PR number"})

        # Extract proposal ID from PR title: [FORGE] ... #123
        proposal_id = None
        pr_title = pr_data.get("title", "")
        match = re.search(r"#(\d+)", pr_title)
        if match:
            proposal_id = int(match.group(1))

        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if event_type == "pull_request_review":
                review = payload.get("review", {})
                review_state = review.get("state", "").lower()
                reviewer = review.get("user", {}).get("login", "unknown")
                review_body = review.get("body", "")

                # Map GitHub review states
                status_map = {
                    "approved": "approved",
                    "changes_requested": "changes_requested",
                    "commented": "commented",
                    "dismissed": "dismissed",
                }
                review_status = status_map.get(review_state, review_state)

                cur.execute(
                    """INSERT INTO forge_reviews
                           (pr_number, proposal_id, review_source, review_status,
                            summary, comments, raw_payload)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        pr_number,
                        proposal_id,
                        "coderabbit" if "coderabbit" in reviewer.lower() else "human",
                        review_status,
                        review_body[:1000] if review_body else None,
                        json.dumps([{"reviewer": reviewer, "state": review_state, "body": review_body[:500]}]),
                        json.dumps(payload)[:10000],
                    ),
                )

                # Update proposal status based on review
                if proposal_id and review_status in ("approved", "changes_requested"):
                    new_status = "ready_for_deployment" if review_status == "approved" else "review_changes_requested"
                    cur.execute(
                        """UPDATE improvement_proposals
                           SET status = %s
                           WHERE id = %s AND status IN ('deploying', 'pr_created')""",
                        (new_status, proposal_id),
                    )

                conn.commit()
                logger.info(
                    f"[FORGE] Webhook: PR #{pr_number} review={review_status} "
                    f"by {reviewer} (proposal #{proposal_id})"
                )

                # Send Telegram notification for changes_requested
                if review_status == "changes_requested":
                    try:
                        import requests as _req

                        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                        if bot_token:
                            text = (
                                f"🔧 *F.O.R.G.E. Review: Changes Requested*\n\n"
                                f"PR #{pr_number}: {pr_title}\n"
                                f"Reviewer: {reviewer}\n"
                                f"Proposal: #{proposal_id}\n\n"
                                f"_{review_body[:200] if review_body else 'No details'}_"
                            )
                            cur.execute(
                                "SELECT telegram_id FROM telegram_users "
                                "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                            )
                            for row in cur.fetchall():
                                _req.post(
                                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                    json={"chat_id": row["telegram_id"], "text": text, "parse_mode": "Markdown"},
                                    timeout=15,
                                )
                    except Exception as tg_err:
                        logger.warning(f"[FORGE] Telegram failed: {tg_err}")

            elif event_type == "pull_request_review_comment":
                comment = payload.get("comment", {})
                cur.execute(
                    """INSERT INTO forge_reviews
                           (pr_number, proposal_id, review_source, review_status,
                            summary, comments, raw_payload)
                       VALUES (%s, %s, %s, 'comment', %s, %s, %s)""",
                    (
                        pr_number,
                        proposal_id,
                        "coderabbit" if "coderabbit" in comment.get("user", {}).get("login", "").lower() else "human",
                        comment.get("body", "")[:500],
                        json.dumps(
                            [
                                {
                                    "file": comment.get("path", ""),
                                    "line": comment.get("line"),
                                    "body": comment.get("body", "")[:500],
                                    "user": comment.get("user", {}).get("login", ""),
                                }
                            ]
                        ),
                        json.dumps(payload)[:10000],
                    ),
                )
                conn.commit()

            elif event_type == "pull_request":
                action = payload.get("action", "")
                if action == "closed" and pr_data.get("merged"):
                    # PR was merged — update proposal status
                    if proposal_id:
                        cur.execute(
                            """UPDATE improvement_proposals
                               SET status = 'deployed'
                               WHERE id = %s""",
                            (proposal_id,),
                        )
                        conn.commit()
                        logger.info(f"[FORGE] PR #{pr_number} merged — proposal #{proposal_id} deployed")

            return jsonify({"success": True, "event": event_type, "pr": pr_number})

        except Exception as e:
            logger.error(f"[FORGE] Webhook error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # REVIEWS — query stored review data
    # ==================================================================

    @bp.route("/api/forge/reviews/<int:pr_number>", methods=["GET"])
    @login_required
    @admin_required
    def forge_reviews(pr_number):
        """Get all F.O.R.G.E. reviews for a PR."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT id, pr_number, proposal_id, review_source, review_status,
                          summary, comments, attempt_number, created_at
                   FROM forge_reviews
                   WHERE pr_number = %s
                   ORDER BY created_at DESC""",
                (pr_number,),
            )
            reviews = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "reviews": reviews, "count": len(reviews)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/forge/deploy/<int:pr_number>", methods=["POST"])
    @login_required
    @admin_required
    def forge_deploy(pr_number):
        """Deploy by merging a F.O.R.G.E. PR with pre-checks.

        Verifies CodeRabbit approved, no conflicts, then squash-merges.
        Updates proposal status and sends Telegram notification.
        """
        from .services.forge_pipeline import deploy_via_merge

        data = request.get_json() or {}
        proposal_id = data.get("proposal_id")

        # Try to extract proposal_id from PR if not provided
        if not proposal_id:
            from .services.github_service import get_pr_status

            status = get_pr_status(pr_number)
            if status.get("success"):
                title = status.get("title", "")
                match = re.search(r"#(\d+)", title)
                if match:
                    proposal_id = int(match.group(1))

        result = deploy_via_merge(pr_number, proposal_id)
        return jsonify(result)

    # ==================================================================
    # SELF-HEALING ROUTES (Phases 9-14)
    # ==================================================================

    @bp.route("/api/forge/self-heal/<int:proposal_id>", methods=["POST"])
    @login_required
    @admin_required
    def forge_self_heal(proposal_id):
        """Trigger a full self-healing cycle for a proposal."""
        from .services.forge_self_heal import run_self_heal_cycle

        return jsonify(run_self_heal_cycle(proposal_id))

    @bp.route("/api/forge/self-heal/<int:proposal_id>/retry-test", methods=["POST"])
    @login_required
    @admin_required
    def forge_retry_test(proposal_id):
        """Retry fix after sandbox test failure."""
        from .services.forge_self_heal import retry_after_test_failure

        data = request.get_json() or {}
        test_output = data.get("test_output", "")
        current_patch = data.get("current_patch", "")
        return jsonify(retry_after_test_failure(proposal_id, test_output, current_patch))

    @bp.route("/api/forge/self-heal/<int:proposal_id>/retry-review", methods=["POST"])
    @login_required
    @admin_required
    def forge_retry_review(proposal_id):
        """Retry fix after CodeRabbit review feedback."""
        from .services.forge_self_heal import retry_after_review_feedback

        data = request.get_json() or {}
        pr_number = data.get("pr_number", 0)
        comments = data.get("comments", [])
        return jsonify(retry_after_review_feedback(proposal_id, pr_number, comments))

    @bp.route("/api/forge/self-heal/<int:proposal_id>/regression", methods=["POST"])
    @login_required
    @admin_required
    def forge_regression_check(proposal_id):
        """Run regression check before merge."""
        from .services.forge_self_heal import run_regression_check

        return jsonify(run_regression_check(proposal_id))

    @bp.route("/api/forge/self-heal/stats", methods=["GET"])
    @login_required
    @admin_required
    def forge_self_heal_stats():
        """Self-healing pipeline statistics."""
        from .services.forge_self_heal import get_self_heal_stats

        return jsonify(get_self_heal_stats())

    @bp.route("/api/forge/self-heal/<int:proposal_id>/escalate", methods=["POST"])
    @login_required
    @admin_required
    def forge_escalate(proposal_id):
        """Manually escalate a proposal to human review."""
        from .services.forge_self_heal import escalate_to_human

        data = request.get_json() or {}
        reason = data.get("reason", "Manual escalation by admin")
        escalate_to_human(proposal_id, reason, {"manual": True})
        return jsonify({"success": True, "proposal_id": proposal_id, "status": "escalated"})
