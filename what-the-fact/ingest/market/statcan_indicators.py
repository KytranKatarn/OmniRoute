"""
StatCan economic indicators (CPI, unemployment, GDP, housing starts) — ingest
via the StatCan Web Data Service (WDS) REST API.

Uses: POST https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods
The endpoint accepts an ARRAY of {"vectorId": N, "latestN": N} objects, so all
four indicators below are fetched in ONE HTTP call.

Indicators (vector IDs + table IDs verified live 2026-09-04):
  - cpi_index           vectorId 41690973  table 18-10-0004-01  CPI, all-items,
                         RAW INDEX (2002=100) — e.g. 169.9. NOT a percentage.
  - unemployment_rate   vectorId 2062815   table 14-10-0287-01  Labour Force
                         Survey, already a direct percentage — e.g. 6.4.
  - gdp_level           vectorId 65201210  table 36-10-0434-01  Real GDP,
                         monthly, RAW LEVEL in millions of chained dollars —
                         e.g. 2369309.0 (~$2.37 trillion). NOT a percentage.
  - housing_starts_saar vectorId 52300157  table 34-10-0158-01  Housing starts,
                         seasonally adjusted at annual rates (CMHC data,
                         republished by StatCan via this API) — real level in
                         thousands of units, e.g. 229.074.

Every value is stored RAW, exactly as StatCan reports it. Year-over-year /
month-over-month % change is deliberately NOT computed here — that derivation
belongs in the route layer (a pure helper reading consecutive rows), the same
separation boc_rates.py uses: this module stores rate_pct, the /rates route
derives "since peak" / consecutive-holds from it.

Manual run: python -m ingest.market.statcan_indicators
Scheduling + drift_guard registration + the /economy route wiring are done by
the coordinator after both Batch 12 ingest PRs land — this module intentionally
does not touch ingest/run.py or ingest/parliament/drift_guard.py.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.market")

DB_URL = os.environ.get("WTF_DATABASE_URL", "")
WDS_URL = (
    "https://www150.statcan.gc.ca/t1/wds/rest/"
    "getDataFromVectorsAndLatestNPeriods"
)
# ~24 months of monthly history + 1 extra point, per-vector.
_LATEST_N = 25

# StatCan release timestamps in the WDS payload (e.g. "2026-08-17T08:30") carry
# no offset — StatCan releases are always announced at that wall-clock time in
# Eastern, so a naive stamp is interpreted as America/Toronto before it is
# handed to the (UTC-storing) TIMESTAMPTZ column, per timezone.md.
_RELEASE_TZ = ZoneInfo("America/Toronto")

# indicator_key -> (vectorId, table_id). table_id kept in the display format
# (NN-NN-NNNN-NN) the platform uses elsewhere (see boc_rates.py's Valet series,
# and the /economy StatCan table citations).
_INDICATORS: list[dict] = [
    {"key": "cpi_index", "vector_id": 41690973, "table_id": "18-10-0004-01"},
    {"key": "unemployment_rate", "vector_id": 2062815, "table_id": "14-10-0287-01"},
    {"key": "gdp_level", "vector_id": 65201210, "table_id": "36-10-0434-01"},
    {"key": "housing_starts_saar", "vector_id": 52300157, "table_id": "34-10-0158-01"},
]


def _fetch_indicators() -> list[dict]:
    """POST all four vectorIds in one call, return the raw parsed WDS response
    array (one element per requested vector, in request order but not relied
    on — _build_rows keys off object.vectorId)."""
    body = json.dumps(
        [{"vectorId": ind["vector_id"], "latestN": _LATEST_N} for ind in _INDICATORS]
    ).encode("utf-8")
    req = urllib.request.Request(
        WDS_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "WhatTheFact/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _parse_release_time(raw: str | None):
    """WDS releaseTime is a naive 'YYYY-MM-DDTHH:MM' string in Eastern wall
    clock. Returns a tz-aware datetime, or None on anything unparseable — a
    bad timestamp must never fabricate a release time."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_RELEASE_TZ)
    return parsed


