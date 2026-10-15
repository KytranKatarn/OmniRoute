"""/team (2026-10-15): department cards use the directory portrait (or initials, never an emoji), and the 'unattributed' bucket is explained by tier."""

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape  # noqa: E402

from consumer import team_attribution as TA  # noqa: E402

TPL = ROOT / "consumer" / "templates"
# Pictographic emoji only. U+2665 (the heart in the welfare pill, "♥ 91/100 welfare") is the design's own typographic glyph and is deliberately allowed.
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u2664\u2666-\u27BF]")


class TestInitials:
    @pytest.mark.parametrize("name,exp", [("P.R.O.O.F.", "PR"), ("E.C.H.O.", "EC"), ("V.E.R.I.F.Y.-B", "VE"), ("V.E.T.", "VE"), ("", "?"), (None, "?"), ("...", "?")])
    def test_first_two_letters(self, name, exp):
        assert TA.initials(name) == exp


class TestBreakdown:
    def test_known_tiers_get_plain_english_labels_largest_first(self):
        out = TA.unattributed_breakdown({"quick_v1": 2972, "quick_v1+full": 78, "quick_v1_failed+full": 220, "": 1290})
        assert [o["events"] for o in out] == [2972, 1290, 220, 78]
        assert out[0]["label"] == "Tier-1 quick triage (small model)" and out[1]["label"] == TA.NO_TIER

    def test_unknown_and_empty_tiers_merge_into_no_tier_recorded(self):
        out = TA.unattributed_breakdown({"": 5, "weird_v9": 7})
        assert out == [{"label": TA.NO_TIER, "events": 12}]

    def test_zero_and_missing_input(self):
        assert TA.unattributed_breakdown({"quick_v1": 0}) == [] and TA.unattributed_breakdown(None) == []


@pytest.fixture(scope="module")
def env():
    return Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block title %}{% endblock %}{% block meta %}{% endblock %}<body>{% block content %}{% endblock %}</body>"}), FileSystemLoader(str(TPL))]),
                       autoescape=select_autoescape(["html"]))


NAMED = {"name": "F.A.C.T.", "full": "x", "role": "Director", "model": "gemma3:12b", "description": "d", "coming_soon": False, "portrait_url": None,
         "accent_colour": "#dc2626", "welfare": {"welfare_score": 91, "shift_state": "active"}, "status_label": "Active", "status_is_active": True, "initials": "FA"}


def _dept(name, url, shift="active"):
    return {"name": name, "shift_state": shift, "events_24h": 5, "work_label": "5 fact-checks · 24h", "portrait_url": url, "initials": TA.initials(name)}


def _render(env, **kw):
    ctx = dict(agents=[NAMED], source_count=46, dept_agents=[], roster_rows=[], dept_total=22, named_count=8, unattributed_tiers=[])
    ctx.update(kw)
    return env.get_template("team.html").render(**ctx)


class TestCards:
    def test_a_dept_agent_with_a_directory_portrait_shows_it(self, env):
        h = _render(env, dept_agents=[_dept("P.R.O.O.F.", "https://kytranempowerment.com/assets/portraits/p.jpg")])
        assert "background-image: url('https://kytranempowerment.com/assets/portraits/p.jpg')" in h and "Portrait of P.R.O.O.F." in h
        assert "No portrait is published" not in h

    def test_a_dept_agent_without_one_shows_initials_and_an_accurate_note(self, env):
        h = _render(env, dept_agents=[_dept("C.O.N.D.U.I.T.", None)])
        assert 'wtf-team-initials" aria-hidden="true">CO<' in h and "No portrait is published for this agent yet." in h

    def test_the_old_false_claim_and_emoji_are_gone(self, env):
        h = _render(env, dept_agents=[_dept("P.R.O.O.F.", None), _dept("E.C.H.O.", "https://x/y.jpg")])
        assert "from the directory when published" not in h and not EMOJI.findall(h)

    def test_a_named_agent_without_a_portrait_gets_initials_not_an_emoji(self, env):
        h = _render(env)
        assert ">FA<" in h and not EMOJI.findall(h)

    def test_template_source_has_no_emoji(self):
        assert not EMOJI.findall((TPL / "team.html").read_text(encoding="utf-8"))


class TestAttributionExplained:
    ONLY_UNATTR = [{"label": "unattributed", "value": 5941}]

    def test_only_unattributed_says_so_and_explains_by_tier(self, env):
        h = _render(env, roster_rows=self.ONLY_UNATTR, unattributed_tiers=[{"label": "Tier-1 quick triage (small model)", "events": 2972}, {"label": TA.NO_TIER, "events": 1290}])
        assert "No named agent was recorded for any work in this window." in h
        assert "Tier-1 quick triage (small model) 2972" in h and "no tier recorded 1290" in h and "Fact-checks carry no tier record." in h

    def test_named_rows_present_means_no_none_recorded_message(self, env):
        h = _render(env, roster_rows=[{"label": "V.E.R.I.F.Y.", "value": 39}, {"label": "unattributed", "value": 100}])
        assert "No named agent was recorded" not in h

    def test_no_breakdown_no_extra_line(self, env):
        assert "by how they were produced" not in _render(env, roster_rows=self.ONLY_UNATTR)

    def test_route_passes_the_breakdown_and_portraits(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert "unattributed_tiers=_team_attribution.unattributed_breakdown(" in src and '"portrait_url": portrait_lookup.get(name)' in src
