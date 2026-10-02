"""/global — Canada's ODA from the OECD, reduced from design-handoff/wtf-global.html."""
from __future__ import annotations

import pathlib
import re
import sys

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consumer import global_data as gd  # noqa: E402
from ingest.market import oda_canada as oda  # noqa: E402


def _oda(years, **over):
    """Overrides apply to every year passed in this call."""
    rows = []
    for y in years:
        base = {"oda_ge": 10_000.0, "bilateral_ge": 8_000.0, "oda_gni_pct": 0.35}
        base.update(over)
        rows += [{"ref_year": y, "item_key": k, "value": v} for k, v in base.items() if v is not None]
    return rows


def _exp(years, v=500_000.0):
    return [{"ref_year": y, "item_key": "expense", "value_millions": v} for y in years]


def test_empty_gives_none():
    assert gd.build([]) is None


def test_only_years_where_all_three_series_exist_are_shown():
    rows = _oda([2015, 2016], oda_gni_pct=None, bilateral_ge=None) + _oda([2018, 2019])
    d = gd.build(rows)
    assert [r["year"] for r in d["rows"]] == [2018, 2019]


def test_multilateral_is_total_minus_bilateral_in_billions():
    r = gd.build(_oda([2024]))["latest"]
    assert (r["total"], r["bilateral"], r["multilateral"]) == (pytest.approx(10.0), pytest.approx(8.0), pytest.approx(2.0))
    assert r["bilateral_share"] == pytest.approx(80.0)


def test_federal_share_needs_both_sides_never_zero():
    assert gd.build(_oda([2024]))["latest"]["federal_share"] is None
    assert gd.build(_oda([2024]), _exp([2024]))["latest"]["federal_share"] == pytest.approx(2.0)


def test_gap_reports_how_far_the_latest_published_year_is_from_today():
    assert gd.build(_oda([2024]), today_year=2026)["gap"] == 2


def test_change_vs_prior_year():
    rows = _oda([2023], oda_ge=10_000.0) + _oda([2024], oda_ge=9_000.0)
    c = gd.build(rows)["change"]
    assert c["year"] == 2023 and c["abs"] == pytest.approx(-1.0) and c["pct"] == pytest.approx(-10.0)


def test_own_contracts_uses_the_latest_full_year_only():
    k = [{"title_en": "Global Affairs Canada", "year": 2025, "n_contracts": 10, "signed_value": 2e9},
         {"title_en": "Global Affairs Canada", "year": 2026, "n_contracts": 3, "signed_value": 1e8},
         {"title_en": "Other", "year": 2025, "n_contracts": 9, "signed_value": 9e9}]
    o = gd.build(_oda([2024]), contract_rows=k, today_year=2026)["own_contracts"]
    assert o == {"year": 2025, "n": 10, "value": pytest.approx(2.0)}


# ------------------------------------------------------------------ ingest parser
def _csv(*rows):
    head = "DATAFLOW,DONOR,MEASURE,TYING_STATUS,FLOW_TYPE,UNIT_MEASURE,PRICE_BASE,SECTOR,TIME_PERIOD,OBS_VALUE,BASE_PER,OBS_STATUS,UNIT_MULT,DECIMALS"
    return "\n".join([head] + [f"X,CAN,{m},_Z,{f},{u},{p},_Z,{y},{v},,A,{mult}," for (m, f, u, p, y, v, mult) in rows])


def test_parser_keeps_current_price_series_only():
    t = _csv(("11010", "1160", "XDC", "V", 2024, "10164.91", 6), ("11010", "1160", "XDC", "Q", 2024, "9999", 6),
             ("11015", "1160", "XDC", "V", 2024, "8298.99", 6), ("11002", "1160", "PT_B5G", "V", 2024, "0.34", 0))
    rows, errors = oda.build_rows(t)
    assert {(r["item_key"], r["value"]) for r in rows} == {("oda_ge", 10164.91), ("bilateral_ge", 8298.99), ("oda_gni_pct", 0.34)}
    assert errors == []


def test_parser_skips_blank_values_and_flags_missing_series():
    rows, errors = oda.build_rows(_csv(("11010", "1160", "XDC", "V", 2024, "", 6), ("11010", "1160", "XDC", "V", 2023, "5", 6)))
    assert [r["ref_year"] for r in rows] == [2023]
    assert any("bilateral_ge" in e for e in errors) and any("oda_gni_pct" in e for e in errors)


def test_parser_rejects_an_unexpected_unit_multiplier():
    rows, errors = oda.build_rows(_csv(("11010", "1160", "XDC", "V", 2024, "5", 9)))
    assert rows == [] and any("UNIT_MULT" in e for e in errors)


# ------------------------------------------------------------------ wiring + page
def test_ingest_scheduled_watched_and_route_is_real():
    run = (ROOT / "ingest" / "run.py").read_text(encoding="utf-8")
    assert "run_oda_canada" in run and "_last_oda_week" in run
    from ingest.parliament import drift_guard
    assert "oda_canada" in drift_guard._MAX_AGE_DAYS and "oda_canada" in drift_guard._REQUIRED_TASKS
    src = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
    assert '@bp.get("/global")' in src and '    "global": (' not in src


def _render(d):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block title %}{% endblock %}{% block meta %}{% endblock %}<body>{% block content %}{% endblock %}</body>"}),
                                           FileSystemLoader(str(ROOT / "consumer" / "templates"))]), autoescape=True)
    return env.get_template("global.html").render(d=d, is_subscriber=False)


def _text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", h, flags=re.S)))


def test_empty_state_has_no_figures():
    t = _text(_render(None))
    assert "has not been loaded yet" in t and "$" not in t


def test_page_states_latest_published_year_and_what_it_leaves_out():
    d = gd.build(_oda(range(2018, 2025)), _exp(range(2018, 2025)), today_year=2026)
    t = _text(_render(d))
    assert "2024 is the latest year the OECD has published" in t and "2025 is not out yet" in t
    assert "Multilateral (derived)" in t and "derived here, not an OECD line" in t
    assert "Not on this page yet" in t and "nothing is estimated in its place" in t
    assert "Every figure approximate and sourced" not in t  # the design's unprovable claim
