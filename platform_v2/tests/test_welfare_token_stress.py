"""Unit tests for the token-budget overwork stress term (C.R.E.E.D. accounting Fix #C).

stress_energy_from_load() is pure (no DB), so these run directly on the host.
"""

from services.welfare_load import STRESS_CEILING, stress_energy_from_load


def test_token_util_zero_is_backward_compatible():
    """token_util=0.0 (the default) must be identical to omitting it entirely,
    across a range of load/failure/hours/rest inputs."""
    cases = [
        (0.0, 0, 10, 0.0, False),
        (0.5, 0, 10, 0.0, False),
        (0.5, 2, 10, 4.0, False),
        (1.0, 5, 10, 12.0, True),
        (0.3, 0, 0, 0.0, False),
    ]
    for load, failures, total, hours, resting in cases:
        without = stress_energy_from_load(load, failures, total, hours, resting)
        with_zero = stress_energy_from_load(load, failures, total, hours, resting, token_util=0.0)
        with_default = stress_energy_from_load(load, failures, total, hours, resting, 0.0)
        assert without == with_zero == with_default


def test_token_util_below_threshold_adds_nothing():
    """<=70% of daily budget must not move stress at all."""
    base = stress_energy_from_load(0.5, 0, 10)
    for util in (0.0, 0.3, 0.5, 0.7):
        s, e = stress_energy_from_load(0.5, 0, 10, token_util=util)
        assert (s, e) == base


def test_token_util_100pct_adds_about_point_one_one():
    base_s, _ = stress_energy_from_load(0.5, 0, 10)
    at_100, _ = stress_energy_from_load(0.5, 0, 10, token_util=1.0)
    assert round(at_100 - base_s, 2) == 0.11


def test_token_util_150pct_adds_about_point_three():
    base_s, _ = stress_energy_from_load(0.5, 0, 10)
    at_150, _ = stress_energy_from_load(0.5, 0, 10, token_util=1.5)
    assert round(at_150 - base_s, 2) == 0.30


def test_token_util_beyond_150pct_does_not_add_more():
    """The term is clamped at 150% of budget — further overage adds nothing extra."""
    at_150, _ = stress_energy_from_load(0.5, 0, 10, token_util=1.5)
    at_300, _ = stress_energy_from_load(0.5, 0, 10, token_util=3.0)
    assert at_150 == at_300


def test_stress_stays_within_db_check_bounds():
    """Even a maxed-out agent (full load, failures, hours, and 364% token overage)
    must stay within the existing stress ceiling (DB CHECK <= 0.9)."""
    s, e = stress_energy_from_load(1.0, 10, 10, hours_on_duty=12.0, token_util=3.64)
    assert 0.0 <= s <= STRESS_CEILING
    assert 0.1 <= e <= 0.9


def test_overbudget_agent_reads_more_stressed_than_same_load_unknown_budget():
    """The core bug this fixes: an agent 364% over its daily token budget must NOT
    read as 'relaxed' relative to identical load/failure/hours with no budget signal."""
    unknown_budget_s, _ = stress_energy_from_load(0.1, 0, 10, hours_on_duty=1.0, token_util=0.0)
    over_budget_s, _ = stress_energy_from_load(0.1, 0, 10, hours_on_duty=1.0, token_util=3.64)
    assert over_budget_s > unknown_budget_s
    assert round(over_budget_s - unknown_budget_s, 2) == 0.30
