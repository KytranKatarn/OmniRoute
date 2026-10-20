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

ADVISORY 2026-10-05 → 2026-10-19, THEN REVERSED
------------------------------------------------
When this module shipped, the verdict was deliberately ADVISORY: `merge_state` never read
it and it could not block a merge. CODEX is a second opinion, F.O.R.G.E. was the
authority, and a model that can stall every merge is a liability — especially given the
false positives F.O.R.G.E. itself emits on ordinary code. What it bought was VISIBILITY:
the F.O.R.G.E.-approves / CODEX-objects combination, which is worth a human's attention,
became legible on the row instead of only inside the PR.

Then 2026-10-19 measured it on the open PRs and the ordering was wrong. F.O.R.G.E. had
approved #3921, #3927 and #3930 — each carrying a real defect, confirmed by reading the file
at the PR head — and the whole-diff CODEX review refused all three. The reviewer that found
the bugs was the one the gate could not see.

That same sweep also refused #3923, which reading the file disproved (the reviewer quoted
the REMOVED line as if it were the head). So this is not a reviewer that is always right,
and a refusal is a claim: see `codex_merge_refusal` for what it costs and the one command
that clears it.

So a *fresh* REQUEST_CHANGES from here now refuses a merge. `pr_review_service.
codex_merge_refusal` is the single definition; `merge_state` reads it for the row, both
attended merge routes read it for the refusal. An APPROVE changes nothing, and a verdict
marked `stale` — its `head_sha` is no longer the branch tip — never blocks, so nobody is
held behind a refusal that describes code they already replaced.

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

What makes that flag trustworthy is WHICH sha is stored. The verdict carries the commit the
CODEX review actually covers (`rev["commit_id"]`, where GitHub supplies it), NOT the branch
tip at poll time — the poll already writes the tip to `metadata->>'head_sha'`, and that
right-biased merge leaves this key alone. Two readers compare the pair:
`verdict_staleness.staleness_for` for the UI, and `pr_review_service.codex_merge_refusal`
for the merge gate. Storing the TIP here (which this did until 2026-10-19) made both
comparisons always-equal, so a verdict read as "current" forever — and the gate that now
reads this flag would have refused a merge permanently once a fix was pushed. See
`verdict_staleness` below, which decides the flag and is pure so it is unit-tested.
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


def verdict_staleness(rev: dict[str, Any], tip: str | None) -> tuple[str, bool]:
    """The sha this review covers, and whether the branch tip has moved past it. Pure.

    Returns ``(covered_sha, stale)``. The rule is deliberately asymmetric about what it
    cannot prove: with no review sha, or no tip, the answer is ``(tip, False)`` — "unproven
    is not stale", the same rule the merge gate uses for a missing `reviewed_head_sha`, so
    a GitHub response that omits `commit_id` cannot silently invalidate every verdict.

    Extracted from the ingest loop because it is the ONE definition two readers depend on —
    `verdict_staleness.staleness_for` for the UI, `codex_merge_refusal` for the merge gate
    — and the loop it came out of needs GitHub and a DB to reach, so the comparison had no
    test. It was wrong there, which is how the gate nearly shipped with an escape hatch
    that closed itself one poll later.
    """
    covered = str(rev.get("commit_id") or rev.get("head_sha") or tip or "")
    return covered, bool(tip and covered and tip != covered)


