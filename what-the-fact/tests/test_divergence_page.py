"""/divergence renders its stories SERVER-SIDE (batch 5, WTF design-handoff rollout).

WHY THIS FILE EXISTS. The page shipped with an empty `<div id="div-list">` and
4 window filter buttons carrying `data-days` attributes but no click handler
anywhere in static/js/ — /api/v1/divergence had real rows the whole time.
Same defect shape as /blindspot before #5767 (see test_blindspot_page.py):
the template parsed, the route returned 200, the API was healthy — only
*rendering the page and counting the stories* catches it.
"""

import pathlib
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROOT = TPL.parents[1]

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")

WINDOWS = (7, 30, 60, 90)


class FakeRequest:
    path = "/divergence"


@pytest.fixture(scope="module")
def env():
    e = Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )
    e.globals["request"] = FakeRequest()
    return e


DIVERGENCES = [
    {
        "id": 501, "representative_title": "Budget vote <script>alert(1)</script> splits coverage",
        "article_count": 12, "certainty_label": "high",
        "en_count": 5, "fr_count": 0, "en_avg_score": 0.42, "fr_avg_score": None,
        "divergence_score": 0.42, "en_only": True, "fr_only": False,
    },
    {
        # no title, no fr_avg_score — must fall back / show a dash, not vanish
        "id": 502, "representative_title": None, "article_count": 4,
        "certainty_label": None, "en_count": 0, "fr_count": 3,
        "en_avg_score": None, "fr_avg_score": -0.15,
        "divergence_score": 0.15, "en_only": False, "fr_only": True,
    },
    {
        "id": 503, "representative_title": "Pipeline debate framed differently",
        "article_count": 20, "certainty_label": "medium",
        "en_count": 6, "fr_count": 4, "en_avg_score": 0.3, "fr_avg_score": -0.2,
        "divergence_score": 0.5, "en_only": False, "fr_only": False,
    },
]


def page(env, *, rows=DIVERGENCES, days=30, subscriber=False):
    return env.get_template("divergence.html").render(
        divergences=rows, days=days, windows=WINDOWS, is_subscriber=subscriber)


class TestTheStoriesActuallyRender:
    """The whole defect: a page that returned 200 and showed nothing."""

    def test_every_story_appears(self, env):
        html = page(env)
        assert "splits coverage" in html
        assert "Pipeline debate framed differently" in html
        # count OPENING card divs specifically — "wtf-dv-dv-card" as a bare
        # substring also matches its own CSS rule + 3 modifier selectors in
        # the page's <style> block, which are always present regardless of
        # story count and would make this assertion pass on zero cards.
        assert len(re.findall(r'<div class="wtf-dv-dv-card', html)) == len(DIVERGENCES)

    def test_a_story_without_a_title_does_not_vanish(self, env):
        """representative_title is nullable — the card must still render."""
        html = page(env)
        assert "Untitled story" in html

    def test_the_page_needs_no_client_javascript(self, env):
        html = page(env)
        assert "<script" not in html.lower(), "server-rendered — no JS required"

    def test_no_js_file_targets_the_removed_mount_point(self):
        js_dir = ROOT / "consumer" / "static" / "js"
        if not js_dir.exists():
            pytest.skip("no static/js directory")
        hits = [p.name for p in js_dir.glob("*.js") if "div-list" in p.read_text(errors="ignore")]
        assert not hits, f"{hits} still target the removed mount point"


class TestTheWindowFilterWorksWithoutJavaScript:
    def test_each_window_is_a_real_link(self, env):
        html = page(env, days=30)
        for w in WINDOWS:
            assert f"/divergence?days={w}" in html, f"{w}-day window is not a link"

    def test_the_current_window_is_marked(self, env):
        html = page(env, days=60)
        assert "wtf-dv-active" in html

    def test_the_route_validates_the_window(self):
        """A hand-typed ?days=999 must not reach the SQL. Read from source —
        asserting the constant merely APPEARS is not enough (it's also passed
        to the template as windows=), so assert the membership test itself."""
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "days not in _DIVERGENCE_WINDOWS" in body, (
            "the window is not range-checked — ?days=999 reaches the query"
        )
        assert "days = 30" in body, "no fallback for an out-of-range window"

    def test_a_non_numeric_window_does_not_500(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "except (TypeError, ValueError)" in body


class TestDivergenceTypeIsReadable:
    """Colour alone is never the signal — every card carries a text badge."""

    def test_en_only_is_labelled(self, env):
        html = page(env)
        assert "EN ONLY" in html

    def test_fr_only_is_labelled(self, env):
        html = page(env)
        assert "FR ONLY" in html

    def test_bias_gap_is_labelled(self, env):
        html = page(env)
        assert "BIAS GAP" in html

    def test_missing_scores_show_a_dash_not_a_fabricated_number(self, env):
        """en_avg_score/fr_avg_score are nullable per-language — a missing
        score must render as an explicit absence, never coerce to 0.0."""
        html = page(env)
        assert "—" in html


class TestHonestEmptyAndPaywall:
    def test_an_empty_window_says_so_rather_than_rendering_nothing(self, env):
        html = page(env, rows=[])
        assert "No divergent stories in this window" in html

    def test_anonymous_gets_the_shared_paywall_but_still_sees_the_stories(self, env):
        html = page(env, subscriber=False)
        assert '<div class="wtf-dv-paywall-gate">' in html
        assert "splits coverage" in html, "the free story list must not be gated"

    def test_a_subscriber_gets_no_paywall(self, env):
        # the class name still appears in the page's own <style> block (CSS
        # rules are static regardless of subscriber status) — assert on the
        # rendered element, not the bare class-name substring.
        assert '<div class="wtf-dv-paywall-gate">' not in page(env, subscriber=True)


class TestNoPrivateStyling:
    def test_no_orbitron(self, env):
        assert "Orbitron" not in page(env)


class TestExternalTextIsEscaped:
    def test_title_is_escaped(self, env):
        html = page(env)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)" not in html


class TestPageAndApiShareOneQuery:
    def test_the_api_calls_the_same_helper_as_the_page(self):
        """A story shown to a reader and one returned to an API client must be
        the same set — so the SQL must live in exactly one place."""
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert src.count("def _divergence_rows(") == 1
        api_start = src.index("def api_v1_divergence():")
        # Bound at whichever comes first: the next route OR the next
        # top-level def — see test_blindspot_page.py's identical guard for
        # why a bare "\n@bp." boundary is fragile to a later insertion.
        next_bp = src.index("\n@bp.", api_start)
        next_def_idx = src.find("\ndef ", api_start)
        api_end = min(next_bp, next_def_idx) if next_def_idx != -1 else next_bp
        api_body = src[api_start:api_end]
        assert "_divergence_rows(" in api_body, "API no longer shares the helper"
        assert "cluster_lang AS" not in api_body, "API re-inlined its own SQL — it can drift"
