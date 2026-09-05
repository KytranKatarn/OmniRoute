"""Regression coverage for /economy — the real six-indicator grid
(2026-09-05, WTF Batch 12, #6523).

Replaces the single-indicator (BoC rate only) version shipped in Batch 9
(#6272). The other five indicators now have real ingested sources:
market_watch.fx_rates (BoC Valet FXUSDCAD, PR #3204) and
market_watch.economic_indicators (StatCan WDS — CPI, unemployment, GDP,
housing starts; PR #3205), wired into the weekly ingest loop in PR #3206.

Everything numeric here traces to either (a) the pure helper functions in
consumer/routes.py, exercised directly on synthetic data (no DB, no
network, no app context — same pattern as test_rates_batch11.py's
`from consumer import routes as R`), or (b) a Jinja render of economy.html
with an explicit, hand-built context (same `_render`/DictLoader pattern).

Mutation check (house rule #7) run once at authoring time, by hand,
against the pre-fix economy.html — NOT a permanent test, per
feedback_mutation-check-no-runtime-git.md (HEAD stops being "pre-fix" the
moment this PR merges). Confirmed then: the pre-fix template contained the
literal strings "the other five aren't shown" and "invented numbers" in
its disclaimer paragraph, and had no `wtf-ec-ind` grid at all — this PR's
`test_old_disclaimer_language_is_gone` and
`test_indicator_grid_renders_all_six_real_cards` would both have failed
against it.
"""

from __future__ import annotations

import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROUTES_PY = ROOT / "consumer" / "routes.py"
TPL_DIR = ROOT / "consumer" / "templates"

from consumer import routes as R  # noqa: E402

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _d(s):
    return datetime.date.fromisoformat(s)


def _row(ref_date_s, value):
    return {"ref_date": _d(ref_date_s), "value": value}


# ────────────────────────── source-inspection (rule #6) ──────────────────

def _economy_route_body() -> str:
    src = ROUTES_PY.read_text(encoding="utf-8")
    start = src.index("def economy(")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def test_route_no_longer_hardcodes_a_single_indicator():
    body = _economy_route_body()
    assert "boc_current" not in body, "old single-indicator variable should be fully removed"
    assert "indicators" in body
    assert "market_watch.fx_rates" in body
    assert "market_watch.economic_indicators" in body


def test_each_indicator_block_is_independently_guarded():
    # One flaky table must degrade one card, never the whole page — same
    # principle the original single-card version already used.
    body = _economy_route_body()
    assert body.count("except Exception:") >= 3


# ────────────────────────── _econ_mini_chart ──────────────────────────────

def test_mini_chart_returns_none_for_fewer_than_two_points():
    assert R._econ_mini_chart([]) is None
    assert R._econ_mini_chart([(_d("2026-01-01"), 1.0)]) is None


def test_mini_chart_spans_full_width_and_tracks_min_max():
    series = [(_d("2025-01-01"), 2.0), (_d("2025-06-01"), 5.0), (_d("2026-01-01"), 1.0)]
    chart = R._econ_mini_chart(series, width=220, height=54, pad=4)
    assert chart["width"] == 220 and chart["height"] == 54
    points = chart["points"].split(" ")
    assert len(points) == 3
    first_x, first_y = (float(v) for v in points[0].split(","))
    last_x, last_y = (float(v) for v in points[-1].split(","))
    assert first_x == 4.0  # left pad, first date == t0
    assert last_x == 216.0  # width - pad, last date == t1
    # value 1.0 is the series min -> plotted at height - pad (bottom)
    assert last_y == 50.0
    assert chart["end_x"] == last_x and chart["end_y"] == last_y


# ────────────────────────── _econ_cpi_yoy ─────────────────────────────────

def test_cpi_yoy_requires_a_same_month_prior_year_row():
    # Only 13 months of data -> exactly ONE point has a same-month
    # prior-year match (the 13th row vs the 1st).
    rows = [_row(f"2025-{m:02d}-01", 100.0 + m) for m in range(1, 13)] + [_row("2026-01-01", 115.0)]
    yoy = R._econ_cpi_yoy(rows)
    assert len(yoy) == 1
    d, pct = yoy[0]
    assert d == _d("2026-01-01")
    assert round(pct, 4) == round((115.0 / 101.0 - 1) * 100, 4)


def test_cpi_yoy_empty_when_under_a_year_of_history():
    rows = [_row("2026-01-01", 100.0), _row("2026-02-01", 101.0)]
    assert R._econ_cpi_yoy(rows) == []


# ────────────────────────── _econ_gdp_mom ─────────────────────────────────

def test_gdp_mom_is_plain_consecutive_delta():
    rows = [_row("2026-01-01", 100.0), _row("2026-02-01", 101.0), _row("2026-03-01", 100.5)]
    mom = R._econ_gdp_mom(rows)
    assert len(mom) == 2
    assert round(mom[0][1], 4) == 1.0
    assert round(mom[1][1], 4) == round((100.5 / 101.0 - 1) * 100, 4)


def test_gdp_mom_empty_for_a_single_row():
    assert R._econ_gdp_mom([_row("2026-01-01", 100.0)]) == []


# ────────────────────────── _econ_indicator ───────────────────────────────

