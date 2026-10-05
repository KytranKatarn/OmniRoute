"""Stale verdicts — which stored reviews no longer describe the branch tip.

Why this exists
---------------
A review is a statement about a *commit*. Push a new one and every verdict on that PR
describes code that is no longer there. The merge gate already refuses a stale F.O.R.G.E.
approval (`github_service` compares `metadata.reviewed_head_sha` to the live head), so the
gate is safe — but nothing *told* you. There was no re-review trigger anywhere: the CODEX
and P.R.O.B.E. verdicts added in #3628 were not part of any staleness check at all, and
F.O.R.G.E. only became visibly stale at the moment you tried to merge.

So this DETECTS AND SURFACES. It deliberately does not re-review:

  * every push to a WIP branch would fire a model review, burning budget and flooding the
    dispatch queue for work nobody intends to land;
  * auto-firing also removes the human's moment of judgement — "this push is a rebase, the
    verdict still stands" is a decision, not a lookup;
  * the gate already refuses a stale merge, so the failure mode being prevented is
    "merge something unreviewed", and that is already prevented.

This module is therefore a *loud, deduplicated nudge*, not an automation.

Sourcing the head sha without extra API calls
---------------------------------------------
`pr_head_sha()` is one GitHub request PER PR — unaffordable for a 200-row list render. The
poll already fetches each PR's full object, so it records `metadata.head_sha` on every
pass, and the JSONB `||` merge in the poll is right-biased PER KEY. That means adding the
head sha refreshes exactly one key and leaves `reviewed_head_sha`, `codex` and `probe`
untouched. Every consumer here reads that stored value: zero additional GitHub calls.

"Staleness unprovable" is NOT stale
-----------------------------------
The merge gate's own rule is: no `reviewed_head_sha` → "staleness unprovable" → ALLOW. This
module matches that. Most of the 3,370 historical rows predate SHA stamping, so treating
"unprovable" as stale would report the entire archive as broken on the first run — noise
that trains people to ignore the signal. Unprovable is reported separately, as a weaker
signal, and never counted as a failure.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Which reviewers have a verdict that can go stale, and where each one's reviewed sha lives.
#: Mirrors the storage decided in #3628: F.O.R.G.E. owns `reviewed_head_sha`, the two
#: advisory reviewers each keep their own `head_sha` inside their own metadata key.
REVIEWER_SHAS = {
    "forge": ("reviewed_head_sha",),
    "codex": ("codex", "head_sha"),
    "probe": ("probe", "head_sha"),
}

#: Short labels for the UI/notification.
REVIEWER_LABELS = {
    "forge": "F.O.R.G.E.",
    "codex": "CODEX",
    "probe": "P.R.O.B.E.",
}


def _has_verdict(meta: dict[str, Any], path: tuple[str, ...]) -> bool:
    """Does this reviewer have a stored verdict at all?

    `path` is the container path to the verdict, i.e. REVIEWER_SHAS[r] minus the trailing
    sha key. F.O.R.G.E.'s verdict is the presence of `reviewed_head_sha` itself, so its
    container is the metadata root and a missing sha genuinely means "no verdict".
    """
    node: Any = meta
    for part in path:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return False
    if isinstance(node, dict):
        return bool(node.get("verdict"))
    # Present but unreadable (a list, an int, a string where a verdict object belongs).
    # Count it as a verdict we cannot date: surfacing beats hiding, and `unproven` is not
    # actionable, so this cannot turn a corrupt row into a notification.
    return bool(node)


def staleness_for(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Decide which stored verdicts no longer match the branch tip. Pure, unit-tested.

    Returns:
        head       the sha the poll last saw (empty if never polled)
        stale      reviewer keys whose verdict covers a DIFFERENT commit
        unproven   reviewer keys with a verdict but no recorded sha to compare
        current    reviewer keys whose verdict still matches the tip
    """
    meta = metadata if isinstance(metadata, dict) else {}
    head = meta.get("head_sha") or ""
    out: dict[str, Any] = {"head": head, "stale": [], "unproven": [], "current": []}

    for reviewer, path in REVIEWER_SHAS.items():
        node: Any = meta
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if node is None:
            # The sha is missing. That is NOT the same as the reviewer having no opinion:
            # for the two advisory reviewers the sha lives INSIDE their verdict, so a
            # verdict stored without it means "reviewed, sha not recorded" — unprovable,
            # and it must be reported as such. Walking the path alone cannot tell the two
            # apart, so ask whether a verdict exists before deciding.
            if _has_verdict(meta, path[:-1]):
                out["unproven"].append(reviewer)
            continue  # otherwise: no verdict from this reviewer at all
        reviewed = node if isinstance(node, str) else ""
        if not reviewed:
            out["unproven"].append(reviewer)
        elif not head:
            # Cannot compare without a polled head. Not stale — unprovable, same as the gate.
            out["unproven"].append(reviewer)
        elif reviewed != head:
            out["stale"].append(reviewer)
        else:
            out["current"].append(reviewer)
    return out


