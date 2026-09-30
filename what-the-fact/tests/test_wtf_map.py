"""Guards for the shared map component after the Leaflet -> d3-geo swap.

Three classes of assertion, because three different things could regress and
none of them shows up as a failing page load:

  1. SOVEREIGNTY. The whole point of vendoring is that a reader's browser talks
     only to our origin. One re-added CDN <script> silently undoes that, and the
     page looks perfect. These greps are the only thing standing in the way.
  2. PROJECTION. Run against the ACTUAL VENDORED BUNDLE, not a fresh npm copy —
     a test that passes against node_modules while the shipped file is stale
     proves nothing about what readers get.
  3. HONESTY WORDING. "Outside this view" and "impossible coordinates" are
     different claims about a story's location and must stay distinct.

⚠️ WHY NOT A DOM TEST: rendering needs jsdom, which would add a node_modules
tree to a Python project for one test file. The projection is the part with real
arithmetic in it and it is testable headlessly; the DOM wiring is covered by the
source invariants below plus a live browser drive, which is what actually caught
the last header-state bug (KB #283579).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "consumer/static/js/wtf-map.js"
VENDOR = ROOT / "consumer/static/vendor"
TPL = ROOT / "consumer/templates"


# --------------------------------------------------------------------------
# 1. No third-party requests
# --------------------------------------------------------------------------

# Hosts a reader's browser must never be sent to by this site's own markup.
_FORBIDDEN_HOSTS = (
    "unpkg.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "basemaps.cartocdn.com",
    "tile.openstreetmap.org",
    # /news served every source logo from google.com/s2/favicons — up to 46
    # third-party requests per page view, telling Google which outlets each
    # reader browses. The guard did not list google.com, so news.html PASSED
    # while doing it. Icons are now fetched from each publisher's own domain at
    # build time (scripts/fetch_source_favicons.py) and served from /static.
    "google.com",
)


def _consumer_templates():
    return sorted(TPL.glob("*.html"))


# ⚠️ SCAN THE MARKUP, NOT THE PROSE. The migrated pages EXPLAIN in their comments
# what was removed and why ("pulled raster basemap tiles from basemaps.cartocdn
# .com"), so a bare substring search flags the very documentation of the rule —
# the same way the innerHTML guard below first tripped on the comment forbidding
# innerHTML. What matters is whether the page LOADS from a host, so comments are
# stripped and only src=/href= attributes are examined.
_COMMENT = re.compile(r"\{#.*?#\}|<!--.*?-->|/\*.*?\*/", re.S)
_LOADS = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""")


def _loaded_urls(path: Path) -> list[str]:
    return _LOADS.findall(_COMMENT.sub(" ", path.read_text(encoding="utf-8")))


def _code_without_comments(path: Path) -> str:
    txt = _COMMENT.sub(" ", path.read_text(encoding="utf-8"))
    return "\n".join(ln for ln in txt.splitlines() if not ln.strip().startswith("//"))


# ⚠️ index.html IS NOT MIGRATED BY THIS CHANGE and still runs its own inline
# Leaflet with CARTO tiles. It is the homepage — the busiest page on the site —
# and the largest of the three maps (lean choropleth + article markers +
# centroid circles, ADR-011), so it is a separate piece of work rather than a
# rider on this one.
#
# It is listed here rather than excluded silently, and the list is checked in
# BOTH directions below: a new offender fails, and a page that has since been
# cleaned ALSO fails, forcing it out of the list. A known-gap list nobody is
# obliged to shrink is how "temporary" becomes permanent.
# index.html left this set when the homepage moved onto wtf-map.js (PORT-STATUS row 2);
# it is now covered by every check below like any other migrated page.
_NOT_YET_MIGRATED = set()


@pytest.mark.parametrize("host", _FORBIDDEN_HOSTS)
def test_no_migrated_template_loads_from_a_third_party_cdn(host):
    """The reason this is a test and not a comment: /map carried CARTO basemap
    tiles for months while wtf-map.js's own docstring promised 'NO third-party
    tiles'. A promise in a docstring is not enforcement."""
    offenders = [p.name for p in _consumer_templates()
                 if p.name not in _NOT_YET_MIGRATED
                 and any(host in u for u in _loaded_urls(p))]
    assert not offenders, f"{host} referenced by: {offenders}"


