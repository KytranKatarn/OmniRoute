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

from .citypage_parse import parse_document

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
             "no_observations": 0, "fetch_error": 0, "parse_error": 0}

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

    return stats


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