def is_actionable(staleness: dict[str, Any]) -> bool:
    """True only when a verdict positively contradicts the tip.

    `unproven` is deliberately excluded: it is the state of every legacy row, and counting
    it would make the first run report the whole archive.
    """
    return bool(staleness.get("stale"))


def describe(staleness: dict[str, Any], pr_number: int | None = None) -> str:
    """One-line human summary for a notification."""
    label = f"PR #{pr_number}" if pr_number else "PR"
    if staleness.get("stale"):
        who = ", ".join(REVIEWER_LABELS.get(r, r) for r in staleness["stale"])
        return (
            f"{label}: {who} verdict(s) cover an OLDER commit — the branch has moved on. " f"Re-review before merging."
        )
    if staleness.get("unproven"):
        who = ", ".join(REVIEWER_LABELS.get(r, r) for r in staleness["unproven"])
        return f"{label}: {who} verdict(s) predate SHA stamping — staleness cannot be proven."
    return f"{label}: verdicts are current."


def find_stale_open_prs(limit: int = 100) -> dict[str, Any]:
    """Scan open PRs for stale verdicts, reporting each distinct (pr, head) once.

    Dedupe state lives in the row as `stale_notified_head`. Without it, a job running every
    30 minutes would re-file the same notification 48 times a day for one forgotten
    re-review — which is how a monitor becomes something people mute.

    The notification is re-armed only when the head moves, so a genuine new push alerts
    again while the same un-actioned state stays quiet.
    """
    from database import get_db_cursor

    checked = 0
    reported: list[dict[str, Any]] = []
    reasons: list[str] = []

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT pr_number, repo, title, metadata
                  FROM pr_reviews
                 WHERE state = 'open'
                 ORDER BY updated_at DESC
                 LIMIT %s
                """,
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("staleness scan failed: %s", exc)
        return {"checked": 0, "stale": 0, "reported": [], "reasons": [f"scan failed: {exc}"]}

    for row in rows:
        checked += 1
        st = staleness_for(row.get("metadata"))
        if not is_actionable(st):
            continue
        meta = row.get("metadata") or {}
        if meta.get("stale_notified_head") == st.get("head"):
            continue  # already reported for this exact head
        reported.append(
            {
                "pr_number": row.get("pr_number"),
                "title": (row.get("title") or "")[:80],
                "stale": list(st["stale"]),
                "head": st.get("head"),
                "summary": describe(st, row.get("pr_number")),
            }
        )

    for item in reported:
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """
                    UPDATE pr_reviews
                       SET metadata = COALESCE(metadata, '{}'::jsonb)
                                      || jsonb_build_object('stale_notified_head', %s::text)
                     WHERE pr_number = %s
                    """,
                    (item["head"] or "", item["pr_number"]),
                )
        except Exception as exc:  # noqa: BLE001 - dedupe bookkeeping must not break the scan
            reasons.append(f"#{item['pr_number']}: could not arm dedupe ({exc})")

    return {
        "checked": checked,
        "stale": len(reported),
        "reported": reported,
        "reasons": reasons,
    }


def format_alert_message(result: dict[str, Any]) -> str:
    """Notification body for a non-empty result."""
    reported = result.get("reported") or []
    if not reported:
        return "No stale verdicts found."
    lines = [
        f"{len(reported)} open PR(s) have a review verdict that no longer covers the branch tip.",
        "",
    ]
    for item in reported[:15]:
        lines.append(f"  - {item['summary']}")
        if item.get("title"):
            lines.append(f"      {item['title']}")
    if len(reported) > 15:
        lines.append(f"  ... and {len(reported) - 15} more")
    return "\n".join(lines)
