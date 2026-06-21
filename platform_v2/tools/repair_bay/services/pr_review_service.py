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


# ---------------------------------------------------------------------------
# Verdict parsing — SINGLE SOURCE OF TRUTH
# ---------------------------------------------------------------------------
#
# The review prompt (pr_diff_analyzer._build_prompt) instructs F.O.R.G.E. to
# emit `VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW`. Every consumer
# (auto-merge gate, tier classifier, notifications) MUST parse the verdict via
# this one function so the emitted token and the checked token can never drift.
#
# Backward compatibility: older stored summaries may contain `APPROVED`, so the
# approval pattern accepts both `APPROVE` and `APPROVED`. Word boundaries
# (\bAPPROVED?\b) prevent false positives — `\bAPPROVE\b` does NOT match inside
# `NOT APPROVED`'s surrounding text incorrectly, and REQUEST CHANGES / REJECT
# are checked FIRST so a "NOT APPROVED — request changes" summary classifies as
# a change request rather than an approval.

# Order matters: rejection/change patterns are evaluated before approval so that
# negative verdicts can never be mis-read as an approval.
_VERDICT_REJECT_RE = re.compile(r"VERDICT\s*[:\-—]\s*(?:REQUEST\s+CHANGES|REJECT)", re.IGNORECASE)
_VERDICT_NEEDS_RE = re.compile(r"VERDICT\s*[:\-—]\s*NEEDS\s+REVIEW", re.IGNORECASE)
# \bAPPROVED?\b matches the emitted "APPROVE" and legacy "APPROVED" only as a
# whole word — it will not match a substring inside another token.
_VERDICT_APPROVE_RE = re.compile(r"VERDICT\s*[:\-—]\s*APPROVED?\b", re.IGNORECASE)


def parse_verdict(summary_or_text: str | None) -> str:
    """Parse a F.O.R.G.E. review summary into a canonical verdict token.

    Returns one of:
        "APPROVE" | "REQUEST CHANGES" | "NEEDS REVIEW" | "REVIEWED"

    "REVIEWED" is the fallback when no explicit VERDICT line is present.
    Accepts both the emitted "APPROVE" and the legacy "APPROVED" token on the
    read side; the emit side is always "APPROVE".
    """
    if not summary_or_text:
        return "REVIEWED"
    text = summary_or_text
    # Check negative verdicts first so they can never be misread as approval.
    if _VERDICT_REJECT_RE.search(text):
        return "REQUEST CHANGES"
    if _VERDICT_NEEDS_RE.search(text):
        return "NEEDS REVIEW"
    if _VERDICT_APPROVE_RE.search(text):
        return "APPROVE"
    return "REVIEWED"


