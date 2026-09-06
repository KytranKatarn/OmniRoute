"""/divergence renders its stories SERVER-SIDE, two views (task #6524 redesign).

WHY THIS FILE EXISTS. The page shipped with an empty `<div id="div-list">` and
4 window filter buttons carrying `data-days` attributes but no click handler
anywhere in static/js/ — /api/v1/divergence had real rows the whole time.
Same defect shape as /blindspot before #5767 (see test_blindspot_page.py):
the template parsed, the route returned 200, the API was healthy — only
*rendering the page and counting the stories* catches it.

Redesigned (task #6524): the PRIMARY view (view=disputes, default) is a
"checkable fact in dispute" tracker (design-handoff/wtf-divergence.js). The
ORIGINAL French-English coverage-language detection is kept exactly as it
shipped, demoted to a secondary view=language tab — Kytran confirmed this
session it should not be retired. TestDisputes* classes below cover the new
primary view; TestLanguageView* classes cover the (unchanged) secondary one.
"""

import pathlib
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROOT = TPL.parents[1]

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")

LANGUAGE_WINDOWS = (7, 30, 60, 90)
DISPUTE_WINDOWS = (30, 90, 180, 365)


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


# ─────────────────────────── disputes (primary) view ───────────────────────

DISPUTES = [
    {
        "id": 601, "representative_title": "Rate hold <script>alert(1)</script> splits reaction",
        "article_count": 9, "beat": "economy",
        "lean_l_count": 3, "lean_c_count": 1, "lean_r_count": 5,
        "divergence_score": 62, "disputed_point": "Whether the hold signals a cut at the next meeting",
        "verdict": "developing", "is_opinion": False, "why": None,
        "left_articles": [{"title": "Left headline", "source_name": "CBC"}],
        "right_articles": [{"title": "Right headline", "source_name": "National Post"}],
    },
    {
        # no verdict, is_opinion — must show "Opinion, not scored"; right side
        # has NO articles — must say so, not skip the whole sides block (that
        # only happens when BOTH sides are empty).
        "id": 602, "representative_title": "Forecast dispute over next quarter",
        "article_count": 7, "beat": "business",
        "lean_l_count": 2, "lean_c_count": 0, "lean_r_count": 3,
        "divergence_score": 40, "disputed_point": "Whether the hold signals a cut",
        "verdict": None, "is_opinion": True, "why": None,
        "left_articles": [{"title": "Only-side headline", "source_name": "CBC"}],
        "right_articles": [],
    },
]

EXCLUDED = [
    {
        "id": 603, "representative_title": "Thin story, not enough spread",
        "article_count": 3, "beat": "politics",
        "lean_l_count": 2, "lean_c_count": 1, "lean_r_count": 0,
        "divergence_score": None, "disputed_point": None,
        "verdict": None, "is_opinion": None, "why": "fewer than six outlets",
        "left_articles": [], "right_articles": [],
    },
]


def disputes_page(env, *, rows=DISPUTES, days=90, subscriber=False,
                   total=None, show_excluded=False):
    return env.get_template("divergence.html").render(
        view="disputes", disputes=rows, days=days, windows=DISPUTE_WINDOWS,
        is_subscriber=subscriber,
        total_in_window=(total if total is not None else len(rows)),
        show_excluded=show_excluded)


class TestDisputesActuallyRender:
    def test_every_dispute_appears(self, env):
        html = disputes_page(env)
        assert "splits reaction" in html
        assert "Forecast dispute over next quarter" in html
        assert len(re.findall(r'wtf-a-rcard', html)) >= len(DISPUTES)

    def test_the_disputed_point_is_shown(self, env):
        html = disputes_page(env)
        assert "Whether the hold signals a cut at the next meeting" in html

    def test_the_page_needs_no_client_javascript(self, env):
        html = disputes_page(env)
        assert "<script" not in html.lower(), "server-rendered — no JS required"


class TestOpinionDisputesAreNotScored:
    """Task #6524's forecast case — no document settles a forecast."""

    def test_opinion_shows_not_scored_not_a_verdict(self, env):
        html = disputes_page(env)
        assert "Opinion, not scored" in html
        # the opinion row's own verdict is None — it must never render a
        # capitalized verdict word for that row specifically
        assert "does not score it" in html.lower() or "settles a forecast" in html.lower()

    def test_a_real_verdict_is_shown_capitalized(self, env):
        html = disputes_page(env)
        assert "Developing" in html


