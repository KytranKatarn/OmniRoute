"""Guards for /races and /races/<district> (WTF Elections section).

These are RENDER tests against fixture data, not SQL tests. The bugs they exist
to catch were all template-layer and all invisible to a 200-status check:

  * `ranked_bars` reads .label/.value and Jinja has NO list comprehension, so
    the first draft's bar expression was syntactically dead.
  * `data_table` unpacks `for head, align in columns`, so a plain list of
    header strings raises at render.
  * `{{ cell }}` is autoescaped, so HTML built by string concatenation with `~`
    prints its own tags as text — while ALSO putting the source data in raw.
    The {% set %}…{% endset %} block idiom (as /archive uses) is correct on
    both counts, and these tests pin that.

⚠️ A 200 and a keyword scan are not verification. Every assertion below names a
value that can be checked against Elections Canada independently.
"""

from __future__ import annotations

import html
import re

import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

flask = pytest.importorskip("flask")
jinja2 = pytest.importorskip("jinja2")


@pytest.fixture(scope="module")
def env():
    """The real template directory, with only the macros the pages import."""
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader("consumer/templates"),
        autoescape=True,  # matches Flask for .html — the whole point
    )


# One riding whose numbers are public record: GE44 Châteauguay—Lacolle, won by
# Brenda Shanahan (Liberal) by 12 votes — the closest result in that election.
RACES = [
    {"district_number": "24019", "district_name": "Châteauguay--Lacolle",
     "province": "Quebec", "candidate_name": "Brenda Shanahan", "party": "Liberal",
     "incumbent": True, "votes": 18029, "vote_share": 37.0, "majority": 12,
     "margin_pct": 0.02, "runner_up_party": "Bloc Québécois"},
    {"district_number": "10006", "district_name": "St. John's East",
     "province": "Newfoundland and Labrador", "candidate_name": "Joanne Thompson",
     "party": "Liberal", "incumbent": False, "votes": 16601, "vote_share": 44.1,
     "majority": 2532, "margin_pct": 6.7, "runner_up_party": "NDP-New Democratic Party"},
]
BARS = [{"label": "Liberal", "value": 160, "display": "160 seats"},
        {"label": "Conservative", "value": 119, "display": "119 seats"}]


def _render(env, **kw):
    """Render races.html standalone.

    base.html pulls in the whole site shell, so the page block is rendered on
    its own — these tests are about the table and bars, not the chrome (the nav
    has its own guard in test_nav_shell.py).
    """
    src = open("consumer/templates/races.html", encoding="utf-8").read()
    body = src.split("{% block content %}", 1)[1].rsplit("{% endblock %}", 1)[0]
    macros = '{% from "_archetypes.html" import stat_tiles, segment, data_table, ranked_bars %}'
    defaults = dict(ge=44, election_date=None, tiles=[], parties=[], party_bars=[],
                    elections=[], races=[], total_races=0, provinces=[], province="")
    defaults.update(kw)
    return env.from_string(macros + body).render(**defaults)


def test_the_riding_link_is_a_LINK_not_escaped_markup(env):
    """The `~` concatenation this replaced produced `&lt;a href=...` on screen."""
    out = _render(env, races=RACES, total_races=2)
    assert '<a href="/races/24019?ge=44">' in out
    assert "&lt;a href" not in out


def test_candidate_names_are_still_escaped(env):
    """Markup-safe must not mean data-raw. A government CSV is not a reason to
    stop escaping — the site rule is that external text never enters markup."""
    rows = [dict(RACES[0], candidate_name='Bad <script>alert(1)</script>')]
    out = _render(env, races=rows, total_races=1)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_column_headers_unpack(env):
    """data_table does `for head, align in columns`; a flat list of strings
    raises ValueError at render time, which a 200-check never sees."""
    out = _render(env, races=RACES, total_races=2)
    for head in ("Riding", "Province", "Elected", "Party", "Votes",
                 "Share", "Margin", "Runner-up"):
        assert f">{head}</th>" in out


def test_seat_bars_render_from_shaped_rows(env):
    """ranked_bars reads .label/.value. The bar rows are built in the ROUTE
    because Jinja cannot express a list comprehension."""
    out = _render(env, party_bars=BARS)
    assert "<span>Liberal</span>" in out
    assert "160 seats" in out
    # widest bar is the largest value, at 100%
    assert "width: 100.0%" in out


def test_a_twelve_vote_margin_does_NOT_render_as_zero_percent(env):
    """12 votes in ~48,000 rounds to 0.0%, and "12 (0.0%)" reads as no margin
    at all. Sub-0.05% shows as <0.1% instead. Caught by rendering the real
    closest race, not by any unit assertion on the SQL."""
    out = html.unescape(_render(env, races=RACES, total_races=2))
    assert "12 (<0.1%)" in out
    assert "(0.0%)" not in out
    # …and an ordinary margin is unaffected
    assert "2,532 (6.7%)" in out


def test_a_tight_race_is_marked_and_a_comfortable_one_is_not(env):
    out = _render(env, races=RACES, total_races=2)
    cells = re.findall(r'<span class="wtf-rc-mar([^"]*)"', out)
    assert cells[0].strip() == "wtf-rc-tight", cells
    assert cells[1].strip() == "", cells


def test_incumbency_is_shown_but_never_as_the_reason_they_won(env):
    """Both rows are winners; only one is an incumbent. If the marker ever
    became the winner signal, the second row would vanish from the table."""
    out = html.unescape(_render(env, races=RACES, total_races=2))
    assert out.count("· incumbent") == 1
    assert "Brenda Shanahan" in out and "Joanne Thompson" in out


def test_empty_state_says_so_rather_than_rendering_a_bare_table(env):
    out = _render(env, races=[], total_races=0)
    assert "No ridings match this filter." in out


# --------------------------------------------------------------------------
# The fixture must match what the QUERY emits
# --------------------------------------------------------------------------


def test_the_margin_fixture_matches_the_querys_own_rounding():
    """⚠️ THIS IS THE TEST THAT WAS MISSING, and its absence shipped a bug.

    The <0.1% guard was written against a fixture of 0.0246 — a value the query
    CANNOT produce, because the SQL rounds margin_pct before the template ever
    sees it. At the shipped 1dp a 12-vote win in 57,349 became exactly 0.0, the
    template guard (`margin_pct > 0`) never fired, and the closest race in the
    country rendered "12 (0.0%)" on the LIVE SITE while this suite was green.
    The test was rigorous about a number that does not exist.

    Second time this session a self-chosen fixture proved a property of the
    fixture rather than of the code (cf. the winner-rule districts, which all
    happened to have simple party names). When you pick the input, you pick the
    answer — so pin the query's rounding and DERIVE the fixture from it.
    """
    routes = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
    assert "round(100.0 * w.majority / w.cast_votes, 2)" in routes, (
        "margin_pct must keep 2dp — 1dp flattens a sub-0.1% margin to 0.0 "
        "before the template can say '<0.1%'")

    # The real riding (Châteauguay—Lacolle, GE44), computed as the query does.
    majority, cast_votes = 12, 57349
    assert round(100.0 * majority / cast_votes, 2) == RACES[0]["margin_pct"]
    # …and that value must still trip the template's guard.
    assert 0 < RACES[0]["margin_pct"] < 0.05
