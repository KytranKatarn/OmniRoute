"""The backup auto-raise + "Back up now" remedy (#5865).

WHY: measured 2026-08-25, the Approvals tab showed 6 blocked `deploy_approve` rows reading
"no successful backup in the last 6h" while the last successful backup was 8.7h old and
there were ZERO pending `backup_before_deploy` rows. The blocker named no remedy and
nothing in the system was going to create one. Separately, 6 APPROVED deploys had already
died on `W.A.R.D.E.N. clearance denied: backup age 8.2h exceeds medium limit of 6h` AFTER
passing their sandbox gate 3/3 — sound work, discarded on backup age.

Both halves are pure functions so the decision is testable without a queue:
  should_raise  -> may the watchdog enqueue a backup approval?

The UI half (`backup_is_actionable` + the "Back up now" button) is a separate PR:
the combined diff was 31,947 chars against F.O.R.G.E.'s 18,768-char review window, so
4 of 6 files were truncated away before the model saw them and the verdict could not
cover them. Split so every file is actually reviewed.
"""

import pytest

from services.backup_autoraise import should_raise


# --------------------------------------------------------------- should_raise

_DEAD_END = dict(blocked_deploys=6, backup_pending=False, backup_in_flight=False, recent_backup_ok=False)


def test_raises_in_the_dead_end_state():
    """The measured live state: deploys blocked, backup stale, nothing queued."""
    assert should_raise(**_DEAD_END) is True


def test_does_not_raise_when_a_backup_is_already_pending():
    """A second request is noise — the operator already has one to approve."""
    assert should_raise(**{**_DEAD_END, "backup_pending": True}) is False


def test_does_not_raise_while_a_backup_is_in_flight():
    """Approved-but-unexecuted means RUNNING. The remedy is to wait for the ARTIFACT.

    ADR-014: approving removes the row from `pending` instantly while nothing is on disk
    yet, so treating "not pending" as "not running" would queue a duplicate every cycle.
    """
    assert should_raise(**{**_DEAD_END, "backup_in_flight": True}) is False


def test_does_not_raise_when_a_recent_backup_exists():
    assert should_raise(**{**_DEAD_END, "recent_backup_ok": True}) is False


def test_does_not_raise_on_an_idle_queue():
    """Nothing is blocked, so there is nothing to unblock. A backup 'just in case' is
    a 15-minute job nobody asked for."""
    assert should_raise(**{**_DEAD_END, "blocked_deploys": 0}) is False


@pytest.mark.parametrize(
    "override",
    [
        {"backup_pending": True},
        {"backup_in_flight": True},
        {"recent_backup_ok": True},
        {"blocked_deploys": 0},
    ],
)
def test_any_single_negative_input_suppresses_the_raise(override):
    """Every uncertain input must fail toward NOT enqueueing. Enumerated rather than
    trusted to the implementation's `or` chain, so reordering the guards cannot
    accidentally make one of them non-binding."""
    assert should_raise(**{**_DEAD_END, **override}) is False
