"""Guard tests for A.U.R.O.R.A. provenance (project #393).

On 2026-08-18 what-the-fact.com was advertising "Environment Canada + NASA
EarthData + NOAA. Weather intelligence integrated into every story" while
holding NO weather data at all — no ingest, no table, no endpoint. The claim
lived in prose, so no query could contradict it and nothing alarmed.

These tests exist so that failure mode cannot return silently. They are
deliberately blunt: a template may only name a data source inside its
attribution block, and the page must render sources by looping the
aurora_layer_status view.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEATHER_HTML = ROOT / "consumer" / "templates" / "weather.html"
ROUTES = ROOT / "consumer" / "routes.py"
CWFIS = ROOT / "ingest" / "weather" / "cwfis.py"
AURORA_MAP = ROOT / "consumer" / "aurora_map.py"

# Bodies we must never name unless we genuinely ingest them. CWFIS/NRCan is
# absent because we DO ingest it — and even then only via the looped view.
_UNBACKED_SOURCES = ["NASA", "EarthData", "NOAA", "Environment Canada"]


def _rendered_markup(path: pathlib.Path) -> str:
    """Template text minus Jinja comments.

    The property that matters is what a READER sees, so a `{# ... #}` note
    explaining why a source must not be hardcoded is not a violation — the
    first version of this test flagged its own warning comment.
    """
    return re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)


def test_weather_template_names_no_data_source_directly():
    """The page must not hardcode a source name; it loops aurora_layer_status."""
    html = _rendered_markup(WEATHER_HTML)
    offenders = [s for s in _UNBACKED_SOURCES if s in html]
    assert not offenders, (
        f"weather.html names {offenders} directly. Source names must come from "
        "the aurora_layer_status view so the page cannot outlive its data. "
        "See KB #290491."
    )


def test_weather_template_loops_the_layer_view():
    html = WEATHER_HTML.read_text(encoding="utf-8")
    assert "for L in layers" in html, (
        "weather.html must render provenance by iterating `layers` "
        "(wtf.aurora_layer_status), not from static markup."
    )
    assert "is_stale" in html, (
        "weather.html must render a stale-layer state. A layer that stops "
        "updating has to SAY so rather than showing its last good number."
    )


def test_route_supplies_layers_from_the_view():
    src = ROUTES.read_text(encoding="utf-8")
    assert "wtf.aurora_layer_status" in src, (
        "the /weather route must read the layer-status view"
    )


def test_ingest_targets_only_the_approved_host():
    """ADR-001: CWFIS only. api.weather.gc.ca disallows /collections/*/items."""
    src = CWFIS.read_text(encoding="utf-8")
    calls = re.findall(r'https?://([a-z0-9.\-]+)', src)
    # api.weather.gc.ca may appear in the prose explaining why it is NOT used;
    # it must never appear as the WFS/base endpoint constant.
    assert "cwfis.cfs.nrcan.gc.ca" in src
    base = re.search(r'^_WFS\s*=\s*"([^"]+)"', src, re.M)
    assert base and "cwfis.cfs.nrcan.gc.ca" in base.group(1), (
        "the ingest base URL must be CWFIS (ADR-001)"
    )
    assert "api.weather.gc.ca/collections" not in src, (
        "GeoMet /collections/*/items is disallowed by its robots.txt (ADR-001)"
    )


def test_foreign_hotspots_are_filtered():
    """hotspots_last24hrs carries US + Mexico detections in the same layer;
    2,824 of 10,599 on the first live run. A Canadian page must not count them."""
    src = CWFIS.read_text(encoding="utf-8")
    assert "_CA_PROV" in src and "foreign" in src, (
        "hotspot ingest must filter non-Canadian agencies and report how many "
        "it dropped"
    )


def test_foreign_fire_weather_stations_are_filtered():
    """CWFIS is Canadian but its station layer carries US NWS stations too.

    Measured 2026-08-18: 177 of 571 stations were US (Florida at 25.7N,
    Michigan, New York...). Phase 1 shipped with the filter applied to hotspots
    but NOT to stations, so the live "strongest winds" table briefly ranked US
    stations on a page whose stated premise is Canada.
    """
    src = CWFIS.read_text(encoding="utf-8")
    assert "_FOREIGN_AGENCIES" in src and "NWS" in src, (
        "station ingest must exclude foreign operating agencies"
    )
    assert "_US_STATE_CODES" in src, (
        "station ingest must also reject US state codes appearing in `prov`"
    )
    assert "foreign_by_agency" in src, (
        "the drop must be REPORTED per agency, not silent — an unexpected "
        "agency code showing up in the drop list is how we learn the feed "
        "changed"
    )


