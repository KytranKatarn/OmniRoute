"""#5934 Phase 3 — close the Review-to-Coder loop: fix the SAME branch, re-review, cap at 2.

Phase 1 (#5932, PR #2898) let a human turn a REQUEST CHANGES review's blocking findings
into ``improvement_proposals`` rows (``status='fix_requested'``,
``metadata.source='pr_review_finding'``, evidence line mandatory). This module is the
consumer: it amends the ORIGINAL PR so the original PR is what gets re-reviewed —
existing fix-gen opens a NEW PR, which is exactly what this must not do.

THE CONTRACT (task #5934):
  * commit to the PR's HEAD BRANCH, never to main, never a new PR (hard guard below)
  * re-review via ``pr_diff_analyzer.review_pr`` after the push — NOT pr_review_service
    (that import raises ImportError and a background job exits 0, so a failed re-review
    would look like a completed one)
  * HARD CAP of 2 attempts per finding; the same finding failing twice escalates to the
    owner (Telegram) instead of looping
  * NEVER auto-merge — the allowlist + tier governance gate stays exactly as-is
  * the verdict is read from the STORED review row via ``verdict_is_approved()``, never
    the ``review_status`` column ('reviewed' means finished, not approved — #5194)

CONVERGENCE: a finding whose fix survives re-review flips its proposal to
``status='pr_open'`` with ``apply_mode='review_fix'`` — the SAME shape ship_as_pr and
record_engine_pr write — so ``complete_merged_fix_proposals`` (the one completion
authority, all three pollers) settles it when the human deliberately merges the PR,
and reopens it to fix_requested if the PR closes unmerged.

SAFETY around generation (the #2861 destructive-rewrite lesson): fixes are strict
FIND/REPLACE, the FIND block must occur EXACTLY ONCE in the file, and a fix that
shrinks the file by more than 20% is refused. Every refusal is counted and reported —
nothing is dropped silently.
"""

from __future__ import annotations

import base64
import json
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

_SOURCE = "pr_review_finding"
_MAX_ATTEMPTS = 2
_MAX_FINDINGS_PER_CYCLE = 3
_EXCERPT_RADIUS = 40  # lines of context around the evidence line in the fix prompt
_SHRINK_GUARD = 0.80  # new content must keep at least 80% of the old size

_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "find": {"type": "string"},
        "replace": {"type": "string"},
    },
    "required": ["find", "replace"],
}

_SYSTEM_PROMPT = (
    "You are a precise code-repair assistant. You fix EXACTLY ONE review finding with the "
    'SMALLEST possible change. Reply with JSON only: {"find": "...", "replace": "..."}. '
    "The find value MUST be copied VERBATIM from the file excerpt (including whitespace and "
    "newlines) and must be unique enough to occur only once in the file. Never rewrite "
    "unrelated code. Never invent identifiers that are not visible in the excerpt."
)


# --------------------------------------------------------------------------- helpers


def _strip_diff_marker(line: str) -> str:
    """Normalise a cited diff line to comparable code text (drop +/- and edge space)."""
    text = line or ""
    if text[:1] in "+-":
        text = text[1:]
    return text.strip()


def _locate_evidence_file(diff_text: str, evidence: str):
    """Which changed file carries the evidence line? Returns the b/ path or None.

    Walks the unified diff's ``+++ b/<path>`` sections and matches the evidence
    against hunk lines with quoting/whitespace normalised the same way on both sides.
    """
    needle = _strip_diff_marker(evidence)
    if not needle:
        return None
    current = None
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith(("+++", "---", "diff --git", "index ", "@@")):
            continue
        if current and line[:1] in "+-" and _strip_diff_marker(line) == needle:
            return current
    return None


def _excerpt_around(content: str, needle: str, radius: int = _EXCERPT_RADIUS) -> str:
    """A raw (never line-numbered — the find must be copy-pastable) window around the
    needle line; the whole file when the needle is not present or the file is small."""
    lines = (content or "").splitlines()
    if len(lines) <= 2 * radius:
        return content or ""
    idx = next((i for i, ln in enumerate(lines) if needle and needle in ln), None)
    if idx is None:
        return content or ""
    lo, hi = max(0, idx - radius), min(len(lines), idx + radius + 1)
    return "\n".join(lines[lo:hi])


