"""K.I.N. autonomous-action policy (#5176).

Phase 3 of ``kin_welfare_digest`` executes actions returned as free-form JSON by
K.I.N. (a 7B model). Nothing validated the action against the flag that raised it,
so ``welfare_recovery`` — which is ``recover_idle()``, a WRITE of stress -0.15 /
energy +0.2 — was applied to ``over_budget`` agents: the idle cure given to the
most overworked agents on the fleet, suppressing the signal that raised the flag.
Measured 12 such actions in 30 days (governance_audit_log, 2026-07-25).
"""

from services.welfare_load import KIN_FORBIDDEN_ACTIONS_BY_FLAG, kin_action_allowed


class TestOverBudgetNeverHealed:
    """The bug this policy exists to stop."""

    def test_over_budget_refuses_welfare_recovery(self):
        # recover_idle() lowers stress on an agent whose problem is too much work.
        assert kin_action_allowed("over_budget", "welfare_recovery") is False

    def test_over_budget_still_allows_throttling_remedies(self):
        # ADR-004 (#4090): token overage is a THROTTLE concern. Capping or cooling
        # the agent down is a coherent response; healing its stress is not.
        assert kin_action_allowed("over_budget", "workload_cap") is True
        assert kin_action_allowed("over_budget", "cooldown") is True


class TestNonActionableFlag:
    """``starving_no_llm`` is documented as 'expected, no action needed'."""

    def test_starving_no_llm_refuses_every_action(self):
        for action in ("welfare_recovery", "cooldown", "barracks", "workload_cap"):
            assert kin_action_allowed("starving_no_llm", action) is False


class TestFailOpen:
    """Narrow the behaviour only where it is known-wrong."""

    def test_starving_idle_is_a_real_gap_and_stays_actionable(self):
        # A genuinely idle agent (dispatcher routing gap) SHOULD be recovered.
        assert kin_action_allowed("starving_idle", "welfare_recovery") is True

    def test_unknown_flag_is_unconstrained(self):
        assert kin_action_allowed("some_future_flag", "welfare_recovery") is True

    def test_no_flag_is_unconstrained(self):
        # K.I.N. may act on an at_risk agent that produced no outlier flag.
        assert kin_action_allowed(None, "welfare_recovery") is True
        assert kin_action_allowed("", "cooldown") is True

    def test_unknown_action_type_is_not_refused_by_this_gate(self):
        # Unrecognised actions are dropped by the executor's own else-branch, not here.
        assert kin_action_allowed("over_budget", "something_new") is True


class TestPolicyShape:
    def test_policy_values_are_frozensets_so_the_table_cannot_be_mutated(self):
        for flag, actions in KIN_FORBIDDEN_ACTIONS_BY_FLAG.items():
            assert isinstance(actions, frozenset), flag
