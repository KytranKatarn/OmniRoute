"""/mps — Ridings tab (#6272, Batch 8, final item).

design-handoff/wtf-mps.html's Ridings tab wants a Lambert-projection MAP of
338 riding boundary polygons plus postal-code search. Neither the boundary
geometry nor a postal-code geocoder exists on this platform, and the
design's own prose admits its sample build has no riding-to-member join
either ("Ridings are shown only for the five members on record; the rest
read 'not recorded'"). That map+geocode version stays out of scope — same
blocker as the standalone /ridings page (Batch 9).

What IS real: `parliament.mps.riding_name` is fully populated on the live
roster (337 current MPs, 337 have riding_name, 337 distinct, 0 missing —
measured 2026-09-04). `mps_listing()` (routes.py:4369) already SELECTs it
into every row of the `mps` list the template receives — no new query
needed. This adds a third tab: a searchable riding->MP list built from data
already in hand. Same "port what's real, drop what's ambitious-but-absent"
discipline as governance.html and weather_city.html.

The filter/sort JS was extracted from the template and functionally
exercised in Node with a mock DOM (sort order, substring match on riding
name, substring match on MP name, empty-result state, reset) before this
file was written — this file re-asserts the STATIC template contract
(markup present, existing tabs undisturbed, honest no-map copy), not the
JS behavior itself (Jinja rendering can't execute client-side JS).
"""

import pathlib
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


MOCK_MPS = [
    {"slug": "a-mp", "name": "Alex Alderman", "party": "Liberal", "riding_name": "Alderwood",
     "province_code": "ON", "photo_url": None, "twitter": None, "cabinet_role": None,
     "vote_count": 12, "mention_count": 4, "party_colour": "#dc2626"},
    {"slug": "b-mp", "name": "Bea Baxter", "party": "Conservative", "riding_name": "Bexley",
     "province_code": "AB", "photo_url": None, "twitter": None, "cabinet_role": None,
     "vote_count": 8, "mention_count": 2, "party_colour": "#1e40af"},
]


def _render(env, **overrides):
    kwargs = dict(
        mps=MOCK_MPS, parties=["Liberal", "Conservative"], provinces=["ON", "AB"],
        party_filter="all", province_filter="ALL", source_count=46,
        senators=[], total_seats=337,
    )
    kwargs.update(overrides)
    return env.get_template("mps.html").render(**kwargs)


def _body(html):
    return html.split("</style>", 1)[1]


class TestRidingsTabPresent:
    def test_tab_button_present(self, env):
        b = _body(_render(env))
        assert "🗺 Ridings" in b

    def test_pane_present_and_initially_hidden(self, env):
        html = _render(env)
        i = html.index('id="wtf-tab-ridings"')
        # the display:none inline style is on the same opening tag
        tag = html[html.rindex("<div", 0, i):html.index(">", i) + 1]
        assert 'style="display:none;"' in tag

    def test_search_input_present(self, env):
        b = _body(_render(env))
        assert 'id="rd-search-input"' in b
        assert "Search by riding name or MP name" in b

    def test_wtftab_js_includes_ridings_target(self, env):
        html = _render(env)
        wtf_tab_fn = html[html.index("function wtfTab"):html.index("</script>", html.index("function wtfTab"))]
        assert "'ridings'" in wtf_tab_fn


class TestNoFabricatedMapOrGeocoding:
    """The design's map+postal-code version is deliberately not built."""

    def test_disclosure_states_this_is_not_a_map(self, env):
        b = _body(_render(env))
        assert "not a map" in b

    def test_no_postal_code_search_field(self, env):
        """The design's Ridings tab has a dedicated postal-code <input>; this
        build's only input is the riding/MP-name search box."""
        pane = html_pane(_render(env))
        inputs = re.findall(r"<input[^>]*>", pane)
        assert len(inputs) == 1
        assert "postal" not in inputs[0].lower()

    def test_no_svg_map_or_boundary_rendering_in_ridings_pane(self, env):
        pane = html_pane(_render(env))
        assert "<svg" not in pane
        assert "boundary" not in pane.lower() or "boundary data" in pane.lower()


def html_pane(html):
    start = html.index('id="wtf-tab-ridings"')
    start = html.rindex("<div", 0, start)
    end = html.index("<!-- /wtf-tab-ridings -->")
    return html[start:end]


class TestRidingDataRendersHonestly:
    def test_mock_riding_names_reach_the_js_payload(self, env):
        # The pane markup itself is a static shell (JS populates #rd-list at
        # runtime) — the riding data lives in the RD_MPS json payload in the
        # <script> block right after the pane, not in the pane div.
        html = _render(env)
        payload_start = html.index("var RD_MPS")
        payload = html[payload_start:html.index(";", payload_start)]
        assert "Alderwood" in payload
        assert "Bexley" in payload

    def test_no_riding_count_hardcoded_stale(self, env):
        """The lede states the count from mps|length, not a fixed number."""
        b = _body(_render(env, mps=MOCK_MPS))
        assert f"{len(MOCK_MPS)} tracked" in b


class TestExistingTabsUndisturbed:
    def test_hoc_and_senate_panes_still_present(self, env):
        html = _render(env)
        assert 'id="wtf-tab-hoc"' in html
        assert 'id="wtf-tab-senate"' in html

    def test_hoc_still_the_default_active_tab(self, env):
        html = _render(env)
        # The HoC button still carries 'active'; the new Ridings button does not.
        hoc_btn = re.search(r'<button class="([^"]*)"[^>]*onclick="wtfTab\(\'hoc\'', html)
        rd_btn = re.search(r'<button class="([^"]*)"[^>]*onclick="wtfTab\(\'ridings\'', html)
        assert hoc_btn and "active" in hoc_btn.group(1)
        assert rd_btn and "active" not in rd_btn.group(1)

    def test_seating_map_script_and_senator_data_untouched(self, env):
        html = _render(env)
        assert "ALL_SENATORS" in html
        assert "wtf-parl-svg" in html


class TestMpsRoutingWiring:
    """Mirrors TestCreedRouteWiring's source-grep approach — this change
    touched the template only, so confirm routes.py's mps_listing() still
    selects riding_name and passes the same kwargs it always did."""

    def test_route_still_selects_riding_name(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def mps_listing(")
        end = src.index("\n\n\n", start)
        body = src[start:end]
        assert "riding_name" in body
        assert 'render_template("mps.html"' in body
