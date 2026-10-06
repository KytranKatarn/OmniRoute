"""/cost headline window: a TRAILING window of at most five COMPLETE years, so every "5-year" name stays true.

2026-10-06: /cost showed 2021-2025 and carried 2026 only as an addendum line (2 of 4 quarters disclosed). Reading
cost.py for that turned up a 2027 trap: the window was "every year with 4 quarters", uncapped, so 2026 completing
(~Feb 2027, once its Q2+Q3 land) would have made the headline SIX years under keys and copy that say 5-year
(grand_total_5yr, five_year_total, "5-year cost"; civic-watch reads the same payload). The window is now capped at
the last five complete years: 2027 rolls it to 2022-2026 and 2021 drops out.
"""
import contextlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import cost  # noqa: E402

Q4 = {"Q1", "Q2", "Q3", "Q4"}


def _quarters(**by_year):
    return {int(k[1:]): set(v) for k, v in by_year.items()}


# ------------------------------------------------------------------------------------------ window_years

def test_today_the_window_is_2021_2025_and_2026_is_the_partial_year():
    w, cur, retired = cost.window_years(_quarters(y2020={"Q2", "Q3"}, y2021=Q4, y2022=Q4, y2023=Q4, y2024=Q4,
                                                  y2025=Q4, y2026={"Q1", "Q4"}))
    assert w == (2021, 2022, 2023, 2024, 2025) and cur == 2026 and retired == ()


def test_when_2026_completes_the_window_rolls_and_2021_drops_off():
    w, cur, retired = cost.window_years(_quarters(y2020={"Q2", "Q3"}, y2021=Q4, y2022=Q4, y2023=Q4, y2024=Q4,
                                                  y2025=Q4, y2026=Q4, y2027={"Q4"}))
    assert w == (2022, 2023, 2024, 2025, 2026) and len(w) == 5     # never six
    assert cur == 2027 and retired == (2021,)


def test_a_year_with_three_quarters_is_still_partial():
    w, cur, _ = cost.window_years(_quarters(y2021=Q4, y2022=Q4, y2023=Q4, y2024=Q4, y2025=Q4,
                                            y2026={"Q1", "Q2", "Q3"}))
    assert 2026 not in w and cur == 2026


def test_fewer_than_five_complete_years_gives_a_shorter_window_not_a_padded_one():
    w, cur, retired = cost.window_years(_quarters(y2024=Q4, y2025=Q4, y2026={"Q4"}))
    assert w == (2024, 2025) and cur == 2026 and retired == ()


def test_an_empty_table_falls_back_to_the_static_years():
    assert cost.window_years({})[0] == cost.YEARS


def test_the_window_size_is_the_five_that_the_names_promise():
    assert cost.WINDOW_SIZE == 5


# ----------------------------------------------------------------------- the real summary builder, faked DB

# A consistent fake: every year's expenses follow ONE seasonal shape, so a projection is exactly predictable.
SHAPE = {"Q4": 0.30, "Q1": 0.20, "Q2": 0.25, "Q3": 0.25}          # Q4 = Jan-Mar ... as disclosed: Q4, Q1, Q2, Q3
ANNUAL = {"mp": 10_000_000.0, "senator": 1_000_000.0, "ministerial": 400_000.0}


class _Res:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows
    def scalar(self): return self.rows[0][0] if self.rows else None


def _series(years, kind):
    return [(y, q, ANNUAL[kind] * SHAPE[q]) for y in sorted(years) for q in years[y]]