def test_the_unmigrated_list_is_still_accurate():
    """Fails when a listed page no longer needs to be listed. Without this the
    exemption outlives the problem and quietly protects a regression."""
    for name in _NOT_YET_MIGRATED:
        urls = _loaded_urls(TPL / name)
        assert any(h in u for h in _FORBIDDEN_HOSTS for u in urls), (
            f"{name} is clean — remove it from _NOT_YET_MIGRATED")


def test_leaflet_is_gone_from_every_migrated_page():
    hits = {p.name: [ln.strip()[:60] for ln in _code_without_comments(p).splitlines()
                     if "leaflet" in ln.lower()]
            for p in _consumer_templates() if p.name not in _NOT_YET_MIGRATED}
    hits = {k: v for k, v in hits.items() if v}
    assert not hits, f"leaflet still referenced: {hits}"
    assert "L.map(" not in _code_without_comments(JS)


def test_the_vendored_libraries_exist_and_are_the_ones_referenced():
    names = {"internmap.min.js", "d3-array.min.js", "d3-geo.min.js"}
    on_disk = {p.name for p in VENDOR.glob("*.js")}
    assert names <= on_disk, f"missing vendored files: {names - on_disk}"
    for page in ("map.html", "weather.html"):
        src = (TPL / page).read_text(encoding="utf-8")
        for n in names:
            assert f"/static/vendor/{n}" in src, f"{page} does not load {n}"


def test_load_order_is_dependency_correct():
    """d3-geo needs d3-array needs internmap. Out of order, d3.geoConicConformal
    is undefined and the component prints 'Map library failed to load.' — which
    is honest, but the map is still gone."""
    for page in ("map.html", "weather.html"):
        src = (TPL / page).read_text(encoding="utf-8")
        i = src.index("internmap.min.js")
        a = src.index("d3-array.min.js")
        g = src.index("d3-geo.min.js")
        assert i < a < g, page


def test_vendor_versions_are_recorded():
    """A vendored copy with no recorded version cannot be updated safely or
    audited for a CVE."""
    txt = (VENDOR / "VERSIONS.txt").read_text(encoding="utf-8")
    for pkg in ("internmap@", "d3-array@", "d3-geo@"):
        assert pkg in txt, pkg


# --------------------------------------------------------------------------
# 2. Projection — against the shipped bundle
# --------------------------------------------------------------------------

# The bundles are our own files, read from the repo by absolute path, with no
# caller-supplied input reaching them. vm.runInThisContext is used rather than
# eval() because it is the explicit "run this script file" primitive: no
# surrounding scope is captured, and the intent is legible at the call site.
_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const ctx = {};
ctx.globalThis = ctx;
vm.createContext(ctx);
%(loads)s
const d3 = ctx.d3;
const geo = JSON.parse(fs.readFileSync(%(geojson)s, 'utf8'));
const W = 980, H = 560, pad = 12;
const proj = d3.geoConicConformal().parallels([49, 77]).rotate([96, 0])
  .fitExtent([[pad, pad], [W - pad, H - pad]], geo);
