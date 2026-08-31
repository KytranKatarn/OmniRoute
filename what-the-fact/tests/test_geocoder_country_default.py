"""L.O.C.A.L. geo defaults must survive a SANITIZED LLM result (#6210).

articles.country_code was NULL for every geocoded article for 21 straight days
— 4,460 provincial articles in one week, exactly ONE of which had a country.
/map colours pins by country, so the whole map rendered a single "unknown" grey
and its legend advertised two categories that could never appear.

The cause was one word. `extract_geo` did:

    result.setdefault("country_code", "CA")

on a dict that had already been through `_sanitize()`. Sanitize's whole job is
converting the LLM's literal "null"/"none"/"" into a real Python None — which
leaves the KEY PRESENT. `setdefault` only fills a MISSING key, so it silently
did nothing, forever.

⚠️ The trap is that the code READS correctly. Only executing it with a REAL
L.O.C.A.L. payload (country_code="null") exposes the no-op, which is why these
tests drive `extract_geo` end to end rather than asserting on source text.

Run: python3 -m pytest tests/test_geocoder_country_default.py -q
"""
import pytest

from ingest import geocoder


@pytest.fixture
def local_agent(monkeypatch):
    """Stub L.O.C.A.L. so each test controls exactly what the LLM returns."""
    def _install(payload):
        monkeypatch.setattr(geocoder, "analyze",
                            lambda kind, aid, title, body: dict(payload))
        monkeypatch.setattr(geocoder, "_GEO_LIVE_SKIP", False)
    return _install


def _geo():
    return geocoder.extract_geo(1, "Council votes on budget",
                                "The city council met today to vote.")


# ── the regression itself ──────────────────────────────────────────────────
def test_province_with_llm_string_null_country_still_gets_CA(local_agent):
    """THE #6210 case. This is what L.O.C.A.L. actually emits in production."""
    local_agent({"province_code": "ON", "city": "Toronto", "lat": None, "lng": None,
                 "country_code": "null", "geo_scope": "provincial",
                 "geo_confidence": 0.8})
    assert _geo()["country_code"] == "CA"


@pytest.mark.parametrize("blank", ["null", "none", "NULL", "None", "", "   "])
def test_every_blank_spelling_the_sanitizer_handles_still_yields_CA(local_agent, blank):
    """_sanitize maps all of these to None, so all of them defeated setdefault."""
    local_agent({"province_code": "AB", "country_code": blank,
                 "geo_scope": "provincial"})
    assert _geo()["country_code"] == "CA"


def test_country_key_absent_entirely_still_gets_CA(local_agent):
    """The case setdefault DID handle — must keep working."""
    local_agent({"province_code": "QC", "geo_scope": "provincial"})
    assert _geo()["country_code"] == "CA"


@pytest.mark.parametrize("prov", ["AB", "BC", "MB", "NB", "NL", "NS", "NT",
                                  "NU", "ON", "PE", "QC", "SK", "YT"])
def test_all_thirteen_provinces_resolve_to_canada(local_agent, prov):
    local_agent({"province_code": prov, "country_code": "null",
                 "geo_scope": "provincial"})
    assert _geo()["country_code"] == "CA"


# ── the fix must not over-reach ────────────────────────────────────────────
def test_a_real_foreign_country_is_NOT_overwritten_to_CA(local_agent):
    """The whole point is filling a BLANK, never replacing a real reading.

    If this ever fails, every international article has been relabelled
    Canadian — a far worse bug than the one being fixed.
    """
    local_agent({"province_code": None, "country_code": "US",
                 "geo_scope": "international"})
    assert _geo()["country_code"] == "US"


def test_a_foreign_country_keeps_its_international_scope(local_agent):
    local_agent({"province_code": None, "country_code": "GB",
                 "geo_scope": "international"})
    r = _geo()
    assert r["country_code"] == "GB"
    assert r["province_code"] is None


def test_unmappable_stays_unmappable_with_no_country(local_agent):
    """An article with no location must NOT be defaulted into Canada.

    'We could not place this' and 'this is Canadian' are different facts.
    """
    local_agent({"province_code": None, "country_code": "null",
                 "geo_scope": "null"})
    r = geocoder.extract_geo(1, "zzzz", "zzzz")   # matches no heuristic pattern
    assert r["country_code"] is None
    assert r["geo_scope"] == "unmappable"


# ── the helper, in isolation ───────────────────────────────────────────────
def test_fill_if_blank_overwrites_an_explicit_None():
    """This is the exact behaviour setdefault lacks."""
    d = {"country_code": None}
    geocoder._fill_if_blank(d, "country_code", "CA")
    assert d["country_code"] == "CA"


def test_fill_if_blank_leaves_a_real_value_alone():
    d = {"country_code": "US"}
    geocoder._fill_if_blank(d, "country_code", "CA")
    assert d["country_code"] == "US"


def test_setdefault_would_still_fail_here():
    """Pins WHY the helper exists, so nobody 'simplifies' it back.

    If someone reverts _fill_if_blank to setdefault, the tests above fail — but
    this one documents the reason in one line.
    """
    d = {"country_code": None}
    d.setdefault("country_code", "CA")
    assert d["country_code"] is None, "setdefault cannot overwrite an explicit None"


def test_no_setdefault_remains_on_the_sanitized_result():
    """A NEW default added with setdefault would be silently dead on arrival."""
    import inspect
    src = inspect.getsource(geocoder.extract_geo)
    assert "setdefault" not in src, (
        "extract_geo operates on a _sanitize()d dict; use _fill_if_blank so the "
        "default survives an explicit None"
    )
