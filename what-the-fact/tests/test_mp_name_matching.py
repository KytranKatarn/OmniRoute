"""MP name matching must not fire on substrings of ordinary words.

Every case below is drawn from LIVE data, not invented. The production matcher
used `family_name.lower() in text.lower()`, which attached sitting MPs to
articles that merely contained the word "change", "granted" or "blocked":

    Chang  x521    Grant  x87    Block  x61    Small  x35    Fisher x14

52.7% of the 26,844 tags in the table matched nothing at a word boundary.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament.openparl import (  # noqa: E402
    MATCH_FAMILY_NAME,
    MATCH_FULL_NAME,
    _compile_mp_patterns,
    match_mp_in_text,
)


def _match(full_name, family, text):
    return match_mp_in_text(text, *_compile_mp_patterns(full_name, family))


# ── the bug: substrings of common words ───────────────────────────────────────

@pytest.mark.parametrize("family,text", [
    ("Chang", "The policy will change how permits are issued."),
    ("Chang", "Exchange rates moved sharply overnight."),
    ("Chang", "Nothing is changing at the plant this year."),
    ("Grant", "The city granted the permit last Tuesday."),
    ("Grant", "She arrived as an immigrant in 1998."),
    ("Block", "Police blocked the intersection for two hours."),
    ("Small", "A smaller crowd turned out this year."),
    ("Fisher", "Atlantic fisheries reported a record season."),
    ("Church", "The church hall was used as a shelter."),
])
def test_substring_of_a_common_word_is_not_a_match(family, text):
    assert _match(f"Wade {family}", family, text) is None


def test_the_exact_live_failure():
    """Article 2031818 was publicly tagged with MP Wade Grant."""
    title = "For Hamiltonians battling addiction, peer support is a dose of empathy"
    assert _match("Wade Grant", "Grant", title) is None


# ── the family-name tier still works when it should ───────────────────────────

def test_capitalised_surname_at_a_word_boundary_matches():
    assert _match("Mark Carney", "Carney", "Prime Minister Carney said Monday") \
        == MATCH_FAMILY_NAME


def test_lowercase_common_noun_does_not_match_the_surname():
    """"the grant was awarded" is not a reference to MP Wade Grant."""
    assert _match("Wade Grant", "Grant", "the grant was awarded in June") is None


def test_full_name_wins_over_family_name():
    assert _match("Mark Carney", "Carney", "Mark Carney and Carney's office") \
        == MATCH_FULL_NAME


def test_full_name_is_case_insensitive():
    """A headline in caps is still the same person."""
    assert _match("Mark Carney", "Carney", "MARK CARNEY ANNOUNCES PLAN") \
        == MATCH_FULL_NAME


def test_short_family_names_are_never_used_alone():
    """<5 chars is too collision-prone; the existing rule, kept."""
    assert _match("Chandra Arya", "Arya", "Arya spoke in the House") is None
    assert _match("Chandra Arya", "Arya", "Chandra Arya spoke") == MATCH_FULL_NAME


# ── robustness ────────────────────────────────────────────────────────────────

def test_punctuation_in_a_name_is_escaped_not_interpreted():
    """A '.' in a name must match a literal dot, not any character."""
    assert _match("Jean-Yves Duclos", "Duclos", "Jean-Yves Duclos rose") == MATCH_FULL_NAME
    assert _match("A. Smith", "Smith", "AxSmith") is None


def test_accented_surname_matches_at_a_word_boundary():
    assert _match("Claude DeBellefeuille", "DeBellefeuille",
                  "DeBellefeuille asked the minister") == MATCH_FAMILY_NAME


def test_empty_and_none_inputs_do_not_raise():
    assert _match("Mark Carney", "Carney", "") is None
    assert _match("Mark Carney", "Carney", None) is None
    assert _match(None, None, "anything at all") is None
    assert _match("", "", "anything at all") is None


def test_surname_adjacent_to_punctuation_still_matches():
    """"Carney," and "(Carney)" are word-boundary hits."""
    assert _match("Mark Carney", "Carney", "According to Carney, the plan holds.") \
        == MATCH_FAMILY_NAME
    assert _match("Mark Carney", "Carney", "the PM (Carney) said") == MATCH_FAMILY_NAME
