"""F.O.R.G.E. GitHub Routes — PR management, issue tracking, webhooks.

Full-cycle Optimization & Regenerative GitHub Engine (Project #188).
"""

import hashlib
import hmac
import json
import logging
import os
import time
from database import _get_db_password
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

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
        from .services.pr_review_service import stamp_merge_states

        state = request.args.get("state", "open")
        data = list_all_prs_enriched(state)
        # #5853: this payload is GitHub-shaped — `mergeable`/`review_decision` know
        # nothing about the F.O.R.G.E. verdict, so the Reviews tab was rendering an
        # enabled green Merge on PRs the server would refuse. Stamp the SAME
        # merge_state that list_reviews() uses so both surfaces agree.
        # Best-effort: a stamping failure must degrade the BUTTON, never the LISTING —
        # stamp_merge_states is itself fail-closed, so an unstamped row is simply
        # rendered as awaiting_review by the client.
        try:
            stamp_merge_states(data.get("prs") or [])
        except Exception as exc:
            logger.warning("forge_list_prs: merge_state stamping failed: %s", exc)
        # MERGE ORDER (2026-09-11): same contract as merge_state — computed here, only
        # rendered by the client. Best-effort: a failure stamps "unavailable", never
        # an invented rank, and never takes the listing down.
        try:
            from .services.github_service import REPO_FULL
            from .services.merge_order_service import stamp_merge_order

            stamp_merge_order(data.get("prs") or [], number_key="number", default_repo=REPO_FULL)
        except Exception as exc:
            logger.warning("forge_list_prs: merge_order stamping failed: %s", exc)
        return jsonify(data)

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

        # CROSS-REPO (2026-09-11): the PR Review tab lists rows from every repo F.O.R.G.E.
        # has reviewed (review_pr(repo=…) stores them), but this route looked the verdict
        # up and merged WITHOUT the repo. Measured on archie-code #64/#65: both held a
        # clean APPROVE and the button answered 422 "no stored F.O.R.G.E. review" — the
        # lookup searched archie-platform for the same number. Worse, had a same-numbered
        # archie-platform PR carried an approval, the override would have merged THAT one.
        # The row's repo travels with the click; absent → the default repo (back-compat).
        from .services.pr_review_service import _is_valid_repo

        _repo_in = data.get("repo")
        if _repo_in is not None and not _is_valid_repo(_repo_in):
            return jsonify({"success": False, "error": "Invalid repo"}), 400
        _repo = _repo_in or None

        # human_override: this endpoint is @login_required @admin_required — an operator
        # clicking merge is an attended decision, so it bypasses the unattended-merge
        # governance gate (#5194). Automated callers must never pass this.
        #
        # #5834 PARITY: the override clears AUTHORITY (allowlist, tier ceiling) — never the
        # SAFETY property that an approving verdict exists. The Approvals tab enforces this
        # via tab_merge_refusal; this route did not, so the SAME PR refused there could be
        # merged here on a needs_changes verdict. That inconsistency is how #2458 reached
        # main. Staleness stays with merge_pr's _override_stale_verdict_check (#5672).
        try:
            from .services.github_service import verdict_refusal
            from .services.pr_review_service import (
                coverage_dropped_paths,
                get_review,
                verdict_is_approved,
            )

            _row = get_review(pr_number, repo=_repo) or {}
            _summary = _row.get("ai_summary") or ""
            _ack = bool(data.get("coverage_ack"))
            _refusal = verdict_refusal(_summary, bool(_summary) and verdict_is_approved(_summary), coverage_ack=_ack)
            _dropped = coverage_dropped_paths(_summary) if _refusal else []
        except Exception as _exc:  # noqa: BLE001
            # FAIL CLOSED — an unreadable verdict is not an approval, and this ends in an
            # unrevertable merge to main.
            _refusal = f"could not verify the verdict ({_exc}) — refusing rather than guessing"
            _dropped = []
        if _refusal:
            logger.warning("[FORGE] refusing merge of PR #%s (%s): %s", pr_number, _repo or "default repo", _refusal)
            return (
                jsonify(
                    {
                        "success": False,
                        "merged": False,
                        "error": _refusal,
                        # coverage_only tells the UI it may offer an informed discharge; the
                        # dropped list is WHAT the human is being asked to take responsibility
                        # for. A count alone would make that an uninformed click.
                        "coverage_only": _refusal.startswith("COVERAGE ONLY"),
                        "dropped_files": _dropped,
                    }
                ),
                422,
            )

        result = merge_pr(pr_number, method, repo=_repo, human_override=True)
        if result.get("success") or result.get("merged"):
            logger.info(
                "[FORGE] PR #%s (%s) merged via %s (human override)", pr_number, _repo or "default repo", method
            )
            # THIRD SURFACE, same row (#5283/#5338). Telegram and the Approvals
            # tab already converge via resolve_pr_merge_approval; without this
            # the Repair Bay button was the odd one out — merging the PR while
            # leaving a pending pr_merge approval behind to expire, or worse to
            # be tapped later against an already-merged PR.
            try:
                from .services.github_service import REPO_FULL
                from .services.pr_review_service import resolve_pr_merge_approval

                # pr_merge approval rows exist only for the polled default repo and are
                # keyed by number alone — resolving one for a cross-repo PR would close a
                # DIFFERENT PR's approval that happens to share the number.
                if not _repo or _repo == REPO_FULL:
                    resolve_pr_merge_approval(pr_number, approved=True, user_id=getattr(current_user, "id", None))

                # MERGE → AUTO-DEPLOY (deploy-provenance #5375/#2543): a GitHub merge of
                # the DEFAULT repo deploys nothing by itself — the hub bind-mounts
                # /mnt/archie_brain, so the host must fast-forward the checkout and
                # restart the containers. Enqueue the signed hub_deploy host command
                # (async, NOT submit_and_wait: the host restarts archie_platform, which
                # is THIS container — waiting would kill the request mid-reply).
                # Cross-repo merges (watch products, KBS, creed…) never deploy the hub.
                if not _repo or _repo == REPO_FULL:
                    try:
                        from tools.system_operations.host_command_client import submit_host_command

                        command_id = submit_host_command(
                            "hub_deploy",
                            {},
                            submitted_by="repair_bay_merge",
                            user_id=getattr(current_user, "id", None),
                        )
                        result["deploy"] = {
                            "enqueued": True,
                            "command_id": command_id,
                            "command_type": "hub_deploy",
                        }
                        logger.info("[FORGE] PR #%s merged — hub_deploy enqueued (%s)", pr_number, command_id)
                    except Exception as deploy_exc:
                        logger.warning("[FORGE] PR #%s merged but hub_deploy not enqueued: %s", pr_number, deploy_exc)
                        result["deploy"] = {"enqueued": False, "error": str(deploy_exc)}
                else:
                    result["deploy"] = {"enqueued": False, "reason": "cross-repo merge does not deploy the hub"}
            except Exception as exc:  # noqa: BLE001 — bookkeeping never fails a real merge
                logger.warning("[FORGE] PR #%s merged but post-merge bookkeeping failed: %s", pr_number, exc)
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
            return jsonify({"error": "Webhook not configured"}), 401
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
                        from services.telegram_service import send_forge

                        text = (
                            f"PR #{pr_number}: {pr_title}\n"
                            f"Reviewer: {reviewer}\n"
                            f"Proposal: #{proposal_id}\n\n"
                            f"{review_body[:200] if review_body else 'No details'}"
                        )
                        send_forge("PR Review: Changes Requested", text, source_module="github_routes")
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

                    # #3336: auto-queue C.O.D.E.X. documentation for EVERY merged
                    # PR (not just ones with a proposal). Deduped against the
                    # merge-pr skill's Step-8 delegation so a skill-merged PR is
                    # not documented twice. Best-effort — never break the webhook.
                    try:
                        cur.execute(
                            """SELECT 1 FROM unified_tasks
                               WHERE delegation_args->'args'->>'pr_number' = %s
                                 AND delegation_args->>'capability' = 'documentation'
                                 AND created_at > NOW() - INTERVAL '2 hours'
                               LIMIT 1""",
                            (str(pr_number),),
                        )
                        if not cur.fetchone():
                            from services.delegation_service import delegate_task

                            _title = pr_data.get("title", f"PR #{pr_number}")
                            _repo = (payload.get("repository") or {}).get("full_name", "KytranKatarn/archie-platform")
                            delegate_task(
                                capability="documentation",
                                reason=f"Auto-document merged PR #{pr_number}: {_title}",
                                args={
                                    "pr_number": pr_number,
                                    "pr_title": _title,
                                    "repo": _repo,
                                    "auto_store": True,
                                },
                                delegation_source="automation",
                                requested_by="forge_webhook",
                            )
                            logger.info(f"[FORGE] PR #{pr_number} merged — queued C.O.D.E.X. documentation")
                    except Exception as _doc_err:
                        logger.warning(f"[FORGE] doc auto-queue failed for PR #{pr_number}: {_doc_err}")

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

    # ── PR Review Service (Project #247 Phase 1, Task #1799) ─────────────────

    _pr_reviews_cache: dict = {}
    _PR_REVIEWS_CACHE_TTL = 30

    @bp.route("/api/forge/pr-reviews", methods=["GET"])
    @login_required
    @admin_required
    def forge_pr_reviews_list():
        """List tracked PR reviews with optional state/review_status filters."""
        from .services.pr_review_service import list_reviews

        state = request.args.get("state")
        review_status = request.args.get("review_status")
        limit = request.args.get("limit", 200, type=int)
        bust = request.args.get("bust")

        cache_key = f"{state}:{review_status}:{limit}"
        now = time.time()
        if not bust and cache_key in _pr_reviews_cache:
            ts, data = _pr_reviews_cache[cache_key]
            if now - ts < _PR_REVIEWS_CACHE_TTL:
                return jsonify({"reviews": data, "cached": True})

        result = list_reviews(state=state, review_status=review_status, limit=limit)
        # MERGE ORDER (2026-09-11): rows carry `repo`; open rows are ranked per repo.
        try:
            from .services.merge_order_service import stamp_merge_order

            stamp_merge_order(result)
        except Exception as exc:
            logger.warning("forge_pr_reviews_list: merge_order stamping failed: %s", exc)
        _pr_reviews_cache[cache_key] = (now, result)
        return jsonify({"reviews": result})

    @bp.route("/api/forge/pr-reviews/<int:pr_number>", methods=["GET"])
    @login_required
    @admin_required
    def forge_pr_review_get(pr_number):
        """Fetch a single PR review record."""
        from .services.pr_review_service import get_review

        review = get_review(pr_number)
        if not review:
            return jsonify({"error": "not found"}), 404
        return jsonify({"review": review})

    @bp.route("/api/forge/pr-reviews/<int:pr_number>/send-back", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_review_send_back(pr_number):
        """#5932 Phase 1: turn the stored review's blocking findings into
        fix_requested proposals in the existing queue. Human-triggered only —
        NO automatic execution happens here or downstream of this call."""
        from .services.pr_review_service import create_fix_requests_from_review

        data = request.get_json(silent=True) or {}
        result = create_fix_requests_from_review(pr_number, repo=data.get("repo"))
        return jsonify(result), (200 if result.get("success") else 422)

    _coderabbit_cache: dict = {}
    _CR_CACHE_TTL = 300  # 5 min — GH API is slow

    @bp.route("/api/forge/pr-reviews/<int:pr_number>/coderabbit", methods=["GET"])
    @login_required
    @admin_required
    def forge_pr_coderabbit(pr_number):
        """Fetch the CodeRabbit walkthrough comment for a PR from GitHub API."""
        import os
        import re
        import urllib.request

        now = time.time()
        if pr_number in _coderabbit_cache:
            ts, data = _coderabbit_cache[pr_number]
            if now - ts < _CR_CACHE_TTL:
                return jsonify({**data, "cached": True})

        token = os.getenv("GITHUB_TOKEN", "")
        repo = "KytranKatarn/archie-platform"
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=50"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                import json as _json

                comments = _json.loads(resp.read().decode())
        except Exception as exc:
            return jsonify({"error": str(exc), "coderabbit": None}), 502

        # Find best CodeRabbit comment — prefer walkthrough over "skip review"
        walkthrough = None
        skip_review = None
        for c in comments:
            if c.get("user", {}).get("login") != "coderabbitai[bot]":
                continue
            body = c.get("body", "")
            # Skip "Review triggered" action replies
            if "Actions performed" in body or "Review triggered" in body:
                continue
            clean = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
            if "walkthrough" in body.lower() or "Walkthrough" in body:
                walkthrough = clean
                break
            elif "skip review" in body.lower() or "Review skipped" in body:
                skip_review = clean

        result_text = walkthrough or skip_review or None
        result = {
            "coderabbit": result_text,
            "total_bot_comments": sum(1 for c in comments if c.get("user", {}).get("login") == "coderabbitai[bot]"),
        }
        _coderabbit_cache[pr_number] = (now, result)
        return jsonify(result)

    @bp.route("/api/forge/pr-reviews/poll", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_reviews_poll():
        """Manually trigger a GitHub PR poll + sync closed PRs."""
        from .services.pr_review_service import poll_open_prs, sync_closed_prs

        poll_result = poll_open_prs()
        closed = sync_closed_prs()
        return jsonify({**poll_result, "closed_synced": closed})

    @bp.route("/api/forge/pr-reviews/<int:pr_number>/analyze", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_review_analyze(pr_number):
        """Trigger F.O.R.G.E. AI review for a specific PR via DHQ dispatch queue.

        Returns 202 immediately — analysis runs in a background thread through
        the DHQ orchestration pipeline. Frontend polls /api/forge/pr-reviews for
        status change from 'in_progress' → 'reviewed'.
        """
        import threading

        from .services.pr_review_service import (
            get_review,
            mark_review_started,
            mark_review_done,
            mark_review_pending,
        )
        from .services.pr_diff_analyzer import (
            _fetch_diff,
            _build_prompt,
            _run_forge_review,
            _obtain_review_summary,
            _notify_pr_reviewed,
            review_scope_override,
        )

        review = get_review(pr_number)
        if not review:
            return jsonify({"error": f"PR #{pr_number} not found in pr_reviews"}), 404

        if review.get("review_status") == "in_progress":
            # Allow re-trigger if stuck > 5 minutes (thread likely died silently)
            from datetime import datetime, timezone

            updated = review.get("updated_at")
            stuck = False
            if updated:
                try:
                    age = (datetime.now(timezone.utc) - updated).total_seconds()
                    stuck = age > 300
                except Exception:
                    stuck = False
            if not stuck:
                return jsonify({"status": "in_progress", "message": "Review already running — check back in 30s"}), 200
            # Fall through to re-trigger — reset to pending first
            from .services.pr_review_service import _DEFAULT_REPO, mark_review_pending as _reset

            _reset(pr_number, review.get("repo", _DEFAULT_REPO))

        diff_url = review.get("diff_url")
        if not diff_url:
            return jsonify({"error": "No diff URL for this PR — re-poll GitHub to refresh"}), 422

        repo = review.get("repo", "KytranKatarn/archie-platform")

        # #6769 — `wide` re-runs the review with the WHOLE diff shown to the reviewer.
        # Parsed here (in the request context), not inside the thread, so a missing body
        # degrades to the default freeform path exactly as before.
        _body = request.get_json(silent=True) or {}
        wide = bool(_body.get("wide"))

        # Per-send review SCOPE. Parsed here in the request context (like `wide`),
        # so a missing/garbage body degrades to the stored global defaults rather
        # than erroring. `plan`/`max_files` only change how much of the diff the
        # model is SHOWN — the coverage gate still measures what was actually
        # read, so a scope that still drops files still demotes the verdict.
        _plan = str(_body.get("plan") or "").strip().lower() or None
        if _plan not in ("packed", "per_file", None):
            _plan = None
        try:
            _max_files = int(_body["max_files"]) if _body.get("max_files") else None
        except (TypeError, ValueError):
            _max_files = None

        def _run_in_background():
            # The override is THREAD-LOCAL, so it has to be entered inside the
            # thread. Wrapping the Thread(...) construction instead would set it
            # on the request thread and this review would never see it.
            try:
                with review_scope_override(plan=_plan, max_files=_max_files):
                    _do_review()
            except Exception as exc:
                logger.error("[PRAnalyze] PR #%s failed: %s", pr_number, exc)
                mark_review_pending(pr_number, repo)

        def _do_review():
            try:
                mark_review_started(pr_number, repo)
                diff = _fetch_diff(diff_url)
                if wide:
                    # Re-review the FILES the last pass never saw. The freeform prompt
                    # below would use the SAME capped window and drop the SAME files, so
                    # route the whole diff through the coverage-aware path instead: its
                    # size rule (#6023) already escalates an over-window diff to the
                    # patient full-window reviewer, and it re-stamps an honest coverage
                    # note if anything still falls out — a clean re-review can never read
                    # like the #5836 approval that only saw part of the diff.
                    summary = _obtain_review_summary(review, diff, pr_number, repo)
                else:
                    prompt = _build_prompt(review, diff)
                    # DHQ dispatch — goes through queue+orchestration pipeline
                    summary = _run_forge_review(prompt)
                if summary:
                    mark_review_done(pr_number, summary, repo)
                    _notify_pr_reviewed(pr_number, repo, review.get("title", ""), summary)
                else:
                    mark_review_pending(pr_number, repo)
            except Exception as exc:
                logger.error("[PRAnalyze] PR #%s failed: %s", pr_number, exc)
                mark_review_pending(pr_number, repo)

        t = threading.Thread(target=_run_in_background, daemon=True)
        t.start()

        return (
            jsonify(
                {
                    "success": True,
                    "status": "analyzing",
                    "pr_number": pr_number,
                    "message": "F.O.R.G.E. review dispatched — auto-refreshes in 60s",
                }
            ),
            202,
        )

    @bp.route("/api/forge/review-scope", methods=["GET"])
    @login_required
    @admin_required
    def forge_review_scope():
        """The EFFECTIVE review-scope defaults, read through the pipeline's own accessors.

        Feeds the PR Review tab's scope control so it opens on the real current
        values instead of hardcoded ones — a control showing a stale default is
        how an operator "changes" a setting that was never in effect.

        Read-only: the per-send override travels with the analyze POST, so
        nothing here mutates state.
        """
        try:
            from .services.pr_diff_analyzer import forge_settings_snapshot

            snap = forge_settings_snapshot()
            return jsonify(
                {
                    "success": True,
                    "plan": snap.get("forge:review_plan"),
                    "max_files": snap.get("forge:review_max_files"),
                    "max_chunks": snap.get("forge:review_max_chunks"),
                    # The clamp the server applies regardless of what is sent, so
                    # the control cannot offer a value the backend would silently
                    # reduce.
                    "max_files_ceiling": 25,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("forge_review_scope: %s", exc)
            return jsonify({"success": False, "error": str(exc)[:200]}), 500

    @bp.route("/api/forge/pr-reviews/analyze-all", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_review_analyze_all():
        """Bulk-dispatch F.O.R.G.E. reviews for all pending PRs.

        Returns 202 immediately — each PR is queued through DHQ in a background
        thread. This is the endpoint behind the F.O.R.G.E. chat 'analyze all' action.
        """
        import threading

        from .services.pr_review_service import (
            get_pending_reviews,
            mark_review_started,
            mark_review_done,
            mark_review_pending,
        )
        from .services.pr_diff_analyzer import (
            _fetch_diff,
            _build_prompt,
            _run_forge_review,
            _notify_pr_reviewed,
        )

        reviews = get_pending_reviews(limit=50)
        if not reviews:
            return jsonify({"success": True, "queued": 0, "message": "No pending PRs to review"}), 200

        def _analyze_one(review):
            pr_number = review["pr_number"]
            repo = review.get("repo", "KytranKatarn/archie-platform")
            diff_url = review.get("diff_url")
            if not diff_url:
                return
            try:
                mark_review_started(pr_number, repo)
                diff = _fetch_diff(diff_url)
                prompt = _build_prompt(review, diff)
                summary = _run_forge_review(prompt)
                if summary:
                    mark_review_done(pr_number, summary, repo)
                    _notify_pr_reviewed(pr_number, repo, review.get("title", ""), summary)
                else:
                    mark_review_pending(pr_number, repo)
            except Exception as exc:
                logger.error("[PRAnalyzeAll] PR #%s failed: %s", pr_number, exc)
                mark_review_pending(pr_number, repo)

        for review in reviews:
            t = threading.Thread(target=_analyze_one, args=(review,), daemon=True)
            t.start()

        return (
            jsonify(
                {
                    "success": True,
                    "queued": len(reviews),
                    "message": f"F.O.R.G.E. reviewing {len(reviews)} PRs — check back in a few minutes",
                }
            ),
            202,
        )

    @bp.route("/api/forge/pr-reviews/<int:pr_number>/skip", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_review_skip(pr_number):
        """Mark a PR as skipped (no AI review needed)."""
        from .services.pr_review_service import mark_review_skipped

        mark_review_skipped(pr_number)
        return jsonify({"success": True})

    @bp.route("/api/forge/pr-reviews/<int:pr_number>/retry", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_review_retry(pr_number):
        """Cancel a stuck 'Reviewing…' and put the PR back in the review queue.

        The escape hatch for an orphaned review: ``mark_review_started`` set the row
        'in_progress', its dispatch then died, and ``mark_review_done`` never ran (KB
        #270002). ``reap_stale_reviews`` already recovers these, but only after a 20m
        window on a 5m tick — so until now an operator who could SEE it was stuck had
        no way to act, and the Analyze button is disabled in exactly that state.

        ⚠️ DELIBERATELY NARROW: 'in_progress' only. Resetting a *reviewed* row would
        discard a stored verdict, and that verdict is what the merge gate reads — so a
        stray click here could turn a REQUEST CHANGES into a fresh, possibly-different
        review. Re-reviewing a finished PR already has its own affordance (Analyze).
        Everything else is refused with 409 and the row is left exactly as it was.

        ⚠️ Repo comes from the BODY, like the merge routes: PR numbers collide across
        repos (1-20 each exist in 2-5 of them), so a bare lookup silently resolves a
        plausible WRONG row rather than erroring.
        """
        from .services.pr_review_service import (
            _is_valid_repo,
            get_review,
            mark_review_pending,
            review_progress,
        )

        _repo_in = (request.get_json(silent=True) or {}).get("repo")
        if _repo_in is not None and not _is_valid_repo(_repo_in):
            return jsonify({"success": False, "error": "Invalid repo"}), 400

        review = get_review(pr_number, repo=_repo_in or None)
        if not review:
            return jsonify({"success": False, "error": f"PR #{pr_number} not found"}), 404

        status = review.get("review_status")
        if status != "in_progress":
            return (
                jsonify(
                    {
                        "success": False,
                        "error": (
                            f"PR #{pr_number} is '{status}', not a review in flight. "
                            "Retry only cancels a stuck review; use Analyze to re-review."
                        ),
                        "review_status": status,
                    }
                ),
                409,
            )

        prog = review_progress(status, review.get("updated_at"))
        mark_review_pending(pr_number, repo=_repo_in or None)
        logger.info(
            "[F.O.R.G.E.] review retry: PR #%s (%s) reset after %sm in_progress by %s",
            pr_number,
            _repo_in or "default repo",
            prog.get("elapsed_minutes"),
            getattr(current_user, "username", "?"),
        )
        # reap_count is deliberately left alone: a human retry should not hand a
        # permanently-broken review a fresh budget to loop on.
        return jsonify(
            {
                "success": True,
                "pr_number": pr_number,
                "was_running_minutes": prog.get("elapsed_minutes"),
                "review_status": "pending",
            }
        )

    @bp.route("/api/forge/pr-reviews/<int:pr_number>/merge", methods=["POST"])
    @login_required
    @admin_required
    def forge_pr_review_merge(pr_number):
        """Merge a PR via GitHub API (squash merge). State syncs on next poll cycle."""
        from .services.pr_review_service import get_review
        from .services.github_service import merge_pr

        # Same cross-repo lookup as forge_merge_pr (2026-09-11): the row's repo comes with
        # the request; without it a cross-repo PR's verdict is looked up in the wrong repo.
        from .services.pr_review_service import _is_valid_repo

        _repo_in = (request.get_json(silent=True) or {}).get("repo")
        if _repo_in is not None and not _is_valid_repo(_repo_in):
            return jsonify({"success": False, "error": "Invalid repo"}), 400
        review = get_review(pr_number, repo=_repo_in or None)
        if not review:
            return jsonify({"error": f"PR #{pr_number} not found"}), 404

        # #5834 PARITY — same rule as the Approvals tab: the override clears AUTHORITY,
        # never the SAFETY property that an approving verdict exists. `review` being
        # non-None only proves a review ROW exists; it says nothing about the verdict.
        try:
            from .services.github_service import verdict_refusal
            from .services.pr_review_service import coverage_dropped_paths, verdict_is_approved

            _summary = review.get("ai_summary") or ""
            _ack = bool((request.get_json(silent=True) or {}).get("coverage_ack"))
            _refusal = verdict_refusal(_summary, bool(_summary) and verdict_is_approved(_summary), coverage_ack=_ack)
            _dropped = coverage_dropped_paths(_summary) if _refusal else []
        except Exception as _exc:  # noqa: BLE001
            _refusal = f"could not verify the verdict ({_exc}) — refusing rather than guessing"
            _dropped = []
        if _refusal:
            logger.warning("[FORGE] refusing merge of PR #%s: %s", pr_number, _refusal)
            return (
                jsonify(
                    {
                        "success": False,
                        "merged": False,
                        "error": _refusal,
                        "coverage_only": _refusal.startswith("COVERAGE ONLY"),
                        "dropped_files": _dropped,
                    }
                ),
                422,
            )

        # #4494: merge against the PR's OWN repo (watch-product PRs live in separate repos).
        # human_override: @login_required @admin_required — an attended operator merge,
        # so it bypasses the unattended-merge governance gate (#5194).
        result = merge_pr(pr_number, method="squash", repo=review.get("repo"), human_override=True)

        if result.get("merged"):
            return jsonify({"success": True, "merged": True, "message": result.get("message", "Merged")})
        else:
            err = result.get("error", "Merge failed")
            return jsonify({"success": False, "merged": False, "error": err}), 422