def _validate_fix(content: str, find: str, replace: str):
    """(ok, reason). The gates that keep a generated fix from doing #2861-class damage."""
    if not find or not isinstance(find, str):
        return False, "empty find"
    if not isinstance(replace, str):
        return False, "replace is not a string"
    if find == replace:
        return False, "find == replace (no-op)"
    count = content.count(find)
    if count == 0:
        return False, "find not present in file (model did not copy verbatim)"
    if count > 1:
        return False, f"find occurs {count} times — not unique, refusing ambiguous replace"
    new_content = content.replace(find, replace, 1)
    # Mass-deletion guard, with an absolute floor: a minimal fix on a SMALL file is a
    # large percentage by construction, so the ratio alone would refuse legitimate
    # one-line fixes. Only a shrink that is BOTH >20% and >500 bytes reads as damage.
    shrink = len(content) - len(new_content)
    if shrink > max(500, int(len(content) * (1 - _SHRINK_GUARD))):
        return False, "fix deletes a large share of the file — refusing suspicious mass deletion"
    return True, "ok"


def _parse_fix_json(raw: str):
    """Tolerate fence-wrapped model JSON (the platform-wide _parse_llm_json lesson)."""
    text = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------- GitHub seams (patchable)


def _get_pr(repo: str, pr_number: int):
    from .github_service import _api_get

    ok, data = _api_get(f"/repos/{repo}/pulls/{pr_number}")
    return data if ok and isinstance(data, dict) else None


def _get_file_at_ref(repo: str, path: str, ref: str):
    """(text, blob_sha) of the file at ref, or (None, None)."""
    from .github_service import _api_get

    ok, data = _api_get(f"/repos/{repo}/contents/{path}", params={"ref": ref})
    if not ok or not isinstance(data, dict) or data.get("type") != "file":
        return None, None
    try:
        text = base64.b64decode(data.get("content") or "").decode("utf-8")
    except Exception:
        return None, None
    return text, data.get("sha")


def _put_file(repo: str, path: str, branch: str, new_content: str, blob_sha: str, message: str):
    """Commit ONE file to ``branch`` via the Contents API. Returns commit sha or None."""
    from .github_service import _api_put

    ok, data = _api_put(
        f"/repos/{repo}/contents/{path}",
        {
            "message": message,
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "sha": blob_sha,
            "branch": branch,
        },
    )
    if not ok:
        logger.warning("review_fix: contents PUT failed for %s@%s: %s", path, branch, data)
        return None
    return ((data.get("commit") or {}).get("sha")) if isinstance(data, dict) else None


def _fetch_pr_diff(repo: str, pr_number: int) -> str:
    from .pr_diff_analyzer import _fetch_diff

    # The API URL, NOT github.com/<repo>/pull/N.diff — _fetch_diff authenticates with a
    # token + diff Accept header, which the API honours and the web host 404s on a
    # private repo (measured live on the #5934 drive; also the form pr_reviews.diff_url
    # itself stores).
    return _fetch_diff(f"https://api.github.com/repos/{repo}/pulls/{pr_number}")


# --------------------------------------------------------- generation + review (seams)


def _generate_find_replace(finding_md: dict, file_content: str):
    """((find, replace), reason). All inference through the DHQ dispatcher (ADR-013),
    queue-aware (dispatch_awaiting_queue — bare dispatch masks cold-load queueing)."""
    from tools.department_hq.services.department_dispatcher import dispatch_awaiting_queue

    needle = _strip_diff_marker(finding_md.get("evidence") or "")
    excerpt = _excerpt_around(file_content, needle)
    prompt = (
        "Fix exactly this code-review finding with the minimal change.\n\n"
        f"FINDING ({finding_md.get('severity')}): {finding_md.get('finding_title')}\n"
        f"WHY IT MATTERS: {finding_md.get('finding_why') or '(not stated)'}\n"
        f"THE REVIEW CITED THIS LINE: {needle}\n\n"
        "FILE EXCERPT (verbatim — copy your find block from here):\n"
        "-----\n"
        f"{excerpt}\n"
        "-----\n\n"
        'Reply with JSON only: {"find": "<verbatim block to replace, occurring once>", '
        '"replace": "<the corrected block>"}'
    )
    raw = dispatch_awaiting_queue(
        "code",
        prompt,
        system_prompt=_SYSTEM_PROMPT,
        json_mode=_FIX_SCHEMA,
        module_id="review_fix",
        local_only=True,
        poll_timeout_s=300,
    )
    if not raw:
        return None, "dispatch returned nothing (failed or timed out)"
    data = _parse_fix_json(raw)
    if not data:
        return None, "model reply was not parseable JSON"
    find, replace = data.get("find"), data.get("replace")
    ok, reason = _validate_fix(file_content, find, replace)
    if not ok:
        return None, reason
    return (find, replace), "ok"


