"""
Bank of Canada overnight rate decisions — ingest via Valet API.

Uses: https://www.bankofcanada.ca/valet/observations/V122514/json
V122514 = Target for the Overnight Rate (announced at each rate decision)

Manual run: python -m ingest.market.boc_rates
Scheduled: run_boc_rates(engine) from ingest/run.py, weekly (#6272, Batch 9)
— BoC decisions are ~8/year on fixed dates, so daily would buy nothing; this
was a one-off 2026-05-18 backfill with no scheduled follow-up, discovered
~5 months stale during the WTF design-handoff economy-page scoping pass.
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
VALET_URL = "https://www.bankofcanada.ca/valet/observations/V122514/json"
BOC_RELEASE_BASE = "https://www.bankofcanada.ca/press-releases/"


def _fetch_observations() -> list[dict]:
    """Fetch all overnight rate observations from BoC Valet API."""
    req = urllib.request.Request(
        VALET_URL,
        headers={"Accept": "application/json", "User-Agent": "WhatTheFact/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    obs = data.get("observations", [])
    return obs


def _build_press_release_url(d: date) -> str:
    """Best-effort press release URL — BoC uses date slug format."""
    month_names = [
        "", "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]
    slug = f"{d.year}/{month_names[d.month]}/bank-of-canada-{d.strftime('%B-%d-%Y').lower().replace(' ', '-')}"
    return f"{BOC_RELEASE_BASE}{slug}/"


def _build_rows(obs: list[dict]) -> list[dict]:
    """Pure transform: raw Valet observations -> upsert-ready rows.

    BoC announces rates on fixed dates — the series only has ~8 data
    points/year plus some historical daily data pre-2010. Dedupes to one
    entry per month for the pre-2010 daily noise, then computes basis-point
    changes between consecutive decisions."""
    decisions = []
    for o in obs:
        val = o.get("V122514", {})
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
        decisions.append({"date": d, "rate": rate})

    decisions.sort(key=lambda x: x["date"])

    deduped = []
    seen_months = set()
    for rec in decisions:
        month_key = (rec["date"].year, rec["date"].month)
        if month_key in seen_months and rec["date"].year < 2010:
            deduped = [r for r in deduped if (r["date"].year, r["date"].month) != month_key]
        seen_months.add(month_key)
        deduped.append(rec)

    rows = []
    prev_rate = None
    for rec in deduped:
        change_bps = None if prev_rate is None else round((rec["rate"] - prev_rate) * 100)
        rows.append({
            "decision_date": rec["date"],
            "rate_pct": rec["rate"],
            "change_bps": change_bps,
            "press_release_url": _build_press_release_url(rec["date"]),
        })
        prev_rate = rec["rate"]
    return rows


def _upsert(engine, rows: list[dict]) -> int:
    """Upsert rows into market_watch.boc_rate_decisions. Returns inserted count."""
    inserted = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS market_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_watch.boc_rate_decisions (
                id              SERIAL PRIMARY KEY,
                decision_date   DATE UNIQUE NOT NULL,
                rate_pct        DECIMAL(5,3) NOT NULL,
                change_bps      INTEGER,
                press_release_url TEXT,
                scraped_at      TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_boc_rate_date "
            "ON market_watch.boc_rate_decisions(decision_date DESC)"
        ))
        for row in rows:
            result = conn.execute(text("""
                INSERT INTO market_watch.boc_rate_decisions
                    (decision_date, rate_pct, change_bps, press_release_url)
                VALUES (:decision_date, :rate_pct, :change_bps, :press_release_url)
                ON CONFLICT (decision_date) DO UPDATE
                    SET rate_pct = EXCLUDED.rate_pct,
                        change_bps = EXCLUDED.change_bps,
                        press_release_url = EXCLUDED.press_release_url,
                        scraped_at = NOW()
            """), row)
            if result.rowcount > 0:
                inserted += 1
    return inserted


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log row on BOTH paths — mirrors ingest/elections/
    results.py's _heartbeat exactly (same table, same never-raise contract).
    A swallowed error that never reaches the log is how an ingest rots for
    months while every dashboard stays green — which is precisely how this
    task went 5 months stale the first time, with no heartbeat at all."""
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


def run_boc_rates(engine) -> dict:
    """Fetch and upsert BoC rate decisions. Never raises — same contract as
    run_election_results(): a failure is reported in the return dict and
    logged to parliament.ingest_log, not thrown into the ingest loop."""
    task = "boc_rates"
    out: dict = {}
    exc: Exception | None = None
    try:
        obs = _fetch_observations()
        rows = _build_rows(obs)
        if not rows:
            out["error"] = "no rate-decision rows parsed from Valet response"
        else:
            inserted = _upsert(engine, rows)
            out.update(fetched=len(obs), upserted=inserted,
                       current_rate=rows[-1]["rate_pct"],
                       current_as_of=str(rows[-1]["decision_date"]))
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        out["error"] = str(e)
        logger.exception("%s failed", task)
    _heartbeat(engine, task, out, exc)
    logger.info("%s: %s", task, out)
    return out


def ingest():
    """CLI entry point for a manual run: python -m ingest.market.boc_rates."""
    if not DB_URL:
        print("ERROR: WTF_DATABASE_URL not set")
        sys.exit(1)
    engine = create_engine(DB_URL)
    result = run_boc_rates(engine)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(f"  Upserted: {result['upserted']} rows")
    print(f"  Current rate: {result['current_rate']}% (as of {result['current_as_of']})")
    print("Done.")


if __name__ == "__main__":
    ingest()
