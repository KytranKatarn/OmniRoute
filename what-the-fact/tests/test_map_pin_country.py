"""Country resolution for /map pins (_pin_country).

/map colours every pin by country. articles.country_code stopped being written
at some point — all 4,291 geocoded articles in the live 7-day window have it
NULL while 5,475 older rows carry 'CA' — so every pin rendered the same
"unknown" grey and the legend advertised Canadian and International categories
that could never appear.

Most of it is recoverable because the province code is still written. These
tests pin the two rules that keep the recovery from inventing facts:

  1. A REPORTED country always beats a derived one.
  2. Only the 13 real Canadian codes derive a country.

Rule 2 is not defensive programming. province_code is NOT exclusively
Canadian in this database — measured live, it also holds US state codes and,
in one row, a country code.

Run: python3 -m pytest tests/test_map_pin_country.py -q
"""
import pytest

from consumer.routes import _CA_PROVINCES, _pin_country


# ── rule 1: a reported country wins ────────────────────────────────────────
def test_reported_country_is_used_as_is():
    assert _pin_country("US", None) == ("US", "reported")


def test_reported_country_beats_the_province_derivation():
    """89 live rows are country='US' province='ON'.

    Ontario normally derives CA. Here the country was actually recorded, and a
    recorded value is evidence where a derivation is only an implication — so
    these 89 articles must NOT be relabelled Canadian.
    """
    assert _pin_country("US", "ON") == ("US", "reported")


def test_reported_canadian_country_is_reported_not_derived():
    """CA from the column is a READING; CA from a province is an INFERENCE.

    Both produce the code 'CA', so only `source` can tell them apart — which is
    what the UI counts to say how many pins were recovered.
    """
    assert _pin_country("CA", "ON") == ("CA", "reported")


# ── rule 2: only genuine Canadian codes derive a country ───────────────────
@pytest.mark.parametrize("prov", sorted(_CA_PROVINCES))
def test_every_canadian_province_derives_canada(prov):
    assert _pin_country(None, prov) == ("CA", "derived")


def test_all_thirteen_provinces_and_territories_are_covered():
    """A missing code silently drops that province into "unknown" grey."""
    assert len(_CA_PROVINCES) == 13
    for code in ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU",
                 "ON", "PE", "QC", "SK", "YT"):
        assert code in _CA_PROVINCES


@pytest.mark.parametrize("state", ["KY", "NY"])
def test_a_us_state_code_does_not_become_canadian(state):
    """Live data has province_code='KY' and 'NY'.

    "Has a province_code" therefore does NOT mean "is Canadian". Deriving from
    presence rather than from an allowlist would file Kentucky under Canada.
    """
    assert _pin_country(None, state) == ("??", "unknown")


def test_a_country_code_in_the_province_column_is_not_a_province():
    """One live row carries province_code='CA'.

    That is a country code in the wrong column. It must not round-trip into a
    confident "Canadian" — the row's real location is unknown.
    """
    assert _pin_country(None, "CA") == ("??", "unknown")


# ── absence ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cc", [None, "", "??", "  "])
def test_missing_country_with_no_province_stays_unknown(cc):
    assert _pin_country(cc, None) == ("??", "unknown")


def test_the_sentinel_is_not_treated_as_a_reported_country():
    """The SQL COALESCEs NULL to '??'. If that sentinel were taken as a real
    country code the derivation would never run and the bug would persist."""
    assert _pin_country("??", "QC") == ("CA", "derived")


# ── normalisation ──────────────────────────────────────────────────────────
def test_inputs_are_normalised_before_matching():
    """Case and whitespace must not decide whether a province is recognised."""
    assert _pin_country(None, " on ") == ("CA", "derived")
    assert _pin_country(" us ", None) == ("US", "reported")


def test_source_is_always_one_of_the_three_known_values():
    """The template branches on this string; a fourth value would fall through
    every branch and render nothing."""
    for cc, pc in [("US", None), (None, "ON"), (None, None), ("??", "KY")]:
        assert _pin_country(cc, pc)[1] in {"reported", "derived", "unknown"}
