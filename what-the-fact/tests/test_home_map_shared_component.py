"""Homepage map runs on the shared WTFMap component, not Leaflet (PORT-STATUS row 2).

Source-level guards on index.html: the homepage is the most-visited page, and Leaflet
+ CARTO raster tiles were the map that watermarked on 2026-08-30 and drew circles
instead of province shapes. /map and /weather already use static/js/wtf-map.js.
"""
import re
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "consumer" / "templates" / "index.html").read_text(encoding="utf-8")


def test_no_leaflet_or_carto_left_on_the_homepage():
    assert not re.search(r"leaflet|cartocdn|\bL\.(map|tileLayer|geoJSON|layerGroup|marker|circle|control)\b", INDEX, re.I)


def test_no_leaflet_layer_state_survives():
    for name in ("pinLayer", "clusterLayer", "provinceLayer", "worldLayer", "PROVINCE_CENTROIDS"):
        assert name not in INDEX, name


def test_shared_component_and_d3_are_loaded_in_order():
    order = [INDEX.index(t) for t in ("d3-array.min.js", "d3-geo.min.js", "js/wtf-map.js")]
    assert order == sorted(order)


def test_lean_and_volume_layers_are_wired():
    for token in ('id="btn-lean"', 'id="btn-volume"', "setMapLayer('lean')", "setMapLayer('volume')",
                  'id="wtf-home-map-legend"', "WTFMap.create("):
        assert token in INDEX, token


def test_world_mode_uses_the_real_world_projection_not_a_disclaimer():
    body = INDEX[INDEX.index("function setMapMode("):INDEX.index("function loadArticleFeed_country")]
    assert "wtfmap.setScope(mode === 'world' ? 'world' : 'canada')" in body
    assert "wtf-world-note" not in INDEX and "projection covers Canada" not in INDEX
    # the old code hid the map in world mode; it must stay visible now
    assert "host.hidden" not in body


def test_world_layers_read_country_counts_and_never_province_data():
    for layer_id in ("'lean'", "'volume'"):
        i = INDEX.index("{ id: " + layer_id)
        metric = INDEX[i:INDEX.index("tooltip:", i)]
        assert "mapMode === 'world'" in metric, layer_id
        world_branch = metric[metric.index("mapMode === 'world'"):]
        world_branch = world_branch[: world_branch.index("var pd") if "var pd" in world_branch else len(world_branch)]
        assert "mapProvinces" not in world_branch, layer_id  # provinces are Canada-only data
    assert "function worldTip(" in INDEX and "wtfmap.regionName(cc)" in INDEX


def test_world_country_click_loads_that_countrys_feed():
    body = INDEX[INDEX.index("onSelect: function(pc)"):INDEX.index("function loadMapData")]
    assert "mapMode === 'world'" in body and "loadArticleFeed_country(pc)" in body


def test_province_select_uses_the_component_not_a_map_object():
    body = INDEX[INDEX.index("function setProvince("):INDEX.index("function toggleProvinceDropdown")]
    assert "wtfmap.focusProvince(pc)" in body and "wtfmap.resetView()" in body
    assert "map.fitBounds" not in body and "map.setView" not in body


def test_dropdown_switches_to_canada_before_selecting():
    i = INDEX.index("function toggleProvinceDropdown")
    seg = INDEX[i:i + 1600]
    assert seg.index("setMapMode('canada')") < seg.index("setProvince(p.code)")


def test_the_activity_feed_helpers_were_carried_over():
    for fn in ("function buildActivityItem(", "function loadAgentActivity(", "function timeAgo("):
        assert INDEX.count(fn) == 1, fn
