"""A.U.R.O.R.A. Phase 2 — MSC Datamart city observations + forecasts.

Sibling of ingest/weather/cwfis.py (Phase 1) and follows its contract exactly:
a single never-raising entry point, a heartbeat on EVERY path including the
swallowed-error return, and task names that match drift_guard._MAX_AGE_DAYS.

ADR-001: dd.weather.gc.ca ONLY. It serves no robots.txt (404 = unrestricted).
api.weather.gc.ca/collections/*/items is disallowed by its robots.txt and
dd.alpha.weather.gc.ca is "Disallow: /". Do not repoint this at either.

PATH — every segment here was wrong in an earlier attempt, so none of it is
guesswork:
    https://dd.weather.gc.ca/{YYYYMMDD}/WXO-DD/citypage_weather/{PROV}/{HH}/
        {ts}_MSC_CitypageWeather_{site}_{en|fr}.xml
  · /citypage_weather/ at the ROOT is 404 — the root is date-partitioned.
  · omitting WXO-DD is 404.
  · there is no xml/ segment (every older MSC doc says there is).
  · the DATED path is used rather than today/ because today/ flips wholesale at
    00:00Z; a run straddling midnight would silently change which day it read.
  · filenames are millisecond-stamped and NOT constructible from the site code.
    List the hour dir and take max() — a site republishes several times an hour
    and taking the FIRST file serves a stale amendment.
"""
import datetime
import logging
import os
import re
import urllib.request

from sqlalchemy import text

from .citypage_parse import parse_document, parse_extras

logger = logging.getLogger(__name__)

_BASE = "https://dd.weather.gc.ca"
_UA = {"User-Agent": "archie-aurora/1.0 (what-the-fact.com; weather ingest)"}
_TIMEOUT = int(os.environ.get("AURORA_CITY_HTTP_TIMEOUT", "25"))
# How many hour-directories back to look for a site's newest file. A site can be
# quiet for an hour or two; 3 keeps a card alive across a short publishing gap
# without ever presenting a stale reading as fresh (the row carries its own
# observed_utc, and the layer view marks the layer stale after 3h).
_HOUR_LOOKBACK = int(os.environ.get("AURORA_CITY_HOUR_LOOKBACK", "3"))


