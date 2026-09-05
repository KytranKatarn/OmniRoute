"""Regression coverage for /weather's 3 quick-win features (task #17):

  1. "My city" select — persists a home-city pick to
     localStorage['wtf.homeCity'], highlights the matching card
     (data-city + .is-home) and scrolls it into view, including on a page
     load that already has a stored home city (no re-select required).
  2. "Copy link to this view" — a URL hash built from the current
     layer/province (#layer=<id>&prov=<code>), written on every map
     selection/layer change, read back once on load, plus a clipboard copy
     with an offscreen-textarea fallback for when navigator.clipboard is
     unavailable (this app is served over plain HTTP on the LAN in some
     deployments).
  3. Colourblind-safe palette toggle — a checkbox persisted to
     localStorage['wtf-cb'] that swaps FIRE_STOPS/FWI_STOPS/TEMP_STOPS/
     STATION_TEMP_STOPS for blue->yellow (never red<->green) twins with the
     SAME breakpoints and labels, and re-points WX_LAYERS[i].ramp so the
     legend (which wtf-map.js's drawLegend() re-reads fresh on every draw,
     but only from that already-captured object property, not from the
     FIRE_STOPS/etc. variable itself) actually updates.

This is a template+JS-only change. `def weather():` in consumer/routes.py is
byte-for-byte unchanged (test_route_weather_body_is_unchanged pins this
against a hash captured from `main` at authoring time, per
feedback_mutation-check-no-runtime-git.md — no git call is baked into a
test that runs after this merges).
"""

from __future__ import annotations

import colorsys
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = REPO_ROOT / "consumer" / "routes.py"
TPL_DIR = REPO_ROOT / "consumer" / "templates"
WEATHER = TPL_DIR / "weather.html"

_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"
_UTC = datetime.timezone.utc

# Baseline captured at authoring time from `main` (commit a9eb08ff4, 2026-09-05)
# via `git show main:what-the-fact/consumer/routes.py`, sliced the same way
# test_route_weather_body_is_unchanged slices the LIVE file below. This is a
# frozen constant, not a live git call — see feedback_mutation-check-no-
# runtime-git.md: a "git show HEAD" baked into a permanent test only proves
# anything once, at authoring time, and would fail forever after this merges.
_WEATHER_ROUTE_BASELINE_SHA256 = (
    "3894b67b8640c7f49d3ae0e2d16012b96aba925b19c7c31497a4abad2f9774f8"
)


# ────────────────────────── Jinja render (rule #1: no UndefinedError) ─────


def _aurora_map():
    return {
        "provinces": {
            "ON": {
                "name": "Ontario", "hotspots": 12, "stations": 5,
                "max_fwi": 22.0, "max_temp": 21, "max_wind": 30,
                "fwi_source": None,
            },
        },
        "prov_order": [
            "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU",
            "ON", "PE", "QC", "SK", "YT",
        ],
        "coverage": {
            "hotspot_provinces": ["ON", "BC"],
            "station_provinces": ["ON"],
            "stations_unplaced": 0,
        },
        "national": {
            "stations": 5, "warmest": 21, "max_wind": 30,
            "max_fwi": 22.0, "hotspots": 12,
        },
        "stations": [
            {"n": "Toronto Pearson", "p": "ON", "lat": 43.68, "lon": -79.63,
             "t": 18, "w": 12, "g": None, "h": 55, "f": 15.0},
        ],
    }


def _aurora_cities():
    return {
        "cities": [
            {"name": "Toronto", "prov": "ON", "lat": 43.65, "lon": -79.38,
             "temp": 19, "condition": "Clear", "calm": False, "wind": 10,
             "dir": "NW", "gust": None, "humidity": 50, "humidex": None,
             "age_min": 20, "status": "ok", "is_capital": False,
             "forecast": [{"label": "Mon", "high": 20, "low": 10, "pop": 10}]},
            {"name": "Ottawa", "prov": "ON", "lat": 45.42, "lon": -75.70,
             "temp": None, "condition": None, "calm": False, "wind": None,
             "dir": None, "gust": None, "humidity": None, "humidex": None,
             "age_min": None, "status": "no_observations", "is_capital": True,
             "forecast": []},
        ],
        "reporting": 1, "count": 2, "provinces": ["ON"],
    }


