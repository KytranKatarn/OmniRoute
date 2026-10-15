"""/methodology transparency, evidence and live-page wiring.

The page uses an illustrative bias-band key, a caveated process walkthrough,
and links to the live roster and governance pages. It must not invent outlet
positions, fixed model assignments, or a fallback governance grade.
"""

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"

_STUB = (
    "{% block title %}{% endblock %}{% block meta %}{% endblock %}"
    "<body>{% block content %}{% endblock %}</body>"
)


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


FULL_STATS = {
    "total_articles": 1284,
    "ai_analyzed": 340,
    "geolocated": 1050,
    "total_sources": 46,
}


def _render(env, stats, **overrides):
    kwargs = dict(stats=stats, is_subscriber=False)
    kwargs.update(overrides)
    return env.get_template("methodology.html").render(**kwargs)


class TestLiveStatsRender:
    def test_dynamic_stat_values_render(self, env):
        html = _render(env, FULL_STATS)
        for value in ("1284", "340", "1050", "46"):
            assert value in html

    def test_missing_stats_render_as_unknown(self, env):
        html = _render(env, {})
        assert html.count("—") >= 4
        assert "RADICAL TRANSPARENCY" in html
        assert "46 active Canadian sources" not in html


class TestProcessAndTransparency:
    def test_process_steps_are_named_and_coverage_is_caveated(self, env):
        html = _render(env, FULL_STATS)
        for stage in ("Collect and prepare", "Group related coverage", "Select deeper analysis",
                      "Summarize and record", "Publish what is available"):
            assert stage in html
        for role in ("F.A.C.T.", "B.I.A.S.", "V.E.R.I.F.Y.", "L.O.C.A.L."):
            assert role in html
        assert "not a guaranteed, one-agent-after-another workflow" in html
        assert "title-token Jaccard similarity" in html
        assert "does not call a separate I.N.K. agent" in html
        assert "backlog workers" in html
        assert "missing signal" in html

    def test_scale_is_explanatory_and_does_not_place_named_outlets(self, env):
        html = _render(env, FULL_STATS)
        for band in ("LEFT", "CENTER-LEFT", "CENTER", "CENTER-RIGHT", "RIGHT"):
            assert band in html
        for threshold in ("−0.6", "−0.2", "0.2", "0.6"):
            assert threshold in html
        assert 'href="/sources"' in html
        assert "not a live ranking" in html
        assert "CBC" not in html
        assert "National Post" not in html
        assert "WTF verified center" not in html

    def test_live_roster_is_the_source_for_current_agent_details(self, env):
        html = _render(env, FULL_STATS)
        assert 'href="/team"' in html
        assert "current named roles, model labels, status" in html
        for stale_model in ("gemma3:12b", "qwen2.5:7b", "gemma2:9b",
                            "llama3.2:3b", "dolphin3:latest"):
            assert stale_model not in html


class TestHonestMethodology:
    def test_verdict_vocabulary_and_limits_remain_visible(self, env):
        html = _render(env, FULL_STATS)
        for verdict in ("verified", "mixed", "disputed", "unverifiable",
                        "descriptive_reporting"):
            assert verdict in html
        assert html.count("creed.kytranempowerment.com/remediation#") == 7
        assert "missing score is not a neutral or verified result" in html

    def test_governance_preview_uses_live_badge_without_fake_score(self, env):
        html = _render(env, FULL_STATS)
        assert 'src="/api/creed-badge"' in html
        assert 'href="/governance"' in html
        assert 'href="/creed"' in html
        assert "99.5" not in html
        assert "A+" not in html
        assert "api/public/score" not in html

    def test_flags_do_not_promise_automatic_review_or_score_changes(self, env):
        html = _render(env, FULL_STATS)
        assert 'href="/score"' in html
        assert "/api/v1/flag" in html
        assert "does not itself change a score" in html
        assert "All flags are reviewed" not in html


class TestMethodologyRouteWiring:
    def test_methodology_is_a_real_route(self):
        src = ROUTES.read_text(encoding="utf-8")
        assert '@bp.get("/methodology")' in src
        start = src.index("_COMING_SOON = {")
        end = src.index("\n}\n", start)
        assert '"methodology": (' not in src[start:end]

    def test_route_queries_the_stats_displayed_by_the_page(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def methodology(")
        end = src.index("\n\n\n", start)
        body = src[start:end]
        for field in ("total_articles", "ai_analyzed", "geolocated", "total_sources"):
            assert field in body
