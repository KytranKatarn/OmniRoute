"""A.U.R.O.R.A. — AQHI (Air Quality Health Index) observations.

Sibling of ingest/weather/citypage.py, same contract: a single never-raising
entry point, a heartbeat on EVERY path including the swallowed-error return,
and a task name that matches drift_guard._MAX_AGE_DAYS.

ADR-001: dd.weather.gc.ca ONLY (same host as citypage/cwfis).

PATH — verified live 2026-09-06 (Dev HQ #6621 item 5):
    https://dd.weather.gc.ca/{YYYYMMDD}/WXO-DD/air_quality/aqhi/{region}/
        observation/realtime/json/{ts}_MSC_AQHI-Observation_{location_id}.json
  · {region} is one of 5 meteorological super-regions (atl, ont, pnr, pyr,
    que) — NOT a province code. The observation payload itself carries no
    province field at all, so no province is assigned here; a station is
    plotted by lat/lon only, same as this codebase already does for the
    19 fire-weather stations that have coordinates but no attributable
    province (see consumer/aurora_map.py's _canon_prov docstring — the same
    "plot it, don't guess the attribution" principle applies here).
  · Same dated-directory reasoning as citypage: filenames are timestamped and
    a region publishes many stations per file-listing, so list the dir and
    take the newest file PER STATION (a station can appear in more than one
    timestamped batch within the lookback window).
  · Payload is GeoJSON (Feature/geometry/properties), not XML — genuinely
    simpler to parse than citypage's format.
"""
import datetime
import json
import logging
import os
import re
import urllib.request

from sqlalchemy import text

logger = logging.getLogger(__name__)

_BASE = "https://dd.weather.gc.ca"
_UA = {"User-Agent": "archie-aurora/1.0 (what-the-fact.com; weather ingest)"}
_TIMEOUT = int(os.environ.get("AURORA_AQHI_HTTP_TIMEOUT", "25"))
_REGIONS = ("atl", "ont", "pnr", "pyr", "que")
# AQHI observations publish roughly hourly per station; same 3h lookback as
# citypage so a station quiet for an hour or two still stays on the map
# without ever presenting a stale reading as fresh (observed_utc is stored
# per row, and staleness is judged from that at render time, not here).
_HOUR_LOOKBACK = int(os.environ.get("AURORA_AQHI_HOUR_LOOKBACK", "3"))


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
        logger.debug("aqhi: listing %s failed: %s", url, exc)
        return []
    if st != 200:
        return []
    return re.findall(r'href="([^"]+\.json)"', body.decode("utf-8", "replace"))


def _files_for_region(region, now_utc):
    """(base_url, [filenames]) across the lookback window for one region.
    Returns every filename seen — a region's dir mixes many stations per
    hour, so the caller groups by location_id and keeps the newest per
    station rather than the newest file overall."""
    seen = {}
    for back in range(_HOUR_LOOKBACK):
        # AQHI observation dirs are NOT hour-partitioned like citypage —
        # verified live: .../observation/realtime/json/ holds one flat
        # listing per region, refreshed in place. Only the DATE root
        # rolls over (at 00:00Z, same reasoning as citypage: use the dated
        # path, never today/, so a run straddling midnight reads one
        # consistent day).
        t = now_utc - datetime.timedelta(hours=back)
        base = "%s/%s/WXO-DD/air_quality/aqhi/%s/observation/realtime/json/" % (
            _BASE, t.strftime("%Y%m%d"), region)
        names = _list_dir(base)
        if names:
            return base, names
    return None, []


def _parse_one(base, fname):
    """One AQHI GeoJSON Feature -> a row dict, or None on any shape surprise.
    Never raises — a single malformed file must not stop the region."""
    try:
        st, raw = _fetch(base + fname)
        if st != 200:
            return None
        doc = json.loads(raw)
        props = doc.get("properties") or {}
        geom = doc.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        aqhi = props.get("aqhi")
        loc_id = props.get("location_id")
        obs_dt = props.get("observation_datetime")
        if not loc_id or obs_dt is None or aqhi is None:
            # A real "no reading" case (station reporting but no current
            # value) is a different fact from "we could not reach the
            # source" — skip quietly, do not fabricate a zero.
            return None
        return {
            "location_id": loc_id,
            "location_name": props.get("location_name_en"),
            "lat": coords[1] if len(coords) > 1 else None,
            "lon": coords[0] if len(coords) > 0 else None,
            "aqhi_value": float(aqhi),
            "observed_utc": obs_dt,
            "source_file": fname,
        }
    except Exception as exc:  # noqa: BLE001 — one bad file must not stop the region
        logger.debug("aqhi: parse failed for %s: %s", fname, exc)
        return None


def _run_aqhi(engine, dry_run):
    now = datetime.datetime.now(datetime.timezone.utc)
    stats = {"regions": len(_REGIONS), "fetched": 0, "upserted": 0, "parse_error": 0}
    by_station = {}  # location_id -> row, newest observed_utc wins

    for region in _REGIONS:
        base, names = _files_for_region(region, now)
        if not base:
            continue
        for fname in names:
            row = _parse_one(base, fname)
            if row is None:
                stats["parse_error"] += 1
                continue
            stats["fetched"] += 1
            row["region"] = region
            prev = by_station.get(row["location_id"])
            if prev is None or row["observed_utc"] > prev["observed_utc"]:
                by_station[row["location_id"]] = row

    if dry_run:
        stats["upserted"] = len(by_station)
        return stats

    if not by_station:
        return {"error": "no AQHI observations parsed from any region"}

    with engine.begin() as c:
        for row in by_station.values():
            result = c.execute(text("""
                INSERT INTO wtf.aurora_aqhi_obs
                    (location_id, location_name, region, lat, lon, aqhi_value,
                     observed_utc, source_file)
                VALUES (:location_id, :location_name, :region, :lat, :lon, :aqhi_value,
                        :observed_utc, :source_file)
                ON CONFLICT (location_id, observed_utc) DO NOTHING
            """), row)
            if result.rowcount > 0:
                stats["upserted"] += 1
    return stats


def _heartbeat(engine, task, result, exc):
    """parliament.ingest_log on BOTH paths — same never-silent contract as
    citypage.py/boc_rates.py (a swallowed error here is how a feed rots for
    months while every dashboard stays green)."""
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES (:t, :f, :u)"),
                    {"t": task, "f": int(result.get("fetched") or 0),
                     "u": int(result.get("upserted") or 0)})
            else:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:  # noqa: BLE001 — a heartbeat must never break the ingest
        logger.exception("aqhi: heartbeat write failed for %s", task)


def run_aurora_aqhi(engine, dry_run=False):
    """Entry point. NEVER raises — returns a per-run summary dict, same
    contract as run_aurora_citypage/run_aurora_cwfis."""
    task = "aurora_aqhi"
    try:
        res = _run_aqhi(engine, dry_run)
        if not dry_run:
            _heartbeat(engine, task, res, None)
        return res
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s crashed", task)
        if not dry_run:
            _heartbeat(engine, task, {}, exc)
        return {"error": str(exc)}


if __name__ == "__main__":
    import sys
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["WTF_DATABASE_URL"])
    print(run_aurora_aqhi(eng, dry_run="--dry-run" in sys.argv))
