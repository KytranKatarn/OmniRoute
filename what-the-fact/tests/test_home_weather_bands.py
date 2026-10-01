"""Homepage weather strip + 'Wildfire and alerts' band (PORT-STATUS row 4).

The design's figures are sample data. These tests pin the rule that replaced them:
every number comes from a query, and one that cannot be read is an em dash, never 0.
"""
import datetime as dt
import re
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "consumer"))
import aurora_map as am  # noqa: E402  (stdlib-only module)

DASH = "—"


# ── glyph mapping ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cond,glyph", [
    ("Clear", "sun"), ("Sunny", "sun"), ("Partly Cloudy", "cloudsun"), ("Mainly clear", "cloudsun"),
    ("Mostly Cloudy", "cloud"), ("Overcast", "cloud"), ("Light Rain Showers", "rain"),
    ("Thunderstorm", "rain"), ("Fog patches", "fog"), ("Mist", "fog"), ("Smoke", "smoke"),
    ("Haze", "smoke"), ("Windy", "wind"), ("Snow", "cloud"), (None, "cloud"), ("", "cloud"),
])
def test_condition_maps_to_a_registry_glyph(cond, glyph):
    assert am.wx_glyph(cond) == glyph


def test_every_glyph_the_mapping_can_return_exists_in_the_icon_registry():
    reg = (ROOT / "consumer/templates/_archetypes.html").read_text()
    keys = set(re.findall(r"^\s*'([\w-]+)':", reg[reg.index("_ICON_PATHS = {"):], re.M))
    for _needles, key in am._GLYPH_RULES:
        assert key in keys, key
    assert "cloud" in keys  # the fallback


# ── alert -> city matching ───────────────────────────────────────────────────
CITIES = [{"code": "a", "name": "Montréal"}, {"code": "b", "name": "Halifax"}, {"code": "c", "name": "Ottawa"}]


def test_alert_matches_city_by_whole_word_ignoring_accents():
    out = am.match_city_alerts(CITIES, [{"area_desc": "Montreal - Laval", "event": "Heat Warning", "severity": "Severe"}])
    assert out == {"a": {"event": "Heat Warning", "severity": "Severe"}}


def test_a_county_alert_does_not_flag_a_city_the_feed_never_named():
    assert am.match_city_alerts(CITIES, [{"area_desc": "Halifax County", "event": "x", "severity": "Minor"}]).keys() == {"b"}
    assert am.match_city_alerts(CITIES, [{"area_desc": "Victoria County", "event": "x", "severity": "Minor"}]) == {}


def test_a_substring_is_not_a_match():
    assert am.match_city_alerts([{"code": "c", "name": "Ottawa"}], [{"area_desc": "Ottawan Reserve", "event": "x"}]) == {}


def test_most_severe_alert_wins():
    out = am.match_city_alerts([{"code": "c", "name": "Ottawa"}], [
        {"area_desc": "Ottawa", "event": "Frost Advisory", "severity": "Minor"},
        {"area_desc": "Ottawa", "event": "Tornado Warning", "severity": "Extreme"}])
    assert out["c"]["event"] == "Tornado Warning"


# ── tile builder: honesty ────────────────────────────────────────────────────
def _tiles(**kw):
    a = dict(hotspot_rows=[{"prov": "AB", "hotspots": 2180, "max_fwi": 31.24}, {"prov": "BC", "hotspots": 40, "max_fwi": None},
                           {"prov": "ON", "hotspots": 0, "max_fwi": None}],
             obs_date=dt.date(2026, 9, 29), alerts=[{"event": "Wind Warning"}, {"event": "Frost Advisory"}],
             evac_naad=3, evac_bc_orders=4, reporting=24, total=25, silent_names=["Cambridge Bay"])
    a.update(kw)
    return {t["key"]: t for t in am.build_fire_alert_tiles(**a)}


def test_five_tiles_and_no_spread_pressure_tile():
    t = _tiles()
    assert list(t) == ["hotspots", "worst", "alerts", "evac", "cities"]
    assert not any("spread" in (x["label"] + x["note"]).lower() for x in t.values())


def test_hotspot_totals_and_worst_province_come_from_the_rows():
    t = _tiles()
    assert t["hotspots"]["value"] == "2,220" and "2 of 13" in t["hotspots"]["note"]
    assert t["worst"]["value"] == "AB" and t["worst"]["note"] == "2,180 detections · FWI 31.2"


def test_worst_province_omits_fwi_when_unmeasured_rather_than_printing_zero():
    t = _tiles(hotspot_rows=[{"prov": "BC", "hotspots": 40, "max_fwi": None}])
    assert "FWI" not in t["worst"]["note"]


