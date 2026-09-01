"""Guard: the canonical city vocabulary (#6174).

Pure stdlib — no DB, no network, no fixtures, so it can never silently SKIP.

Every case below came from LIVE data measured 2026-09-01, not imagination:
  articles.city top values included Toronto 5438, Montreal 15 AND Montréal 8,
  Sydney 13, London 8, Vancouver Island 9, Cape Breton 9, the literal string
  "null" 23, and the countries Nepal 8 / Israel 7.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.city_identity import (  # noqa: E402
    AMBIGUOUS_WITHOUT_PROVINCE,
    CANONICAL_CITIES,
    canon_city,
    city_label,
    city_province,
    slug_for_site_code,
)


# ------------------------------------------------------- the join actually joins

def test_every_eccc_site_code_resolves():
    """The weather side. All 25 ECCC sites must reach a canonical slug."""
    assert len(CANONICAL_CITIES) == 25
    for slug, (code, _prov, _label) in CANONICAL_CITIES.items():
        assert slug_for_site_code(code) == slug


def test_the_news_side_reaches_the_same_slug():
    """The whole point: free text and site_code must land on ONE key."""
    assert canon_city("Toronto") == slug_for_site_code("s0000458") == "toronto"
    assert canon_city("Montréal") == slug_for_site_code("s0000635") == "montreal"


# --------------------------------------------------------------- trap 3: accents

def test_accented_and_unaccented_are_the_SAME_city():
    """Live data carries BOTH 'Montreal' (15) and 'Montréal' (8)."""
    assert canon_city("Montreal") == canon_city("Montréal") == "montreal"
    assert canon_city("Quebec") == canon_city("Québec") == "quebec"


# -------------------------------------------------- trap 4: ECCC parentheticals

def test_eccc_parenthetical_suffix_is_stripped():
    """The site label is 'Ottawa (Kanata - Orléans)'; the city is Ottawa."""
    assert canon_city("Ottawa (Kanata - Orléans)") == "ottawa"
    assert canon_city("Ottawa") == "ottawa"


def test_city_label_is_the_SHORT_form():
    """⚠️ Only 1 of 25 rows has a display_name, so name_en still carries the
    parenthetical. Rendering name_en directly gives 24 ugly/blank cards."""
    assert city_label("ottawa") == "Ottawa"
    assert "(" not in city_label("ottawa")
    assert city_label("montreal") == "Montréal"   # accent KEPT for display


# ------------------------------------------------ 🔴 trap 1: ambiguous names

def test_sydney_alone_does_NOT_resolve():
    """Sydney NS vs Sydney Australia. Live rows include `Sydney | NS | AU` and
    `Sydney | ON | GB` — the enricher is confused, so a bare name must not win."""
    assert canon_city("Sydney") is None


def test_london_alone_does_NOT_resolve():
    """London ON vs London UK."""
    assert canon_city("London") is None


def test_ambiguous_names_resolve_WITH_the_right_province():
    assert canon_city("Sydney", "NS") == "sydney"
    assert canon_city("London", "ON") == "london"


def test_ambiguous_names_REFUSE_a_contradicting_province():
    """`Sydney | ON` exists live. Sydney is in NS; ON must not resolve it."""
    assert canon_city("Sydney", "ON") is None
    assert canon_city("London", "NS") is None


def test_the_ambiguous_set_is_not_empty():
    """If this ever empties, the guard above becomes vacuous."""
    assert AMBIGUOUS_WITHOUT_PROVINCE
    assert AMBIGUOUS_WITHOUT_PROVINCE <= set(CANONICAL_CITIES)


# --------------------------------------------------- 🔴 trap 2: regions ≠ cities

def test_vancouver_island_is_NOT_vancouver():
    """A substring or fuzzy match would merge these. 9 live rows."""
    assert canon_city("Vancouver Island") is None
    assert canon_city("Vancouver") == "vancouver"


def test_cape_breton_is_NOT_sydney():
    assert canon_city("Cape Breton") is None


# --------------------------------- ⚠️ Saint John (NB) vs St. John's (NL)

def test_saint_john_and_st_johns_stay_DIFFERENT_cities():
    """One province apart. Deleting punctuation instead of separating on it
    pushes these toward each other."""
    sj = canon_city("Saint John")
    sjs = canon_city("St. John's")
    assert sj == "saint-john" and city_province(sj) == "NB"
    assert sjs == "st-johns" and city_province(sjs) == "NL"
    assert sj != sjs


# ----------------------------------------------------- trap 5: junk in the column

def test_the_literal_string_null_is_not_a_city():
    """23 live rows contain the STRING 'null' — not SQL NULL."""
    assert canon_city("null") is None
    assert canon_city("None") is None


def test_countries_are_not_cities():
    """Live: Nepal 8, Israel 7 in articles.city."""
    assert canon_city("Nepal") is None
    assert canon_city("Israel") is None


def test_foreign_cities_do_not_resolve():
    for name in ("New York", "Washington D.C.", "Kyiv", "Beijing", "Paris", "Tokyo"):
        assert canon_city(name) is None, f"{name} must not map to a Canadian city"


def test_empty_and_none_are_safe():
    assert canon_city(None) is None
    assert canon_city("") is None
    assert canon_city("   ") is None
    assert slug_for_site_code(None) is None
    assert city_label(None) is None


# ------------------------------------------------------------ internal coherence

def test_no_two_cities_share_a_site_code():
    codes = [c for c, _p, _l in CANONICAL_CITIES.values()]
    assert len(codes) == len(set(codes))


def test_every_province_is_a_real_canadian_code():
    valid = {"AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"}
    for slug, (_c, prov, _l) in CANONICAL_CITIES.items():
        assert prov in valid, f"{slug} has province {prov!r}"