def test_newfoundland_legacy_code_is_accepted():
    """CWFIS still emits NF (not NL) for Newfoundland — 60 stations on the
    first live run. An allowlist missing it would silently drop the province."""
    src = CWFIS.read_text(encoding="utf-8")
    prov_block = re.search(r"_CA_PROV\s*=\s*\{(.*?)\}", src, re.S)
    assert prov_block, "_CA_PROV not found"
    assert '"NF"' in prov_block.group(1), (
        "CWFIS emits Newfoundland as NF; dropping it loses the province"
    )


def test_drift_guard_watches_the_aurora_layers():
    guard = (ROOT / "ingest" / "parliament" / "drift_guard.py").read_text(encoding="utf-8")
    for task in ("aurora_firewx", "aurora_fire"):
        assert task in guard, f"{task} must be in the drift_guard watch list"
    assert "_REQUIRED_TASKS" in guard, (
        "a never-run puller must alarm rather than being skipped as "
        "'not yet tracked' — that is how a feed reports green forever"
    )


# ── staleness must be APPLIED, not merely declared (#5756 follow-up) ──────────

def test_layer_staleness_uses_the_declared_threshold_not_a_blanket_window():
    """Migration 055 added wtf.aurora_layer_status.stale_after_hours (city_obs 3h,
    city_forecast 12h, fire 48h) specifically because a fixed 48-hour window let a
    40-hour-old "current condition" render as FRESH on an hourly layer.

    Measured 2026-08-18: the column existed and NOTHING read it — the /weather
    route still computed is_stale from a hardcoded `interval '48 hours'`, so the
    fix had never taken effect. A threshold that is declared but never applied is
    unmonitored while APPEARING monitored; same shape as a retention tier with a
    policy and no pruner.
    """
    src = (ROOT / "consumer" / "routes.py").read_text()
    assert "stale_after_hours" in src, (
        "the /weather route must SELECT stale_after_hours — declaring it in the "
        "view and never reading it is the bug this guards"
    )
    assert "interval '48 hours'" not in src, (
        "is_stale must derive from each layer's own stale_after_hours, not a "
        "blanket 48h window that is wrong for every hourly layer"
    )