def test_only_events_named_warning_count_as_warnings():
    t = _tiles(alerts=[{"event": "Wind Warning"}, {"event": "Frost Advisory"}, {"event": "Rainfall Watch"}, {"event": "Special Weather Statement"}])
    assert t["alerts"]["value"] == "4" and t["alerts"]["note"] == "1 of them warnings"


def test_evacuation_tile_shows_its_components_and_no_people_count():
    e = _tiles()["evac"]
    assert e["value"] == "7" and e["note"] == "3 Alert Ready · 4 BC orders"
    assert "people" not in e["note"].lower()


@pytest.mark.parametrize("kw,key", [
    (dict(obs_date=None), "hotspots"), (dict(hotspot_rows=[]), "worst"),
    (dict(alerts=None), "alerts"), (dict(evac_naad=None), "evac"), (dict(evac_bc_orders=None), "evac"),
    (dict(total=0), "cities")])
def test_an_unreadable_figure_is_an_em_dash_never_zero(kw, key):
    assert _tiles(**kw)[key]["value"] == DASH


def test_zero_alerts_is_a_real_zero_when_the_feed_was_readable():
    assert _tiles(alerts=[])["alerts"]["value"] == "0"


def test_cities_reporting_names_who_is_silent():
    assert _tiles()["cities"]["note"] == "Cambridge Bay silent"
    assert _tiles(reporting=25, silent_names=[])["cities"]["note"] == "all reporting"
    assert _tiles(silent_names=["A", "B", "C", "D"])["cities"]["note"] == "A, B +2 silent"


# ── template ─────────────────────────────────────────────────────────────────
def _render(weather_strip):
    env = Environment(loader=FileSystemLoader(str(ROOT / "consumer/templates")))
    env.globals.update(url_for=lambda ep, filename=None, **k: "/static/" + str(filename), session={},
                       nav_sections=[], wtf_nav_icon=lambda n: "", nav_source_count=41, source_count=41,
                       request=type("R", (), {"path": "/"})(), t=lambda k, *a, **kw: k)
    return env.get_template("index.html").render(articles=[], top_stories=[], is_subscriber=False, weather_strip=weather_strip)


def _city(name, prov, temp, cond, glyph, alert=None, age=10):
    return {"code": name, "name": name, "prov": prov, "temp": temp, "condition": cond, "glyph": glyph, "alert": alert, "age_min": age}


STRIP = {"cities": [_city("Calgary", "AB", 16.0, "Cloudy", "cloud", alert="Wind Warning"),
                    _city("Toronto", "ON", 21.4, "Partly cloudy", "cloudsun"),
                    _city("Winnipeg", "MB", -3.2, "Clear", "sun"),
                    _city("Regina", "SK", None, None, "cloud", age=None),
                    _city("Halifax", "NS", 14.0, "Mist", "fog", age=400)],
         "bands": am.build_fire_alert_tiles([{"prov": "AB", "hotspots": 9, "max_fwi": 20}], dt.date(2026, 9, 29), [], 0, 0, 4, 5, ["Regina"]),
         "fire_obs_date": "2026-09-29", "fire_provinces": [], "count": 5, "reporting": 4}


def test_cards_show_province_glyph_and_a_temperature_without_a_plus_sign():
    h = _render(STRIP)
    cards = re.findall(r'<a href="/weather" class="wtf-weather-card[^"]*" data-city="([^"]+)"', h)
    assert cards == ["Calgary", "Toronto", "Winnipeg", "Regina", "Halifax"]
    assert ">AB<" in h and ">ON<" in h
    assert ">16°<" in h and ">-3°<" in h and "+" not in re.sub(r"<[^>]+>", "", h[h.index('id="wtf-weather-cards"'):h.index("Wildfire and alerts")]).replace("&middot;", "")
    assert h.count('class="wxi"') >= 5


def test_alert_card_says_the_alert_and_is_flagged():
    h = _render(STRIP)
    card = h[h.index('data-city="Calgary"'):h.index('data-city="Toronto"')]
    assert "is-alert" in h[h.index('data-city="Calgary"') - 80:h.index('data-city="Calgary"')]
    assert "Wind Warning" in card and "wtf-weather-card-dot" in card


def test_a_city_with_no_reading_says_no_data_and_an_old_one_says_how_old():
    h = _render(STRIP)
    assert "no data" in h[h.index('data-city="Regina"'):h.index('data-city="Halifax"')]
    assert "6h old" in h[h.index('data-city="Halifax"'):h.index("Wildfire and alerts")]
    assert "is-stale" in h[h.index('data-city="Halifax"') - 80:h.index('data-city="Halifax"')]


def test_band_renders_five_tiles_and_no_hardcoded_hex_in_the_block():
    h = _render(STRIP)
    block = h[h.index('id="wtf-weather-strip"'):h.index("Home city first")]
    assert block.count('class="wtf-fire-card wtf-fire-card--') == 5
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block)
    assert "Spread pressure" not in h


