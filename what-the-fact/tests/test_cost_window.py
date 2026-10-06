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

class _Res:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class _Conn:
    def __init__(self, years):
        self.years = years      # {year: [quarters]}

    def execute(self, sql, params=None):
        s = str(sql)
        ys = sorted(self.years)
        if "indemnity_rates" in s:
            return _Res([(y, role, amt) for y in range(2019, 2031) for role, amt in (("mp", 100000.0), ("senator", 150000.0))])
        if "array_agg" in s:
            return _Res([(y, list(self.years[y])) for y in ys])
        if "cabinet_role" in s:
            return _Res([])
        if "senator_expenses" in s:
            return _Res([(y, 90, 1000000.0) for y in ys])
        if "minister_travel" in s:
            return _Res([(y, 50000.0) for y in ys])
        if "mp_expenses" in s:                       # office_rows
            return _Res([(y, 300, 10000000.0) for y in ys])
        raise AssertionError("unexpected SQL: " + s[:80])


class _Engine:
    def __init__(self, years): self.years = years
    def connect(self): return contextlib.nullcontext(_Conn(self.years))


TODAY = {2020: ["Q2", "Q3"], 2021: sorted(Q4), 2022: sorted(Q4), 2023: sorted(Q4), 2024: sorted(Q4),
         2025: sorted(Q4), 2026: ["Q1", "Q4"]}
ROLLED = {**TODAY, 2026: sorted(Q4), 2027: ["Q4"]}


def test_summary_today_shows_2026_only_as_the_year_to_date_addendum():
    d = cost.parliament_cost_summary(_Engine(TODAY))
    assert d["window"]["years"] == [2021, 2022, 2023, 2024, 2025]
    assert [r["year"] for r in d["by_year"]] == [2021, 2022, 2023, 2024, 2025]
    kinds = {a["year"]: a["kind"] for a in d["addenda"]}
    assert kinds == {2020: "partial_pre_window", 2026: "latest_ytd"}


def test_summary_after_2026_completes_is_still_five_years_and_the_total_matches():
    d = cost.parliament_cost_summary(_Engine(ROLLED))
    assert d["window"]["years"] == [2022, 2023, 2024, 2025, 2026]
    assert d["window"]["label"].startswith("5 complete fiscal years (2022")
    assert len(d["by_year"]) == 5
    assert d["grand_total_5yr"] == sum(r["total"] for r in d["by_year"])     # the "5yr" key sums exactly 5 years
    assert 2021 not in [r["year"] for r in d["by_year"]]


def test_a_complete_year_that_rolled_off_is_not_reported_as_partial():
    """2021 has all four quarters; labelling it 'partial_pre_window' in the addenda would be false."""
    d = cost.parliament_cost_summary(_Engine(ROLLED))
    assert 2021 not in [a["year"] for a in d["addenda"]]
    assert {a["year"]: a["kind"] for a in d["addenda"]} == {2020: "partial_pre_window", 2027: "latest_ytd"}


def test_the_current_year_addendum_carries_what_the_chart_bar_needs():
    d = cost.parliament_cost_summary(_Engine(TODAY))
    ytd = [a for a in d["addenda"] if a["kind"] == "latest_ytd"][0]
    for k in ("year", "quarters", "parliamentary", "mp_indemnity", "mp_office", "senator"):
        assert k in ytd
    assert ytd["parliamentary"] == ytd["mp_indemnity"] + ytd["mp_office"] + ytd["senator"]
    assert d["grand_total_5yr"] == sum(r["total"] for r in d["by_year"])     # the partial year is NOT in it
