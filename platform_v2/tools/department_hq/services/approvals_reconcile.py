"""Close approval rows that the world has already made moot (#5862).

THE BUG: a `pr_merge` approval is raised while its PR is open, the PR then merges by
some OTHER route — the `/merge-pr` skill, `gh pr merge`, the GitHub UI, or an
authenticated `human_override` — and nothing ever closes the queue row. It sits
`pending` forever. Measured 2026-08-20: **4 of 4** pending merge approvals were for
PRs already merged, one of them raised 2 minutes before its own PR merged.

This is the missing half of #5419. That task stopped the escalation from *notifying*
about an already-merged PR, and `approvals_pending` already stops a stale row from
*blocking* the deploy gate — but neither closes the row, so the DHQ Approvals tab kept
showing merge requests that Repair Bay (correctly) did not.

WHY A SWEEP AND NOT ONLY A HOOK AT THE MERGE: `merge_pr` closes the row on the fast
path, but merges that never travel through `merge_pr` at all (the GitHub web UI, a raw
`gh pr merge`) leave nothing to hook. The sweep is the backstop that makes the
invariant hold regardless of how the PR closed.

⚠️ FAIL-SAFE, NOT FAIL-OPEN. `pr_is_open` returns None when GitHub cannot be read, and
that is treated as "still open" — the row is LEFT ALONE. Cancelling an approval because
an API call failed would silently discard a real, actionable merge request; leaving one
stale row costs a glance. Those are not symmetric.
"""

import logging

logger = logging.getLogger(__name__)

# The status a moot approval lands in. Already an in-use value on this table, and
# honest: the approval was not denied on its merits, it stopped being a question.
STALE_STATUS = "cancelled"
STALE_REASON = "PR already merged/closed out-of-band — approval no longer actionable"

# One GitHub call per row, so bound the blast radius. The real population is tiny (4
# pending on 2026-08-20; 87 pr_merge rows in 30 days), but an unbounded loop over a
# pathological backlog would burn write-guard quota. Capping is LOGGED, never silent —
# a truncated sweep that reports success reads as "all clean" when it is not.
MAX_SWEEP = 25


def _pending_pr_merge_rows(cur):
    cur.execute(
        """
        SELECT id,
               NULLIF(action_data->>'pr_number','')::int AS pr_number,
               NULLIF(action_data->>'repo','')          AS repo
          FROM autonomy_approval_queue
         WHERE action_type = 'pr_merge'
           AND status = 'pending'
           AND executed_at IS NULL
         ORDER BY id
        """
    )
    out = []
    for row in cur.fetchall():
        get = row.get if isinstance(row, dict) else None
        out.append(
            {
                "id": row["id"] if get else row[0],
                "pr_number": row["pr_number"] if get else row[1],
                "repo": row["repo"] if get else row[2],
            }
        )
    return out


def close_stale_pr_merge_approvals(dry_run=False):
    """Cancel pending `pr_merge` approvals whose PR is no longer open on GitHub.

    Returns {"checked": n, "closed": [ids], "left_open": [ids], "undetermined": [ids]}.
    Never raises — this runs inside a scheduled sync whose other work must not be lost
    to a reconciliation failure.
    """
    result = {"checked": 0, "closed": [], "left_open": [], "undetermined": []}
    try:
        from database import get_db_cursor

        from tools.repair_bay.services.github_service import pr_is_open
    except Exception as exc:  # noqa: BLE001
        logger.warning("approvals reconcile unavailable: %s", exc)
        return result

    try:
        with get_db_cursor(commit=not dry_run) as (_conn, cur):
            rows = _pending_pr_merge_rows(cur)
            if len(rows) > MAX_SWEEP:
                logger.warning(
                    "approvals reconcile: %d pending pr_merge rows exceeds MAX_SWEEP=%d — "
                    "checking the oldest %d only, %d deferred to the next run",
                    len(rows),
                    MAX_SWEEP,
                    MAX_SWEEP,
                    len(rows) - MAX_SWEEP,
                )
                result["deferred"] = len(rows) - MAX_SWEEP
                rows = rows[:MAX_SWEEP]
            result["checked"] = len(rows)

            for row in rows:
                pr_number, approval_id = row["pr_number"], row["id"]
                if not pr_number:
                    # No PR number to check against — not ours to judge.
                    result["undetermined"].append(approval_id)
                    continue

                try:
                    still_open = pr_is_open(pr_number, row.get("repo"))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("pr_is_open(%s) failed: %s", pr_number, exc)
                    still_open = None

                if still_open is None:
                    # Unreadable => assume open. See the fail-safe note in the docstring.
                    result["undetermined"].append(approval_id)
                    continue
                if still_open:
                    result["left_open"].append(approval_id)
                    continue

                if not dry_run:
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                           SET status = %s,
                               rejected_reason = %s,
                               updated_at = now()
                         WHERE id = %s
                           AND status = 'pending'
                           AND executed_at IS NULL
                        RETURNING id
                        """,
                        (STALE_STATUS, STALE_REASON, approval_id),
                    )
                    # The re-checked WHERE means a row approved a millisecond ago is not
                    # clobbered; if it matched nothing, do not report it as closed.
                    if not cur.fetchone():
                        result["left_open"].append(approval_id)
                        continue
                result["closed"].append(approval_id)

        if result["closed"]:
            # The verb must match what actually happened. A dry run that logs "closed"
            # tells a future operator rows were cleared when nothing was written — the
            # same status-misreports-reality failure this file exists to fix.
            logger.info(
                "approvals reconcile: %s %d stale pr_merge approval(s): %s",
                "would close" if dry_run else "closed",
                len(result["closed"]),
                result["closed"],
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("close_stale_pr_merge_approvals failed: %s", exc)

    return result


def close_pr_merge_approvals_for(pr_number, repo=None):
    """Close any pending approval for a PR that has JUST been merged.

    Called from the merge choke point so the common case closes instantly instead of
    waiting for the 4-hour sweep. Trusts the caller's merge result rather than spending
    an API call to re-ask GitHub what it just told us.

    Returns the number of rows closed. Never raises — a bookkeeping failure must never
    turn a SUCCESSFUL merge into an error.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            # repo is matched only when supplied AND present on the row: older rows
            # predate the repo key, and a NULL there must not stop the match.
            cur.execute(
                """
                UPDATE autonomy_approval_queue
                   SET status = %s,
                       rejected_reason = %s,
                       updated_at = now()
                 WHERE action_type = 'pr_merge'
                   AND status = 'pending'
                   AND executed_at IS NULL
                   AND NULLIF(action_data->>'pr_number','')::int = %s
                   AND (%s IS NULL
                        OR NULLIF(action_data->>'repo','') IS NULL
                        OR action_data->>'repo' = %s)
                RETURNING id
                """,
                (STALE_STATUS, STALE_REASON, int(pr_number), repo, repo),
            )
            closed = cur.fetchall() or []
            if closed:
                logger.info("closed %d pending approval(s) for merged PR #%s", len(closed), pr_number)
            return len(closed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not close approvals for merged PR #%s: %s", pr_number, exc)
        return 0
