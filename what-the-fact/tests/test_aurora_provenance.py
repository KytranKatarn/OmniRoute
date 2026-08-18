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


def test_drift_guard_watches_the_aurora_layers():
    guard = (ROOT / "ingest" / "parliament" / "drift_guard.py").read_text(encoding="utf-8")
    for task in ("aurora_firewx", "aurora_fire"):
        assert task in guard, f"{task} must be in the drift_guard watch list"
    assert "_REQUIRED_TASKS" in guard, (
        "a never-run puller must alarm rather than being skipped as "
        "'not yet tracked' — that is how a feed reports green forever"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
