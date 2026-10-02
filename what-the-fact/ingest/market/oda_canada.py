"""
Canada's official development assistance (ODA) — OECD DAC1 via the OECD Data API (SDMX).

Feeds /global (design-handoff/wtf-global.html). Source: OECD Development Assistance
Committee, dataflow OECD.DCD.FSD DSD_DAC1@DF_DAC1, donor CAN. The design cites the same OECD
DAC tables. CSV is requested with `Accept: text/csv`.

Series pulled (all calendar years; codes read from the DSD codelists, 2026-10-01):
  oda_ge          MEASURE 11010  "ODA, grant equivalent"          FLOW 1160  XDC  C$ millions
  bilateral_ge    MEASURE 11015  "Bilateral ODA, grant equivalent" FLOW 1160  XDC  C$ millions
  oda_gni_pct     MEASURE 11002  "ODA as percent of GNI, g.e."     FLOW 1160  PT_B5G  percent

XDC is national currency (CAD), so no exchange-rate conversion is applied by us.
"Grant equivalent" is the OECD's headline measure since 2018: loans count only for their
concessional element, which is why it is lower than gross disbursements.

⚠️ The latest year PUBLISHED is not the current year. At time of writing (Oct 2026) the newest
observation is 2024; 2025 is not yet in the table. The page states the latest year it holds and
never labels it as the current year.

Never fabricates: a series/year with no value is skipped, not zero-filled. Multilateral is NOT
stored — it is derived on the page as total minus bilateral and labelled as such.

Manual run: python -m ingest.market.oda_canada
Scheduled:  run_oda_canada(engine) from ingest/run.py, weekly (the table moves ~once a year; the
weekly run exists so the heartbeat can prove the puller is alive).
"""

from __future__ import annotations

import csv
import io
import logging
import os
import sys
import urllib.request

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.market")

DB_URL = os.environ.get("WTF_DATABASE_URL", "")
URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.DCD.FSD,DSD_DAC1@DF_DAC1,1.5/"
    "CAN.......?startPeriod=2000&dimensionAtObservation=AllDimensions"
)
SOURCE = "OECD DAC1 (DSD_DAC1@DF_DAC1)"

# (MEASURE, FLOW_TYPE, UNIT_MEASURE) -> item_key
SERIES: dict[tuple[str, str, str], str] = {
    ("11010", "1160", "XDC"): "oda_ge",
    ("11015", "1160", "XDC"): "bilateral_ge",
    ("11002", "1160", "PT_B5G"): "oda_gni_pct",
}


def _fetch() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": "WhatTheFact/1.0", "Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read().decode("utf-8", "ignore")


def build_rows(csv_text: str) -> tuple[list[dict], list[str]]:
    """Pure transform: OECD CSV -> upsert rows. Current-price (PRICE_BASE 'V') series only;
    constant-price rows share the same measure/flow and must not be mixed in."""
    rows: dict[tuple[int, str], dict] = {}
    errors: list[str] = []
    for r in csv.DictReader(io.StringIO(csv_text)):
        key = SERIES.get((r.get("MEASURE", ""), r.get("FLOW_TYPE", ""), r.get("UNIT_MEASURE", "")))
        if key is None or r.get("PRICE_BASE") != "V":
            continue
        raw = (r.get("OBS_VALUE") or "").strip()
        if raw == "":
            continue
        try:
            year = int(r["TIME_PERIOD"][:4])
            value = float(raw)
        except (KeyError, ValueError):
            continue
        # UNIT_MULT 6 = millions for the money series; the percent series carries 0.
        want_mult = "0" if key == "oda_gni_pct" else "6"
        if (r.get("UNIT_MULT") or "").strip() not in (want_mult, ""):
            errors.append(f"{key} {year}: unexpected UNIT_MULT {r.get('UNIT_MULT')!r}")
            continue
        rows[(year, key)] = {"ref_year": year, "item_key": key, "value": value,
                             "unit": "percent" if key == "oda_gni_pct" else "CAD_millions",
                             "source": SOURCE}
    have = {k for _, k in rows}
    for key in SERIES.values():
        if key not in have:
            errors.append(f"{key}: no observations in response")
    return list(rows.values()), errors


def _upsert(engine, rows: list[dict]) -> int:
    n = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS market_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_watch.oda_canada_annual (
                ref_year   INTEGER NOT NULL,
                item_key   TEXT NOT NULL,
                value      NUMERIC(14,3) NOT NULL,
                unit       TEXT NOT NULL,
                source     TEXT NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (ref_year, item_key)
            )
        """))
        for r in rows:
            n += conn.execute(text("""
                INSERT INTO market_watch.oda_canada_annual (ref_year, item_key, value, unit, source)
                VALUES (:ref_year, :item_key, :value, :unit, :source)
                ON CONFLICT (ref_year, item_key) DO UPDATE
                    SET value = EXCLUDED.value, unit = EXCLUDED.unit,
                        source = EXCLUDED.source, fetched_at = now()
            """), r).rowcount
    return n


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) VALUES (:t, :f, :u)"),
                          {"t": task, "f": int(result.get("fetched") or 0), "u": int(result.get("upserted") or 0)})
            else:
                c.execute(text("INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                          {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:  # noqa: BLE001
        logger.exception("%s heartbeat write failed", task)


def run_oda_canada(engine) -> dict:
    """Fetch + upsert. Never raises; a failure lands in the return dict and ingest_log."""
    task = "oda_canada"
    out: dict = {}
    exc: Exception | None = None
    try:
        rows, errors = build_rows(_fetch())
        have = {r["item_key"] for r in rows}
        if "oda_ge" not in have:
            out["error"] = "headline ODA series missing: " + "; ".join(errors)[:300]
        else:
            n = _upsert(engine, rows)
            out.update(fetched=len(rows), upserted=n,
                       latest_year=max(r["ref_year"] for r in rows if r["item_key"] == "oda_ge"))
            if errors:
                out["partial"] = errors[:6]
    except Exception as e:  # noqa: BLE001
        exc = e
        out["error"] = str(e)
        logger.exception("%s failed", task)
    _heartbeat(engine, task, out, exc)
    logger.info("%s: %s", task, out)
    return out


def ingest():
    if not DB_URL:
        print("ERROR: WTF_DATABASE_URL not set")
        sys.exit(1)
    result = run_oda_canada(create_engine(DB_URL))
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(result)


if __name__ == "__main__":
    ingest()
