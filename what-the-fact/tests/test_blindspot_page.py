"""/blindspot renders its stories SERVER-SIDE (#6165).

WHY THIS FILE EXISTS. The page shipped as an empty `<div id="bs-list">` waiting
for JavaScript that was never written: no <script> in the template, and nothing
anywhere in static/js/ referenced `bs-list` or `wtf-bs-`. Meanwhile
/api/v1/blindspot returned 20 real stories and the page sat in the main nav — so
every visitor got a heading, four dead filter buttons, and nothing else.

Verified live on production before the fix: `#bs-list` had 0 children and the
only script on the page was i18n.js.

The defect was invisible to every existing check: the template parsed, the route
returned 200, and the API was healthy. Only *rendering the page and counting the
stories* catches it — which is what these tests do.
"""

import pathlib
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROOT = TPL.parents[1]

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")

WINDOWS = (3, 7, 14, 30)


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


BLINDSPOTS = [
    {
        "id": 4211, "representative_title": "Fallback title",
        # a hostile headline — this product renders scraped news
        "headline": "Watchdog report <script>alert(1)</script> buried",
        "brief": "Only two outlets carried it.",
        "article_count": 3, "source_count": 2,
        "coverage_gap_score": 0.04, "certainty_label": "Established",
    },
    {
        # no headline and no brief — must fall back, not render blank
        "id": 4212, "representative_title": "Committee testimony goes unreported",
        "headline": None, "brief": None,
        "article_count": 2, "source_count": 1,
        "coverage_gap_score": 0.13, "certainty_label": None,
    },
]


def page(env, *, rows=BLINDSPOTS, days=7, subscriber=False):
    return env.get_template("blindspot.html").render(
        blindspots=rows, days=days, windows=WINDOWS, is_subscriber=subscriber)


class TestTheStoriesActuallyRender:
    """The whole defect: a page that returned 200 and showed nothing."""

    def test_every_story_appears(self, env):
        html = page(env)
        assert "Watchdog report" in html
        assert "Committee testimony goes unreported" in html
        assert html.count("wtf-a-rcard") >= len(BLINDSPOTS)

    def test_a_story_without_a_headline_falls_back_to_its_title(self, env):
        """headline is LEFT JOINed from summaries and is often NULL — a card
        must not render blank when it is."""
        html = page(env)
        assert "Committee testimony goes unreported" in html

    def test_the_page_needs_no_client_javascript(self, env):
        html = page(env)
        assert "<script" not in html.lower(), "server-rendered — no JS required"
        assert 'id="bs-list"' not in html, "the empty JS mount point is gone"

    def test_no_js_file_is_expected_to_fill_this_page(self):
        """The original bug was an implicit dependency on a file that never
        existed. Assert nothing in the repo is supposed to fill it."""
        js_dir = ROOT / "consumer" / "static" / "js"
        if not js_dir.exists():
            pytest.skip("no static/js directory")
        hits = [p.name for p in js_dir.glob("*.js") if "bs-list" in p.read_text(errors="ignore")]
        assert not hits, f"{hits} still target the removed mount point"


class TestTheWindowFilterWorksWithoutJavaScript:
    def test_each_window_is_a_real_link(self, env):
        html = page(env, days=7)
        for w in WINDOWS:
            assert f"/blindspot?days={w}" in html, f"{w}-day window is not a link"

    def test_the_current_window_is_marked(self, env):
        html = page(env, days=14)
        assert "is-active" in html

    def test_the_route_validates_the_window(self):
        """A hand-typed ?days=999 must not reach the SQL. Read from source.

        ⚠️ Asserting merely that `_BLINDSPOT_WINDOWS` appears in the body is
        NOT enough — the constant is also passed to the template as
        `windows=_BLINDSPOT_WINDOWS`, so that check survives deleting the
        validation entirely. It did; the mutation run caught it. Assert the
        MEMBERSHIP TEST itself.
        """
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def blindspot_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "days not in _BLINDSPOT_WINDOWS" in body, (
            "the window is not range-checked — ?days=999 reaches the query"
        )
        assert "days = 7" in body, "no fallback for an out-of-range window"

    def test_a_non_numeric_window_does_not_500(self):
        """?days=abc must fall back, not raise."""
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def blindspot_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "except (TypeError, ValueError)" in body


class TestSeverityIsReadable:
    def test_gap_severity_carries_a_text_label(self, env):
        """Colour alone is never the signal — the rule the lean scale is on."""
        html = page(env)
        assert "Near-total blackout" in html   # 4%
        assert "Thinly covered" in html        # 13%

    def test_the_coverage_share_is_stated_as_a_number(self, env):
        html = page(env)
        assert "4% of tracked press" in html
        assert "13% of tracked press" in html


class TestHonestEmptyAndPaywall:
    def test_an_empty_window_says_so_rather_than_rendering_nothing(self, env):
        """An empty list must be DISTINGUISHABLE from the old broken page."""
        html = page(env, rows=[])
        assert "No blind spots in the last 7 days" in html

    def test_anonymous_gets_the_shared_paywall_but_still_sees_the_stories(self, env):
        """The story list was always public; only deeper analysis is gated."""
        html = page(env, subscriber=False)
        assert "wtf-a-pay" in html and "/login?next=/blindspot" in html
        assert "Watchdog report" in html, "the free story list must not be gated"

    def test_a_subscriber_gets_no_paywall(self, env):
        assert "wtf-a-pay" not in page(env, subscriber=True)


class TestNoPrivateStyling:
    def test_no_orbitron_and_no_literal_hex(self, env):
        html = page(env)
        assert "Orbitron" not in html
        hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b", html))
        assert not hexes, f"blindspot.html hardcodes {sorted(hexes)}"


class TestExternalTextIsEscaped:
    def test_headline_is_escaped(self, env):
        html = page(env)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)" not in html


class TestPageAndApiShareOneQuery:
    def test_the_api_calls_the_same_helper_as_the_page(self):
        """A story shown to a reader and one returned to an API client must be
        the same set — so the SQL must live in exactly one place."""
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert src.count("def _blindspot_rows(") == 1
        api_start = src.index("def api_v1_blindspot():")
        api_body = src[api_start:src.index("\n@bp.", api_start)]
        assert "_blindspot_rows(" in api_body, "API no longer shares the helper"
        assert "story_clusters" not in api_body, "API re-inlined its own SQL — it can drift"
