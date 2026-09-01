"""Guards for A.U.R.O.R.A. forecast verification.

`consumer/aurora_verify` is deliberately stdlib-only so this file can always
import it. If that ever stops being true these tests would SKIP rather than
fail, which is the failure mode KB #290497 exists to prevent — so the import
is at module scope, unguarded, on purpose.
"""

import datetime

from consumer.aurora_verify import (
    BIAS_NEUTRAL_BAND_C,
    MIN_PAIRS_FOR_CONFIDENCE,
    bias_direction,
    city_scoreboard,
    skill_curve,
    summarise,
    verification_payload,
)


def _row(lead, fc, ob, site="s1", city="Testville", day=None):
    return {
        "lead_days": lead,
        "forecast_c": fc,
        "observed_c": ob,
        "site_code": site,
        "city": city,
        "province": "ON",
        "target_day": day or datetime.date(2026, 8, 20),
    }


# --------------------------------------------------------------------------
# The arithmetic itself
# --------------------------------------------------------------------------

def test_bias_is_signed_and_mae_is_not():
    """A forecast 2 degrees high and one 2 degrees low average to zero bias,
    but the mean absolute error is 2. Collapsing these into one number is
    exactly what hides a systematic error, so both must survive."""
    rows = [_row(1, 22.0, 20.0), _row(1, 18.0, 20.0)]
    curve = skill_curve(rows)
    assert len(curve) == 1
    assert curve[0]["bias_c"] == 0.0
    assert curve[0]["mae_c"] == 2.0


def test_negative_bias_means_the_forecast_ran_cold():
    """Sign convention is load-bearing: it drives the word AND the colour on
    the page. Forecast below observed => under-called the high => 'cold'."""
    rows = [_row(5, 19.0, 21.0)]
    curve = skill_curve(rows)
    assert curve[0]["bias_c"] == -2.0
    assert curve[0]["direction"] == "cold"


def test_positive_bias_reads_warm():
    rows = [_row(5, 23.0, 21.0)]
    assert skill_curve(rows)[0]["direction"] == "warm"


def test_small_bias_reads_even_not_a_direction():
    """Below the neutral band we must not imply a direction the sample cannot
    support — 'even' is an honest answer, a coloured arrow is not."""
    tiny = BIAS_NEUTRAL_BAND_C / 2
    assert bias_direction(tiny) == "even"
    assert bias_direction(-tiny) == "even"
    assert bias_direction(None) is None


# --------------------------------------------------------------------------
# Missing data must never become a zero error
# --------------------------------------------------------------------------

def test_a_missing_observation_is_skipped_not_counted_as_zero_error():
    """THE bug this module most needs to not have. A day we never observed is
    absent evidence; counting it as a perfect forecast would make the service
    look better the more data it loses."""
    rows = [_row(1, 20.0, 20.0), _row(1, 25.0, None)]
    curve = skill_curve(rows)
    assert curve[0]["pairs"] == 1, "the unobserved day must not be counted"
    assert curve[0]["mae_c"] == 0.0


def test_all_rows_unusable_yields_a_gap_not_a_crash_and_not_a_zero():
    rows = [_row(1, None, None), _row(2, 20.0, None)]
    payload = verification_payload(rows)
    assert payload["has_data"] is False
    assert payload["summary"]["total_pairs"] == 0
    assert payload["summary"]["same_day_mae_c"] is None


def test_empty_input_renders_an_honest_empty_state():
    """A fresh deploy has no verified pairs. That must be a stated absence,
    never a 500 and never zeroes that read as a flawless forecast."""
    payload = verification_payload([])
    assert payload["has_data"] is False
    assert payload["skill_curve"] == []
    assert payload["cities"] == []
    assert payload["summary"]["window_days"] == 0


def test_none_input_is_tolerated():
    assert verification_payload(None)["has_data"] is False


# --------------------------------------------------------------------------
# Scoreboard shaping
# --------------------------------------------------------------------------

