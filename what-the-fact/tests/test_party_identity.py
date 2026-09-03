"""Guards for the party canonicalisation boundary and the /parties page.

The bug this whole module exists to prevent, measured on real ingested data:

    GE43 (2019)  "People's Party"        315 candidates    294,092 votes
    GE44 (2021)  "People's Party - PPC"  312 candidates    840,993 votes

Elections Canada Table 12 records the BALLOT name, and the PPC's gained its
initialism between the two elections. Grouped on the raw string, /parties
reported that the party did not contest 2019 and materialised with 840,993
votes in 2021 — destroying the single most notable fact about them, that their
vote nearly TRIPLED from a near-identical slate.

⚠️ These tests are stdlib + jinja2 only, deliberately. shared/party_identity.py
imports nothing, so its guards can never silently SKIP on a box without
psycopg2 (KB #290497) — the same reason results_parse.py is kept pure.
"""

from __future__ import annotations

import html

import pytest

from shared.party_identity import (
    NOT_MERGED,
    canonical_party,
    display_house_party,
    merged_labels,
)

jinja2 = pytest.importorskip("jinja2")


# --------------------------------------------------------------------------
# Canonicalisation
# --------------------------------------------------------------------------


def test_the_ppc_is_ONE_party_across_both_elections():
    """The regression that motivated the module."""
    assert canonical_party("People's Party") == canonical_party("People's Party - PPC")


def test_an_abbreviated_label_matches_its_spelled_out_form():
    """GE43 "ML" (50 candidates) is GE44 "Marxist-Leninist" (36)."""
    assert canonical_party("ML") == canonical_party("Marxist-Leninist") == "Marxist-Leninist"


def test_an_unmapped_party_passes_through_UNCHANGED():
    """Fail open. A new or renamed party must render honestly as itself rather
    than vanish into a wrong bucket or an 'Other' pile."""
    for name in ("Liberal", "Bloc Québécois", "Some Brand New Party"):
        assert canonical_party(name) == name


def test_blank_and_none_collapse_to_empty_string():
    assert canonical_party(None) == "" and canonical_party("   ") == ""


def test_plausible_but_UNPROVEN_renames_are_NOT_merged():
    """Inventing continuity is worse than showing two rows a reader can compare.

    Each of these is a merge someone could reasonably propose; none is
    demonstrable from the ingested data, so each stays separate AND carries a
    written reason so it is not 'fixed' later by someone who only sees the gap.
    """
    for name in ("Maverick Party", "Marijuana Party", "PC Party"):
        assert canonical_party(name) == name
        assert name in NOT_MERGED and len(NOT_MERGED[name]) > 40


def test_the_house_vocabulary_is_a_SEPARATE_namespace():
    """parliament.mps says "Bloc"/"NDP" for the SITTING house — a different
    event, with a different seat count (343 after the 2023 redistribution vs
    338 contested in GE44). Mapping the two into one namespace would make
    joining them look reasonable, and that join compares different elections."""
    assert display_house_party("Bloc") == "Bloc"
    assert canonical_party("Bloc") == "Bloc"
    # …and the House form is NOT an alias of the election form
    assert canonical_party("Bloc Québécois") != display_house_party("Bloc")


def test_every_merge_is_disclosed_to_the_reader():
    """A merge the reader cannot see is a merge they cannot check."""
    m = merged_labels()
    assert "People's Party" in m
    assert sorted(m["People's Party"]) == ["People's Party", "People's Party - PPC"]
    # only real merges are listed — a single-label group is not a merge
    assert all(len(v) > 1 for v in m.values())


# --------------------------------------------------------------------------
# The SQL projection must be generated FROM the Python table, never re-typed
# --------------------------------------------------------------------------


def test_the_sql_case_is_built_from_the_python_aliases():
    """A second copy of the alias table pasted into SQL is exactly how a
    canonicalisation boundary stops being one. Assert the generated SQL covers
    every alias, so adding one to the dict cannot leave the query behind."""
    pytest.importorskip("flask")
    from consumer.routes import _party_case_sql
    from shared.party_identity import _ALIASES

    sql = _party_case_sql()
    for raw, canon in _ALIASES.items():
        assert raw.replace("'", "''") in sql, raw
        assert canon.replace("'", "''") in sql, canon
    assert sql.count("WHEN") == len(_ALIASES)