class _Conn:
    snapshots = None       # rows to return for the snapshot ledger; None => the table does not exist

    def __init__(self, years):
        self.years = years      # {year: [quarters]}

    def execute(self, sql, params=None):
        s = str(sql)
        ys = sorted(self.years)
        for kind in ("mp", "senator", "ministerial"):
            if "quarter_series:" + kind in s:
                return _Res(_series(self.years, kind))
        if "cost_projection_snapshots" in s:
            if self.snapshots is None:
                raise RuntimeError("relation does not exist")
            return _Res(self.snapshots)
        if "indemnity_rates" in s:
            return _Res([(y, role, amt) for y in range(2019, 2031) for role, amt in (("mp", 100000.0), ("senator", 150000.0))])
        if "array_agg" in s:
            return _Res([(y, list(self.years[y])) for y in ys])
        if "cabinet_role" in s:
            return _Res([])
        if "senator_expenses" in s:
            return _Res([(y, 90, sum(ANNUAL["senator"] * SHAPE[q] for q in self.years[y])) for y in ys])
        if "minister_travel" in s:
            return _Res([(y, sum(ANNUAL["ministerial"] * SHAPE[q] for q in self.years[y])) for y in ys])
        if "mp_expenses" in s:                       # office_rows
            return _Res([(y, 300, sum(ANNUAL["mp"] * SHAPE[q] for q in self.years[y])) for y in ys])
        raise AssertionError("unexpected SQL: " + s[:80])


class _Engine:
    def __init__(self, years, snapshots=None):
        self.years, self.snapshots = years, snapshots
    def connect(self):
        c = _Conn(self.years)
        c.snapshots = self.snapshots
        return contextlib.nullcontext(c)


TODAY = {2020: ["Q2", "Q3"], 2021: sorted(Q4), 2022: sorted(Q4), 2023: sorted(Q4), 2024: sorted(Q4),
         2025: sorted(Q4), 2026: ["Q1", "Q4"]}
THREE = {**TODAY, 2026: ["Q1", "Q2", "Q4"]}
ROLLED = {**TODAY, 2026: sorted(Q4), 2027: ["Q4"]}


def _ytd(d):
    return [a for a in d["addenda"] if a["kind"] == "latest_ytd"][0]


def test_summary_today_shows_2026_only_as_the_year_to_date_addendum():
    d = cost.parliament_cost_summary(_Engine(TODAY))
    assert d["window"]["years"] == [2021, 2022, 2023, 2024, 2025]
    assert [r["year"] for r in d["by_year"]] == [2021, 2022, 2023, 2024, 2025]
    assert {a["year"]: a["kind"] for a in d["addenda"]} == {2020: "partial_pre_window", 2026: "latest_ytd"}


def test_summary_after_2026_completes_is_still_five_years_and_the_total_matches():
    d = cost.parliament_cost_summary(_Engine(ROLLED))
    assert d["window"]["years"] == [2022, 2023, 2024, 2025, 2026]
    assert d["window"]["label"].startswith("5 complete fiscal years (2022")
    assert d["grand_total_5yr"] == sum(r["total"] for r in d["by_year"])     # the "5yr" key sums exactly 5 years
    assert 2021 not in [r["year"] for r in d["by_year"]]


def test_a_complete_year_that_rolled_off_is_not_reported_as_partial():
    d = cost.parliament_cost_summary(_Engine(ROLLED))
    assert {a["year"]: a["kind"] for a in d["addenda"]} == {2020: "partial_pre_window", 2027: "latest_ytd"}


def test_the_current_year_addendum_carries_what_the_chart_bar_needs():
    d = cost.parliament_cost_summary(_Engine(TODAY))
    ytd = _ytd(d)
    for k in ("year", "quarters", "parliamentary", "mp_indemnity", "mp_office", "senator"):
        assert k in ytd
    assert ytd["parliamentary"] == ytd["mp_office"] + ytd["mp_indemnity"] + ytd["senator"]
    assert d["grand_total_5yr"] == sum(r["total"] for r in d["by_year"])     # the partial year is NOT in it


# ----------------------------------------------------------------- partial-year salary is prorated (task #7130)

def test_prorate_scales_an_annual_amount_to_the_quarters_disclosed():
    assert cost._prorate(200_000, 2) == 100_000
    assert cost._prorate(200_000, 1) == 50_000
    assert cost._prorate(200_000, 4) == 200_000
    assert cost._prorate(200_000, 0) == 0 and cost._prorate(None, 2) == 0
    assert cost._prorate(200_000, 9) == 200_000          # never more than a year