def _run_review(pr_number: int, repo: str):
    """(ran, approved). Re-review via pr_diff_analyzer.review_pr — the ONLY correct
    import (task #5934 warning) — then read the verdict from the STORED row with
    verdict_is_approved(); review_status alone means finished, not approved (#5194).
    forge_reviews attempt recording happens inside the review path itself."""
    from .pr_diff_analyzer import review_pr
    from .pr_review_service import get_review, verdict_is_approved

    try:
        review_pr(pr_number, repo=repo)
    except Exception as e:
        logger.warning("review_fix: re-review of PR #%s raised: %s", pr_number, e)
        return False, False
    row = get_review(pr_number, repo) or {}
    return True, verdict_is_approved(row.get("ai_summary") or "")


def _notify_owner(title: str, message: str):
    """Escalation channel — A.R.C.H.I.E.'s unified voice. Never raises into the loop."""
    try:
        from services.telegram_service import send_system

        send_system(title, message)
    except Exception as e:
        logger.warning("review_fix: owner notification failed: %s", e)


# ------------------------------------------------------------------- row bookkeeping


def _stamp(proposal_id: int, patch: dict, new_status: str = None):
    with get_db_cursor(commit=True) as (conn, cur):
        if new_status:
            cur.execute(
                """UPDATE improvement_proposals
                   SET status = %s,
                       metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                   WHERE id = %s""",
                (new_status, json.dumps(patch), proposal_id),
            )
        else:
            cur.execute(
                """UPDATE improvement_proposals
                   SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                   WHERE id = %s""",
                (json.dumps(patch), proposal_id),
            )


def _escalate(row: dict, reason: str):
    md = row["metadata"]
    pr = md.get("pr_number")
    attempts = int(md.get("fix_attempts") or 0)
    _stamp(row["id"], {"escalated": True, "escalated_reason": reason})
    _notify_owner(
        f"Review-fix escalation — PR #{pr}",
        (
            f"Finding \"{md.get('finding_title')}\" on PR #{pr} needs human attention "
            f"after {attempts} automated fix attempt(s): {reason}. "
            f"https://github.com/{md.get('repo')}/pull/{pr}"
        ),
    )
    logger.warning("review_fix: ESCALATED proposal #%s (PR #%s): %s", row["id"], pr, reason)


# --------------------------------------------------------------------------- the loop


def _candidates():
    """Non-escalated pr_review_finding fix requests, oldest PR first."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, metadata FROM improvement_proposals
               WHERE status = 'fix_requested'
                 AND metadata->>'source' = %s
                 AND (metadata->>'escalated') IS NULL
               ORDER BY (metadata->>'pr_number')::int, id""",
            (_SOURCE,),
        )
        return [dict(r) for r in cur.fetchall()]


