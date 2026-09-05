"""
CAD/USD daily exchange rate — ingest via Bank of Canada Valet API.

Uses: https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=800
FXUSDCAD = daily average USD/CAD exchange rate. Unlike the overnight rate
(V122514, ~8 fixed decision dates/year — see boc_rates.py), this series
updates once per business day, so `recent=800` pulls roughly the last
~2+ years of daily observations in one call.

Manual run: python -m ingest.market.fx_rates
Scheduled: NOT YET WIRED — this module intentionally does not touch
ingest/run.py or ingest/parliament/drift_guard.py (batch-12 scope
discipline: a parallel StatCan-indicators agent owns those shared files
this round). The coordinator wires the scheduled call + drift_guard
registration + the /economy card in a follow-up pass once both ingest
PRs land, mirroring the boc_rates.py weekly-cadence pattern (#6272).
"""

import json
import logging
import os
import sys
import urllib.request
from datetime import date

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.market")

DB_URL = os.environ.get("WTF_DATABASE_URL", "")
VALET_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=800"


def _fetch_observations() -> list[dict]:
    """Fetch recent USD/CAD daily-rate observations from BoC Valet API."""
    req = urllib.request.Request(
        VALET_URL,
        headers={"Accept": "application/json", "User-Agent": "WhatTheFact/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    obs = data.get("observations", [])
    return obs


def _build_rows(obs: list[dict]) -> list[dict]:
    """Pure transform: raw Valet observations -> upsert-ready rows.

    BoC Valet sometimes has gaps for holidays/weekends where the series
    key is present but empty, or absent entirely — those dates are
    SKIPPED, never interpolated or invented (never fabricate a rate)."""
    rows = []
    for o in obs:
        val = o.get("FXUSDCAD", {})
        if not val or val.get("v") is None:
            continue
        d_str = o.get("d")
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
            rate = float(val["v"])
        except (ValueError, KeyError):
            continue
        rows.append({"rate_date": d, "usd_cad": rate})
    rows.sort(key=lambda r: r["rate_date"])
    return rows


def _upsert(engine, rows: list[dict]) -> int:
    """Upsert rows into market_watch.fx_rates. Returns upserted count."""
    inserted = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS market_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_watch.fx_rates (
                id         SERIAL PRIMARY KEY,
                rate_date  DATE UNIQUE NOT NULL,
                usd_cad    DECIMAL(8,4) NOT NULL,
                scraped_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_fx_rates_date "
            "ON market_watch.fx_rates(rate_date DESC)"
        ))
        for row in rows:
            result = conn.execute(text("""
                INSERT INTO market_watch.fx_rates (rate_date, usd_cad)
                VALUES (:rate_date, :usd_cad)
                ON CONFLICT (rate_date) DO UPDATE
                    SET usd_cad = EXCLUDED.usd_cad,
                        scraped_at = NOW()
            """), row)
            if result.rowcount > 0:
                inserted += 1
    return inserted


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log row on BOTH paths — same never-raise contract
    as boc_rates.py's _heartbeat / ingest/elections/results.py's
    _heartbeat. A swallowed error that never reaches the log is how an
    ingest rots for months while every dashboard stays green."""
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


def run_fx_rates(engine) -> dict:
    """Fetch and upsert CAD/USD daily exchange rates. Never raises — same
    contract as run_boc_rates(): a failure is reported in the return dict
    and logged to parliament.ingest_log, not thrown into the ingest loop."""
    task = "fx_rates"
    out: dict = {}
    exc: Exception | None = None
    try:
        obs = _fetch_observations()
        rows = _build_rows(obs)
        if not rows:
            out["error"] = "no exchange-rate rows parsed from Valet response"
        else:
            inserted = _upsert(engine, rows)
            out.update(fetched=len(obs), upserted=inserted,
                       current_rate=rows[-1]["usd_cad"],
                       current_as_of=str(rows[-1]["rate_date"]))
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        out["error"] = str(e)
        logger.exception("%s failed", task)
    _heartbeat(engine, task, out, exc)
    logger.info("%s: %s", task, out)
    return out


def ingest():
    """CLI entry point for a manual run: python -m ingest.market.fx_rates."""
    if not DB_URL:
        print("ERROR: WTF_DATABASE_URL not set")
        sys.exit(1)
    engine = create_engine(DB_URL)
    result = run_fx_rates(engine)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(f"  Upserted: {result['upserted']} rows")
    print(f"  Current rate: {result['current_rate']} USD/CAD (as of {result['current_as_of']})")
    print("Done.")


if __name__ == "__main__":
    ingest()
