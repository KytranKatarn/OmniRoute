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

# A tracked repo MUST be an ``owner/repo`` slug. Anything else (e.g. a bare
# ``kytran-creed`` from the pre-#4295 cross-repo mis-stamp bug, KB #272111) is
# rejected so it can never be polled or re-inserted as a phantom row (#3941).
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def _is_valid_repo(repo: str | None) -> bool:
    """True only for a well-formed ``owner/repo`` slug."""
    return bool(repo and _REPO_RE.match(repo))


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
# RC-3d (QW-4): a weak 7B can echo the verdict MENU verbatim ("VERDICT: APPROVE | REQUEST
# CHANGES | NEEDS REVIEW"). Reject-first would misread the embedded "REQUEST CHANGES" as a real
# block. A single VERDICT line offering ALL THREE options is UN-CHOSEN — route it to NEEDS REVIEW
# (a human decides) instead of a false REQUEST CHANGES.
_VERDICT_MENU_RE = re.compile(
    r"VERDICT\s*[:\-—].*\bAPPROVED?\b.*\bREQUEST\s+CHANGES\b.*\bNEEDS\s+REVIEW\b",
    re.IGNORECASE,
)


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
    # QW-4: an un-chosen verdict MENU echo (all three options on the VERDICT line) is not a real
    # block — route it to NEEDS REVIEW before the reject-first check can misread the embedded
    # "REQUEST CHANGES" as a verdict.
    if _VERDICT_MENU_RE.search(text):
        return "NEEDS REVIEW"
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


def get_tracked_repos(cur=None) -> list:
    """Return repos to poll.

    Union of two sources, in order, deduped, filtered to valid ``owner/repo``:
      1. Configured repos — GITHUB_REPOS (comma-separated) or GITHUB_REPO.
      2. Any valid ``owner/repo`` already present in ``pr_reviews``.

    Source (2) self-heals cross-repo tracking (#3941): a repo F.O.R.G.E. reviewed
    on-demand (e.g. KytranKatarn/archie-code) keeps getting polled AND
    sync_closed_prs'd instead of its rows rotting ``open`` forever once it drops
    out of the configured set. Malformed labels (e.g. a bare ``kytran-creed`` from
    the pre-#4295 mis-stamp bug, KB #272111) are filtered out so they are never
    re-polled. Fail-open: a DB read error falls back to the configured repos.

    ``cur`` is an optional injected cursor (for unit tests); when omitted the
    function opens its own read cursor.
    """
    repos_env = os.getenv("GITHUB_REPOS", "").strip()
    configured = [r.strip() for r in repos_env.split(",") if r.strip()] if repos_env else [_DEFAULT_REPO]

    discovered: list = []
    try:

        def _scan(c) -> list:
            c.execute("SELECT DISTINCT repo FROM pr_reviews")
            return [row["repo"] for row in c.fetchall()]

        if cur is not None:
            discovered = _scan(cur)
        else:
            with get_db_cursor() as (conn, c):
                discovered = _scan(c)
    except Exception as e:  # fail-open — a read error must never break polling
        logger.warning("get_tracked_repos: pr_reviews scan failed, using configured repos only: %s", e)

    out: list = []
    for repo in (*configured, *discovered):
        if _is_valid_repo(repo) and repo not in out:
            out.append(repo)
    return out or [_DEFAULT_REPO]


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def poll_open_prs(repo: str = None) -> dict:
    """Poll GitHub for open PRs and upsert into pr_reviews.

    Returns:
        dict: {polled, inserted, updated, errors}
    """
    from tools.repair_bay.services.github_service import list_all_prs_enriched

    _repo = (repo or _DEFAULT_REPO).strip()
    if not _is_valid_repo(_repo):
        # Defends against re-inserting a phantom row under a malformed label
        # (the KB #272111 / #3941 failure mode).
        logger.error("pr_review_service: refusing to poll malformed repo %r (expected owner/repo)", _repo)
        return {"polled": 0, "inserted": 0, "updated": 0, "errors": 1}
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

    _repo = (repo or _DEFAULT_REPO).strip()
    if not _is_valid_repo(_repo):
        logger.error("pr_review_service: refusing to sync_closed malformed repo %r (expected owner/repo)", _repo)
        return 0
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

    # ST-4: persist which review path produced this verdict + emit a telemetry line, so the
    # structured-vs-freeform ratio is observable (a silent drop to ~100% freeform = a regression).
    _path = _extract_review_path(summary)
    _mark_review_path(pr_number, _path, repo)
    logger.info(
        "[PR Review] PR #%s path=%s verdict=%s",
        pr_number,
        _path,
        "approved" if verdict_is_approved(summary) else "needs_changes",
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

    # Sticky REQUEST-CHANGES marker (#3962 follow-up). Recorded regardless of
    # auto_merge so a later — possibly flaky / non-deterministic — APPROVE on the same
    # PR within the defer window gates to a human instead of auto-merging. The manual
    # review_pr path and the scheduled forge_pr_review poll review independently.
    if not verdict_is_approved(summary):
        try:
            _mark_changes_requested(pr_number, repo)
        except Exception as _cr_err:
            logger.warning("[F.O.R.G.E.] changes-requested stamp error: %s", _cr_err)

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

    # DEFER GATE (#3962 follow-up) — do NOT let a (possibly flaky / non-deterministic)
    # APPROVE override a RECENT REQUEST-CHANGES on the same PR. The manual review_pr
    # path and the scheduled forge_pr_review poll review independently, and 7B verdicts
    # vary run-to-run; without this a scheduled APPROVE could auto-merge a PR another
    # review just flagged (exactly what happened to PR #1843). Window tunable via
    # FORGE_CHANGES_REQUESTED_DEFER_HOURS (default 6; <=0 disables). New commits aren't
    # tracked by sha here, so the window self-clears — a human /merge-pr always works.
    if _changes_requested_recently(_review, _os.getenv("FORGE_CHANGES_REQUESTED_DEFER_HOURS")):
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO system_notifications (title, message, type, source, visibility) "
                "VALUES (%s, %s, 'warning', 'forge', 'all')",
                (
                    f"PR #{pr_number} needs human merge (recent REQUEST-CHANGES)",
                    f"F.O.R.G.E. approved PR #{pr_number}, but a REQUEST-CHANGES review landed on the "
                    f"same PR within the defer window — auto-merge deferred to a human /merge-pr so a "
                    f"flaky APPROVE can't override it.",
                ),
            )
        logger.info(
            "[F.O.R.G.E.] PR #%s approved but a recent REQUEST-CHANGES exists — DEFERRED (human merge)",
            pr_number,
        )
        return

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

    # REVIEW-ONLY GATE (#4494) — only the default repo (archie-platform) auto-merges.
    # The auto-merge write token is archie-platform-scoped and FORGE_REVIEW_TOKEN is
    # read-only, so an auto-merge on a watch-product repo can't succeed and (now that
    # merge_pr is repo-aware) must never be attempted against the wrong repo. Watch
    # PRs are auto-REVIEWED but gated to a human merge.
    _merge_repo = repo or _DEFAULT_REPO
    if _merge_repo != _DEFAULT_REPO:
        logger.info(
            "[F.O.R.G.E.] PR #%s approved on %s — review-only (non-default repo), not auto-merged (#4494)",
            pr_number,
            _merge_repo,
        )
        return

    try:
        from .github_service import merge_pr

        result = merge_pr(pr_number, "squash", repo=_merge_repo)
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


