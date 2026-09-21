"""PR Review Service — GitHub polling + review state management.

Phase 1 of the PR Review Pipeline (Project #247, Task #1799).
Polls GitHub for open PRs, upserts into pr_reviews, tracks AI review state.
Phase 2 (F.O.R.G.E. AI review) and Phase 3 (Repair Bay UI) build on this.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

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


def coverage_only_demotion(summary_or_text: str | None) -> bool:
    """True when the ONLY thing standing between this review and an approval is coverage.

    The #5836 coverage gate appends its block to the model's summary and ends it with
    ``VERDICT: NEEDS REVIEW``. parse_verdict reads the LAST verdict, so a review the model
    APPROVED becomes indistinguishable from one it REJECTED — both return False from
    verdict_is_approved. The standing rule distinguishes them ("a coverage demotion is
    overridable — a human should read the rest; a REQUEST CHANGES is NOT"), but until now
    only in prose. This makes that distinction checkable.

    STRICT by construction: annotate() builds the summary as f"{summary}\n\n{block}", so
    everything before MARKER is verbatim what the model produced. We re-parse THAT and
    require an approval. A REQUEST CHANGES that also got coverage-demoted therefore returns
    False and stays unmergeable — which is the whole point.
    """
    if not summary_or_text:
        return False
    from services.review_coverage import MARKER  # noqa: PLC0415 - pure module, no cycle

    if MARKER not in summary_or_text:
        return False
    underlying = summary_or_text.split(MARKER, 1)[0]
    return parse_verdict(underlying) == "APPROVE"


def coverage_dropped_paths(summary_or_text: str | None) -> list:
    """The files the reviewer never read, for showing a human what they are discharging.

    A count alone does not tell anyone whether the dropped file was a README or the deploy
    path — the same reasoning as coverage_note's own listing.
    """
    if not summary_or_text:
        return []
    from services.review_coverage import MARKER  # noqa: PLC0415

    if MARKER not in summary_or_text:
        return []
    block = summary_or_text.split(MARKER, 1)[1]
    out = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and not stripped.startswith("- ...and "):
            out.append(stripped[2:].strip())
        elif out and not stripped:
            break  # the listing ends at the first blank line after it starts
    return out


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
    from psycopg2.extras import Json as _Json  # noqa: PLC0415
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
    if not data.get("success", True):
        # #5707: list_all_prs_enriched reports API failure via success=False, it
        # does not raise — an unchecked failure dict reads as "zero open PRs".
        logger.error("pr_review_service: GitHub poll failed: %s", data.get("error"))
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
                         metadata, last_polled_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (pr_number, repo) DO UPDATE SET
                        title          = EXCLUDED.title,
                        state          = EXCLUDED.state,
                        diff_url       = EXCLUDED.diff_url,
                        -- REFRESH the refs, do not just seed them on INSERT. They were
                        -- absent from this SET list, so `base_branch` was written once
                        -- and never again: 1,878 of 2,518 rows were NULL because a
                        -- review stub had created the row first, and a poll can only
                        -- ever UPDATE it. Stacked PRs make the staleness worse than the
                        -- NULLs — GitHub RETARGETS a stacked PR when its parent merges,
                        -- so the stored base is wrong exactly when it decides whether a
                        -- merge ships or folds into a parent branch (#5866).
                        base_branch    = EXCLUDED.base_branch,
                        head_branch    = EXCLUDED.head_branch,
                        additions      = EXCLUDED.additions,
                        deletions      = EXCLUDED.deletions,
                        changed_files  = EXCLUDED.changed_files,
                        -- MERGE, never replace: metadata carries tier_processed /
                        -- forge_escalated_tier / review_path, and a poll must not
                        -- wipe them. `||` right-biases, so the fresh draft flag wins
                        -- while every other key survives.
                        metadata       = COALESCE(pr_reviews.metadata, '{}'::jsonb)
                                         || EXCLUDED.metadata,
                        -- ⚠️ DO NOT add `updated_at = NOW()` here. A poll is not a
                        -- change to the REVIEW; `last_polled_at` below is the column
                        -- for poll bookkeeping, and three separate consumers read
                        -- `updated_at` as "when did this review last meaningfully
                        -- move":
                        --   get_pending_reviews  (~L436) retry an in_progress row after 20m
                        --   reap_stale_reviews   (~L994) recover a dead review after 20m
                        --   review_progress      (~L1310) elapsed time shown in the UI
                        -- Refreshing it every cycle made `updated_at < NOW() - 20 min`
                        -- unreachable for any OPEN pr — and BOTH recovery paths also
                        -- filter `state = 'open'`, i.e. exactly the population this
                        -- upsert re-stamps. So neither could ever fire, and the UI's
                        -- elapsed timer reset on every poll.
                        -- Measured 2026-09-20: PR #3411 sat 'in_progress' for 6+ hours
                        -- with reap_count = 0 (never reaped once), while four rows
                        -- spanning BOTH 'in_progress' and 'reviewed' shared one
                        -- updated_at to the millisecond — the tell that a bulk poll,
                        -- not any review, was writing it. A finished review being
                        -- re-stamped is the part that cannot be explained innocently.
                        last_polled_at = NOW()
                    RETURNING (xmax = 0) AS is_new
                    """,
                    (
                        pr.get("number"),
                        _repo,
                        pr.get("title", ""),
                        pr.get("user") if isinstance(pr.get("user"), str) else (pr.get("user") or {}).get("login"),
                        pr.get("state", "open"),
                        pr.get("base_ref") or (pr.get("base") or {}).get("ref"),
                        (pr.get("head") or {}).get("ref") or pr.get("head_ref"),
                        pr.get("diff_url"),
                        pr.get("additions"),
                        pr.get("deletions"),
                        pr.get("changed_files"),
                        # Draft state, captured here because the PR-list response
                        # ALREADY carries it (#5362). Recording it at poll time is
                        # what makes the tier worker's skip cost ZERO extra API
                        # calls — the alternative, asking GitHub per tick, is the
                        # quota burn this fix exists to remove.
                        _Json({"draft": bool(pr.get("draft"))}),
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
    # #5297: review-path health rides the existing poll cadence — no new scheduler
    # wiring, and send_system's (title, source) dedup + cooldown own the spam control.
    # Best-effort: the health check must never break polling.
    try:
        check_review_path_health()
    except Exception as _health_err:  # noqa: BLE001
        logger.debug("review-path health check skipped: %s", _health_err)
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
    if not open_data.get("success", True):
        # #5707: a FAILED list is not an EMPTY list. During the 2026-08-17 GitHub
        # partial outage the pulls-list endpoint 403'd with valid tokens; the
        # failure dict has no "prs" key, so .get("prs", []) turned the outage
        # into "zero open PRs" and this function closed every live pr_reviews
        # row (terminating their pending reviews as 'skipped'). Twice.
        logger.error(
            "pr_review_service: sync_closed skipped — open-PR list failed: %s",
            open_data.get("error"),
        )
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

            # #5780: the CASE above can only reach rows STILL marked state='open'. A row that
            # reached state='closed' while its review_status was still 'pending'/'in_progress'
            # is missed by BOTH owners — this UPDATE (WHERE state='open') and
            # reap_stale_reviews (which also filters AND state='open', delegating closed PRs
            # to here). Neither finalizes it, so it is stuck FOREVER.
            # Measured 2026-08-22: 20 such rows (19 pending + 1 in_progress), all dated
            # 2026-05-31; the in_progress one had sat 83 days on an already-MERGED PR.
            # The comment above already states the invariant ("must be terminated to
            # 'skipped' — otherwise they accumulate forever"); this enforces it.
            # ⚠️ Deliberately NOT gated on pr_number: a closed PR is closed regardless of
            # whether it appeared in this poll's open set.
            cur.execute(
                """
                UPDATE pr_reviews
                   SET review_status = 'skipped', updated_at = NOW()
                 WHERE repo = %s AND state <> 'open'
                   AND review_status IN ('pending', 'in_progress')
                """,
                (_repo,),
            )
            if cur.rowcount:
                logger.info(
                    "pr_review_service: finalized %d orphaned review row(s) on closed PRs (%s) — #5780",
                    cur.rowcount,
                    _repo,
                )
                updated += cur.rowcount
    except Exception as e:
        logger.error("pr_review_service: sync_closed update failed: %s", e)

    # A PR leaving the open set also makes any pending merge APPROVAL for it moot
    # (#5862). Wired HERE rather than at each caller: sync_closed_prs has three
    # (the manual Repair Bay route, dept_hq jobs `agent_forge_pr_poll`, and
    # agent_loop `forge_pr_review_poll`), and per-caller wiring is precisely how the
    # merge-governance hole existed. Deliberately below the early returns above — a
    # FAILED PR list must not be read as "everything closed" (#5707).
    try:
        from tools.department_hq.services.approvals_reconcile import (
            close_stale_pr_merge_approvals,
        )

        close_stale_pr_merge_approvals()
    except Exception as e:  # noqa: BLE001
        logger.warning("pr_review_service: approval reconcile skipped: %s", e)

    # Proposal merge-completion sweep (spec 2026-08-26 §6.4) — same choke-point
    # placement as the approvals reconcile above: all three pollers share this
    # function, so a merged fix PR completes its proposal (code_applied: true)
    # no matter which poller noticed. Fail-soft: the poller must never die on it.
    try:
        from .forge_pipeline import complete_merged_fix_proposals

        complete_merged_fix_proposals()
    except Exception as e:  # noqa: BLE001
        logger.warning("pr_review_service: merged-fix sweep skipped: %s", e)

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


# ---------------------------------------------------------------------------
# MACHINE-AUTHORED PRs — never auto-merged, by ANY actor. ONE definition.
# ---------------------------------------------------------------------------
#
# Autonomous code must pass a human merge gate: branch+PR only, then a human
# /merge-pr (mirrors codex's never-auto-merge rule + ADR-003). Two producers:
# the A.R.C.H.I.E. build engine names branches "engine/<slug>" and titles PRs
# "[engine] …" (build_loop._branch_name); the cockpit apply lane (#6680) names
# them "cockpit/apply-<job>-<slug>" / "[cockpit] …" and carries cloud-model
# content with no test gate.
#
# This lived ONLY in mark_review_done until 2026-09-10. That function is
# F.O.R.G.E.'s own post-review branch — NOT the merge choke point — and it
# stamps nothing on the review row, so ``_run_archie_pr_review_worker`` (every
# 2 min, selects on ``review_status='reviewed'``, which mark_review_done sets
# BEFORE this gate runs) classified the tier itself and merged Tier 1 through
# merge_pr, reaching a governance gate with no authorship rule at all.
# MEASURED on this feature's own acceptance target: a ``cockpit/apply-*`` PR
# touching ``docs/…`` is Tier 1, passes ``^docs/`` in _SAFE_AUTOMERGE_PATTERNS,
# and the container ceiling is 1 — so it merged to main with no human ~2 min
# after the approve. Third instance of #5194's lesson: gate the CHOKE POINT.
#
# Both call sites — mark_review_done below and
# github_service._automerge_governance_ok — read THESE functions, so the two
# lists cannot drift.
_NO_AUTOMERGE_BRANCH_PREFIXES_DEFAULT = "engine/,cockpit/"
NO_AUTOMERGE_TITLE_PREFIXES = ("[engine]", "[cockpit]")


def no_automerge_branch_prefixes() -> tuple:
    """Branch prefixes that are human-merge-only. Read from env on every call.

    ``FORGE_NO_AUTOMERGE_BRANCH_PREFIXES`` (comma-separated) REPLACES the default
    ``engine/,cockpit/`` — live-tunable without a deploy, matching the way the
    other gate knobs work. An empty/blank value disables the branch half only;
    the title prefixes are not tunable, so a machine PR can never become
    auto-mergeable by clearing one env var.
    """
    return tuple(
        p.strip()
        for p in os.getenv("FORGE_NO_AUTOMERGE_BRANCH_PREFIXES", _NO_AUTOMERGE_BRANCH_PREFIXES_DEFAULT).split(",")
        if p.strip()
    )


def machine_authored_reason(review: dict | None) -> str | None:
    """Why ``review`` is a machine-authored PR, or ``None`` when it is not.

    Accepts either row shape: ``head_branch`` (the ``pr_reviews`` column, what
    ``get_review`` returns) or ``branch`` (the alias some list/normalise paths
    use). Pure — no DB, no network — so it is safe to check first at any gate.
    """
    row = review or {}
    branch = str(row.get("head_branch") or row.get("branch") or "")
    title = str(row.get("title") or "")
    prefixes = no_automerge_branch_prefixes()
    if prefixes and branch.startswith(prefixes):
        return f"branch {branch!r}"
    if title.startswith(NO_AUTOMERGE_TITLE_PREFIXES):
        return f"title {title!r}"
    return None


# ---------------------------------------------------------------------------
# AUTO-MERGE PATH ALLOWLIST — deny-by-default (owner directive 2026-07-22:
# "stop forge from auto merging service code").
#
# The pre-existing gates are SIZE-based (Tier 1), author-based (engine/*) and
# repo-based. None of them look at WHAT changed, so a small diff touching code
# that runs the platform auto-merged: PR #2409 shipped
# platform_v2/services/delegation_service.py to main with no human in the loop
# purely because it was small enough to classify Tier 1.
#
# Deliberately an ALLOWLIST, not a denylist — mirroring the codex scope-guard
# rule (config/agents/codex.yaml, .claude/rules/codex-agent.md). A denylist is
# wrong by default for anything it forgot to name; an allowlist is safe by
# default and fails toward a human. Docs/tests/QA-specs auto-merge; everything
# else — services, ai_bridge, routes, migrations, compose, deploy + DR scripts —
# needs /merge-pr.
#
# Tunable without a deploy via FORGE_AUTOMERGE_SAFE_PATHS (comma-separated
# regexes, REPLACES the defaults). Set it to something unmatchable to disable
# auto-merge entirely.
_SAFE_AUTOMERGE_PATTERNS = (
    r"\.md$",  # documentation anywhere
    r"^\.claude/",  # rules, commands, skills, plans
    r"^docs/",
    r"^platform_v2/qa_suites/",  # P.R.O.B.E. test specs
    r"^platform_v2/qa/",  # P.R.O.B.E. harness tests
    r"^platform_v2/tests/",  # unit tests
)

# Per-repo allowlists for the NON-default repos permitted to auto-merge (owner
# decision 2026-08-29: KSO is "software managed and created here", so it gets the
# same auto-merge CLASS as the platform — docs and tests; service code, compose,
# Dockerfile and rule_packs still require a human /merge-pr). A repo with no entry
# here gets an EMPTY pattern set, so every file blocks — deny-by-default holds for
# any repo someone adds to FORGE_AUTOMERGE_REPOS without also deciding its paths.
# KSO is image-baked (COPY .), so a merge never deploys by itself either way.
_SAFE_AUTOMERGE_PATTERNS_BY_REPO = {
    "KytranKatarn/kytran-system-operations": (
        r"\.md$",  # documentation anywhere
        r"^docs/",
        r"^tests/",
        r"(^|/)test_[^/]+\.py$",  # KSO keeps test files beside the code
    ),
}

# Repos where an UNATTENDED merge may be attempted at all. The watch products and
# KBS stay review-only: the write token has NO access there (probed 2026-08-23,
# #5981 — never reason about merge safety from assumed token absence, but here the
# absence is measured). Env-tunable without a deploy; the list REPLACES the default.
_DEFAULT_AUTOMERGE_REPOS = (
    "KytranKatarn/archie-platform",
    "KytranKatarn/kytran-system-operations",
)


def automerge_repos() -> tuple:
    """The repos unattended merge may target. FORGE_AUTOMERGE_REPOS overrides."""
    raw = os.getenv("FORGE_AUTOMERGE_REPOS", "").strip()
    if raw:
        return tuple(r.strip() for r in raw.split(",") if r.strip())
    return _DEFAULT_AUTOMERGE_REPOS


def _automerge_paths_allowed(pr_number: int, repo: str):
    """Return (allowed, blocking_files) for the auto-merge path allowlist.

    FAILS CLOSED: if the changed-file list cannot be determined, auto-merge is
    refused. Not knowing what a PR touches is not evidence that it is safe —
    that inversion is the exact failure mode this whole gate exists to stop.

    Patterns are PER-REPO: the default repo keeps _SAFE_AUTOMERGE_PATTERNS (and the
    FORGE_AUTOMERGE_SAFE_PATHS env override, which applies to the default repo only —
    its historical contract); other repos read _SAFE_AUTOMERGE_PATTERNS_BY_REPO, and
    an unlisted repo gets an empty set, blocking every file.
    """
    if (repo or _DEFAULT_REPO) == _DEFAULT_REPO:
        raw = os.getenv("FORGE_AUTOMERGE_SAFE_PATHS", "").strip()
        patterns = tuple(p.strip() for p in raw.split(",") if p.strip()) if raw else _SAFE_AUTOMERGE_PATTERNS
    else:
        patterns = _SAFE_AUTOMERGE_PATTERNS_BY_REPO.get(repo, ())
    if not patterns:
        # No allowlist for this repo — nothing is auto-mergeable in it.
        return False, ["<no auto-merge path allowlist for this repo>"]
    try:
        from .github_service import _api_get

        ok, files = _api_get(f"/repos/{repo}/pulls/{pr_number}/files", {"per_page": 100})
    except Exception as exc:  # noqa: BLE001 - fail closed on any transport error
        logger.warning("[F.O.R.G.E.] PR #%s: could not list changed files (%s) — gating auto-merge", pr_number, exc)
        return False, ["<changed-file list unavailable>"]
    if not ok or not isinstance(files, list) or not files:
        logger.warning("[F.O.R.G.E.] PR #%s: changed-file list empty/unavailable — gating auto-merge", pr_number)
        return False, ["<changed-file list unavailable>"]
    blocking = [f.get("filename", "") for f in files if not any(re.search(p, f.get("filename", "")) for p in patterns)]
    return (not blocking), blocking


_HEAD_SHA_ATTEMPTS = 3
_HEAD_SHA_BACKOFF_S = 1.5


def pr_head_sha(pr_number: int, repo: str = None) -> str:
    """The PR's CURRENT head commit SHA, or '' if it genuinely cannot be read (#5646).

    Returns '' rather than raising: an unknown SHA means "cannot prove freshness",
    which the merge gate turns into a REFUSAL. That direction is deliberate and must
    not be softened — treating an unreadable SHA as a match would silently reinstate
    the hole this exists to close (a merge on a verdict that never saw the code).

    BOUNDED RETRY (F.O.R.G.E. review of PR #2601): a single transient GitHub failure
    would otherwise cost a legitimate merge until someone re-ran it. Retrying a
    read-only GET a few times removes that nuisance WITHOUT weakening the guarantee —
    the refusal still stands for a real, persistent failure. Deliberately small: this
    sits on the merge path, so it must not turn a GitHub outage into a long stall.
    """
    from .github_service import _api_get  # noqa: PLC0415

    last_err = None
    for attempt in range(_HEAD_SHA_ATTEMPTS):
        try:
            ok, data = _api_get(f"/repos/{repo or _DEFAULT_REPO}/pulls/{pr_number}")
            if ok and isinstance(data, dict):
                sha = str(((data.get("head") or {}).get("sha") or "")).strip()
                if sha:
                    return sha
                # A 200 with no head.sha is a SHAPE problem, not a transient one —
                # retrying cannot fix it, so stop and let the caller refuse.
                logger.warning("[PR Review] PR #%s response carried no head.sha", pr_number)
                return ""
            last_err = f"api_get ok={ok}"
        except Exception as exc:  # noqa: BLE001 — never fatal here; the caller refuses
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < _HEAD_SHA_ATTEMPTS - 1:
            time.sleep(_HEAD_SHA_BACKOFF_S * (attempt + 1))

    logger.warning(
        "[PR Review] could not read head SHA for PR #%s after %d attempts (%s) — "
        "the merge gate will refuse rather than assume freshness",
        pr_number,
        _HEAD_SHA_ATTEMPTS,
        last_err,
    )
    return ""


def mark_review_done(pr_number: int, summary: str, repo: str = None, auto_merge: bool = True) -> None:
    # Stamp WHICH COMMIT this verdict covers (#5646). Without it the gate could only
    # ask "is there an approval?", never "does it cover the code being merged?" — and
    # the ordinary workflow (open PR -> review -> address feedback -> push -> merge)
    # produces a stale verdict EVERY time. Measured on PR #2600: the stored APPROVE at
    # 02:38:36Z predated commit c787958fc at 02:41:41Z and had never seen the file that
    # commit changed, yet the gate reported a clean approval.
    _head = pr_head_sha(pr_number, repo)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE pr_reviews
            SET review_status='reviewed', ai_summary=%s, ai_review_at=NOW(), updated_at=NOW(),
                metadata = COALESCE(metadata, '{}'::jsonb)
                           || jsonb_build_object('reviewed_head_sha', %s::text)
            WHERE pr_number=%s AND repo=%s
            """,
            (summary, _head, pr_number, repo or _DEFAULT_REPO),
        )

    # ST-4: persist which review path produced this verdict + emit a telemetry line, so the
    # structured-vs-freeform ratio is observable (a silent drop to ~100% freeform = a regression).
    _path = _extract_review_path(summary)
    _mark_review_path(pr_number, _path, repo)
    # #5859 — APPEND this attempt before anything else can overwrite ai_summary. Without it a
    # rebuttal-flip (same head sha, REQUEST CHANGES -> APPROVE, zero code change) is erased by
    # the very re-review that proves the finding was false. Best-effort by construction.
    record_review_attempt(pr_number, summary, repo=repo, head_sha=_head, review_path=_path)
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

    # SAFETY GATE — machine-authored PRs are NEVER auto-merged, regardless of tier.
    # ONE definition, shared with github_service._automerge_governance_ok (THE merge
    # choke point) via machine_authored_reason() — see the block beside
    # _SAFE_AUTOMERGE_PATTERNS for why both are needed and what merged to main when
    # only this one existed. This branch is F.O.R.G.E. declining to merge what it just
    # approved; the choke point is what stops every OTHER actor, including the tier
    # worker that reaches merge_pr without passing through here at all.
    _branch = _review.get("branch") or _review.get("head_branch") or ""
    if machine_authored_reason(_review):
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO system_notifications (title, message, type, source, visibility) "
                "VALUES (%s, %s, 'warning', 'forge', 'all')",
                (
                    f"PR #{pr_number} needs human merge (autonomous or cockpit-authored)",
                    f"F.O.R.G.E. approved autonomous/cockpit PR #{pr_number} (branch {_branch!r}) — autonomous "
                    f"code is NEVER auto-merged; gated for a human /merge-pr.",
                ),
            )
        logger.info(
            "[F.O.R.G.E.] PR #%s is autonomous/cockpit-authored (branch=%s) — GATED from auto-merge (human merge required)",
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
        # HAND OFF, don't close. This used to call _mark_tier_processed, which is
        # the very flag the tiered-merge worker skips on — so F.O.R.G.E. saying
        # "above my ceiling, escalate" told A.R.C.H.I.E. "already handled".
        # Tier 2 never reached her and Tier 3 never reached Kytran's buttons;
        # every such PR waited for a manual /merge-pr (#5363).
        _mark_forge_escalated(pr_number, _tier)
        _next = "A.R.C.H.I.E. (COO)" if _tier == 2 else "Kytran"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO system_notifications (title, message, type, source, visibility) "
                "VALUES (%s, %s, 'info', 'forge', 'all')",
                (
                    f"PR #{pr_number} escalated to {_next} (Tier {_tier})",
                    f"F.O.R.G.E. approved PR #{pr_number}; it is Tier {_tier}, above F.O.R.G.E.'s "
                    f"ceiling ({_max_auto}), so merge authority passes to {_next}.",
                ),
            )
        logger.info(
            "[F.O.R.G.E.] PR #%s approved but Tier %s > max_auto %s — GATED (not merged)",
            pr_number,
            _tier,
            _max_auto,
        )
        return

    # AUTO-MERGE REPO ALLOWLIST (#4494, widened 2026-08-29 by owner decision: KSO is
    # software managed and created here, so it auto-merges under the SAME safety gates
    # as the platform). The original #4494 rationale said the write token was
    # archie-platform-scoped; the 2026-08-23 probe (#5981) measured push+admin on
    # kytran-system-operations too. The watch products and KBS stay review-only —
    # there the token genuinely has no access. A repo outside automerge_repos() is
    # auto-REVIEWED but gated to a human merge; a repo added to the list without a
    # _SAFE_AUTOMERGE_PATTERNS_BY_REPO entry still blocks on paths (deny-by-default).
    _merge_repo = repo or _DEFAULT_REPO
    if _merge_repo not in automerge_repos():
        logger.info(
            "[F.O.R.G.E.] PR #%s approved on %s — review-only (repo not in automerge_repos), not auto-merged (#4494)",
            pr_number,
            _merge_repo,
        )
        return

    # SENSITIVE-PATH GATE — code that RUNS the platform is never auto-merged.
    # The gates above judge SIZE, AUTHOR and REPO; none of them judge WHAT changed.
    # PR #2409 reached main with platform_v2/services/delegation_service.py in it
    # purely because the diff was small enough for Tier 1. Deny-by-default allowlist,
    # fails closed. Owner directive 2026-07-22.
    _paths_ok, _blocking = _automerge_paths_allowed(pr_number, _merge_repo)
    if not _paths_ok:
        _shown = ", ".join(_blocking[:5]) + (f" (+{len(_blocking) - 5} more)" if len(_blocking) > 5 else "")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO system_notifications (title, message, type, source, visibility) "
                "VALUES (%s, %s, 'warning', 'forge', 'all')",
                (
                    f"PR #{pr_number} needs human merge (touches service code)",
                    f"F.O.R.G.E. APPROVED PR #{pr_number}, but it changes files outside the "
                    f"auto-merge allowlist (docs / .claude / tests / qa_suites): {_shown}. "
                    f"Run /merge-pr to merge it deliberately.",
                ),
            )
        logger.info(
            "[F.O.R.G.E.] PR #%s approved but touches non-allowlisted paths (%s) — GATED for human merge",
            pr_number,
            _shown,
        )
        # ASK, don't just announce. This gate used to stop at the notification
        # above: no approval row, no buttons, nothing in the Approvals tab — the
        # owner got an unactionable "[INFO] F.O.R.G.E. Review: APPROVE" and had
        # to remember to type /merge-pr. Tier 3 already opens a durable row AND
        # a buttoned Telegram (#5283); this gate is just as much a
        # human-decision point, so it now uses the SAME dual surface. Both are
        # best-effort: a notification failure must never block the gate itself.
        try:
            _row = get_review(pr_number) or {}
            _title = _row.get("title") or f"PR #{pr_number}"
            _summary = _row.get("ai_summary") or "F.O.R.G.E. approved; touches non-allowlisted paths."
            _approval_id = open_pr_merge_approval(pr_number, _title, _summary, repo=_merge_repo)
            send_pr_merge_buttons(
                pr_number,
                _title,
                f"F.O.R.G.E. APPROVED, but this changes files outside the auto-merge "
                f"allowlist:\n`{_shown}`\n\n{_summary[:280]}",
            )
            # #6649: THIS is the producer that started the alert loop. It opened the
            # durable row and sent the buttoned Telegram — both surfaces, correctly —
            # but never set `kytran_approval_sent`. The 2-minute `forge_archie_pr_review`
            # worker skips a PR only when `tier_processed` or `kytran_approval_sent` is
            # set, so it re-processed this PR on every tick, hit the same governance
            # refusal, and re-paged. 49 duplicate pages for PR #3238 over 1h43m.
            #
            # Recording it here is ADR-014-correct: the ROW EXISTS (we have its id) and
            # the owner has been paged. We are recording the artifact, not the intent —
            # which is why it is gated on `_approval_id` rather than set unconditionally.
            if _approval_id:
                _mark_kytran_approval_sent(pr_number, repo=_merge_repo)
        except Exception as _ask_exc:  # noqa: BLE001
            logger.warning("[F.O.R.G.E.] PR #%s: could not open the merge approval: %s", pr_number, _ask_exc)
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


# ---------------------------------------------------------------------------
# THE STUCK-REVIEW WINDOW — one definition, two consumers.
#
# ``reap_stale_reviews`` (below) decides WHEN a stuck review is recovered; the
# ``review_progress`` UI helper decides when to TELL the operator it is overdue.
# Those two must agree, so the numbers live here rather than being retyped at
# each site. A UI measuring staleness on its own clock would confidently promise
# a recovery that never comes — or cry stale at a review the reaper thinks is fine.
#
# _REAP_INTERVAL_MINUTES mirrors the ``forge_review_reaper`` IntervalTrigger in
# ai_bridge/agent_loop.py. It is used ONLY to word the hint ("re-driven within
# ~5m"); nothing schedules off it here, so a drift is cosmetic, not behavioural.
# ---------------------------------------------------------------------------

_REAP_STALE_MINUTES = 20
_REAP_INTERVAL_MINUTES = 5


def reap_stale_reviews(stale_minutes: int = _REAP_STALE_MINUTES, max_retries: int = 3) -> dict:
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


# ---------------------------------------------------------------------------
# MERGE STATE — what the Merge affordance should SAY before you click it (#5853).
#
# THE BUG THIS FIXES: the Merge button rendered unconditionally green/enabled for every
# open PR, and the badge beside it showed `review_status`, whose green "reviewed" is
# IDENTICAL for an APPROVE, a REQUEST CHANGES and a coverage demotion. So a refused PR
# displayed a green badge next to a green button — the UI actively signalled "good to go"
# on something the gate would refuse. You learned the truth by clicking. Measured live
# 2026-08-20 on PR #2736: first click 422, second click (with ack) 200.
#
# ⚠️ THE VERDICT RULE STAYS ON THE SERVER. This composes the EXISTING predicates and adds
# no new ones. Re-deriving "is this approved" in JS would be a second implementation of a
# safety rule — exactly what #2722 existed to collapse, and how #2458 reached main.
#
# ⚠️ ORDER IS LOAD-BEARING: approved BEFORE coverage_only BEFORE changes_requested. A
# coverage demotion rewrites the FINAL verdict to NEEDS REVIEW (so verdict_is_approved is
# False) while coverage_only_demotion re-reads the ORIGINAL — and a REQUEST CHANGES that
# was ALSO coverage-demoted must land in changes_requested, never coverage_only, because
# an ack is consent to unread files and never consent to a defect.
MERGE_STATE_REVIEWING = "reviewing"
MERGE_STATE_AWAITING = "awaiting_review"
MERGE_STATE_APPROVED = "approved"
MERGE_STATE_COVERAGE_ONLY = "coverage_only"
MERGE_STATE_CHANGES = "changes_requested"
MERGE_STATE_CLOSED = "closed"


def merge_state(
    review_status: str | None,
    ai_summary: str | None,
    base_branch: str | None = None,
    default_branch: str = "main",
    pr_state: str | None = None,
) -> dict:
    """Derive what the UI should render for one PR row. Pure — no DB, no Flask.

    Returns {state, mergeable, label, hint, dropped_files, base_branch, stacked}.
    `mergeable` means only "the gate would not refuse outright"; coverage_only is
    mergeable ONLY with an explicit ack, which the merge handler still enforces
    server-side.

    ⚠️ `base_branch` does NOT change `state` or `mergeable`. WHERE a PR lands is
    orthogonal to WHETHER it is fit to land, so it decorates the label/hint only —
    exactly like the Approvals category filter, which is presentation and can never
    relax a gate. Merging a stacked PR into its parent is legitimate; it just is not
    shipping, and the row must say so.

    ⚠️ `pr_state` DOES change both, and is checked FIRST — before the review status,
    before the verdict. A closed or merged PR cannot be merged whatever its verdict
    says, so no later branch may override it. Measured 2026-09-20 (#6792): five rows
    carried a correct `state='closed'` while rendering `mergeable=True` behind a green
    Merge button, because this function was never handed the field that sat on the very
    row its result was being stamped onto.

    FAIL-SAFE on absence: an unknown/empty `pr_state` is treated as OPEN, so every
    pre-#6792 caller is byte-identical. Blocking a genuinely open PR on missing data
    would stop real work; a stale Merge button costs one refused GitHub call, and the
    server-side merge gate binds either way.
    """
    status = (review_status or "").strip().lower()
    summary = ai_summary or ""

    # FIRST — ahead of in_progress, ahead of the verdict. A closed PR with a review
    # still running reads CLOSED; "REVIEWING…" on a dead PR is noise, not information.
    life = (pr_state or "").strip().lower()
    if life in ("closed", "merged"):
        _merged = life == "merged"
        return _with_merge_target(
            {
                "state": MERGE_STATE_CLOSED,
                "mergeable": False,
                "label": "MERGED" if _merged else "CLOSED",
                "hint": (
                    "This PR is already merged — nothing left to land."
                    if _merged
                    else "This PR is closed. Reopen it on GitHub if it should still ship."
                ),
                "dropped_files": [],
            },
            base_branch,
            default_branch,
        )

    if status == "in_progress":
        return _with_merge_target(
            {
                "state": MERGE_STATE_REVIEWING,
                "mergeable": False,
                "label": "REVIEWING…",
                "hint": "A review is running — wait for it to finish.",
                "dropped_files": [],
            },
            base_branch,
            default_branch,
        )
    if not summary.strip() or status == "pending":
        return _with_merge_target(
            {
                "state": MERGE_STATE_AWAITING,
                "mergeable": False,
                "label": "WAITING FOR REVIEW",
                "hint": "No stored verdict yet — nothing has reviewed this PR.",
                "dropped_files": [],
            },
            base_branch,
            default_branch,
        )

    if verdict_is_approved(summary):
        return _with_merge_target(
            {
                "state": MERGE_STATE_APPROVED,
                "mergeable": True,
                "label": "APPROVED",
                "hint": "",
                "dropped_files": [],
            },
            base_branch,
            default_branch,
        )

    if coverage_only_demotion(summary):
        dropped = coverage_dropped_paths(summary) or []
        return _with_merge_target(
            {
                "state": MERGE_STATE_COVERAGE_ONLY,
                "mergeable": True,  # only WITH an ack — the route still enforces it
                "label": f"COVERAGE · {len(dropped)} unread",
                # Reuse the refusal's own words so the row and the refusal agree.
                "hint": _merge_hint(summary, False),
                "dropped_files": dropped,
            },
            base_branch,
            default_branch,
        )

    return _with_merge_target(
        {
            "state": MERGE_STATE_CHANGES,
            "mergeable": False,
            "label": "CHANGES REQUESTED",
            "hint": _merge_hint(summary, False),
            "dropped_files": [],
        },
        base_branch,
        default_branch,
    )


def _with_merge_target(result: dict, base_branch: str | None, default_branch: str) -> dict:
    """Name the branch a merge would actually land on. PURE.

    WHY: 2026-08-25, a 4-PR stack was shipped by clicking Merge on the TOP one. That
    folded it into its own parent — a branch that already contained everything below it —
    so the click was a no-op and `main` never moved. The row read "Merge" and gave no
    hint that it was not shipping. `pr_reviews.base_branch` was already populated by
    `poll_open_prs`; nothing had ever read it.

    Stacked PRs stay MERGEABLE — merging into a parent is a legitimate act. The row just
    has to say where it goes.
    """
    base = (base_branch or "").strip()
    out = dict(result)
    out["base_branch"] = base or None
    out["stacked"] = bool(base) and base != default_branch
    if not out["stacked"]:
        return out
    if out.get("mergeable"):
        out["label"] = f"{out.get('label', 'MERGE')} → {base}"
    warning = (
        f"Merges into '{base}', NOT {default_branch} — this will NOT ship. "
        f"Merge the PRs below it first (bottom-up); GitHub retargets each one as its "
        f"parent lands."
    )
    existing = (out.get("hint") or "").strip()
    out["hint"] = f"{warning} · {existing}" if existing else warning
    return out


def _merge_hint(summary: str, verdict_ok: bool) -> str:
    """The refusal string the merge route itself would produce, verbatim.

    Imported lazily: github_service imports this module, so a top-level import would be
    circular. Never raises — a missing hint must not blank the whole row.
    """
    try:
        from tools.repair_bay.services.github_service import verdict_refusal

        return verdict_refusal(summary, verdict_ok) or ""
    except Exception:  # noqa: BLE001
        return ""


def _elapsed_minutes(ts, now=None) -> int | None:
    """Whole minutes between ``ts`` and now, or None if that cannot be computed.

    Defensive about tz-awareness on purpose: ``pr_reviews.updated_at`` is TIMESTAMPTZ,
    but several platform tables deviate from that convention (``forge_reviews.created_at``,
    ``agent_emotional_state.timestamp``), and a naive/aware subtraction raises TypeError.
    Here that would blank a whole row over a formatting detail, so an un-subtractable
    value degrades to "unknown" instead.
    """
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone

        ref = now or datetime.now(timezone.utc)
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if getattr(ref, "tzinfo", None) is None:
            ref = ref.replace(tzinfo=timezone.utc)
        seconds = (ref - ts).total_seconds()
    except (AttributeError, TypeError, ValueError, OverflowError):
        # Narrowed deliberately (F.O.R.G.E. review of #3389): these are the four ways a
        # bad timestamp actually arrives — a non-datetime (AttributeError on .tzinfo), a
        # naive/aware mismatch the guards above missed (TypeError), an unparseable or
        # out-of-range value (ValueError/OverflowError). A bare `except Exception` also
        # swallowed genuine programming errors in this function, which is the one class
        # of failure that should be loud.
        return None
    # A row written microseconds ago, or mild clock skew, can read slightly negative.
    # Clamp rather than render a negative age.
    return max(0, int(seconds // 60))


def _humanize_minutes(mins: int) -> str:
    if mins < 1:
        return "just started"
    if mins < 60:
        return f"{mins}m"
    hours, rem = divmod(mins, 60)
    return f"{hours}h" if rem == 0 else f"{hours}h {rem}m"


def review_progress(
    review_status: str | None,
    updated_at=None,
    now=None,
    stale_minutes: int = _REAP_STALE_MINUTES,
) -> dict:
    """What an in-flight "Reviewing…" row should SAY. Pure — no DB, no Flask.

    THE DEFECT THIS ADDRESSES: an in-flight review rendered as a bare, disabled
    "Analyzing…" with no elapsed time and no way out, so a review that would finish in
    40 seconds and one whose dispatch died 45 minutes ago were pixel-identical. The only
    way to tell them apart was the CLI — which is exactly what happened on archie-platform
    #3385 and archie-code #71: both read "Reviewing…", one had a live dispatch, the other
    had already had one reaped.

    ⚠️ The threshold is NOT cosmetic — it is ``reap_stale_reviews``' own window, measured
    off the same column (``pr_reviews.updated_at``). Keeping them in step is the whole
    point: this function only ever *predicts* what the reaper will do.

    Returns {active, elapsed_minutes, label, stale, hint, reap_minutes}. ``active`` is
    False for every non-``in_progress`` status, so callers can render unconditionally.
    """
    idle = {
        "active": False,
        "elapsed_minutes": None,
        "label": None,
        "stale": False,
        "hint": None,
        "reap_minutes": stale_minutes,
    }
    if (review_status or "") != "in_progress":
        return idle

    elapsed = _elapsed_minutes(updated_at, now)
    if elapsed is None:
        # We do NOT know how long it has run. Say that. Rendering "0m" here would read
        # as "just started" — a claim the data does not support, and the precise kind of
        # confident-but-unfounded status this change exists to remove.
        return {
            "active": True,
            "elapsed_minutes": None,
            "label": "Analyzing…",
            "stale": False,
            "hint": "Elapsed time unknown — this row carries no updated_at.",
            "reap_minutes": stale_minutes,
        }

    stale = elapsed >= stale_minutes
    if stale:
        hint = (
            f"Running {_humanize_minutes(elapsed)} — past the {stale_minutes}m stuck-review "
            f"window. The reaper resets it within ~{_REAP_INTERVAL_MINUTES}m, or use Retry "
            f"to reset it now."
        )
    else:
        hint = (
            f"Running {_humanize_minutes(elapsed)}. A per-file review is several SERIAL "
            f"dispatches, so minutes are expected; it is only overdue past {stale_minutes}m."
        )
    return {
        "active": True,
        "elapsed_minutes": elapsed,
        "label": f"Analyzing… {_humanize_minutes(elapsed)}",
        "stale": stale,
        "hint": hint,
        "reap_minutes": stale_minutes,
    }


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
        rows = [dict(r) for r in cur.fetchall()]
    # Stamp the merge state server-side (#5853) so the UI renders a decision it did not
    # make. Kept out of the SQL deliberately: the verdict rule is Python, and a second
    # copy of it in SQL would be the same duplication the JS copy would have been.
    for row in rows:
        row["merge_state"] = merge_state(
            row.get("review_status"),
            row.get("ai_summary"),
            row.get("base_branch"),
            pr_state=row.get("state"),
        )
        # Same rule as merge_state: the elapsed time AND the overdue threshold are decided
        # server-side, so the template cannot drift from the reaper's actual window.
        row["review_progress"] = review_progress(row.get("review_status"), row.get("updated_at"))
    return rows


def stamp_merge_states(prs: list, repo: str = None) -> list:
    """Stamp ``merge_state`` onto GitHub-shaped PR dicts from their STORED verdicts.

    The Reviews-tab list (``GET /api/forge/prs``) renders from a GitHub payload whose
    ``mergeable`` / ``review_decision`` fields know nothing about F.O.R.G.E. — it stores
    its verdict in ``pr_reviews.ai_summary`` and posts **no GitHub review**, so
    ``review_decision`` is ~always null and a button gated on it degenerates to
    "mergeable => green". That surface therefore rendered an enabled green Merge on a
    REQUEST CHANGES and on a coverage demotion alike (#5853); #2737 fixed only the
    OTHER surface, which reads ``list_reviews()``.

    Reuses the same pure ``merge_state()`` as ``list_reviews`` so the two surfaces cannot
    drift — a second copy of the verdict rule is exactly what #2722 collapsed.

    Fail-CLOSED, in both directions that matter:
      * a PR with **no stored row** stamps ``awaiting_review`` / ``mergeable=False``,
        which is precisely what ``verdict_refusal("", False)`` returns for an empty
        summary ("a dead review is not an approval"), so the row and the route agree;
      * a **DB read error** stamps the same, because a UI that cannot read the verdict
        must not imply one.
    The UI can therefore only ever be MORE conservative than the server, never less —
    it is a mirror of the gate, not a second gate.
    """
    prs = prs or []
    if not prs:
        return prs
    _repo = (repo or _DEFAULT_REPO).strip()

    numbers = []
    for pr in prs:
        n = pr.get("number")
        if isinstance(n, int):
            numbers.append(n)

    stored: dict = {}
    if numbers:
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT pr_number, review_status, ai_summary FROM pr_reviews "
                    "WHERE repo = %s AND pr_number = ANY(%s)",
                    (_repo, numbers),
                )
                for row in cur.fetchall():
                    stored[row["pr_number"]] = (row["review_status"], row["ai_summary"])
        except Exception as e:  # fail-CLOSED: unknown verdict => not mergeable
            logger.warning(
                "stamp_merge_states: verdict lookup failed for %s, rendering all rows " "as awaiting_review: %s",
                _repo,
                e,
            )
            stored = {}

    for pr in prs:
        status, summary = stored.get(pr.get("number"), (None, None))
        pr["merge_state"] = merge_state(status, summary, pr_state=pr.get("state"))
    return prs


def get_review(pr_number: int, repo: str = None) -> dict | None:
    """Fetch a single PR review by number."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM pr_reviews WHERE pr_number=%s AND repo=%s",
            (pr_number, repo or _DEFAULT_REPO),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_fix_requests_from_review(pr_number: int, repo: str = None) -> dict:
    """#5932 Phase 1 — make a REQUEST CHANGES actionable without Claude.

    Human-triggered (the Repair Bay PR Review "Send back to coders" button): each
    blocking finding (CRITICAL/WARNING) in the stored F.O.R.G.E. review becomes an
    ``improvement_proposals`` row with ``status='fix_requested'``, carrying the
    finding text AND its evidence line plus pr_number/repo/head_sha.
    ``metadata.source='pr_review_finding'`` keeps it distinguishable from
    'code_health_audit'. NO automatic execution in this phase: the proposal simply
    appears in the existing queue that already consumes fix_requested rows.

    A finding WITHOUT an evidence line is counted in ``skipped_no_evidence`` and
    NOT created — the review integrity gates key off evidence, so a fix request
    without one can never be verified as addressed (task #5932 gotcha). Nothing is
    dropped silently. Idempotent: an already-open row for the same
    (pr, repo, evidence) counts as a duplicate instead of minting a twin — the
    #2896 lesson, dedup at CREATION.
    """
    repo = repo or _DEFAULT_REPO
    review = get_review(pr_number, repo)
    if not review:
        return {"success": False, "error": f"no tracked review for PR #{pr_number} ({repo})"}
    summary = review.get("ai_summary") or ""
    if not summary.strip():
        return {"success": False, "error": f"PR #{pr_number} has no stored F.O.R.G.E. review to send back"}

    from .pr_diff_analyzer import _parse_freeform_issues  # canonical ISSUES-line parser

    findings = _parse_freeform_issues(summary)
    blocking = [f for f in findings if (f.get("severity") or "").upper() in ("CRITICAL", "WARNING")]
    if not blocking:
        return {
            "success": False,
            "error": "review has no CRITICAL/WARNING findings to send back",
            "findings_total": len(findings),
        }

    try:
        head_sha = pr_head_sha(pr_number, repo)
    except Exception as e:  # a GitHub blip must not block a human send-back
        logger.warning("send-back: could not resolve head_sha for PR #%s: %s", pr_number, e)
        head_sha = None

    created, duplicates, skipped_no_evidence = [], 0, 0
    with get_db_cursor(commit=True) as (conn, cur):
        for f in blocking:
            evidence = (f.get("evidence") or "").strip()
            if not evidence:
                skipped_no_evidence += 1
                continue
            finding_title = (f.get("title") or "review finding").strip()
            cur.execute(
                """
                SELECT id FROM improvement_proposals
                 WHERE metadata->>'source' = 'pr_review_finding'
                   AND metadata->>'pr_number' = %s
                   AND COALESCE(metadata->>'repo', '') = %s
                   AND metadata->>'evidence' = %s
                   AND status NOT IN ('archived', 'rejected', 'deployed')
                 LIMIT 1
                """,
                (str(pr_number), repo, evidence),
            )
            if cur.fetchone():
                duplicates += 1
                continue
            title = f"[FIX REQUEST] PR #{pr_number}: {finding_title}"[:120]
            description = (
                f"Human send-back of a F.O.R.G.E. review finding on PR #{pr_number} ({repo}).\n\n"
                f"**Severity:** {f.get('severity')}\n"
                f"**Finding:** {finding_title}\n"
                + (f"**Why it matters:** {f.get('why')}\n" if f.get("why") else "")
                + f"**Evidence (the diff line the review cited):**\n```\n{evidence}\n```\n"
                + (f"**Head SHA at send-back:** {head_sha}\n" if head_sha else "")
            )
            metadata = json.dumps(
                {
                    "source": "pr_review_finding",
                    "pr_number": str(pr_number),
                    "repo": repo,
                    "head_sha": head_sha,
                    "severity": (f.get("severity") or "").upper(),
                    "finding_title": finding_title,
                    "finding_why": f.get("why") or "",
                    "evidence": evidence,
                    "auto_generated": False,
                }
            )
            cur.execute(
                """
                INSERT INTO improvement_proposals
                    (title, category, description, code_changes, rationale,
                     priority, risk_level, status, metadata, collaboration_enabled)
                VALUES (%s, 'pr_review_fix', %s, '', %s, %s, 'medium', 'fix_requested', %s::jsonb, false)
                RETURNING id
                """,
                (
                    title,
                    description,
                    f"Owner-triggered send-back from Repair Bay PR Review (PR #{pr_number})",
                    "critical" if (f.get("severity") or "").upper() == "CRITICAL" else "medium",
                    metadata,
                ),
            )
            created.append(cur.fetchone()["id"])

    logger.info(
        "[send-back] PR #%s (%s): %d fix request(s) created, %d duplicate(s), %d without evidence",
        pr_number,
        repo,
        len(created),
        duplicates,
        skipped_no_evidence,
    )
    return {
        "success": True,
        "pr_number": pr_number,
        "repo": repo,
        "head_sha": head_sha,
        "created": created,
        "duplicates": duplicates,
        "skipped_no_evidence": skipped_no_evidence,
        "findings_total": len(findings),
    }


# ---- Tiered PR Merge Authority ----

_TIER3_TITLE_KW = {"breaking", "migration", "security"}


def classify_pr_tier(review: dict) -> int:
    """Classify a PR review into merge tier 1 (F.O.R.G.E.), 2 (A.R.C.H.I.E.), or 3 (Kytran).

    Tier 3 (highest precedence):
        - > 1500 lines changed
        - title contains breaking/migration/security
        - branch looks like a numbered migration (e.g. 382_partner_profiles)
        - F.O.R.G.E. verdict contains REJECT
        - touches a KERNEL path — lane_classifier.KERNEL_PATTERNS (#5986)

    The kernel gate needs ``review["changed_paths"]``. That is stamped by
    ``pr_diff_analyzer._obtain_review_summary``, which already holds the diff, so the
    REVIEW path always has it. A review dict loaded straight from the DB (e.g. at merge
    time) does NOT, and then this gate is silently inert — deliberately, and safely: the
    merge path refuses sensitive paths earlier and unconditionally via
    ``_automerge_paths_allowed`` (CONDITION 2), which fails CLOSED and binds every actor.
    Do not "fix" that by making this function fetch the file list; it is pure, it is
    monkeypatched in seven test files, and it sits on hot paths.

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
    # KERNEL PATHS (#5986). Every gate above this line reads SIZE, TITLE or BRANCH — never
    # what the PR actually touches. The branch-name migration check right above is a proxy
    # for "touches a migration" and is trivially missed: a branch called `fix/typo` that
    # adds database/migrations/479_x.sql escapes it and classifies on size alone.
    #
    # Tier is not only a merge ceiling. `pr_diff_analyzer._review_is_strong` is `tier >= 3`,
    # and it picks the REVIEW MODEL: Tier 3 gets gemma3:12b at the wide cap, everything else
    # qwen2.5:7b at the tight one. So before this gate a small diff to the dispatch kernel,
    # the merge kernel, rbac.py or auth_service.py drew the WEAKEST review available —
    # exactly inverted.
    #
    # Uses lane_classifier.is_kernel_path so the tier ladder and the coder-lane boundary
    # cannot drift apart (decision #953: safety properties are universal).
    from services.lane_classifier import is_kernel_path  # noqa: PLC0415

    if any(is_kernel_path(p) for p in (review.get("changed_paths") or [])):
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


def _mark_tier_processed(pr_number: int, tier: int, repo: str = None) -> None:
    """Record that a tier decision was CARRIED OUT (merged, or sent to Kytran).

    ⚠️ TERMINAL ONLY. ``metadata.tier_processed`` is the flag the tiered-merge
    worker skips on (``if meta.get("tier_processed") … continue``), so writing it
    means "this PR is DONE, never look at it again". Only call it after a real
    merge or after Tier 3 has been handed to Kytran.

    Do NOT use it to record that F.O.R.G.E. ESCALATED — see
    ``_mark_forge_escalated``. Doing so was a live bug: F.O.R.G.E. saying "above
    my ceiling, pass to the COO" wrote the same field that tells the COO
    "already handled", so A.R.C.H.I.E.'s Tier-2 merge and Kytran's Tier-3
    buttons were both unreachable and every such PR waited for a manual
    /merge-pr (#5363; PRs #2523/#2524/#2528/#2533, 2026-07-28).
    """
    from psycopg2.extras import Json as _Json  # noqa: PLC0415
    from services.time_utils import now_utc  # noqa: PLC0415

    payload = _Json({"tier_processed": tier, "tier_processed_at": now_utc().isoformat()})
    with get_db_cursor(commit=True) as (conn, cur):
        # See _mark_kytran_approval_sent for why `repo` matters: pr_number is not
        # unique in pr_reviews (PR #19 exists in FIVE repos, measured 2026-09-07).
        # repo=None keeps the historical repo-blind UPDATE for callers that do not
        # know their repo, rather than silently narrowing them.
        #
        # ⚠️ This is `tier_processed` — the WORKER SKIP flag. Do not confuse it with
        # `_mark_forge_escalated`'s `forge_escalated_tier`, which is deliberately a
        # DIFFERENT key: #5363 found that writing the skip flag on escalation made
        # "pass this up to the next authority" read as "already handled", so Tier 2
        # never reached the COO and Tier 3 never reached Kytran (PRs #2523/#2524/
        # #2528/#2533). `TestEscalationIsNotCompletion` pins that separation.
        if repo:
            cur.execute(
                "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s "
                "WHERE pr_number = %s AND repo = %s",
                (payload, pr_number, repo),
            )
        else:
            cur.execute(
                "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
                (payload, pr_number),
            )


def _mark_forge_escalated(pr_number: int, tier: int) -> None:
    """Record that F.O.R.G.E. handed a PR UP the ladder — a hand-off, not a completion.

    Deliberately a DIFFERENT key from ``tier_processed``: the next authority
    (A.R.C.H.I.E. at Tier 2, Kytran at Tier 3) must still find this PR waiting
    for them. Tier 1 F.O.R.G.E. → Tier 2 A.R.C.H.I.E. → Tier 3 Kytran is the
    governance ladder; an escalation is the START of the next actor's turn.
    """
    from psycopg2.extras import Json as _Json  # noqa: PLC0415
    from services.time_utils import now_utc  # noqa: PLC0415

    payload = _Json({"forge_escalated_tier": tier, "forge_escalated_at": now_utc().isoformat()})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
            (payload, pr_number),
        )


def _mark_kytran_approval_sent(pr_number: int, repo: str = None) -> None:
    """Prevent duplicate Tier 3 TELEGRAM messages for this PR.

    NOTE (#5283): this flag gates the Telegram send ONLY. It must never be used to
    skip creating the ``autonomy_approval_queue`` row — the two surfaces are
    independent, and suppressing the durable row is exactly how a missed Telegram
    used to strand a PR with nothing visibly pending anywhere.

    ⚠️ PASS ``repo`` (#6649). ``pr_number`` is NOT unique in ``pr_reviews`` — that
    table has a ``repo`` column and the same number exists across repos. Measured
    2026-09-07: **PR #19 exists in FIVE repos** (archie-code, archie-platform,
    kytran-business-suite, kytran-civic-watch, kytran-legal-watch), #16/#7/#13/#15/#20
    in four each. A repo-blind UPDATE therefore marks every repo's PR #19 as "the
    owner has been asked", silently retiring four live PRs from the escalation path
    with no log line anywhere.

    ``repo=None`` preserves the old repo-blind behaviour on purpose: narrowing an
    existing caller's UPDATE without its knowledge could leave the flag unset and
    reintroduce the very re-escalation loop this parameter exists to stop. Callers
    that know their repo must pass it.
    """
    from psycopg2.extras import Json as _Json  # noqa: PLC0415

    payload = _Json({"kytran_approval_sent": True})
    with get_db_cursor(commit=True) as (conn, cur):
        if repo:
            cur.execute(
                "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s "
                "WHERE pr_number = %s AND repo = %s",
                (payload, pr_number, repo),
            )
        else:
            cur.execute(
                "UPDATE pr_reviews SET metadata = COALESCE(metadata, '{}'::jsonb) || %s WHERE pr_number = %s",
                (payload, pr_number),
            )


def pending_pr_merge_approval(pr_number: int, repo: str = None) -> "int | None":
    """Id of a LIVE pending ``pr_merge`` approval row for this PR, else None.

    Exists so ``_escalate_blocked_merge`` can tell the two reasons
    ``open_pr_merge_approval`` returns None apart (#6649):

      * **dedup** — a row already exists, so the owner HAS an actionable item and
        has already been paged. Re-paging adds nothing.
      * **draft guard / error** — no row exists, so the request would genuinely be
        lost if we recorded it as asked.

    Treating those identically is what produced the alert loop: every 2-minute tick
    re-sent the Telegram and then declined to set the flag, so the next tick did it
    again. Measured 59 sends over 7 days, all of them dedups (49 for PR #3238 alone,
    over 1h43m), with zero draft-guard and zero error cases.

    ⚠️ Repo-aware ON PURPOSE, unlike ``_check_existing_approval``'s dedup predicate,
    which matches on ``pr_number`` alone. This function's answer SUPPRESSES a page,
    so a cross-repo false match here would silence a real request.
    """
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = 'pr_merge'
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND action_data->>'pr_number' = %s
                  AND (%s::text IS NULL OR action_data->>'repo' = %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(pr_number), repo, repo),
            )
            row = cur.fetchone()
        if not row:
            return None
        return row["id"] if isinstance(row, dict) else row[0]
    except Exception:  # noqa: BLE001
        # Fail to None — "we could not confirm a row exists" must behave like
        # "no row", i.e. keep retrying. Suppressing a page on an unreadable DB
        # would be the #5829 trap (recording intent as artifact) via a new door.
        logger.warning("pending_pr_merge_approval: lookup failed for PR #%s", pr_number, exc_info=True)
        return None


def _pr_is_draft(pr_number: int, repo: str = None) -> "bool | None":
    """True/False from GitHub's PR object; None when unreadable.

    Fail-OPEN on None — an unreadable draft state must never block raising a
    legitimate approval; the guard only acts on a POSITIVE draft reading.
    """
    try:
        from .github_service import REPO_FULL, _api_get  # noqa: PLC0415

        ok, data = _api_get(f"/repos/{repo or REPO_FULL}/pulls/{pr_number}")
        if ok and isinstance(data, dict) and "draft" in data:
            return bool(data.get("draft"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("_pr_is_draft failed for PR #%s: %s", pr_number, exc)
    return None


def open_pr_merge_approval(pr_number: int, title: str, summary: str, repo: str = None) -> "int | None":
    """Create the durable Approvals-tab row for a Tier-3 PR (#5283).

    The second surface beside the Telegram message. Tier 3 previously notified via
    Telegram ONLY, send-once — so a missed, dismissed or undelivered message left
    the PR stranded with nothing pending in the Approvals tab.

    ⚠️ Two DIFFERENT meanings of "tier" meet here, and conflating them auto-merges
    the one thing that must never auto-merge:
      * PR merge-authority tier — 1 F.O.R.G.E. / 2 A.R.C.H.I.E. / 3 Kytran.
      * approval-queue tier     — 1 = AUTO-APPROVE, 2 = wait for a human.
    A PR-authority Tier 3 must therefore be filed as queue ``tier=2`` (wait for a
    human). Passing tier=1 here would auto-approve it instantly.

    Returns the approval id, or None if it could not be created (never raises —
    failing to open the row must not break the Telegram path that follows).
    """
    # #5403: a DRAFT PR is structurally un-mergeable — GitHub 405s the merge.
    # Raising an approval for one asks a human to authorise the impossible and
    # then BURNS their authorisation when the executor hits the 405 (approval
    # 6485 / PR #2549, 2026-07-29: Kytran tapped approve, the 405 flipped the
    # row 'failed', nothing re-raised, the PR sat unmerged). Guard fires only
    # on a POSITIVE draft reading; an unreadable state fails open.
    if _pr_is_draft(pr_number, repo) is True:
        logger.info("open_pr_merge_approval: PR #%s is a DRAFT — no approval raised (#5403)", pr_number)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO system_notifications (title, message, type, source, visibility) "
                    "VALUES (%s, %s, 'warning', 'forge', 'all')",
                    (
                        f"PR #{pr_number} is a DRAFT — merge approval NOT raised",
                        f"PR #{pr_number} ({title}) passed review but is still a draft, which GitHub "
                        "refuses to merge. Mark it 'Ready for review' and the approval will be raised "
                        "on the next review pass — no authorisation was requested or spent.",
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("draft-guard notification failed for PR #%s: %s", pr_number, exc)
        return None

    try:
        from ai_bridge.agent_loop import request_approval  # noqa: PLC0415

        return request_approval(
            action_type="pr_merge",
            action_data={
                "pr_number": pr_number,
                "title": title,
                "summary": (summary or "")[:1000],
                "repo": repo,
            },
            reason=f"PR #{pr_number} is Tier 3 — requires Kytran's approval before merge: {title}",
            requested_by="archie_pr_review_worker",
            priority=7,
            tier=2,  # queue tier 2 = WAIT FOR HUMAN. Never 1. See docstring.
        )
    except Exception as exc:
        logger.warning("open_pr_merge_approval failed for PR #%s: %s", pr_number, exc)
        return None


def send_pr_merge_buttons(pr_number: int, title: str, summary: str, repo: str = None) -> None:
    """Telegram message with ✅ Merge / ❌ Deny for a PR awaiting a human merge.

    Same callback_data the Tier-3 path uses (``pr_merge_approve_N`` /
    ``pr_merge_deny_N``), so ONE gateway handler serves every surface. Kept here
    rather than on AgentLoop so the review service can ask directly — the
    sensitive-path gate runs in the platform container, not the agent loop.
    Best-effort: never raises.
    """
    # #5403: same draft guard as open_pr_merge_approval — a Merge button on a
    # draft can only 405. open_pr_merge_approval already posted the explanation,
    # so this just skips quietly.
    if _pr_is_draft(pr_number, repo) is True:
        logger.info("send_pr_merge_buttons: PR #%s is a DRAFT — buttons skipped (#5403)", pr_number)
        return
    try:
        from services.telegram_service import send_with_buttons  # noqa: PLC0415

        send_with_buttons(
            category="system",
            title=f"PR #{pr_number} — Merge Approval Required",
            message=(f"*PR #{pr_number}:* {title}\n\n{(summary or '')[:600]}\n\nApprove to merge."),
            buttons=[
                {"text": "✅ Merge", "callback_data": f"pr_merge_approve_{pr_number}"},
                {"text": "❌ Deny", "callback_data": f"pr_merge_deny_{pr_number}"},
            ],
            source_agent="A.R.C.H.I.E.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_pr_merge_buttons failed for PR #%s: %s", pr_number, exc)


def resolve_pr_merge_approval(pr_number: int, approved: bool, user_id: int = None) -> None:
    """Close the Approvals-tab row for a PR decided on EITHER surface (#5283).

    Shared by the Telegram callback and the Approvals-tab action so the two can
    never disagree: whichever one the owner uses, the other stops showing a
    pending item. Idempotent — resolving an already-resolved row is a no-op, so a
    double-tap across both surfaces cannot merge twice.

    Best-effort: never raises. A bookkeeping failure must not turn a SUCCESSFUL
    merge into a reported failure.
    """
    try:
        status = "approved" if approved else "rejected"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE autonomy_approval_queue
                   SET status = %s,
                       approved_by = COALESCE(%s, approved_by),
                       approved_at = NOW(),
                       updated_at = NOW()
                 WHERE action_type = 'pr_merge'
                   AND status = 'pending'
                   AND (action_data->>'pr_number')::int = %s
                """,
                (status, user_id, pr_number),
            )
    except Exception as exc:
        logger.warning("resolve_pr_merge_approval failed for PR #%s: %s", pr_number, exc)


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


_ATTEMPT_SEVERITY_RE = re.compile(r"^\s*-\s*\[(CRITICAL|WARNING|INFO|LOW)\]", re.M)


def _attempt_severity_counts(summary: str) -> dict:
    """{severity: n} over the rendered '- [SEV] ...' finding lines."""
    out: dict = {}
    for sev in _ATTEMPT_SEVERITY_RE.findall(summary or ""):
        out[sev] = out.get(sev, 0) + 1
    return out


def record_review_attempt(
    pr_number: int,
    summary: str,
    repo: str = None,
    head_sha: str = None,
    review_path: str = None,
) -> int | None:
    """Append THIS review attempt to ``forge_reviews`` (#5859, corpus for #5857).

    ``pr_reviews`` is UNIQUE on (pr_number, repo) and ``mark_review_done`` UPDATEs
    ``ai_summary`` IN PLACE, so a re-review DESTROYS the previous verdict. That throws away
    the single most valuable label a review corpus can produce: a REQUEST CHANGES that a
    rebuttal flipped to APPROVE **at the same head sha with no code change** — i.e. a
    blocking finding demonstrably false. Measured 2026-08-20: 343 reviewed PRs in 30 days,
    only 20 carrying a blocking finding, and every false one already overwritten by the
    APPROVE that disproved it. Severity-rubric tuning cannot be measured without those
    pairs, so they must be kept AS THEY HAPPEN — they cannot be reconstructed later.

    ``forge_reviews`` already had exactly this shape (``attempt_number``, ``raw_payload``)
    and ZERO rows: its only writers were two INSERTs inside ``POST /api/forge/webhook``, an
    external receiver that has never fired. This wires the REAL review path to it.

    The table has no ``repo`` column, so repo (plus head sha, path, verdict, coverage state
    and severity counts) goes in ``raw_payload``; the full text goes in ``summary``.

    ⚠️ ``forge_reviews.created_at`` is ``timestamp WITHOUT time zone``, deviating from the
    platform TIMESTAMPTZ convention — compute ages for it IN SQL, never by subtracting an
    aware ``now_utc()`` (that raises a naive/aware TypeError).

    NEVER raises and never blocks: a review that COMPLETED must not be lost because a
    bookkeeping INSERT failed. Returns the attempt number, or None."""
    try:
        verdict = parse_verdict(summary)
        payload = {
            "repo": repo or _DEFAULT_REPO,
            "head_sha": head_sha,
            "review_path": review_path,
            "verdict": verdict,
            "coverage_only": bool(coverage_only_demotion(summary or "")),
            "dropped_files": coverage_dropped_paths(summary or ""),
            "severities": _attempt_severity_counts(summary or ""),
        }
        with get_db_cursor(commit=True) as (conn, cur):
            # attempt_number derived inside the INSERT so two concurrent reviews of the same
            # PR cannot both read the same MAX and collide on it.
            cur.execute(
                """
                INSERT INTO forge_reviews
                       (pr_number, review_source, review_status, summary, raw_payload, attempt_number)
                SELECT %s, 'forge', %s, %s, %s::jsonb, COALESCE(MAX(attempt_number), 0) + 1
                  FROM forge_reviews
                 WHERE pr_number = %s
                   AND COALESCE(raw_payload->>'repo', %s) = %s
                RETURNING attempt_number
                """,
                (
                    pr_number,
                    verdict,
                    summary,
                    json.dumps(payload),
                    pr_number,
                    _DEFAULT_REPO,
                    repo or _DEFAULT_REPO,
                ),
            )
            row = cur.fetchone()
        return (dict(row) if row else {}).get("attempt_number")
    except Exception as exc:  # noqa: BLE001 — telemetry must never break a completed review
        logger.warning("[F.O.R.G.E.] review-attempt record error (PR #%s): %s", pr_number, exc)
        return None


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


# --- #5297: review-path health — the fallback-rate metric WITH its consumer -----------
#
# #5287 proved the freeform fallback is where the false verdicts come from, and that a
# signal nobody consumes is worthless: quality=blocking_issue_without_evidence sat on
# review rows for weeks, consumed by nothing, while the pipeline degraded. This metric
# therefore ships ONLY together with its consumer (check_review_path_health → send_system).

_REVIEW_PATH_JSON_MARKER = "structured=json"
_REVIEW_PATH_GATED_MARKER = "structured=freeform-gated"


def _classify_review_path(ai_summary: str | None) -> str:
    """'structured_json' | 'freeform_gated' | 'legacy' from the [review-meta] marker.
    Anything without a structured marker — including pre-QW-1 reviews with no meta line
    at all — counts as legacy freeform: the degraded path."""
    text = ai_summary or ""
    if _REVIEW_PATH_JSON_MARKER in text:
        return "structured_json"
    if _REVIEW_PATH_GATED_MARKER in text:
        return "freeform_gated"
    return "legacy"


def review_path_stats(days: int = 7) -> dict:
    """Path split of recent completed reviews + the fallback rate (#5297).

    MEASUREMENT CAVEAT (deliberate): pr_reviews stores the LATEST review per PR — a
    re-review overwrites ai_summary — so this is a current-verdict INVENTORY, not
    per-run telemetry. Good enough for the health question ("is the pipeline mostly
    degraded right now?"); per-run history would need its own log table.
    """
    counts = {"structured_json": 0, "freeform_gated": 0, "legacy": 0}
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT ai_summary FROM pr_reviews
               WHERE review_status = 'reviewed' AND ai_summary IS NOT NULL
                 AND updated_at >= NOW() - (%s * INTERVAL '1 day')""",
            (int(days),),
        )
        rows = cur.fetchall() or []
    for r in rows:
        summary = r["ai_summary"] if isinstance(r, dict) else r[0]
        counts[_classify_review_path(summary)] += 1
    total = sum(counts.values())
    rate = None if total == 0 else round((total - counts["structured_json"]) / total, 3)
    return {"window_days": days, "total": total, "fallback_rate": rate, **counts}


def _fallback_rate_warn_threshold() -> float:
    """platform_settings 'forge:fallback_rate_warn' — tunable live, defaults 0.5."""
    try:
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'forge:fallback_rate_warn'")
            row = cur.fetchone()
            if row:
                return float(row["value"] if isinstance(row, dict) else row[0])
    except Exception as exc:  # noqa: BLE001 — a settings hiccup must not break the check
        logger.debug("fallback_rate_warn threshold read failed (using default): %s", exc)
    return 0.5


def _send_system_alert(title: str, message: str) -> None:
    """Isolated so tests can capture the alert without a Telegram round-trip."""
    from services.telegram_service import send_system

    send_system(title, message)


def check_review_path_health(days: int = 7, min_total: int = 5) -> dict:
    """#5297 consumer: WARN when the trailing fallback rate crosses the threshold.

    A mostly-degraded review pipeline means every verdict in the system is worth less
    than it appears (#5287: the same diff drew a false blocking CRITICAL on the
    freeform path and a clean APPROVE on the structured path). Guards:
      * min_total — a handful of reviews all-freeform is noise, not a trend;
      * FIXED alert title — send_system dedups on (title, source) with a cooldown,
        so a persistent condition reports once per window instead of flooding.
    """
    stats = review_path_stats(days)
    stats["alerted"] = False
    rate = stats.get("fallback_rate")
    total = stats.get("total", 0)
    if rate is None or total < min_total:
        return stats
    threshold = _fallback_rate_warn_threshold()
    stats["threshold"] = threshold
    if rate > threshold:
        _send_system_alert(
            "F.O.R.G.E. reviews degrading to freeform fallback",
            (
                f"{rate:.0%} of the last {total} stored reviews ({days}d window) came from the "
                f"degraded freeform path (warn threshold {threshold:.0%}) — verdicts are worth "
                "less than they appear. Check 7B node health / dispatch timeouts "
                "(#5287/#5297; the 2026-07-27 storm was the ComfyUI livelock pinning models to CPU). "
                "Note: latest-review-per-PR inventory, not per-run telemetry."
            ),
        )
        stats["alerted"] = True
    return stats