def test_strip_is_absent_rather_than_empty_when_there_are_no_cities():
    assert 'id="wtf-weather-strip"' not in _render({"cities": [], "bands": [], "fire_provinces": []})


# ── route composition with a stubbed database ────────────────────────────────
class _Res:
    def __init__(self, rows=None, scalar=None): self._r, self._s = rows or [], scalar
    def mappings(self): return self
    def all(self): return self._r
    def scalar(self): return self._s


def _fake_db(alerts_ok=True):
    obs = dt.datetime.now(dt.timezone.utc)
    site = lambda code, name, prov, temp: {  # noqa: E731
        "site_code": code, "name_en": name, "display_name": None, "source_prov": prov, "lat": 1.0, "lon": 1.0,
        "last_obs_status": "ok", "observed_utc": obs if temp is not None else None, "temp_c": temp,
        "condition_text": "Clear" if temp is not None else None, "rel_humidity_pct": None, "wind_speed_kmh": None,
        "wind_is_calm": False, "wind_gust_kmh": None, "wind_dir": None, "humidex": None, "pressure_kpa": None,
        "age_min": 5 if temp is not None else None}
    sites = [site("s1", "Calgary", "AB", 16.0), site("s2", "Toronto", "ON", 21.0), site("s3", "Regina", "SK", None)]

    class Conn:
        def execute(self, q):
            sql = str(q)
            if "aurora_city_site" in sql: return _Res(sites)
            if "aurora_city_forecast" in sql: return _Res([])
            if "aurora_fire_hotspot_daily" in sql:
                return _Res([{"prov": "AB", "hotspots": 100, "max_fwi": 30.0, "obs_date": dt.date(2026, 9, 29)}])
            if "aurora_alerts" in sql:
                if not alerts_ok: raise RuntimeError("relation does not exist")
                return _Res([{"event": "Wind Warning", "severity": "Severe", "area_desc": "Calgary"}])
            if "aurora_bc_evacuations" in sql: return _Res(scalar=2)
            if "aurora_evacuations" in sql: return _Res(scalar=1)
            raise AssertionError(sql)

    class Ctx:
        def __enter__(self): return Conn()
        def __exit__(self, *a): return False

    class Eng:
        def begin(self): return Ctx()
    return Eng()


def test_route_flags_sorts_and_builds_tiles(monkeypatch):
    from consumer import routes  # direct import: a missing dependency must FAIL, not skip
    monkeypatch.setattr(routes, "_db", lambda: _fake_db())
    p = routes._home_weather_strip()
    assert [c["name"] for c in p["cities"]] == ["Calgary", "Toronto", "Regina"]  # alert first, grid order kept
    assert p["cities"][0]["alert"] == "Wind Warning" and p["cities"][0]["glyph"] == "sun"
    t = {x["key"]: x for x in p["bands"]}
    assert t["alerts"]["value"] == "1" and t["evac"]["value"] == "3" and t["cities"]["value"] == "2 / 3"
    assert t["cities"]["note"] == "Regina silent"


def test_route_survives_a_broken_alerts_table_with_two_tiles_blanked(monkeypatch):
    from consumer import routes  # direct import: a missing dependency must FAIL, not skip
    monkeypatch.setattr(routes, "_db", lambda: _fake_db(alerts_ok=False))
    p = routes._home_weather_strip()
    assert p["cities"], "the weather cards must survive an alerts failure"
    t = {x["key"]: x for x in p["bands"]}
    assert t["alerts"]["value"] == DASH and all(c["alert"] is None for c in p["cities"])
    assert t["hotspots"]["value"] == "100"


# ── 6th tile: spread pressure (current conditions, never a forecast) ─────────
def _spread(code="AB", name="Alberta", score=62, band="high"):
    return {"code": code, "name": name, "score": score, "band": band, "inputs": {}, "n_inputs": 3}


def test_spread_tile_absent_by_default_so_the_five_tile_band_is_unchanged():
    assert "spread" not in _tiles()


def test_spread_tile_names_province_and_says_current_conditions_not_forecast():
    t = _tiles(spread_rows=[_spread(), _spread("BC", "British Columbia", 30, "moderate")])["spread"]
    assert (t["value"], t["tone"]) == ("62", "severe")
    assert "Alberta" in t["note"] and "current conditions" in t["note"]
    assert "48" not in t["note"] and "next" not in t["note"].lower()


def test_spread_tile_em_dash_not_zero_when_nothing_measurable():
    for rows in ([], [_spread(score=None, band=None)]):
        t = _tiles(spread_rows=rows)["spread"]
        assert t["value"] == "—"