def test_city_staleness_is_not_restated_in_the_template():
    """One definition of 'current'. The JS threshold must be passed in from the
    registry, not hardcoded alongside it."""
    tpl = (ROOT / "consumer" / "templates" / "weather.html").read_text()
    assert "var CITY_STALE_MIN = 180;" not in tpl, (
        "CITY_STALE_MIN must come from city_stale_min (derived from the view), "
        "not be restated as a literal that drifts from the registry"
    )
    assert "city_stale_min" in tpl


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── map payload honesty (project #393, /weather interactive map) ─────────────
# The two CWFIS layers cover DISJOINT halves of the country: stations are
# eastern (zero in BC/SK/MB/YT/NT), hotspots are western/northern (zero in the
# Maritimes). Every test below defends a way the map could quietly misreport
# that, which is the whole reason the page exists.

def _payload(**kw):
    """Import the PURE builder — no Flask, no DB, so this never skips.

    This helper used to exec consumer/routes.py, which pulls in Flask and
    SQLAlchemy; on any machine without them every test below reported `s`
    (skipped) and the suite still said "passed". That is the same failure this
    file exists to prevent, one level up. aurora_map.py is stdlib-only.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_auroramap", AURORA_MAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._aurora_map_payload(
        kw.get("stations", []), kw.get("station_provinces", []),
        kw.get("fire_provinces", []), kw.get("obs_time"),
    )


def _stn(prov, **kw):
    d = {"station_name": "S", "prov": prov, "lat": 50.0, "lon": -100.0,
         "temp_c": 20.0, "rel_humidity": 50.0, "wind_speed_kmh": 10.0,
         "wind_gust_kmh": None, "fwi": 5.0}
    d.update(kw)
    return d


def test_newfoundland_nf_is_canonicalised_to_nl():
    """CWFIS says NF; the map's GeoJSON says NL. 60 stations — an entire
    province — render nowhere if these are not reconciled."""
    p = _payload(
        stations=[_stn("NF")],
        station_provinces=[{"prov": "NF", "stations": 60, "avg_temp": 18.5,
                            "max_temp": 22.0, "min_temp": 12.0,
                            "max_wind": 37.7, "max_fwi": 33.1, "avg_rh": 70}],
    )
    assert "NL" in p["provinces"], "NF must map onto the GeoJSON's NL"
    assert "NF" not in p["provinces"], "the legacy code must not also survive"
    assert p["provinces"]["NL"]["stations"] == 60
    assert p["stations"][0]["p"] == "NL"


def test_a_province_with_no_stations_is_absent_not_zero():
    """BC has 6 satellite hotspots' worth of fire and ZERO stations. Rendering
    it as 0 degrees / 0 km/h would state a measurement that was never taken."""
    p = _payload(fire_provinces=[{"prov": "BC", "hotspots": 748,
                                  "max_fwi": None, "obs_date": None}])
    bc = p["provinces"]["BC"]
    assert bc["stations"] is None, "no stations must be None, never 0"
    assert bc["avg_temp"] is None and bc["max_wind"] is None
    assert bc["hotspots"] == 748
    assert "BC" not in p["coverage"]["station_provinces"]
    assert "BC" in p["coverage"]["hotspot_provinces"]


def test_a_province_with_no_hotspots_is_absent_not_zero():
    """Nova Scotia has 67 stations and no hotspot rows. '0 hotspots' would be
    a claim of no fire; absent means the layer does not cover it."""
    p = _payload(station_provinces=[{"prov": "NS", "stations": 67,
                                     "avg_temp": 20.6, "max_temp": 24.0,
                                     "min_temp": 15.0, "max_wind": 32.4,
                                     "max_fwi": 10.4, "avg_rh": 65}])
    assert p["provinces"]["NS"]["hotspots"] is None
    assert "NS" not in p["coverage"]["hotspot_provinces"]


def test_stations_without_a_province_are_kept_and_counted():
    """19 stations report valid coordinates and a BLANK province. They can be
    PLOTTED even though they cannot be ATTRIBUTED — dropping them loses real
    observations, and guessing a province invents data."""
    p = _payload(stations=[_stn(""), _stn(None), _stn("ON")])
    assert p["coverage"]["stations_unplaced"] == 2
    assert len(p["stations"]) == 3, "unattributed stations must still be mapped"
    assert [s["p"] for s in p["stations"]] == [None, None, "ON"]


def test_fwi_records_which_instrument_it_came_from():
    """Station FWI and hotspot FWI are different instruments. Falling back is
    fine; doing it silently makes the number unauditable."""
    p = _payload(
        station_provinces=[{"prov": "ON", "stations": 92, "avg_temp": 21.9,
                            "max_temp": 26.0, "min_temp": 14.0,
                            "max_wind": 32.0, "max_fwi": 22.4, "avg_rh": 60}],
        fire_provinces=[{"prov": "ON", "hotspots": 6, "max_fwi": 99.0,
                         "obs_date": None},
                        {"prov": "NT", "hotspots": 6488, "max_fwi": 41.0,
                         "obs_date": None}],
    )
    assert p["provinces"]["ON"]["max_fwi"] == 22.4, "station FWI wins"
    assert p["provinces"]["ON"]["fwi_source"] == "stations"
    assert p["provinces"]["NT"]["max_fwi"] == 41.0, "hotspot FWI is the fallback"
    assert p["provinces"]["NT"]["fwi_source"] == "hotspots"


def test_missing_reading_stays_none_and_never_becomes_zero():
    p = _payload(stations=[_stn("ON", temp_c=None, wind_gust_kmh=None)])
    s = p["stations"][0]
    assert s["t"] is None and s["g"] is None, (
        "a missing reading and a zero reading are different facts"
    )


def test_map_does_not_depend_on_the_layer_status_block():
    """The map must be a SIBLING of the layer-status strip, not nested in it.

    Caught in review 2026-08-18: the map block was spliced inside
    `{% if layers %}`, so an empty aurora_layer_status view took the entire
    interactive map down with it — two unrelated failures wearing one switch.
    The map's own guard is `aurora_map.stations`.
    """
    html = WEATHER_HTML.read_text(encoding="utf-8")
    lines = html.split("\n")
    layers_if = next(i for i, l in enumerate(lines) if l.strip() == "{% if layers %}")
    # Probe the DIV, not the CSS rule — `#wtf-wx-map {` appears in the <style>
    # block far earlier and made the first version of this test fail on
    # already-correct markup.
    map_at = next(i for i, l in enumerate(lines) if 'id="wtf-wx-map"' in l)

    # Walk the block structure from `{% if layers %}` to find its matching endif.
    depth = 0
    layers_end = None
    for i in range(layers_if, len(lines)):
        s = lines[i]
        depth += s.count("{% if ") + s.count("{% for ")
        depth -= s.count("{% endif %}") + s.count("{% endfor %}")
        if depth == 0 and i > layers_if:
            layers_end = i
            break
    assert layers_end is not None, "could not find the endif closing `if layers`"
    # Assert NESTING, not ORDER. The original form was `map_at > layers_end`, which
    # also required the map to come AFTER the strip — true of the old page, false
    # once #2691 moved the map to the top to match the homepage. That is a layout
    # choice, not a correctness property; the property is that an empty
    # aurora_layer_status view must not be able to remove the map.
    assert not (layers_if < map_at < layers_end), (
        "the map is nested inside `{% if layers %}` — an empty layer-status "
        "view would silently remove the whole map"
    )
