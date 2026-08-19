"""Bulk approve/deny for the DHQ Approvals tab.

Hermetic: pure selection logic only, no Flask app and no DB. The properties pinned here
are the ones where a wrong answer is invisible — a silently truncated batch, a duplicate
executing twice, and the publishing carve-out quietly widening.
"""

import pytest

from tools.department_hq.services import approvals_bulk as B


# ---------------- the publishing carve-out ----------------
@pytest.mark.parametrize(
    "action_type",
    ["linkedin_post", "linkedin_comment", "linkedin_comment_reply", "linkedin_like", "website_deploy"],
)
def test_outbound_types_get_no_one_click_shortcut(action_type):
    """One click must not publish N pieces of content in the owner's name."""
    assert B.can_bulk_all(action_type) is False


@pytest.mark.parametrize(
    "action_type", ["deploy_approve", "improvement_approve_red", "backup_before_deploy", "pr_merge"]
)
def test_internal_types_may_offer_approve_all(action_type):
    assert B.can_bulk_all(action_type) is True


def test_carve_out_is_case_insensitive_and_null_safe():
    assert B.can_bulk_all("LinkedIn_Post") is False
    assert B.can_bulk_all("  linkedin_post  ") is False
    # An UNKNOWN type is allowed — the excluded set is the deliberate list, and a new
    # internal type should not silently lose its shortcut. Adding a new OUTBOUND type
    # means adding it to BULK_ALL_EXCLUDED_TYPES.
    assert B.can_bulk_all("some_new_internal_type") is True
    assert B.can_bulk_all(None) is True


# ---------------- id parsing (mirrors the single-approve route) ----------------
def test_valid_ids_parse():
    assert B.parse_approval_id("autonomy:123") == ("autonomy", 123)
    assert B.parse_approval_id("contractor:7") == ("contractor", 7)
    assert B.parse_approval_id("bridge:99") == ("bridge", 99)


@pytest.mark.parametrize(
    "bad", ["", "autonomy", "autonomy:", ":123", "nope:1", "autonomy:abc", "autonomy:1:2", None, 123]
)
def test_bad_ids_rejected(bad):
    assert B.parse_approval_id(bad) is None


# ---------------- batch validation ----------------
def test_happy_batch():
    parsed, err = B.validate_batch(["autonomy:1", "bridge:2"], "approve")
    assert err is None
    assert [p[0] for p in parsed] == ["autonomy:1", "bridge:2"]


def test_duplicates_execute_once():
    """The same id twice must not action it twice."""
    parsed, err = B.validate_batch(["autonomy:1", "autonomy:1", "bridge:2"], "approve")
    assert err is None
    assert len(parsed) == 2


def test_oversized_batch_is_REFUSED_not_truncated():
    """A silent slice would report success while leaving items pending — the operator
    would believe the queue was cleared."""
    parsed, err = B.validate_batch([f"autonomy:{i}" for i in range(B.MAX_BULK + 1)], "approve")
    assert parsed is None
    assert "at most" in err


def test_batch_at_the_cap_is_allowed():
    parsed, err = B.validate_batch([f"autonomy:{i}" for i in range(B.MAX_BULK)], "approve")
    assert err is None and len(parsed) == B.MAX_BULK


def test_one_bad_id_rejects_the_WHOLE_batch():
    """Fail closed: silently dropping the unparseable one would action a different set
    than the operator selected."""
    parsed, err = B.validate_batch(["autonomy:1", "garbage", "bridge:2"], "approve")
    assert parsed is None
    assert "garbage" in err


@pytest.mark.parametrize("action", ["", "delete", "APPROVE", None])
def test_only_approve_and_deny_are_actions(action):
    parsed, err = B.validate_batch(["autonomy:1"], action)
    assert parsed is None and "action" in err


@pytest.mark.parametrize("ids", [[], None, "autonomy:1", {}])
def test_ids_must_be_a_non_empty_list(ids):
    parsed, err = B.validate_batch(ids, "approve")
    assert parsed is None and "ids" in err