def _build_rows(payload: list[dict]) -> tuple[list[dict], list[str]]:
    """Pure transform: raw WDS response array -> upsert-ready rows.

    Never fabricates: a vector that FAILED, returned no data points, or has an
    unparseable value/date is SKIPPED (and its skip recorded in `errors`) —
    it never becomes a row with a guessed or zeroed value. A response array
    can legitimately contain a mix of SUCCESS and FAILED elements (WDS reports
    per-vector status), so one bad vector must not discard the good ones."""
    by_vector_id = {ind["vector_id"]: ind for ind in _INDICATORS}
    rows: list[dict] = []
    errors: list[str] = []

    for item in payload or []:
        obj = item.get("object") or {}
        vector_id = obj.get("vectorId")
        indicator = by_vector_id.get(vector_id)
        if indicator is None:
            errors.append(f"unrecognized vectorId {vector_id} in WDS response")
            continue

        key = indicator["key"]
        if item.get("status") != "SUCCESS":
            errors.append(f"{key}: WDS status={item.get('status')!r}")
            continue

        points = obj.get("vectorDataPoint") or []
        if not points:
            errors.append(f"{key}: no data points returned")
            continue

        parsed_any = False
        for point in points:
            ref_per = point.get("refPer")
            raw_value = point.get("value")
            if not ref_per or raw_value is None:
                continue
            try:
                ref_date = date.fromisoformat(str(ref_per)[:10])
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "indicator_key": key,
                    "ref_date": ref_date,
                    "value": value,
                    "vector_id": vector_id,
                    "table_id": indicator["table_id"],
                    "release_time": _parse_release_time(point.get("releaseTime")),
                }
            )
            parsed_any = True

        if not parsed_any:
            errors.append(f"{key}: every data point was unparseable")

    return rows, errors


def _upsert(engine, rows: list[dict]) -> int:
    """Upsert rows into market_watch.economic_indicators. Returns the count of
    rows the driver reports as touched (insert or update)."""
    inserted = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS market_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_watch.economic_indicators (
                id            SERIAL PRIMARY KEY,
                indicator_key TEXT NOT NULL,
                ref_date      DATE NOT NULL,
                value         DECIMAL(14,4) NOT NULL,
                vector_id     INTEGER NOT NULL,
                table_id      TEXT NOT NULL,
                release_time  TIMESTAMPTZ,
                scraped_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (indicator_key, ref_date)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_economic_indicators_key_date "
            "ON market_watch.economic_indicators(indicator_key, ref_date DESC)"
        ))
        for row in rows:
            result = conn.execute(text("""
                INSERT INTO market_watch.economic_indicators
                    (indicator_key, ref_date, value, vector_id, table_id, release_time)
                VALUES (:indicator_key, :ref_date, :value, :vector_id, :table_id, :release_time)
                ON CONFLICT (indicator_key, ref_date) DO UPDATE
                    SET value = EXCLUDED.value,
                        vector_id = EXCLUDED.vector_id,
                        table_id = EXCLUDED.table_id,
                        release_time = EXCLUDED.release_time,
                        scraped_at = NOW()
            """), row)
            if result.rowcount > 0:
                inserted += 1
    return inserted


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log row on BOTH paths — mirrors boc_rates.py's
    _heartbeat exactly (same table, same never-raise contract). A swallowed
    error that never reaches the log is how an ingest rots for months while
    every dashboard stays green."""
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
    except Exception:
        logger.exception("%s heartbeat write failed", task)


def run_statcan_indicators(engine) -> dict:
    """Fetch and upsert the four StatCan indicators. Never raises — same
    contract as run_boc_rates(): a failure is reported in the return dict and
    logged to parliament.ingest_log, not thrown into the ingest loop."""
    task = "statcan_indicators"
    out: dict = {}
    exc: Exception | None = None
    try:
        payload = _fetch_indicators()
        rows, errors = _build_rows(payload)
        if not rows:
            out["error"] = "; ".join(errors) if errors else (
                "no indicator rows parsed from WDS response"
            )
        else:
            inserted = _upsert(engine, rows)
            out.update(fetched=len(rows), upserted=inserted)
            if errors:
                # A partial fetch (some indicators OK, others skipped) is NOT
                # a failed run — the good rows still land, and the heartbeat
                # stays a success. Errors are surfaced for visibility only.
                out["partial_errors"] = "; ".join(errors)
            latest: dict[str, dict] = {}
            for row in rows:
                key = row["indicator_key"]
                if key not in latest or row["ref_date"] > latest[key]["ref_date"]:
                    latest[key] = row
            out["latest"] = {
                key: {"value": row["value"], "as_of": str(row["ref_date"])}
                for key, row in latest.items()
            }
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        out["error"] = str(e)
        logger.exception("%s failed", task)
    _heartbeat(engine, task, out, exc)
    logger.info("%s: %s", task, out)
    return out


def ingest():
    """CLI entry point for a manual run: python -m ingest.market.statcan_indicators."""
    if not DB_URL:
        print("ERROR: WTF_DATABASE_URL not set")
        sys.exit(1)
    engine = create_engine(DB_URL)
    result = run_statcan_indicators(engine)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(f"  Upserted: {result['upserted']} rows")
    for key, info in result.get("latest", {}).items():
        print(f"  {key}: {info['value']} (as of {info['as_of']})")
    if result.get("partial_errors"):
        print(f"  (partial) {result['partial_errors']}")
    print("Done.")


if __name__ == "__main__":
    ingest()
