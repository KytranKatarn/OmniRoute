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
    get_review,
    mark_review_done,
    mark_review_pending,
    mark_review_started,
    parse_verdict,
    poll_open_prs,
)

logger = logging.getLogger(__name__)

_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
# Raised from 6000: a 7B/12B has headroom, and a bigger window means fewer truncations
# (truncation mid-file was a direct cause of false 'no tests'/'unclosed loop' flags).
_DIFF_MAX_CHARS = 12000

# Phase-1 anti-hallucination rubric (project #381). Seeded from the 2026-06-22 review where
# F.O.R.G.E. (qwen2.5:7b) hallucinated flags on ~8/10 verified-correct PRs. Each rule maps to
# a confirmed false positive. Prepended to every review prompt so the 7B stops repeating them.
_FALSE_POSITIVE_RUBRIC = (
    "GROUND RULES — these are COMMON FALSE POSITIVES; do NOT flag them as issues:\n"
    "1. Parameterized SQL (psycopg2 %s placeholders / query params) is NOT SQL injection. Only "
    "string-concatenated or f-string SQL built from user input is.\n"
    "2. A file that COMPILES and PASSES TESTS has no syntax error, missing semicolon, or unclosed "
    "loop/bracket. Python statements need no semicolons.\n"
    "3. A test file added IN THIS SAME DIFF means tests WERE added — never claim 'no tests'.\n"
    "4. Importing one shared function from multiple call sites is REUSE (DRY), not duplication.\n"
    "5. A platform_settings/env read with a code default fallback is intentional, not a missing value.\n"
    "6. A bare hash/string built for an md5/dedup key is NOT SQL and has no injection surface.\n"
    "7. Do NOT call an import or variable 'unused' or 'removed' unless you can SEE it is never "
    "referenced anywhere in the changes shown. If the diff is truncated, NEVER raise "
    "unused/missing/removed-symbol issues — you cannot see all usages.\n"
    "EVIDENCE RULE: for EVERY issue, quote the '+' or '-' diff line VERBATIM as it appears below. "
    "NEVER invent a line number or a line that is not present in the diff. A fabricated citation is "
    "worse than no issue — if you cannot find the exact line below, DO NOT raise the issue.\n"
    "VERDICT RULE: only [CRITICAL] or [WARNING] issues justify REQUEST CHANGES. If the only issues "
    "are [INFO] (or there are none), the VERDICT MUST be APPROVE — INFO notes never block a merge.\n"
)


def review_pr(pr_number: int, repo: str = None) -> dict:
    """Grounded on-demand review of a single PR.

    Single entry point for diff-grounded F.O.R.G.E. review: fetches the REAL
    unified diff, builds the prompt with it, dispatches, and stores the result.
    Use this instead of hand-rolling a prompt from just the title + diff_url —
    a bare diff_url passed as prompt text is not fetchable by the local model
    and produces generic, ungrounded "reviews" (the failure mode behind the
    boilerplate OWASP verdicts).

    Returns:
        dict: {ok, pr_number, verdict, summary, error}
    """
    review = get_review(pr_number, repo)
    if not review:
        # Not tracked yet — poll once, then retry.
        poll_open_prs(repo)
        review = get_review(pr_number, repo)
    if not review:
        return {"ok": False, "pr_number": pr_number, "error": "PR not tracked"}

    _repo = review.get("repo") or repo
    diff_url = review.get("diff_url")
    if not diff_url:
        return {"ok": False, "pr_number": pr_number, "error": "no diff_url"}

    try:
        mark_review_started(pr_number, _repo)
        diff = _fetch_diff(diff_url)
        summary = _run_forge_review(_build_prompt(review, diff), pr_number, _repo)
        if not summary:
            mark_review_pending(pr_number, _repo)
            return {
                "ok": False,
                "pr_number": pr_number,
                "status": "queued",
                "error": "queued — F.O.R.G.E. model cold-loading; verdict lands async via callback",
            }
        mark_review_done(pr_number, summary, _repo)
        _notify_pr_reviewed(pr_number, _repo, review.get("title", ""), summary)
        # Single source of truth — same parser the merge gate + tier classifier use.
        verdict = parse_verdict(summary)
        return {"ok": True, "pr_number": pr_number, "verdict": verdict, "summary": summary}
    except Exception as exc:
        logger.error("[PR Review] review_pr #%s failed: %s", pr_number, exc)
        try:
            mark_review_pending(pr_number, _repo)
        except Exception:
            pass
        return {"ok": False, "pr_number": pr_number, "error": str(exc)}


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
            summary = _run_forge_review(prompt, pr_number, repo)

            if summary:
                mark_review_done(pr_number, summary, repo)
                _notify_pr_reviewed(pr_number, repo, review.get("title", ""), summary)
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


