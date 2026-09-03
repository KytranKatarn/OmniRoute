"""/weather's map REGISTRATION (#6165).

/weather no longer implements a map. It registers three layers with the shared
component (consumer/static/js/wtf-map.js), which owns rendering, the derived
legend and the no-data treatment — those rules are tested in
tests/test_wtf_map_component.js against the shipped module.

WHAT THIS FILE COVERS IS THE PAGE'S HALF:
  * the component is actually LOADED (a comment naming the path is not a
    <script> tag — that exact mistake was made during this migration and would
    have thrown "WTFMap is not defined", taking the whole map with it)
  * every ramp stop still carries its own label, since the page owns the ramps
    and the component derives the legend from them
  * every layer declares its coverage — the honesty rule that matters MOST once
    a shared component makes unlike layers look uniform
  * the cities layer still tints provinces FLAT rather than by temperature
  * selection routes through the component, so the scope buttons and the map
    cannot hold two different ideas of what is selected

HISTORY. Before the migration this file asserted on weather.html's own
drawLegend/styleFor. Those failed the moment the logic moved — correctly. The
assertions were not deleted; they moved to the component's test file, where they
now protect all three maps instead of one.
"""

import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates" / "weather.html"
SRC = TPL.read_text()

RAMPS = ("FIRE_STOPS", "FWI_STOPS", "TEMP_STOPS")


def ramp_entries(name):
    m = re.search(name + r"\s*=\s*\[(.*?)\];", SRC, re.S)
    assert m, f"{name} not found"
    return re.findall(r"\[\s*(-?[\d.e+]+)\s*,\s*\"(#[0-9a-fA-F]{6})\"\s*,\s*\"([^\"]*)\"\s*\]", m.group(1))


class TestTheComponentIsActuallyLoaded:
    def test_the_script_tag_exists(self):
        """⚠️ THE BUG THIS MIGRATION ACTUALLY HIT. The first pass mentioned
        static/js/wtf-map.js in a COMMENT and shipped no <script> tag. A grep
        for the filename matched — and the page would still have thrown."""
        assert re.search(r"<script[^>]+wtf-map\.js", SRC), (
            "wtf-map.js is not loaded — WTFMap.create() would be undefined"
        )

    def test_it_loads_after_its_projection_library(self):
        """The component calls d3.geoConicConformal() at create time.

        ⚠️ This test used to assert "after Leaflet". The renderer moved to
        d3-geo on 2026-09-02 and Leaflet is gone from this page, so the old
        assertion was not merely outdated — its subject no longer exists, and
        SRC.index() would raise rather than fail with a useful message.
        """
        d3geo = SRC.index("/static/vendor/d3-geo.min.js")
        comp = SRC.index("js/wtf-map.js")
        assert d3geo < comp, "wtf-map.js must load AFTER d3-geo"

    def test_it_loads_before_the_inline_script_that_uses_it(self):
        """⚠️ Match the TAG and the CALL SITE, not the first mention of either.

        An earlier version compared SRC.index("wtf-map.js") with
        SRC.index("WTFMap.create(") and failed on a correct file: the comment
        above the script tag contains the words "which calls WTFMap.create()",
        so index() found the PROSE, which sits before the tag. Third time this
        session a probe matched an explanatory comment instead of code
        (cf. KB #299620). Anchor on syntax that only appears in real code.
        """
        tag = SRC.index('filename=\'js/wtf-map.js\'')
        call = SRC.index("wtfmap = WTFMap.create(")   # the assignment, not the prose
        assert tag < call, "the component must load before WTFMap.create() runs"

    def test_the_page_no_longer_builds_its_own_map(self):
        assert "L.map(" not in SRC, "page still constructs a Leaflet map directly"
        assert "L.geoJSON" not in SRC, "page still builds its own choropleth"
        assert "function drawLegend" not in SRC, "page still owns a legend"