# ---------------- the signature asymmetry that bit during implementation ----------------
def test_approve_and_deny_helpers_have_DIFFERENT_shapes():
    """_approve_*(source_id, user_id) -> (ok, action_type)
       _deny_*(source_id, user_id, REASON) -> bool

    Unpacking deny like approve raises TypeError, and the first draft of the bulk route
    did exactly that — every deny would have failed. Pinned here so the next person
    touching the route sees the asymmetry before runtime does."""
    import inspect

    from tools.department_hq import approvals_routes as R

    for name in ("_approve_autonomy", "_approve_contractor", "_approve_bridge"):
        assert len(inspect.signature(getattr(R, name)).parameters) == 2, name
    for name in ("_deny_autonomy", "_deny_contractor", "_deny_bridge"):
        assert len(inspect.signature(getattr(R, name)).parameters) == 3, name


# ---------------------------------------------------------------------------
# ORDERING + PREREQUISITES — clearing the queue in arrival order can ship work the
# safety net was meant to cover. Measured on the live queue 2026-08-19: ONE pending
# backup_before_deploy ("backup age 9.0h exceeds medium limit of 6h") alongside TWELVE
# medium-risk deploy_approve items.
# ---------------------------------------------------------------------------


def test_prerequisites_sort_before_the_work_they_gate():
    order = ["backup_before_deploy", "pr_merge", "deploy_approve", "improvement_approve_red", "website_deploy"]
    got = sorted(order, key=B.category_priority)
    assert got[0] == "backup_before_deploy", "the safety net is taken FIRST"
    assert got.index("pr_merge") < got.index("deploy_approve"), "code lands before it deploys"
    assert got.index("deploy_approve") < got.index("website_deploy")


def test_judgement_categories_sort_last():
    for t in ["linkedin_post", "linkedin_like", "hire_candidate"]:
        assert B.category_priority(t) > B.category_priority("deploy_approve")


def test_unknown_category_lands_mid_table_never_first():
    assert B.category_priority("brand_new_type") > B.category_priority("backup_before_deploy")


def test_deploy_is_blocked_while_a_backup_approval_is_pending():
    """THE measured case — deploying first ships medium-risk fixes against a stale backup.

    Asserts BEHAVIOUR (a reason exists for the backup prerequisite), not wording: the
    text is deliberately consequence-phrased, and an earlier version of this test asserted
    the literal word "backup" and broke on a rewording that changed nothing real."""
    unsat = B.unsatisfied_prerequisites({"backup_before_deploy", "deploy_approve"})
    assert "backup_before_deploy" in unsat
    assert B.blocking_reasons("deploy_approve", unsat), "must be blocked"


def test_deploy_is_blocked_while_a_pr_merge_is_pending():
    """deploy_approve deploys FILES directly (sandbox gate -> deploy), not via a PR, so
    deploying with a merge outstanding puts the running code out of step with main."""
    reasons = B.blocking_reasons("deploy_approve", {"pr_merge", "deploy_approve"})
    assert any("out of step with main" in r for r in reasons)


def test_both_prerequisites_are_reported_together():
    reasons = B.blocking_reasons("deploy_approve", {"backup_before_deploy", "pr_merge", "deploy_approve"})
    assert len(reasons) == 2, "the operator should see EVERY reason, not just the first"


def test_nothing_is_blocked_once_prerequisites_are_cleared():
    assert B.blocking_reasons("deploy_approve", {"deploy_approve", "linkedin_post"}) == []
    assert B.blocking_reason("deploy_approve", {"deploy_approve"}) is None


def test_prerequisites_do_not_block_themselves():
    """A self-referential gate would deadlock the queue."""
    assert B.blocking_reasons("backup_before_deploy", {"backup_before_deploy"}) == []
    assert B.blocking_reasons("pr_merge", {"pr_merge", "backup_before_deploy"}) == []


def test_hire_candidate_lost_its_one_click_shortcut():
    """Provisioning, not publishing — but 'Approve all 15' creates fifteen agents in one
    click. Found by a LIVE drive; the first rule caught publishing and missed this."""
    assert B.can_bulk_all("hire_candidate") is False