def test_the_sql_case_escapes_apostrophes():
    """"People's Party" contains the SQL string delimiter. An unescaped one
    does not merely break the query — it changes what the query means."""
    pytest.importorskip("flask")
    from consumer.routes import _party_case_sql

    sql = _party_case_sql()
    assert "People''s Party" in sql
    assert "'People's Party'" not in sql


# --------------------------------------------------------------------------
# Page rendering
# --------------------------------------------------------------------------

ROWS = [
    # Liberal: won a far larger share of seats than of votes.
    {"party": "Liberal", "candidates": 338, "votes": 5556629, "seats": 160,
     "vote_pct": 32.62, "seat_pct": 47.34, "gap": 14.72,
     "prev_votes": 6018728, "prev_seats": 157,
     "votes_delta": -462099, "seats_delta": 3},
    # PPC: 840,993 votes, ZERO seats — and it DID contest the prior election.
    {"party": "People's Party", "candidates": 312, "votes": 840993, "seats": 0,
     "vote_pct": 4.94, "seat_pct": 0.00, "gap": -4.94,
     "prev_votes": 294092, "prev_seats": 0,
     "votes_delta": 546901, "seats_delta": 0},
    # GE44 only — genuinely has no prior figure.
    {"party": "Free Party Canada", "candidates": 59, "votes": 47252, "seats": 0,
     "vote_pct": 0.28, "seat_pct": 0.00, "gap": -0.28,
     "prev_votes": None, "prev_seats": None,
     "votes_delta": None, "seats_delta": None},
]
HOUSE = [{"party": "Liberal", "seats": 174}, {"party": "Bloc", "seats": 22}]


def _render(**kw):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("consumer/templates"), autoescape=True)
    src = open("consumer/templates/parties.html", encoding="utf-8").read()
    body = src.split("{% block content %}", 1)[1].rsplit("{% endblock %}", 1)[0]
    macros = ('{% from "_archetypes.html" import stat_tiles, segment, '
              'data_table, ranked_bars %}')
    d = dict(rows=ROWS, house=HOUSE, tiles=[], bars=[], elections=[],
             ge=44, prev_ge=43, election_date=None,
             merged=merged_labels(), unresolved={"candidates": 1, "votes": 52})
    d.update(kw)
    return env.from_string(macros + body).render(**d)


def test_a_party_that_ran_before_shows_a_CHANGE_not_an_em_dash():
    """The whole point of the canonicalisation, asserted at the page level."""
    out = html.unescape(_render())
    assert "+546,901" in out


def test_a_genuinely_new_party_shows_an_em_dash_and_NOT_a_zero():
    """No prior figure is not a change of zero. Rendering "+0" would claim the
    party held steady when in truth it did not run."""
    out = html.unescape(_render(rows=[ROWS[2]]))
    assert "—" in out
    assert "+0" not in out


def test_the_seat_gap_carries_its_sign():
    out = html.unescape(_render())
    assert "+14.7" in out   # Liberal, over-represented
    assert "-4.9" in out    # PPC, 4.94% of votes and no seats at all


def test_dropped_candidates_are_named_so_the_arithmetic_closes():
    """The party table excludes blank-party rows while the totals tile counts
    every row — GE44 rendered 2,009 candidates against 2,010 in the source. A
    one-row gap nobody can see is the kind that stays wrong."""
    out = html.unescape(_render())
    assert "1 candidate" in out and "52 vote" in out


def test_no_unresolved_candidates_means_NO_note_at_all():
    """A zero must not render as a disclosure about nothing."""
    out = _render(unresolved={"candidates": 0, "votes": 0})
    assert "whose party could not be read" not in out


def test_the_sitting_house_is_labelled_as_a_DIFFERENT_measurement():
    """343 sitting members vs 338 seats contested in GE44 — different events.
    Presented adjacently without that warning, a reader adds them up."""
    out = html.unescape(_render())
    assert "different measurement" in out.lower()
    assert "174" in out and "22" in out


def test_the_merge_is_explained_on_the_page_itself():
    out = html.unescape(_render())
    assert "People's Party - PPC" in out
    assert "nearly tripled" in out
