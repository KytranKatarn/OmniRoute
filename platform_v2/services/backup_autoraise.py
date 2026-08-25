"""Raise a `backup_before_deploy` approval when deploys are stuck ONLY on backup freshness.

## The gap this closes

The prerequisite machinery already existed and works: `backup_before_deploy` has an executor
that runs `create_backup_programmatic`, and it sorts FIRST in the Approvals tab
(`CATEGORY_PRIORITY = 10`). What was missing is a RE-RAISE.

`unsatisfied_prerequisites()` distinguishes three states, and only the third is a dead end:

    "a backup approval is still pending"              -> wait, one exists
    "the approved backup has not finished running yet" -> wait, it is running
    "no successful backup in the last Nh"             -> NOTHING will happen  <-- here

Measured 2026-08-25: 6 pending `deploy_approve` rows showed that third message, the last
successful backup was 8.7h old, and there were ZERO pending `backup_before_deploy` rows. The
operator saw a blocker with no remedy in the queue. The same shape had already cost 6 approved
deploys, which failed with "W.A.R.D.E.N. clearance denied: backup age 8.2h exceeds medium
limit of 6h" AFTER passing their sandbox gate 3/3 — approved work, sound work, dead on backup age.

## Why a job and not the GET

The Approvals tab computes these prerequisites on read. Raising an approval from a GET would
make a page refresh mutate the queue — and a bot, a second tab, or a browser preload would
each enqueue another. This runs from `approval_watchdog`, which already watches this queue.

## Safety

- Raises at most ONE row, and only when nothing is pending or in flight (`should_raise`).
- Requires a real blocked deploy to exist: no deploys waiting, no backup requested. It never
  manufactures work for an idle queue.
- Every uncertain input returns False. An unknown state must not enqueue.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The action_type the executor and the prerequisite ordering both already know.
BACKUP_ACTION = "backup_before_deploy"

# Categories whose blockage justifies taking a fresh restore point. These are exactly the
# ones `PREREQUISITES` gates behind backup_before_deploy.
_DEPLOY_LIKE = ("deploy_approve", "improvement_approve_red")


def should_raise(
    *,
    blocked_deploys: int,
    backup_pending: bool,
    backup_in_flight: bool,
    recent_backup_ok: bool,
) -> bool:
    """PURE. True only in the dead-end state: work is blocked and nothing will unblock it.

    Deliberately conservative in every direction:
      - `recent_backup_ok`  -> nothing to fix
      - `backup_pending`    -> a request already exists; a second one is noise
      - `backup_in_flight`  -> one is running; wait for the artifact (ADR-014: the
                               prerequisite is satisfied by the ARTIFACT, not the status)
      - `blocked_deploys=0` -> nothing is waiting, so do not take a backup "just in case"
    """
    if recent_backup_ok:
        return False
    if backup_pending or backup_in_flight:
        return False
    return blocked_deploys > 0


def _gather(cur) -> dict:
    """Read the four inputs. Same queries the Approvals tab uses, so they cannot disagree."""
    cur.execute(
        "SELECT count(*) AS n FROM autonomy_approval_queue " "WHERE action_type = ANY(%s) AND status = 'pending'",
        (list(_DEPLOY_LIKE),),
    )
    blocked = int((cur.fetchone() or {"n": 0})["n"] or 0)

    cur.execute(
        "SELECT count(*) AS n FROM autonomy_approval_queue " "WHERE action_type = %s AND status = 'pending'",
        (BACKUP_ACTION,),
    )
    pending = int((cur.fetchone() or {"n": 0})["n"] or 0)

    # approved-but-not-executed == still running. This is the ADR-014 distinction: approving
    # removes it from `pending` INSTANTLY while nothing is on disk yet.
    cur.execute(
        "SELECT count(*) AS n FROM autonomy_approval_queue "
        "WHERE action_type = %s AND status = 'approved' AND executed_at IS NULL",
        (BACKUP_ACTION,),
    )
    in_flight = int((cur.fetchone() or {"n": 0})["n"] or 0)

    from tools.department_hq.services.approvals_bulk import BACKUP_FRESH_HOURS

    cur.execute(
        "SELECT count(*) AS n FROM backup_log "
        "WHERE status = 'success' AND created_at > now() - make_interval(hours => %s)",
        (BACKUP_FRESH_HOURS,),
    )
    fresh = int((cur.fetchone() or {"n": 0})["n"] or 0)

    return {
        "blocked_deploys": blocked,
        "backup_pending": bool(pending),
        "backup_in_flight": bool(in_flight),
        "recent_backup_ok": fresh > 0,
        "fresh_hours": BACKUP_FRESH_HOURS,
    }


def maybe_raise_backup_approval() -> dict:
    """Enqueue one backup approval if — and only if — deploys are stuck on backup age.

    Returns a dict describing what it saw and did; NEVER raises. A failure here must not
    take down the watchdog that hosts it.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_conn, cur):
            state = _gather(cur)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[backup_autoraise] could not read queue state: %s", exc)
        return {"raised": False, "error": str(exc)}

    if not should_raise(
        blocked_deploys=state["blocked_deploys"],
        backup_pending=state["backup_pending"],
        backup_in_flight=state["backup_in_flight"],
        recent_backup_ok=state["recent_backup_ok"],
    ):
        return {"raised": False, **state}

    try:
        from ai_bridge.agent_loop import request_approval

        approval_id = request_approval(
            action_type=BACKUP_ACTION,
            action_data={"trigger": "autoraise", "blocked_deploys": state["blocked_deploys"]},
            reason=(
                f"{state['blocked_deploys']} deploy approval(s) are blocked with no successful "
                f"backup in the last {state['fresh_hours']}h, and no backup is pending or "
                "running. Approving this takes a fresh restore point and unblocks them."
            ),
            requested_by="backup_autoraise",
            priority=1,  # sorts to the top; it is the prerequisite for everything below it
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[backup_autoraise] enqueue failed: %s", exc)
        return {"raised": False, "error": str(exc), **state}

    # `request_approval` signals its OWN dedup by returning None, not by raising. Reporting
    # raised=True here would claim a row that does not exist — the exact "status misreports
    # the artifact" shape this whole feature exists to fix.
    if not approval_id:
        logger.info("[backup_autoraise] request_approval deduped — no new row")
        return {"raised": False, "deduped": True, **state}

    logger.info(
        "[backup_autoraise] raised approval #%s — %s deploy(s) blocked, backup older than %sh",
        approval_id,
        state["blocked_deploys"],
        state["fresh_hours"],
    )
    return {"raised": True, "approval_id": approval_id, **state}