def test_indicator_formats_value_and_delta_from_the_series_own_endpoints():
    series = [(_d("2024-08-01"), "4.50"), (_d("2026-08-01"), "2.20")]
    ind = R._econ_indicator(
        key="overnight_rate", name="Overnight rate target", value="2.20", unit="%",
        source="BoC Valet V122514", href="/rates", series=series,
    )
    assert ind["value"] == "2.2%"
    assert ind["delta"]["text"] == "-2.3%"
    assert ind["delta"]["start_date"] == _d("2024-08-01")
    assert ind["delta"]["end_date"] == _d("2026-08-01")
    assert ind["chart"] is not None


def test_indicator_no_delta_when_series_has_under_two_points():
    ind = R._econ_indicator(
        key="housing_starts_saar", name="Housing starts", value=229, unit="",
        source="StatCan 34-10-0158-01 (CMHC starts)", href=None, series=[], decimals=0,
    )
    assert ind["value"] == "229"
    assert ind["delta"] is None
    assert ind["chart"] is None


def test_signed_flag_only_adds_plus_for_a_positive_value():
    up = R._econ_indicator(key="gdp_mom", name="GDP MoM", value=0.3, unit="%",
                            source="s", href=None, series=[], signed=True)
    down = R._econ_indicator(key="gdp_mom", name="GDP MoM", value=-0.2, unit="%",
                              source="s", href=None, series=[], signed=True)
    unsigned = R._econ_indicator(key="cpi_yoy", name="CPI", value=3.0, unit="%",
                                  source="s", href=None, series=[], signed=False)
    assert up["value"] == "+0.3%"
    assert down["value"] == "-0.2%"
    assert unsigned["value"] == "3.0%"  # no design precedent shows a '+' here


# ────────────────────────── template render ───────────────────────────────

def _render(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    base_ctx = dict(
        articles=[], economy_count=0, business_count=0, foreign_count=0,
        indicators=[], is_subscriber=False,
    )
    base_ctx.update(ctx)
    return env.get_template("economy.html").render(**base_ctx)


def _six_indicators():
    boc = R._econ_indicator(
        key="overnight_rate", name="Overnight rate target", value=2.2, unit="%",
        source="BoC Valet V122514", href="/rates",
        series=[(_d("2024-08-01"), 4.5), (_d("2026-08-01"), 2.2)],
    )
    fx = R._econ_indicator(
        key="cad_usd", name="CAD per USD", value=1.384, unit="", decimals=4,
        source="BoC Valet FXUSDCAD", href=None,
        series=[(_d("2024-09-27"), 1.35), (_d("2026-09-04"), 1.384)],
    )
    cpi = R._econ_indicator(
        key="cpi_yoy", name="CPI, year over year", value=3.0, unit="%",
        source="StatCan 18-10-0004-01", href=None,
        series=[(_d("2025-07-01"), 1.7), (_d("2026-07-01"), 3.0)],
    )
    unemployment = R._econ_indicator(
        key="unemployment_rate", name="Unemployment rate", value=6.4, unit="%",
        source="StatCan 14-10-0287-01 (LFS)", href=None,
        series=[(_d("2024-08-01"), 6.6), (_d("2026-08-01"), 6.4)],
    )
    gdp = R._econ_indicator(
        key="gdp_mom", name="Real GDP, monthly change", value=0.3, unit="%", signed=True,
        source="StatCan 36-10-0434-01", href=None,
        series=[(_d("2024-07-01"), 0.2), (_d("2026-06-01"), 0.3)],
    )
    housing = R._econ_indicator(
        key="housing_starts_saar", name="Housing starts, SAAR (000s)", value=229, unit="", decimals=0,
        source="StatCan 34-10-0158-01 (CMHC starts)", href=None,
        series=[(_d("2024-07-01"), 276), (_d("2026-07-01"), 229)],
    )
    return [boc, fx, cpi, unemployment, gdp, housing]


def test_indicator_grid_renders_all_six_real_cards():
    html = _render(indicators=_six_indicators())
    for name in ["Overnight rate target", "CAD per USD", "CPI, year over year",
                 "Unemployment rate", "Real GDP, monthly change",
                 "Housing starts, SAAR (000s)"]:
        assert name in html
    for source in ["BoC Valet V122514", "BoC Valet FXUSDCAD", "StatCan 18-10-0004-01",
                    "StatCan 14-10-0287-01", "StatCan 36-10-0434-01", "StatCan 34-10-0158-01"]:
        assert source in html
    assert html.count("wtf-ec-card") >= 6  # base + link variant classes


def test_only_the_boc_card_links_to_rates():
    html = _render(indicators=_six_indicators())
    assert 'href="/rates" class="wtf-ec-card wtf-ec-card-link"' in html
    # exactly one card is a link — the other five render as plain divs
    assert html.count('class="wtf-ec-card wtf-ec-card-link"') == 1


def test_chart_svg_present_when_indicator_has_a_series():
    html = _render(indicators=_six_indicators())
    assert html.count("<polyline") == 6


def test_empty_indicators_shows_unavailable_not_a_crash():
    html = _render(indicators=[])
    assert "temporarily unavailable" in html


def test_old_disclaimer_language_is_gone():
    html = _render(indicators=_six_indicators())
    low = html.lower()
    assert "the other five" not in low
    assert "invented numbers" not in low
    assert "only one of six" not in low


def test_paywall_is_unchanged_public_page():
    # /economy has never been paywall-gated (consistent with /weather) —
    # this must stay true after the rewrite. is_subscriber isn't read by
    # the template at all; rendering with both values must succeed.
    _render(indicators=_six_indicators(), is_subscriber=False)
    _render(indicators=_six_indicators(), is_subscriber=True)
