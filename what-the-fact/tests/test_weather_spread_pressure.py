"""Spread pressure (PORT-STATUS row 8b): a current-conditions index from real rows only.

The design called it a 48-hour prediction. We have no forecast model, so this is labelled
a reading of current conditions, prints its formula, and never imputes a missing input.
A.R.C.H.I.E.'s A.U.R.O.R.A. agent can later store predictions and be scored against it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from consumer.aurora_map import SPREAD_FORMULA, spread_pressure  # noqa: E402

WEATHER = (ROOT / "consumer" / "templates" / "weather.html").read_text(encoding="utf-8")
ROUTES = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")


def by(rows):
    return {r["code"]: r for r in rows}


def test_all_inputs_score_is_their_mean():
    rows = spread_pressure(
        [{"prov": "BC", "hotspots": 150, "max_fwi": 30}],
        [{"prov": "BC", "max_wind": 25, "max_temp": 22.5}],
    )
    r = by(rows)["BC"]
    # hotspots .5, fwi 1.0, wind .5, temp .5 -> mean .625
    assert r["score"] == 62 or r["score"] == 63
    assert r["n_inputs"] == 4 and r["band"] == "high"


def test_missing_inputs_are_left_out_not_imputed():
    # stations-only province (east): fwi+wind+temp, no hotspots
    r = by(spread_pressure([], [{"prov": "NS", "max_wind": 50, "max_temp": 35, "max_fwi": 30}]))["NS"]
    assert r["n_inputs"] == 3 and "hotspots" not in r["inputs"] and r["score"] == 100


def test_fewer_than_two_inputs_is_no_data_not_a_number():
    r = by(spread_pressure([{"prov": "YT", "hotspots": 9}], []))["YT"]
    assert r["score"] is None and r["band"] is None and r["n_inputs"] == 1


def test_values_clamp_and_bands_are_ordered():
    r = by(spread_pressure([], [{"prov": "AB", "max_wind": 500, "max_temp": -40, "max_fwi": 99}]))["AB"]
    assert all(0 <= v["pct"] <= 100 for v in r["inputs"].values())
    lo = by(spread_pressure([], [{"prov": "ON", "max_wind": 0, "max_temp": 10, "max_fwi": 0}]))["ON"]
    assert lo["score"] == 0 and lo["band"] == "low"


def test_sorted_most_pressure_first_and_no_data_last():
    rows = spread_pressure(
        [{"prov": "YT", "hotspots": 9}],
        [{"prov": "AB", "max_wind": 50, "max_temp": 35, "max_fwi": 30},
         {"prov": "ON", "max_wind": 5, "max_temp": 12, "max_fwi": 2}],
    )
    assert [r["code"] for r in rows] == ["AB", "ON", "YT"]


def test_province_codes_go_through_the_one_canonicaliser():
    # CWFIS says NF, Datamart/GeoJSON say NL: must be ONE province, not two.
    rows = spread_pressure([{"prov": "NF", "hotspots": 10, "max_fwi": 5}],
                           [{"prov": "NL", "max_wind": 10, "max_temp": 15, "max_fwi": 4}])
    assert [r["code"] for r in rows] == ["NL"] and rows[0]["n_inputs"] == 4


def test_handles_empty_and_none():
    assert spread_pressure(None, None) == []


def test_formula_is_honest_about_what_it_is():
    f = SPREAD_FORMULA.lower()
    assert "not a forecast" in f and "at least 2 inputs" in f


def test_route_and_template_wiring():
    assert "spread_pressure([dict(r) for r in fire_provinces]" in ROUTES
    assert "spread_rows=spread_rows" in ROUTES and "spread_formula=SPREAD_FORMULA" in ROUTES
    assert "{{ spread_formula }}" in WEATHER
    assert "no data" in WEATHER and "48" not in WEATHER.split("wtf-wx-spread")[1][:1500]


def test_panel_renders_bars_and_no_data_rows():
    a = WEATHER.index("{% if spread_rows %}")
    b = WEATHER.index("{% endif %}", WEATHER.index("{% endfor %}", a)) + len("{% endif %}")
    # the panel's own closing endif is the last one before the stories title
    b = WEATHER.index("Recent climate", a)
    frag = WEATHER[a:b].rsplit("<div", 1)[0]
    rows = spread_pressure([{"prov": "YT", "hotspots": 9}],
                           [{"prov": "AB", "max_wind": 50, "max_temp": 35, "max_fwi": 30}])
    out = jinja2.Environment().from_string(frag).render(spread_rows=rows, spread_formula=SPREAD_FORMULA)
    assert 'style="width:100%"' in out and "no data" in out and "not a forecast" in out
