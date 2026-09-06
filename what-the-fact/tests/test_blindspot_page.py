"""/blindspot renders its stories SERVER-SIDE (#6165), political-LEAN
imbalance edition (task #6524).

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

Redesigned (task #6524) from an outlet-COUNT silence signal to a political-
LEAN coverage imbalance signal — a story lands here when one side of the
spectrum covered it and the other (almost) didn't, computed by
ingest/cluster_metrics.py and precomputed onto story_clusters.blindspot_side.
coverage_gap_score is still a real column (surfaced on /archive) but is no
longer what this page means.
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
        "brief": "Only right-leaning outlets carried it.",
        "article_count": 5, "source_count": 4,
        "coverage_gap_score": 0.09, "certainty_label": "Established",
        "blindspot_side": "L", "lean_l_count": 0, "lean_c_count": 1, "lean_r_count": 4,
        "age_hours": 18.0,
        "reasons": [
            ("No bureau on that side in AB",
             "No outlet on that side of the spectrum has filed from this province in the corpus at all, on any story."),
            ("Staffed, and still absent",
             "Outlets on that side cover this beat and this province elsewhere, and did not carry this story."),
        ],
    },
    {
        # no headline and no brief — must fall back, not render blank
        "id": 4212, "representative_title": "Committee testimony goes unreported",
        "headline": None, "brief": None,
        "article_count": 4, "source_count": 4,
        "coverage_gap_score": 0.13, "certainty_label": None,
        "blindspot_side": "R", "lean_l_count": 3, "lean_c_count": 0, "lean_r_count": 0,
        "age_hours": 2.5,
        "reasons": [
            ("The story is 2.5 hours old",
             "A gap this young is a news cycle, not an editorial position. It may close today."),
        ],
    },
]


def page(env, *, rows=BLINDSPOTS, days=7, subscriber=False, total=2883):
    return env.get_template("blindspot.html").render(
        blindspots=rows, total_in_window=total, days=days, windows=WINDOWS,
        is_subscriber=subscriber)


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


class TestLeanImbalanceIsReadable:
    """Task #6524: the signal is which SIDE was silent, not how few outlets
    ran the story — colour is never the only carrier of that."""

    def test_each_card_names_the_silent_side(self, env):
        html = page(env)
        assert "Left blindspot" in html
        assert "Right blindspot" in html

    def test_the_lean_split_is_stated_as_numbers(self, env):
        html = page(env)
        assert "L 0" in html and "C 1" in html and "R 4" in html
        assert "L 3" in html and "C 0" in html and "R 0" in html

    def test_the_methodology_names_the_real_rule(self, env):
        html = page(env)
        assert "quarter or less" in html
        assert "at least three articles behind" in html


class TestReasonsAreSubscriberGated:
    """Reasons ('why is this side silent') are the paywalled deeper analysis —
    the story itself and its side/split stay free, matching the paywall
    boundary the page already had (HARD RULE: never touch paywall scope)."""

    def test_anonymous_does_not_see_reasons(self, env):
        html = page(env, subscriber=False)
        assert "No bureau on that side in AB" not in html
        assert "Left blindspot" in html, "the card itself must still be free"

    def test_subscriber_sees_reasons(self, env):
        html = page(env, subscriber=True)
        assert "No bureau on that side in AB" in html
        assert "Staffed, and still absent" in html

    def test_a_young_story_gets_the_age_reason(self, env):
        html = page(env, subscriber=True)
        assert "2.5 hours old" in html


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
        # Bound the slice at whichever comes first: the next route OR the
        # next top-level def/helper — an unrelated function inserted right
        # after api_v1_blindspot() (e.g. a later page's own shared-rows
        # helper) must not get swept into this function's body.
        next_bp = src.index("\n@bp.", api_start)
        next_def = src.index("\ndef ", api_start)
        api_end = min(next_bp, next_def)
        api_body = src[api_start:api_end]
        assert "_blindspot_rows(" in api_body, "API no longer shares the helper"
        assert "story_clusters" not in api_body, "API re-inlined its own SQL — it can drift"

    def test_the_api_reports_blindspot_side_not_just_the_old_gap_score(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        api_start = src.index("def api_v1_blindspot():")
        api_end = src.index("\n@bp.", api_start)
        api_body = src[api_start:api_end]
        assert '"blindspot_side"' in api_body


class TestTheCountIsThePopulationNotThePageSize:
    """`blindspots|length` is the LIMIT (20). Measured live: 255 stories
    qualify in 3 days and 2,883 in 30. Printing 20 as "stories in window" tells
    a reader there are twenty blind spots in a month when there are nearly
    three thousand — the same shape as /owners' 149% shares."""

    def test_the_tile_shows_the_qualifying_total(self, env):
        html = page(env, total=2883)
        assert "2,883" in html, "the tile shows the page size, not the population"

    def test_the_page_size_is_stated_separately(self, env):
        html = page(env, total=2883)
        assert f"showing {len(BLINDSPOTS)} most recent" in html

    def test_the_two_numbers_are_not_conflated(self, env):
        """A window with more qualifying stories than fit on the page must not
        report the page size as the total."""
        html = page(env, total=255, days=3)
        assert "255" in html and "showing 2 most recent" in html
