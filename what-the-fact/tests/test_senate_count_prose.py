"""/mps Senate tab — the "N current senators" prose must match the real
roster on the same page, not a hardcoded design-mockup number.

design-handoff's own README corrections table (item #1) documents this
exact live defect: "Senate page states 96 senators, renders 93" — the
senator roster (`senators`, from `parliament.senators WHERE is_current`)
was always real and correctly counted 93, but one static prose sentence in
mps.html still hardcoded the design mockup's "96", never updated when the
real data was wired in. Ninety-six does not even match Canada's Senate's
statutory 105 seats, so it was never a real total — just a stale copy-paste.

Fix: the prose reads `{{ senators|length }}` instead of a literal number,
so it can never drift from the roster again as appointments/retirements
change the real count.
"""
from __future__ import annotations

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


def _senators(n):
    return [{"slug": f"s{i}", "name": f"Senator {i}", "given_name": "S", "family_name": str(i),
             "caucus": "ISG", "province": "ON", "photo_url": None, "profile_url": None,
             "appointed_at": None} for i in range(n)]


def _render(env, senators):
    return env.get_template("mps.html").render(
        mps=[], parties=[], provinces=[], party_filter="", province_filter="",
        source_count=1, senators=senators, total_seats=337, is_subscriber=False,
    )


class TestSenateCountMatchesTheRoster:
    def test_prose_count_equals_the_real_roster_length(self, env):
        html = _render(env, _senators(93))
        assert "93 current senators" in html

    def test_the_literal_96_never_appears(self, env):
        """Regression: the design-mockup's hardcoded number, in any roster
        size, must never survive in the rendered prose."""
        for n in (60, 93, 96, 105):
            html = _render(env, _senators(n))
            assert "96 current senators" not in html or n == 96

    def test_count_tracks_the_roster_not_a_frozen_number(self, env):
        """A roster of 90 renders 90, not whatever number shipped last time
        — proves the fix reads senators|length, not a re-hardcoded literal."""
        html_90 = _render(env, _senators(90))
        html_94 = _render(env, _senators(94))
        assert "90 current senators" in html_90
        assert "94 current senators" in html_94

    def test_six_caucus_groups_claim_still_present(self, env):
        """Not part of this fix — confirming the untouched half of the same
        sentence survives the edit unchanged."""
        html = _render(env, _senators(93))
        assert "Six caucus groups" in html
