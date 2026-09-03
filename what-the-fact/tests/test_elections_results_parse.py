"""Guards for Elections Canada Table 12 parsing (WTF Elections section).

Fixtures are REAL rows lifted verbatim from GE44 and GE43.

⚠️ A NOTE ON WHAT FIXTURES CAN AND CANNOT TEST HERE, because getting this wrong
is what let three parser bugs through:

`derive_parties` recovers the party vocabulary by grouping candidate cells on
their French half and taking the longest common suffix. That needs VOLUME — two
candidates minimum per party. In a five-district sample most parties appear
once, and in a single-district sample every party does, so derivation legitimately
finds nothing. The fixtures therefore pass an EXPLICIT vocabulary when they
exercise the split, and derivation is tested separately against groups big enough
to derive from. The production ingest always parses the whole file (2,010+ rows),
where derivation is exact — verified: 24 parties, zero unmatched.

The first version of this file tested the winner rule thoroughly on four
districts and treated that green as evidence the parser was sound. It was not:
53% of rows had no party, 57% had the party glued into the name. A test can be
rigorous about one property and completely silent about another.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.elections.results_parse import (
    derive_parties,
    parse_table12,
    split_candidate,
)

FIX = Path(__file__).parent / "fixtures"
GE44 = FIX / "ge44_table12_sample.csv"
BEAUCE = FIX / "ge43_beauce_two_berniers.csv"

# The real GE44 ballot names, as derive_parties recovers them from the full file.
VOCAB = [
    "Liberal/Libéral",
    "Conservative/Conservateur",
    "NDP-New Democratic Party/NPD-Nouveau Parti démocratique",
    "People's Party - PPC/Parti populaire - PPC",
    "Green Party/Parti Vert",
    "Independent/Indépendant(e)",
    "Bloc Québécois/Bloc Québécois",
    "Nationalist/Nationaliste",
    "Parti Rhinocéros Party/Parti Rhinocéros Party",
    "Marxist-Leninist/Marxiste-Léniniste",
]


@pytest.fixture(scope="module")
def report():
    return parse_table12(GE44.read_text(encoding="utf-8"), VOCAB)


# --------------------------------------------------------------------------
# The winner rule — `**` is INCUMBENCY, not victory
# --------------------------------------------------------------------------


def test_every_district_returns_exactly_one_winner(report):
    per = {}
    for c in report.candidates:
        per[c.district_number] = per.get(c.district_number, 0) + (1 if c.elected else 0)
    assert per == {d: 1 for d in per}, per


def test_a_seat_won_WITHOUT_a_star_is_still_elected(report):
    """Measured over all 338 GE44 districts: 306 rows carry `**`, 32 districts
    have none, and the starred row is the top-vote row in only 285. Using `**`
    names the WRONG MP in 53 ridings. These three won with no star."""
    for dnum, who in (("10006", "Joanne Thompson"),
                      ("11004", "Heath MacDonald"),
                      ("12006", "Lena Metlege Diab")):
        won = [c for c in report.candidates if c.district_number == dnum and c.elected]
        assert len(won) == 1 and won[0].name == who, (dnum, won)
        assert won[0].incumbent is False


def test_incumbency_and_victory_are_independent(report):
    assert [c for c in report.candidates if c.elected and c.incumbent]
    assert len([c for c in report.candidates if c.elected and not c.incumbent]) >= 3


def test_majority_is_empty_for_everyone_but_the_winner(report):
    for c in report.candidates:
        if not c.elected:
            assert c.majority is None, (c.district_number, c.name)


def test_no_anomalies_on_known_good_data(report):
    assert report.anomalies == [], report.anomalies


# --------------------------------------------------------------------------
# Party vocabulary — derived, never hardcoded
# --------------------------------------------------------------------------


def test_derive_parties_recovers_multiword_names():
    """The names that defeated the hardcoded map."""
    cells = [
        "Ann Smith NDP-New Democratic Party/NPD-Nouveau Parti démocratique",
        "Bo Jones NDP-New Democratic Party/NPD-Nouveau Parti démocratique",
        "Cal Roy People's Party - PPC/Parti populaire - PPC",
        "Dee Katz People's Party - PPC/Parti populaire - PPC",
    ]
    got = set(derive_parties(cells))
    assert "NDP-New Democratic Party/NPD-Nouveau Parti démocratique" in got
    assert "People's Party - PPC/Parti populaire - PPC" in got


def test_a_shared_name_suffix_bleeds_into_the_derived_party():
    """A KNOWN LIMIT, pinned so it is not discovered as a surprise.

    The party is recovered as the longest common suffix of the names before the
    slash. If EVERY candidate of a party shares a trailing name token, that
    token is part of the common suffix and lands in the party string. Two
    candidates both surnamed "Roy" is enough to trigger it.

    Harmless in production — a real party fields dozens to hundreds of
    candidates and they do not all share a surname (verified: 24/24 GE44
    parties derived correctly, zero unmatched) — but it is why this must run
    over the WHOLE file and never a sample.
    """
    got = derive_parties(["C Roy Green Party/Parti Vert",
                          "D Roy Green Party/Parti Vert"])
    assert got == ["Roy Green Party/Parti Vert"], got


def test_a_party_with_ONE_candidate_yields_no_entry():
    """The longest common suffix of a single string is that whole string, so a
    one-candidate party derived the vocabulary entry "Gus Stefanis Nationalist"
    — the person's NAME became the party, the name went empty, and empty names
    then collided on the unique key and silently dropped a row."""
    assert derive_parties(["Gus Stefanis Nationalist/Nationaliste"]) == []


def test_derivation_does_not_use_table_9():
    """Table 9 looks authoritative and is a DIFFERENT vocabulary: registered
    legal names ("Liberal Party of Canada/Parti libéral du Canada") vs Table
    12's ballot names ("Liberal/Libéral"). Matching against it left 1,715 of
    2,010 cells unmatched."""
    import inspect
    import ingest.elections.results_parse as m
    assert not hasattr(m, "parse_table9_parties")
    assert "Table 9" in inspect.getdoc(m.derive_parties)


# --------------------------------------------------------------------------
# Cell splitting
# --------------------------------------------------------------------------


def test_split_uses_the_vocabulary():
    name, raw, party, inc = split_candidate("Ken McDonald ** Liberal/Libéral", VOCAB)
    assert (name, raw, party, inc) == ("Ken McDonald", "Liberal/Libéral", "Liberal", True)


def test_split_without_a_star():
    name, _r, party, inc = split_candidate(
        "Matthew Chapman Conservative/Conservateur", VOCAB)
    assert (name, party, inc) == ("Matthew Chapman", "Conservative", False)


def test_an_unresolvable_cell_keeps_the_whole_string_as_the_NAME():
    """Never guess a boundary. The previous fallback scanned tokens from the
    START for the first tail containing "/" — which is the whole string — so it
    returned an EMPTY name and put "Lainie Stewart People's Party - PPC" in the
    party column. 4,156 rows collapsed to 1,213."""
    name, raw, party, _inc = split_candidate("Someone Unknown Party/Parti", [])
    assert name == "Someone Unknown Party/Parti"
    assert party == "" and raw == ""


def test_unresolved_cells_are_reported_not_silently_dropped(report):
    """One minor-party candidate must be visible, but must not withhold 338
    real results — so it is reported, not fatal."""
    assert report.party_unresolved, "the fixture contains singleton parties"
    assert report.anomalies == [], "an unresolved party is NOT a blocking anomaly"


def test_bilingual_cells_keep_only_the_english_half(report):
    for c in report.candidates:
        assert "/" not in c.province and "/" not in c.district_name


def test_padded_numbers_are_parsed(report):
    for c in (c for c in report.candidates if c.elected):
        assert isinstance(c.votes, int) and c.votes > 0
        assert c.majority is not None and c.majority > 0


# --------------------------------------------------------------------------
# A person's name is not a unique identifier
# --------------------------------------------------------------------------


def test_two_candidates_with_the_SAME_NAME_in_one_riding():
    """GE43, Beauce: the People's Party leader Maxime Bernier and a Rhinoceros
    Party candidate who legally changed his name to Maxime Bernier to confuse
    the ballot. A (district, name) unique key dropped one — 2,146 parsed, 2,145
    stored, and the row count was the only symptom.

    Derivation cannot run on a single district (every party is a singleton
    there), so the vocabulary is supplied — which is the point of the test: the
    two rows must survive as distinct records.
    """
    # ⚠️ GE43 vocabulary, not GE44's. The ballot name CHANGED between
    # elections — "People's Party/Parti populaire" in 2019 became
    # "People's Party - PPC/Parti populaire - PPC" in 2021 — which is why the
    # vocabulary is derived per election rather than shared.
    ge43_vocab = VOCAB + ["People's Party/Parti populaire"]
    rep = parse_table12(BEAUCE.read_text(encoding="utf-8"), ge43_vocab)
    berniers = [c for c in rep.candidates if c.name == "Maxime Bernier"]
    assert len(berniers) == 2, [c.name for c in rep.candidates]
    assert {b.party for b in berniers} == {"People's Party", "Parti Rhinocéros Party"}
    # …and they are distinguishable, which is what the widened key relies on
    assert len({(b.district_number, b.name, b.party) for b in berniers}) == 2
