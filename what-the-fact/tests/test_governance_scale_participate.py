"""/governance — "The scale the badge uses" + "How this newsroom participates"
(#6272, Batch 8).

design-handoff/wtf-governance.html has 6 sections; the live page had 3 before
this change (scorecard, Pillars, unavailable-state). Two of the four missing
sections are STATIC, factual content that matches this repo's own docs
verbatim (badge thresholds, rule-pack count) — those are ported here. The
other two ("Why the grade is failing" and "Recent governance events") are
built in the design file from an explicitly-fabricated `SCAN`/`EVENTS`
JS fallback, not from anything `_fetch_creed_scan()` actually returns, and
are deliberately NOT ported — same discipline as weather_city.html dropping
its hourly/AQI/sun-moon sections.
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


def _scan(overall, by_category=None):
    return {
        "overall": overall,
        "grade": "B+",
        "event_count": 4531,
        "by_category": by_category or {
            "transparency": {"score": 96, "events": 900, "provisional": False, "note": None}
        },
        "overall_categories": ["transparency"],
        "freshness": {"events_30d": 812},
        "ok": True,
    }


def _render(env, scan, **overrides):
    kwargs = dict(scan=scan, source_count=46, is_subscriber=False)
    kwargs.update(overrides)
    return env.get_template("governance.html").render(**kwargs)


def _body(html):
    """Content after the page's own <style> block — excludes the explanatory
    CSS comment, which itself names the two dropped sections and would
    otherwise false-positive a naive substring search for their absence."""
    return html.split("</style>", 1)[1]


BAND_CASES = [
    (100, "is-green"), (90, "is-green"), (95, "is-green"),
    (89, "is-blue"), (80, "is-blue"), (85, "is-blue"),
    (79, "is-yellow"), (70, "is-yellow"), (72, "is-yellow"),
    (69, "is-red"), (0, "is-red"), (40, "is-red"),
]


class TestBadgeScaleSection:
    @pytest.mark.parametrize("overall,expect_band", BAND_CASES)
    def test_exactly_one_band_is_marked_current(self, env, overall, expect_band):
        html = _render(env, _scan(overall))
        hits = re.findall(r'class="wtf-gv-scale-pill (\S+) is-current"', html)
        assert hits == [expect_band], f"overall={overall}: got {hits}, want [{expect_band}]"

    def test_four_bands_always_render(self, env):
        html = _render(env, _scan(95))
        b = _body(html)
        for name in ("Green", "Blue", "Yellow", "Red"):
            assert name in b

    def test_thresholds_match_this_repos_own_documented_values(self, env):
        # .claude/rules/security-network.md + compliance-standards.md:
        # Green 90%+, Blue 80%+, Yellow 70%+, Red <60% — 5 rule packs, 178 rules.
        html = _render(env, _scan(95))
        b = _body(html)
        assert "178 compliance" in b
        assert "five rule packs" in b
        assert "every six hours" in b


class TestParticipationSection:
    def test_all_four_participation_cards_render(self, env):
        html = _render(env, _scan(95))
        b = _body(html)
        for heading in (
            "Every action emits an event",
            "Every agent publishes a model card",
            "Method is disclosed, not just results",
            "The grade is theirs, and it is public",
        ):
            assert heading in b, f"missing participation card: {heading}"

    def test_named_agents_match_the_methodology_page(self, env):
        # Consistency check against the agent roster already shipped on
        # /methodology (test_methodology_page.py) — not a fresh claim.
        html = _render(env, _scan(95))
        b = _body(html)
        assert "B.I.A.S." in b
        assert "V.E.R.I.F.Y." in b
        assert "D.R.A.F.T." in b

    def test_participation_links_present(self, env):
        html = _render(env, _scan(95))
        b = _body(html)
        assert 'href="/creed"' in b
        assert 'href="https://creed-ai.org"' in b
        assert 'href="/activity"' in b


class TestNoFabricatedSections:
    """The two sections this change deliberately does NOT build."""

    @pytest.mark.parametrize("overall", [0, 40, 72, 95, 100])
    def test_why_grade_is_failing_never_renders(self, env, overall):
        b = _body(_render(env, _scan(overall)))
        assert "Why the grade is failing" not in b

    @pytest.mark.parametrize("overall", [0, 40, 72, 95, 100])
    def test_recent_governance_events_never_renders(self, env, overall):
        b = _body(_render(env, _scan(overall)))
        assert "Recent governance events" not in b


class TestUnavailableStateUnaffected:
    def test_new_sections_do_not_render_with_no_scan(self, env):
        html = _render(env, None)
        b = _body(html)
        assert "temporarily unavailable" in b
        assert "The scale the badge uses" not in b
        assert "How this newsroom participates" not in b

    def test_no_current_band_marker_with_no_scan(self, env):
        # Scope to the body: the CSS class is always defined in <style>
        # regardless of `scan`; only the <span> markup is conditional.
        html = _render(env, None)
        assert '<span class="wtf-gv-scale-pill' not in _body(html)


class TestExistingSectionsUnaffected:
    """Regression guard: the scorecard, Pillars grid and footnote (all
    pre-existing) must survive the insertion untouched."""

    def test_scorecard_and_pillars_still_render(self, env):
        html = _render(env, _scan(87, by_category={
            "transparency": {"score": 96, "events": 900, "provisional": False, "note": None},
            "fairness": {"score": 58, "events": 12, "provisional": True, "note": None},
        }))
        b = _body(html)
        assert "87" in b
        assert "Pillars" in b
        assert "provisional" in b
        assert "Meet the team on" in b  # footnote survives


class TestGovernanceRouteWiring:
    """Mirrors TestMethodologyRouteWiring's source-grep approach — this
    change touched the template only, so confirm routes.py was NOT edited
    and still passes exactly {scan, source_count, is_subscriber}."""

    def test_route_still_passes_the_same_three_kwargs(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def governance_page(")
        end = src.index("\n\n", start)
        body = src[start:end]
        assert 'scan=scan' in body
        assert 'source_count=source_count' in body
        assert 'is_subscriber=is_subscriber()' in body