class TestEverySymbolTheMapUsesIsDeclared:
    """⚠️ THE BUG THIS MIGRATION ACTUALLY SHIPPED, BRIEFLY.

    Extracting the map plumbing removed a region that ALSO contained the ramp
    definitions, cityIsFresh, CITY_PROVS and CITY_STALE_MIN. The new code still
    referenced them, so the page would have thrown at runtime — and
    `node --check` PASSED, because it validates syntax, not references.

    Nothing else in this file catches that: the ramp tests match on
    `FIRE_STOPS\\s*=`, which a renamed `_UNUSED_FIRE_STOPS =` still satisfies.
    This test anchors on word boundaries and checks declaration, not presence.
    """

    SYMBOLS = ["FIRE_STOPS", "FWI_STOPS", "TEMP_STOPS", "STATION_TEMP_STOPS",
               "CITY_PROVS", "CITY_STALE_MIN", "CENTROIDS", "WX_LAYERS"]
    FUNCS = ["cityIsFresh", "renderAurora", "renderCards", "renderCities",
             "fireMetric", "wxMetric", "cityMetric", "provinceTooltip",
             "stationPoints", "cityPoints"]

    @staticmethod
    def _script():
        blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", SRC, re.S)
        return max(blocks, key=len)

    @pytest.mark.parametrize("sym", SYMBOLS)
    def test_referenced_constant_is_declared(self, sym):
        js = self._script()
        if not re.search(r"\b%s\b" % sym, js):
            pytest.skip(f"{sym} not referenced")
        assert re.search(r"\bvar\s+%s\s*=" % sym, js), (
            f"{sym} is USED but never declared — the page would throw at runtime"
        )

    @pytest.mark.parametrize("fn", FUNCS)
    def test_referenced_function_is_declared(self, fn):
        js = self._script()
        if not re.search(r"\b%s\b" % fn, js):
            pytest.skip(f"{fn} not referenced")
        assert re.search(r"\bfunction\s+%s\b" % fn, js), (
            f"{fn} is USED but never declared — the page would throw at runtime"
        )

    def test_no_call_targets_a_function_that_no_longer_exists(self):
        """⚠️ THE ONE THE HAND-WRITTEN LIST ABOVE MISSED.

        After the migration a bootstrap line still called drawLegend(), which
        had moved into the component. Every static check passed and the page
        threw `ReferenceError: drawLegend is not defined` on EVERY load — found
        only by opening it in a browser and reading the console.

        The list-based tests above cannot catch that: they check symbols I
        thought to enumerate. This DERIVES every locally-called identifier from
        the source instead, so a call left behind by any future extraction
        fails here rather than in production.
        """
        js = self._script()
        # strip comments first — prose mentioning a removed function is not a call
        code = "\n".join(re.sub(r"//.*$", "", ln) for ln in js.splitlines())
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        # Strip STRING LITERALS too. A call cannot live inside a quoted string,
        # and prose like " hotspots (72h)" otherwise reads as a call to
        # `hotspots(` — which is how this test first false-positived.
        code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
        code = re.sub(r"'(?:[^'\\]|\\.)*'", "''", code)

        # A bare call only: NOT preceded by a dot (that is a method on some
        # object, not a local function) and not a language keyword.
        KEYWORDS = {"function", "return", "typeof", "catch", "switch", "while",
                    "default", "delete", "instanceof", "void", "throw", "await"}
        called = {
            m.group(1) for m in re.finditer(r"(?<![.\w])([a-z][A-Za-z0-9_]{3,})\s*\(", code)
            if m.group(1) not in KEYWORDS
        }
        declared = set(re.findall(r"\bfunction\s+([A-Za-z0-9_]+)", code))
        declared |= set(re.findall(r"\bvar\s+([A-Za-z0-9_]+)\s*=\s*function", code))

        # things that legitimately come from elsewhere
        allowed = {
            # browser / language builtins used on this page
            "parseInt", "parseFloat", "isNaN", "setTimeout", "encodeURIComponent",
            "toFixed", "toLocaleString", "getElementById", "querySelectorAll",
            "querySelector", "createElement", "createTextNode", "appendChild",
            "addEventListener", "forEach", "filter", "map", "sort", "slice",
            "join", "push", "concat", "indexOf", "includes", "split", "replace",
            "toggle", "add", "remove", "contains", "keys", "values", "round",
            "sqrt", "abs", "min", "max", "floor", "ceil", "toString", "trim",
            "hasOwnProperty", "bindTooltip", "setStyle", "resetStyle", "addTo",
            "clearLayers", "addLayer", "flyTo", "json", "then", "catch", "fetch",
            "reduce", "some", "every", "find", "charAt", "substring", "match",
            "toUpperCase", "toLowerCase", "padStart", "getTime", "strftime",
            "setLayer", "select", "refresh", "create", "ramp", "getLayer",
            "getSelected", "toISOString", "getFullYear", "apply", "call", "bind",
        }
        missing = sorted(c for c in called if c not in declared and c not in allowed)
        assert not missing, (
            f"called but not declared on this page: {missing} — if one of these "
            "moved into the shared component, the call site must move or go too"
        )


