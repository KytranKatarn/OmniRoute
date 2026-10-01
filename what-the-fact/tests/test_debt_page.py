"""/debt — real federal fiscal data (StatCan), reduced from design-handoff/wtf-debt.html.

Layers: the pure view-model (consumer/debt_data.py), the ingest parsers
(ingest/market/fiscal_federal.py), wiring (weekly run + drift guard + route), and the
template rendering real vs empty data. The honesty rules are asserted, not assumed:
no zero-filled gaps, no partial-year-vs-full-year ranking, no Public-Accounts labels.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consumer import debt_data as dd  # noqa: E402
from ingest.market import fiscal_federal as ff  # noqa: E402

TPL = ROOT / "consumer" / "templates"


def _annual(years, over=None):
    over = over or {}
    rows = []
    for y in years:
        base = {"revenue": 400_000.0 + y, "expense": 450_000.0 + y, "net_lending": -50_000.0,
                "net_financial_worth": -900_000.0, "interest": 40_000.0, "gdp_nominal": 3_000_000.0}
        base.update(over.get(y, {}))
        for k, v in base.items():
            if v is not None:
                rows.append({"ref_year": y, "item_key": k, "value_millions": v})
    return rows


def _q(year, quarter, **v):
    base = {"revenue": 100_000.0, "expense": 110_000.0, "net_lending": -10_000.0,
            "interest": 10_000.0, "net_financial_worth": -950_000.0}
    base.update(v)
    return [{"ref_quarter": dt.date(year, 3 * quarter - 2, 1), "item_key": k, "value_millions": x}
            for k, x in base.items()]


# --------------------------------------------------------------------------- view-model
def test_empty_ingest_gives_none_not_zeros():
    assert dd.build([], []) is None


def test_a_year_without_revenue_and_expense_is_not_a_year():
    rows = [r for r in _annual([2023]) if r["item_key"] != "expense"]
    assert dd.build(rows, []) is None


def test_net_debt_is_the_sign_flipped_net_financial_worth_in_billions():
    d = dd.build(_annual([2024]), [])
    assert d["latest"]["net_debt"] == pytest.approx(900.0)
    assert d["latest"]["net_debt_gdp"] == pytest.approx(30.0)


def test_ratio_is_none_when_gdp_is_missing_never_zero():
    d = dd.build(_annual([2024], {2024: {"gdp_nominal": None}}), [])
    assert d["latest"]["net_debt_gdp"] is None and d["latest"]["balance_gdp"] is None


def test_window_is_eleven_years_max_newest_last():
    d = dd.build(_annual(range(1990, 2026)), [])
    assert [r["year"] for r in d["rows"]] == list(range(2015, 2026))


def test_breakdown_shares_sum_to_100_with_remainder_row():
    d = dd.build(_annual([2024], {2024: {"revenue": 1000.0, "taxes_income": 600.0, "taxes_goods_services": 200.0}}), [])
    rows = d["revenue_breakdown"]
    assert sum(r["share"] for r in rows) == pytest.approx(100.0)
    assert rows[-1]["label"] == "Everything else" and rows[-1]["value"] == pytest.approx(0.2)


def test_ytd_uses_whole_quarters_and_the_same_quarters_a_year_earlier():
    q = _q(2025, 1, revenue=100_000) + _q(2025, 2, revenue=110_000) + _q(2026, 1, revenue=120_000) + _q(2026, 2, revenue=130_000)
    y = dd.build(_annual([2025]), q)["ytd"]
    assert y["year"] == 2026 and y["quarters"] == [1, 2] and y["through"] == "June 2026"
    m = y["metrics"]["revenue"]
    assert (m["value"], m["year_ago"], m["change"]) == (pytest.approx(250.0), pytest.approx(210.0), pytest.approx(40.0))
    assert y["comparable"] is True


def test_ytd_without_a_year_ago_quarter_is_not_compared():
    y = dd.build(_annual([2025]), _q(2026, 1))["ytd"]
    assert y["comparable"] is False and y["metrics"]["revenue"]["year_ago"] is None


def test_ytd_requires_a_run_starting_at_q1():
    assert dd.build(_annual([2025]), _q(2026, 2))["ytd"] is None


def test_no_ytd_when_the_newest_year_is_complete_and_already_annual():
    q = sum((_q(2025, i) for i in (1, 2, 3, 4)), [])
    assert dd.build(_annual([2025]), q)["ytd"] is None


def test_quarter_rows_carry_like_for_like_change_newest_first():
    q = _q(2025, 2, revenue=100_000) + _q(2026, 2, revenue=130_000)
    rows = dd.build(_annual([2025]), q)["quarters"]
    assert rows[0]["label"] == "Q2 2026" and rows[0]["revenue_yoy"] == pytest.approx(30.0)
    assert rows[1]["revenue_yoy"] is None  # nothing a year before Q2 2025 → no invented figure


def test_verdict_compares_with_prior_year_and_2019_and_names_direction():
    rows = _annual([2019, 2024, 2025], {2019: {"interest": 20_000.0}, 2025: {"interest": 30_000.0}})
    v = {x["title"]: x for x in dd.build(rows, [])["verdict"]}
    i = v["Interest as a share of revenue"]
    assert i["vs_prior"]["word"] == "improved" and i["vs_base"]["word"] == "worsened"


def test_direction_is_symmetric_and_has_a_tolerance():
    assert dd._direction(1.0, 1.02) == "about the same"
    assert dd._direction(1.0, 2.0, lower_is_better=True) == "improved"
    assert dd._direction(1.0, 2.0, lower_is_better=False) == "worsened"


# --------------------------------------------------------------------------- ingest parsers
def _wds(vector_id, points, status="SUCCESS"):
    return {"status": status, "object": {"vectorId": vector_id, "vectorDataPoint": points}}


def _pt(ref, value, scalar=6):
    return {"refPer": ref, "value": value, "scalarFactorCode": scalar, "releaseTime": "2026-09-01T08:30"}


def test_annual_rows_skip_missing_values_never_zero_fill():
    payload = [_wds(ff.FEDERAL_VECTORS["revenue"], [_pt("2024-01-01", "486736"), _pt("2025-01-01", None), _pt("2023-01-01", "")])]
    rows, _ = ff.build_annual_rows(payload)
    assert [(r["ref_year"], r["value_millions"]) for r in rows] == [(2024, 486736.0)]


def test_annual_rows_reject_a_non_million_scalar():
    rows, errors = ff.build_annual_rows([_wds(ff.FEDERAL_VECTORS["revenue"], [_pt("2024-01-01", "1", scalar=9)])])
    assert rows == [] and any("scalar" in e for e in errors)


def test_one_failed_vector_does_not_discard_the_good_ones():
    payload = [_wds(ff.FEDERAL_VECTORS["revenue"], [_pt("2024-01-01", "5")]),
               _wds(ff.FEDERAL_VECTORS["expense"], [], status="FAILED")]
    rows, errors = ff.build_annual_rows(payload)
    assert {r["item_key"] for r in rows} == {"revenue"} and any("expense" in e for e in errors)


def test_gdp_is_the_mean_of_four_quarters_and_incomplete_years_are_dropped():
    pts = [_pt(f"2024-{m:02d}-01", str(v)) for m, v in ((1, 100), (4, 200), (7, 300), (10, 400))] + [_pt("2025-01-01", "999"), _pt("2025-04-01", "999")]
    rows, _ = ff.build_gdp_rows([_wds(ff.GDP_VECTOR, pts)])
    assert [(r["ref_year"], r["value_millions"], r["derived"]) for r in rows] == [(2024, 250.0, True)]


def test_quarterly_rows_reject_a_non_quarter_start():
    rows, errors = ff.build_quarterly_rows([_wds(ff.QUARTERLY_VECTORS["revenue"], [_pt("2026-02-01", "1"), _pt("2026-04-01", "2")])])
    assert [r["ref_quarter"] for r in rows] == [dt.date(2026, 4, 1)] and any("odd quarter" in e for e in errors)


def test_every_vector_maps_to_exactly_one_key():
    assert len(set(ff.FEDERAL_VECTORS.values())) == len(ff.FEDERAL_VECTORS)
    assert len(set(ff.QUARTERLY_VECTORS.values())) == len(ff.QUARTERLY_VECTORS)


# --------------------------------------------------------------------------- wiring
def test_ingest_is_scheduled_and_watched():
    run = (ROOT / "ingest" / "run.py").read_text(encoding="utf-8")
    guard = (ROOT / "ingest" / "parliament" / "drift_guard.py").read_text(encoding="utf-8")
    assert "run_fiscal_federal" in run and "_last_fiscal_week" in run
    from ingest.parliament import drift_guard
    assert "fiscal_federal" in drift_guard._MAX_AGE_DAYS and "fiscal_federal" in drift_guard._REQUIRED_TASKS
    assert "fiscal_federal" in guard


def test_debt_is_a_real_route_not_a_coming_soon_placeholder():
    src = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
    assert '@bp.get("/debt")' in src
    assert '    "debt": (' not in src


# --------------------------------------------------------------------------- template
def _render(d):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block title %}{% endblock %}{% block meta %}{% endblock %}<body>{% block content %}{% endblock %}</body>"}),
                                           FileSystemLoader(str(TPL))]), autoescape=True)
    return env.get_template("debt.html").render(d=d, is_subscriber=False)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S)))


def test_empty_state_is_honest_and_shows_no_figures():
    t = _text(_render(None))
    assert "has not been loaded yet" in t and "$" not in t


def test_real_data_page_states_calendar_year_basis_and_year_to_date():
    q = _q(2025, 1) + _q(2025, 2) + _q(2026, 1) + _q(2026, 2)
    t = _text(_render(dd.build(_annual(range(2015, 2026)), q)))
    assert "calendar years" in t and "Public Accounts" in t
    assert "2026 so far" in t and "first 2 quarters" in t and "not yet a full year" in t
    assert "Quarter by quarter" in t and "Better or worse?" in t


def test_page_never_claims_what_the_data_cannot_show():
    t = _text(_render(dd.build(_annual(range(2015, 2026)), [])))
    assert "exceed what Ottawa transfers for health" not in t  # the design's unprovable sentence
    assert "Public Accounts of Canada, Volume II" not in t


def test_negative_amounts_put_the_sign_before_the_dollar():
    t = _text(_render(dd.build(_annual(range(2015, 2026)), [])))
    assert "−$50.0B" in t and "$-" not in t


def test_the_current_year_is_not_ranked_against_full_years_in_the_annual_table():
    q = _q(2026, 1)
    html = _render(dd.build(_annual(range(2015, 2026)), q))
    table = html[html.index("Revenue in, expenses out"):]
    assert "2026" not in table.split("</table>")[0]
