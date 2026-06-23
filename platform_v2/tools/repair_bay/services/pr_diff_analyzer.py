"""PR Diff Analyzer — Phase 2 of the PR Review Pipeline.

Fetches GitHub diffs for pending PR reviews and dispatches them to F.O.R.G.E.
via the Bridge dispatcher for AI code review. Results stored in pr_reviews.ai_summary.
"""

from __future__ import annotations

import logging
import os
import re

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
    "syntax / 'unclosed-loop' / 'no-tests' issue.\n"
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
        summary = _structured_review(review, diff, pr_number, _repo) or _run_forge_review(
            _build_prompt(review, diff), pr_number, _repo, diff=diff
        )
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
            summary = _structured_review(review, diff, pr_number, repo) or _run_forge_review(
                prompt, pr_number, repo, diff=diff
            )

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
        if _NONBLOCKING_CATEGORY_RE.search(blob):
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
        if m and _NONBLOCKING_CATEGORY_RE.search(m.group(2)):
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


def _render_review_text(parsed: dict, model: str = "", note: str = "") -> str:
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
    return "\n".join(lines) + f"\n\nVERDICT: {parsed.get('verdict', 'NEEDS REVIEW')}" + meta


# --- Phase-1 PR-C: deterministic evidence-verification + self-refute + false-positive learning (#381) ---


def _normalize_match(s: str) -> str:
    import re as _re

    return _re.sub(r"\s+", " ", (s or "").lower()).strip()


def _evidence_in_diff(evidence: str, diff: str) -> bool:
    """True if the issue's cited evidence ties to a line this PR actually CHANGED. Catches
    fabricated citations (PR-C): a line the model invented, or an unchanged/context line cited as
    if changed (the #1869 'unused import time' fabrication — import time is context, not a + line).
    Conservative: only returns False when a substantial evidence string is genuinely absent from
    the +/- lines (short or lightly-paraphrased evidence is kept)."""
    import re as _re

    if not evidence or not diff:
        return True  # nothing to verify -> don't drop
    changed = " ".join(ln[1:] for ln in diff.splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---"))
    changed_n = _normalize_match(changed)
    core = _normalize_match(_re.sub(r"^[+\-\s]+", "", evidence))
    if len(core) < 6:
        return True  # trivially short (<6 chars) -> ambiguous, don't drop
    if core in changed_n:
        return True
    toks = _re.findall(r"[a-z_][a-z0-9_]{2,}", core)  # tolerate light paraphrase of a real line
    if toks and sum(1 for t in toks if t in changed_n) / len(toks) >= 0.85:
        return True
    return False


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


def _verify_evidence(issues: list, diff: str):
    """Split issues into (kept, dropped): drop issues whose evidence isn't a changed diff line
    (fabricated citation) OR that are a spurious 'SQL injection' flag on a parameterized query."""
    kept, dropped = [], []
    for it in issues or []:
        ev = (it or {}).get("evidence") or ""
        if not _evidence_in_diff(ev, diff) or _is_spurious_injection(it):
            dropped.append(it)
        else:
            kept.append(it)
    return kept, dropped


def _evidence_verification_enabled() -> bool:
    return str(_get_setting("forge:evidence_verification_enabled", "true")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _self_refute_enabled() -> bool:
    return str(_get_setting("forge:self_refute_enabled", "true")).strip().lower() in ("1", "true", "yes", "on")


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


def _structured_review(review: dict, diff: str, pr_number: int = None, repo: str = None):
    """PR-B: JSON-structured grounded review. Returns canonical review TEXT, or None to fall back
    to the freeform path (disabled flag / queue / empty / unparseable JSON — all fail-safe)."""
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
    # PR-C: deterministic evidence-verification — drop issues whose evidence isn't a changed line.
    if _evidence_verification_enabled():
        kept, dropped = _verify_evidence(issues, diff)
        if dropped:
            note = f"dropped {len(dropped)} issue(s) with evidence not in the diff"
            logger.info("[PR Review] PR #%s — %s", pr_number, note)
            if _writeback_enabled():
                _writeback_false_positives(dropped, pr_number, repo)
        issues = kept
    # PR-C + ST-2: self-refute surviving CRITICALs (highest-stakes only).
    unverified_criticals = []
    if _self_refute_enabled():
        criticals = [i for i in issues if str((i or {}).get("severity", "")).upper() == "CRITICAL"]
        if criticals:
            confirmed, audit_ran = _self_refute_criticals(review, diff, criticals)
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
    parsed["issues"] = issues
    # ST-2: an unverified CRITICAL must not ASSERT a block — exclude it from the verdict computation,
    # then floor to NEEDS REVIEW so it reaches a human (unless a real blocker already requests changes).
    verdict_issues = [i for i in issues if not (isinstance(i, dict) and i.get("_unverified"))]
    verdict = _recompute_verdict(verdict_issues, parsed.get("confidence"), _review_confidence_min())
    if unverified_criticals and verdict != "REQUEST CHANGES":
        verdict = "NEEDS REVIEW"
    parsed["verdict"] = verdict
    return _render_review_text(parsed, model=model_label, note=note)


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


def _render_freeform_gated(summary: str, issues: list, verdict: str, note: str) -> str:
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
    meta = "\n[review-meta] structured=freeform-gated" + (f" {note}" if note else "")
    return "\n".join(lines) + f"\n\nVERDICT: {verdict}" + meta


def _gate_freeform_review(text: str, diff: str, pr_number: int = None, repo: str = None) -> str:
    """QW-1 (RC-1): run the FREEFORM review through the same evidence-verification + severity
    normalizer + deterministic verdict recompute as the structured path. Fail-open — flag off / no
    parsed issues / no diff / any exception returns the prior _apply_severity_gate(text), never worse."""
    if not text or not _freeform_gate_enabled():
        return _apply_severity_gate(text)
    try:
        issues = _parse_freeform_issues(text)
        if not issues or not diff:
            return _apply_severity_gate(text)
        notes = []
        if _evidence_verification_enabled():
            kept, dropped = _verify_evidence(issues, diff)
            if dropped:
                notes.append(f"dropped {len(dropped)} issue(s) with evidence not in the diff")
                if _writeback_enabled():
                    _writeback_false_positives(dropped, pr_number, repo)
            issues = kept
        _normalize_severity(issues)
        n_demoted = sum(1 for i in issues if isinstance(i, dict) and i.get("_demoted_from"))
        if n_demoted:
            notes.append(f"normalized {n_demoted} nit(s) to INFO")
        verdict = _recompute_verdict(issues, None, _review_confidence_min())
        return _render_freeform_gated(_extract_summary_block(text), issues, verdict, "; ".join(notes))
    except Exception as exc:
        logger.info("[PR Review] freeform gate fell back to severity-gate: %s", exc)
        return _apply_severity_gate(text)


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
