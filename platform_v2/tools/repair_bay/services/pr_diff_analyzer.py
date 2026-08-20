"""PR Diff Analyzer — Phase 2 of the PR Review Pipeline.

Fetches GitHub diffs for pending PR reviews and dispatches them to F.O.R.G.E.
via the Bridge dispatcher for AI code review. Results stored in pr_reviews.ai_summary.
"""

from __future__ import annotations

import logging
import os
import re

import requests

from services.review_coverage import annotate, chunk_plan, coverage, prioritize, summarize
from tools.repair_bay.services.pr_review_service import (
    get_pending_reviews,
    get_review,
    mark_review_done,
    mark_review_pending,
    mark_review_started,
    _classify_review_path,
    parse_verdict,
    poll_open_prs,
)

logger = logging.getLogger(__name__)

_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
# Read-only token for cross-repo diff fetches (watch-product repos). Prefer the
# least-privilege FORGE_REVIEW_TOKEN; fall back to the write token for archie-platform.
_REVIEW_TOKEN = os.getenv("FORGE_REVIEW_TOKEN", "")
# Raised from 6000: a 7B/12B has headroom, and a bigger window means fewer truncations
# (truncation mid-file was a direct cause of false 'no tests'/'unclosed loop' flags).
# _DIFF_MAX_CHARS is the conservative cap used when the review window is at Ollama's ~2048
# default (forge:review_num_ctx unset/0). QW-5 follow-on: when that flag raises the window,
# _diff_max_chars() widens the cap toward _DIFF_MAX_WIDE so fewer PRs truncate.
_DIFF_MAX_CHARS = 12000
_DIFF_MAX_WIDE = 20000
# ST-3: the qwen2.5:7b (every Tier-1/2 structured review + the freeform fallback) must finish a
# review inside the 240s per-node dispatch window. A big diff (the full _DIFF_MAX_WIDE window) makes
# the 7B time out -> the weaker freeform fallback (the #1901 failure). Cap the 7B's diff here so
# reviews COMPLETE; the patient (CPU-bound) Tier-3 gemma3:12b keeps the full window. See
# _diff_cap_for_model().
_DIFF_MAX_7B = 9000

# Phase-1 anti-hallucination rubric (project #381). Seeded from the 2026-06-22 review where
# F.O.R.G.E. (qwen2.5:7b) hallucinated flags on ~8/10 verified-correct PRs. Each rule maps to
# a confirmed false positive. Prepended to every review prompt so the 7B stops repeating them.
_FALSE_POSITIVE_RUBRIC = (
    "GROUND RULES — these are COMMON FALSE POSITIVES; do NOT flag them as issues:\n"
    "1. Parameterized SQL (psycopg2 %s placeholders / query params) is NOT SQL injection. Only "
    "string-concatenated or f-string SQL built from user input is.\n"
    "2. A file that COMPILES and PASSES TESTS has no syntax error, missing semicolon, or unclosed "
    "loop/bracket. Python statements need no semicolons.\n"
    "3. A test file added IN THIS SAME DIFF means tests WERE added — never claim 'no tests'. You "
    "CANNOT run anything, so never claim a test is 'not executed', 'not run', 'never called' or "
    "'not wired up': a pytest-named file/class/function is collected automatically and you have no "
    "way to observe otherwise. Only say a test does not run if the diff SHOWS an explicit skip "
    "(@pytest.mark.skip / xfail / a return before the asserts).\n"
    "4. Importing one shared function from multiple call sites is REUSE (DRY), not duplication.\n"
    "5. A platform_settings/env read with a code default fallback is intentional, not a missing value.\n"
    "6. A bare hash/string built for an md5/dedup key is NOT SQL and has no injection surface.\n"
    "7. Do NOT call an import or variable 'unused' or 'removed' unless you can SEE it is never "
    "referenced anywhere in the changes shown. If the diff is truncated, NEVER raise "
    "unused/missing/removed-symbol issues — you cannot see all usages.\n"
    "8. POLARITY: a '-' line is code this PR DELETES — it will NOT exist after the merge. A '+' line "
    "is the PROPOSED state. Judge ONLY the '+' lines. If the thing you object to is on a '-' line, "
    "this PR has already removed it — that is the FIX, not the defect. The one exception is objecting "
    "to the removal ITSELF ('this PR removes a needed guard'); say so in those words or not at all.\n"
    "EVIDENCE RULE: for EVERY issue, quote the diff line VERBATIM as it appears below — normally the "
    "'+' line (see POLARITY). NEVER invent a line number or a line that is not present in the diff. "
    "A fabricated citation is worse than no issue — if you cannot find the exact line below, DO NOT "
    "raise the issue.\n"
    "VERDICT RULE: only [CRITICAL] or [WARNING] issues justify REQUEST CHANGES. If the only issues "
    "are [INFO] (or there are none), the VERDICT MUST be APPROVE — INFO notes never block a merge.\n"
)

