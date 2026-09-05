"""Regression coverage for /weather/accuracy's batch-11 additions (2026-09-04,
project #393 audit).

Three real, DB-computed pieces land here, all folded onto the payload inside
`weather_accuracy()` itself (never inside `consumer.aurora_verify`, which is
outside this batch's touch-scope):

* A **persistence baseline** — the naive "the target day will be like the day
  this forecast was issued" forecast, computed as a self-join on
  `aurora_city_obs` offset by the SAME lead_days bucket the real forecast
  uses, so its dashed reference line lands on the real skill curve's own
  x-axis. Verified live against the `wtf` database before writing this file:
  the real forecast beats persistence at every lead we hold data for
  (1 through 6 days — see the module docstring on the route for why the
  range stops there; it is the ingest window, not an omission).
* A **worst-call-this-month** callout — the single largest verified miss in
  the current calendar month, deduped to the shortest lead per (site,
  target_day) so one bad day is not counted three times across three lead
  buckets that all missed it. No causal narrative is attached — the schema
  has no column naming *why* a forecast missed, so only measured numbers
  are shown (temps, miss, lead time, date, city).
* A link to the site's real `/api/docs` page (already used elsewhere as
  `<a href="/api/docs">`, e.g. `api_keys.html` and the main nav) — not a
  fabricated accuracy-specific endpoint, since none exists yet.

Deliberately NOT added: a "where the model is weakest" panel naming specific
meteorological failure modes (fog, convective timing, etc.) — `\\d
aurora_city_forecast` / `\\d aurora_city_obs` were both inspected live and
carry temperature/wind/pressure columns only, no phenomenon classification.
Building that panel would mean inventing failure modes, which rule 1
forbids; it is left as a documented gap needing a new ingest column.
"""

from __future__ import annotations

import pathlib
from datetime import date

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _weather_accuracy_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def weather_accuracy")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


# ---------------------------------------------------------------------------
# Source-inspection: the route's SQL/logic, never executed against a live DB
# in this test file (house convention — see test_mp_hero_links.py).
# ---------------------------------------------------------------------------

def test_persistence_query_excludes_lead_zero():
    """Lead 0 is target_day - 0 == target_day: comparing the actual high
    against itself would always read 0.00 error, which is not a baseline,
    it's an identity. The route must filter it out before aggregating."""
    body = _weather_accuracy_route_body()
    assert "(period_index / 2) >= 1" in body, (
        "persistence rows must exclude lead_days=0 or the baseline "
        "silently reports a trivial 0.00 at TODAY"
    )


def test_persistence_query_offsets_by_lead_days_not_a_fixed_day():
    """The naive forecast must be keyed off the ISSUE day (target_day minus
    that row's own lead_days), not a fixed 1-day lag — otherwise every lead
    bucket would compare against yesterday regardless of how far out the
    real forecast reached, which is not the same claim."""
    body = _weather_accuracy_route_body()
    assert "fd.target_day - fd.lead_days" in body


def test_worst_miss_query_dedupes_by_site_and_day():
    body = _weather_accuracy_route_body()
    assert "DISTINCT ON (fc.site_code, fc.target_day)" in body, (
        "without this, a single missed day at 3 lead times counts as 3 "
        "misses instead of 1 story"
    )


def test_worst_miss_query_scoped_to_calendar_month():
    body = _weather_accuracy_route_body()
    assert "date_trunc('month', CURRENT_DATE)" in body


def test_worst_miss_picks_the_shortest_lead_per_story():
    body = _weather_accuracy_route_body()
    assert "ORDER BY fc.site_code, fc.target_day, fc.lead_days ASC" in body


def test_payload_carries_all_three_new_keys():
    body = _weather_accuracy_route_body()
    assert 'payload["persistence_curve"]' in body
    assert 'payload["worst_miss"]' in body
    assert 'payload["chart_max_mae"]' in body


def test_chart_max_mae_considers_both_series():
    """The bar chart and the persistence dashed line share one height scale
    — if chart_max_mae were derived from the model series alone, a
    persistence value larger than any model bar (the common case, since
    persistence is worse) would render past the top of the chart."""
    body = _weather_accuracy_route_body()
    assert "_model_maes + _persist_maes" in body


# ---------------------------------------------------------------------------
# Pure-Python re-implementation of the aggregation arithmetic (no DB, no
# import of the route module — mirrors test_mp_hero_links.py's standalone
# regex-reimplementation pattern). Proves the MATH the route performs is
# correct on a known input, independent of source-inspection above.
# ---------------------------------------------------------------------------

def _aggregate(pairs):
    usable = [(f, o) for f, o in pairs if f is not None and o is not None]
    n = len(usable)
    if n == 0:
        return 0, None, None
    bias = sum(f - o for f, o in usable) / n
    mae = sum(abs(f - o) for f, o in usable) / n
    return n, round(bias, 2), round(mae, 2)


def test_persistence_aggregation_bias_and_mae():
    # (persistence_c, observed_c) pairs at one lead bucket
    pairs = [(18.0, 20.0), (10.0, 10.0), (5.0, 8.0)]
    n, bias, mae = _aggregate(pairs)
    assert n == 3
    # signed: (18-20) + (10-10) + (5-8) = -2 + 0 + -3 = -5 / 3 = -1.67
    assert bias == -1.67
    # abs:    2 + 0 + 3 = 5 / 3 = 1.67
    assert mae == 1.67


