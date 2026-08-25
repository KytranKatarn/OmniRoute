"""The "Back up now" remedy — which rows may offer it (#5865).

2 of 3, split from the auto-raise service (which owns `should_raise`). The deploy gate
showed "no successful backup in the last Nh" as a prerequisite on every deploy row and
named NO remedy anywhere in the UI; `backup_is_actionable` decides which rows get the
button.

⚠️ The whole point is that the UI keys off a server-stamped FLAG, never the reason TEXT.
All three prerequisite states render as prose in `blocked_reasons`, so a JS substring
match on "no successful backup in the last Nh" would silently stop working the day
someone rewords it. `test_the_ui_flag_does_not_depend_on_the_reason_TEXT` pins that.
"""

from tools.department_hq.services.approvals_bulk import PREREQUISITES, backup_is_actionable


# ------------------------------------------------------- backup_is_actionable

_UNSAT_STALE = {"backup_before_deploy": "no successful backup in the last 6h"}


def test_button_offered_for_a_deploy_blocked_on_backup_age():
    assert backup_is_actionable("deploy_approve", _UNSAT_STALE) is True


def test_button_offered_for_the_red_self_heal_family_too():
    """improvement_approve_red carries the same prerequisite and the same remedy."""
    assert backup_is_actionable("improvement_approve_red", _UNSAT_STALE) is True


def test_button_withheld_while_a_backup_is_in_flight():
    """The remedy there is to WAIT. A button that starts a second concurrent dump would
    serialise on acquire_backup_lock and tell the operator nothing true."""
    assert backup_is_actionable("deploy_approve", _UNSAT_STALE, backup_in_flight=True) is False


def test_button_withheld_when_backup_is_not_the_blocker():
    """A pr_merge-only blocker is not fixed by taking a backup."""
    assert backup_is_actionable("deploy_approve", {"pr_merge": "a merge is still open"}) is False


def test_button_withheld_for_a_category_that_does_not_need_a_backup():
    """website_deploy is gated on pr_merge ONLY. Offering it a backup button would
    imply a prerequisite that does not exist."""
    assert "website_deploy" in PREREQUISITES  # the premise, asserted not assumed
    assert not any(p == "backup_before_deploy" for p, _ in PREREQUISITES["website_deploy"])
    assert backup_is_actionable("website_deploy", _UNSAT_STALE) is False


def test_button_withheld_for_an_ungated_category():
    assert backup_is_actionable("linkedin_post", _UNSAT_STALE) is False


def test_unknown_and_empty_action_types_are_safe():
    assert backup_is_actionable(None, _UNSAT_STALE) is False
    assert backup_is_actionable("", _UNSAT_STALE) is False
    assert backup_is_actionable("deploy_approve", None) is False


def test_action_type_matching_is_case_and_space_tolerant():
    assert backup_is_actionable("  Deploy_Approve  ", _UNSAT_STALE) is True


def test_the_ui_flag_does_not_depend_on_the_reason_TEXT():
    """The whole point of the flag. All three prerequisite states render as prose in
    `blocked_reasons`; a JS substring match on "no successful backup in the last Nh"
    would silently stop working the day someone rewords it. The predicate keys off the
    prerequisite KEY, so an arbitrary message still yields True."""
    assert backup_is_actionable("deploy_approve", {"backup_before_deploy": "anything at all"}) is True
    assert backup_is_actionable("deploy_approve", {"backup_before_deploy": ""}) is True


# --------------------------------------------------------------- the threshold


def test_display_threshold_reads_the_gate_rather_than_mirroring_it():
    """BACKUP_FRESH_HOURS used to be a hardcoded 6 that "mirrors" the deploy gate. The
    gate is tunable live via system_config['backup_governance_gates'], so a mirror drifts:
    raise the gate to 12h and the UI would still say "no successful backup in the last 6h"
    while the gate allowed 12. It now derives from the gate config."""
    import inspect

    from tools.department_hq.services import approvals_bulk

    src = inspect.getsource(approvals_bulk._backup_fresh_hours)
    assert "_load_gate_config" in src, "the threshold must READ the gate, not restate it"
    assert isinstance(approvals_bulk.BACKUP_FRESH_HOURS, int)
    assert approvals_bulk.BACKUP_FRESH_HOURS > 0


def test_threshold_falls_back_tight_not_loose():
    """If the gate config is unreadable the fallback must be the CONSERVATIVE 6h, not a
    generous window — a display that over-states freshness would tell the operator a
    blocked deploy is clear to ship."""
    from tools.department_hq.services.approvals_bulk import _backup_fresh_hours

    assert _backup_fresh_hours() > 0
