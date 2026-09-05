"""Regression coverage for the final 6 hand-curated /team weak-spot lines
(2026-09-05, follow-up to PRs #3209/#3210).

Kytran chose "draft candidates, you edit/approve" for the 6 agents with no
derivable real signal (F.A.C.T., B.I.A.S., L.O.C.A.L., I.N.K., D.R.A.F.T.,
P.U.B.L.I.S.H.) — Claude drafted speculative lines grounded in each agent's
real documented job description (never a fabricated statistic), presented
them in chat for review, and Kytran approved them as-is ("good"). These
tests pin the approved text landing on the right agent and confirm the two
computed agents (A.U.R.O.R.A., V.E.R.I.F.Y.) still correctly carry NO
static key — a regression here would mean a static string got hardcoded
over what should stay a live-computed line.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consumer import routes as R  # noqa: E402

_EXPECTED = {
    "F.A.C.T.": "Coordinates coverage decisions across the team",
    "B.I.A.S.": "Scores each article independently",
    "L.O.C.A.L.": "Maps each story to a single province",
    "I.N.K.": "Threads stories together by similarity",
    "D.R.A.F.T.": "Summarizes what's already reported",
    "P.U.B.L.I.S.H.": "Reports what it publishes, not how it performs",
}


def _by_name():
    return {a["name"]: a for a in R.TEAM_AGENTS}


def test_all_eight_named_agents_present():
    names = {a["name"] for a in R.TEAM_AGENTS}
    assert names == {
        "F.A.C.T.", "B.I.A.S.", "V.E.R.I.F.Y.", "L.O.C.A.L.",
        "I.N.K.", "D.R.A.F.T.", "P.U.B.L.I.S.H.", "A.U.R.O.R.A.",
    }


def test_each_approved_line_lands_on_the_right_agent():
    agents = _by_name()
    for name, expected_start in _EXPECTED.items():
        assert "weak_spot" in agents[name], f"{name} is missing its approved weak_spot"
        assert agents[name]["weak_spot"].startswith(expected_start), name


def test_computed_agents_still_have_no_static_key():
    # A.U.R.O.R.A. and V.E.R.I.F.Y. must keep getting their line from real
    # data (see _aurora_team_weak_spot / _verify_team_weak_spot in team()),
    # never a hand-typed string that could drift from the real number.
    agents = _by_name()
    assert "weak_spot" not in agents["A.U.R.O.R.A."]
    assert "weak_spot" not in agents["V.E.R.I.F.Y."]


def test_no_line_contains_an_invented_number():
    # These 6 are speculation about mechanism, not measurement — none of
    # them should carry a percentage or statistic dressed up as fact.
    agents = _by_name()
    for name in _EXPECTED:
        text = agents[name]["weak_spot"]
        assert "%" not in text, f"{name}'s line looks like an invented statistic: {text!r}"