_STATIC_CTX = dict(
    aurora_map=_aurora_map(),
    aurora_cities=_aurora_cities(),
    city_stale_min=180,
    climate_count=3,
    sci_count=2,
    source_count=46,
    articles=[],
    layers=[],
    fire_summary=None,
    fire_provinces=None,
    windiest=None,
)


def _env():
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    # A raw jinja2.Environment (unlike Flask's) has no `tojson` filter — Flask
    # registers its own. weather.html embeds `{{ aurora_map | tojson }}` and
    # `{{ (aurora_cities or {}) | tojson }}` for the inline script, so a bare
    # Environment must be given an equivalent filter or every render here
    # fails with "No filter named 'tojson' found" before ever reaching the
    # UndefinedError this test class actually exists to catch.
    env.filters["tojson"] = json.dumps
    # Same reason: `url_for` is a Flask request-context global, not part of
    # Jinja2 itself. weather.html calls
    # `{{ url_for('static', filename='js/wtf-map.js') }}`.
    env.globals["url_for"] = lambda endpoint, **kw: (
        f"/static/{kw.get('filename', '')}"
    )
    return env


def _render(**overrides):
    ctx = dict(_STATIC_CTX)
    ctx.update(overrides)
    return _env().get_template("weather.html").render(**ctx)


def test_renders_with_full_context_no_undefined_error():
    html = _render()
    assert "Weather" in html
    assert "wtf-wx-city-select" in html


def test_renders_when_aurora_map_is_absent():
    """The whole map zone is guarded by `{% if aurora_map %}` — the page must
    still render (city-conditions/articles panels are independent of it).

    ⚠️ Checked via `id="wtf-wx-map"` (the actual element), not the bare
    substring "wtf-wx-map" — that substring is ALSO present unconditionally
    in the page's own `<style>` block (`#wtf-wx-map { height:460px; ... }`),
    so a bare-substring check would pass even with the div rendered."""
    html = _render(aurora_map=None)
    assert 'id="wtf-wx-map"' not in html
    # The quick-win toolbar controls live INSIDE the map zone, so they must
    # not render when aurora_map is absent either. `id=` (the element), not
    # the bare class substring — `.wtf-wx-city-select { ... }` is also a
    # CSS rule in the page's unconditional <style> block.
    assert 'id="wtf-wx-city-select"' not in html


def test_renders_when_aurora_cities_is_absent():
    html = _render(aurora_cities=None)
    # `.wtf-wx-citygrid { ... }` (the CSS rule) renders unconditionally in
    # the page's <style> block — check for the actual element, not the bare
    # class-name substring (same pitfall as the wtf-wx-map check above).
    assert 'id="wtf-wx-citygrid"' not in html
    # The map zone itself is independent of aurora_cities (see the route
    # docstring: city obs come from a different feed than CWFIS).
    assert 'id="wtf-wx-map"' in html


def test_renders_with_articles_present_and_absent():
    article = {
        "id": 1, "title": "A climate story", "source": "CBC",
        "province_code": "ON", "published_at": None, "band": "center",
        "beat": "climate", "cluster_size": 2, "cluster_id": 1,
    }
    html = _render(articles=[article])
    assert "A climate story" in html
    html_empty = _render(articles=[])
    assert "No climate or science stories" in html_empty


def test_renders_with_layers_fire_summary_fire_provinces_windiest_populated():
    layer = {
        "layer_label": "Fire hotspots", "record_count": 42,
        "issuing_body": "CWFIS", "dataset_id": "cwfis-hotspots",
        # is_stale=False takes the template's non-stale branch, which calls
        # `L.last_pull.strftime(...)` unconditionally (only the STALE branch
        # guards it with `if L.last_pull else 'never'`) — needs a real
        # datetime here, not None.
        "is_stale": False,
        "last_pull": datetime.datetime(2026, 9, 1, 12, 0, tzinfo=_UTC),
    }
    fire_summary = {"perimeter_count": 7, "earliest_start": None}
    fire_provinces = [{"prov": "BC", "hotspots": 5, "max_fwi": 30.2}]
    windiest = [{"station_name": "Station A", "prov": "AB",
                 "wind_speed_kmh": 40.0, "wind_gust_kmh": None,
                 "temp_c": 12.0, "fwi": None}]
    html = _render(layers=[layer], fire_summary=fire_summary,
                    fire_provinces=fire_provinces, windiest=windiest)
    assert "Fire hotspots" in html
    assert "Station A" in html