def codex_reviews(reviews: list[dict[str, Any]] | None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The CODEX reviews in a `/pulls/{n}/reviews` payload, OLDEST FIRST. Pure.

    Returns ``[(parsed_verdict, raw_review), ...]``, dropping non-CODEX reviews and
    anything unparseable. Sorted explicitly by ``(submitted_at, id)`` rather than trusting
    the response order: GitHub documents this endpoint as *chronological*, and the ingest
    this replaced assumed the opposite ("reviews come newest-first") and therefore pinned
    the oldest review on the PR forever — #3926's COMMENT outlived its APPROVE by three
    minutes and would have outlived it by every poll thereafter. The sort is the fix, and
    the ``id`` tiebreak keeps two reviews submitted in the same second ordered instead of
    arbitrary.
    """
    found: list[tuple[tuple[str, int], dict[str, Any], dict[str, Any]]] = []
    for rev in reviews or []:
        if not isinstance(rev, dict):
            continue
        parsed = parse_codex_review(rev.get("body") or "")
        if not parsed:
            continue
        try:
            review_id = int(rev.get("id") or 0)
        except (TypeError, ValueError):
            review_id = 0
        found.append(((str(rev.get("submitted_at") or ""), review_id), parsed, rev))
    found.sort(key=lambda item: item[0])
    return [(parsed, rev) for _key, parsed, rev in found]


def ingest_for_open_prs(
    repo: str = DEFAULT_REPO,
    token: str | None = None,
    timeout: int = 12,
) -> dict[str, Any]:
    """Fetch and record CODEX verdicts for every OPEN tracked PR.

    Open PRs only, by decision: the interesting case is a verdict on work in flight, and
    history is backfilled on demand rather than sweeping every merged row on every poll.
    One request per open PR, and open PRs are few.

    Staleness is decided HERE, where BOTH shas are in hand — the branch tip the poll
    recorded and the commit the review covers — and stored as a flag so `merge_state` never
    needs a GitHub call. It is re-decided on every tick, which is what lets a pushed fix
    clear it; the module docstring above says why the sha stored on the verdict has to be
    the reviewed commit for that to hold.
    """
    import json
    import os
    import urllib.error
    import urllib.request

    from .pr_review_service import list_reviews, pr_head_sha

    token = token or os.getenv("GITHUB_TOKEN", "")
    checked = recorded = 0
    reasons: list[str] = []

    prs = [
        r for r in (list_reviews(state="open", limit=100) or []) if r.get("state") == "open" and r.get("repo") == repo
    ]
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

        found = codex_reviews(reviews)
        if not found:
            continue
        # The LAST entry: GitHub returns reviews in CHRONOLOGICAL order, so the newest
        # CODEX review is the current verdict. Keeping the FIRST one — which this did until
        # 2026-10-19, on a comment that claimed newest-first — pinned the OLDEST review on
        # the PR forever: #3926 was COMMENTed and then APPROVEd three minutes later, and the
        # stored verdict stayed the COMMENT on every subsequent tick. Harmless while nothing
        # read it; a permanent false refusal once the gate does.
        parsed, rev = found[-1]
        # The sha the review COVERS, not the branch tip. `record_verdict` overwrites one
        # JSONB key on every tick, so storing the tip made `metadata->'codex'->>'head_sha'`
        # and the poll's `metadata->>'head_sha'` equal forever: `staleness_for` reported the
        # verdict as current after any push, and the `stale` flag oscillated (True for the
        # tick after a push, False from the next tick on). Measured 2026-10-19.
        covered_sha, stale = verdict_staleness(rev, head_sha)
        if record_verdict(
            int(num),
            repo,
            verdict=parsed["verdict"],
            head_sha=covered_sha,
            stale=stale,
            summary=parsed["summary"],
            finding_count=parsed["finding_count"],
            findings=parsed["findings"],
            review_id=rev.get("id"),
            reviewed_at=rev.get("submitted_at"),
        ):
            recorded += 1
            # EVERY CODEX review in the response, not just the current one: the corpus
            # (#5859) is an append-only history of who said what about which head, and a
            # review superseded inside one poll interval would otherwise be lost. The
            # dedup key keeps a re-reading poller from appending it twice per tick.
            for _parsed, _rev in found:
                _record_attempt(int(num), repo, _rev)

    return {"checked": checked, "recorded": recorded, "reasons": reasons}


def _record_attempt(pr_number: int, repo: str, rev: dict) -> None:
    """Append this post to ``forge_reviews`` as the ``codex`` writer.

    ``forge_reviews`` is the review corpus (#5859) and until now its ONLY writer was
    F.O.R.G.E.'s chunked path — the platform-side reviewer. The whole-diff CODEX verdict,
    which is what actually caught #3921/#3927/#3930, existed nowhere in the corpus: it was
    a GitHub comment and a `metadata->'codex'` blob. A corpus of "which reviewer said what
    about which head" cannot answer which reviewer is worth listening to when it omits the
    one that was.

    Deliberately NOT folded into ``record_verdict``: that one is a strict overwrite of a
    single field, this one is an append-only history, and a poller re-reads the same
    GitHub review every tick. ``dedup_key`` on the GitHub review id is what keeps the
    corpus a function of the code rather than of the cron interval.

    ``head_sha`` is taken from the review's own ``commit_id`` where GitHub supplies it:
    the corpus entry should describe the commit the reviewer actually read, not whatever
    the branch tip happened to be at poll time.
    """
    if rev.get("id") is None:
        return
    try:
        from .pr_review_service import record_review_attempt

        record_review_attempt(
            pr_number,
            summary=(rev.get("body") or "").strip(),
            repo=repo,
            head_sha=rev.get("commit_id") or rev.get("head_sha") or "",
            review_path="codex-whole-diff",
            review_source="codex",
            dedup_key=f"github-review:{rev['id']}",
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not stop the ingest
        logger.warning("codex attempt record failed for #%s: %s", pr_number, exc)


def verdict_for_row(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Project a stored verdict into what the list needs. Pure, so it is unit-tested.

    Returns `{}` when there is nothing to show, so the UI renders nothing at all rather
    than an empty badge. `stale` was decided at ingest, where the review's commit and the
    branch tip were both in hand (`verdict_staleness` above).
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

    Advisory: `merge_state` never reads this. Kept beside the CODEX projection because
    both are "a second opinion", and keeping one place for that decision stops a reviewer
    being wired into the gate quietly — which is what happened to CODEX, deliberately, on
    2026-10-19 (see the module docstring: a QA verdict is still not a code review).

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
