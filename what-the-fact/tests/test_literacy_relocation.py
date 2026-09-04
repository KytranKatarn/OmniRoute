"""/literacy relocation (#6272, Batch 9) — owner decision.

The design handoff wants a PUBLIC, no-login tips page at /literacy. The
route that already lived there was a subscriber-gated personal "Media
Literacy Score" dashboard, which cannot coexist with the design's page at
the same URL. Owner decision (asked explicitly, not inferred): the personal
dashboard moves to /literacy/score; the design's public page takes /literacy.

Two halves to verify:
  1. Jinja-only render tests for both templates' CONTENT (no Flask needed —
     mirrors every other page in this rollout, e.g. test_governance_scale_
     participate.py, test_creed_page.py).
  2. A live Flask test client (same fixture pattern as test_nav_shell.py)
     for the ROUTING/GATING behavior itself: /literacy must return 200 with
     no redirect for an anonymous visitor; /literacy/score must still
     redirect anonymous visitors to /login, exactly as /literacy used to.
"""

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from consumer.app import create_app

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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("WTF_BILLING_DB_PATH", str(tmp_path / "b.db"))
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _body(html):
    return html.split("</style>", 1)[1]


class TestPublicLiteracyPageContent:
    def test_all_five_tips_present(self, env):
        html = env.get_template("literacy.html").render(source_count=46, is_subscriber=False)
        b = _body(html)
        for heading in (
            "1. Read the cluster, not the article",
            "2. Check who is quoted directly",
            "3. Separate the fact from the frame",
            "4. Notice the absence",
            "5. Distrust a single number",
        ):
            assert heading in b, f"missing tip: {heading}"

    def test_sidebar_caveats_present(self, env):
        html = env.get_template("literacy.html").render(source_count=46, is_subscriber=False)
        b = _body(html)
        assert "Where this site can mislead you" in b
        assert "flattens a lot" in b
        assert "not how important a story is" in b

    def test_source_count_is_dynamic_not_hardcoded(self, env):
        """The design's own copy says '40 sources' as a fixed number — this
        must track the live count instead."""
        html_a = env.get_template("literacy.html").render(source_count=46, is_subscriber=False)
        html_b = env.get_template("literacy.html").render(source_count=12, is_subscriber=False)
        assert "46 sources" in _body(html_a)
        assert "12 sources" in _body(html_b)
        assert "46 sources" not in _body(html_b)

    def test_no_login_or_subscribe_gate_markup(self, env):
        html = env.get_template("literacy.html").render(source_count=46, is_subscriber=False)
        b = _body(html).lower()
        assert "login" not in b
        assert "subscribe" not in b
        assert "connect?gated" not in b

    def test_blindspot_link_present(self, env):
        html = env.get_template("literacy.html").render(source_count=46, is_subscriber=False)
        assert 'href="/blindspot"' in _body(html)


class TestRelocatedScoreDashboardContentUnchanged:
    """Content-preservation check: the move is a URL/filename change only."""

    def test_score_and_distribution_still_render(self, env):
        html = env.get_template("literacy_score.html").render(
            user_email="test@example.com", score=72, total_scored=10, total_views=15,
            distribution={"left": 2, "center-left": 3, "center": 5, "center-right": 0,
                          "right": 0, "unscored": 0},
            recent=[],
        )
        assert "72" in html
        assert "Media Literacy Score" in html


class TestRoutingAndGating:
    def test_literacy_is_public_no_redirect(self, client):
        r = client.get("/literacy", follow_redirects=False)
        assert r.status_code == 200, r.status_code
        assert "Media literacy" in r.get_data(as_text=True)

    def test_literacy_score_redirects_anonymous_to_login(self, client):
        r = client.get("/literacy/score", follow_redirects=False)
        assert r.status_code in (301, 302), r.status_code
        assert r.headers["Location"].startswith("/login")
        assert "next=%2Fliteracy%2Fscore" in r.headers["Location"] or "next=/literacy/score" in r.headers["Location"]

    def test_bare_literacy_does_not_redirect_like_the_old_gated_route_did(self, client):
        """Regression guard for the relocation itself: before this change,
        GET /literacy redirected anonymous visitors to /login. It must not
        anymore — that behavior belongs to /literacy/score now."""
        r = client.get("/literacy", follow_redirects=False)
        assert r.status_code == 200
        assert "Location" not in r.headers


class TestLinksUpdatedToNewPath:
    def test_account_page_links_to_score_not_literacy(self):
        html = (TPL / "account.html").read_text(encoding="utf-8")
        assert 'href="/literacy/score"' in html
        assert 'href="/literacy"' not in html

    def test_article_page_links_to_score_not_literacy(self):
        html = (TPL / "article.html").read_text(encoding="utf-8")
        assert 'href="/literacy/score"' in html
        assert 'href="/literacy"' not in html

    def test_robots_txt_disallows_the_score_dashboard_not_the_public_page(self):
        src = ROUTES.read_text(encoding="utf-8")
        assert "Disallow: /literacy/score" in src
        assert "Disallow: /literacy\\n" not in src


class TestNavPlacement:
    def test_literacy_is_in_the_unconditional_about_group(self):
        """/literacy must be reachable in the nav for a signed-out visitor —
        it moved out of the `if session.get('wtf_authenticated')` block."""
        html = (TPL / "base.html").read_text(encoding="utf-8")
        about_start = html.index("_about = [")
        about_end = html.index("]", about_start)
        about_body = html[about_start:about_end]
        assert "'/literacy'" in about_body, "/literacy must be in the base _about list, not the gated append"
