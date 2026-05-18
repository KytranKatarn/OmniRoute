"""
Bank of Canada overnight rate decisions — ingest via Valet API.

Uses: https://www.bankofcanada.ca/valet/observations/V122514/json
V122514 = Target for the Overnight Rate (announced at each rate decision)

Run: python -m ingest.market.boc_rates
"""

import json
import os
import sys
import urllib.request
from datetime import date, datetime

import psycopg2

DB_URL = os.environ.get("WTF_DATABASE_URL", "")
VALET_URL = "https://www.bankofcanada.ca/valet/observations/V122514/json"
BOC_RELEASE_BASE = "https://www.bankofcanada.ca/press-releases/"


def _connect():
    import sqlalchemy
    from sqlalchemy import create_engine
    engine = create_engine(DB_URL)
    return engine.connect()


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


def ingest():
    """Fetch and upsert BoC rate decisions into market_watch.boc_rate_decisions."""
    if not DB_URL:
        print("ERROR: WTF_DATABASE_URL not set")
        sys.exit(1)

    print("Fetching BoC Valet API...")
    obs = _fetch_observations()
    print(f"  Got {len(obs)} raw observations")

    # Filter to actual rate-decision dates only:
    # BoC announces rates on fixed dates — the series only has 8 data points/year
    # plus some historical daily data pre-2010. We take unique non-null values
    # and deduplicate by keeping one per month-end group for pre-2010 data.
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

    # Sort ascending to compute changes
    decisions.sort(key=lambda x: x["date"])

    # For pre-2010 daily series: keep only one entry per month (the last)
    # so we get ~monthly snapshots rather than daily noise
    deduped = []
    seen_months = set()
    for rec in decisions:
        month_key = (rec["date"].year, rec["date"].month)
        if month_key in seen_months and rec["date"].year < 2010:
            # Replace previous entry for same month (keep last = highest date)
            deduped = [r for r in deduped if (r["date"].year, r["date"].month) != month_key]
        seen_months.add(month_key)
        deduped.append(rec)

    print(f"  Unique rate-decision records: {len(deduped)}")

    # Compute basis-point changes
    rows = []
    prev_rate = None
    for rec in deduped:
        if prev_rate is None:
            change_bps = None
        else:
            change_bps = round((rec["rate"] - prev_rate) * 100)
        rows.append({
            "decision_date": rec["date"],
            "rate_pct": rec["rate"],
            "change_bps": change_bps,
            "press_release_url": _build_press_release_url(rec["date"]),
        })
        prev_rate = rec["rate"]

    # Upsert
    from sqlalchemy import create_engine, text
    engine = create_engine(DB_URL)
    inserted = updated = 0
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

    print(f"  Upserted: {inserted} rows")
    print(f"  Current rate: {rows[-1]['rate_pct']}% (as of {rows[-1]['decision_date']})")
    print("Done.")


if __name__ == "__main__":
    ingest()