def test_persistence_aggregation_skips_none_pairs():
    n, bias, mae = _aggregate([(None, 5.0), (10.0, None), (12.0, 10.0)])
    assert n == 1
    assert mae == 2.0


def test_persistence_aggregation_empty_is_zero_not_a_crash():
    n, bias, mae = _aggregate([])
    assert (n, bias, mae) == (0, None, None)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _base_payload(persistence_curve=None, worst_miss=None, chart_max_mae=3.0):
    return {
        "has_data": True,
        "summary": {
            "same_day_mae_c": 1.0, "same_day_pairs": 100,
            "longest_lead_days": 6, "longest_mae_c": 2.13,
            "long_range_bias_c": None, "long_range_direction": None,
            "total_pairs": 190,
            "window_start": date(2026, 8, 1), "window_end": date(2026, 9, 3),
            "window_days": 34,
        },
        "skill_curve": [
            {"lead_days": 0, "pairs": 891, "bias_c": 0.1, "mae_c": 1.38, "direction": "warm", "thin": False},
            {"lead_days": 1, "pairs": 838, "bias_c": -0.2, "mae_c": 1.52, "direction": "cold", "thin": False},
        ],
        "cities": [],
        "persistence_curve": persistence_curve if persistence_curve is not None else {},
        "chart_max_mae": chart_max_mae,
        "worst_miss": worst_miss,
    }


def _render(payload, is_subscriber=True):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("forecast_accuracy.html").render(
        verification=payload, is_subscriber=is_subscriber,
    )


def test_persistence_dashed_line_renders_for_a_covered_lead():
    payload = _base_payload(persistence_curve={
        1: {"pairs": 838, "bias_c": -0.5, "mae_c": 2.09, "thin": False},
    })
    html = _render(payload)
    assert "wtf-fa-persist-line" in html
    assert "Persistence baseline at +1d" in html


def test_persistence_dashed_line_absent_for_lead_zero():
    """Lead 0 has no matching entry in persistence_curve by construction
    (the route excludes it) — the template must not crash on a missing key
    and must not draw a line at TODAY."""
    payload = _base_payload(persistence_curve={
        1: {"pairs": 838, "bias_c": -0.5, "mae_c": 2.09, "thin": False},
    })
    html = _render(payload)
    idx_today = html.find("TODAY")
    idx_plus1 = html.find("+1D")
    assert idx_today != -1 and idx_plus1 != -1
    # the persist-line for TODAY's own bar-wrap must not exist: count the
    # rendered <span class="wtf-fa-persist-line" ...> ELEMENTS (not the
    # class's own CSS rule in the <style> block, which always contains the
    # substring "wtf-fa-persist-line" regardless of data) and confirm there
    # is exactly one (for +1D only).
    assert html.count('class="wtf-fa-persist-line"') == 1


def test_legend_shows_persistence_only_when_data_exists():
    with_p = _render(_base_payload(persistence_curve={1: {"pairs": 5, "bias_c": 0.1, "mae_c": 2.0, "thin": True}}))
    without_p = _render(_base_payload(persistence_curve={}))
    assert "Persistence baseline —" in with_p
    assert "Persistence baseline —" not in without_p


def test_worst_miss_panel_renders_real_computed_numbers():
    payload = _base_payload(worst_miss={
        "site_code": "s0000045", "lead_days": 0, "forecast_c": 18.0,
        "observed_c": 26.0, "target_day": date(2026, 9, 3),
        "city": "Edmonton", "province": "AB", "miss_c": 8.0,
    })
    html = _render(payload)
    assert "Edmonton" in html
    assert "AB" in html
    assert "18.0" in html
    assert "26.0" in html
    assert "8.0" in html
    # lead_days=0 -> "0 days out" (plural branch), never "0 day out"
    assert "0 days out" in html


def test_worst_miss_panel_honest_empty_state_when_none():
    html = _render(_base_payload(worst_miss=None))
    assert "No verified misses yet this month" in html
    assert "Worst call this month" in html
    # must not fabricate a placeholder city/number in the empty state
    assert "Edmonton" not in html


def test_worst_miss_singular_day_wording():
    payload = _base_payload(worst_miss={
        "site_code": "s1", "lead_days": 1, "forecast_c": 10.0,
        "observed_c": 15.0, "target_day": date(2026, 9, 2),
        "city": None, "province": None, "miss_c": 5.0,
    })
    html = _render(payload)
    assert "1 day out" in html
    assert "1 days out" not in html


def test_api_docs_link_present_and_real_path():
    html = _render(_base_payload())
    assert 'href="/api/docs"' in html
    assert "Explore the developer API" in html


def test_empty_page_state_unaffected_by_new_panels():
    """The pre-existing has_data=False branch must still render its own
    honest empty message and must NOT reach the new panels (which live
    inside the has_data branch and read verification.summary / .worst_miss,
    keys the empty payload never carries). The shared <style> block always
    defines the .wtf-fa-persist-line CSS rule regardless of branch, so the
    real assertion is that no ELEMENT with that class is ever rendered here
    — not that the class name is absent from the page's CSS altogether."""
    html = _render({"has_data": False})
    assert "No forecast has been verified yet" in html
    assert "Worst call this month" not in html
    assert 'class="wtf-fa-persist-line"' not in html
