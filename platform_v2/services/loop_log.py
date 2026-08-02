"""Why did that job fail? — shared reason-resolver for autonomy_loop_log (#5339).

THE MEASUREMENT
---------------
2026-07-28, last 7 days of ``autonomy_loop_log``::

    status='partial'  64 rows, 64 with no reason   (8 jobs)
    status='error'    43 rows, 43 with no reason   (6 jobs)

**107 of 107 failing rows recorded nothing about why.** Not most — all. Worst
offenders: vps_health 38, delegate_task_worker 25, approvals 11,
code_health_backlog_drain 9, kin_welfare_digest 7, ollama_model_health 6,
creed_accounting_audit 5, warden_backup_verify 2.

A failure row with a NULL reason is worse than no row: it reports that something
broke while withholding the one field that would let anyone act, and it renders
identically to a healthy job in every dashboard that only counts statuses. This
is the same defect family as the zombie reaper mislabelling healthy jobs and a
merged PR reporting success over dead code — a status that misdescribes reality.

WHY THIS LIVES IN ONE PLACE
---------------------------
There are SIX copy-paste ``_log_cycle`` implementations (security_network,
department_hq, consciousness, fleet_jobs, agent_jobs, agent_loop) and **240 call
sites, 186 of which pass no error_message**. Fixing the call sites means 186
edits across six modules — unreviewable, and it would silently regress the
moment someone adds site 241.

So the fix goes where the leverage is: the resolver. Most of those 186 calls
happen INSIDE an ``except`` block, and ``sys.exc_info()`` still has the live
exception there — the reason was always available, nobody just asked for it.

CONTRACT
--------
* An explicit ``error_message`` from the caller ALWAYS wins. Never overwrite what
  the code that actually failed chose to say.
* ``success`` rows stay NULL. Do not decorate healthy runs.
* Otherwise capture the exception being handled, if any.
* Otherwise fall back to reasons the job already enumerated in ``details``.
* If there is genuinely no reason anywhere (a job that counted failures without
  raising and without explaining), record an explicit admission naming the gap
  rather than leaving NULL. An admission is greppable and countable; a NULL is
  indistinguishable from fine.

READING ``details['reasons']`` (2026-08-02)
-------------------------------------------
Several jobs DO explain themselves — into ``details['reasons']`` — while passing
no ``error_message``. ``kin_welfare_digest`` is the worked example: it records
"4 agent(s) over budget", "14 idle agents (dispatcher routing gap)" and
"16 LLM-free scheduled workers" in ``details``, and the row still read
"(no reason recorded: ... raised nothing)". That sentinel was *literally* true —
the resolver was never handed ``details`` — but it had two bad effects:

1. It **overstated the remaining #5339 worklist**. The marker exists to count
   jobs that cannot say why they failed; a job whose reasons are sitting one
   column away is not one of them.
2. The briefing surfaces ``reasons`` and ``error_message`` side by side, so an
   operator saw three concrete reasons next to "no reason recorded" and had to
   work out which to believe.

This lookup is deliberately LAST before the sentinel: an explicit caller message
and a live exception both still win, so no row that is explained today changes.
The change can only ever affect rows that currently carry the sentinel.
"""

from __future__ import annotations

import sys

#: autonomy_loop_log.error_message is TEXT, but keep rows readable in table output.
MAX_REASON_CHARS = 500

#: Marker for "the job reported failure and offered no explanation". Deliberately
#: distinctive so `... WHERE error_message LIKE '(no reason recorded%'` counts the
#: remaining gap per job — the follow-up worklist writes itself.
NO_REASON_PREFIX = "(no reason recorded"


def _reasons_from_details(details) -> "str | None":
    """Join ``details['reasons']`` into one line, or None if unusable.

    Every input is treated as hostile: ``details`` reaches us straight from
    arbitrary job code and this runs on the logging path of every job, so an
    exception here would turn a LOGGED failure into an UNLOGGED crash.
    """
    try:
        if not isinstance(details, dict):
            return None
        reasons = details.get("reasons")
        if isinstance(reasons, (str, bytes)):
            # A bare string is a single reason, not an iterable of characters.
            reasons = [reasons]
        if not isinstance(reasons, (list, tuple)):
            return None
        parts = [str(r).strip() for r in reasons if r is not None and str(r).strip()]
        return "; ".join(parts) or None
    except Exception:  # noqa: BLE001 — a reason-resolver must never raise
        return None


def explain_failure(
    status: str,
    items_failed: int = 0,
    error_message: str = None,
    details: dict = None,
) -> "str | None":
    """Resolve what to store in ``autonomy_loop_log.error_message``.

    Args:
        status: the computed cycle status (``success`` / ``partial`` / ``error``).
        items_failed: how many items the job counted as failed.
        error_message: whatever the caller passed, if anything.
        details: the job's ``details`` dict; ``details['reasons']`` is read as a
            last resort before admitting the gap. Optional, so the five-arg and
            four-arg call sites both keep working.

    Returns:
        The reason to store, or ``None`` for a healthy run.
    """
    # 1. The caller's own words win, always.
    if error_message:
        return str(error_message)[:MAX_REASON_CHARS]

    # 2. Never decorate a healthy row.
    if status == "success":
        return None

    # 3. The reason is usually right there — we are almost always inside an
    #    `except` block. In Python 3 sys.exc_info() is cleared when the handler
    #    exits, so this cannot leak a stale exception from an earlier call.
    try:
        exc = sys.exc_info()[1]
    except Exception:  # noqa: BLE001 — a reason-resolver must never raise
        exc = None
    if exc is not None:
        return f"{type(exc).__name__}: {exc}"[:MAX_REASON_CHARS]

    # 4. No exception — but the job may have enumerated its own reasons into
    #    details['reasons'] (kin_welfare_digest does). Prefer the job's own words
    #    over admitting a gap that does not exist. LAST before the sentinel, so
    #    this can only ever change rows that would otherwise be marked unexplained.
    from_details = _reasons_from_details(details)
    if from_details:
        return from_details[:MAX_REASON_CHARS]

    # 5. Nothing anywhere: the job counted failures without raising and without
    #    explaining. Say so out loud instead of storing NULL, which reads as
    #    "nothing went wrong".
    if items_failed:
        return (
            f"{NO_REASON_PREFIX}: {items_failed} item(s) failed but the job passed "
            f"no error_message and raised nothing — see #5339)"
        )[:MAX_REASON_CHARS]

    return f"{NO_REASON_PREFIX}: status={status} with no failure count — see #5339)"[:MAX_REASON_CHARS]