def run_review_fix_cycle(max_findings: int = _MAX_FINDINGS_PER_CYCLE) -> dict:
    """Process ONE PR's send-back findings: fix on the SAME branch, re-review, cap at 2.

    Bounded by design — one PR and at most ``max_findings`` LLM fix generations per
    cycle. Every skip/refusal is counted in the result; nothing is dropped silently.
    """
    from .github_service import REPO_FULL

    result = {
        "prs_processed": 0,
        "pr_number": None,
        "fixes_pushed": 0,
        "generation_failed": 0,
        "escalated": 0,
        "review_ran": False,
        "approved": None,
        "skipped_unsupported_repo": 0,
        "archived_pr_gone": 0,
    }

    rows = _candidates()
    if not rows:
        return result

    # Attempt-cap self-heal: any row already at the cap escalates immediately —
    # even one stranded by a crash between increment and escalation.
    live = []
    for row in rows:
        if int(row["metadata"].get("fix_attempts") or 0) >= _MAX_ATTEMPTS:
            _escalate(row, f"attempt cap reached ({_MAX_ATTEMPTS})")
            result["escalated"] += 1
        else:
            live.append(row)

    # ONE PR per cycle, and only on the repo the write token covers (REPO_FULL);
    # other repos are review-only by governance — reported, never silently eaten.
    target = None
    for row in live:
        repo = row["metadata"].get("repo") or ""
        if repo != REPO_FULL:
            result["skipped_unsupported_repo"] += 1
            continue
        target = (repo, int(row["metadata"]["pr_number"]))
        break
    if not target:
        return result
    repo, pr_number = target
    group = [r for r in live if (r["metadata"].get("repo"), int(r["metadata"]["pr_number"])) == (repo, pr_number)]
    result["prs_processed"], result["pr_number"] = 1, pr_number

    pr = _get_pr(repo, pr_number)
    if not pr:
        logger.warning("review_fix: PR #%s unreadable — leaving rows untouched (blip rule)", pr_number)
        return result
    if pr.get("merged_at") or pr.get("state") != "open":
        why = "pr_merged_before_fix" if pr.get("merged_at") else "pr_closed_before_fix"
        for row in group:
            _stamp(row["id"], {"archived_reason": why}, new_status="archived")
            result["archived_pr_gone"] += 1
        return result

    head_ref = (pr.get("head") or {}).get("ref") or ""
    # HARD GUARD (task #5934): this mechanism may only ever write to a PR's head
    # branch. main/master or a missing ref is refused outright, whatever GitHub says.
    if not head_ref or head_ref in ("main", "master"):
        logger.error("review_fix: refusing PR #%s — head ref %r is not a writable PR branch", pr_number, head_ref)
        return result

    try:
        diff_text = _fetch_pr_diff(repo, pr_number)
    except Exception as e:
        logger.warning("review_fix: diff fetch failed for PR #%s: %s — leaving rows untouched", pr_number, e)
        return result

    pushed_rows = []
    for row in group[:max_findings]:
        md = row["metadata"]
        attempts = int(md.get("fix_attempts") or 0)
        path = _locate_evidence_file(diff_text, md.get("evidence") or "")
        if not path:
            _escalate(row, "evidence line not locatable in the PR diff")
            result["escalated"] += 1
            continue
        content, blob_sha = _get_file_at_ref(repo, path, head_ref)
        if content is None:
            logger.warning("review_fix: could not read %s@%s — leaving row untouched", path, head_ref)
            continue
        fix, reason = _generate_find_replace(md, content)
        if not fix:
            attempts += 1
            _stamp(row["id"], {"fix_attempts": attempts, "last_fix_error": reason})
            result["generation_failed"] += 1
            if attempts >= _MAX_ATTEMPTS:
                row["metadata"]["fix_attempts"] = attempts
                _escalate(row, f"fix generation failed: {reason}")
                result["escalated"] += 1
            continue
        find, replace = fix
        new_content = content.replace(find, replace, 1)
        commit_sha = _put_file(
            repo,
            path,
            head_ref,
            new_content,
            blob_sha,
            f"fix(review): PR #{pr_number} attempt {attempts + 1} — {md.get('finding_title')}\n\n"
            f"[review-fix] proposal #{row['id']} (#5934 loop; evidence-grounded find/replace)",
        )
        if not commit_sha:
            attempts += 1
            _stamp(row["id"], {"fix_attempts": attempts, "last_fix_error": "contents PUT failed"})
            if attempts >= _MAX_ATTEMPTS:
                row["metadata"]["fix_attempts"] = attempts
                _escalate(row, "could not commit the fix to the PR branch")
                result["escalated"] += 1
            continue
        attempts += 1
        _stamp(
            row["id"],
            {
                "fix_attempts": attempts,
                "fix_commit_sha": commit_sha,
                "fix_file": path,
                "last_fix_error": None,
            },
        )
        row["metadata"]["fix_attempts"] = attempts
        pushed_rows.append(row)
        result["fixes_pushed"] += 1

    if not pushed_rows:
        return result

    ran, approved = _run_review(pr_number, repo)
    result["review_ran"], result["approved"] = ran, (approved if ran else None)

    if ran and approved:
        # Converge into the ONE completion authority: pr_open + the ship_as_pr metadata
        # shape, so the deliberate human merge settles these rows and a close reopens
        # them. NEVER merged from here — the governance gate stays exactly as-is.
        for row in pushed_rows:
            _stamp(
                row["id"],
                {
                    "pr_number": pr_number,
                    "pr_url": f"https://github.com/{repo}/pull/{pr_number}",
                    "branch": head_ref,
                    "apply_mode": "review_fix",
                    "code_applied": False,
                },
                new_status="pr_open",
            )
    else:
        # Fix did not clear the review (or the review could not run — stored verdict is
        # then still the old REQUEST CHANGES, the safe direction). The attempt is spent;
        # rows at the cap escalate NOW rather than idling a cycle.
        for row in pushed_rows:
            if int(row["metadata"].get("fix_attempts") or 0) >= _MAX_ATTEMPTS:
                _escalate(row, "fix pushed but the re-review did not approve")
                result["escalated"] += 1
    return result
