"""/weather radar + cloud layers, the PAGE half (WX-1b, task 7250, ADR #1134): wiring and honesty rules. The map mechanics are tested in
tests/test_wtf_map_overlay.js (run below); the proxy in tests/test_wx_overlay.py."""

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "consumer" / "templates" / "weather.html").read_text()
ROUTES = (ROOT / "consumer" / "routes.py").read_text()
BLOCK = PAGE[PAGE.index("var WX_LAYERS"):PAGE.index("wtfmap = WTFMap.create")]
RENDER = PAGE[PAGE.index("function renderOverlayInfo"):PAGE.index("function overlayCoverage")]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_overlay_harness_passes():
    r = subprocess.run(["node", str(ROOT / "tests" / "test_wtf_map_overlay.js")], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stdout + r.stderr


def test_raster_helper_loads_before_the_map_component():
    a, b = PAGE.index("js/wtf-raster.js"), PAGE.index("js/wtf-map.js")
    assert a < b, "WTFRaster must exist before wtf-map.js is evaluated"


def test_buttons_exist_and_ids_match_the_registered_layers():
    for key in ("radar", "cloud"):
        assert f'data-layer="{key}"' in PAGE and f'id: "{key}"' in BLOCK


def test_each_overlay_points_at_a_proxy_route_that_exists():
    for key in ("radar", "cloud"):
        assert f'baseUrl: "/weather/overlay/{key}"' in BLOCK
    assert '"/weather/overlay/<key>/meta.json"' in ROUTES and '"/weather/overlay/<key>.png"' in ROUTES


def test_images_never_come_from_a_third_party_directly():
    assert "geo.weather.gc.ca" not in PAGE and "cwfis.cfs.nrcan.gc.ca" not in PAGE


def test_layer_index_does_not_fall_through_to_city_temperatures():
    seg = PAGE[PAGE.index("function layerIndexRows"):PAGE.index("function layerIndexRows") + 400]
    assert "if (OVERLAY_COPY[activeLayer]) return [];" in seg


def test_observed_and_forecast_are_labelled_differently():
    assert "Observed" in RENDER and "Model forecast" in RENDER and "is-observed" in PAGE and "is-forecast" in PAGE
    assert "FORECAST" in PAGE and "not clear skies" in PAGE


def test_failure_and_staleness_are_said_in_words_and_never_read_as_dry():
    assert "does not mean it is dry" in PAGE and "STALE" in RENDER and "Do not read it as the current rain" in RENDER
    assert "latest refresh failed" in RENDER


def test_readout_writes_with_textcontent_only():
    assert "innerHTML" not in RENDER and "textContent" in RENDER


def test_times_are_shown_in_eastern_never_in_utc():
    assert 'timeZone: "America/Toronto"' in PAGE
    shown = re.findall(r'ovRow\([^;]*', RENDER)
    assert not any("UTC" in s for s in shown)


def test_attribution_and_legend_are_rendered_with_the_layer():
    assert "m.attribution" in RENDER and "m.legend_url" in RENDER and "m.note" in RENDER and "m.domain_note" in RENDER