def _fetch(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — fixed public host
        return r.status, r.read()


def _list_dir(url):
    """Filenames in an Apache autoindex listing. [] on any failure — a missing
    hour directory is normal near the top of the hour, not an error."""
    try:
        st, body = _fetch(url)
    except Exception as exc:  # noqa: BLE001 — an absent hour dir is expected
        logger.debug("citypage: listing %s failed: %s", url, exc)
        return []
    if st != 200:
        return []
    return re.findall(r'href="([^"]+\.xml)"', body.decode("utf-8", "replace"))


def _newest_file_for(prov, site_code, now_utc):
    """(url, filename) of the newest _en.xml for one site, or (None, None).

    Walks back at most _HOUR_LOOKBACK hours and takes max() within the first
    hour that has the site — filenames sort lexicographically by timestamp, and
    max(filename) implies max(observation) (verified 8/8 across multi-publish
    sites).
    """
    for back in range(_HOUR_LOOKBACK):
        t = now_utc - datetime.timedelta(hours=back)
        base = "%s/%s/WXO-DD/citypage_weather/%s/%02d/" % (
            _BASE, t.strftime("%Y%m%d"), prov, t.hour)
        names = [n for n in _list_dir(base) if n.endswith("_%s_en.xml" % site_code)]
        if names:
            return base + max(names), max(names)
    return None, None


_OBS_COLS = (
    "site_code, observed_utc, observed_local_ts, local_zone, local_utc_offset, "
    "station_code, station_name, station_lat, station_lon, condition_text, icon_code, "
    "temp_c, dewpoint_c, rel_humidity_pct, humidex, wind_chill, pressure_kpa, "
    "pressure_change_kpa, pressure_tendency, visibility_km, wind_speed_kmh, "
    "wind_is_calm, wind_gust_kmh, wind_dir, wind_bearing_deg, source_file"
)
_FCST_COLS = (
    "site_code, issued_utc, period_index, period_label, period_weekday, temp_high_c, "
    "temp_low_c, text_summary, abbrev_summary, pop_pct, wind_summary, wind_gust_kmh, "
    "uv_index, uv_category, source_file"
)


# The sections added by migration 105 (Dev HQ 7234). Written by guarded helpers, never by the core insert above, so applying the migration late
# costs the new data only and can never break the existing observation / forecast feed.
_HOURLY_COLS = (
    "site_code, issued_utc, hour_utc, condition, icon_code, temp_c, lop_pct, lop_category, wind_speed_kmh, "
    "wind_is_calm, wind_dir, wind_gust_kmh, wind_chill, humidex, source_file"
)
_HOURLY_RETENTION = "3 days"


def run_aurora_citypage(engine, dry_run=False):
    """Entry point. NEVER raises — returns a per-task summary dict.

    Mirrors cwfis.run_aurora_cwfis: one layer failing must not take the other
    down, and every outcome (including a swallowed {"error": ...}) writes a
    heartbeat.
    """
    out = {}
    for task, fn in (("aurora_city_obs", _run_obs_and_forecasts),):
        try:
            res = fn(engine, dry_run)
            out[task] = res
            if not dry_run:
                _heartbeat(engine, task, res, None)
                # The forecast half is a SEPARATE drift_guard task, so it needs
                # its own heartbeat — one row cannot certify two layers.
                _heartbeat(engine, "aurora_city_forecast",
                           {"fetched": res.get("forecast_rows", 0),
                            "upserted": res.get("forecast_rows", 0),
                            "error": res.get("error")}, None)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s crashed", task)
            out[task] = {"error": str(exc)}
            if not dry_run:
                _heartbeat(engine, task, {}, exc)
                _heartbeat(engine, "aurora_city_forecast", {}, exc)
    return out


def _run_obs_and_forecasts(engine, dry_run):
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as c:
        sites = c.execute(text(
            "SELECT site_code, source_prov FROM wtf.aurora_city_site "
            "WHERE is_city ORDER BY sort_order, site_code")).mappings().all()
    if not sites:
        return {"error": "no cities in wtf.aurora_city_site — migration 055 not applied?"}

    stats = {"sites": len(sites), "fetched": 0, "upserted": 0, "forecast_rows": 0,
             "no_observations": 0, "fetch_error": 0, "parse_error": 0,
             "hourly_rows": 0, "normals": 0, "yesterday": 0, "sun": 0, "extras_error": 0}

    for s in sites:
        code, prov = s["site_code"], s["source_prov"]
        url, fname = _newest_file_for(prov, code, now)
        if not url:
            stats["fetch_error"] += 1
            if not dry_run:
                _mark_site(engine, code, "fetch_error", None, None, None)
            continue
        try:
            st, raw = _fetch(url)
            if st != 200:
                raise OSError("HTTP %s" % st)
            meta, cur, fcs = parse_document(raw, fname)
            stats["fetched"] += 1
        except Exception as exc:  # noqa: BLE001 — one bad site must not stop the run
            logger.warning("citypage: %s parse/fetch failed: %s", code, exc)
            stats["parse_error"] += 1
            if not dry_run:
                _mark_site(engine, code, "parse_error", None, None, None)
            continue

        if dry_run:
            continue

        if cur is None:
            # MSC published the file but no observations. That is a DIFFERENT
            # fact from "we could not reach the source", and the page says so.
            stats["no_observations"] += 1
            _mark_site(engine, code, "no_observations", now, meta.get("lat"), meta.get("lon"))
        else:
            _upsert_obs(engine, code, cur)
            stats["upserted"] += 1
            _mark_site(engine, code, "ok", now, meta.get("lat"), meta.get("lon"))

        if fcs:
            stats["forecast_rows"] += _upsert_forecasts(engine, code, fcs)

        _store_extras(engine, code, raw, fname, fcs, stats)

    if not dry_run:
        _prune_hourly(engine, stats)
    if stats["extras_error"]:
        logger.warning("citypage: %d extras write/parse failure(s) this run (is migration 105 applied on this database?)", stats["extras_error"])
    return stats


def _store_extras(engine, code, raw, fname, fcs, stats):
    """Parse and store the hourly / normals / yesterday / sun sections and the new forecast-period fields.

    EVERY step is guarded on its own: a failure here (migration 105 not applied yet, an unexpected element) is counted and logged but NEVER raises, so
    the observation and forecast that were just stored are untouched and the remaining sites still run.
    """
    try:
        extras = parse_extras(raw, fname)
    except Exception as exc:  # noqa: BLE001
        logger.warning("citypage: %s extras parse failed: %s", code, exc)
        stats["extras_error"] += 1
        return
    steps = (
        ("hourly_rows", lambda: _upsert_hourly(engine, code, extras["hourly"])),
        ("normals", lambda: _upsert_normals(engine, code, extras["normals"])),
        ("yesterday", lambda: _upsert_yesterday(engine, code, extras["yesterday"])),
        ("sun", lambda: _upsert_sun(engine, code, extras["sun"])),
        (None, lambda: _update_forecast_extras(engine, code, fcs)),
    )
    for key, fn in steps:
        try:
            n = fn()
            if key:
                stats[key] += int(n or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("citypage: %s extras write (%s) failed: %s", code, key or "forecast_extras", exc)
            stats["extras_error"] += 1


def _upsert_hourly(engine, code, rows):
    if not rows:
        return 0
    cols = [c.strip() for c in _HOURLY_COLS.split(",")]
    stmt = text("INSERT INTO wtf.aurora_city_hourly (%s) VALUES (%s) ON CONFLICT (site_code, issued_utc, hour_utc) DO NOTHING"
                % (", ".join(cols), ", ".join(":" + k for k in cols)))
    with engine.begin() as c:
        c.execute(stmt, [dict(r, site_code=code) for r in rows])
    return len(rows)


def _upsert_normals(engine, code, row):
    if not row:
        return 0
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO wtf.aurora_city_normals (site_code, issued_utc, normal_high_c, normal_low_c, text_summary, source_file) "
            "VALUES (:site_code, :issued_utc, :normal_high_c, :normal_low_c, :text_summary, :source_file) "
            "ON CONFLICT (site_code) DO UPDATE SET issued_utc = EXCLUDED.issued_utc, normal_high_c = EXCLUDED.normal_high_c, "
            "normal_low_c = EXCLUDED.normal_low_c, text_summary = EXCLUDED.text_summary, source_file = EXCLUDED.source_file, fetched_at = now() "
            "WHERE EXCLUDED.issued_utc >= wtf.aurora_city_normals.issued_utc"), dict(row, site_code=code))
    return 1


