"""/methodology — ported from tech/templates/methodology.html (#6272, Batch 8).

Unlike most items in this rollout, this page's `_COMING_SOON` stub was
pointing at REAL, already-written content: tech/routes.py's methodology()
view (served there at /transparency, matching what-the-fact.tech/transparency)
renders a complete, accurate page — prompt excerpts, bias-band thresholds,
known limitations with live C.R.E.E.D. remediation-registry links, honest
RSS-coverage-gap reporting. This is a content port, not a rewrite: the
consumer route mirrors the tech route's stats query exactly.
"""

import pathlib

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


FULL_STATS = {"total_articles": 1284, "ai_analyzed": 340, "geolocated": 1050, "total_sources": 46}


def _render(env, stats, **overrides):
    kwargs = dict(stats=stats, is_subscriber=False)
    kwargs.update(overrides)
    return env.get_template("methodology.html").render(**kwargs)


class TestLiveStatsRender:
    def test_all_four_stat_numbers_appear(self, env):
        html = _render(env, FULL_STATS)
        assert "1284" in html
        assert "340" in html
        assert "1050" in html
        assert ">46<" in html or "46 active" in html

    def test_empty_stats_does_not_crash_and_falls_back_honestly(self, env):
        # The route always returns a row from a COUNT(*) aggregate, but the
        # template must survive a genuinely empty dict too (e.g. a query
        # change that drops a column) rather than raising in production.
        html = _render(env, {})
        assert "RADICAL TRANSPARENCY" in html
        assert "46 active Canadian sources" in html  # documented fallback default


class TestRealContentPresent:
    """This is a content port — assert the substance made it across, not
    just that the page renders."""

    def test_all_five_named_agents_appear(self, env):
        html = _render(env, FULL_STATS)
        for agent in ("F.A.C.T.", "B.I.A.S.", "V.E.R.I.F.Y.", "L.O.C.A.L.", "I.N.K.", "D.R.A.F.T."):
            assert agent in html, f"missing agent model card: {agent}"

    def test_all_five_bias_bands_appear_with_thresholds(self, env):
        html = _render(env, FULL_STATS)
        for band in ("LEFT", "CENTER-LEFT", "CENTER", "CENTER-RIGHT", "RIGHT"):
            assert band in html

    def test_fact_check_verdict_vocabulary_is_complete(self, env):
        html = _render(env, FULL_STATS)
        for verdict in ("verified", "mixed", "disputed", "unverifiable", "descriptive_reporting"):
            assert verdict in html

    def test_known_limitations_link_to_the_remediation_registry(self, env):
        html = _render(env, FULL_STATS)
        assert html.count("creed.kytranempowerment.com/remediation#") == 7

    def test_coverage_gap_outlets_are_named_honestly(self, env):
        html = _render(env, FULL_STATS)
        assert "La Presse" in html
        assert "Toronto Star" in html
        assert "RSS discontinued" in html or "non-functional" in html
        # CTV is the one restored/active outlet — must read differently from
        # the two still-broken ones, not be lumped in as another gap.
        assert "Restored and active" in html

    def test_live_scorer_and_flag_links_present(self, env):
        html = _render(env, FULL_STATS)
        assert 'href="/score"' in html
        assert "/api/v1/flag" in html


class TestMethodologyRouteWiring:
    """Mirrors TestOwnersRouteWiring's source-grep approach."""

    def test_methodology_route_exists_and_is_not_a_coming_soon_stub(self):
        src = ROUTES.read_text(encoding="utf-8")
        assert '@bp.get("/methodology")' in src, (
            "a real /methodology route must exist"
        )
        # The graduation rule this repo enforces elsewhere (platforms, races):
        # a page that exists must not also be advertised as unbuilt.
        coming_soon_start = src.index("_COMING_SOON = {")
        coming_soon_end = src.index("\n}\n", coming_soon_start)
        coming_soon_body = src[coming_soon_start:coming_soon_end]
        assert '"methodology": (' not in coming_soon_body, (
            "methodology graduated to a real page — its _COMING_SOON stub "
            "must be deleted, not left alongside the real route"
        )

    def test_methodology_route_queries_real_stats_not_hardcoded_numbers(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def methodology(")
        end = src.index("\n\n\n", start)
        body = src[start:end]
        assert "total_articles" in body
        assert "ai_analyzed" in body
        assert "geolocated" in body
        assert "total_sources" in body
