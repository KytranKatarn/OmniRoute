"""PR Review Service — GitHub polling + review state management.

Phase 1 of the PR Review Pipeline (Project #247, Task #1799).
Polls GitHub for open PRs, upserts into pr_reviews, tracks AI review state.
Phase 2 (F.O.R.G.E. AI review) and Phase 3 (Repair Bay UI) build on this.
"""

from __future__ import annotations

import logging
import os
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

_DEFAULT_REPO = os.getenv("GITHUB_REPO", "KytranKatarn/archie-platform")


def get_tracked_repos() -> list:
    """Return repos to poll. Reads GITHUB_REPOS (comma-separated) or falls back to GITHUB_REPO."""
    repos_env = os.getenv("GITHUB_REPOS", "").strip()
    if repos_env:
        return [r.strip() for r in repos_env.split(",") if r.strip()]
    return [_DEFAULT_REPO]


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def poll_open_prs(repo: str = None) -> dict:
    """Poll GitHub for open PRs and upsert into pr_reviews.

    Returns:
        dict: {polled, inserted, updated, errors}
    """
    from tools.repair_bay.services.github_service import list_all_prs_enriched

    _repo = repo or _DEFAULT_REPO
    try:
        data = list_all_prs_enriched("open")
    except Exception as e:
        logger.error("pr_review_service: GitHub poll failed: %s", e)
        return {"polled": 0, "inserted": 0, "updated": 0, "errors": 1}

    prs = data.get("prs", [])
    inserted = updated = errors = 0

    for pr in prs:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO pr_reviews
                        (pr_number, repo, title, author, state,
                         base_branch, head_branch, diff_url,
                         additions, deletions, changed_files,
                         last_polled_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (pr_number, repo) DO UPDATE SET
                        title          = EXCLUDED.title,
                        state          = EXCLUDED.state,
                        diff_url       = EXCLUDED.diff_url,
                        additions      = EXCLUDED.additions,
                        deletions      = EXCLUDED.deletions,
                        changed_files  = EXCLUDED.changed_files,
                        updated_at     = NOW(),
                        last_polled_at = NOW()
                    RETURNING (xmax = 0) AS is_new
                    """,
                    (
                        pr.get("number"),
                        _repo,
                        pr.get("title", ""),
                        pr.get("user") if isinstance(pr.get("user"), str) else (pr.get("user") or {}).get("login"),
                        pr.get("state", "open"),
                        (pr.get("base") or {}).get("ref"),
                        (pr.get("head") or {}).get("ref") or pr.get("head_ref"),
                        pr.get("diff_url"),
                        pr.get("additions"),
                        pr.get("deletions"),
                        pr.get("changed_files"),
                    ),
                )
                row = cur.fetchone()
                if row and row["is_new"]:
                    inserted += 1
                else:
                    updated += 1
        except Exception as e:
            logger.error("pr_review_service: upsert failed for PR #%s: %s", pr.get("number"), e)
            errors += 1

    logger.info(
        "pr_review_service: poll done — %d polled, %d inserted, %d updated, %d errors",
        len(prs),
        inserted,
        updated,
        errors,
    )
    return {"polled": len(prs), "inserted": inserted, "updated": updated, "errors": errors}


def sync_closed_prs(repo: str = None) -> int:
    """Mark pr_reviews rows as closed/merged when the PR is no longer open on GitHub."""
    from tools.repair_bay.services.github_service import list_all_prs_enriched

    _repo = repo or _DEFAULT_REPO
    try:
        open_data = list_all_prs_enriched("open")
    except Exception as e:
        logger.error("pr_review_service: sync_closed poll failed: %s", e)
        return 0

    open_numbers = {pr["number"] for pr in open_data.get("prs", [])}
    updated = 0
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE pr_reviews SET state = 'closed', updated_at = NOW()
                WHERE repo = %s AND state = 'open'
                  AND pr_number NOT IN %s
                """,
                (_repo, tuple(open_numbers) if open_numbers else (0,)),
            )
            updated = cur.rowcount
    except Exception as e:
        logger.error("pr_review_service: sync_closed update failed: %s", e)
    return updated


# ---------------------------------------------------------------------------
# Review state management
# ---------------------------------------------------------------------------


def get_pending_reviews(limit: int = 10) -> list:
    """Return open PRs ready for AI review, oldest first.

    Includes rows stuck in 'in_progress' for >20 minutes so they can be retried.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT * FROM pr_reviews
            WHERE state = 'open'
              AND (
                review_status = 'pending'
                OR (
                    review_status = 'in_progress'
                    AND updated_at < NOW() - INTERVAL '20 minutes'
                )
              )
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def mark_review_started(pr_number: int, repo: str = None) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET review_status='in_progress', updated_at=NOW() WHERE pr_number=%s AND repo=%s",
            (pr_number, repo or _DEFAULT_REPO),
        )


def mark_review_done(pr_number: int, summary: str, repo: str = None, auto_merge: bool = True) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE pr_reviews
            SET review_status='reviewed', ai_summary=%s, ai_review_at=NOW(), updated_at=NOW()
            WHERE pr_number=%s AND repo=%s
            """,
            (summary, pr_number, repo or _DEFAULT_REPO),
        )

    if not auto_merge:
        return

    # Auto-merge when F.O.R.G.E. explicitly approves the PR
    if not re.search(r"VERDICT\s*[:—]\s*APPROVED", summary, re.IGNORECASE):
        return

    try:
        from .github_service import merge_pr

        result = merge_pr(pr_number, "squash")
        if result.get("merged"):
            logger.info("[F.O.R.G.E.] PR #%s auto-merged after approval", pr_number)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO system_notifications (title, message, type, source, visibility) "
                    "VALUES (%s, %s, 'success', 'forge', 'all')",
                    (
                        f"F.O.R.G.E. merged PR #{pr_number}",
                        f"PR #{pr_number} was approved by F.O.R.G.E. and auto-merged.",
                    ),
                )
        else:
            logger.warning("[F.O.R.G.E.] Auto-merge failed for PR #%s: %s", pr_number, result)
    except Exception as e:
        logger.error("[F.O.R.G.E.] Auto-merge error for PR #%s: %s", pr_number, e)


def mark_review_skipped(pr_number: int, repo: str = None) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET review_status='skipped', updated_at=NOW() WHERE pr_number=%s AND repo=%s",
            (pr_number, repo or _DEFAULT_REPO),
        )


def mark_review_pending(pr_number: int, repo: str = None) -> None:
    """Reset a review back to pending so it will be re-processed next cycle."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET review_status='pending', updated_at=NOW() WHERE pr_number=%s AND repo=%s",
            (pr_number, repo or _DEFAULT_REPO),
        )


def list_reviews(state: str = None, review_status: str = None, limit: int = 50) -> list:
    """List PR reviews with optional filters."""
    query = "SELECT * FROM pr_reviews WHERE 1=1"
    params: list = []
    if state:
        query += " AND state = %s"
        params.append(state)
    if review_status:
        query += " AND review_status = %s"
        params.append(review_status)
    query += " ORDER BY updated_at DESC LIMIT %s"
    params.append(limit)
    with get_db_cursor() as (conn, cur):
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def get_review(pr_number: int, repo: str = None) -> dict | None:
    """Fetch a single PR review by number."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM pr_reviews WHERE pr_number=%s AND repo=%s",
            (pr_number, repo or _DEFAULT_REPO),
        )
        row = cur.fetchone()
        return dict(row) if row else None