# ────────────────────────── route unchanged (rule: template+JS only) ──────


def test_route_weather_body_is_unchanged():
    """This was deliberately a template-only change. Slices `def weather():`
    the same way test_route_no_route_changes_were_needed slices news() in
    test_news_filters_collapse_and_empty_state.py, and hashes the slice
    against a baseline captured from `main` at authoring time (see the
    module docstring — never a live git call baked into this test)."""
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def weather():")
    end = src.index("\n@bp.get", start + 1)
    body = src[start:end]
    got = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert got == _WEATHER_ROUTE_BASELINE_SHA256, (
        "def weather() changed — this task was scoped to weather.html only"
    )


# ────────────────────────── shared JS-source helpers ───────────────────────


def _script_source() -> str:
    """The largest inline (no src=) <script> block — mirrors
    tests/test_weather_map_legend.py's own `_script()` helper."""
    src = WEATHER.read_text(encoding="utf-8")
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S)
    return max(blocks, key=len)


def _extract_function(src: str, name: str) -> str:
    """Brace-matched extraction of `function <name>(...) { ... }` — robust to
    internal reformatting, unlike a fixed-line-count or next-function slice."""
    marker = f"function {name}("
    start = src.index(marker)
    brace_start = src.index("{", start)
    depth = 0
    i = brace_start
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return src[start:i + 1]


# ────────────────────────── source-inspection: markup + wiring ────────────


def test_city_select_present_with_label_and_toolbar_location():
    src = WEATHER.read_text(encoding="utf-8")
    assert 'id="wtf-wx-city-select"' in src
    assert '<label class="wtf-wx-toolbar-label" for="wtf-wx-city-select">' in src
    # Feature 1 explicitly requires this control live in the layerbar toolbar.
    layerbar = src[src.index('class="wtf-wx-layerbar"'):
                    src.index('id="wtf-wx-map"')]
    assert "wtf-wx-city-select" in layerbar


def test_copy_link_button_present_with_aria_label():
    src = WEATHER.read_text(encoding="utf-8")
    assert 'id="wtf-wx-copy-link"' in src
    assert 'aria-label="Copy link to this view"' in src
    around = src[src.index('id="wtf-wx-copy-link"') - 40:
                 src.index('id="wtf-wx-copy-link"')]
    assert "<button" in around


def test_copy_status_has_aria_live_polite():
    src = WEATHER.read_text(encoding="utf-8")
    assert 'id="wtf-wx-copy-status"' in src
    tag_open = src.rindex("<div", 0, src.index('id="wtf-wx-copy-status"'))
    tag_close = src.index(">", tag_open)
    tag = src[tag_open:tag_close + 1]
    assert 'aria-live="polite"' in tag
    assert "hidden" in tag


def test_cb_toggle_checkbox_present_with_label():
    src = WEATHER.read_text(encoding="utf-8")
    assert 'id="wtf-wx-cb-toggle"' in src
    assert 'type="checkbox"' in src
    assert '<label class="wtf-wx-cb-toggle" for="wtf-wx-cb-toggle">' in src


def test_no_click_only_handlers_on_non_interactive_elements():
    """The 3 new controls must be real form elements, not a <div>/<span>
    wired up with a bare onclick — keyboard operability depends on it."""
    src = WEATHER.read_text(encoding="utf-8")
    tag_start = src.rindex("<select", 0, src.index('id="wtf-wx-city-select"'))
    assert src[tag_start:tag_start + 8] == "<select "
    tag_start = src.rindex("<button", 0, src.index('id="wtf-wx-copy-link"'))
    assert src[tag_start:tag_start + 8] == "<button "
    tag_start = src.rindex("<input", 0, src.index('id="wtf-wx-cb-toggle"'))
    assert src[tag_start:tag_start + 7] == "<input "