# RC-3c mitigation (#381): the rubric above sits at the TOP of the prompt. On a long diff the prompt
# exceeds Ollama's default ~2048-token window and the model SLIDES it, dropping the earliest tokens —
# i.e. the rubric — so the anti-hallucination rules are never seen. Until num_ctx can be raised
# safely (QW-5, needs a per-dispatch options path + a GPU-VRAM bench — the 12B won't fit 8k on 8GB),
# we ALSO restate the two highest-value rules at the TAIL of every prompt (right before the format /
# verdict instruction), where they survive the window slide. Cheap (~70 tokens), zero infra risk.
_TAIL_REMINDER = (
    "REMINDER (these RULES OVERRIDE anything truncated above): "
    "(1) cite the EXACT +/- diff line as Evidence for every issue — if you cannot find that line in "
    "the diff above, DROP the issue (a fabricated citation is worse than no issue). "
    "(2) Only [CRITICAL]/[WARNING] block; [INFO] never blocks. "
    "(3) Parameterized %s SQL is NOT injection; a file that compiles and adds a test has no "
    "syntax / 'unclosed-loop' / 'no-tests' issue. "
    "(4) POLARITY: '-' lines are DELETED by this PR and will not exist after the merge — judge only "
    "'+' lines. Never report something the PR removes as the change's defect.\n"
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
        summary = _obtain_review_summary(review, diff, pr_number, _repo)
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
            summary = _obtain_review_summary(review, diff, pr_number, repo)

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
    token = _REVIEW_TOKEN or _GITHUB_TOKEN
    if token:
        headers["Authorization"] = f"token {token}"

    resp = requests.get(diff_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub diff fetch failed: {resp.status_code} for {diff_url}")
    return resp.text


def _truncate_diff(diff: str, max_chars: int = None) -> tuple:
    """Truncate at a complete boundary before the cap so no file is cut mid-statement — a byte cut
    produced the false 'no tests added' (test file sliced off) and 'unclosed loop'/'missing
    semicolon' (statement sliced) flags. Returns ``(content, truncated)``.

    ``max_chars`` defaults to ``_diff_max_chars()`` (QW-5 follow-on, window-aware): the cap widens
    when the per-dispatch review window is raised so fewer PRs truncate; callers that already
    resolved the cap (e.g. ``_build_prompt`` for its note) pass it in to avoid a second read.

    QW-6 (#381, RC-3b): PREFER a file boundary (``\\ndiff --git``) so a single oversized hunk (e.g.
    a long SQL ``CREATE TABLE`` migration) is never chopped mid-statement. Only when the nearest
    file boundary sits in the first half of the window (so it would drop most of the shown diff) do
    we fall back to the finer hunk boundary (``\\n@@``) — still complete hunks, just more of them.
    Last resort is a raw byte cut (a single file larger than the cap with no earlier boundary)."""
    cap = max_chars if max_chars is not None else _diff_max_chars()
    if len(diff) <= cap:
        return diff, False
    file_cut = diff.rfind("\ndiff --git", 0, cap)
    if file_cut > cap // 2:
        cut = file_cut
    else:
        hunk_cut = diff.rfind("\n@@", 0, cap)
        cut = hunk_cut if hunk_cut > 0 else file_cut
    return (diff[:cut] if cut > 0 else diff[:cap]), True


def _build_prompt(review: dict, diff: str) -> str:
    """Assemble the F.O.R.G.E. code review prompt with an anti-hallucination grounding rubric
    + a hunk-boundary-safe diff window (Phase-1 agent-optimization, project #381)."""
    cap = _diff_cap_for_model(strong=False)  # ST-3: the freeform fallback always runs the 7B
    diff_content, truncated = _truncate_diff(diff, cap)
    truncation_note = (
        f"\n[Note: diff truncated to ~{cap} chars at a hunk boundary — the shown "
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
{_TAIL_REMINDER}
Provide your review in this exact format:

SUMMARY
One paragraph describing what this PR does and its overall quality.

ISSUES
- [CRITICAL] <issue> — <why it matters> — Evidence: <exact + or - diff line>
- [WARNING] <issue> — <why it matters> — Evidence: <exact + or - diff line>
- [INFO] <issue> — <why it matters> — Evidence: <exact + or - diff line>
(List ONLY real issues you can tie to a specific diff line shown above. Apply the GROUND RULES
first — most rejected reviews fail there. If none, write: No issues found.)

Finally, output EXACTLY ONE verdict line with a SINGLE choice — do NOT list more than one option:
VERDICT: APPROVE
(use "VERDICT: REQUEST CHANGES" only for a real [CRITICAL]/[WARNING], or "VERDICT: NEEDS REVIEW" if genuinely unsure)"""


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


# --- QW-2 (#381): deterministic non-blocking severity normalizer ------------------------------
# The 7B systematically self-labels true-but-trivial nits (missing tests, type hints, docstrings,
# code duplication, naming, style, sys.path, broad-except, magic numbers) as [WARNING]/[CRITICAL],
# and BOTH the freeform gate and the structured _recompute_verdict treat ANY WARNING/CRITICAL as a
# hard block — so a correct-but-trivial nit blocks the merge. These categories never justify a
# block; demote them to [INFO] regardless of the model's label. CRITICAL allow-list BY OMISSION:
# only a title/why MATCHING a known nit category is demoted; real bug classes (injection, data loss,
# crash, auth, race, leak, overflow) never match and keep their severity.
# Diagnosis: .claude/plans/2026-06-22-forge-review-quality-diagnosis.md (RC-2 / QW-2).
_NONBLOCKING_CATEGORY_RE = re.compile(
    "|".join(
        (
            r"(missing|no|lack\w*|add\w*|insufficient|needs?|without|more)\s+(unit\s+|integration\s+)?tests?",
            r"test\s+coverage",
            r"untested",
            r"type[\s-]?hints?",
            r"type\s+annotations?",
            r"docstrings?",
            r"doc\s*comments?",
            r"code\s+duplicat\w*",
            r"duplicat\w*\s+(code|logic|block|function|method|implementation)",
            r"naming\s+conventions?",
            r"variable\s+nam\w*",
            r"poor\s+nam\w*",
            r"stylistic",
            r"style\s+(issue|nit|convention|guide|preference)",
            r"inconsistent\s+formatting",
            r"formatting\s+(issue|nit|convention)",
            r"pep[\s-]?8",
            r"\blinting?\b",
            r"sys\.path",
            # NOTE: 'bare/broad except' is deliberately NOT here — in this codebase a bare except
            # has a documented history of leaking DB connections (KB #270617 / fleet.md), so it can
            # be a REAL bug. Let it stay a WARNING and reach a human rather than silently demote it.
            r"magic\s+numbers?",
            r"\bnit[\s-]?pick\w*",
            r"minor\s+(nit|style|issue|concern)",
        )
    ),
    re.IGNORECASE,
)

_BLOCKING_SEVERITIES = ("CRITICAL", "WARNING")


# A finding that asserts NO DEFECT is praise wearing a severity label. Measured live on
# PR #2403: "[CRITICAL] Content Verification Check Added — Ensures that the deployed code
# matches what is running in the sandbox, preventing potential discrepancies." That text
# describes the change working AS INTENDED, yet the CRITICAL tag alone flipped the verdict to
# REQUEST CHANGES. It slips every other gate by construction: the citation is a real ADDED
# line, so grounding (#5009) and polarity (#5075) both correctly pass it, and it makes no
# runtime claim (#5098). Nothing is wrong with the finding except that its severity does not
# match its content — which only the severity layer can judge.
_APPROVAL_RE = re.compile(
    r"\b(ensur\w+|prevent\w+|improv\w+|enhanc\w+|safeguard\w*|correctly|properly|"
    r"align\w*\s+with|(good|best)\s+practice|is\s+a\s+\w*\s*(safety|sanity)\s+check|"
    r"add(s|ed|ing)?\s+(a|an)?\s*\w*\s*(check|validation|guard|safeguard|verification))\b",
    re.I,
)
# Any PREDICATIVE fault claim wins over approval wording — "prevents X but is still
# vulnerable" must keep blocking. Deliberately about asserting a fault IN the code, not the
# mere presence of a scary noun (a "prevents potential discrepancies" clause names the thing
# avoided, not a defect present).
_DEFECT_ASSERTION_RE = re.compile(
    r"\b(is|are|was|were)\s+(missing|incorrect|wrong|unsafe|invalid|broken|vulnerable)\b"
    r"|\blacks?\b|\bfail(s|ing|ed)?\s+to\b|\bdoes\s*n[o']t\s+handle\b|\bdo\s+not\s+handle\b"
    r"|\bshould\s+(be|use|have|not)\b|\bvulnerab\w+|\bunhandled\b|\bno\s+error\s+handling\b"
    r"|\bwill\s+(crash|fail|break)\b|\bcan\s+(crash|fail|break)\b|\bbreaks\b|\btypos?\b"
    r"|\brace\s+condition\b|\bmemory\s+leak\b|\bnot\s+thread[\s-]?safe\b",
    re.I,
)


# A DESIGN OBSERVATION is the third shape of non-finding, and neither gate above catches it.
# _asserts_no_defect needs APPROVAL wording ("ensures", "prevents"); _NONBLOCKING_CATEGORY_RE needs a
# known nit CATEGORY. A neutral remark about shape — "introduces new functions which add complexity",
# "the threshold value may be too long or too short" — asserts no fault at all, so it matches neither
# and blocks the merge on its own.
#
# Measured 2026-08-18 on three consecutive PRs (#2686/#2687/#2688): every one returned REQUEST CHANGES
# on WARNING-level remarks of exactly this shape, and #2687 (an auth + rate-limit fix closing a LIVE
# anonymous path into hub LLM work) was blocked twice by it. "This change adds code" cannot be a
# defect in a PR whose entire purpose is to add a security gate.
#
# Two families, both requiring NO fault assertion anywhere (same asymmetry as _asserts_no_defect):
#   1. complexity//size remarks — adding functions or complexity is not a defect
#   2. unfalsifiable hedges — "may be too long OR too short" names both directions, so it makes no
#      checkable claim; a real defect is asserted, not hypothesised in both directions at once.
_DESIGN_OBSERVATION_RE = re.compile(
    r"add(s|ed|ing)?\s+(to\s+the\s+)?complexity|increas\w+\s+\w*\s*complexity"
    r"|complexity\s+(to|in|of)\s+the\s+(codebase|code|module)"
    r"|introduc\w+\s+(a|an|the)?\s*(new\s+)?(functions?|methods?|class(es)?|helpers?)"
    r"|additional\s+functionality"
    r"|hard[\s-]?cod\w+"
    r"|may\s+be\s+too\s+\w+\s+or\s+too\s+\w+",
    re.I,
)

# CARVE-OUT — a hardcoded SECRET or ADDRESS is a real bug in this codebase, not a nit. `.env` rules
# and the mesh mandate both exist because of exactly these. If any of these nouns appear, the finding
# keeps its severity no matter how it is phrased.
_HARDCODE_IS_REAL_RE = re.compile(
    r"\b(secret|credential|password|passphrase|token|api[\s-]?key|private\s+key"
    r"|ip\s+address|hostname|endpoint\s+url|connection\s+string|dsn)\b",
    re.I,
)


# CARVE-OUT #2 (#5841) — a CONTRASTIVE conjunction means the operative claim is what FOLLOWS it,
# not the shape remark before it. "Introduces a new function `_logout(client)` ... HOWEVER, this
# function is not used in any of the tests. It should either be used or removed" is a real dead-code
# finding wearing a design-observation opening. Without this guard the article fix below would have
# DEMOTED it — measured on the live corpus (pr_reviews #1692), which is exactly the suppression risk
# that kept #5841 out of the #5839 PR.
#
# Deliberately broad: ANY contrastive anywhere in the blob vetoes the demotion. Erring toward NOT
# demoting is the safe direction for a demote-only gate — a false block costs one human glance, a
# false demotion hides a defect. Measured cost on 1,741 real issue lines: 4 findings stop being
# demoted, and one of them is a genuine "[WARNING] SQL Injection Risk: ... queries use string
# formatting directly" that the gate had been silently demoting.
_CONTRASTIVE_RE = re.compile(r"\b(however|but|although|though|that\s+said|nevertheless|nonetheless|whereas)\b", re.I)


# SPECULATIVE COVERAGE (#5846) — the FOURTH non-finding shape, and the one that blocked
# PR #2718 three times running.
#
# "The regex `_PERMANENT_AUTH_RE` is deliberately narrow to avoid false positives, but it
# could still miss some cases where the server rejects a credential."
#
# By the third pass the finding had absorbed the rebuttal and stated the design rationale
# ITSELF — and still carried [WARNING], which blocks. It asserts no present defect: it
# hypothesises about INPUTS THAT DO NOT EXIST IN THE DIFF. That makes it a CLAIM problem in
# ADR-001 terms (like _is_unverifiable_test_execution_claim), not a severity-vocabulary one:
# no diff can show that a pattern handles every string that might ever arrive. A reviewer can
# always say "your allow-list might be incomplete" about any allow-list, forever.
#
# Distinct from its neighbours: _asserts_no_defect needs APPROVAL wording, _is_design_observation
# needs a SHAPE remark, _NONBLOCKING_CATEGORY_RE needs a known nit category. This matches none.
#
# THREE conditions, because this DEMOTES and a false positive hides a real defect:
#   1. speculative-coverage phrasing,
#   2. no predicative fault claim (_DEFECT_ASSERTION_RE) — "may not cover X and IS broken" blocks,
#   3. NO CONCRETE EXEMPLAR. "may not cover all edge cases, SUCH AS multiple retries" names a
#      case a human can go and check, which makes it an observation rather than speculation —
#      it keeps its severity. Measured on the live corpus: this exclusion is what keeps
#      pr_reviews' "exception handling ... such as multiple retries" finding blocking.
#
# Corpus-measured before shipping (1,743 real issue lines): this predicate demotes 6 lines
# total, of which only 2 carried a BLOCKING severity — the #2718 finding and a "consider
# adding more explicit mocks" suggestion. Neither alleges a defect. The exemplar rule is what
# keeps the third blocking candidate ("may not cover all edge cases, SUCH AS multiple
# retries") at WARNING.
_SPECULATIVE_COVERAGE_RE = re.compile(
    r"not\s+exhaustive" r"|may\s+not\s+be\s+(exhaustive|comprehensive|complete)"
    # NB: no "fail to ..." branch — `_DEFECT_ASSERTION_RE` matches `fail(s|ing|ed)? to` and
    # vetoes first, so such a branch could never take effect. That veto is the CORRECT
    # outcome ("could fail to cover" reads as a fault claim, so the finding keeps its
    # severity); the branch would just be dead pattern implying otherwise.
    r"|(may|might|could)\s+(still\s+)?(miss|not\s+(match|cover|handle|account))"
    r"|future\s+(?:\w+\s+){1,3}(may|might|could)\s+not"
    r"|(may|might|could)\s+not\s+cover\s+all",
    re.I,
)

# A cited example turns speculation into a checkable observation — keep its severity.
_CONCRETE_EXEMPLAR_RE = re.compile(r"\bsuch\s+as\b|\be\.?g\.?\b|\bfor\s+(example|instance)\b", re.I)


def _is_speculative_coverage_claim(blob: str) -> bool:
    """True when a finding's only complaint is that a pattern/list might not cover inputs that
    are not in the diff — unfalsifiable from a diff, so it may inform but must not block."""
    if not blob:
        return False
    if _DEFECT_ASSERTION_RE.search(blob):
        return False
    if _CONCRETE_EXEMPLAR_RE.search(blob):
        return False
    return bool(_SPECULATIVE_COVERAGE_RE.search(blob))


def _is_design_observation(blob: str) -> bool:
    """True when a finding only remarks on SHAPE (complexity, size, a hardcoded tunable) or hedges
    unfalsifiably, and asserts no fault anywhere.

    Demote-only and deliberately narrow. Requires ALL of:
      * a design-observation phrase,
      * no predicative fault claim (_DEFECT_ASSERTION_RE) — so "adds complexity AND is vulnerable"
        still blocks,
      * no secret/address noun (_HARDCODE_IS_REAL_RE) — a hardcoded credential is a REAL finding,
      * no contrastive conjunction (_CONTRASTIVE_RE) — after "however"/"but" the operative claim is
        what FOLLOWS, so the shape remark before it cannot speak for the whole finding (#5841).
    """
    if not blob:
        return False
    if _DEFECT_ASSERTION_RE.search(blob):
        return False
    if _HARDCODE_IS_REAL_RE.search(blob):
        return False
    if _CONTRASTIVE_RE.search(blob):
        return False
    return bool(_DESIGN_OBSERVATION_RE.search(blob))


def _asserts_no_defect(blob: str) -> bool:
    """True when a finding reads as APPROVAL and asserts no fault — i.e. it is not a finding.

    Requires BOTH: approval wording present, and no predicative fault claim anywhere. That
    asymmetry is the safety property — any real defect language keeps the original severity,
    so "the new guard prevents injection but the old path is still vulnerable" still blocks.
    Demote-only; the text is never dropped, so a human still reads it.
    """
    if not blob:
        return False
    return bool(_APPROVAL_RE.search(blob)) and not _DEFECT_ASSERTION_RE.search(blob)


def _normalize_severity(issues: list) -> list:
    """Demote non-blocking nit CATEGORIES (see _NONBLOCKING_CATEGORY_RE) to INFO regardless of the
    model's self-assigned severity — structured (dict) path. Mutates + returns the same list; stamps
    ``_demoted_from`` for the audit note. Only touches issues currently labelled CRITICAL/WARNING."""
    for i in issues:
        if not isinstance(i, dict):
            continue
        if str(i.get("severity", "")).upper() not in _BLOCKING_SEVERITIES:
            continue
        blob = f"{i.get('title', '')} {i.get('why', '')}"
        if (
            _NONBLOCKING_CATEGORY_RE.search(blob)
            or _asserts_no_defect(blob)
            or _is_design_observation(blob)
            or _is_speculative_coverage_claim(blob)
        ):
            i["_demoted_from"] = str(i.get("severity", "")).upper()
            i["severity"] = "INFO"
    return issues


def _demote_nonblocking_lines(review_text: str) -> str:
    """Freeform-text counterpart of _normalize_severity: rewrite the [CRITICAL]/[WARNING] tag of any
    issue LINE whose content matches a non-blocking category to [INFO] BEFORE the block check. Issue
    lines follow ``- [SEV] <title> — <why> — Evidence: <line>`` (rubric-mandated). Conservative —
    only rewrites the severity tag; never drops the line."""
    if not review_text:
        return review_text
    out = []
    for line in review_text.splitlines():
        m = re.match(r"(\s*[-*]?\s*)\[\s*(?:CRITICAL|WARNING)\s*\](.*)", line, re.IGNORECASE)
        if m and (
            _NONBLOCKING_CATEGORY_RE.search(m.group(2))
            or _asserts_no_defect(m.group(2))
            or _is_design_observation(m.group(2))
            or _is_speculative_coverage_claim(m.group(2))
        ):
            line = f"{m.group(1)}[INFO]{m.group(2)}"
        out.append(line)
    return "\n".join(out)


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
    # QW-2: first demote true-but-trivial nit lines (tests/type-hints/docstrings/duplication/style/
    # sys.path/broad-except/...) to [INFO] so they don't count as blocking on the freeform path.
    review_text = _demote_nonblocking_lines(review_text)
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


# --- Phase-1 PR-B: structured JSON review + confidence gate + tier model escalation (#381) ---

_TIER3_REVIEW_MODEL = "gemma3:12b"  # stronger model for big/breaking/security/migration PRs

_REVIEW_JSON_SCHEMA = (
    '{"summary": "<one paragraph>", "confidence": <float 0.0-1.0, your certainty>, '
    '"issues": [{"severity": "CRITICAL|WARNING|INFO", "title": "<short>", "why": "<impact>", '
    '"evidence": "<the exact + or - diff line, copied verbatim>"}], '
    '"verdict": "APPROVE|REQUEST CHANGES|NEEDS REVIEW"}'
)


def _get_setting(key: str, default):
    """Read a platform_settings value, fail-safe to default (handles dict or tuple rows)."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return default
        val = row.get("value") if isinstance(row, dict) else row[0]
        return default if val is None else val
    except Exception:
        return default


def _structured_review_enabled() -> bool:
    return str(_get_setting("forge:structured_review_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _review_confidence_min() -> float:
    try:
        return float(_get_setting("forge:review_confidence_min", 0.7))
    except (TypeError, ValueError):
        return 0.7


def _build_json_prompt(review: dict, diff: str, strong: bool = False) -> str:
    """JSON-output variant of the grounded review prompt (PR-B). Same rubric + hunk-safe diff.
    ST-3: ``strong`` (the Tier-3 gemma3:12b path) keeps the full window-aware diff cap; the 7B
    (strong=False) gets the tighter _DIFF_MAX_7B cap so the review finishes inside the 240s window."""
    diff_content, truncated = _truncate_diff(diff, _diff_cap_for_model(strong))
    note = "\n[diff truncated at a hunk boundary — judge only the complete hunks shown]\n" if truncated else ""
    return (
        "You are F.O.R.G.E., A.R.C.H.I.E.'s code-review engine.\n\n"
        + _FALSE_POSITIVE_RUBRIC
        + f"\nPR #{review['pr_number']} — {review.get('title', '')}\n"
        + f"--- DIFF ---\n{diff_content}\n--- END DIFF ---\n{note}\n"
        + _TAIL_REMINDER
        + "Return ONLY a JSON object (no prose before or after) matching exactly:\n"
        + _REVIEW_JSON_SCHEMA
        + "\nRules: include an issue ONLY if you can copy its exact diff line into 'evidence'. "
        "Set 'confidence' lower when the diff is truncated or you are unsure. "
        "Use [INFO] for style/nits — they never block."
    )


def _balanced_json_candidates(text: str) -> list:
    """ST-1: string/escape-aware scan for balanced ``{...}`` objects in arbitrary text. Robust to
    markdown ```json fences, prose before/after, and braces inside string literals (a naive
    ``\\{.*\\}`` regex grabs the first ``{`` through the LAST ``}`` and chokes on either). Returns
    the candidate substrings sorted largest-span first, so the full review object outranks a
    nested one. Operates on the small model RESPONSE, not the diff."""
    cands = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        j = i
        while j < n:
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    cands.append(text[i : j + 1])
                    break
            j += 1
        i += 1
    cands.sort(key=len, reverse=True)
    return cands


def _parse_review_json(text: str):
    """Extract + parse the review JSON. ST-1: robust to markdown fences / surrounding prose —
    scans for balanced ``{...}`` objects (string-aware) and returns the largest that is a dict
    containing ``issues``. Returns None (caller re-prompts once, then falls back to the gated
    freeform path). The ``issues`` requirement is intentional — it also keeps the self-refute
    audit parse (which reads ``{"confirmed": [...]}``) returning None, unchanged."""
    if not text:
        return None
    import json

    for cand in _balanced_json_candidates(text):
        try:
            d = json.loads(cand)
        except Exception:
            continue
        if isinstance(d, dict) and "issues" in d:
            if not isinstance(d.get("issues"), list):
                d["issues"] = []
            return d
    return None


def _parse_confirmed_indices(text):
    """ST-2: parse the self-refute audit reply ``{"confirmed": [<1-based indices>]}`` into a set of
    ints, or None when no parseable ``confirmed`` array is present. Uses the ST-1 balanced-object
    scanner so a fenced/prose-wrapped reply still parses. The audit JSON has NO ``issues`` key, so it
    is deliberately NOT routed through _parse_review_json (which requires one — that mismatch made the
    audit silently fail-open). An empty list -> empty set (a valid 'retract all'); None -> the caller
    treats the audit as unavailable and fails closed."""
    if not text:
        return None
    import json

    for cand in _balanced_json_candidates(text):
        try:
            d = json.loads(cand)
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("confirmed"), list):
            out = set()
            for x in d["confirmed"]:
                try:
                    out.add(int(x))
                except (TypeError, ValueError):
                    continue
            return out
    return None


def _recompute_verdict(issues: list, confidence, threshold: float) -> str:
    """Deterministic verdict from surviving issues + confidence (subsumes the severity gate):
    any CRITICAL/WARNING -> REQUEST CHANGES; else low confidence -> NEEDS REVIEW; else APPROVE."""
    blocking = any(str((i or {}).get("severity", "")).upper() in ("CRITICAL", "WARNING") for i in issues)
    if blocking:
        return "REQUEST CHANGES"
    if confidence is not None:
        try:
            if float(confidence) < threshold:
                return "NEEDS REVIEW"
        except (TypeError, ValueError):
            pass
    return "APPROVE"


def _render_review_text(
    parsed: dict, model: str = "", note: str = "", n_ungrounded: int = 0, unsupported_claims: list = None
) -> str:
    """Render parsed JSON back into the canonical SUMMARY/ISSUES/VERDICT text so every downstream
    consumer (parse_verdict, merge gate, notify, UI) is unchanged."""
    issues = parsed.get("issues") or []
    lines = [f"SUMMARY\n{(parsed.get('summary') or '').strip()}\n", "ISSUES"]
    if issues:
        for i in issues:
            sev = str((i or {}).get("severity", "INFO")).upper()
            title = ((i or {}).get("title") or "").strip()
            why = ((i or {}).get("why") or "").strip()
            ev = ((i or {}).get("evidence") or "").strip()
            lines.append(f"- [{sev}] {title} — {why} — Evidence: {ev}")
    else:
        lines.append("No issues found.")
    conf = parsed.get("confidence")
    meta = f"\n[review-meta] structured=json model={model or 'default'} confidence={conf}"
    if note:
        meta += f" {note}"
    # #5018 provenance + #5647 false-CLEAR flags. NEITHER changes the verdict.
    meta += _quality_suffix("json", n_ungrounded, issues, unsupported_claims)
    return "\n".join(lines) + f"\n\nVERDICT: {parsed.get('verdict', 'NEEDS REVIEW')}" + meta


# --- Phase-1 PR-C: deterministic evidence-verification + self-refute + false-positive learning (#381) ---


def _normalize_match(s: str) -> str:
    import re as _re

    return _re.sub(r"\s+", " ", (s or "").lower()).strip()


def _side_text(diff: str, sign: str) -> str:
    """Normalized text of every diff line on ONE side ('+' added / '-' removed)."""
    skip = "+++" if sign == "+" else "---"
    return _normalize_match(" ".join(ln[1:] for ln in (diff or "").splitlines() if ln[:1] == sign and ln[:3] != skip))


def _token_present(tok: str, haystack_n: str) -> bool:
    """Is ``tok`` in the haystack as its own identifier, not buried inside a longer word?

    #5839: the old test was a bare ``tok in haystack_n``, so the INVENTED token ``pass``
    matched inside the real word ``passed`` and a fabricated evidence line scored as
    grounded. Measured on PR #2715: no standalone ``pass`` existed on the added side at all
    (``\bpass\b`` -> False; the only matches were ``passed``, ``passed``), yet token overlap
    came out 12/12 = 1.00 and the finding blocked the PR.

    The boundary deliberately treats ``_`` as a SEPARATOR rather than a word character
    (which is why this is not ``\b``): ``coverage`` must still match ``review_coverage`` —
    a model citing a bare identifier that the code prefixes is a REAL citation, and
    rejecting it would drop true findings, which is the far worse direction. Only a
    same-alphabet extension (``pass`` -> ``passed``, ``cap`` -> ``capability``) is refused.
    """
    import re as _re

    return bool(_re.search(r"(?<![a-z0-9])" + _re.escape(tok) + r"(?![a-z0-9])", haystack_n))


def _cites(core: str, haystack_n: str) -> bool:
    """Does this evidence string tie to the given side of the diff? Substring match, or an
    85% token overlap so a lightly-paraphrased real line still counts."""
    import re as _re

    if not core or not haystack_n:
        return False
    # #5839: the whole-core substring fast-path needs the SAME boundary rule as the token
    # test below. A bare `core in haystack_n` matched the invented core `pass` inside the
    # real word `passed` and returned True before the token logic ever ran — which is why
    # fixing only the token loop left the bug alive.
    if _token_present(core, haystack_n):
        return True
    toks = _re.findall(r"[a-z_][a-z0-9_]{2,}", core)
    return bool(toks) and sum(1 for t in toks if _token_present(t, haystack_n)) / len(toks) >= 0.85


def _evidence_polarity(evidence: str, diff: str) -> str:
    """Which SIDE of the diff does the cited evidence come from: 'added' | 'removed_only' | 'absent'.

    Polarity is the whole point (#5075). A defect can only exist in code that SURVIVES the merge,
    so a finding may only be raised against an ADDED line. Judging '+' and '-' as one undifferentiated
    "changed" blob let the reviewer quote the line the PR DELETED and report it as the proposed
    state — the exact inverse of the change. Observed on gov-watch PR #45: the diff removed
    ``event=True`` from contract_date, and the review flagged "contract_date is being marked as
    retrospective", citing the removed line, and returned REQUEST CHANGES. A second run on the same
    diff (no dispatch timeout) APPROVED it. Most likely when the dispatch degrades and the model
    sees a partial diff and loses +/- polarity.

    'added' is checked FIRST so an ordinary MODIFIED line (present on both sides) stays grounded.
    Returns 'added' when there is nothing to verify — this gate only ever removes confident noise.
    """
    import re as _re

    if not evidence or not diff:
        return "added"  # nothing to verify -> don't drop

    lines = [ln for ln in str(evidence).splitlines() if ln.strip()]
    if len(lines) > 1:
        # #5839: judge EACH cited line. The old code normalised the whole block into ONE
        # string, so a fabricated line's tokens were diluted by a real line's and the
        # 85% overlap still passed. Measured on PR #2715: evidence was
        #     +def prioritize(diff: str | None, cap: int | None = None) -> str | None:
        #     +    pass
        # The first line is REAL, `+    pass` is INVENTED — no standalone `pass` exists on
        # the added side — yet the blob scored 12/12 = 1.00 and the finding blocked the PR.
        #
        # ANY evaluable line that is absent disqualifies the whole citation: a model that
        # invented part of its evidence was not reading the diff for that part, and a
        # finding is only as grounded as its weakest cited line. Lines with no identifier
        # token at all (`}`, `)`, `...`) carry no information and are SKIPPED rather than
        # counted either way — they cannot confirm or refute anything.
        verdicts = []
        for ln in lines:
            ln_core = _normalize_match(_re.sub(r"^[+\-\s]+", "", ln))
            if not _re.findall(r"[a-z_][a-z0-9_]{2,}", ln_core):
                continue  # punctuation-only, unevaluable
            if _cites(ln_core, _side_text(diff, "+")):
                verdicts.append("added")
            elif _cites(ln_core, _side_text(diff, "-")):
                verdicts.append("removed_only")
            else:
                return "absent"
        if not verdicts:
            return "added"  # nothing evaluable -> don't drop
        return "added" if "added" in verdicts else "removed_only"

    core = _normalize_match(_re.sub(r"^[+\-\s]+", "", evidence))
    if len(core) < 6:
        return "added"  # trivially short (<6 chars) -> ambiguous, don't drop
    if _cites(core, _side_text(diff, "+")):
        return "added"
    if _cites(core, _side_text(diff, "-")):
        return "removed_only"
    return "absent"


def _evidence_in_diff(evidence: str, diff: str) -> bool:
    """True if the evidence ties to a line this PR actually CHANGED, EITHER side.

    Kept as the grounding (did the model read its input?) predicate — deliberately polarity-blind.
    Use ``_evidence_polarity`` when the question is whether a DEFECT can be raised, which only an
    added line can support. Catches fabricated citations (PR-C): a line the model invented, or an
    unchanged/context line cited as if changed (the #1869 'unused import time' fabrication)."""
    return _evidence_polarity(evidence, diff) != "absent"


def _is_spurious_injection(issue: dict) -> bool:
    """Myth #1 deterministic guard: an 'SQL injection' flag whose cited evidence line contains NO
    string-building is a false positive — the single most common LLM code-review hallucination, and
    it blocks (CRITICAL). SQL injection requires building the query from a variable IN that line, so
    if the cited line has no string-building marker it cannot be injectable. This drops BOTH a
    CONSTANT query (zero injection surface) AND a PARAMETERIZED query (%s / %(name)s). A genuine
    injection — concat (``"..." + var``), f-string, ``.format()``, or %-format operator
    (``"..." % var``) — keeps a marker and is NEVER dropped."""
    import re as _re

    text = (str((issue or {}).get("title", "")) + " " + str((issue or {}).get("why", ""))).lower()
    if "injection" not in text and "sqli" not in text:
        return False
    ev = str((issue or {}).get("evidence", "") or "")
    # The ONLY ways a single cited line builds SQL from a variable. ``"..." %`` (quote then %) is the
    # %-format operator (unsafe); a bare ``%s`` INSIDE the quotes is a parameterized placeholder (safe)
    # and is intentionally NOT a marker.
    has_stringbuild = bool(_re.search(r"""f["']|\.format\(|["']\s*\+|\+\s*["']|["']\s*%\s*[\(\w]""", ev))
    return not has_stringbuild


# A claim that something "is not executed" is an assertion about RUNTIME. The reviewer cannot run
# anything, so for an auto-collected pytest construct it is unfalsifiable from the diff alone.
_NON_EXECUTION_RE = re.compile(
    r"not\s+(?:be\s+|being\s+)?(?:executed|run|running|invoked|called|collected)"
    r"|never\s+(?:executed|run|invoked|called|collected)"
    r"|(?:isn'?t|aren'?t|won'?t|doesn'?t|do(?:es)?\s+not|will\s+not)\s+(?:be\s+)?"
    r"(?:executed|run|invoked|called|collected)"
    r"|not\s+wired\s+up",
    re.I,
)
# pytest auto-collects test_*.py / class Test* / def test_*, so ADDING one of these IS wiring it up.
_PYTEST_CONSTRUCT_RE = re.compile(
    r"^\+\+\+ b/.*\btest_[^/]*\.py|^\+\s*(?:async\s+)?def\s+test_|^\+\s*class\s+Test",
    re.M,
)
# ...unless the diff SHOWS the test disabled, in which case "does not run" is a REAL finding.
_SKIP_MARKER_RE = re.compile(r"@pytest\.mark\.(?:skip|xfail)|pytest\.skip\(|unittest\.skip", re.I)


def _is_unverifiable_test_execution_claim(issue: dict, diff: str) -> bool:
    """True for a blocking claim that a TEST "is not executed" — unfalsifiable from a diff (#5098).

    Caught live on PR #2401 (the #5075 fix), where F.O.R.G.E. blocked on:
        [WARNING] "The test case for the regression is added but not executed"
        Evidence: the test file's own DOCSTRING line.
    Disproved by running the node ID; the test passed. Neither existing gate can catch this: the
    cited line genuinely IS an added line, so the evidence-grounding gate (#5009) considers it
    grounded and the polarity gate (#5075) correctly leaves it alone. The CITATION is real — the
    CLAIM is not. Only a deterministic guard or the rubric can remove it.

    Narrow ON PURPOSE — all four must hold, because the neighbouring findings are valuable:
      1. the prose actually asserts non-execution,
      2. the claim is about a TEST (so a genuine "this production helper is never called"
         dead-code finding is untouched — that one IS verifiable from the diff and worth keeping),
      3. the diff really does add a pytest-discoverable construct (adding it IS wiring it up), and
      4. the diff shows NO skip/xfail marker — if a test is VISIBLY disabled, "it does not run" is
         a legitimate finding and must survive.
    """
    text = (str((issue or {}).get("title", "")) + " " + str((issue or {}).get("why", ""))).strip()
    if not _NON_EXECUTION_RE.search(text):
        return False
    evidence = str((issue or {}).get("evidence", "") or "")
    about_a_test = bool(re.search(r"\btest", text, re.I)) or bool(
        re.search(r"def\s+test_|class\s+Test|test_\w*\.py", evidence, re.I)
    )
    if not about_a_test:
        return False
    if not _PYTEST_CONSTRUCT_RE.search(diff or ""):
        return False
    return not _SKIP_MARKER_RE.search(diff or "")


def _critiques_the_removal(issue: dict) -> bool:
    """True when a finding is ABOUT the deletion itself rather than an inverted reading of it.

    Necessary carve-out for the polarity gate (#5075). "This PR removes a guard that was needed"
    is a LEGITIMATE finding whose evidence can only ever be a removed line — dropping it wholesale
    would delete a real review capability (catching a dangerous deletion) while fixing the
    inversion. The two read almost identically in evidence and are opposite in meaning:

      inversion  -> "contract_date IS BEING MARKED retrospective"   (removed line described as
                                                                     the proposed state)
      legitimate -> "this PR REMOVES the event=True guard"          (a critique OF the deletion)

    so they are separated by whether the finding's own prose acknowledges a removal. Deliberately
    generous: anything that sounds like it is critiquing a deletion is kept, because a false
    [INFO]/[WARNING] a human can dismiss costs far less than silently losing a real one.
    """
    import re as _re

    text = (str((issue or {}).get("title", "")) + " " + str((issue or {}).get("why", ""))).lower()
    return bool(_re.search(r"\bremov|\bdelet|\bdrop(?:s|ped|ping)?\b|no longer|used to|previously", text))


# A finding that asserts THE CHANGE ITSELF removes/deletes/drops something. Deliberately
# NARROWER than _critiques_the_removal (which errs generous because it only ever KEEPS
# findings): this pattern earns a DROP, and over-eager filtering is a worse bug than the one
# being fixed. Two shapes only: a pr/patch/commit/change/diff subject before the verb
# ("this PR removes ..."), or the verb aimed at something qualified as needed/existing
# ("removes a needed guard"). Behavioral wording about the code's own runtime ("the handler
# drops the connection") matches neither and keeps its severity.
_REMOVAL_CLAIM_RE = re.compile(
    r"\b(?:pr|patch|commit|change(?:set)?|diff)\b[^.!?]{0,60}?"
    r"\b(?:remov(?:es|ed|ing|al)?|delet(?:es|ed|ing|ion)?|drop(?:s|ped|ping)?)\b"
    r"|\b(?:remov(?:es|ed|ing)?|delet(?:es|ed|ing)?|drop(?:s|ped|ping)?)\s+(?:a|an|the)\s+"
    r"(?:needed|necessary|required|important|critical|existing|original|previous)\b",
    re.I,
)


def _is_removal_claim_without_removal(issue: dict, diff: str) -> bool:
    """True for a finding asserting this PR REMOVES something when the diff deletes NOTHING (#5286).

    Measured live on PR #2503: the freeform path returned "[CRITICAL] PR removes a needed
    guard" citing ``except Exception as e:`` against a PURE-ADDITION diff — the "removed"
    guard was the very guard the PR ADDS. Every other gate correctly passes it: the citation
    is a real ADDED line, so grounding (#5009) and polarity (#5075) hold, and the
    _critiques_the_removal carve-out is never consulted (it only applies to removed_only
    evidence). The CLAIM is what is false, and it is deterministically checkable: no diff
    with zero removed lines can support any "this PR removes X" finding.

    The carve-out itself is untouched — a genuine dangerous-deletion critique (gov-watch
    PR #45) has removed lines in its diff by definition, so this guard stands down there.
    Fail-open: no diff -> nothing to verify -> never fires (mirrors _evidence_polarity).
    """
    if not diff:
        return False
    text = (str((issue or {}).get("title", "")) + " " + str((issue or {}).get("why", ""))).lower()
    if not _REMOVAL_CLAIM_RE.search(text):
        return False
    return not _side_text(diff, "-")


def _verify_evidence(issues: list, diff: str):
    """Split issues into (kept, dropped): drop issues whose evidence isn't a changed diff line
    (fabricated citation) OR that are a spurious 'SQL injection' flag on a parameterized query.

    Each dropped issue is tagged with ``_drop_reason`` because the reasons mean DIFFERENT
    things about the reviewer (#5009, #5075):
      ``evidence_not_in_diff``  the model cited something that is not in its own input — a
                                GROUNDING failure, i.e. evidence it was not reading the diff.
      ``evidence_only_removed`` the cited line is real but was DELETED by this PR, so the
                                "defect" describes code that will not exist after the merge —
                                a POLARITY inversion (#5075). The model WAS reading; it read
                                the wrong side. Never a grounding failure. A finding whose own
                                prose critiques the DELETION ("this PR removes the guard") is
                                kept — see _critiques_the_removal.
      ``spurious_injection``    a TRUSTED deterministic correction of a real-but-wrong flag;
                                the model WAS reading, it just misjudged. Says nothing bad
                                about grounding.
      ``unverifiable_runtime_claim``
                                the finding asserts a TEST "is not executed" — an assertion about
                                RUNTIME the reviewer cannot observe from a diff (#5098). Like
                                spurious_injection: the citation is real, the claim is not.
      ``removal_claim_without_removal``
                                the finding asserts this PR REMOVES something, but the diff
                                contains ZERO removed lines — the claim is provably false
                                (#5286). Like spurious_injection: deterministic, trusted, and
                                says nothing bad about grounding (the citation is real).
    Only the first may influence the verdict floor.
    """
    kept, dropped = [], []
    for it in issues or []:
        ev = (it or {}).get("evidence") or ""
        polarity = _evidence_polarity(ev, diff)
        if polarity == "absent":
            reason = "evidence_not_in_diff"
        elif polarity == "removed_only" and not _critiques_the_removal(it):
            reason = "evidence_only_removed"
        elif _is_spurious_injection(it):
            reason = "spurious_injection"
        elif _is_unverifiable_test_execution_claim(it, diff):
            reason = "unverifiable_runtime_claim"
        elif _is_removal_claim_without_removal(it, diff):
            reason = "removal_claim_without_removal"
        else:
            reason = None
        if reason:
            if isinstance(it, dict):
                it["_drop_reason"] = reason
            dropped.append(it)
        else:
            kept.append(it)
    return kept, dropped


def _count_ungrounded(dropped: list) -> int:
    """How many issues were dropped specifically because their evidence was NOT in the diff."""
    return sum(1 for d in dropped or [] if isinstance(d, dict) and d.get("_drop_reason") == "evidence_not_in_diff")


def _should_floor_ungrounded(verdict: str, n_ungrounded: int, surviving_issues: list) -> bool:
    """#5009 — pure predicate shared by the structured and freeform paths.

    True when an APPROVE rests on NOTHING the reviewer grounded in the diff: it raised issues, every
    one cited evidence absent from its own input, and none survived. Such an APPROVE is an artifact
    of the anti-hallucination filter emptying the issue list, not a judgement about the change.

    Narrow on purpose:
      * ``surviving_issues`` non-empty -> the model grounded something -> NOT floored.
      * ``n_ungrounded == 0``          -> nothing was fabricated (e.g. only a trusted
                                          spurious_injection drop) -> NOT floored.
      * verdict already REQUEST CHANGES/NEEDS REVIEW -> leave it alone; never RELAX a verdict.
    """
    return bool(verdict == "APPROVE" and n_ungrounded > 0 and not surviving_issues)


# --- GATE 5 (#5647): the FALSE CLEAR ---------------------------------------------------
#
# Gates 1-4 all interrogate FINDINGS (grounding / polarity / checkable-claim / severity). An
# APPROVE carries NO findings, so the summary PROSE of a clear is never checked against the
# diff at all. That is the hole, and it is not theoretical — three measured cases:
#
#   PR #2600  APPROVE: "introduces a shadow DOM-piercing mechanism [that] resolves the issue"
#             — it did not; a live re-test still returned 0. The reviewer believed a CODE
#             COMMENT describing an intention.
#   PR #2603  APPROVE: "The parameterized SQL usage and test addition are correct."
#             — that PR contained NO SQL and NO tests. 1 file, 0 test files, 0 `assert`.
#             Wholesale fabrication, and every existing gate passed it.
#   PR #2609  the inverse — a false CRITICAL grounded in a `@-@` REMOVED line. Run 2 on the
#             SAME diff, zero code changed, self-retracted it. The gates are
#             NON-DETERMINISTIC, not absent, which is why a single run must never be
#             treated as authoritative.
#
# THE ASYMMETRY THAT MATTERS: this gate STRIPS THE CLAIM AND KEEPS THE APPROVE. It must never
# convert a clear into a block — a fabricated compliment is a reporting defect, not evidence
# the code is broken, and flipping the verdict on it would make every clean PR unmergeable.
# Same principle as review_quality_flags(): annotate instead of adjudicate.
#
# Deliberately CONSERVATIVE in both directions:
#   * the "does the diff have X" probes are LIBERAL (any hint counts as present), so a claim
#     is only stripped when the artifact is plainly absent;
#   * a sentence OBSERVING an absence ("no tests were added", "consider adding a migration")
#     is legitimate review content and is never stripped.

_ARTIFACT_ABSENCE_HINTS = (
    "no ",
    "not ",
    "n't",
    "never",
    "missing",
    "lack",
    "absent",
    "without",
    "should add",
    "consider adding",
    "needs",
    "would benefit",
    "recommend",
)

# (label, summary asserts it, diff-actually-has-it probe)
_ARTIFACT_CLAIM_CHECKS = (
    (
        "tests",
        r"\btests?\b|\btesting\b|\btest (?:addition|coverage|case|suite)s?\b",
        r"(?mi)^\+\+\+\s+\S*test|^\+.*(?:def test_|assert\s|it\(|describe\(|pytest|unittest)",
    ),
    (
        "sql",
        r"\bsql\b|\bparameteri[sz]ed\s+quer|\bprepared statement|\bbind(?:ing)? parameter",
        r"(?mi)^\+.*(?:\bselect\b|\binsert\b|\bupdate\b|\bdelete\b|\bfrom\b\s+\w+|cur\.execute|cursor|%s|psycopg)",
    ),
    (
        "migration",
        r"\bmigrations?\b",
        r"(?mi)^\+\+\+\s+\S*migrations?/|^\+.*(?:ALTER TABLE|CREATE TABLE|ADD COLUMN)",
    ),
)


def _split_sentences(text: str) -> list:
    """Cheap sentence split — good enough for review prose, no NLP dependency."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if p.strip()]


def unsupported_artifact_claims(summary: str, diff: str) -> list:
    """Artifact classes the SUMMARY asserts as present/correct but the DIFF does not contain.

    Returns e.g. ``['sql', 'tests']``. Pure; no verdict influence.
    """
    if not (summary or "").strip() or not (diff or "").strip():
        return []
    found = []
    for sentence in _split_sentences(summary):
        low = sentence.lower()
        if any(h in low for h in _ARTIFACT_ABSENCE_HINTS):
            continue  # an observation ABOUT absence is legitimate review content
        for label, claim_re, diff_re in _ARTIFACT_CLAIM_CHECKS:
            if label in found:
                continue
            if re.search(claim_re, low) and not re.search(diff_re, diff or ""):
                found.append(label)
    return found


def strip_unsupported_claims(summary: str, diff: str):
    """(cleaned_summary, claims). Drops whole sentences that assert absent artifacts.

    If EVERY sentence would be dropped the summary is replaced with an explicit marker rather
    than left empty — an empty summary reads as "nothing to say", which is the opposite of
    what happened.
    """
    claims = unsupported_artifact_claims(summary, diff)
    if not claims:
        return (summary or ""), []
    keep = []
    for sentence in _split_sentences(summary):
        low = sentence.lower()
        if any(h in low for h in _ARTIFACT_ABSENCE_HINTS):
            keep.append(sentence)
            continue
        bad = any(
            re.search(claim_re, low) and not re.search(diff_re, diff or "")
            for _label, claim_re, diff_re in _ARTIFACT_CLAIM_CHECKS
        )
        if not bad:
            keep.append(sentence)
    cleaned = " ".join(keep).strip()
    if not cleaned:
        cleaned = "(summary withheld — every claim cited artifacts absent from the diff)"
    return cleaned, claims


def review_quality_flags(
    structured: str, n_ungrounded: int, surviving_issues: list, unsupported_claims: list = None
) -> list:
    """#5018 — provenance for a verdict. Returns flag strings; NEVER alters the verdict.

    #5009 floors an ungrounded APPROVE so it cannot auto-merge, and deliberately leaves
    REQUEST CHANGES alone ("never RELAX a verdict") — relaxing one would let real findings
    through, far worse than a false positive. The cost of that correct asymmetry: a degraded
    model can fabricate a CRITICAL, block a correct change, and read exactly like a clean
    review. On PR #2366 the 7B timed out 3x (warm_boot_ms 600094), fell back to freeform,
    and returned a CRITICAL with an EMPTY evidence field that was simply wrong.

    So: annotate instead of adjudicate. A human seeing `blocking_issue_without_evidence`
    + `freeform_fallback` knows to read the diff themselves before acting on the verdict.

      freeform_fallback              structured parse failed; the weaker path produced this
      no_grounded_evidence           issues were raised and NONE survived verification
      blocking_issue_without_evidence a surviving issue cites nothing — the #2366 signature
      unsupported_summary_claim:<x>  the summary asserted artifact <x> that is not in the diff
                                     (#5647 — the false-CLEAR signature; verdict untouched)
    """
    flags = []
    if (structured or "").strip().lower() != "json":
        flags.append("freeform_fallback")
    if n_ungrounded > 0 and not surviving_issues:
        flags.append("no_grounded_evidence")
    if any(not str((i or {}).get("evidence", "")).strip() for i in (surviving_issues or [])):
        flags.append("blocking_issue_without_evidence")
    for claim in unsupported_claims or []:
        flags.append(f"unsupported_summary_claim:{claim}")
    return flags


def _quality_suffix(structured: str, n_ungrounded: int, surviving_issues: list, unsupported_claims: list = None) -> str:
    """Render flags for the [review-meta] line. Empty string when the review is clean."""
    flags = review_quality_flags(structured, n_ungrounded, surviving_issues, unsupported_claims)
    return (" quality=" + ",".join(flags)) if flags else ""


def _freeform_rc_retry_enabled() -> bool:
    return str(_get_setting("forge:freeform_rc_retry_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _unevidenced_demotion_enabled() -> bool:
    return str(_get_setting("forge:unevidenced_blocking_demotion_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _demote_unevidenced_blocking(verdict: str, issues: list) -> bool:
    """#5287 — CONSUME the blocking_issue_without_evidence signal instead of decorating with it.

    On PR #2501 the meta line self-reported ``quality=freeform_fallback,blocking_issue_without_
    evidence`` and the REQUEST CHANGES stood anyway — the pipeline detected its own problem and
    stored it as a label nobody consumed. A blocking verdict resting SOLELY on CRITICAL/WARNING
    issues that cite NOTHING has no adjudicable content: there is no line a human (or the
    self-refute auditor) can even check. Demote it to NEEDS REVIEW — never APPROVE — so a human
    adjudicates and auto-merge stays impossible.

    Narrow on purpose:
      * verdict not REQUEST CHANGES        -> untouched (never relax an evidenced block,
                                              never touch an APPROVE).
      * ANY blocking issue cites evidence  -> the RC stands in full; a partially-evidenced
                                              review earned its block.
      * no blocking issues at all          -> nothing to demote (the verdict came from
                                              elsewhere, e.g. low confidence).
    """
    if verdict != "REQUEST CHANGES" or not issues:
        return False
    blocking = [i for i in issues if isinstance(i, dict) and str(i.get("severity", "")).upper() in _BLOCKING_SEVERITIES]
    if not blocking:
        return False
    return all(not str((i or {}).get("evidence", "")).strip() for i in blocking)


def _evidence_verification_enabled() -> bool:
    return str(_get_setting("forge:evidence_verification_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _self_refute_enabled() -> bool:
    return str(_get_setting("forge:self_refute_enabled", "true")).strip().lower() in ("1", "true", "yes", "on")


def _ungrounded_review_floor_enabled() -> bool:
    """#5009 kill switch (platform_settings, no deploy needed)."""
    return str(_get_setting("forge:ungrounded_review_floor_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _false_clear_gate_enabled() -> bool:
    """#5647 kill switch (platform_settings, no deploy needed).

    Safe to disable: the gate only edits summary PROSE and adds a provenance flag, so turning
    it off restores the previous (unchecked) narrative and changes no verdict either way.
    """
    return str(_get_setting("forge:false_clear_gate_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _review_num_ctx():
    """QW-5: per-dispatch num_ctx for F.O.R.G.E. reviews so the rubric + full diff
    fit Ollama's window instead of being slid out (dropping the rubric on long
    diffs). Returns the configured int, or None when 0/unset (default-safe OFF).
    Enable: platform_settings forge:review_num_ctx=8192. Rollback: set to 0."""
    try:
        v = int(str(_get_setting("forge:review_num_ctx", "0")).strip() or "0")
    except (TypeError, ValueError):
        return None
    return v if v >= 512 else None


def _diff_max_chars() -> int:
    """QW-5 follow-on (#381): scale the diff truncation cap to the per-dispatch review window.

    When forge:review_num_ctx raises the window (default 8192), the rubric + tail-reminder + a
    BIGGER diff + the model's own output all fit, so we widen the cap to truncate fewer PRs —
    mid-file truncation was a direct cause of false 'no tests'/'unclosed loop' flags. When the
    window is unset/0 (rollback) we keep the conservative _DIFF_MAX_CHARS so nothing regresses.

    Budget: reserve ~3500 tokens of the window for the rubric + format instructions + the model's
    own output, give the rest to the diff at ~4 chars/token, and clamp to
    [_DIFF_MAX_CHARS, _DIFF_MAX_WIDE]. 8192 -> 18768 | 0/unset -> 12000 | 1024 -> 12000 (floor) |
    32768 -> 20000 (ceiling)."""
    nc = _review_num_ctx()
    if not nc:
        return _DIFF_MAX_CHARS
    diff_budget = (nc - 3500) * 4
    return max(_DIFF_MAX_CHARS, min(diff_budget, _DIFF_MAX_WIDE))


def _diff_cap_for_model(strong: bool) -> int:
    """ST-3: right-size the diff window to the model that will run the review. The Tier-3
    gemma3:12b (``strong``) is CPU-bound but patient, so it keeps the full window-aware cap for
    maximum grounding. The qwen2.5:7b — which runs every Tier-1/2 structured review AND the
    freeform fallback — must finish inside the 240s per-node dispatch window or it times out to
    the weaker freeform path (the #1901 failure); cap its diff at _DIFF_MAX_7B so it completes."""
    full = _diff_max_chars()  # window-aware (#1900): up to _DIFF_MAX_WIDE at the raised num_ctx
    return full if strong else min(full, _DIFF_MAX_7B)


def _review_max_chunks() -> int:
    """How many serial passes a review may take (#5848). Default 1 = today's behaviour.

    Clamped to [1, 3]: 3 is the owner-chosen ceiling (~4 min, ~3x tokens). Anything
    unparseable falls back to 1, so a bad setting degrades to the SAFE single-pass path
    rather than to an unbounded one. Rollback is this value, not a deploy."""
    try:
        n = int(_get_setting("forge:review_max_chunks", 1) or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, min(n, 3))


def forge_settings_snapshot() -> dict:
    """ST-4: the EFFECTIVE value of every forge:* review knob, read through the same accessors the
    pipeline uses (so the defaults match exactly — no drift, no seeded platform_settings rows
    needed). Lets an operator see the current review config + tune any knob via platform_settings
    without a code change, and shows the derived per-model diff caps."""
    return {
        "forge:structured_review_enabled": _structured_review_enabled(),
        "forge:review_num_ctx": _review_num_ctx(),
        "forge:json_reprompt_enabled": _json_reprompt_enabled(),
        "forge:freeform_gate_enabled": _freeform_gate_enabled(),
        "forge:evidence_verification_enabled": _evidence_verification_enabled(),
        "forge:self_refute_enabled": _self_refute_enabled(),
        "forge:self_refute_failclosed_enabled": _self_refute_failclosed_enabled(),
        "forge:false_positive_writeback_enabled": _writeback_enabled(),
        "forge:review_confidence_min": _review_confidence_min(),
        "diff_cap_7b": _diff_cap_for_model(False),
        "diff_cap_strong": _diff_cap_for_model(True),
    }


def _writeback_enabled() -> bool:
    return str(_get_setting("forge:false_positive_writeback_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _self_refute_failclosed_enabled() -> bool:
    """ST-2: when the gemma3:12b auditor is UNAVAILABLE (cold/queued/exception/unparseable) we cannot
    verify a CRITICAL. Fail CLOSED — send the unverified CRITICAL to a human (NEEDS REVIEW) instead of
    fail-open keeping it as an auto-block. Default ON; rollback: forge:self_refute_failclosed_enabled=false."""
    return str(_get_setting("forge:self_refute_failclosed_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _self_refute_criticals(review: dict, diff: str, criticals: list) -> tuple:
    """PR-C Fix #5 + ST-2: second-opinion pass on surviving CRITICAL issues — re-ask the stronger
    gemma3:12b to confirm each with a verbatim changed line or RETRACT. Returns
    ``(confirmed_list, audit_ran)``.

    ``audit_ran`` is True ONLY when the auditor actually returned a parseable verdict — then
    ``confirmed_list`` is the real kept subset (possibly empty = retract all). It is False when the
    auditor was UNAVAILABLE (dispatch error, cold-load queue, no response, or an unparseable reply);
    ``confirmed_list`` is then the inputs unchanged and the caller fails CLOSED (the unverified
    CRITICAL goes to a human via NEEDS REVIEW) rather than fail-open keeping it as an auto-block."""
    if not criticals:
        return criticals, True
    from tools.department_hq.services.department_dispatcher import dispatch

    diff_content, _ = _truncate_diff(diff)  # gemma3:12b audit — full window cap is correct
    listing = "\n".join(
        f"{i + 1}. {(c or {}).get('title', '')}: {(c or {}).get('evidence', '')}" for i, c in enumerate(criticals)
    )
    prompt = (
        _FALSE_POSITIVE_RUBRIC
        + "\nYou previously flagged these as CRITICAL on PR #%s:\n%s\n\n--- DIFF ---\n%s\n--- END DIFF ---\n"
        % (review.get("pr_number"), listing, diff_content)
        + 'Audit yourself. Return ONLY JSON {"confirmed": [<1-based indices you can STILL justify '
        "with an exact changed + or - line>]}. Retract any you cannot tie to a real changed line."
    )
    try:
        res = dispatch(
            capability="code_review",
            prompt=prompt,
            module_id="repair_bay",
            json_mode=True,
            prefer_model="gemma3:12b",  # a stronger model audits the 7B's CRITICALs
            preferred_node=["starship_76583490e36955ab", "archie-starbase"],
            num_ctx=_review_num_ctx(),
        )
    except Exception:
        return criticals, False  # auditor unavailable -> caller fails closed
    if getattr(res, "queued", False):
        return criticals, False  # cold-load queue — couldn't verify in-line
    if not (getattr(res, "success", False) and getattr(res, "response", "")):
        return criticals, False
    keep = _parse_confirmed_indices(res.response)
    if keep is None:
        return criticals, False  # unparseable audit reply -> couldn't verify
    confirmed = [c for n, c in enumerate(criticals, 1) if n in keep]
    return confirmed, True  # audit ran: real kept subset (empty set = retract all)


def _writeback_false_positives(dropped: list, pr_number: int, repo: str) -> None:
    """PR-C Fix #6: record dropped BLOCKING fabrications as quarantined KB mistakes so the rubric
    learns over time (C.O.D.E.X. promotes from quarantine). Best-effort; never breaks the review."""
    blockers = [d for d in dropped if str((d or {}).get("severity", "")).upper() in ("CRITICAL", "WARNING")]
    if not blockers:
        return
    try:
        from services.agent_kb_service import propose_agent_memory

        for d in blockers[:2]:  # cap to avoid spam; quarantine + C.O.D.E.X. gate the rest
            title = ((d or {}).get("title") or "")[:120]
            ev = ((d or {}).get("evidence") or "")[:160]
            content = (
                f"F.O.R.G.E. code-review FALSE POSITIVE (auto-detected): flagged "
                f"[{(d or {}).get('severity', '')}] '{title}' on PR #{pr_number} but the cited evidence "
                f"'{ev}' is NOT a changed line in the diff (fabricated/unsupported). Do not raise this "
                f"class of issue without a verbatim changed + or - line."
            )
            propose_agent_memory(
                agent_id=136,
                agent_name="F.O.R.G.E.",
                content=content,
                title=f"FORGE false-positive: {title}"[:120],
                tags=["code_review", "false_positive", "agent_optimization"],
            )
    except Exception as exc:
        logger.info("[PR Review] false-positive writeback skipped: %s", exc)


def _json_reprompt_enabled() -> bool:
    """ST-1: re-prompt the model ONCE for clean JSON when the first structured reply doesn't parse,
    before dropping to the gated freeform path. Default ON; rollback: forge:json_reprompt_enabled=false."""
    return str(_get_setting("forge:json_reprompt_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _dispatch_json_review(prompt: str, kw: dict):
    """One structured (json_mode) review dispatch. Returns ``(parsed_dict_or_None, status)`` where
    status is 'parsed' | 'parse_fail' | 'queued' | 'error' | 'empty'. Shared by the first structured
    attempt and the ST-1 JSON re-prompt so both honor the same node pinning, num_ctx, and tier model.
    Only 'parse_fail' (a real non-JSON response) warrants a re-prompt — queued/error/empty go straight
    to the freeform fallback, exactly as before."""
    from tools.department_hq.services.department_dispatcher import dispatch

    try:
        result = dispatch(
            capability="code_review",
            prompt=prompt,
            module_id="repair_bay",
            json_mode=True,
            preferred_node=["starship_76583490e36955ab", "archie-starbase"],
            num_ctx=_review_num_ctx(),
            **kw,
        )
    except Exception as exc:
        logger.warning("[PR Review] structured dispatch error, falling back: %s", exc)
        return None, "error"
    if getattr(result, "queued", False):
        return None, "queued"
    if not (getattr(result, "success", False) and getattr(result, "response", "")):
        return None, "empty"
    parsed = _parse_review_json(result.response)
    return (parsed, "parsed") if parsed else (None, "parse_fail")


def _check_dockerfile_provenance(diff: str) -> list:
    """Deterministic deploy-provenance guard (#4749, KB mistake #279350).

    An image-baked Dockerfile (``COPY .`` — bakes the whole source into the image)
    that ships WITHOUT a ``GIT_SHA`` build ARG can't stamp its commit, so ``/version``
    can't report it and deploy-drift monitoring goes blind (the exact project-#385
    failure: per-branch deploys silently reverting each other). Flag any diff section
    for a Dockerfile that ADDS a whole-context COPY but introduces no ``GIT_SHA`` arg.

    Advisory only (severity 'low' → never blocks a merge; verdict blocks solely on
    CRITICAL/WARNING) and conservative: a GIT_SHA already in the surrounding context
    lines suppresses the finding, so editing an already-stamped Dockerfile won't
    false-positive. Fail-open: any parse issue or a missing diff returns []."""
    if not diff or "Dockerfile" not in diff:
        return []
    findings = []
    try:
        for sec in re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE):
            first = sec.splitlines()[0] if sec else ""
            if "Dockerfile" not in first:
                continue
            m = re.search(r" b/(\S+)", first)
            path = m.group(1) if m else "Dockerfile"
            if not path.rsplit("/", 1)[-1].startswith("Dockerfile"):
                continue
            added = "\n".join(ln[1:] for ln in sec.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
            # Only when the change ADDS a whole-context copy (COPY .  /  COPY ./  /  COPY . .).
            if not re.search(r"^\s*COPY\s+\.\.?/?(\s|$)", added, re.MULTILINE):
                continue
            # Suppress if a GIT_SHA arg is present anywhere in this file's hunk (added OR context).
            if re.search(r"\bARG\s+GIT_SHA\b", sec) or "GIT_SHA" in added:
                continue
            findings.append(
                {
                    "severity": "low",
                    "title": f"Dockerfile `{path}` bakes source (COPY .) without a GIT_SHA build ARG",
                    "why": (
                        "Image-baked products must stamp their commit so /version reports it and "
                        "deploy-drift monitoring works (deploy-provenance, KB #279350). Add "
                        "`ARG GIT_SHA` + `ENV <PRODUCT>_GIT_SHA=$GIT_SHA` near the end of the "
                        "Dockerfile, pass `build.args: {GIT_SHA: ...}` in compose, and deploy via "
                        "scripts/deploy_with_sha.sh."
                    ),
                    "evidence": f"{path} adds a whole-context COPY but no `ARG GIT_SHA`.",
                }
            )
    except Exception as exc:  # noqa: BLE001 — advisory check must never break a review
        logger.info("[PR Review] dockerfile-provenance check skipped: %s", exc)
        return []
    return findings


def _structured_review(
    review: dict,
    diff: str,
    pr_number: int = None,
    repo: str = None,
    ground_diff: str = None,
    dockerfile_findings: list = None,
):
    """PR-B: JSON-structured grounded review. Returns canonical review TEXT, or None to fall back
    to the freeform path (disabled flag / queue / empty / unparseable JSON — all fail-safe)."""
    # #5848 — `diff` is what the MODEL SEES (a chunk once chunking is on). `ground_diff`
    # is the WHOLE PR, used by every grounding / absence check. Defaults to diff, so every
    # pre-chunking caller is byte-for-byte unchanged.
    #
    # Decision 2 of the spec: judge against the whole PR, show only the chunk. If grounding
    # used the chunk, a finding whose evidence lives in ANOTHER chunk would be dropped as
    # ungrounded — and that is a real defect class splitting itself manufactures (a caller
    # in chunk 1 broken by a signature change in chunk 3).
    ground_diff = ground_diff if ground_diff is not None else diff

    if not _structured_review_enabled():
        return None
    from tools.repair_bay.services.pr_review_service import classify_pr_tier

    try:
        tier = classify_pr_tier(review)
    except Exception:
        tier = 1
    kw = {}
    model_label = "default"
    strong = tier >= 3  # ST-3: Tier-3 -> gemma3:12b (full diff window); else qwen2.5:7b (tighter cap)
    if strong:
        kw["prefer_model"] = _TIER3_REVIEW_MODEL
        model_label = _TIER3_REVIEW_MODEL
    parsed, status = _dispatch_json_review(_build_json_prompt(review, diff, strong=strong), kw)
    if status == "queued":
        return None  # cold model — let the freeform path handle the queue + callback
    if status == "parse_fail" and _json_reprompt_enabled():
        # ST-1: the model replied but not as JSON — re-prompt ONCE for a clean object before we
        # drop to the (gated) freeform path. Fires only on a real non-JSON reply, so it's rare
        # once _parse_review_json strips fences/prose and QW-5 keeps the rubric in-window.
        reprompt = (
            "Your previous reply was NOT valid JSON. Return ONLY a single JSON object matching the "
            "schema below — no markdown code fences, no prose, nothing before or after the braces.\n\n"
            + _build_json_prompt(review, diff, strong=strong)
        )
        parsed, status = _dispatch_json_review(reprompt, kw)
        if parsed:
            logger.info("[PR Review] PR #%s — recovered structured JSON on re-prompt", pr_number)
    if not parsed:
        logger.info("[PR Review] structured JSON unparseable for PR #%s — falling back", pr_number)
        return None
    issues = parsed.get("issues") or []
    note = ""
    n_ungrounded = 0
    # PR-C: deterministic evidence-verification — drop issues whose evidence isn't a changed line.
    if _evidence_verification_enabled():
        kept, dropped = _verify_evidence(issues, ground_diff)
        if dropped:
            note = f"dropped {len(dropped)} issue(s) with evidence not in the diff"
            n_ungrounded = _count_ungrounded(dropped)
            logger.info("[PR Review] PR #%s — %s", pr_number, note)
            if _writeback_enabled():
                _writeback_false_positives(dropped, pr_number, repo)
        issues = kept
    # PR-C + ST-2: self-refute surviving CRITICALs (highest-stakes only).
    unverified_criticals = []
    if _self_refute_enabled():
        criticals = [i for i in issues if str((i or {}).get("severity", "")).upper() == "CRITICAL"]
        if criticals:
            confirmed, audit_ran = _self_refute_criticals(review, ground_diff, criticals)
            if audit_ran:
                if len(confirmed) != len(criticals):
                    cset = {id(c) for c in confirmed}
                    issues = [
                        i for i in issues if str((i or {}).get("severity", "")).upper() != "CRITICAL" or id(i) in cset
                    ]
                    note = (
                        note + "; " if note else ""
                    ) + f"self-refute retracted {len(criticals) - len(confirmed)} CRITICAL"
            elif _self_refute_failclosed_enabled():
                # ST-2: the auditor was UNAVAILABLE -> these CRITICALs are unverified. Keep them
                # VISIBLE but don't let a possibly-hallucinated CRITICAL auto-block; mark them so the
                # verdict floors to NEEDS REVIEW (a human adjudicates) instead of REQUEST CHANGES.
                unverified_criticals = [c for c in criticals if isinstance(c, dict)]
                for c in unverified_criticals:
                    c["_unverified"] = True
                note = (note + "; " if note else "") + (
                    f"{len(criticals)} CRITICAL unverified (auditor unavailable) → NEEDS REVIEW"
                )
    # QW-2: demote non-blocking nit categories to INFO BEFORE the verdict + render, so a
    # true-but-trivial WARNING/CRITICAL can't block (the dominant residual false-block class, RC-2).
    _normalize_severity(issues)
    n_demoted = sum(1 for i in issues if isinstance(i, dict) and i.get("_demoted_from"))
    if n_demoted:
        note = (note + "; " if note else "") + f"normalized {n_demoted} nit(s) to INFO"
    # Deploy-provenance guard (#4749): deterministic, appended AFTER normalize so it stays
    # advisory 'low' (non-blocking) and isn't counted among the demoted nits.
    # #5848 task 5 — provenance is a WHOLE-PR property, so the caller computes it once on the
    # full diff and hands it in. None means no caller supplied it (any future direct caller),
    # in which case compute it here exactly as before.
    if dockerfile_findings is None:
        dockerfile_findings = _check_dockerfile_provenance(ground_diff)
    if dockerfile_findings:
        issues.extend(dockerfile_findings)
        note = (note + "; " if note else "") + f"deploy-provenance: {len(dockerfile_findings)} Dockerfile finding(s)"
    parsed["issues"] = issues
    # ST-2: an unverified CRITICAL must not ASSERT a block — exclude it from the verdict computation,
    # then floor to NEEDS REVIEW so it reaches a human (unless a real blocker already requests changes).
    verdict_issues = [i for i in issues if not (isinstance(i, dict) and i.get("_unverified"))]
    verdict = _recompute_verdict(verdict_issues, parsed.get("confidence"), _review_confidence_min())
    if unverified_criticals and verdict != "REQUEST CHANGES":
        verdict = "NEEDS REVIEW"
    # #5009: an APPROVE is only meaningful if the reviewer demonstrably READ the diff. When the model
    # raised issues and EVERY one was dropped as ungrounded (evidence absent from its own input),
    # nothing it said was anchored to the change — yet the old code reached APPROVE precisely BECAUSE
    # the anti-hallucination filter had emptied the issue list. That is how PR #2351 (+147/-23) was
    # auto-approved by a review whose summary said the diff "does not contain any actual code
    # changes". Floor to NEEDS REVIEW so a human adjudicates; NEEDS REVIEW does not auto-merge.
    # Deliberately narrow: only when NOTHING survived. A model that grounded even one issue was
    # reading the diff, and spurious_injection drops (a trusted correction) never count.
    if _should_floor_ungrounded(verdict, n_ungrounded, verdict_issues) and _ungrounded_review_floor_enabled():
        verdict = "NEEDS REVIEW"
        note = (note + "; " if note else "") + (
            f"ungrounded review: all {n_ungrounded} issue(s) cited evidence absent from the diff "
            "— floored to NEEDS REVIEW (#5009)"
        )
        logger.warning(
            "[PR Review] PR #%s — APPROVE floored to NEEDS REVIEW: %d/%d issues ungrounded",
            pr_number,
            n_ungrounded,
            n_ungrounded,
        )
    # #5287: an RC resting SOLELY on blocking issues that cite no evidence has no adjudicable
    # content — demote to NEEDS REVIEW (never APPROVE) so a human decides and auto-merge can't.
    if _unevidenced_demotion_enabled() and _demote_unevidenced_blocking(verdict, verdict_issues):
        verdict = "NEEDS REVIEW"
        note = (note + "; " if note else "") + "blocking issue(s) cite no evidence — demoted to NEEDS REVIEW (#5287)"
        logger.warning(
            "[PR Review] PR #%s — blocking verdict demoted to NEEDS REVIEW: every blocking issue cites no evidence",
            pr_number,
        )
    parsed["verdict"] = verdict

    # GATE 5 (#5647) — the false CLEAR. Gates 1-4 interrogate FINDINGS; an APPROVE has none,
    # so its summary PROSE was never checked against the diff. PR #2603 was APPROVED with
    # "The parameterized SQL usage and test addition are correct" on a diff containing
    # neither. Strip the fabricated sentence, flag it, and LEAVE THE VERDICT ALONE — a
    # fabricated compliment is a reporting defect, not evidence the code is broken.
    unsupported_claims = []
    if _false_clear_gate_enabled():
        cleaned, unsupported_claims = strip_unsupported_claims(parsed.get("summary") or "", ground_diff)
        if unsupported_claims:
            parsed["summary"] = cleaned
            note = (note + "; " if note else "") + (
                "summary asserted artifact(s) absent from the diff: "
                + ", ".join(unsupported_claims)
                + " — claim(s) stripped, verdict unchanged (#5647)"
            )
            logger.warning(
                "[PR Review] PR #%s — summary claimed %s not present in the diff; stripped (verdict %s unchanged)",
                pr_number,
                unsupported_claims,
                verdict,
            )
    return _render_review_text(parsed, model=model_label, note=note, unsupported_claims=unsupported_claims)


# --- QW-1 (#381): gate the FREEFORM fallback with the SAME guards as the structured path --------
# RC-1 (dominant): every Phase-1 guard (evidence-verification, injection drop, severity normalizer,
# deterministic verdict recompute) lived ONLY inside _structured_review. The freeform fallback —
# which handles ~80% of reviews when the 7B doesn't emit clean JSON — ran a single relax-only
# _apply_severity_gate, so a fabricated [CRITICAL] (evidence not in the diff) blocked unconditionally.
# QW-1 parses the freeform issue lines into the same dicts and runs them through the identical
# evidence + normalize + recompute pipeline. Fail-open: any problem returns the prior behavior.


def _freeform_gate_enabled() -> bool:
    return str(_get_setting("forge:freeform_gate_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_FREEFORM_ISSUE_RE = re.compile(r"^\s*[-*]?\s*\[\s*(CRITICAL|WARNING|INFO)\s*\]\s*(.+)$", re.IGNORECASE)


def _parse_freeform_issues(text: str) -> list:
    """Parse the rubric-mandated ``- [SEV] <title> — <why> — Evidence: <line>`` freeform issue lines
    into the same {severity,title,why,evidence} dicts the structured path uses."""
    issues = []
    for line in (text or "").splitlines():
        m = _FREEFORM_ISSUE_RE.match(line)
        if not m:
            continue
        sev = m.group(1).upper()
        body = m.group(2).strip()
        ev = ""
        ev_m = re.search(r"evidence\s*:\s*(.*)$", body, re.IGNORECASE)
        if ev_m:
            ev = ev_m.group(1).strip()
            body = body[: ev_m.start()].rstrip(" —–-")
        parts = re.split(r"\s+[—–-]\s+", body, maxsplit=1)
        title = parts[0].strip()
        why = parts[1].strip() if len(parts) > 1 else ""
        issues.append({"severity": sev, "title": title, "why": why, "evidence": ev})
    return issues


def _extract_summary_block(text: str) -> str:
    """Pull the SUMMARY paragraph out of a freeform review (between 'SUMMARY' and 'ISSUES')."""
    m = re.search(r"SUMMARY\s*\n(.*?)(?:\n\s*ISSUES\b|\Z)", text or "", re.IGNORECASE | re.S)
    return (m.group(1).strip() if m else "").strip()


def _render_freeform_gated(summary: str, issues: list, verdict: str, note: str, n_ungrounded: int = 0) -> str:
    """Re-render the gated freeform review into canonical SUMMARY/ISSUES/VERDICT text so the merge
    gate + parse_verdict see the recomputed verdict. Marked structured=freeform-gated (not =json)."""
    lines = [f"SUMMARY\n{summary}\n", "ISSUES"]
    if issues:
        for i in issues:
            sev = str((i or {}).get("severity", "INFO")).upper()
            title = ((i or {}).get("title") or "").strip()
            why = ((i or {}).get("why") or "").strip()
            ev = ((i or {}).get("evidence") or "").strip()
            lines.append(f"- [{sev}] {title} — {why} — Evidence: {ev}")
    else:
        lines.append("No issues found.")
    meta = (
        "\n[review-meta] structured=freeform-gated"
        + (f" {note}" if note else "")
        + _quality_suffix("freeform-gated", n_ungrounded, issues)  # #5018 provenance, never a verdict change
    )
    return "\n".join(lines) + f"\n\nVERDICT: {verdict}" + meta


def _gate_freeform_review(text: str, diff: str, pr_number: int = None, repo: str = None) -> str:
    """QW-1 (RC-1): run the FREEFORM review through the same evidence-verification + severity
    normalizer + deterministic verdict recompute as the structured path. Fail-open — flag off / no
    parsed issues / no diff / any exception returns the prior _apply_severity_gate(text), never worse."""
    if not text or not _freeform_gate_enabled():
        return _apply_severity_gate(text)
    try:
        issues = _parse_freeform_issues(text)
        dockerfile_findings = _check_dockerfile_provenance(diff) if diff else []
        if (not issues and not dockerfile_findings) or not diff:
            return _apply_severity_gate(text)
        notes = []
        n_ungrounded = 0
        if issues and _evidence_verification_enabled():
            kept, dropped = _verify_evidence(issues, diff)
            if dropped:
                notes.append(f"dropped {len(dropped)} issue(s) with evidence not in the diff")
                n_ungrounded = _count_ungrounded(dropped)
                if _writeback_enabled():
                    _writeback_false_positives(dropped, pr_number, repo)
            issues = kept
        _normalize_severity(issues)
        n_demoted = sum(1 for i in issues if isinstance(i, dict) and i.get("_demoted_from"))
        if n_demoted:
            notes.append(f"normalized {n_demoted} nit(s) to INFO")
        # Deploy-provenance guard (#4749): deterministic, appended AFTER normalize so it stays
        # advisory 'low' (non-blocking) and isn't counted among the demoted nits.
        if dockerfile_findings:
            issues.extend(dockerfile_findings)
            notes.append(f"deploy-provenance: {len(dockerfile_findings)} Dockerfile finding(s)")
        verdict = _recompute_verdict(issues, None, _review_confidence_min())
        # #5009: same ungrounded-review floor as the structured path — the freeform fallback handles
        # the majority of reviews, so guarding only the structured path would leave the hole open.
        if _should_floor_ungrounded(verdict, n_ungrounded, issues) and _ungrounded_review_floor_enabled():
            verdict = "NEEDS REVIEW"
            notes.append(
                f"ungrounded review: all {n_ungrounded} issue(s) cited evidence absent from the diff "
                "— floored to NEEDS REVIEW (#5009)"
            )
        # #5287: same unevidenced-blocking demotion as the structured path — the freeform fallback
        # is precisely where the evidence-less blocking CRITICALs come from (#2366, #2501).
        if _unevidenced_demotion_enabled() and _demote_unevidenced_blocking(verdict, issues):
            verdict = "NEEDS REVIEW"
            notes.append("blocking issue(s) cite no evidence — demoted to NEEDS REVIEW (#5287)")
        # n_ungrounded passthrough (#5287): was omitted, so `no_grounded_evidence` could never
        # appear on a freeform-gated meta line even when every issue was dropped as ungrounded.
        return _render_freeform_gated(
            _extract_summary_block(text), issues, verdict, "; ".join(notes), n_ungrounded=n_ungrounded
        )
    except Exception as exc:
        logger.info("[PR Review] freeform gate fell back to severity-gate: %s", exc)
        return _apply_severity_gate(text)


def _is_degraded_blocking(summary: str) -> bool:
    """True for a blocking verdict produced OFF the structured path (#5287).

    ``structured=json`` in the meta marks the authoritative path. Anything else — the gated
    freeform fallback (``structured=freeform-gated``) or legacy severity-gate text with no meta
    line at all — is the degraded path, whose REQUEST CHANGES warrants one structured retry
    before it is stored as the verdict."""
    if not summary or "structured=json" in summary:
        return False
    return parse_verdict(summary) == "REQUEST CHANGES"


# #5848 — verdict LATTICE for folding chunk results. NEEDS REVIEW means "a human should look";
# REQUEST CHANGES asserts a DEFECT. Folding the first into the second manufactures a defect claim
# no pass actually made, and false blocks are the live problem this work exists to reduce. An
# unparseable verdict ("REVIEWED") and a lost pass both land on NEEDS REVIEW: neither found a
# defect, and neither auto-merges (verdict_is_approved admits APPROVE only).
_VERDICT_RANK = {"APPROVE": 0, "REVIEWED": 1, "NEEDS REVIEW": 1, "REQUEST CHANGES": 2}
_VERDICT_BY_RANK = {0: "APPROVE", 1: "NEEDS REVIEW", 2: "REQUEST CHANGES"}


def _merge_chunk_summaries(summaries: list, cov: dict) -> str:
    """Fold per-chunk summaries into ONE canonical review (#5848). Worst verdict wins.

    Fails CLOSED twice over: a pass that returned NOTHING blocks, and so does one whose
    verdict will not parse — ``parse_verdict`` returns "REVIEWED", not "APPROVE", when there
    is no VERDICT line. A lost pass must never read as an approval; that is the #2458 shape.

    The ``[review-meta]`` path marker is carried forward WEAKEST-WINS. It is not cosmetic:
    ``pr_review_service._classify_review_path`` reads a summary with NO marker as "legacy —
    the degraded path" and feeds ``check_review_path_health`` → ``send_system``, so folding
    the marker away would alarm on a perfectly healthy chunked review. A lost pass degrades
    the marker too, because that review genuinely was degraded."""
    findings, seen, paths = [], set(), []
    worst, lost = 0, False
    for idx, s in enumerate(summaries, 1):
        if not s:
            lost = True
            continue
        paths.append(_classify_review_path(s))
        rank = _VERDICT_RANK.get(parse_verdict(s), 1)
        chunk_blocks = rank > 0
        worst = max(worst, rank)
        before = len(findings)
        for line in s.splitlines():
            st = line.strip()
            if not st.startswith("- ["):
                continue
            key = _normalize_match(st)
            if key in seen:
                continue
            seen.add(key)
            findings.append(st)
        # A blocking pass that yielded no parseable finding would otherwise fold into
        # "REQUEST CHANGES / No issues found." — a block with no stated reason. That is the
        # unactionable review this work exists to stop producing, so keep its prose.
        if chunk_blocks and len(findings) == before:
            raw = " ".join(
                x.strip() for x in s.splitlines() if x.strip() and not x.strip().startswith(("VERDICT:", "[review-"))
            )
            if raw:
                findings.append(f"- [WARNING] pass {idx} blocked without a parseable finding — {raw[:300]}")

    n = len(summaries)
    read = ""
    if cov and cov.get("total"):
        read = f"; {cov.get('reviewed', cov['total'])}/{cov['total']} files read"
    body = "\n".join(findings) if findings else "No issues found."
    verdict = _VERDICT_BY_RANK[max(worst, 1 if lost else 0)]

    healthy = bool(paths) and not lost
    if healthy and all(p == "structured_json" for p in paths):
        meta = f"\n[review-meta] structured=json chunks={len(paths)}"
    elif healthy and all(p in ("structured_json", "freeform_gated") for p in paths):
        meta = f"\n[review-meta] structured=freeform-gated chunks={len(paths)}"
    else:
        meta = ""
    if lost:
        meta += "\n[review-meta] a chunk produced no parseable review — failing closed"
    plural = "pass" if n == 1 else "passes"
    return f"SUMMARY\nChunked review ({n} {plural}{read}).\n\nISSUES\n{body}\n\nVERDICT: {verdict}{meta}"


def _obtain_review_summary(review: dict, diff: str, pr_number: int = None, repo: str = None) -> str | None:
    """Structured first, freeform fallback — with ONE bounded structured retry when the fallback
    produced a blocking verdict (#5287). Shared by review_pr and analyze_pending_prs.

    Measured 2026-07-27: the SAME diff (PR #2503, commit unchanged between runs) drew a false
    blocking CRITICAL on the freeform path and a clean APPROVE on the structured path — and the
    merge gate (verdict_is_approved + #5194) weighs both verdicts equally. So a degraded-path
    REQUEST CHANGES earns exactly ONE structured re-attempt:

      * a PARSED structured verdict supersedes it WHATEVER it says — a persistent REQUEST
        CHANGES stands, so this is a path upgrade, never retry-until-APPROVE;
      * an unavailable structured path (cold model / parse failure) leaves the degraded verdict
        standing, annotated so a human knows which path produced it.

    Bounded by construction: the retry is a single _structured_review call and its output is
    never re-examined by this guard. A degraded APPROVE is deliberately NOT retried — the
    existing #5009 floor + the approved-verdict + tier requirements of the merge gate already
    bound that direction, and re-rolling approvals would add dispatch load for no safety gain."""
    # #5836 — COVERAGE gate. Measured at _diff_cap_for_model(strong=False) because that
    # cap (min(full, _DIFF_MAX_7B)) is what BOTH the freeform fallback AND every Tier-1/2
    # structured review use; only the Tier-3 strong path gets the wider window, and a
    # Tier-3 PR is auto-merged by nobody, so an extra coverage note there costs nothing.
    # Erring toward the smaller cap errs toward FLAGGING, which is the safe direction:
    # an over-flag costs a human glance, an under-flag is #5836 itself.
    _cap = _diff_cap_for_model(strong=False)
    # #5836 follow-up — ORDER the window before measuring or reviewing it. GitHub emits
    # files alphabetically, so `.claude/rules/...` sorts ahead of all code; on PR #2713 a
    # ONE-LINE rules edit (multi-KB lines) took 58% of the budget and the review came back
    # "only a markdown file update". prioritize() is a no-op unless the diff would actually
    # truncate, so a PR that fits is passed through byte-identical.
    diff = prioritize(diff, _cap)
    # #5848 — a diff that will not fit is split into at most 3 SERIAL passes rather than
    # truncated away. At the default forge:review_max_chunks=1, chunk_plan returns [diff]
    # UNCHANGED, so every line below runs exactly as it did pre-chunking. That byte-identity
    # IS the killswitch — it is pinned by tests/test_chunked_review_loop.py, do not weaken it.
    _chunks = chunk_plan(diff, _cap, _review_max_chunks()) or [diff]
    # Coverage is measured over the UNION of what the passes actually show, never over a
    # single window — otherwise chunking would keep reporting as dropped the very files it
    # just started reading.
    # Join with a NEWLINE, not "": _truncate_diff cuts an oversized chunk MID-LINE, and "" glues
    # that cut line straight onto the next chunk's "diff --git" header, so the ^diff --git
    # MULTILINE regex stops matching and a file that WAS reviewed reads as dropped — one lost
    # file per chunk boundary. For a single chunk "\n".join is byte-identical, so the
    # max_chunks=1 killswitch is unaffected.
    _shown = "\n".join(_truncate_diff(_c, _cap)[0] for _c in _chunks)
    _cov = coverage(diff, _shown)
    if not _cov["complete"]:
        logger.warning("[PR Review] PR #%s — %s", pr_number, summarize(_cov))

    # #5848 task 5 — whole-PR checks run ONCE, on the FULL diff. Dockerfile provenance (#4749)
    # is a property of the PR, not of a chunk: per-chunk it would duplicate the finding N times,
    # and scoped to a chunk it would miss a Dockerfile that landed in a different one. It is
    # attached to chunk 0 only, so it renders exactly once in the merged review.
    _prov = _check_dockerfile_provenance(diff)

    _summaries = []
    _retry_used = False
    for _idx, _chunk in enumerate(_chunks):
        _chunk_prov = _prov if _idx == 0 else []
        # ground_diff is ALWAYS the FULL diff (spec Decision 2). A finding whose evidence
        # lives in a different chunk is a genuine cross-chunk defect — the exact class that
        # splitting creates — and grounding against the chunk would drop precisely those.
        summary = _structured_review(
            review, _chunk, pr_number, repo, ground_diff=diff, dockerfile_findings=_chunk_prov
        ) or _run_forge_review(_build_prompt(review, _chunk), pr_number, repo, diff=diff)
        # #5287 — ONE structured retry per REVIEW, not per chunk. The retry is a path upgrade
        # for a degraded blocking verdict and its dispatch budget belongs to the review; a
        # persistent REQUEST CHANGES still stands whatever the retry says.
        if summary and not _retry_used and _freeform_rc_retry_enabled() and _is_degraded_blocking(summary):
            _retry_used = True
            logger.info(
                "[PR Review] PR #%s — degraded-path blocking verdict; attempting one structured retry (#5287)",
                pr_number,
            )
            retry = _structured_review(
                review, _chunk, pr_number, repo, ground_diff=diff, dockerfile_findings=_chunk_prov
            )
            summary = (
                retry + "\n[review-meta-note] degraded-path blocking verdict superseded by structured retry (#5287)"
                if retry
                else summary
                + "\n[review-meta-note] degraded-path blocking verdict stood — structured retry unavailable (#5287)"
            )
        _summaries.append(summary)

    if len(_summaries) == 1:
        return annotate(_summaries[0], _cov)
    # Every pass failed — return None so the caller sees "review unavailable", exactly as the
    # single-pass path does. A fabricated empty review would be worse than no review.
    if not any(_summaries):
        return None
    return annotate(_merge_chunk_summaries(_summaries, _cov), _cov)


def _run_forge_review(prompt: str, pr_number: int = None, repo: str = None, diff: str = None) -> str | None:
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
            num_ctx=_review_num_ctx(),
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
            return _gate_freeform_review(result.response.strip(), diff, pr_number, repo)
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
