"""D3 (2026-06-13): EWMA-smoothed welfare score keeps the headline grade steady.

A single bad snapshot must not tank the grade — smooth_score blends the latest raw
score with the prior EWMA so the headline moves gradually.
"""

from services.welfare_governance import smooth_score, DEFAULT_SCORE_EWMA_ALPHA


def test_first_value_is_raw():
    # No prior history -> the EWMA seeds to the raw value verbatim.
    assert smooth_score(80, None) == 80.0


def test_blends_with_default_alpha():
    # default alpha 0.3: 0.3*100 + 0.7*80 = 86.0
    assert DEFAULT_SCORE_EWMA_ALPHA == 0.3
    assert smooth_score(100, 80) == 86.0


def test_single_spike_is_dampened():
    # A momentary 40 after a steady 95 only drags the headline to 78.5, not 40 —
    # this is the whole point of D3 (one bad moment can't tank the grade).
    assert smooth_score(40, 95, 0.3) == 78.5


def test_alpha_clamped_to_unit():
    # alpha > 1 clamps to 1.0 -> fully responsive (returns raw).
    assert smooth_score(100, 0, 5.0) == 100.0


def test_steady_input_converges():
    e = None
    for _ in range(12):
        e = smooth_score(90, e)
    assert e == 90.0


def test_grade_for_handles_partial_cfg():
    # Regression: grading the EWMA passes governance_limits() (a PARTIAL cfg with only
    # token_pct) — it must fall back to default grade_bands, not KeyError.
    from services.welfare_governance import grade_for, governance_limits

    assert grade_for(96, governance_limits({"token_pct": 0.9})) == "A+"
    assert grade_for(50, {}) == "F"
    assert grade_for(82, None) == "B"
