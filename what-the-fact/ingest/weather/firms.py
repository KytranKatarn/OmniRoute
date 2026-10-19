"""NASA FIRMS near-real-time fire detections, retained as source evidence.

The collector is optional until NASA_FIRMS_MAP_KEY is configured. It never
labels a thermal anomaly as a confirmed fire and stores source rows verbatim.
"""

import csv
import datetime
import io
import json
import logging
import os
import urllib.parse
import urllib.request

from ingest.weather.evidence import capture_source_records, record_capture_failure
from ingest.weather.cwfis import _heartbeat

logger = logging.getLogger("wtf-ingest.aurora.firms")
_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
_TIMEOUT = int(os.environ.get("AURORA_FIRMS_HTTP_TIMEOUT", "45"))
_PRODUCTS = (
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
    "LANDSAT_NRT",
)


def _area():
    """Return validated NASA bbox string (west,south,east,north)."""
    raw = os.environ.get("AURORA_FIRMS_AREA", "-141,41,-52,84")
    parts = raw.split(",")
    if len(parts) != 4:
        raise ValueError("AURORA_FIRMS_AREA must be west,south,east,north")
    values = [float(part.strip()) for part in parts]
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("AURORA_FIRMS_AREA has invalid coordinate bounds")
    return ",".join(str(value) for value in values)


def _fetch_product(product, area, map_key):
    # MAP_KEY is required in the request path; it is never returned, logged,
    # stored in source_url, or included in exception messages.
    encoded_area = urllib.parse.quote(area, safe=",")
    url = "%s/%s/%s/%s/1" % (
        _API,
        urllib.parse.quote(map_key, safe=""),
        product,
        encoded_area,
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WTFIngest/1.0 (A.U.R.O.R.A. fire evidence)",
            "Accept": "text/csv",
        },
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 — fixed NASA host
            req, timeout=_TIMEOUT
        ) as response:
            return response.read().decode("utf-8-sig", "replace")
    except Exception as exc:  # noqa: BLE001 — redact credential-bearing URL
        raise RuntimeError(
            "NASA FIRMS request failed for %s: %s"
            % (product, type(exc).__name__)
        ) from None


def _observed_at(row):
    date = row.get("acq_date") or row.get("ACQ_DATE")
    time = row.get("acq_time") or row.get("ACQ_TIME")
    if not date or time is None:
        return None
    try:
        hhmm = str(time).strip().zfill(4)
        parsed = datetime.datetime.strptime(
            "%s %s" % (date, hhmm), "%Y-%m-%d %H%M"
        )
        return parsed.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def parse_csv_records(product, body):
    """CSV rows -> evidence records; preserve every source-native column."""
    reader = csv.DictReader(io.StringIO(body))
    records = []
    for row in reader:
        if not row or not any(
            value not in (None, "") for value in row.values()
        ):
            continue
        normalized = {
            str(key): value for key, value in row.items() if key is not None
        }
        native_id = normalized.get("id") or normalized.get("ID")
        lat = normalized.get("latitude") or normalized.get("LATITUDE")
        lon = normalized.get("longitude") or normalized.get("LONGITUDE")
        date = normalized.get("acq_date") or normalized.get("ACQ_DATE")
        time = normalized.get("acq_time") or normalized.get("ACQ_TIME")
        stable_id = native_id or "|".join(
            str(value or "") for value in (product, lat, lon, date, time)
        )
        records.append(
            {
                "source_record_key": str(stable_id),
                "source_observed_at": _observed_at(normalized),
                # Acquisition time is not publication time; leave it unknown.
                "payload": {
                    "product": product,
                    "detection": normalized,
                    "evidence_class": "satellite_thermal_anomaly",
                },
                "raw_payload": json.dumps(
                    normalized, sort_keys=False, separators=(",", ":")
                ),
            }
        )
    return records


def run_firms_capture(engine, *, dry_run=False, map_key=None):
    """Capture current products; missing key is an explicit disabled state."""
    map_key = map_key or os.environ.get("NASA_FIRMS_MAP_KEY")
    if not map_key:
        return {
            "disabled": True,
            "reason": "NASA_FIRMS_MAP_KEY is not configured",
        }
    started_at = datetime.datetime.now(datetime.timezone.utc)
    area = _area()
    total = 0
    captures = []
    per_product = {}
    for product in _PRODUCTS:
        body = _fetch_product(product, area, map_key)
        records = parse_csv_records(product, body)
        per_product[product] = len(records)
        total += len(records)
        captures.extend(records)
    result = {
        "products": len(_PRODUCTS),
        "fetched": total,
        "by_product": per_product,
    }
    if dry_run:
        return result
    safe_url = "%s/[MAP_KEY_REDACTED]/<product>/%s/1" % (_API, area)
    for record in captures:
        record["source_url"] = "%s/[MAP_KEY_REDACTED]/%s/%s/1" % (
            _API,
            record["payload"]["product"],
            area,
        )
    with engine.begin() as conn:
        capture_stats = capture_source_records(
            conn,
            dataset_key="nasa_firms_point",
            source_url=safe_url,
            started_at=started_at,
            rows=captures,
        )
    result["upserted"] = capture_stats["inserted_versions"]
    return result


def run_aurora_firms_capture(engine, *, dry_run=False):
    """Scheduled fail-loud wrapper; skip heartbeat while source is disabled."""
    started_at = datetime.datetime.now(datetime.timezone.utc)
    try:
        result = run_firms_capture(engine, dry_run=dry_run)
        if not dry_run and not result.get("disabled"):
            if result.get("error"):
                try:
                    with engine.begin() as conn:
                        record_capture_failure(
                            conn, dataset_key="nasa_firms_point",
                            source_url="%s/[MAP_KEY_REDACTED]/<product>/<area>/1" % _API,
                            started_at=started_at,
                        )
                except Exception:  # noqa: BLE001 — heartbeat still records failure
                    logger.exception("aurora_firms failed run could not be persisted")
            _heartbeat(engine, "aurora_firms", result, None)
        return result
    except Exception as exc:  # noqa: BLE001 — record configured feed failure
        logger.exception("NASA FIRMS capture failed")
        if not dry_run:
            try:
                with engine.begin() as conn:
                    record_capture_failure(
                        conn, dataset_key="nasa_firms_point",
                        source_url="%s/[MAP_KEY_REDACTED]/<product>/<area>/1" % _API,
                        started_at=started_at,
                    )
            except Exception:  # noqa: BLE001 — heartbeat still records failure
                logger.exception("aurora_firms failed run could not be persisted")
            _heartbeat(engine, "aurora_firms", {}, exc)
        return {"error": str(exc)}
