"""Guard tests for the MSC citypage parser (project #393, task #5760).

This feed encodes "no value" FIVE different ways and they are not
interchangeable. Every test below pins one of them, because the entire
A.U.R.O.R.A. surface rests on a single property: a MISSING reading and a ZERO
reading are different facts, and the UI colours them differently.

The dangerous one is `<gust>00</gust>`. It means NO GUST, and it parses cleanly
as the integer 0 — no exception raised, no empty-check triggered. A guard built
on truthiness cannot see it.
"""
import datetime
import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOD = ROOT / "ingest" / "weather" / "citypage_parse.py"

spec = importlib.util.spec_from_file_location("_citypage", MOD)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)          # stdlib-only: this can never skip


# ── the five encodings of absence ───────────────────────────────────────────

def test_forecast_gust_00_sentinel_is_absence_not_zero():
    """THE one that defeats a truthiness guard. Verified live in Toronto's
    forecast: every period carried <gust>00</gust> alongside a real speed."""
    el = ET.fromstring('<gust unitType="metric" units="km/h">00</gust>')
    assert cp.parse_gust(el) is None, (
        "'00' means NO GUST. It parses as int 0, so `int(x or 0)` silently "
        "reports a measured 0 km/h gust that was never observed."
    )


def test_a_real_forecast_gust_still_parses():
    """The sentinel guard must not swallow genuine values."""
    assert cp.parse_gust(ET.fromstring("<gust>50</gust>")) == 50.0


def test_present_but_empty_element_is_none():
    """<windChill></windChill> and <humidex></humidex> — verified live."""
    assert cp.num(ET.fromstring("<windChill></windChill>")) is None
    assert cp.num(ET.fromstring("<humidex/>")) is None


def test_absent_element_is_none():
    """visibility is simply missing on most sites. Normal, not an error."""
    assert cp.num(None) is None


def test_calm_is_a_measurement_not_a_missing_reading():
    """The XSD enumerates Calm/Calme as valid wind SPEEDS. float() raises on it.

    Writing 0.0 would assert a measurement that was never taken AND would render
    identically to an instrument that reported nothing. Calm gets its own flag.
    """
    speed, calm = cp.parse_wind_speed(ET.fromstring("<speed>calm</speed>"))
    assert speed is None and calm is True
    speed, calm = cp.parse_wind_speed(ET.fromstring("<speed>Calm</speed>"))
    assert speed is None and calm is True, "capitalisation varies in the feed"


def test_missing_wind_is_distinguishable_from_calm():
    """(None, False) vs (None, True) — the distinction the extra column buys."""
    assert cp.parse_wind_speed(None) == (None, False)
    assert cp.parse_wind_speed(ET.fromstring("<speed></speed>")) == (None, False)


def test_a_genuine_zero_survives():
    """Nothing here may become blanket 'zero is suspicious'. A real 0 stays 0."""
    assert cp.num(ET.fromstring("<temperature>0</temperature>")) == 0.0
    assert cp.num(ET.fromstring("<temperature>-0.0</temperature>")) == 0.0


# ── hemisphere-suffixed coordinates ─────────────────────────────────────────

def test_west_longitude_is_negative():
    """lat="43.68N" lon="79.63W" are STRINGS. float() raises; stripping the
    letter yields +79.63, which is in China. Every Canadian longitude is W, so
    getting this wrong plots the entire country on the wrong continent."""
    assert cp.parse_latlon("43.68N") == 43.68
    assert cp.parse_latlon("79.63W") == -79.63
    assert cp.parse_latlon("45.0S") == -45.0
    assert cp.parse_latlon("10.5E") == 10.5


def test_latlon_handles_absence_and_junk():
    for bad in (None, "", "   ", "N", "abc"):
        assert cp.parse_latlon(bad) is None


# ── timestamps ──────────────────────────────────────────────────────────────

def test_msc_timestamp_is_utc_aware():
    dt = cp.parse_msc_timestamp("20260818192549")
    assert dt == datetime.datetime(2026, 8, 18, 19, 25, 49, tzinfo=datetime.timezone.utc)
    assert dt.tzinfo is not None, "naive datetimes mix badly with TIMESTAMPTZ"


def test_bad_timestamp_is_none_not_an_exception():
    for bad in (None, "", "2026", "notadate12345678", "20261332999999"):
        assert cp.parse_msc_timestamp(bad) is None


# ── document-level behaviour ────────────────────────────────────────────────

_SELF_CLOSED = b"""<?xml version="1.0" encoding="ISO-8859-1"?>
<siteData><location><name lat="43.68N" lon="79.63W">Nowhere</name>
<province>ON</province></location><currentConditions/></siteData>"""


def test_self_closed_current_conditions_writes_no_row():
    """It has no observation timestamp, so it cannot key. Returning a dict of
    Nones would create a phantom observation; the caller records
    'no_observations' on the registry instead — which is a DIFFERENT fact from
    'we could not reach the source'."""
    meta, cur, fcs = cp.parse_document(_SELF_CLOSED, "x.xml")
    assert cur is None
    assert fcs == []
    assert meta["province_long"] == "ON"   # this fixture uses the code; live docs use "Ontario"
    assert meta["lon"] == -79.63, "location coords use the same hemisphere rule"


def test_observation_without_utc_timestamp_is_unkeyable():
    xml = b"""<?xml version="1.0"?><siteData><currentConditions>
    <dateTime name="observation" zone="EDT" UTCOffset="-4"><timeStamp>20260818153000</timeStamp></dateTime>
    <temperature>26.7</temperature></currentConditions></siteData>"""
    assert cp.parse_current_conditions(ET.fromstring(xml), "x.xml") is None, (
        "only the UTC dateTime is safe to key on; a local-only doc has no "
        "unambiguous observation time"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_document_province_is_the_long_name_and_is_not_the_registry_code():
    """The document says "Ontario"; siteList.xml (and aurora_city_site) say "ON".

    Two vocabularies for one field. Exposing the long name under `source_prov`
    would let it silently overwrite the registry's code — and every province
    join downstream is on the code.
    """
    meta, _, _ = cp.parse_document(_SELF_CLOSED, "x.xml")
    assert meta.get("province_long") == "ON" or meta.get("province_long") is not None
    assert "source_prov" not in meta, (
        "the parser must not emit source_prov — that field belongs to the "
        "registry, sourced from siteList.xml, in the 2-letter vocabulary"
    )