def test_scoreboard_excludes_same_day_by_default():
    """Lead 0 is a much easier problem; including it flatters every city and
    hides which places are genuinely hard to forecast."""
    rows = [
        _row(0, 20.0, 20.0),          # perfect same-day, must be ignored
        _row(2, 26.0, 20.0),          # 6 degrees out at lead 2
    ]
    board = city_scoreboard(rows)
    assert len(board) == 1
    assert board[0]["pairs"] == 1
    assert board[0]["mae_c"] == 6.0


def test_scoreboard_orders_worst_forecast_city_first():
    rows = [
        _row(2, 21.0, 20.0, site="easy", city="Easy"),
        _row(2, 28.0, 20.0, site="hard", city="Hard"),
    ]
    board = city_scoreboard(rows)
    assert [c["city"] for c in board] == ["Hard", "Easy"]


def test_thin_samples_are_flagged_rather_than_hidden():
    """A one-observation city still appears — suppressing it would silently
    shrink the country — but it is marked so it is not read with the same
    confidence as a well-sampled one."""
    rows = [_row(2, 25.0, 20.0)]
    board = city_scoreboard(rows)
    assert board[0]["thin"] is True

    many = [_row(2, 25.0, 20.0) for _ in range(MIN_PAIRS_FOR_CONFIDENCE)]
    assert city_scoreboard(many)[0]["thin"] is False


def test_city_name_survives_when_only_some_rows_carry_it():
    """Station name comes from a LEFT-ish join and can be absent on some rows;
    the display name must not depend on which row happened to arrive first."""
    rows = [
        {"lead_days": 2, "forecast_c": 21.0, "observed_c": 20.0,
         "site_code": "s9", "city": None, "province": None,
         "target_day": datetime.date(2026, 8, 20)},
        _row(2, 22.0, 20.0, site="s9", city="Kelowna"),
    ]
    board = city_scoreboard(rows)
    assert board[0]["city"] == "Kelowna"


# --------------------------------------------------------------------------
# The summary and its window
# --------------------------------------------------------------------------

def test_summary_reports_the_observation_window():
    """Every figure must be able to state the window it came from — publishing
    an accuracy number without it implies a longer record than we hold."""
    rows = [
        _row(1, 20.0, 20.0, day=datetime.date(2026, 8, 18)),
        _row(1, 20.0, 20.0, day=datetime.date(2026, 8, 30)),
    ]
    s = summarise(rows)
    assert s["window_start"] == datetime.date(2026, 8, 18)
    assert s["window_end"] == datetime.date(2026, 8, 30)
    assert s["window_days"] == 13


def test_long_range_bias_is_weighted_by_sample_size():
    """Averaged across the deep leads, weighted, so one thin day cannot swing
    the editorial claim that the forecast runs cold."""
    rows = [_row(5, 19.0, 21.0) for _ in range(10)]   # -2.0, n=10
    rows += [_row(6, 21.5, 21.0)]                     # +0.5, n=1
    s = summarise(rows)
    # weighted: (-2.0*10 + 0.5*1) / 11 = -1.77...
    assert s["long_range_bias_c"] == -1.77
    assert s["long_range_direction"] == "cold"


def test_skill_curve_is_ordered_by_lead_time():
    rows = [_row(6, 20.0, 20.0), _row(0, 20.0, 20.0), _row(3, 20.0, 20.0)]
    assert [c["lead_days"] for c in skill_curve(rows)] == [0, 3, 6]


def test_payload_matches_the_shape_the_template_reads():
    """Cheap contract check: the template indexes these keys, and a rename
    here would otherwise surface as a blank page rather than a failure."""
    rows = [_row(0, 20.0, 20.0), _row(5, 19.0, 21.0)]
    payload = verification_payload(rows)
    assert set(payload) == {"summary", "skill_curve", "cities", "has_data"}
    assert payload["has_data"] is True
    for key in ("total_pairs", "same_day_mae_c", "long_range_bias_c",
                "window_start", "window_end", "window_days"):
        assert key in payload["summary"]
    for key in ("lead_days", "pairs", "bias_c", "mae_c", "direction", "thin"):
        assert key in payload["skill_curve"][0]