def test_a_two_quarter_year_carries_two_quarters_of_salary_not_four():
    """The fake DB gives 300 MPs at a $100k rate: a full year of salary is $30M, so 2 quarters = $15M."""
    ytd = _ytd(cost.parliament_cost_summary(_Engine(TODAY)))
    assert ytd["mp_indemnity"] == 15_000_000
    assert ytd["senator"] == 500_000 + 90 * 150_000 // 2            # half a year of senator office + half the base
    assert ytd["parliamentary"] == ytd["mp_office"] + ytd["mp_indemnity"] + ytd["senator"]


def test_complete_years_still_carry_a_full_year_of_salary():
    d = cost.parliament_cost_summary(_Engine(TODAY))
    assert all(r["mp_indemnity_total"] == 300 * 100_000 for r in d["by_year"])


def test_a_year_with_no_rates_gets_no_invented_salary():
    class NoRates(_Conn):
        def execute(self, sql, params=None):
            if "indemnity_rates" in str(sql):
                return _Res([(y, r, a) for y in range(2019, 2026) for r, a in (("mp", 100000.0), ("senator", 150000.0))])
            return super().execute(sql, params)

    class E(_Engine):
        def connect(self): return contextlib.nullcontext(NoRates(self.years))

    assert _ytd(cost.parliament_cost_summary(E(TODAY)))["mp_indemnity"] == 0


# -------------------------------------------------------------------------------- the seasonal projection

def _s(**years):
    return {int(k[1:]): v for k, v in years.items()}


def _full(total, shape=SHAPE):
    return {q: total * f for q, f in shape.items()}


def test_projection_divides_by_the_same_quarters_share_of_prior_years_not_by_a_flat_four_over_n():
    ser = _s(y2021=_full(100), y2022=_full(100), y2023=_full(100), y2026={"Q4": 30, "Q1": 20})
    r = cost.seasonal_projection(ser, 2026)
    assert r["method"] == "seasonal" and r["projected"] == 100 and r["share"] == pytest.approx(0.5)
    # a flat x2 of a Q4+Q1 that are 60/40 of a year would be wrong; the share is what matters
    heavy = {q: 100 * f for q, f in {"Q4": 0.40, "Q1": 0.20, "Q2": 0.20, "Q3": 0.20}.items()}
    r = cost.seasonal_projection(_s(y2021=heavy, y2022=heavy, y2026={"Q4": 40, "Q1": 20}), 2026)
    assert r["projected"] == 100                        # 60 / 0.60, not 60 x 2 = 120


def test_one_disrupted_year_does_not_drag_the_projection_the_median_resists_it_and_the_range_shows_it():
    odd = {"Q4": 36.0, "Q1": 22.5, "Q2": 43.0, "Q3": 47.0}     # 2025: an election year, Jan-Jun only 39% of the year
    ser = _s(y2021=_full(100), y2022=_full(100), y2023=_full(100), y2024=_full(100), y2025=odd, y2026={"Q4": 30, "Q1": 20})
    r = cost.seasonal_projection(ser, 2026)
    assert r["projected"] == 100                        # median share 0.50 — the outlier year did not move it
    assert r["high"] > 120 and r["low"] == 100          # ...but the range admits that year happened


def test_only_prior_years_supply_the_shares_never_later_ones():
    """A year that has not happened yet (or the year being projected) must not move the share."""
    odd = {"Q4": 5.0, "Q1": 5.0, "Q2": 5.0, "Q3": 85.0}
    base = _s(y2021=_full(100), y2022=_full(100), y2024={"Q4": 30, "Q1": 20})
    with_later = {**base, 2025: odd, 2026: odd, 2027: odd, 2028: odd}
    assert cost.seasonal_projection(with_later, 2024) == cost.seasonal_projection(base, 2024)


def test_with_too_few_prior_years_it_falls_back_to_plain_annualizing_with_no_range():
    r = cost.seasonal_projection(_s(y2025=_full(100), y2026={"Q4": 30, "Q1": 20}), 2026)
    assert r["method"] == "annualized" and r["projected"] == 100 and r["low"] == r["high"] == 100