def _truncate_diff(diff: str) -> tuple:
    """Truncate at the last complete hunk boundary (``\\n@@``) before the cap so no file is
    cut mid-statement — a byte cut produced the false 'no tests added' (test file sliced off)
    and 'unclosed loop' (loop body sliced) flags. Returns ``(content, truncated)``."""
    if len(diff) <= _DIFF_MAX_CHARS:
        return diff, False
    cut = diff.rfind("\n@@", 0, _DIFF_MAX_CHARS)
    return (diff[:cut] if cut > 0 else diff[:_DIFF_MAX_CHARS]), True


def _build_prompt(review: dict, diff: str) -> str:
    """Assemble the F.O.R.G.E. code review prompt with an anti-hallucination grounding rubric
    + a hunk-boundary-safe diff window (Phase-1 agent-optimization, project #381)."""
    diff_content, truncated = _truncate_diff(diff)
    truncation_note = (
        f"\n[Note: diff truncated to ~{_DIFF_MAX_CHARS} chars at a hunk boundary — the shown "
        "hunks are COMPLETE; judge only the changes you can see, do not infer about omitted files.]\n"
        if truncated
        else ""
    )

    return f"""You are F.O.R.G.E., A.R.C.H.I.E.'s Full-cycle Optimization & Regenerative GitHub Engine.
Review this pull request diff and provide a structured code review.

{_FALSE_POSITIVE_RUBRIC}
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
- [CRITICAL] <issue> — <why it matters> — Evidence: <exact + or - diff line>
- [WARNING] <issue> — <why it matters> — Evidence: <exact + or - diff line>
- [INFO] <issue> — <why it matters> — Evidence: <exact + or - diff line>
(List ONLY real issues you can tie to a specific diff line shown above. Apply the GROUND RULES
first — most rejected reviews fail there. If none, write: No issues found.)

VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW"""