def decide_reap_action(reap_count: int, max_retries: int = 3) -> str:
    """Pure: given how many times a stuck review has already been reaped, pick the next action.

    'reset' → flip back to pending for another server-side drive; 'skip' → give up (a
    genuinely-broken review, e.g. an un-fetchable diff, must not loop pending↔in_progress forever).
    """
    return "reset" if reap_count < max_retries else "skip"


def reap_stale_reviews(stale_minutes: int = 20, max_retries: int = 3) -> dict:
    """Recover PR reviews stuck in 'in_progress' past the stale window (#4583).

    When an on-demand review_pr() dies mid-flight (CLI killed, session ended), the row is left
    'in_progress' forever — mark_review_started() ran but mark_review_done() never did (KB
    #270002). This resets such rows to 'pending' so the sidecar re-drives them, capped by
    metadata.reap_count so a permanently-broken review goes 'skipped' instead of looping.
    stale_minutes=20 matches get_pending_reviews so a legitimately in-flight review (cold-load
    can take minutes) is never reaped. Only OPEN PRs are reaped (closed ones are handled by
    sync_closed_prs). Returns {"reset": [...], "skipped": [...]}; each item is {"pr_number", "repo"}.
    """
    reset: list = []
    skipped: list = []
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            SELECT pr_number, repo, COALESCE((metadata->>'reap_count')::int, 0) AS reap_count
            FROM pr_reviews
            WHERE review_status = 'in_progress'
              AND state = 'open'
              AND updated_at < NOW() - make_interval(mins => %s)
            """,
            (stale_minutes,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            pr, repo = r["pr_number"], r["repo"]
            if decide_reap_action(r["reap_count"], max_retries) == "reset":
                cur.execute(
                    """
                    UPDATE pr_reviews
                    SET review_status='pending', updated_at=NOW(),
                        metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb),
                                             '{reap_count}', to_jsonb(%s::int))
                    WHERE pr_number=%s AND repo=%s
                    """,
                    (r["reap_count"] + 1, pr, repo),
                )
                reset.append({"pr_number": pr, "repo": repo})
            else:
                cur.execute(
                    """
                    UPDATE pr_reviews
                    SET review_status='skipped', updated_at=NOW(),
                        ai_summary = COALESCE(ai_summary, '') || %s,
                        metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb),
                                             '{reap_reason}', to_jsonb(%s::text))
                    WHERE pr_number=%s AND repo=%s
                    """,
                    (
                        f"\n[review-reaper] skipped after {max_retries} stuck-recovery attempts.",
                        "max_stuck_retries",
                        pr,
                        repo,
                    ),
                )
                skipped.append({"pr_number": pr, "repo": repo})
    if reset or skipped:
        logger.info(
            "[review-reaper] reset=%s skipped=%s (stale>%dm, cap=%d)",
            [x["pr_number"] for x in reset],
            [x["pr_number"] for x in skipped],
            stale_minutes,
            max_retries,
        )
    return {"reset": reset, "skipped": skipped}


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
    # get_review() is `SELECT *` from pr_reviews, whose column is head_branch — there is NO
    # "branch" column, so the old review.get("branch") was always "" and the branch-based Tier-3
    # escalation (migration / NNN_ patterns -> gemma3:12b) never fired. (F.O.R.G.E. review-quality
    # diagnosis 2026-06-22, QW-3.)
    branch = (review.get("head_branch") or review.get("branch") or "").lower()
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


def _mark_changes_requested(pr_number: int, repo: str = None) -> None:
    """Stamp a sticky 'changes requested' marker in pr_reviews.metadata.

    A later — possibly flaky / non-deterministic — APPROVE on the same PR within the
    defer window will gate to a human instead of auto-merging (#3962 follow-up). The
    timestamp slides on each REQUEST-CHANGES so "recent" tracks the latest one.
    """
    from psycopg2.extras import Json as _Json  # noqa: PLC0415
    from services.time_utils import now_utc  # noqa: PLC0415

    payload = _Json({"changes_requested_at": now_utc().isoformat()})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s "
            "WHERE pr_number = %s AND repo = %s",
            (payload, pr_number, repo or _DEFAULT_REPO),
        )


def _changes_requested_recently(review: dict, window_hours_env: str = None) -> bool:
    """True if a REQUEST-CHANGES was recorded on this PR within the defer window.

    Window = FORGE_CHANGES_REQUESTED_DEFER_HOURS (default 6h; <=0 disables). Fail-open
    to False — a parse error must never block a legitimate merge.
    """
    from datetime import datetime, timedelta  # noqa: PLC0415
    from services.time_utils import now_utc  # noqa: PLC0415

    try:
        hours = float(window_hours_env) if window_hours_env else 6.0
    except (TypeError, ValueError):
        hours = 6.0
    if hours <= 0:
        return False
    meta = review.get("metadata") or {}
    if isinstance(meta, str):
        import json as _json  # noqa: PLC0415

        try:
            meta = _json.loads(meta)
        except (ValueError, TypeError):
            return False
    ts = (meta or {}).get("changes_requested_at")
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts)
        return (now_utc() - when) < timedelta(hours=hours)
    except (ValueError, TypeError):
        return False


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


def _extract_review_path(summary: str) -> str:
    """ST-4: classify which review path produced a verdict, for structured-vs-freeform telemetry.
    Reads the '[review-meta] structured=<x>' line the analyzer emits (_render_review_text ->
    'json'; _render_freeform_gated -> 'freeform-gated'). Returns
    'json' | 'freeform-gated' | 'freeform' | 'unknown'."""
    import re as _re  # noqa: PLC0415

    s = summary or ""
    m = _re.search(r"\[review-meta\][^\n]*structured=([\w-]+)", s)
    if m:
        return m.group(1)
    if _re.search(r"\bVERDICT:", s):
        return "freeform"  # a verdict but no meta line = legacy ungated freeform
    return "unknown"


def _mark_review_path(pr_number: int, path: str, repo: str = None) -> None:
    """ST-4: stamp the review path into pr_reviews.metadata so it is queryable without re-parsing
    ai_summary. Best-effort — telemetry must never break the review write."""
    try:
        from psycopg2.extras import Json as _Json  # noqa: PLC0415

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s "
                "WHERE pr_number = %s AND repo = %s",
                (_Json({"review_path": path}), pr_number, repo or _DEFAULT_REPO),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PR Review] review_path stamp failed: %s", exc)


def get_forge_review_metrics(days: int = 7) -> dict:
    """ST-4: structured-vs-freeform path breakdown over the last ``days`` of reviewed PRs. Prefers
    the stamped metadata.review_path, falling back to parsing ai_summary for rows written before the
    stamp existed. ``structured_ratio`` = json-path / total — a sharp drop signals a regression
    (e.g. forge:structured_review_enabled turned off, or a parse break sending everything freeform)."""
    counts = {"json": 0, "freeform-gated": 0, "freeform": 0, "unknown": 0}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT metadata->>'review_path' AS stamped, ai_summary
                FROM pr_reviews
                WHERE review_status = 'reviewed'
                  AND ai_review_at >= NOW() - (%s || ' days')::interval
                """,
                (str(int(days)),),
            )
            rows = cur.fetchall() or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PR Review] forge metrics query failed: %s", exc)
        return {"counts": counts, "total": 0, "structured_ratio": None, "days": days, "error": str(exc)}
    for row in rows:
        stamped = row.get("stamped") if isinstance(row, dict) else row[0]
        summary = row.get("ai_summary") if isinstance(row, dict) else row[1]
        path = stamped or _extract_review_path(summary)
        counts[path if path in counts else "unknown"] += 1
    total = sum(counts.values())
    return {
        "counts": counts,
        "total": total,
        "structured_ratio": (counts["json"] / total) if total else None,
        "days": days,
    }