def test_no_projection_from_one_quarter_or_for_a_complete_year_or_from_nothing():
    ser = _s(y2021=_full(100), y2022=_full(100), y2026={"Q4": 30})
    assert cost.seasonal_projection(ser, 2026) is None                       # one quarter
    assert cost.seasonal_projection(_s(y2021=_full(100), y2022=_full(100), y2026=_full(100)), 2026) is None
    assert cost.seasonal_projection(_s(y2021=_full(100)), 2026) is None


def test_the_quarters_used_are_the_ones_actually_disclosed_not_the_first_n():
    """The ministerial series had Q1, Q2 and Q4 on file (no Q3): shares must be taken over THOSE quarters."""
    ser = _s(y2021=_full(100), y2022=_full(100), y2026={"Q4": 30, "Q1": 20, "Q2": 25})
    r = cost.seasonal_projection(ser, 2026)
    assert r["share"] == pytest.approx(0.75) and r["projected"] == 100


def test_summary_projects_exactly_the_year_when_the_shape_is_stable_and_counts_salary_once():
    d = cost.parliament_cost_summary(_Engine(TODAY))
    p = _ytd(d)["projected"]
    full_year_salary = 300 * 100_000
    assert p["method"] == "seasonal"
    assert p["mp"] == round(ANNUAL["mp"]) + full_year_salary                          # office 10M + a YEAR of salary
    assert p["senator"] == round(ANNUAL["senator"]) + 90 * 150_000
    assert p["parliamentary"] == p["mp"] + p["senator"]
    assert p["combined"] == p["parliamentary"] + round(ANNUAL["ministerial"])
    assert p["from_quarters"] == 2


def test_the_projection_is_the_same_after_three_quarters_when_nothing_unusual_happened():
    two = _ytd(cost.parliament_cost_summary(_Engine(TODAY)))["projected"]
    three = _ytd(cost.parliament_cost_summary(_Engine(THREE)))["projected"]
    assert three["parliamentary"] == two["parliamentary"] and three["from_quarters"] == 3


def test_a_one_quarter_year_has_no_projection():
    d = cost.parliament_cost_summary(_Engine({**TODAY, 2026: ["Q4"]}))
    assert _ytd(d)["projected"] is None


def test_the_range_widens_with_a_disrupted_year_and_never_excludes_the_estimate():
    odd = {2025: ["Q1", "Q2", "Q3", "Q4"]}
    p = _ytd(cost.parliament_cost_summary(_Engine(TODAY)))["projected"]
    assert p["low"] <= p["parliamentary"] <= p["high"] and p["combined_low"] <= p["combined"] <= p["combined_high"]


# ------------------------------------------------------------------------------------ backtest + ledger

def test_backtest_is_out_of_sample_a_later_year_cannot_change_an_earlier_projection():
    base = _s(y2021=_full(100), y2022=_full(100), y2023=_full(100), y2024=_full(100))
    series = {"mp": base, "senator": base}
    first = [r for r in cost.projection_backtest(series) if r["year"] == 2024]
    odd = {**base, 2025: {"Q4": 5.0, "Q1": 5.0, "Q2": 5.0, "Q3": 90.0}}
    after = [r for r in cost.projection_backtest({"mp": odd, "senator": odd}) if r["year"] == 2024]
    assert first == after and first                       # 2025 existing did not leak into 2024's projection


def test_backtest_reports_zero_error_for_a_stable_shape_and_a_signed_error_for_a_disrupted_year():
    odd = {"Q4": 36.0, "Q1": 22.5, "Q2": 43.0, "Q3": 47.0}     # first two quarters = 39% of the year
    ser = _s(y2021=_full(100), y2022=_full(100), y2023=_full(100), y2024=_full(100), y2025=odd)
    rows = {(r["year"], r["stage_quarters"]): r for r in cost.projection_backtest({"mp": ser, "senator": ser})}
    assert rows[(2024, 2)]["error_pct"] == 0.0
    assert rows[(2025, 2)]["error_pct"] < -15              # under-projected: the year spent more than its pattern implied
    assert rows[(2025, 2)]["actual"] == round(sum(odd.values()))


def test_the_summary_exposes_the_track_record_and_a_typical_error():
    t = cost.parliament_cost_summary(_Engine(TODAY))["projection_track_record"]
    assert t["backtest"] and all(set(r) == {"year", "stage_quarters", "projected", "actual", "error_pct"} for r in t["backtest"])
    assert t["typical_error_pct"]["2"] == 0.0 and t["snapshots"] == []        # no ledger table in the fake => no history