def _attach_pr_review_callback(queue_id: int, pr_number: int, repo: str) -> None:
    """Attach a ``pr_review_result`` callback to a queued code_review dispatch.

    When the F.O.R.G.E. review model is cold/saturated the dispatcher enqueues
    the job (dispatch_pending_queue) and returns ``queued=True`` immediately —
    the synchronous call has no response yet. Without a callback the review was
    left ``pending`` forever ("empty/queued review"). This mirrors
    ``delegation_service._attach_delegation_callback``: when
    ``model_dispatch_worker`` finishes the cold-load job, ``_handle_callback``
    (model_dispatch_service) writes the verdict back to ``pr_reviews`` and flips
    ``review_status='reviewed'``. Only rows still awaiting execution are tagged.
    """
    try:
        import json

        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                   SET callback_type = 'pr_review_result',
                       callback_data = %s::jsonb
                 WHERE id = %s AND status IN ('queued', 'running')
                """,
                (json.dumps({"pr_number": pr_number, "repo": repo}), queue_id),
            )
    except Exception as exc:
        logger.warning("[PR Review] failed to attach callback to queue #%s: %s", queue_id, exc)


def _apply_severity_gate(review_text: str) -> str:
    """Deterministic post-guard (Phase-1 agent-optimization, project #381): a review whose
    issues are all ``[INFO]`` (or has none) must NOT yield REQUEST CHANGES. An INFO-level lint —
    or a fabricated INFO nit — cannot block a PR. Closes the #1869 over-block surfaced by the
    Phase-1 adversarial verification (a real, USED ``import time`` was flagged 'unused' as INFO
    and escalated to REQUEST CHANGES on 2/3 runs, once with a fabricated diff line as evidence).
    ``[CRITICAL]``/``[WARNING]`` issues still block normally — the gate only relaxes, never tightens.
    """
    import re

    if not review_text:
        return review_text
    has_blocking = re.search(r"\[\s*(CRITICAL|WARNING)\s*\]", review_text, re.IGNORECASE)
    asks_changes = re.search(r"VERDICT:\s*REQUEST\s+CHANGES", review_text, re.IGNORECASE)
    if asks_changes and not has_blocking:
        review_text = re.sub(
            r"(VERDICT:\s*)REQUEST\s+CHANGES",
            r"\1APPROVE",
            review_text,
            flags=re.IGNORECASE,
        )
        review_text += (
            "\n\n[severity-gate] Verdict downgraded REQUEST CHANGES → APPROVE: only INFO-level "
            "issues were raised, which do not block a merge (Phase-1 calibration, project #381)."
        )
    return review_text


def _run_forge_review(prompt: str, pr_number: int = None, repo: str = None) -> str | None:
    """Dispatch the review prompt to F.O.R.G.E. via Bridge.

    Returns the summary string from F.O.R.G.E., or ``None``. ``None`` means
    either a hard failure OR that the dispatch was deferred to the cold-load
    queue — in the queued case an async ``pr_review_result`` callback is
    attached (when ``pr_number`` is known) so the verdict lands when the model
    warms, instead of the review staying stuck pending.
    """
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability="code_review",
            prompt=prompt,
            module_id="repair_bay",
            # Pin PR review to capable nodes (#4300): the RTX 3070 Defiant (246)
            # when it's up, else the always-on hub M4000 — both run F.O.R.G.E.'s
            # 7B reliably. This explicitly EXCLUDES the 4GB Runabout (245), where
            # mistral:7b stalls mid-review and leaves the row stuck 'in_progress'.
            # Explicit preferred_node wins over CAPABILITY_NODE_AFFINITY.
            preferred_node=[
                "starship_76583490e36955ab",
                "archie-starbase",
            ],  # node_id (rename-safe): Defiant(.246) RTX3070 then hub M4000; excludes 4GB Runabout (#4342)
        )
        if getattr(result, "queued", False):
            qid = getattr(result, "queue_id", None)
            if qid and pr_number:
                _attach_pr_review_callback(qid, pr_number, repo)
                logger.info(
                    "[PR Review] F.O.R.G.E. dispatch queued (#%s) — callback attached, completes async",
                    qid,
                )
            else:
                logger.info("[PR Review] F.O.R.G.E. dispatch queued — model cold-loading, will retry")
            return None
        if result.success and result.response:
            return _apply_severity_gate(result.response.strip())
        logger.warning("[PR Review] F.O.R.G.E. dispatch returned no response: success=%s", result.success)
        return None
    except Exception as exc:
        logger.error("[PR Review] F.O.R.G.E. dispatch error: %s", exc)
        raise


def _notify_pr_reviewed(pr_number: int, repo: str, title: str, ai_summary: str) -> None:
    """Submit a PR review completion notification to the director_reports inbox.

    Routes through the Unified Voice triage consumer, which adds URL keyboard
    buttons (View in Repair Bay + View on GitHub) before sending to Telegram.
    """
    import re as _re
    from services.director_report_service import submit_via_inbox

    # Single source of truth — same parser the merge gate + tier classifier use.
    verdict = parse_verdict(ai_summary)

    snippet = ""
    if ai_summary:
        m = _re.search(r"SUMMARY\s*([\s\S]{1,200})", ai_summary, _re.IGNORECASE)
        if m:
            snippet = m.group(1).strip()

    _repo = repo or "KytranKatarn/archie-platform"
    github_url = f"https://github.com/{_repo}/pull/{pr_number}/files"
    platform_url = "http://192.168.1.200:3000/tools/repair-bay#pr-review"

    message = (
        f"VERDICT: {verdict}\n\n" f"{snippet}\n\n" f"View in Repair Bay: {platform_url}\n" f"GitHub PR: {github_url}"
    )

    try:
        submit_via_inbox(
            category="pr_reviewed",
            title=f"F.O.R.G.E. Review: {verdict} — {_repo}#{pr_number}: {title[:60]}",
            message=message,
            source_agent="F.O.R.G.E.",
            severity="info",
            department="Engineering & Technology",
        )
    except Exception as exc:
        logger.warning(
            "[PR Review] Failed to submit Telegram notification for PR #%s: %s",
            pr_number,
            exc,
        )
