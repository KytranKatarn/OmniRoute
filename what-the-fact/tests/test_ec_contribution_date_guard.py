"""EC contribution dates: a 'received' date cannot be in the future (beyond a few days of slack).

Measured 2026-10-07: 44 rows ($9.5K) dated up to 2027-09-20 got through the old +366-day bound — monthly-instalment-looking
rows on Annual riding returns — so the riding donor panel showed an 'Annual 2027' line. The guard now stores NULL for them.
"""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "ingest" / "parliament" / "elections_canada.py"
TODAY = date(2026, 10, 7)


def _load(text=None):
    spec = importlib.util.spec_from_loader("ec_mod", loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(text or SRC.read_text(encoding="utf-8"), str(SRC), "exec"), mod.__dict__)
    return mod


def test_the_real_future_rows_are_rejected_and_counted():
    ec = _load()
    ec._DATE_REJECTS["n"] = 0
    for d in ("2027-09-20", "2027-05-20", "2026-12-31"):
        assert ec._parse_date(d, today=TODAY) is None
    assert ec._DATE_REJECTS["n"] == 3


def test_the_slack_boundary_is_31_days():
    ec = _load()
    assert ec._parse_date((TODAY + timedelta(days=31)).isoformat(), today=TODAY) == "2026-11-07"
    assert ec._parse_date((TODAY + timedelta(days=32)).isoformat(), today=TODAY) is None


def test_ordinary_and_old_dates_pass_and_artifacts_still_fail():
    ec = _load()
    assert ec._parse_date("2026-10-07", today=TODAY) == "2026-10-07"
    assert ec._parse_date("2000-03-25", today=TODAY) == "2000-03-25"
    for bad in ("1989-12-31", "0025-04-07", "2923-12-28", "not a date"):
        assert ec._parse_date(bad, today=TODAY) is None


def test_empty_is_none_and_not_counted_as_a_reject():
    ec = _load()
    ec._DATE_REJECTS["n"] = 0
    assert ec._parse_date("", today=TODAY) is None and ec._parse_date(None, today=TODAY) is None
    assert ec._DATE_REJECTS["n"] == 0


def test_the_old_366_day_bound_would_have_let_the_rows_through():
    """Non-vacuity: same tests against a copy with the pre-fix bound — the real row slips through."""
    old = _load(SRC.read_text(encoding="utf-8").replace("_MAX_FUTURE_DAYS = 31", "_MAX_FUTURE_DAYS = 366"))
    assert old._parse_date("2027-09-20", today=TODAY) == "2027-09-20"