def test_localstorage_keys_present():
    src = WEATHER.read_text(encoding="utf-8")
    assert '"wtf.homeCity"' in src
    assert '"wtf-cb"' in src


def test_write_hash_and_read_hash_functions_declared_and_wired():
    js = _script_source()
    assert re.search(r"\bfunction\s+writeHash\s*\(", js)
    assert re.search(r"\bfunction\s+readHash\s*\(", js)
    # readHash must run once, after WTFMap.create() returns.
    create_idx = js.index("wtfmap = WTFMap.create(")
    read_call_idx = js.index("readHash();")
    assert create_idx < read_call_idx, (
        "readHash() must be called AFTER WTFMap.create() returns"
    )
    # writeHash is called from BOTH onSelect and onLayer.
    on_select = js[js.index("onSelect: function"):js.index("onLayer: function")]
    assert "writeHash();" in on_select
    # ⚠️ Brace-matched, not a naive `"});"` search: onLayer's body ALSO
    # contains an inner `.forEach(function (x) {...});` whose OWN closing
    # `});` appears BEFORE the trailing `writeHash();` line — a first-match
    # substring search truncates there and reports a false negative.
    onlayer_start = js.index("onLayer: function")
    onlayer_brace = js.index("{", onlayer_start)
    depth, i = 0, onlayer_brace
    while True:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    onlayer_block = js[onlayer_start:i + 1]
    assert "writeHash();" in onlayer_block


def test_read_hash_calls_setlayer_then_select_in_order():
    js = _script_source()
    body = _extract_function(js, "readHash")
    set_layer_idx = body.index("wtfmap.setLayer(")
    select_idx = body.index("select(params.prov)")
    assert set_layer_idx < select_idx, (
        "readHash() must call setLayer(...) BEFORE select(...)"
    )


def test_clipboard_writetext_has_offscreen_textarea_fallback():
    js = _script_source()
    assert "navigator.clipboard" in js
    assert "navigator.clipboard.writeText" in js
    fallback = _extract_function(js, "fallbackCopyLink")
    assert 'createElement("textarea")' in fallback
    assert "-9999px" in fallback  # offscreen, not display:none (breaks execCommand selection)
    assert 'execCommand("copy")' in fallback


def test_copied_confirmation_uses_textcontent_and_fades():
    body = _extract_function(_script_source(), "showCopiedStatus")
    assert "status.textContent =" in body
    assert ".innerHTML" not in body
    assert "is-fading" in body


def test_all_dynamic_text_insertion_uses_textcontent_not_innerhtml():
    js = _script_source()
    assert ".innerHTML =" not in js and ".innerHTML=" not in js


# ────────────────────────── source-inspection: home-city treatment ────────


def test_render_cities_adds_data_city_and_is_home_and_scrolls():
    body = _extract_function(_script_source(), "renderCities")
    assert 'setAttribute("data-city"' in body
    assert "is-home" in body
    assert "scrollIntoView(" in body


def test_home_city_applied_on_initial_load_without_a_reselect():
    """homeCity must be read from localStorage at top-level script scope
    (before the first renderCities() call at the bottom of the IIFE), not
    only inside the select's change handler — otherwise a stored preference
    would need a re-select to take effect."""
    js = _script_source()
    read_idx = js.index('localStorage.getItem("wtf.homeCity")')
    last_bootstrap_call = js.rindex("renderCities();")
    assert read_idx < last_bootstrap_call


def test_city_select_options_use_textcontent_never_innerhtml():
    body = _extract_function(_script_source(), "populateCitySelect")
    assert "opt.textContent =" in body
    assert ".innerHTML" not in body


# ────────────────────────── source-inspection: colourblind palette ────────


_RAMP_NAMES = ("FIRE_STOPS", "FWI_STOPS", "TEMP_STOPS", "STATION_TEMP_STOPS")

_STOP_RE = re.compile(
    r"\[\s*(-?[\d.e+]+)\s*,\s*\"(#[0-9a-fA-F]{6})\"\s*,\s*\"([^\"]*)\"\s*\]"
)


