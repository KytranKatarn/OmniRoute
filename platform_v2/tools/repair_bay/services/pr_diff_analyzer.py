"""PR Diff Analyzer — Phase 2 of the PR Review Pipeline.

Fetches GitHub diffs for pending PR reviews and dispatches them to F.O.R.G.E.
via the Bridge dispatcher for AI code review. Results stored in pr_reviews.ai_summary.
"""

from __future__ import annotations

import logging
import os

import requests

from tools.repair_bay.services.pr_review_service import (
    get_pending_reviews,
    mark_review_done,
    mark_review_pending,
    mark_review_started,
)

logger = logging.getLogger(__name__)

_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_DIFF_MAX_CHARS = 6000


def analyze_pending_prs(max_prs: int = 3) -> dict:
    """Process up to max_prs pending reviews with F.O.R.G.E. AI analysis.

    Returns:
        dict: {processed, failed, skipped}
    """
    reviews = get_pending_reviews(limit=max_prs)
    processed = failed = skipped = 0

    for review in reviews:
        pr_number = review["pr_number"]
        repo = review.get("repo", "KytranKatarn/archie-platform")

        try:
            mark_review_started(pr_number, repo)

            diff_url = review.get("diff_url")
            if not diff_url:
                logger.warning("[PR Review] PR #%s has no diff_url — skipping", pr_number)
                from tools.repair_bay.services.pr_review_service import mark_review_skipped

                mark_review_skipped(pr_number, repo)
                skipped += 1
                continue

            diff = _fetch_diff(diff_url)
            prompt = _build_prompt(review, diff)
            summary = _run_forge_review(prompt)

            if summary:
                mark_review_done(pr_number, summary, repo)
                processed += 1
            else:
                logger.warning("[PR Review] F.O.R.G.E. returned empty summary for PR #%s", pr_number)
                mark_review_pending(pr_number, repo)
                failed += 1

        except Exception as exc:
            logger.error("[PR Review] PR #%s analysis failed: %s", pr_number, exc)
            try:
                mark_review_pending(pr_number, repo)
            except Exception as reset_err:
                logger.error("[PR Review] Failed to reset PR #%s status: %s", pr_number, reset_err)
            failed += 1

    logger.info(
        "[PR Review] Cycle complete — processed=%d failed=%d skipped=%d",
        processed,
        failed,
        skipped,
    )
    return {"processed": processed, "failed": failed, "skipped": skipped}


def _fetch_diff(diff_url: str) -> str:
    """Fetch raw unified diff from GitHub.

    Raises:
        RuntimeError: If GitHub returns non-200.
    """
    headers = {"Accept": "application/vnd.github.v3.diff"}
    if _GITHUB_TOKEN:
        headers["Authorization"] = f"token {_GITHUB_TOKEN}"

    resp = requests.get(diff_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub diff fetch failed: {resp.status_code} for {diff_url}")
    return resp.text


def _build_prompt(review: dict, diff: str) -> str:
    """Assemble the F.O.R.G.E. code review prompt. Truncates diff at _DIFF_MAX_CHARS."""
    truncated = len(diff) > _DIFF_MAX_CHARS
    diff_content = diff[:_DIFF_MAX_CHARS] if truncated else diff
    truncation_note = "\n[Note: diff truncated to first 6000 chars due to size.]\n" if truncated else ""

    return f"""You are F.O.R.G.E., A.R.C.H.I.E.'s Full-cycle Optimization & Regenerative GitHub Engine.
Review this pull request diff and provide a structured code review.

PR #{review['pr_number']} — {review['title']}
Author: {review.get('author', 'unknown')} | Repo: {review.get('repo', '')}
Changes: +{review.get('additions', 0)} -{review.get('deletions', 0)} across {review.get('changed_files', 0)} files

--- DIFF ---
{diff_content}
--- END DIFF ---
{truncation_note}
Provide your review in this exact format:

SUMMARY
One paragraph describing what this PR does and its overall quality.

ISSUES
- [CRITICAL] <issue> — <why it matters>
- [WARNING] <issue> — <why it matters>
- [INFO] <issue> — <why it matters>
(List only real issues. If none found, write: No issues found.)

VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW"""


def _run_forge_review(prompt: str) -> str | None:
    """Dispatch the review prompt to F.O.R.G.E. via Bridge.

    Returns:
        Summary string from F.O.R.G.E., or None on failure.
    """
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability="code_review",
            prompt=prompt,
            module_id="repair_bay",
        )
        if result.success and result.response:
            return result.response.strip()
        logger.warning("[PR Review] F.O.R.G.E. dispatch returned no response: success=%s", result.success)
        return None
    except Exception as exc:
        logger.error("[PR Review] F.O.R.G.E. dispatch error: %s", exc)
        raise
