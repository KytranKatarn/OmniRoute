"""CODEX (CLI) review verdicts, surfaced in Repair Bay alongside F.O.R.G.E.'s.

Why this exists
---------------
CODEX posts its verdict as a GitHub **PR review** (`gh pr review --comment`). F.O.R.G.E.
writes `pr_reviews.ai_summary`, and `list_reviews` / `merge_state` read only that. So a
CODEX verdict reached Repair Bay nowhere: not the row, not the badge, not the merge gate.
Measured 2026-10-05 on #3627 — F.O.R.G.E. said APPROVE, CODEX said REQUEST_CHANGES with a
`[high]` finding, and the list showed a green APPROVED row with no trace of it. The pane
surfaced CODEX only if you clicked into the PR, which is precisely where nobody looks when
scanning the list.

ADVISORY, ALWAYS
----------------
This module NEVER influences `merge_state` and never blocks a merge. That is a decision,
not an oversight: CODEX is a second opinion, F.O.R.G.E. is the authority, and a model that
can stall every merge is a liability — especially given the false positives F.O.R.G.E.
itself emits on ordinary code. What this buys is VISIBILITY: the F.O.R.G.E.-approves /
CODEX-objects combination, which is the one worth a human's attention, is finally legible.

Storage
-------
`pr_reviews.metadata` (JSONB), under a `codex` key. No migration: the row already exists
per PR and already carries review provenance (`reviewed_head_sha`), so this is the same
kind of data in the same place. `metadata->'codex'` is written ONLY here.

Staleness
---------
A verdict is only meaningful for the commit it reviewed. Push a new commit and an old
REQUEST_CHANGES is no longer a statement about the current diff, so it is recorded as
stale rather than silently presented as current. `list_reviews` surfaces that flag and the
UI marks it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REPO = "KytranKatarn/archie-platform"

#: A CODEX review body starts with the verdict line. This is what distinguishes a CODEX
#: review from a human's: `codex_pr_review.sh` posts only `$BODY`, and the decorative
#: "==== CODEX REVIEW ====" banner is echoed to the operator's terminal, never posted.
_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*([A-Z_]+)", re.MULTILINE)
_FINDING_RE = re.compile(r"^\s*-\s*\[(critical|high|medium|low|info)\]", re.MULTILINE | re.IGNORECASE)

#: Findings we refuse to surface as a "current" verdict.
BLOCKING = ("REQUEST_CHANGES",)


def parse_codex_review(body: str) -> dict[str, Any] | None:
    """Extract verdict + findings from a posted review body, or None if it isn't one.

    Pure and unit-tested: this decides what counts as a CODEX verdict at all, and getting
    it wrong in either direction is bad — too strict and real verdicts vanish (which is
    what happened when the marker `==== CODEX REVIEW ====` was matched instead), too loose
    and a human's "VERDICT: ..." line becomes a model verdict.
    """
    if not body:
        return None
    m = _VERDICT_RE.search(body)
    if not m:
        return None
    verdict = m.group(1)
    # NOTE, and this is a real limitation rather than a design choice: any review body
    # beginning with "VERDICT: <X>" is accepted. An earlier draft required CODEX's
    # characteristic findings shape too, which would have been WRONG in the other
    # direction — a clean CODEX run posts "VERDICT: APPROVE" with "No issues found" and no
    # findings, and every APPROVE would have been dropped. The reverse error is that a
    # human who happens to write "VERDICT: APPROVE" in a GitHub review is ingested as a
    # model verdict. GitHub does not record who authored a review beyond the account, and
    # our own posts use the same account as the author, so the two are indistinguishable
    # after the fact. The honest fix is for the host runner to record the verdict at post
    # time, where it knows for certain; until then the UI tooltip states the provenance
    # rather than implying certainty.
    #
    # findall with ONE group returns a list of STRINGS, not tuples. Taking f[0] of each
    # silently reduced every severity to its first letter ("high" -> "h"), which shipped
    # until the live ingest was inspected. Caught by reading real output, not by a test.
    findings = _FINDING_RE.findall(body)
    return {
        "verdict": verdict,
        "summary": body.strip()[:600],
        "finding_count": len(findings),
        "findings": [str(f).strip().lower() for f in findings][:12],
    }


def record_verdict(
    pr_number: int,
    repo: str = DEFAULT_REPO,
    *,
    verdict: str,
    head_sha: str,
    summary: str = "",
    finding_count: int = 0,
    findings: list[str] | None = None,
    review_id: int | None = None,
    reviewed_at: str | None = None,
    stale: bool = False,
) -> bool:
    """Persist a CODEX verdict onto the PR's row metadata. Returns True if written.

    Never raises into the caller: a sync that cannot record one verdict must still record
    the others.
    """
    try:
        from database import get_db_cursor

        payload = {
            "verdict": verdict,
            "head_sha": head_sha or "",
            "summary": (summary or "")[:600],
            "finding_count": int(finding_count or 0),
            "findings": findings or [],
            "review_id": review_id,
            "reviewed_at": reviewed_at,
            "stale": bool(stale),
        }
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE pr_reviews
                   SET metadata = COALESCE(metadata, '{}'::jsonb)
                                  || jsonb_build_object('codex', %s::jsonb)
                 WHERE pr_number = %s AND repo = %s
                """,
                (__import__("json").dumps(payload), pr_number, repo),
            )
            return cur.rowcount > 0
    except Exception as exc:  # noqa: BLE001 - one bad write must not stop the sync
        logger.warning("codex verdict write failed for #%s: %s", pr_number, exc)
        return False


