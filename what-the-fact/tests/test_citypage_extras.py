"""MSC city-page extras (Dev HQ 7234, S2 of the weather port): hourly forecast, regional normals, yesterday, sunrise/sunset, forecast-period icon/humidex/
humidity, and the uv_category fix.

The parser is exercised against ONE REAL ECCC file (tests/fixtures/msc_citypage_s0000047_en.xml, Calgary, fetched 2026-10-14). The storage helpers run against
a recording fake engine, so the properties that matter for production are pinned: every step is isolated (migration 105 not applied, or a bad section, can
never break the existing observation / forecast feed), the core forecast insert does not depend on the new columns, and a dry run writes nothing.
"""
import datetime as dt
import importlib.util
import pathlib
import xml.etree.ElementTree as ET

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / "tests" / "fixtures" / "msc_citypage_s0000047_en.xml").read_bytes()

spec = importlib.util.spec_from_file_location("_citypage_extras", ROOT / "ingest" / "weather" / "citypage_parse.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)  # stdlib-only: the parser tests can never skip

UTC = dt.timezone.utc


def _extras(xml=FIXTURE):
    return cp.parse_extras(xml, "fx.xml")


# ---- parser, real file -------------------------------------------------------------------------------------------------------------------------------
def test_hourly_is_24_consecutive_hours_with_the_exact_first_row():
    h = _extras()["hourly"]
    assert len(h) == 24
    assert [b["hour_utc"] - a["hour_utc"] for a, b in zip(h, h[1:])] == [dt.timedelta(hours=1)] * 23
    assert h[0]["hour_utc"] == dt.datetime(2026, 10, 14, 13, 0, tzinfo=UTC) and h[-1]["hour_utc"] == dt.datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    first = {k: h[0][k] for k in ("issued_utc", "condition", "icon_code", "temp_c", "lop_pct", "lop_category", "wind_speed_kmh", "wind_is_calm", "wind_dir", "wind_gust_kmh")}
    assert first == {"issued_utc": dt.datetime(2026, 10, 14, 5, 0, tzinfo=UTC), "condition": "Mainly cloudy", "icon_code": "33", "temp_c": 8.0, "lop_pct": 0.0,
                     "lop_category": "Nil", "wind_speed_kmh": 20.0, "wind_is_calm": False, "wind_dir": "W", "wind_gust_kmh": 40.0}


def test_blank_windchill_and_humidex_are_none_never_zero():
    h = _extras()["hourly"]
    assert h[0]["wind_chill"] is None and h[0]["humidex"] is None, "the feed writes <windChill/> and <humidex/> as empty elements"


def test_regional_normals():
    n = _extras()["normals"]
    assert (n["normal_high_c"], n["normal_low_c"], n["text_summary"]) == (12.0, -1.0, "Low minus 1. High 12.")
    assert n["issued_utc"] == dt.datetime(2026, 10, 14, 11, 0, tzinfo=UTC)


def test_yesterday_is_dated_the_day_before_the_local_issue_date_with_exact_values():
    y = _extras()["yesterday"]
    assert y["obs_date"] == dt.date(2026, 10, 13)
    assert (y["high_c"], y["low_c"], y["precip_mm"], y["rain_mm"], y["snow_cm"]) == (12.1, -2.1, 0.0, 0.0, 0.0)
    assert (y["gust_kmh"], y["gust_bearing_deg"], y["gust_dir"]) == (37.08, 164.0, "SSE")
    assert (y["precip_trace"], y["rain_trace"], y["snow_trace"]) == (False, False, False)


def test_sun_is_keyed_by_the_local_date_not_the_sunsets_utc_date():
    s = _extras()["sun"]
    assert s["sun_date"] == dt.date(2026, 10, 14)
    assert s["sunrise_utc"] == dt.datetime(2026, 10, 14, 13, 58, tzinfo=UTC)
    assert s["sunset_utc"] == dt.datetime(2026, 10, 15, 0, 46, tzinfo=UTC)  # the NEXT utc day: why the key is the local date


def test_forecast_periods_gain_icon_humidity_and_the_uv_category_fix():
    _, _, fcs = cp.parse_document(FIXTURE, "fx.xml")
    assert len(fcs) == 13
    p0, p1 = fcs[0], fcs[1]
    assert (p0["icon_code"], p0["rel_humidity_pct"], p0["humidex"]) == ("05", 30.0, None)
    assert (p1["icon_code"], p1["rel_humidity_pct"]) == ("30", 75.0)
    assert (p0["uv_index"], p0["uv_category"]) == (2.0, "low"), "uv_category is an ATTRIBUTE of <uv>; it was NULL on every stored row"
    assert (p1["uv_index"], p1["uv_category"]) == (None, None)


def test_uv_category_attribute_and_the_old_child_form_both_work():
    def period(uv):
        return ET.fromstring("<siteData><forecastGroup>" + _issue_xml("forecastIssue") + "<forecast><period>Today</period>" + uv + "</forecast></forecastGroup></siteData>")
    for uv, want in (('<uv category="high"><index>8</index></uv>', "high"), ("<uv><index>3</index><category>moderate</category></uv>", "moderate")):
        rows = cp.parse_forecasts(period(uv), "x")
        assert rows[0]["uv_category"] == want


def _issue_xml(name, utc="20261014050000", local="20261013230000"):
    return (f'<dateTime name="{name}" zone="UTC" UTCOffset="0"><timeStamp>{utc}</timeStamp></dateTime>'
            f'<dateTime name="{name}" zone="MDT" UTCOffset="-6"><timeStamp>{local}</timeStamp></dateTime>')


# ---- parser, edge cases ------------------------------------------------------------------------------------------------------------------------------
def test_every_new_section_missing_is_empty_and_never_an_exception():
    root = ET.fromstring(FIXTURE)
    for tag in ("hourlyForecastGroup", "yesterdayConditions", "riseSet"):
        root.remove(root.find(tag))
    fg = root.find("forecastGroup")
    fg.remove(fg.find("regionalNormals"))
    x = cp.parse_extras(ET.tostring(root), "x")
    assert x == {"hourly": [], "normals": None, "yesterday": None, "sun": None}
    meta, cur, fcs = cp.parse_document(ET.tostring(root), "x")  # the existing ingest path is untouched
    assert cur is not None and len(fcs) == 13


def test_hourly_gust_sentinel_calm_wind_and_empty_lop_are_absences():
    xml = ("<siteData><hourlyForecastGroup>" + _issue_xml("forecastIssue") +
           '<hourlyForecast dateTimeUTC="202610141300"><condition>Clear</condition><iconCode>30</iconCode><temperature>5</temperature><lop category="Nil"/>'
           '<wind><speed>calm</speed><direction>N</direction><gust>00</gust></wind></hourlyForecast>'
           '</hourlyForecastGroup></siteData>')
    r = _extras(xml.encode())["hourly"][0]
    assert r["wind_gust_kmh"] is None, "'00' means NO GUST, not a measured 0 km/h"
    assert (r["wind_speed_kmh"], r["wind_is_calm"]) == (None, True), "calm is a measurement with no number"
    assert r["lop_pct"] is None and r["lop_category"] == "Nil"


def test_an_unkeyable_hourly_entry_is_skipped_not_stored_under_a_guessed_hour():
    xml = ("<siteData><hourlyForecastGroup>" + _issue_xml("forecastIssue") +
           '<hourlyForecast dateTimeUTC="oops"><temperature>1</temperature></hourlyForecast>'
           '<hourlyForecast dateTimeUTC="202610141400"><temperature>2</temperature></hourlyForecast></hourlyForecastGroup></siteData>')
    h = _extras(xml.encode())["hourly"]
    assert [r["temp_c"] for r in h] == [2.0]


def test_a_trace_amount_keeps_its_flag_and_an_absent_amount_stays_none():
    xml = ("<siteData><forecastGroup>" + _issue_xml("forecastIssue") + "</forecastGroup>"
           '<yesterdayConditions><temperature class="high">5</temperature><precip trace="true">0</precip></yesterdayConditions></siteData>')
    y = _extras(xml.encode())["yesterday"]
    assert (y["precip_mm"], y["precip_trace"]) == (0.0, True)
    assert (y["rain_mm"], y["rain_trace"], y["snow_cm"]) == (None, None, None)


def test_yesterday_without_any_issue_date_is_none_not_a_guessed_date():
    xml = '<siteData><yesterdayConditions><temperature class="high">5</temperature></yesterdayConditions></siteData>'
    assert _extras(xml.encode())["yesterday"] is None


def test_sun_needs_both_sunrise_and_sunset():
    xml = ('<siteData><riseSet><dateTime name="sunrise" zone="UTC"><timeStamp>20261014135800</timeStamp></dateTime></riseSet></siteData>')
    assert _extras(xml.encode())["sun"] is None


# ---- storage (fake engine) ---------------------------------------------------------------------------------------------------------------------------
sa = pytest.importorskip("sqlalchemy", reason="sqlalchemy is not installed: the storage tests did NOT run")
from ingest.weather import citypage  # noqa: E402


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Conn:
    def __init__(self, eng):
        self.eng = eng

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.eng.log.append((sql, params))
        if any(t in sql for t in self.eng.fail_on):
            raise RuntimeError("relation does not exist (migration 105 not applied)")
        if sql.lstrip().startswith("SELECT site_code, source_prov"):
            return _Result([{"site_code": "s0000047", "source_prov": "AB"}])
        return _Result([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeEngine:
    def __init__(self, fail_on=()):
        self.log, self.fail_on = [], tuple(fail_on)

    def begin(self):
        return _Conn(self)

    def statements(self):
        return [s for s, _ in self.log]


def _stats():
    return {"hourly_rows": 0, "normals": 0, "yesterday": 0, "sun": 0, "extras_error": 0}


def test_store_extras_writes_each_section_to_its_own_table_and_counts_them():
    eng, st = FakeEngine(), _stats()
    _, _, fcs = cp.parse_document(FIXTURE, "fx.xml")
    citypage._store_extras(eng, "s0000047", FIXTURE, "fx.xml", fcs, st)
    sql = "\n".join(eng.statements())
    for table in ("aurora_city_hourly", "aurora_city_normals", "aurora_city_yesterday", "aurora_city_sun"):
        assert f"wtf.{table}" in sql
    assert "UPDATE wtf.aurora_city_forecast SET icon_code" in sql
    assert (st["hourly_rows"], st["normals"], st["yesterday"], st["sun"], st["extras_error"]) == (24, 1, 1, 1, 0)


def test_the_forecast_update_backfills_uv_category_only_where_it_is_empty():
    """An issue stored before the parser fix keeps a NULL uv_category (the core insert is ON CONFLICT DO NOTHING); the guarded UPDATE fills it, and COALESCE
    guarantees a stored value is never overwritten."""
    eng = FakeEngine()
    _, _, fcs = cp.parse_document(FIXTURE, "fx.xml")
    citypage._update_forecast_extras(eng, "s0000047", fcs)
    sql, params = eng.log[0]
    assert "uv_category = COALESCE(uv_category, :uv_category)" in sql
    assert params[0]["uv_category"] == "low" and params[1]["uv_category"] is None  # period 0 has a UV block, period 1 (night) does not
    assert len(params) == 13


def test_a_missing_migration_costs_the_new_data_only_and_never_raises():
    eng, st = FakeEngine(fail_on=("aurora_city_hourly", "aurora_city_normals", "aurora_city_yesterday", "aurora_city_sun", "SET icon_code")), _stats()
    _, _, fcs = cp.parse_document(FIXTURE, "fx.xml")
    citypage._store_extras(eng, "s0000047", FIXTURE, "fx.xml", fcs, st)  # must not raise
    assert st["extras_error"] == 5 and st["hourly_rows"] == 0


def test_a_broken_document_is_counted_not_raised():
    st = _stats()
    citypage._store_extras(FakeEngine(), "s0000047", b"<not xml", "bad.xml", [], st)
    assert st["extras_error"] == 1


def test_the_core_forecast_insert_does_not_depend_on_migration_105():
    cols = [c.strip() for c in citypage._FCST_COLS.split(",")]
    assert not {"icon_code", "humidex", "rel_humidity_pct"} & set(cols), "the existing feed must keep working before the migration is applied"
    assert "uv_category" in cols


def test_prune_is_bounded_and_never_raises():
    eng, st = FakeEngine(), _stats()
    citypage._prune_hourly(eng, st)
    assert "DELETE FROM wtf.aurora_city_hourly WHERE issued_utc < now() - interval '3 days'" in eng.statements()[0]
    citypage._prune_hourly(FakeEngine(fail_on=("aurora_city_hourly",)), st)  # must not raise


def _run(monkeypatch, eng, dry_run):
    monkeypatch.setattr(citypage, "_newest_file_for", lambda prov, code, now: ("http://x/f.xml", "f.xml"))
    monkeypatch.setattr(citypage, "_fetch", lambda url: (200, FIXTURE))
    return citypage._run_obs_and_forecasts(eng, dry_run)


def test_a_dry_run_writes_nothing_not_even_the_prune(monkeypatch):
    eng = FakeEngine()
    stats = _run(monkeypatch, eng, dry_run=True)
    assert stats["fetched"] == 1
    assert not [s for s in eng.statements() if s.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))]


def test_a_real_run_stores_everything_and_prunes_last(monkeypatch):
    eng = FakeEngine()
    stats = _run(monkeypatch, eng, dry_run=False)
    assert (stats["hourly_rows"], stats["normals"], stats["yesterday"], stats["sun"], stats["extras_error"]) == (24, 1, 1, 1, 0)
    sql = eng.statements()
    assert sql[-1].lstrip().startswith("DELETE FROM wtf.aurora_city_hourly")
    assert any("INSERT INTO wtf.aurora_city_forecast" in s for s in sql) and any("INSERT INTO wtf.aurora_city_obs" in s for s in sql)


def test_the_existing_feed_still_runs_when_every_new_table_is_missing(monkeypatch):
    eng = FakeEngine(fail_on=("aurora_city_hourly", "aurora_city_normals", "aurora_city_yesterday", "aurora_city_sun", "SET icon_code"))
    stats = _run(monkeypatch, eng, dry_run=False)
    assert stats["forecast_rows"] == 13 and stats["upserted"] == 1 and stats["extras_error"] == 5
    assert "error" not in stats