# ---------------------------------------------------------------------------
# THE GAP LIVE TESTING FOUND: approval is an INTENT, the backup is the FACT.
# Measured 2026-08-19 — approving backup_before_deploy #11442 dropped it out of `pending`
# INSTANTLY while executed_at was NULL and no backup_log row existed, so the deploy gate
# opened against a backup that had not happened (ADR-014: gate on the artifact).
# ---------------------------------------------------------------------------


def test_approved_but_still_running_backup_STILL_blocks():
    """The window that matters: approved, executor not finished, nothing on disk yet."""
    unsat = B.unsatisfied_prerequisites(set(), backup_in_flight=True)
    assert "backup_before_deploy" in unsat
    assert "not finished" in unsat["backup_before_deploy"]
    assert B.blocking_reasons("deploy_approve", unsat)


def test_no_recent_successful_backup_STILL_blocks():
    """Executed is not enough — a backup that produced no artifact leaves no restore point."""
    unsat = B.unsatisfied_prerequisites(set(), recent_backup_ok=False)
    assert "backup_before_deploy" in unsat
    assert B.blocking_reasons("deploy_approve", unsat)


def test_gate_opens_only_when_the_backup_ACTUALLY_landed():
    unsat = B.unsatisfied_prerequisites(set(), backup_in_flight=False, recent_backup_ok=True)
    assert unsat == {}
    assert B.blocking_reasons("deploy_approve", unsat) == []


def test_state_reason_replaces_the_stale_instruction():
    """Once approved, 'approve the backup first' is FALSE. The state message must lead."""
    unsat = B.unsatisfied_prerequisites(set(), backup_in_flight=True)
    reason = B.blocking_reasons("deploy_approve", unsat)[0]
    assert reason.startswith("the approved backup has not finished")
    assert "approve it first" not in reason


def test_set_form_still_works_for_callers_without_measured_state():
    """Back-compat: a bare set of prerequisite names still blocks, just less specifically."""
    assert B.blocking_reasons("deploy_approve", {"pr_merge"})


# ---------------------------------------------------------------------------
# ADR-014 IN A SECOND PLACE: a pr_merge approval whose PR ALREADY MERGED is stale.
# Measured 2026-08-19 — PR #2699 was merged through Repair Bay (the correct path), which
# does NOT action the approval row, so #11680 stayed `pending` and held the deploy gate
# shut on a merge that had already happened. Historic pr_merge rows sat 24.0h and 50.1h
# before expiring, so a stale one can block deploys for a day or more.
# ---------------------------------------------------------------------------


def test_pending_pr_merge_blocks_while_its_PR_is_still_open():
    unsat = B.unsatisfied_prerequisites({"pr_merge"}, pr_merge_open=True)
    assert "pr_merge" in unsat
    assert B.blocking_reasons("deploy_approve", unsat)


def test_pending_pr_merge_whose_PR_ALREADY_MERGED_does_not_block():
    """THE stale case: the row says pending, the PR says merged. The PR is the fact."""
    unsat = B.unsatisfied_prerequisites({"pr_merge"}, pr_merge_open=False)
    assert "pr_merge" not in unsat
    assert B.blocking_reasons("deploy_approve", unsat) == []


def test_unknown_pr_state_FAILS_SAFE_and_still_blocks():
    """Unknown must never open a gate — the same asymmetry as the backup facts."""
    unsat = B.unsatisfied_prerequisites({"pr_merge"}, pr_merge_open=None)
    assert "pr_merge" in unsat


def test_stale_pr_merge_does_not_mask_an_unmet_BACKUP():
    """Clearing one prerequisite must not clear the other."""
    unsat = B.unsatisfied_prerequisites({"pr_merge"}, pr_merge_open=False, recent_backup_ok=False)
    assert "pr_merge" not in unsat
    assert "backup_before_deploy" in unsat
    assert B.blocking_reasons("deploy_approve", unsat)