def _upsert_yesterday(engine, code, row):
    if not row:
        return 0
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO wtf.aurora_city_yesterday (site_code, obs_date, high_c, low_c, precip_mm, precip_trace, rain_mm, rain_trace, snow_cm, snow_trace, "
            "gust_kmh, gust_bearing_deg, gust_dir, source_file) VALUES (:site_code, :obs_date, :high_c, :low_c, :precip_mm, :precip_trace, :rain_mm, "
            ":rain_trace, :snow_cm, :snow_trace, :gust_kmh, :gust_bearing_deg, :gust_dir, :source_file) "
            "ON CONFLICT (site_code, obs_date) DO UPDATE SET high_c = EXCLUDED.high_c, low_c = EXCLUDED.low_c, precip_mm = EXCLUDED.precip_mm, "
            "precip_trace = EXCLUDED.precip_trace, rain_mm = EXCLUDED.rain_mm, rain_trace = EXCLUDED.rain_trace, snow_cm = EXCLUDED.snow_cm, "
            "snow_trace = EXCLUDED.snow_trace, gust_kmh = EXCLUDED.gust_kmh, gust_bearing_deg = EXCLUDED.gust_bearing_deg, "
            "gust_dir = EXCLUDED.gust_dir, source_file = EXCLUDED.source_file, fetched_at = now()"), dict(row, site_code=code))
    return 1


