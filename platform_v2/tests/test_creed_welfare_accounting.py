"""C.R.E.E.D. public welfare-score honesty: the token component must measure load
against each agent's REAL daily budget, not a flat 100k — so an over-budget agent
reads "strained", not "relaxed". Pure-function tests, no DB.
"""

from tools.department_hq.creed_routes import _welfare_score, _TOKEN_DAY_LIMIT


def test_over_budget_scores_lower_than_under_budget():
    under = _welfare_score(0.2, 0.8, 20_000, 100_000)  # 20% of budget
    over = _welfare_score(0.2, 0.8, 360_000, 100_000)  # 360% of budget
    assert over < under, "an over-budget agent must score lower than an under-budget one"
    # at/over budget the token component is exactly 0
    assert over == round((1 - 0.2) * 40 + 0.8 * 30 + 0)


def test_real_budget_not_flat_100k():
    # A 300k-budget agent at 150k tokens is 50% loaded = healthy. The OLD flat-100k
    # formula would have called it "overloaded" (150k > 100k -> token component 0).
    big_budget = _welfare_score(0.2, 0.8, 150_000, 300_000)  # 50% util
    small_budget = _welfare_score(0.2, 0.8, 150_000, 100_000)  # 150% util
    assert big_budget > small_budget, "real budget must not be treated as a flat 100k"
    assert big_budget == round((1 - 0.2) * 40 + 0.8 * 30 + 30 * 0.5)


def test_no_budget_row_uses_fallback():
    # budget=0 -> fall back to _TOKEN_DAY_LIMIT (100k); 50k tokens = 50% -> token comp 15
    s = _welfare_score(0.2, 0.8, 50_000, 0)
    assert s == round((1 - 0.2) * 40 + 0.8 * 30 + 30 * (1 - 50_000 / _TOKEN_DAY_LIMIT))


def test_bounds_and_zero_load():
    idle = _welfare_score(0.0, 1.0, 0, 120_000)  # best case
    burnt = _welfare_score(0.9, 0.1, 999_999, 90_000)  # worst case
    assert idle == round(40 + 30 + 30)  # 100
    assert 0 <= burnt <= 100 and burnt < idle
