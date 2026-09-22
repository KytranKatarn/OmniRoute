"""#6819 — a human affordance to clear a FALSE review finding.

THE GAP THIS CLOSES. Before this, a human facing a wrong REQUEST CHANGES had exactly three
options: re-review and hope (nondeterministic — 2 for 2 flipped to APPROVE with zero code change
on 2026-09-21, which is luck, not a process); press "send back to coders", which files a repair
proposal for a defect that does not exist; or nothing. There was no way to say "this observation
is factually wrong, here is why".

THE PRINCIPLE — CORRECT THE INPUT, NEVER OVERRIDE THE OUTPUT.
A dismissal removes ONE false finding from the set the verdict is computed over, and the verdict
is then recomputed from what remains. It is NOT a merge bypass:

  * if a real blocking finding remains, the PR STAYS blocked;
  * `verdict_refusal` and the tier ceiling are untouched — "nothing merges on a non-approval"
    (decision #953, PR #2722) still binds. The verdict legitimately CHANGED; nothing skipped it;
  * the relaxation reuses `_apply_severity_gate`, the same post-guard the single-pass and merged
    paths use, so there is ONE definition of "does anything blocking remain".

WHY A HUMAN MAY DO THIS AND THE REVIEWER MAY NOT: the reviewer clearing its own finding is
self-certification. A human asserting "I read the code and this claim is false" is evidence, and
the rationale is stored so the assertion is auditable rather than a silent click.

SECOND PAYOFF: every dismissal is a LABELLED false-positive example. #6799/#6800 want to suppress
these automatically and have no corpus. Four shapes are known by hand — a prose-answering pass,
a cross-file move read as a deletion, docs prose reviewed as code, and self-refuting evidence
(now GATE 5, #3425). A fifth arrived on PR #3418: `like = f"%{q}%"` passed as a BOUND PARAMETER,
flagged as SQL injection.
"""

from __future__ import annotations

import hashlib
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

_FINDING_LINE_RE = re.compile(r"^\s*[-*]\s*\[\s*(CRITICAL|WARNING|INFO)\s*\]", re.I)