def _upsert_sun(engine, code, row):
    if not row:
        return 0
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO wtf.aurora_city_sun (site_code, sun_date, sunrise_utc, sunset_utc, source_file) "
            "VALUES (:site_code, :sun_date, :sunrise_utc, :sunset_utc, :source_file) "
            "ON CONFLICT (site_code, sun_date) DO UPDATE SET sunrise_utc = EXCLUDED.sunrise_utc, sunset_utc = EXCLUDED.sunset_utc, "
            "source_file = EXCLUDED.source_file, fetched_at = now()"), dict(row, site_code=code))
    return 1


def _update_forecast_extras(engine, code, fcs):
    """icon_code / humidex / rel_humidity_pct on the forecast periods just stored. A separate UPDATE (not part of the core insert) so these three
    columns, which exist only after migration 105, can never break the forecast feed itself."""
    if not fcs:
        return 0
    stmt = text("UPDATE wtf.aurora_city_forecast SET icon_code = :icon_code, humidex = :humidex, rel_humidity_pct = :rel_humidity_pct "
                "WHERE site_code = :site_code AND issued_utc = :issued_utc AND period_index = :period_index")
    with engine.begin() as c:
        c.execute(stmt, [{"site_code": code, "issued_utc": r["issued_utc"], "period_index": r["period_index"], "icon_code": r.get("icon_code"),
                          "humidex": r.get("humidex"), "rel_humidity_pct": r.get("rel_humidity_pct")} for r in fcs])
    return len(fcs)


def _prune_hourly(engine, stats):
    """The hourly forecast is only ever read for the latest issue, so rows older than the retention window are dropped each run (bounded growth)."""
    try:
        with engine.begin() as c:
            c.execute(text("DELETE FROM wtf.aurora_city_hourly WHERE issued_utc < now() - interval '%s'" % _HOURLY_RETENTION))
    except Exception as exc:  # noqa: BLE001 — pruning must never fail the run
        logger.warning("citypage: hourly prune failed: %s", exc)


def _mark_site(engine, code, status, seen, lat, lon):
    with engine.begin() as c:
        c.execute(text(
            "UPDATE wtf.aurora_city_site SET last_obs_status=:s, "
            "last_seen_utc = COALESCE(:seen, last_seen_utc), "
            "lat = COALESCE(:lat, lat), lon = COALESCE(:lon, lon), fetched_at = now() "
            "WHERE site_code = :c"),
            {"s": status, "seen": seen, "lat": lat, "lon": lon, "c": code})


def _upsert_obs(engine, code, row):
    row = dict(row)
    row["site_code"] = code
    cols = [c.strip() for c in _OBS_COLS.split(",")]
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO wtf.aurora_city_obs (%s) VALUES (%s) "
            "ON CONFLICT (site_code, observed_utc) DO NOTHING"
            % (", ".join(cols), ", ".join(":" + k for k in cols))), row)


def _upsert_forecasts(engine, code, rows):
    cols = [c.strip() for c in _FCST_COLS.split(",")]
    stmt = text("INSERT INTO wtf.aurora_city_forecast (%s) VALUES (%s) "
                "ON CONFLICT (site_code, issued_utc, period_index) DO NOTHING"
                % (", ".join(cols), ", ".join(":" + k for k in cols)))
    n = 0
    with engine.begin() as c:
        for r in rows:
            r = dict(r)
            r["site_code"] = code
            r.setdefault("wind_summary", None)
            c.execute(stmt, r)
            n += 1
    return n


def _heartbeat(engine, task, result, exc):
    """parliament.ingest_log on BOTH paths — including a SWALLOWED
    {"error": ...} return, which is how lobbying and ethics rotted for months
    while every dashboard stayed green."""
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES (:t, :f, :u)"),
                    {"t": task,
                     "f": int(result.get("fetched") or 0),
                     "u": int(result.get("upserted") or 0)})
            else:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:  # noqa: BLE001 — a heartbeat must never break the ingest
        logger.exception("citypage: heartbeat write failed for %s", task)


if __name__ == "__main__":
    import sys
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["WTF_DATABASE_URL"])
    print(run_aurora_citypage(eng, dry_run="--dry-run" in sys.argv))
