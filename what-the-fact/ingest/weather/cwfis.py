"""cwfis.py — A.U.R.O.R.A. Phase 1: wildfire + fire-weather from CWFIS (NRCan).

Three layers, all from the CWFIS GeoServer WFS as plain GeoJSON — stdlib only,
no API key, and deliberately NO GRIB/GDAL dependency (wind arrives as ordinary
numbers on the fire-weather stations, so the heavy geospatial stack buys us
nothing here):

  public:firewx_stns_current  — fire-weather stations. Carries ws / wg / wdir
        (wind speed, gust, direction) plus the full Canadian Fire Weather Index
        component set. THIS IS THE WIND LAYER.
  public:hotspots_last24hrs   — satellite hotspot detections. ~10k features and
        it spans the US and Mexico, so it is rolled up to a Canadian
        per-province daily row on ingest rather than stored raw.
  public:m3_polygons_current  — active fire perimeters. Thin attributes
        (hcount/firstdate/lastdate/area) with NO province or fire name, so we
        store a national daily summary and do not invent per-fire identity the
        source does not publish.

SOURCE GOVERNANCE (ADR-001, owner decision 2026-08-18): CWFIS is used because
its robots.txt is a bare "Disallow:" (allow-all, verified first-hand).
api.weather.gc.ca is deliberately NOT called — its robots.txt disallows
/collections/*/items. Do not repoint this module at GeoMet.

Run: python -m ingest.weather.cwfis [--dry-run]
"""
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.aurora.cwfis")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_WFS = "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs"
_HEADERS = {
    "User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)",
    "Accept": "application/json",
}
_TIMEOUT = 120

# CWFIS is a Canadian system but its layers carry FOREIGN stations and
# detections too (US border coverage feeds the fire-weather models). A page
# whose premise is "Canada first" must exclude them.
#
# hotspots_last24hrs puts the jurisdiction in `agency`, mixing CA provinces
# with US and Mexican state codes.
_CA_PROV = {"AB", "BC", "MB", "NB", "NL", "NF", "NS", "NT", "NU", "ON", "PE", "QC", "SK",
            "YT", "PC"}   # NF = Newfoundland's legacy code, still emitted by CWFIS
                          # PC = Parks Canada
# firewx_stns_current is DENYLISTED instead, deliberately: it reports the
# operating agency (MSC / DNR / NL-DFF / NS-DLF / NWS ...), and CWFIS is
# Canadian by default, so "keep unless proven foreign" avoids silently dropping
# a provincial agency whose code we have not seen yet (BC/AB/SK stations are
# absent from the feed at some hours, so an allowlist could not be verified).
# Measured 2026-08-18: NWS accounted for exactly the 177 non-Canadian stations,
# and 19 Canadian MSC stations carry a BLANK prov — which is why this filters on
# agency, not province.
_FOREIGN_AGENCIES = {"NWS"}
_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND",
    "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY",
}


