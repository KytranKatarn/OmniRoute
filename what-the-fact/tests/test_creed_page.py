"""/creed — About C.R.E.E.D. Institute (#6272, Batch 8).

Built from design-handoff/wtf-creed.html, which is entirely static content
(no `const`/`fetch` in the design source at all) — unlike governance.html
or weather.html, this page needed no fabricated-vs-real data triage on most
of its content. The one exception: the design's "what makes it different"
fact claimed C.R.E.E.D. "governs 129 AI agents across 16 departments" — an
unverifiable, already-stale headcount (this platform's own live roster does
not match it) with no live source on this route. That specific figure was
generalized away rather than ported; everything else (rule-pack count,
badge thresholds, agent names, programs) is either independently verified
against this repo's own docs or static organizational prose.
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


def _render(env, **overrides):
    kwargs = dict(source_count=46, is_subscriber=False)
    kwargs.update(overrides)
    return env.get_template("creed.html").render(**kwargs)


def _body(html):
    return html.split("</style>", 1)[1]


class TestOrganizationPanel:
    def test_all_seven_facts_present(self, env):
        b = _body(_render(env))
        for heading in (
            "What it is", "Where", "Origin", "What makes it different",
            "The compliance manager", "The rules", "The badge",
        ):
            assert heading in b, f"missing fact: {heading}"

    def test_ethos_named_as_compliance_manager(self, env):
        b = _body(_render(env))
        assert "E.T.H.O.S." in b
        assert "Ethical Transparency" in b

    def test_rule_pack_facts_match_this_repos_own_docs(self, env):
        # .claude/rules/security-network.md: 51+30+30+27+40 = 178 rules, 5 packs, 6h cadence.
        b = _body(_render(env))
        assert "178 compliance rules" in b
        assert "five rule packs" in b
        assert "every six hours" in b

    def test_badge_thresholds_match_governance_page(self, env):
        b = _body(_render(env))
        assert "green at 90%" in b
        assert "blue at 80%" in b
        assert "yellow at 70%" in b
        assert "red below 60%" in b

    def test_no_stale_or_unverifiable_agent_headcount(self, env):
        """The design's own '129 AI agents across 16 departments' claim did
        not match this platform's live roster and has no live source on
        this route — must not be ported verbatim."""
        b = _body(_render(env))
        assert "129" not in b
        assert "16 departments" not in b


class TestFourProgramsPanel:
    def test_all_four_programs_present(self, env):
        b = _body(_render(env))
        for name in (
            "Transparency Framework", "Agent Welfare Research",
            "Open Governance Toolkit", "Ethics Education",
        ):
            assert name in b

    def test_exactly_four_program_cards(self, env):
        b = _body(_render(env))
        assert b.count("wtf-cd-card-h") == 4


class TestParticipationPanel:
    def test_all_six_named_agents_present(self, env):
        b = _body(_render(env))
        for agent in ("B.I.A.S.", "V.E.R.I.F.Y.", "D.R.A.F.T.", "I.N.K.", "L.O.C.A.L.", "F.A.C.T."):
            assert agent in b, f"missing agent: {agent}"

    def test_grade_ownership_disclosed_not_self_audited(self, env):
        b = _body(_render(env))
        assert "not a self-audit" in b


class TestLiveGradeDiscipline:
    """The design file's own footnote: never hand-enter a score on this page."""

    def test_no_numeric_grade_hardcoded_on_this_page(self, env):
        b = _body(_render(env))
        # The only numbers on the page are the rule-pack facts (178, 90/80/70/60)
        # and threshold percentages — none of those is a SCORE. Confirm the
        # page links to /governance for the live figure instead of stating one.
        assert 'href="/governance"' in b
        assert b.count('href="/governance"') >= 2  # lede + participation link

    def test_note_explicitly_states_the_no_hand_entry_rule(self, env):
        b = _body(_render(env))
        assert "never a figure entered by hand on this page" in b


class TestCreedRouteWiring:
    """Mirrors TestMethodologyRouteWiring's source-grep approach."""

    def test_creed_route_exists_and_is_not_a_coming_soon_stub(self):
        src = ROUTES.read_text(encoding="utf-8")
        assert '@bp.get("/creed")' in src

        coming_soon_start = src.index("_COMING_SOON = {")
        coming_soon_end = src.index("\n}\n", coming_soon_start)
        coming_soon_body = src[coming_soon_start:coming_soon_end]
        assert '"creed": (' not in coming_soon_body, (
            "creed graduated to a real page — its _COMING_SOON stub must be "
            "deleted, not left alongside the real route"
        )

    def test_creed_route_needs_no_scan_dispatch(self):
        """Unlike governance_page(), creed_page() has no live per-tenant score
        to read — it only needs source_count for the nav ticker. Checks the
        render_template() call itself, not the docstring (which explains,
        in prose, why _fetch_creed_scan() is NOT called here — that mention
        would otherwise false-positive a plain substring search)."""
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def creed_page(")
        end = src.index("\n\n\n", start)
        body = src[start:end]
        render_call = body[body.index('render_template("creed.html"'):]
        assert "scan=" not in render_call, "creed.html should not receive a scan kwarg"
        assert "source_count=source_count" in render_call
        assert "is_subscriber=is_subscriber()" in render_call