def _named_array_literal(js: str, name: str) -> str:
    """The exact `[...]` literal bound to `var <name> = [...]`. Anchored on
    `var` + the exact name followed by `=`, so e.g. `FIRE_STOPS` never
    matches the `FIRE_STOPS_CB`/`FIRE_STOPS_DEFAULT` siblings (an `_` is
    neither whitespace nor `=`)."""
    m = re.search(r"\bvar\s+" + re.escape(name) + r"\s*=\s*\[(.*?)\];", js, re.S)
    assert m, f"var {name} = [...] not found"
    return m.group(1)


@pytest.mark.parametrize("name", _RAMP_NAMES)
def test_cb_twin_exists_with_identical_breakpoints_and_labels(name):
    js = _script_source()
    default_stops = _STOP_RE.findall(_named_array_literal(js, name))
    cb_stops = _STOP_RE.findall(_named_array_literal(js, f"{name}_CB"))
    assert default_stops, f"{name} has no (threshold, colour, label) stops"
    assert len(cb_stops) == len(default_stops), (
        f"{name}_CB has a different number of stops than {name}"
    )
    for (dt, _dc, dl), (ct, _cc, cl) in zip(default_stops, cb_stops):
        assert dt == ct, f"{name}: breakpoint {dt} != {ct} in the CB twin"
        assert dl == cl, f"{name}: label {dl!r} != {cl!r} in the CB twin"


def _hue_degrees(hexcol: str) -> float:
    r, g, b = (int(hexcol[1:3], 16) / 255, int(hexcol[3:5], 16) / 255,
               int(hexcol[5:7], 16) / 255)
    h, _l, _s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0


@pytest.mark.parametrize("name", _RAMP_NAMES)
def test_cb_twin_never_uses_red_or_green(name):
    """Blue -> yellow throughout, never red<->green — the axis a
    protanopia/deuteranopia viewer cannot reliably distinguish. Checked by
    HSL hue band rather than a raw RGB-channel-dominance comparison: amber/
    gold (e.g. #ca8a04, hue ~41°) has R clearly ahead of B, which a naive
    "R > G+40 and R > B+40"-style check mis-classifies as reddish even
    though it reads as yellow-gold to the eye and sits nowhere near true red
    (hue 0°) or green (hue 120°). Measured hues for this palette cluster at
    ~190-244° (blue/indigo family) and ~40-50° (amber/yellow family) —
    comfortably outside both excluded bands."""
    js = _script_source()
    stops = _STOP_RE.findall(_named_array_literal(js, f"{name}_CB"))
    assert stops, f"{name}_CB has no stops"
    for _thr, hexcol, _label in stops:
        hue = _hue_degrees(hexcol)
        is_reddish = hue <= 15 or hue >= 345
        is_greenish = 100 <= hue <= 160
        assert not is_reddish, f"{name}_CB stop {hexcol} (hue {hue:.0f}°) reads as red"
        assert not is_greenish, f"{name}_CB stop {hexcol} (hue {hue:.0f}°) reads as green"


def test_apply_cb_palette_repoints_wx_layers_ramp():
    """THE mechanism proof this task's spec explicitly asks for: reassigning
    the FIRE_STOPS/FWI_STOPS/TEMP_STOPS variable is NOT enough on its own —
    wtf-map.js's drawLegend() reads `layerDef(active).ramp`, an object
    property that was set to the VALUE those variables held at the moment
    the WX_LAYERS array literal was built. applyCbPalette must re-point
    WX_LAYERS[i].ramp explicitly, or the legend never updates even though
    the province fills / point markers (which read FIRE_STOPS etc. via
    closure at call time) correctly repaint."""
    body = _extract_function(_script_source(), "applyCbPalette")
    assert "WX_LAYERS[0].ramp = FIRE_STOPS" in body
    assert "WX_LAYERS[1].ramp = FWI_STOPS" in body
    assert "WX_LAYERS[2].ramp = TEMP_STOPS" in body
    assert "wtfmap.refresh()" in body