def test_published_snapshots_are_compared_with_the_actual_once_the_year_is_complete():
    import datetime
    rows = [(2025, "Q1,Q4", datetime.datetime(2025, 10, 6), 9_000_000, 9_500_000, 8_000_000, 10_000_000, "seasonal"),
            (2026, "Q1,Q4", datetime.datetime(2026, 10, 6), 31_000_000, 31_400_000, 30_000_000, 33_000_000, "seasonal")]
    t = cost.parliament_cost_summary(_Engine(TODAY, snapshots=rows))["projection_track_record"]
    done = [r for r in t["snapshots"] if r["year"] == 2025][0]
    live = [r for r in t["snapshots"] if r["year"] == 2026][0]
    assert "actual" in done and done["error_pct"] == round((9_000_000 - done["actual"]) / done["actual"] * 100, 1)
    assert "actual" not in live and "error_pct" not in live      # 2026 is not complete: nothing to compare yet


def test_snapshot_records_the_current_projection_once_per_quarter_set():
    class C:
        def __init__(self): self.sql = []
        def execute(self, sql, params=None):
            self.sql.append((str(sql), params))
            return type("R", (), {"rowcount": 1})()
    class E(_Engine):
        def __init__(self, years, conn): super().__init__(years); self.c = conn
        def begin(self): return contextlib.nullcontext(self.c)
    conn = C()
    out = cost.snapshot_projection(E(TODAY, conn))
    assert out["recorded"] is True and out["year"] == 2026 and out["quarters"] == "Q1,Q4"
    sql, params = conn.sql[0]
    assert "ON CONFLICT (year, quarters_key) DO NOTHING" in sql        # a later run with the same quarters changes nothing
    assert params["k"] == "Q1,Q4" and params["p"] == _ytd(cost.parliament_cost_summary(_Engine(TODAY)))["projected"]["parliamentary"]


def test_snapshot_with_nothing_to_project_records_nothing():
    class E(_Engine):
        def begin(self): raise AssertionError("must not write")
    assert cost.snapshot_projection(E({**TODAY, 2026: ["Q4"]}))["recorded"] is False


# ----------------------------------------------------------------------------------------- member panels

class _MemberConn:
    """Answers the member block's queries: the member's distinct quarters, and the national quarter series."""
    def __init__(self, quarters, years):
        self.q, self.years = quarters, years
    def execute(self, sql, params=None):
        s = str(sql)
        for kind in ("mp", "senator", "ministerial"):
            if "quarter_series:" + kind in s:
                return _Res(_series(self.years, kind))
        if "DISTINCT RIGHT(period" in s:
            return _Res([(q,) for q in self.q])
        raise AssertionError(s[:60])


def _member(quarters, table="parliament.mp_expenses"):
    core = lambda conn, sid, cur, rates: {"served": True, "total": 0, "office_total": 50_000,     # noqa: E731
                                           "indemnity": 200_000, "top_up": 100_000}
    orig = cost._current_partial_year
    cost._current_partial_year = lambda conn: 2026
    try:
        return cost._current_year_block(_MemberConn(quarters, TODAY), core, table, "mp_id", 1, {})
    finally:
        cost._current_partial_year = orig


def test_member_block_prorates_the_year_to_date_and_projects_office_by_the_national_share():
    b = _member(["Q4", "Q1"])
    assert (b["indemnity"], b["top_up"]) == (100_000, 50_000)                  # half a year of each
    assert b["total"] == 50_000 + 100_000 + 50_000
    assert b["projected_full_year"] == 100_000 + 200_000 + 100_000             # office 50k / 0.50 share; salary ONCE


def test_member_block_has_no_projection_from_one_quarter():
    assert _member(["Q4"])["projected_full_year"] is None


def test_senator_member_block_uses_the_senator_series():
    b = _member(["Q4", "Q1"], table="parliament.senator_expenses")
    assert b["projected_full_year"] == 100_000 + 200_000 + 100_000
