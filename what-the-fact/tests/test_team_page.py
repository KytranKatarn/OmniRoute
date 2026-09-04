"""team.html's "rest of the department" + "who actually did the work" sections
(#6272, Batch 8 of the WTF Claude Design handoff rollout).

design-handoff/wtf-team.html specifies three sections: the 8 named agents
(#tm-grid, already live), the rest of the News & Media department hired by
K.I.N. (#tm-dept), and a fact-check/bias-score attribution ranking (#tm-roster).
The latter two read from data that already existed for OTHER pages —
_get_welfare_lookup() (the full live News & Media roster, not just the 8
named agents) and _newsroom_agents() (24h fact-check/bias attribution, built
for the Activity Log) — and were simply never wired into /team.

Mutation-checked against a reverted copy of team.html: removing the two new
{% if %} blocks makes every new-content assertion below fail.
"""

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, select_autoescape, FileSystemLoader

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


NAMED_AGENT = {
    "name": "F.A.C.T.", "full": "Factual Analysis, Credibility & Transparency",
    "role": "Director & Orchestrator", "model": "gemma3:12b", "description": "desc",
    "coming_soon": False, "portrait_url": None, "accent_colour": "#dc2626",
    "welfare": {"welfare_score": 91, "shift_state": "active"},
}

DEPT_AGENTS = [
    {"name": "P.R.O.O.F.", "shift_state": "active", "events_24h": 612},
    {"name": "S.T.R.I.N.G.E.R.", "shift_state": "barracked", "events_24h": 0},
]

ROSTER_ROWS = [
    {"label": "V.E.R.I.F.Y.", "value": 747},
    {"label": "P.R.O.O.F.", "value": 612},
    {"label": "unattributed", "value": 161},
]


def _render(env, **overrides):
    kwargs = dict(
        agents=[NAMED_AGENT], source_count=46,
        dept_agents=DEPT_AGENTS, roster_rows=ROSTER_ROWS,
        dept_total=22, named_count=8,
    )
    kwargs.update(overrides)
    return env.get_template("team.html").render(**kwargs)


class TestTheDepartmentRosterRenders:
    def test_a_non_named_agent_appears(self, env):
        html = _render(env)
        assert "P.R.O.O.F." in html

    def test_shift_state_is_shown_as_free_text_not_a_binary(self, env):
        # barracked must render distinctly from active — not collapsed to a
        # generic "Active" badge the way department-hq's sc-live/sc-static
        # bug once did on a different page.
        html = _render(env)
        assert "barracked" in html
        assert "active" in html

    def test_a_zero_task_agent_says_zero_not_blank(self, env):
        # STRINGER did no fact-checks/bias in the window — must read "0", not
        # a silently-omitted count that reads as missing data.
        html = _render(env)
        assert "0 fact-check" in html

    def test_no_title_is_invented_for_a_dept_agent(self, env):
        # The hub's fleet-agents payload carries no per-agent "title" field
        # (verified live against /tools/department-hq/api/creed/fleet-agents).
        # A fabricated one (e.g. "Fact-check specialist" as a per-card role
        # label) would violate the design's own "nothing here is invented to
        # fill a gap" rule. The body copy is allowed to describe the hiring
        # pattern generically ("K.I.N. hired specialists...") — what must
        # NOT appear is that phrase attached to a specific agent's card.
        html = _render(env)
        assert "Fact-check specialist" not in html
        assert '<div class="wtf-team-role">Fact-check' not in html

    def test_the_reconciling_count_line_does_the_arithmetic(self, env):
        html = _render(env).replace("\n", " ")
        assert "8 named + 2 listed here = 10" in html
        assert "of the 22 agents" in html


class TestTheAttributionRosterRenders:
    def test_uses_the_shared_ranked_bars_archetype(self, env):
        # Not a bespoke bar chart — the same macro divergence.html/blindspot
        # already use, so a future styling fix lands everywhere at once.
        html = _render(env)
        assert "wtf-a-ranked" in html
        assert "wtf-a-bar-fill" in html

    def test_unattributed_is_a_labelled_row_not_folded_into_a_name(self, env):
        html = _render(env)
        assert "unattributed" in html
        # it must NOT be silently merged into the top-ranked real agent's bar
        assert "747" in html and "161" in html

    def test_the_top_bar_is_the_full_width_reference(self, env):
        html = _render(env)
        assert "width: 100.0%" in html


class TestHonestEmptyState:
    """_get_welfare_lookup() fails OPEN (empty dict) when the hub is
    unreachable — /team must still render, just without these two sections,
    never with a fabricated roster or a 500."""

    def test_both_new_sections_disappear_together(self, env):
        html = _render(env, dept_agents=[], roster_rows=[], dept_total=0)
        assert "the rest of the department" not in html.lower()
        assert "who actually did the work" not in html.lower()
        assert "wtf-a-ranked" not in html

    def test_the_named_grid_still_renders_when_the_hub_is_down(self, env):
        html = _render(env, dept_agents=[], roster_rows=[], dept_total=0)
        assert "F.A.C.T." in html


class TestTeamRouteWiring:
    """Template-only tests above can't catch the ROUTE failing to compute
    dept_agents/roster_rows — the mock data above always supplies them. This
    mirrors TestOwnersRouteWiring's source-grep approach (this repo's test
    suite runs without a live DB)."""

    def test_team_route_builds_dept_agents_and_roster_rows(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index('@bp.get("/team")')
        end = src.index("\n@bp.get", start + 1)
        body = src[start:end]
        assert "_newsroom_agents(" in body, (
            "team() must call _newsroom_agents() to build the 24h attribution "
            "data for both new sections"
        )
        assert "dept_agents" in body and "roster_rows" in body, (
            "team() must pass dept_agents and roster_rows to render_template — "
            "without them the new sections silently never appear"
        )

    def test_dept_agents_excludes_the_eight_named_agents(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index('@bp.get("/team")')
        end = src.index("\n@bp.get", start + 1)
        body = src[start:end]
        assert "named_names" in body and "if name in named_names" in body, (
            "a named agent (e.g. F.A.C.T.) must not also appear in the "
            "rest-of-department grid as a duplicate card"
        )
