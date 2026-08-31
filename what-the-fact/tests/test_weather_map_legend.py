"""The /weather map legend must explain every colour the map can paint (#6165).

WHAT WAS WRONG. `drawLegend()` re-declared its swatch colours by hand instead of
deriving them from the ramps that colour the map. The two lists had drifted, and
the colours that went missing were the ones that matter most:

    #7f1d1d   fire layer, 2,000+ hotspots — the most severe category on the page
    #3730a3   city layer, -20 to -10 C — an ordinary Canadian winter temperature

Either colour could appear on the map with no entry in the key explaining it. A
reader seeing the darkest red on a province had no way to learn it meant the
worst fire activity band rather than simply "a lot".

These tests parse the SHIPPED template, so they fail if anyone reintroduces a
hand-written stop list. Mutation-checked: restoring the old literal legend makes
them fail.
"""

import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates" / "weather.html"
SRC = TPL.read_text()

RAMPS = ("FIRE_STOPS", "FWI_STOPS", "TEMP_STOPS")


def ramp_entries(name):
    """[(threshold, colour, label), ...] for a ramp declared in the template."""
    m = re.search(name + r"\s*=\s*\[(.*?)\];", SRC, re.S)
    assert m, f"{name} not found"
    return re.findall(r"\[\s*(-?[\d.e+]+)\s*,\s*\"(#[0-9a-fA-F]{6})\"\s*,\s*\"([^\"]*)\"\s*\]", m.group(1))


class TestEveryRampStopCarriesItsOwnLabel:
    @pytest.mark.parametrize("name", RAMPS)
    def test_ramp_is_a_triple(self, name):
        """colour AND label live together, so the legend cannot omit one."""
        entries = ramp_entries(name)
        assert entries, f"{name} is not in (threshold, colour, label) form"
        for _thr, col, label in entries:
            assert col.startswith("#")
            assert label.strip(), f"{name}: a stop has no legend label"

    @pytest.mark.parametrize("name", RAMPS)
    def test_no_stop_colour_is_duplicated(self, name):
        """Two stops sharing a colour would make two bands indistinguishable."""
        cols = [c for _t, c, _l in ramp_entries(name)]
        assert len(cols) == len(set(cols)), f"{name} repeats a colour: {cols}"


class TestTheLegendIsDerivedNotRestated:
    def test_draw_legend_reads_the_ramp_arrays(self):
        start = SRC.index("function drawLegend()")
        body = SRC[start:start + 1800]
        assert "FIRE_STOPS" in body and "TEMP_STOPS" in body and "FWI_STOPS" in body, (
            "drawLegend no longer derives from the ramps"
        )

    def test_draw_legend_declares_no_colours_of_its_own(self):
        """THE REGRESSION GUARD. A literal hex inside drawLegend is how the two
        lists drifted in the first place."""
        start = SRC.index("function drawLegend()")
        body = SRC[start:start + 1800]
        # NO_DATA is referenced by NAME, never as a literal, so this stays clean.
        hexes = re.findall(r"\"(#[0-9a-fA-F]{6})\"", body)
        assert not hexes, f"drawLegend hardcodes {hexes} — derive from the ramp"

    def test_the_previously_missing_extremes_are_present(self):
        """The two colours that had no legend entry."""
        fire = [c for _t, c, _l in ramp_entries("FIRE_STOPS")]
        temp = [c for _t, c, _l in ramp_entries("TEMP_STOPS")]
        assert "#7f1d1d" in fire, "the most severe fire band is gone from the ramp"
        assert "#3730a3" in temp, "the -20..-10 C band is gone from the ramp"

    def test_the_no_data_grey_is_explained(self):
        """Grey is painted on the map, so it needs a key entry too — a reader
        must not have to guess whether grey means zero."""
        start = SRC.index("function drawLegend()")
        body = SRC[start:start + 1800]
        assert "NO_DATA" in body and "no data on this layer" in body


class TestTheBasemapIsGoneAndTheViewIsBounded:
    def test_no_third_party_tiles(self):
        assert "cartocdn" not in SRC and "tileLayer" not in SRC, (
            "a raster basemap is back — it competes with the choropleth and "
            "reintroduces an attribution obligation"
        )

    def test_the_view_is_bounded_since_there_are_no_tiles(self):
        """Without tiles, panning off Canada shows empty space."""
        assert "maxBounds" in SRC, "no basemap AND no bounds = pannable void"

    def test_the_container_paints_its_own_ground(self):
        """Leaflet's default container background is white."""
        assert "leaflet-container { background" in SRC


class TestNoDataStaysDistinguishableFromALowValue:
    def test_absent_provinces_are_styled_differently_not_just_darker(self):
        """⚠️ Assert the CONDITIONAL, not the word. An earlier version checked
        only `"dashArray" in body`, which `dashArray: null` also satisfies —
        the mutation run caught that. The treatment must depend on whether the
        province HAS a metric."""
        start = SRC.index("function styleFor(f)")
        body = SRC[start:start + 900]
        assert re.search(r"dashArray:\s*m\s*\?", body), (
            "a province with no data must not read as merely a low value — "
            "its outline treatment has to depend on `m`"
        )

    def test_absent_provinces_also_differ_in_opacity(self):
        start = SRC.index("function styleFor(f)")
        body = SRC[start:start + 900]
        assert re.search(r"fillOpacity:\s*m\s*\?", body), "opacity must depend on `m` too"