def finding_fingerprint(finding_line: str) -> str:
    """Stable id for a finding, computed on NORMALISED text.

    Normalised so re-review wording drift does not orphan a dismissal: the severity tag is
    stripped (the same finding may come back WARNING or INFO), case is folded and whitespace
    collapsed. Deliberately NOT semantic — two genuinely different findings must never collide,
    so everything after the severity tag is significant.
    """
    text = (finding_line or "").strip()
    text = re.sub(r"^\s*[-*]\s*\[\s*(?:CRITICAL|WARNING|INFO)\s*\]\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def dismiss_finding(
    pr_number: int,
    repo: str,
    finding_line: str,
    rationale: str,
    dismissed_by: str,
    head_sha: str = None,
) -> dict:
    """Record ONE finding as a false positive. Returns {ok, fingerprint, error}.

    Refuses a blank rationale IN CODE as well as in the CHECK constraint: a silent dismissal is
    the failure mode this exists to prevent, and the caller deserves a real error rather than an
    IntegrityError. Re-dismissing the same finding at the same head sha is idempotent.
    """
    if not finding_line or not finding_line.strip():
        return {"ok": False, "error": "no finding supplied"}
    if not rationale or not rationale.strip():
        return {"ok": False, "error": "a written rationale is required — silent dismissal is not allowed"}
    if not dismissed_by or not dismissed_by.strip():
        return {"ok": False, "error": "dismissal must be attributed to a user"}
    fp = finding_fingerprint(finding_line)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO pr_review_finding_dismissals
                       (pr_number, repo, finding_fp, finding_text, head_sha, rationale, dismissed_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pr_number, repo, finding_fp, head_sha)
                DO UPDATE SET rationale = EXCLUDED.rationale,
                              dismissed_by = EXCLUDED.dismissed_by,
                              revoked_at = NULL,
                              revoked_by = NULL
                RETURNING id
                """,
                (pr_number, repo, fp, finding_line.strip()[:4000], head_sha, rationale.strip(), dismissed_by.strip()),
            )
            row = cur.fetchone()
        logger.warning(
            "[Repair Bay] finding dismissed as false positive — PR #%s (%s) by %s: %s",
            pr_number, repo, dismissed_by, rationale.strip()[:200],
        )
        return {"ok": True, "fingerprint": fp, "id": (row or {}).get("id")}
    except Exception as exc:  # noqa: BLE001
        logger.error("[Repair Bay] dismiss_finding failed for PR #%s: %s", pr_number, exc)
        return {"ok": False, "error": str(exc)}


def active_dismissals(pr_number: int, repo: str, head_sha: str = None) -> dict:
    """{fingerprint: {rationale, dismissed_by}} for live dismissals at this head sha.

    FAIL-CLOSED: any error returns EMPTY, so a DB problem leaves the verdict untouched and the
    PR blocked. The unsafe direction here is inventing a dismissal, never missing one.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT finding_fp, rationale, dismissed_by
                  FROM pr_review_finding_dismissals
                 WHERE pr_number = %s AND repo = %s
                   AND revoked_at IS NULL
                   AND (head_sha IS NOT DISTINCT FROM %s)
                """,
                (pr_number, repo, head_sha),
            )
            return {
                r["finding_fp"]: {"rationale": r["rationale"], "dismissed_by": r["dismissed_by"]}
                for r in (cur.fetchall() or [])
            }
    except Exception as exc:  # noqa: BLE001
        logger.error("[Repair Bay] active_dismissals failed for PR #%s: %s", pr_number, exc)
        return {}


def apply_dismissals(summary: str, dismissals: dict) -> tuple:
    """Rewrite dismissed findings to [INFO] and recompute the verdict. -> (summary, n_applied).

    The finding is NOT deleted. It stays visible, demoted, annotated with who dismissed it and
    why — a reader must be able to see that a human overruled an observation, not that the
    observation never existed. Then `_apply_severity_gate` decides whether anything blocking
    remains: ONE definition, shared with the single-pass and merged paths.
    """
    if not summary or not dismissals:
        return summary, 0
    from tools.repair_bay.services.pr_diff_analyzer import _apply_severity_gate

    out, applied = [], 0
    for line in summary.splitlines():
        if _FINDING_LINE_RE.match(line):
            hit = dismissals.get(finding_fingerprint(line))
            if hit:
                who = hit.get("dismissed_by") or "unknown"
                why = (hit.get("rationale") or "").strip()
                line = re.sub(
                    r"\[\s*(?:CRITICAL|WARNING)\s*\]",
                    "[INFO]",
                    line,
                    count=1,
                    flags=re.I,
                )
                line = f"{line}  — ⚠ DISMISSED as a false positive by {who}: {why}"
                applied += 1
        out.append(line)
    if not applied:
        return summary, 0
    text = "\n".join(out)
    text = _apply_severity_gate(text)
    text += f"\n\n[dismissals] {applied} finding(s) marked false-positive by a human; verdict recomputed from what remained (#6819)."
    return text, applied


def all_active_dismissals() -> dict:
    """{(pr_number, repo, head_sha): {fp: {...}}} for every live dismissal.

    ONE query for a whole listing rather than N+1: this table is HUMAN-generated, so it stays
    small by construction. FAIL-CLOSED to empty — a DB problem must leave every verdict exactly
    as the reviewer left it.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT pr_number, repo, head_sha, finding_fp, rationale, dismissed_by
                  FROM pr_review_finding_dismissals
                 WHERE revoked_at IS NULL
                """
            )
            out = {}
            for r in cur.fetchall() or []:
                key = (r["pr_number"], r["repo"], r["head_sha"])
                out.setdefault(key, {})[r["finding_fp"]] = {
                    "rationale": r["rationale"],
                    "dismissed_by": r["dismissed_by"],
                }
            return out
    except Exception as exc:  # noqa: BLE001
        logger.error("[Repair Bay] all_active_dismissals failed: %s", exc)
        return {}


def dismissals_for(cache: dict, pr_number: int, repo: str, head_sha: str = None) -> dict:
    """Pick one PR's dismissals out of an `all_active_dismissals()` cache.

    ⚠️ Matches the recorded head_sha, and ALSO accepts rows stored with head_sha NULL (dismissed
    before a sha was known). It does NOT fall back to a DIFFERENT sha: that is the whole point of
    scoping — a judgement about specific code must not silently cover changed code.
    """
    merged = {}
    merged.update(cache.get((pr_number, repo, None)) or {})
    if head_sha:
        merged.update(cache.get((pr_number, repo, head_sha)) or {})
    return merged