class TestExcludedStoriesAreHonest:
    """A cluster that doesn't qualify is EXCLUDED, not silently dropped —
    with a specific, real reason (task #6524's why-classification)."""

    def test_excluded_view_shows_the_reason(self, env):
        html = disputes_page(env, rows=EXCLUDED, show_excluded=True)
        assert "fewer than six outlets" in html
        assert "Thin story, not enough spread" in html

    def test_excluded_toggle_is_a_real_link(self, env):
        # the whole href is built as ONE Jinja expression (~-concatenated),
        # so autoescape converts EVERY '&' in it to '&amp;' consistently —
        # correct, spec-compliant HTML (a browser decodes &amp; in an
        # attribute value back to '&' before requesting the URL).
        html = disputes_page(env, show_excluded=False)
        assert "/divergence?view=disputes&amp;days=90&amp;excl=1" in html
        html2 = disputes_page(env, show_excluded=True)
        assert 'href="/divergence?view=disputes&amp;days=90"' in html2

    def test_the_why_function_distinguishes_not_yet_checked(self):
        """is_opinion is None (not False) is the ONLY signal that no
        cluster_disputes row exists at all — a LEFT JOIN can't produce a
        real False for a column that's NOT NULL DEFAULT false on the table
        unless a row was actually matched.

        Source-inspection + isolated exec (house style — see
        test_archive_batch11.py's docstring): routes.py drags in sqlalchemy
        engine creation and Flask app-context assumptions this test suite
        deliberately avoids importing.
        """
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def _dispute_why(")
        body = src[start:src.index("\ndef ", start + 1)]
        ns: dict = {"_DISPUTE_MIN_ARTICLES": 6}  # module-level constant _dispute_why reads
        exec(body, ns)  # noqa: S102 — trusted first-party source, test-only
        _dispute_why = ns["_dispute_why"]

        never_checked = {"article_count": 8, "lean_l_count": 3, "lean_r_count": 3,
                          "is_opinion": None, "disputed_point": None}
        assert _dispute_why(never_checked) == "not yet checked for a disputed point"
        checked_no_point = {"article_count": 8, "lean_l_count": 3, "lean_r_count": 3,
                             "is_opinion": False, "disputed_point": None}
        assert _dispute_why(checked_no_point) == "disagreement is on tone, not a checkable point"
        qualifies = {"article_count": 8, "lean_l_count": 3, "lean_r_count": 3,
                     "is_opinion": False, "disputed_point": "a real point"}
        assert _dispute_why(qualifies) is None


class TestDivergenceScoreAndSpectrum:
    def test_the_score_is_shown(self, env):
        html = disputes_page(env)
        assert "Divergence 62" in html

    def test_the_lean_split_is_stated_as_numbers(self, env):
        html = disputes_page(env)
        assert "L 3" in html and "C 1" in html and "R 5" in html


class TestDisputeSidesPanels:
    def test_both_sides_render_their_headlines(self, env):
        html = disputes_page(env)
        assert "Left headline" in html
        assert "Right headline" in html

    def test_a_side_with_no_articles_says_so(self, env):
        html = disputes_page(env)  # dispute 602 has empty left/right_articles
        assert "No outlet on this side" in html


class TestDisputeWindowFilterWorksWithoutJavaScript:
    def test_each_window_is_a_real_link(self, env):
        html = disputes_page(env, days=90)
        for w in DISPUTE_WINDOWS:
            assert f"days={w}" in html, f"{w}-day window is not a link"

    def test_the_route_validates_the_window(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "days not in _DISPUTE_WINDOWS" in body, (
            "the dispute window is not range-checked — ?days=999 reaches the query"
        )
        assert "days = 90" in body, "no fallback for an out-of-range dispute window"

    def test_a_non_numeric_window_does_not_500(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert body.count("except (TypeError, ValueError)") >= 2, (
            "both the view's days-parse blocks (language + disputes) need this guard"
        )


class TestDisputesHonestEmptyAndPaywall:
    def test_an_empty_window_says_so(self, env):
        html = disputes_page(env, rows=[])
        assert "No disputes in the last 90 days" in html

    def test_an_empty_excluded_view_says_so(self, env):
        html = disputes_page(env, rows=[], show_excluded=True)
        assert "No excluded stories in the last 90 days" in html

    def test_anonymous_gets_the_shared_paywall_but_still_sees_the_stories(self, env):
        html = disputes_page(env, subscriber=False)
        assert "wtf-a-pay" in html
        assert "splits reaction" in html, "the free story list must not be gated"

    def test_a_subscriber_gets_no_paywall(self, env):
        assert "wtf-a-pay" not in disputes_page(env, subscriber=True)


class TestDisputesNoPrivateStylingAndEscaping:
    def test_no_orbitron_and_no_literal_hex(self, env):
        html = disputes_page(env)
        assert "Orbitron" not in html
        hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b", html))
        assert not hexes, f"the disputes view hardcodes {sorted(hexes)}"

    def test_title_is_escaped(self, env):
        html = disputes_page(env)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)" not in html


class TestDisputesPageAndApiShareOneQuery:
    def test_the_api_calls_the_same_helper_as_the_page(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert src.count("def _dispute_rows(") == 1
        api_start = src.index("def api_v1_disputes():")
        next_bp = src.index("\n@bp.", api_start)
        next_def_idx = src.find("\ndef ", api_start)
        api_end = min(next_bp, next_def_idx) if next_def_idx != -1 else next_bp
        api_body = src[api_start:api_end]
        assert "_dispute_rows(" in api_body, "API no longer shares the helper"
        assert "LEFT JOIN" not in api_body, "API re-inlined its own SQL — it can drift"

    def test_divergence_score_is_pure_math_not_an_llm_field(self):
        """Confirms the score/point separation: divergence_score is computed
        in cluster_metrics.py, never asked of the LLM."""
        src = (ROOT / "ingest" / "cluster_metrics.py").read_text()
        assert "_divergence_score" in src


# ─────────────────────────── language (secondary) view ─────────────────────

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


def language_page(env, *, rows=DIVERGENCES, days=30, subscriber=False):
    return env.get_template("divergence.html").render(
        view="language", divergences=rows, days=days, windows=LANGUAGE_WINDOWS,
        is_subscriber=subscriber)


class TestLanguageViewStoriesRender:
    """Unchanged behavior — the whole defect this file originally guarded."""

    def test_every_story_appears(self, env):
        html = language_page(env)
        assert "splits coverage" in html
        assert "Pipeline debate framed differently" in html
        assert len(re.findall(r'<div class="wtf-dv-dv-card', html)) == len(DIVERGENCES)

    def test_a_story_without_a_title_does_not_vanish(self, env):
        html = language_page(env)
        assert "Untitled story" in html

    def test_the_page_needs_no_client_javascript(self, env):
        html = language_page(env)
        assert "<script" not in html.lower(), "server-rendered — no JS required"

    def test_no_js_file_targets_the_removed_mount_point(self):
        js_dir = ROOT / "consumer" / "static" / "js"
        if not js_dir.exists():
            pytest.skip("no static/js directory")
        hits = [p.name for p in js_dir.glob("*.js") if "div-list" in p.read_text(errors="ignore")]
        assert not hits, f"{hits} still target the removed mount point"


class TestLanguageViewWindowFilterWorksWithoutJavaScript:
    def test_each_window_is_a_real_link(self, env):
        html = language_page(env, days=30)
        for w in LANGUAGE_WINDOWS:
            assert f"/divergence?view=language&days={w}" in html, f"{w}-day window is not a link"

    def test_the_current_window_is_marked(self, env):
        html = language_page(env, days=60)
        assert "wtf-dv-active" in html

    def test_the_route_validates_the_window(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "days not in _DIVERGENCE_WINDOWS" in body, (
            "the language window is not range-checked — ?days=999 reaches the query"
        )
        assert "days = 30" in body, "no fallback for an out-of-range language window"


class TestLanguageViewDivergenceTypeIsReadable:
    """Colour alone is never the signal — every card carries a text badge."""

    def test_en_only_is_labelled(self, env):
        assert "EN ONLY" in language_page(env)

    def test_fr_only_is_labelled(self, env):
        assert "FR ONLY" in language_page(env)

    def test_bias_gap_is_labelled(self, env):
        assert "BIAS GAP" in language_page(env)

    def test_missing_scores_show_a_dash_not_a_fabricated_number(self, env):
        assert "—" in language_page(env)


class TestLanguageViewHonestEmptyAndPaywall:
    def test_an_empty_window_says_so_rather_than_rendering_nothing(self, env):
        html = language_page(env, rows=[])
        assert "No divergent stories in this window" in html

    def test_anonymous_gets_the_shared_paywall_but_still_sees_the_stories(self, env):
        html = language_page(env, subscriber=False)
        assert '<div class="wtf-dv-paywall-gate">' in html
        assert "splits coverage" in html, "the free story list must not be gated"

    def test_a_subscriber_gets_no_paywall(self, env):
        assert '<div class="wtf-dv-paywall-gate">' not in language_page(env, subscriber=True)


class TestLanguageViewNoPrivateStyling:
    def test_no_orbitron(self, env):
        assert "Orbitron" not in language_page(env)


class TestLanguageViewExternalTextIsEscaped:
    def test_title_is_escaped(self, env):
        html = language_page(env)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)" not in html


class TestLanguageViewPageAndApiShareOneQuery:
    def test_the_api_calls_the_same_helper_as_the_page(self):
        """A story shown to a reader and one returned to an API client must be
        the same set — so the SQL must live in exactly one place."""
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert src.count("def _divergence_rows(") == 1
        api_start = src.index("def api_v1_divergence():")
        next_bp = src.index("\n@bp.", api_start)
        next_def_idx = src.find("\ndef ", api_start)
        api_end = min(next_bp, next_def_idx) if next_def_idx != -1 else next_bp
        api_body = src[api_start:api_end]
        assert "_divergence_rows(" in api_body, "API no longer shares the helper"
        assert "cluster_lang AS" not in api_body, "API re-inlined its own SQL — it can drift"


# ─────────────────────────── view switch itself ─────────────────────────────

class TestViewSwitch:
    def test_default_view_is_disputes(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert 'view = _req.args.get("view", "disputes")' in body

    def test_an_invalid_view_falls_back_to_disputes(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def divergence_page():")
        body = src[start:src.index("\n@bp.", start)]
        assert "if view not in _DIVERGENCE_VIEWS" in body
        assert 'view = "disputes"' in body

    def test_both_tabs_are_real_links(self, env):
        html = disputes_page(env)
        assert "/divergence?view=disputes" in html
        assert "/divergence?view=language" in html