def verdict_is_approved(summary_or_text: str | None) -> bool:
    """True only when the canonical verdict is an explicit approval."""
    return parse_verdict(summary_or_text) == "APPROVE"


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
        data = list_all_prs_enriched("open", repo=_repo)
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
        open_data = list_all_prs_enriched("open", repo=_repo)
    except Exception as e:
        logger.error("pr_review_service: sync_closed poll failed: %s", e)
        return 0

    open_numbers = {pr["number"] for pr in open_data.get("prs", [])}
    updated = 0
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Mark the PR closed AND finalize any unresolved review_status. A PR
            # that left GitHub's open set will never be reviewed again, so rows
            # stuck at 'pending'/'in_progress' must be terminated to 'skipped' —
            # otherwise they accumulate forever and pollute the PR Review queue
            # (get_pending_reviews only retries OPEN in_progress rows). #3449.
            cur.execute(
                """
                UPDATE pr_reviews
                SET state = 'closed',
                    review_status = CASE
                        WHEN review_status IN ('pending', 'in_progress')
                        THEN 'skipped'
                        ELSE review_status
                    END,
                    updated_at = NOW()
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

    # Notify on every review completion (approved or not). F.O.R.G.E. is a
    # director, not A.R.C.H.I.E.'s outbound voice, so it CANNOT call
    # telegram_service.send() directly — the unified-voice guard rejects it and
    # the alert is silently dropped (#3973). Route through the sanctioned
    # director→A.R.C.H.I.E. inbox instead (per the guard's own error message).
    try:
        from services.director_report_service import submit_via_inbox  # noqa: PLC0415

        _r = get_review(pr_number)
        _pr_title = (_r or {}).get("title", f"PR #{pr_number}")
        _verdict_label = "APPROVED ✅" if verdict_is_approved(summary) else "NEEDS CHANGES ⚠️"
        submit_via_inbox(
            category="pr_review",
            title=f"F.O.R.G.E. reviewed #{pr_number}",
            message=f"{_verdict_label} — {_pr_title}\nCheck Repair Bay → PR Review for details.",
            source_agent="F.O.R.G.E.",
            severity="low",
            department="Engineering & Technology",
        )
    except Exception as _tg_err:
        logger.warning("[F.O.R.G.E.] review-notify error: %s", _tg_err)

    if not auto_merge:
        return

    # Auto-merge when F.O.R.G.E. explicitly approves the PR.
    # parse_verdict() is the single source of truth — it matches the token the
    # analyzer actually emits ("APPROVE") and tolerates legacy "APPROVED".
    if not verdict_is_approved(summary):
        return

    # Tiered merge governance (ADR-001 / ADR-003): F.O.R.G.E. approval alone no
    # longer force-merges. Only Tier 1 (small + approved) auto-merges; Tier 2/3 are
    # GATED for human approval (chain: F.O.R.G.E. -> Dept Lead -> COO -> Kytran).
    # Tunable: FORGE_AUTO_MERGE_MAX_TIER (default 1). Phase 1 of task #3709.
    import os as _os

    _review = get_review(pr_number) or {}
    if "branch" not in _review and _review.get("head_branch"):
        _review["branch"] = _review["head_branch"]

    # SAFETY GATE — engine-authored PRs are NEVER auto-merged, regardless of tier.
    # Autonomous code (the A.R.C.H.I.E. build engine) must pass a human merge gate:
    # branch+PR only, then a human /merge-pr (mirrors codex's never-auto-merge rule
    # + ADR-003). The engine names branches "engine/<slug>" (build_loop._branch_name)
    # and titles PRs "[engine] ...". Fail-safe ON; tunable via
    # FORGE_NO_AUTOMERGE_BRANCH_PREFIXES (comma-separated, default "engine/").
    _branch = _review.get("branch") or _review.get("head_branch") or ""
    _title = _review.get("title") or ""
    _no_auto_prefixes = tuple(
        p.strip() for p in _os.getenv("FORGE_NO_AUTOMERGE_BRANCH_PREFIXES", "engine/").split(",") if p.strip()
    )
    if (_no_auto_prefixes and _branch.startswith(_no_auto_prefixes)) or _title.startswith("[engine]"):
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO system_notifications (title, message, type, source, visibility) "
                "VALUES (%s, %s, 'warning', 'forge', 'all')",
                (
                    f"PR #{pr_number} needs human merge (engine-authored)",
                    f"F.O.R.G.E. approved engine PR #{pr_number} (branch {_branch!r}) — autonomous "
                    f"code is NEVER auto-merged; gated for a human /merge-pr.",
                ),
            )
        logger.info(
            "[F.O.R.G.E.] PR #%s is engine-authored (branch=%s) — GATED from auto-merge (human merge required)",
            pr_number,
            _branch,
        )
        return

    _tier = classify_pr_tier(_review)
    try:
        _max_auto = int(_os.getenv("FORGE_AUTO_MERGE_MAX_TIER", "1"))
    except (TypeError, ValueError):
        _max_auto = 1
    if _tier > _max_auto:
        _mark_tier_processed(pr_number, _tier)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO system_notifications (title, message, type, source, visibility) "
                "VALUES (%s, %s, 'warning', 'forge', 'all')",
                (
                    f"PR #{pr_number} needs approval (Tier {_tier})",
                    f"F.O.R.G.E. approved PR #{pr_number} but it is Tier {_tier} — gated for human "
                    f"approval (F.O.R.G.E. → Dept Lead → COO → Kytran). Not auto-merged.",
                ),
            )
        logger.info(
            "[F.O.R.G.E.] PR #%s approved but Tier %s > max_auto %s — GATED (not merged)",
            pr_number,
            _tier,
            _max_auto,
        )
        return

    try:
        from .github_service import merge_pr

        result = merge_pr(pr_number, "squash")
        # PR #1278 added a "merged" success key; rely on that rather than "sha"
        # (a successful squash-merge may not echo the commit sha back).
        if result.get("merged"):
            sha = result.get("sha") or ""
            logger.info("[F.O.R.G.E.] PR #%s auto-merged after approval (sha=%s)", pr_number, sha[:8])
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


# ---- Tiered PR Merge Authority ----

_TIER3_TITLE_KW = {"breaking", "migration", "security"}


def classify_pr_tier(review: dict) -> int:
    """Classify a PR review into merge tier 1 (F.O.R.G.E.), 2 (A.R.C.H.I.E.), or 3 (Kytran).

    Tier 3 (highest precedence):
        - > 1500 lines changed
        - title contains breaking/migration/security
        - branch looks like a numbered migration (e.g. 382_partner_profiles)
        - F.O.R.G.E. verdict contains REJECT

    Tier 1:
        - < 300 lines changed AND < 10 files changed
        - AND (has auto-merge label OR F.O.R.G.E. verdict contains APPROVED)

    Tier 2: everything else.
    """
    import re as _re  # noqa: PLC0415

    additions = review.get("additions") or 0
    deletions = review.get("deletions") or 0
    changed_files = review.get("changed_files") or 0
    total = additions + deletions
    title = (review.get("title") or "").lower()
    summary = (review.get("ai_summary") or "").upper()
    branch = (review.get("branch") or "").lower()
    meta = review.get("metadata") or {}

    # --- Tier 3 gates ---
    if total > 1500:
        return 3
    if "REJECT" in summary:
        return 3
    if any(kw in title for kw in _TIER3_TITLE_KW):
        return 3
    if "migration" in branch or _re.search(r"\d{3}_", branch):
        return 3

    # --- Tier 1 gates ---
    small = total < 300 and changed_files < 10
    # Use the shared verdict parser so Tier-1 classification matches the token
    # the analyzer emits ("APPROVE") and the auto-merge gate checks.
    approved = verdict_is_approved(review.get("ai_summary"))
    auto_label = "auto-merge" in (meta.get("labels") or [])
    if small and (approved or auto_label):
        return 1

    return 2


def _mark_tier_processed(pr_number: int, tier: int) -> None:
    """Record tier merge decision in pr_reviews.metadata."""
    from psycopg2.extras import Json as _Json  # noqa: PLC0415
    from services.time_utils import now_utc  # noqa: PLC0415

    payload = _Json({"tier_processed": tier, "tier_processed_at": now_utc().isoformat()})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (payload, pr_number),
        )


def _mark_kytran_approval_sent(pr_number: int) -> None:
    """Prevent duplicate Tier 3 Telegram messages for this PR."""
    from psycopg2.extras import Json as _Json  # noqa: PLC0415

    payload = _Json({"kytran_approval_sent": True})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (payload, pr_number),
        )