def test_cb_toggle_wired_to_apply_cb_palette_and_localstorage():
    js = _script_source()
    assert 'cbToggleEl.addEventListener("change"' in js
    handler = js[js.index('cbToggleEl.addEventListener("change"'):]
    handler = handler[:handler.index("});") + 3]
    assert "applyCbPalette(" in handler
    assert 'localStorage.setItem("wtf-cb"' in handler


def test_cb_palette_state_read_before_first_use():
    """cbOn must be read from localStorage before applyCbPalette(cbOn) is
    first called (the init call, not the change-handler call)."""
    js = _script_source()
    read_idx = js.index('localStorage.getItem("wtf-cb")')
    init_call_idx = js.index("applyCbPalette(cbOn);")
    assert read_idx < init_call_idx


# ────────────────────────── mutation check (documented, not automated) ────
#
# Mutation check: temporarily delete the three `WX_LAYERS[i].ramp = ...`
# lines from applyCbPalette() (leaving the FIRE_STOPS/FWI_STOPS/TEMP_STOPS
# reassignments in place) and confirm test_apply_cb_palette_repoints_wx_
# layers_ramp AND test_node_smoke_cb_palette_array_swap_updates_wx_layers_
# ramp both fail, then revert. This reproduces the exact bug class the task
# spec warned about: the legend looking unpatched after a toggle even
# though the province fills and point markers correctly repaint (they read
# FIRE_STOPS/etc. via closure, not via WX_LAYERS[i].ramp). Run once at
# authoring time — never bake a git-diffing call into a permanent test
# (feedback_mutation-check-no-runtime-git.md).


# ────────────────────────── node smoke tests ───────────────────────────────
#
# Pattern found in tests/test_wtf_map.py (`_project`, `subprocess.run([node,
# "-e", script], ...)` with `vm.createContext`/`vm.runInContext`) — followed
# here, adapted to extract function bodies out of an HTML template
# (test_wtf_map.py's own harness only ever loads standalone .js files)
# rather than reinventing a second node-shelling convention.


def _run_node(js_setup: str, timeout: int = 30) -> dict:
    """Runs `js_setup` inside a `vm.createContext()` sandbox, then reads back
    whatever it assigned to `globalThis.__result`.

    ⚠️ MEASURED, not assumed: `console` DOES exist inside a bare vm context
    (`typeof console === 'object'`, no ReferenceError) but its `.log()`
    silently writes NOWHERE — it is not wired to the real process stdout in
    this Node version. Calling `console.log(...)` from inside
    `vm.runInContext` therefore looks like it ran (exit code 0, no
    exception) while producing zero output, which is indistinguishable from
    a script that never reached that line. `test_wtf_map.py`'s own harness
    avoids this the same way: it extracts values out of `ctx` (there,
    `ctx.d3`) and does all `console.log`/`JSON` work in the OUTER `node -e`
    realm, never inside `vm.runInContext`. Followed here for `__result`.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    harness = r"""