class TestEveryRampStopCarriesItsOwnLabel:
    """The component DERIVES the legend from these, so a stop without a label
    would render a blank key entry."""

    @pytest.mark.parametrize("name", RAMPS)
    def test_ramp_is_a_triple(self, name):
        entries = ramp_entries(name)
        assert entries, f"{name} is not in (threshold, colour, label) form"
        for _thr, col, label in entries:
            assert col.startswith("#") and label.strip(), f"{name}: a stop has no label"

    @pytest.mark.parametrize("name", RAMPS)
    def test_no_stop_colour_is_duplicated(self, name):
        cols = [c for _t, c, _l in ramp_entries(name)]
        assert len(cols) == len(set(cols)), f"{name} repeats a colour: {cols}"

    def test_the_previously_missing_extremes_are_still_present(self):
        """Both were painted on the map with no legend entry before #2974."""
        fire = [c for _t, c, _l in ramp_entries("FIRE_STOPS")]
        temp = [c for _t, c, _l in ramp_entries("TEMP_STOPS")]
        assert "#7f1d1d" in fire, "the most severe fire band is gone"
        assert "#3730a3" in temp, "the -20..-10 C band is gone"


class TestEveryLayerDeclaresItsCoverage:
    """THE rule that matters most once a shared component makes unlike layers
    look uniform. The fire layers cover DISJOINT halves of Canada and the city
    layer is 25 point readings — a viewer cannot know that from the colours."""

    def test_all_three_layers_are_registered(self):
        block = SRC[SRC.index("var WX_LAYERS"):SRC.index("wtfmap = WTFMap.create")]
        for layer_id in ('"fire"', '"wx"', '"cities"'):
            assert layer_id in block, f"layer {layer_id} not registered"

    def test_every_registered_layer_has_a_coverage_note(self):
        block = SRC[SRC.index("var WX_LAYERS"):SRC.index("wtfmap = WTFMap.create")]
        assert block.count("coverageNote:") == 3, (
            "a layer without coverageNote renders as if it covered the whole country"
        )

    def test_coverage_text_says_grey_is_not_zero(self):
        assert "that is not a reading of zero" in SRC

    def test_the_city_layer_says_its_tint_is_not_a_temperature(self):
        assert "NOT a provincial temperature" in SRC


class TestTheCityLayerTintsFlat:
    def test_city_metric_returns_a_flat_tint_not_a_ramp_colour(self):
        """25 cities across 13 provinces is one or two readings each; painting a
        province from that asserts an average nobody measured."""
        body = SRC[SRC.index("function cityMetric"):SRC.index("function provinceTooltip")]
        assert "WTFMap.ramp(TEMP_STOPS" not in body, (
            "the city layer must not colour PROVINCES by temperature"
        )
        assert re.search(r'col:\s*"#[0-9a-fA-F]{6}"', body), "expected a single flat tint"


class TestOneSelectionNotTwo:
    def test_select_routes_through_the_component(self):
        body = SRC[SRC.index("function select(code)"):]
        body = body[:body.index("\n  document.querySelectorAll")]
        assert "wtfmap.select(" in body, (
            "selection must go through the component, or the scope buttons and "
            "the map will disagree about what is selected"
        )

    def test_layer_buttons_route_through_the_component(self):
        assert "wtfmap.setLayer(" in SRC

    def test_the_map_still_drives_the_panels(self):
        """A province chosen on the map must still refresh the A.U.R.O.R.A.
        panel, the station cards and the city grid — that is the whole point."""
        block = SRC[SRC.index("onSelect: function"):SRC.index("onLayer: function")]
        for fn in ("renderAurora()", "renderCards()", "renderCities()"):
            assert fn in block, f"{fn} no longer follows the map selection"


class TestNoThirdPartyTiles:
    def test_page_loads_no_raster_basemap(self):
        assert "cartocdn" not in SRC and "tileLayer" not in SRC