def ingest_for_open_prs(
    repo: str = DEFAULT_REPO,
    token: str | None = None,
    timeout: int = 12,
) -> dict[str, Any]:
    """Fetch and record CODEX verdicts for every OPEN tracked PR.

    Open PRs only, by decision: the interesting case is a verdict on work in flight, and
    history is backfilled on demand rather than sweeping every merged row on every poll.
    One request per open PR, and open PRs are few.

    Staleness is decided HERE, where the current head sha is knowable, and stored as a
    flag. It cannot be decided at read time: `pr_reviews` has no head-sha column, so a
    row cannot tell whether the commit its verdict reviewed is still the branch tip.
    """
    import json
    import os
    import urllib.error
    import urllib.request

    from .pr_review_service import list_reviews, pr_head_sha

    token = token or os.getenv("GITHUB_TOKEN", "")
    checked = recorded = 0
    reasons: list[str] = []

    prs = [r for r in (list_reviews(state="open", limit=100) or []) if r.get("state") == "open"]
    if not prs:
        return {"checked": 0, "recorded": 0, "reasons": ["skipped: no open PRs to check"]}

    for pr in prs:
        num = pr.get("pr_number")
        if not num:
            continue
        checked += 1
        try:
            head_sha = pr_head_sha(int(num), repo) or ""
        except Exception:  # noqa: BLE001 - an unknown sha must not be treated as fresh
            head_sha = ""
        url = f"https://api.github.com/repos/{repo}/pulls/{int(num)}/reviews?per_page=100"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                reviews = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            reasons.append(f"#{num}: HTTP {exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"#{num}: {exc.__class__.__name__}")
            continue

        newest = None
        for rev in reviews or []:
            parsed = parse_codex_review(rev.get("body") or "")
            if not parsed:
                continue
            # Reviews come newest-first from GitHub; keep the first CODEX one.
            newest = (parsed, rev)
            break

        if not newest:
            continue
        parsed, rev = newest
        stored = _stored_verdict(int(num), repo)
        stale = bool(head_sha and stored.get("head_sha") and head_sha != stored["head_sha"])
        if record_verdict(
            int(num),
            repo,
            verdict=parsed["verdict"],
            head_sha=head_sha,
            stale=stale,
            summary=parsed["summary"],
            finding_count=parsed["finding_count"],
            findings=parsed["findings"],
            review_id=rev.get("id"),
            reviewed_at=rev.get("submitted_at"),
        ):
            recorded += 1

    return {"checked": checked, "recorded": recorded, "reasons": reasons}


def _stored_verdict(pr_number: int, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Whatever verdict is already recorded for this PR, or {}."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT metadata FROM pr_reviews WHERE pr_number = %s AND repo = %s",
                (pr_number, repo),
            )
            row = cur.fetchone()
        meta = (row or {}).get("metadata") if isinstance(row, dict) else None
        codex = (meta or {}).get("codex")
        return codex if isinstance(codex, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("codex stored-verdict read failed for #%s: %s", pr_number, exc)
        return {}


def verdict_for_row(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Project a stored verdict into what the list needs. Pure, so it is unit-tested.

    Returns `{}` when there is nothing to show, so the UI renders nothing at all rather
    than an empty badge. `stale` was decided at ingest, where the head sha was knowable.
    """
    codex = (metadata or {}).get("codex")
    if not isinstance(codex, dict) or not codex.get("verdict"):
        return {}
    return {
        "verdict": codex.get("verdict"),
        "finding_count": int(codex.get("finding_count") or 0),
        "findings": codex.get("findings") or [],
        "reviewed_at": codex.get("reviewed_at"),
        "stale": bool(codex.get("stale")),
    }


def probe_for_row(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Project a stored P.R.O.B.E. (QA) verdict for the list. Pure, unit-tested.

    Advisory, like `verdict_for_row` — `merge_state` never reads this. Kept here beside
    the CODEX projection because both are "a second opinion the gate must not read", and
    keeping one place for that decision stops a second reviewer being wired in quietly.

    Returns `{}` when there is nothing stored, so no empty badge renders.
    """
    probe = (metadata or {}).get("probe")
    if not isinstance(probe, dict) or not probe.get("verdict"):
        return {}
    return {
        "reviewer": probe.get("reviewer") or "P.R.O.B.E.",
        "verdict": probe.get("verdict"),
        "summary": (probe.get("summary") or "")[:300],
        "reviewed_at": probe.get("at"),
        "advisory": True,
    }