const vm = require('vm');
const ctx = {};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(%(setup)s, ctx);
console.log(JSON.stringify(ctx.__result === undefined ? null : ctx.__result));
""" % {"setup": json.dumps(js_setup)}
    r = subprocess.run([node, "-e", harness], capture_output=True, text=True,
                        timeout=timeout)
    assert r.returncode == 0, r.stderr[-1500:]
    result = json.loads(r.stdout) if r.stdout.strip() else None
    assert result is not None, "setup script never assigned globalThis.__result"
    return result


def test_node_smoke_write_hash_read_hash_round_trip():
    js = _script_source()
    write_hash_src = _extract_function(js, "writeHash")
    read_hash_src = _extract_function(js, "readHash")

    setup = (
        "var calls = [];\n"
        "var activeLayer = 'wx';\n"
        "var selected = 'ON';\n"
        "var wtfmap = {\n"
        "  setLayer: function (id) { calls.push(['setLayer', id]); },\n"
        "  refresh: function () { calls.push(['refresh']); }\n"
        "};\n"
        "function select(code) { calls.push(['select', code]); }\n"
        "var _hash = '';\n"
        "var location = { get hash() { return _hash; },\n"
        "                  set hash(v) { _hash = v; } };\n"
        "var window = { history: { replaceState: function (s, t, h) { _hash = h; } },\n"
        "               decodeURIComponent: decodeURIComponent };\n"
        "var history = window.history;\n"
        + write_hash_src + "\n"
        + read_hash_src + "\n"
        "writeHash();\n"
        "var hashAfterWrite = location.hash;\n"
        "activeLayer = 'fire'; selected = null;\n"
        "readHash();\n"
        "globalThis.__result = {hashAfterWrite: hashAfterWrite, calls: calls};\n"
    )
    out = _run_node(setup)
    assert out["hashAfterWrite"] == "#layer=wx&prov=ON"
    call_names = [c[0] for c in out["calls"]]
    assert call_names.index("setLayer") < call_names.index("select"), (
        "readHash() must call setLayer before select"
    )
    assert out["calls"][call_names.index("setLayer")][1] == "wx"
    assert out["calls"][call_names.index("select")][1] == "ON"


def test_node_smoke_cb_palette_array_swap_updates_wx_layers_ramp():
    js = _script_source()
    apply_cb_src = _extract_function(js, "applyCbPalette")

    setup = (
        "var FIRE_STOPS_DEFAULT = [[0, '#a', '0']];\n"
        "var FWI_STOPS_DEFAULT  = [[1, '#c', 'x']];\n"
        "var TEMP_STOPS_DEFAULT = [[2, '#e', 'y']];\n"
        "var STATION_TEMP_STOPS_DEFAULT = [[3, '#g', '']];\n"
        "var FIRE_STOPS_CB = [[0, '#b', '0']];\n"
        "var FWI_STOPS_CB  = [[1, '#d', 'x']];\n"
        "var TEMP_STOPS_CB = [[2, '#f', 'y']];\n"
        "var STATION_TEMP_STOPS_CB = [[3, '#h', '']];\n"
        "var FIRE_STOPS = FIRE_STOPS_DEFAULT;\n"
        "var FWI_STOPS  = FWI_STOPS_DEFAULT;\n"
        "var TEMP_STOPS = TEMP_STOPS_DEFAULT;\n"
        "var STATION_TEMP_STOPS = STATION_TEMP_STOPS_DEFAULT;\n"
        "var WX_LAYERS = [{id:'fire', ramp: FIRE_STOPS},\n"
        "                 {id:'wx', ramp: FWI_STOPS},\n"
        "                 {id:'cities', ramp: TEMP_STOPS}];\n"
        "var refreshCalls = 0;\n"
        "var wtfmap = { refresh: function () { refreshCalls++; } };\n"
        + apply_cb_src + "\n"
        "applyCbPalette(true);\n"
        "var afterOn = { fire: WX_LAYERS[0].ramp === FIRE_STOPS_CB,\n"
        "                wx: WX_LAYERS[1].ramp === FWI_STOPS_CB,\n"
        "                cities: WX_LAYERS[2].ramp === TEMP_STOPS_CB,\n"
        "                station: STATION_TEMP_STOPS === STATION_TEMP_STOPS_CB,\n"
        "                refreshCalls: refreshCalls };\n"
        "applyCbPalette(false);\n"
        "var afterOff = { fire: WX_LAYERS[0].ramp === FIRE_STOPS_DEFAULT,\n"
        "                 wx: WX_LAYERS[1].ramp === FWI_STOPS_DEFAULT,\n"
        "                 cities: WX_LAYERS[2].ramp === TEMP_STOPS_DEFAULT,\n"
        "                 station: STATION_TEMP_STOPS === STATION_TEMP_STOPS_DEFAULT,\n"
        "                 refreshCalls: refreshCalls };\n"
        "globalThis.__result = {on: afterOn, off: afterOff};\n"
    )
    out = _run_node(setup)
    assert out["on"] == {
        "fire": True, "wx": True, "cities": True, "station": True,
        "refreshCalls": 1,
    }, "applyCbPalette(true) did not re-point every WX_LAYERS[i].ramp"
    assert out["off"] == {
        "fire": True, "wx": True, "cities": True, "station": True,
        "refreshCalls": 2,
    }, "applyCbPalette(false) did not revert every WX_LAYERS[i].ramp"