const pts = %(points)s;
const out = {};
for (const [name, c] of Object.entries(pts)) {
  const xy = proj(c);
  out[name] = !!(xy && isFinite(xy[0]) && isFinite(xy[1]) &&
                 xy[0] >= 0 && xy[1] >= 0 && xy[0] <= W && xy[1] <= H);
}
console.log(JSON.stringify(out));
"""


def _project(points: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    loads = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(VENDOR / n))}, 'utf8'), ctx);"
        for n in ("internmap.min.js", "d3-array.min.js", "d3-geo.min.js")
    )
    script = _HARNESS % {
        "loads": loads,
        "geojson": json.dumps(str(ROOT / "consumer/static/canada-provinces.geojson")),
        "points": json.dumps(points),
    }
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_every_province_capital_lands_on_the_canvas():
    """If the projection or the fit regressed, this is where it shows. These are
    real coordinates and the answer is checkable against any atlas."""
    got = _project({
        "Victoria BC": [-123.37, 48.43], "Edmonton AB": [-113.49, 53.55],
        "Regina SK": [-104.62, 50.45], "Winnipeg MB": [-97.14, 49.90],
        "Toronto ON": [-79.38, 43.65], "Quebec City QC": [-71.21, 46.81],
        "Fredericton NB": [-66.64, 45.96], "Halifax NS": [-63.57, 44.65],
        "Charlottetown PE": [-63.13, 46.24], "St John's NL": [-52.71, 47.56],
        "Whitehorse YT": [-135.05, 60.72], "Yellowknife NT": [-114.37, 62.45],
        "Iqaluit NU": [-68.52, 63.75],
    })
    missing = [k for k, v in got.items() if not v]
    assert not missing, f"off-canvas: {missing}"


def test_distant_locations_are_clipped_not_silently_squeezed_in():
    """A Canada conic MUST drop these. If it ever draws them, the projection has
    been replaced by something global and the map is lying about its extent."""
    got = _project({"London GB": [-0.13, 51.51], "Tokyo JP": [139.69, 35.69],
                    "Shanghai CN": [121.47, 31.23], "Sydney AU": [151.21, -33.87]})
    drawn = [k for k, v in got.items() if v]
    assert not drawn, f"should be clipped: {drawn}"


# --------------------------------------------------------------------------
# 3. Honesty invariants in the component source
# --------------------------------------------------------------------------


def test_an_impossible_coordinate_is_reported_differently_from_an_offscreen_one():
    """Measured in the live feed: a story carries lat -117.95 / lng 49.28, which
    is a transposed pair, not a location outside Canada. Reporting it as
    'outside this view' states something false about where the story is."""
    src = JS.read_text(encoding="utf-8")
    assert "p.lat < -90 || p.lat > 90" in src
    assert "outside the possible range" in src
    assert "outside this view of Canada" in src


def test_external_text_never_reaches_innerHTML():
    """Tooltips carry article titles — external content, WTF XSS rule."""
    src = JS.read_text(encoding="utf-8")
    # The word appears twice, in the comments that FORBID it. What must never
    # appear is an assignment — checking for the bare word fails on its own rule.
    assert ".innerHTML =" not in src and ".innerHTML=" not in src
    assert "tip.textContent = text" in src


def test_the_leaflet_instance_is_not_exposed_as_map():
    """weather.html used to call wtfmap.map.flyTo(). Re-exposing `.map` on a
    component with no Leaflet behind it would be an interface that lies."""
    src = JS.read_text(encoding="utf-8")
    ret = src[src.rindex("return {"):src.rindex("global.WTFMap")]
    assert "map:" not in ret, ret
    for fn in ("focusProvince", "resetView", "getOffscreenCount", "getInvalidCount"):
        assert fn in ret, fn


def test_weather_uses_the_component_api_not_a_leaflet_call():
    src = (TPL / "weather.html").read_text(encoding="utf-8")
    assert ".flyTo(" not in src
    assert "wtfmap.focusProvince(" in src and "wtfmap.resetView()" in src


def test_map_page_legend_counts_what_was_drawn_not_what_was_handed_in():
    """The page's own long-standing rule — 'the legend always describes what is
    on screen' — has to survive a projection that can now clip."""
    src = (TPL / "map.html").read_text(encoding="utf-8")
    assert "onRender" in src
    assert "drawLegend(r.drawn, r.offscreen)" in src
    assert "drawn.forEach" in src, "tally must be computed from the drawn list"


def test_map_has_no_paywall_gate():
    """2026-09-04 (KB vault_note #304357): the whole map+legend used to sit
    inside {% if is_subscriber %}, blocking the ENTIRE page for every
    signed-out reader even though nothing premium was built behind the gate
    (no city-level pins, no history scrubber, no per-outlet breakdown — those
    are still just design-mockup ideas, not shipped features). Gate a real
    enhancement specifically if one is ever built; don't gate the base map."""
    src = (TPL / "map.html").read_text(encoding="utf-8")
    assert "is_subscriber" not in src, "map.html must not gate the base map"
    assert "paywall(" not in src
    assert 'id="wtfMap"' in src, "the map div itself must be unconditionally present"