def _fetch(layer: str, extra: str = "") -> dict:
    qs = urllib.parse.urlencode({
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "outputFormat": "application/json", "typeName": layer,
    })
    req = urllib.request.Request(f"{_WFS}?{qs}{extra}", headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _clean(value):
    """CWFIS pads and mangles text: names arrive as
    '                    ST.+PETERS' and agencies as 'MSC   '."""
    if not isinstance(value, str):
        return value
    return re.sub(r"\s+", " ", value.replace("+", " ")).strip() or None


def _num(value):
    """Numbers arrive as strings, blanks, or sentinel dashes."""
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def run_firewx_sync(engine, dry_run: bool = False) -> dict:
    """Fire-weather stations → wtf.aurora_firewx_obs (the wind layer)."""
    try:
        data = _fetch("public:firewx_stns_current")
    except Exception as exc:
        return {"error": f"firewx fetch failed: {exc}"}

    feats = data.get("features") or []
    if not feats:
        return {"error": "firewx returned 0 features — layer renamed or WFS changed?"}

    rows, skipped, foreign = [], 0, 0
    foreign_by_agency = defaultdict(int)
    for f in feats:
        p = f.get("properties") or {}
        # wmo is the stable identifier; aes is the fallback for stations without one.
        key = str(p.get("wmo") or p.get("aes") or "").strip()
        rep = _ts(p.get("rep_date"))
        if not key or rep is None:
            skipped += 1
            continue
        agency = (_clean(p.get("agency")) or "").upper()
        prov_code = (_clean(p.get("prov")) or "").upper()
        if agency in _FOREIGN_AGENCIES or prov_code in _US_STATE_CODES:
            foreign += 1
            foreign_by_agency[agency or prov_code or "?"] += 1
            continue
        rows.append({
            "k": key, "n": _clean(p.get("name")), "pv": _clean(p.get("prov")),
            "ag": _clean(p.get("agency")), "la": _num(p.get("lat")), "lo": _num(p.get("lon")),
            "rd": rep, "t": _num(p.get("temp")), "rh": _num(p.get("rh")),
            "ws": _num(p.get("ws")), "wg": _num(p.get("wg")), "wd": _num(p.get("wdir")),
            "pr": _num(p.get("precip")), "ps": _num(p.get("pres")), "vi": _num(p.get("vis")),
            "ffmc": _num(p.get("ffmc")), "dmc": _num(p.get("dmc")), "dc": _num(p.get("dc")),
            "isi": _num(p.get("isi")), "bui": _num(p.get("bui")), "fwi": _num(p.get("fwi")),
            "dsr": _num(p.get("dsr")),
        })

    # Surface key collisions rather than letting ON CONFLICT swallow them:
    # 9 of 571 stations shared a wmo/aes id on the first live run (1.6%). A
    # silent collapse is the exact shape of defect this project keeps finding.
    dupes = len(rows) - len({r["k"] for r in rows})
    result = {"fetched": len(feats), "parsed": len(rows), "skipped": skipped,
              "foreign_skipped": foreign, "foreign_by_agency": dict(foreign_by_agency),
              "duplicate_station_keys": dupes}
    if dry_run:
        logger.info("firewx DRY RUN: %s", result)
        return result

    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO wtf.aurora_firewx_obs
                (station_key, station_name, prov, agency, lat, lon, rep_date,
                 temp_c, rel_humidity, wind_speed_kmh, wind_gust_kmh, wind_dir_deg,
                 precip_mm, pressure_kpa, visibility_km,
                 ffmc, dmc, dc, isi, bui, fwi, dsr, fetched_at)
            VALUES (:k, :n, :pv, :ag, :la, :lo, :rd,
                    :t, :rh, :ws, :wg, :wd, :pr, :ps, :vi,
                    :ffmc, :dmc, :dc, :isi, :bui, :fwi, :dsr, now())
            ON CONFLICT (station_key, rep_date) DO UPDATE SET
                temp_c = EXCLUDED.temp_c, rel_humidity = EXCLUDED.rel_humidity,
                wind_speed_kmh = EXCLUDED.wind_speed_kmh,
                wind_gust_kmh = EXCLUDED.wind_gust_kmh,
                wind_dir_deg = EXCLUDED.wind_dir_deg,
                fwi = EXCLUDED.fwi, fetched_at = now()
        """), rows)
    result["upserted"] = len(rows)
    logger.info("firewx: %s", result)
    return result


def run_fire_sync(engine, dry_run: bool = False) -> dict:
    """Hotspots (rolled up per province) + perimeter summary."""
    out = {}

    # ── hotspots ─────────────────────────────────────────────────────────────
    try:
        hs = _fetch("public:hotspots_last24hrs",
                    "&propertyName=agency,rep_date,fwi,frp,fuel")
    except Exception as exc:
        return {"error": f"hotspots fetch failed: {exc}"}
    feats = hs.get("features") or []
    if not feats:
        return {"error": "hotspots returned 0 features — layer renamed or WFS changed?"}

    buckets = defaultdict(list)
    foreign = 0
    for f in feats:
        p = f.get("properties") or {}
        prov = (_clean(p.get("agency")) or "").upper()
        if prov not in _CA_PROV:      # US/MX detections share this layer
            foreign += 1
            continue
        rep = _ts(p.get("rep_date"))
        buckets[(rep.date() if rep else None, prov)].append(p)

    rows = []
    for (obs_date, prov), items in buckets.items():
        if obs_date is None:
            continue
        fwis = [v for v in (_num(i.get("fwi")) for i in items) if v is not None]
        frps = [v for v in (_num(i.get("frp")) for i in items) if v is not None]
        fuels = [_clean(i.get("fuel")) for i in items if _clean(i.get("fuel"))]
        rows.append({
            "d": obs_date, "p": prov, "n": len(items),
            "mx": max(fwis) if fwis else None,
            "mf": (sum(frps) / len(frps)) if frps else None,
            "fu": max(set(fuels), key=fuels.count) if fuels else None,
        })

    out.update({"hotspots_fetched": len(feats), "hotspots_foreign_skipped": foreign,
                "provinces": len(rows)})

    # ── perimeters ───────────────────────────────────────────────────────────
    try:
        pm = _fetch("public:m3_polygons_current",
                    "&propertyName=hcount,firstdate,lastdate,area")
    except Exception as exc:
        return {"error": f"perimeters fetch failed: {exc}"}
    pfeats = pm.get("features") or []
    areas = [v for v in (_num((f.get("properties") or {}).get("area")) for f in pfeats)
             if v is not None]
    starts = [t for t in (_ts((f.get("properties") or {}).get("firstdate")) for f in pfeats)
              if t is not None]
    out["perimeters"] = len(pfeats)

    if dry_run:
        logger.info("fire DRY RUN: %s", out)
        return out

    today = datetime.now(timezone.utc).date()
    with engine.begin() as c:
        if rows:
            c.execute(text("""
                INSERT INTO wtf.aurora_fire_hotspot_daily
                    (obs_date, prov, hotspot_count, max_fwi, mean_frp, dominant_fuel, fetched_at)
                VALUES (:d, :p, :n, :mx, :mf, :fu, now())
                ON CONFLICT (obs_date, prov) DO UPDATE SET
                    hotspot_count = EXCLUDED.hotspot_count,
                    max_fwi = EXCLUDED.max_fwi, mean_frp = EXCLUDED.mean_frp,
                    dominant_fuel = EXCLUDED.dominant_fuel, fetched_at = now()
            """), rows)
        c.execute(text("""
            INSERT INTO wtf.aurora_fire_perimeters
                (snapshot_date, perimeter_count, total_area, max_area, earliest_start, fetched_at)
            VALUES (:d, :n, :ta, :ma, :es, now())
            ON CONFLICT (snapshot_date) DO UPDATE SET
                perimeter_count = EXCLUDED.perimeter_count,
                total_area = EXCLUDED.total_area, max_area = EXCLUDED.max_area,
                earliest_start = EXCLUDED.earliest_start, fetched_at = now()
        """), {"d": today, "n": len(pfeats),
               "ta": sum(areas) if areas else None,
               "ma": max(areas) if areas else None,
               "es": min(starts) if starts else None})
    logger.info("fire: %s", out)
    return out


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log row on BOTH paths — including a SWALLOWED
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
                     "f": int(result.get("fetched") or result.get("hotspots_fetched") or 0),
                     "u": int(result.get("upserted") or result.get("provinces") or 0)})
            else:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:
        logger.exception("%s heartbeat write failed", task)


def run_aurora_cwfis(engine, dry_run: bool = False) -> dict:
    """Both layers + heartbeats. Never raises — a dead layer must alarm via the
    heartbeat, not take the whole ingest loop down with it."""
    out = {}
    for task, fn in (("aurora_firewx", run_firewx_sync), ("aurora_fire", run_fire_sync)):
        try:
            res = fn(engine, dry_run=dry_run)
            out[task] = res
            if not dry_run:
                _heartbeat(engine, task, res, None)
        except Exception as exc:            # noqa: BLE001 — one layer must not kill the other
            logger.exception("%s crashed", task)
            out[task] = {"error": str(exc)}
            if not dry_run:
                _heartbeat(engine, task, {}, exc)
    return out


if __name__ == "__main__":
    import sys
    eng = create_engine(os.environ["WTF_DATABASE_URL"])
    print(run_aurora_cwfis(eng, dry_run="--dry-run" in sys.argv))
