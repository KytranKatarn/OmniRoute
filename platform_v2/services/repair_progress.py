"""Live Code Health patch, review and merge progress."""

from database import get_db_cursor


def progress(proposal):
    """Return a live stage; approval queue tiers and PR merge tiers remain distinct."""
    from services.repair_submission import metadata

    meta = metadata(proposal.get("metadata"))
    submission = dict(meta.get("repair_submission") or {})
    stage = submission.get("stage", "patch_ready" if proposal.get("status") == "ready_for_review" else "generation")
    result = {"stage": stage, "submission": submission, "pr_number": meta.get("pr_number")}
    with get_db_cursor(commit=False) as (_, cur):
        from services.planned_repair_service import planned_progress

        result["planned_work"] = planned_progress(proposal, cur)
        if result["planned_work"].get("stage") and not meta.get("pr_number"):
            result["stage"] = result["planned_work"]["stage"]
        if meta.get("pr_number"):
            cur.execute(
                "SELECT * FROM pr_reviews WHERE pr_number=%s AND repo=%s",
                (meta["pr_number"], "KytranKatarn/archie-platform"),
            )
            review = cur.fetchone()
            if review:
                from tools.repair_bay.services.pr_review_service import classify_pr_tier, verdict_is_approved

                result["merge_tier"] = classify_pr_tier(dict(review))
                result["review_status"] = review.get("review_status")
                if meta.get("repair_verification") and proposal.get("status") == "deployed":
                    result["stage"] = "verified_complete"
                elif review.get("state") == "merged":
                    result["stage"] = "merged_awaiting_verification"
                elif review.get("state") == "closed":
                    result["stage"] = "pr_closed_unmerged"
                elif (
                    review.get("review_status") == "reviewed"
                    and metadata(review.get("metadata")).get("head_sha")
                    and metadata(review.get("metadata")).get("head_sha")
                    == metadata(review.get("metadata")).get("reviewed_head_sha")
                    and verdict_is_approved(review.get("ai_summary") or "")
                ):
                    result["stage"] = (
                        "awaiting_human_merge"
                        if result["merge_tier"] == 3 or metadata(review.get("metadata")).get("kytran_approval_sent")
                        else "awaiting_governed_merge"
                    )
                else:
                    result["stage"] = "pr_review"
        elif submission.get("approval_id"):
            cur.execute("SELECT status FROM autonomy_approval_queue WHERE id=%s", (submission["approval_id"],))
            row = cur.fetchone()
            result["approval_status"] = row and row["status"]
            if row and row["status"] in ("failed", "rejected", "expired", "cancelled"):
                result["stage"] = "blocked"
        elif submission.get("queue_id"):
            cur.execute("SELECT status FROM dispatch_pending_queue WHERE id=%s", (submission["queue_id"],))
            row = cur.fetchone()
            result["queue_status"] = row and row["status"]
            if row and row["status"] in ("failed", "cancelled"):
                result["stage"] = "blocked"
    if meta.get("merged_pr"):
        result["stage"] = (
            "verified_complete"
            if meta.get("repair_verification") and proposal.get("status") == "deployed"
            else "merged_awaiting_verification"
        )
    return result
