"""
Federal fiscal aggregates (revenue, expense, balance, debt) — StatCan WDS.

Feeds /debt (design-handoff/wtf-debt.html). Source of truth is Statistics
Canada, table 10-10-0172-01 "Statement of government operations and balance
sheet, government finance statistics, annual", the *Federal government* member.
Nominal GDP for the debt-to-GDP ratio comes from table 36-10-0104-01
(current prices, seasonally adjusted at annual rates).

⚠️ WHAT THE YEAR MEANS — measured 2026-10-01, not assumed. The annual REF_DATE
is a CALENDAR year: for 2022, 2023 and 2024 the four calendar quarters of the
quarterly table 10-10-0015-01 sum EXACTLY to the annual federal revenue
(438,882 / 460,790 / 486,736), whereas the Apr–Mar window does not. So these
are Statistics Canada's *government finance statistics* (a consolidated
accounting basis), NOT the Public Accounts of Canada fiscal-year totals the
design mockup labels "15–16 … 24–25". The two differ by a few percent and
must never be shown under each other's name. The page says "calendar year"
and "Statistics Canada".

Vector IDs were read from the published full-table CSV (23 federal rows) and
GDP v62305783 ("Gross domestic product at market prices"). They are stable
series identifiers.

Never fabricates: a vector that FAILED or returned nothing is reported in the
return dict and the run is flagged, rather than silently filling a gap.

Manual run: python -m ingest.market.fiscal_federal
Scheduled:  run_fiscal_federal(engine) from ingest/run.py, weekly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.market")

DB_URL = os.environ.get("WTF_DATABASE_URL", "")
WDS_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"

ANNUAL_TABLE = "10-10-0172-01"
QUARTERLY_TABLE = "10-10-0015-01"
GDP_TABLE = "36-10-0104-01"
GDP_VECTOR = 62305783
# 1990 → latest is ~36 years; ask for headroom so a new year never truncates the oldest.
_ANNUAL_LATEST_N = 45
# Quarterly GDP back to 1990 = 4 * 36; headroom as above.
_GDP_LATEST_N = 180

_RELEASE_TZ = ZoneInfo("America/Toronto")

# item_key -> StatCan vector id (federal government, table 10-10-0172-01)
FEDERAL_VECTORS: dict[str, int] = {
    "revenue": 1645353801,
    "taxes_income": 1645353803,
    "taxes_goods_services": 1645353806,
    "taxes_trade": 1645353807,
    "social_contributions": 1645353809,
    "grants_revenue": 1645353810,
    "other_revenue": 1645353811,
    "expense": 1645353812,
    "compensation": 1645353813,
    "goods_services": 1645353814,
    "fixed_capital": 1645353815,
    "interest": 1645353816,
    "subsidies": 1645353817,
    "grants_expense": 1645353818,
    "social_benefits": 1645353819,
    "other_expense": 1645353820,
    "net_operating_balance": 1645353822,
    "net_lending": 1645353824,
    "non_financial_assets": 1645353842,
    "financial_assets": 1645353843,
    "liabilities": 1645353850,
    "debt_securities": 1645353852,
    "net_financial_worth": 1645353857,
}
_BY_VECTOR = {v: k for k, v in FEDERAL_VECTORS.items()}

# Quarterly federal series (table 10-10-0015-01) — the only place the CURRENT year exists:
# the annual table lags, the quarterly one reached Apr–Jun 2026 when this was written.
# REF_DATE is the first day of a CALENDAR quarter (2026-04-01 = Q2, Apr–Jun).
QUARTERLY_VECTORS: dict[str, int] = {
    "revenue": 52531053, "taxes_income": 52531055, "taxes_goods_services": 52531058,
    "taxes_trade": 52531059, "social_contributions": 52531061, "expense": 52531064,
    "compensation": 52531065, "interest": 52531068, "grants_expense": 52531070,
    "social_benefits": 52531071, "net_operating_balance": 52531074, "net_lending": 52531076,
    "liabilities": 52531102, "debt_securities": 52531104, "net_financial_worth": 52531109,
}
_QBY_VECTOR = {v: k for k, v in QUARTERLY_VECTORS.items()}
_QUARTERLY_LATEST_N = 12


def _post(vectors: list[tuple[int, int]]) -> list[dict]:
    body = json.dumps([{"vectorId": v, "latestN": n} for v, n in vectors]).encode("utf-8")
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _fetch() -> tuple[list[dict], list[dict], list[dict]]:
    annual = _post([(v, _ANNUAL_LATEST_N) for v in FEDERAL_VECTORS.values()])
    gdp = _post([(GDP_VECTOR, _GDP_LATEST_N)])
    quarterly = _post([(v, _QUARTERLY_LATEST_N) for v in QUARTERLY_VECTORS.values()])
    return annual, gdp, quarterly


def _release_time(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).replace(tzinfo=_RELEASE_TZ)
    except ValueError:
        return None


def build_annual_rows(payload: list[dict]) -> tuple[list[dict], list[str]]:
    """Pure transform: WDS array -> upsert rows. Millions of CAD, as published.

    One bad vector must not discard the good ones, so failures are collected
    as `errors` instead of raising. A data point with no value (StatCan's
    ".." / not-available) is skipped, never zero-filled — a missing year is
    different from a year that is zero."""
    rows: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for item in payload:
        obj = item.get("object") or {}
        vid = obj.get("vectorId")
        key = _BY_VECTOR.get(vid)
        if key is None:
            errors.append(f"unrecognized vectorId {vid}")
            continue
        if item.get("status") != "SUCCESS":
            errors.append(f"{key}: WDS status={item.get('status')!r}")
            continue
        got = False
        for p in obj.get("vectorDataPoint") or []:
            ref, raw = p.get("refPer"), p.get("value")
            if not ref or raw in (None, ""):
                continue
            try:
                year = int(str(ref)[:4])
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if int(p.get("scalarFactorCode", 6)) != 6:
                errors.append(f"{key}: unexpected scalar {p.get('scalarFactorCode')} (expected millions)")
                continue
            rows.append({"ref_year": year, "item_key": key, "value_millions": value,
                         "vector_id": vid, "source_table": ANNUAL_TABLE, "derived": False,
                         "release_time": _release_time(p.get("releaseTime"))})
            got = True
        if got:
            seen.add(key)
        else:
            errors.append(f"{key}: no usable data points")
    for key in FEDERAL_VECTORS:
        if key not in seen and not any(e.startswith(key) for e in errors):
            errors.append(f"{key}: missing from response")
    return rows, errors


def build_quarterly_rows(payload: list[dict]) -> tuple[list[dict], list[str]]:
    """Calendar-quarter rows (millions CAD). Flows are NOT seasonally adjusted, so only
    compare a quarter with the same quarter of another year, or sum whole years."""
    rows: list[dict] = []
    errors: list[str] = []
    for item in payload:
        obj = item.get("object") or {}
        key = _QBY_VECTOR.get(obj.get("vectorId"))
        if key is None:
            errors.append(f"unrecognized vectorId {obj.get('vectorId')}")
            continue
        if item.get("status") != "SUCCESS":
            errors.append(f"{key}: WDS status={item.get('status')!r}")
            continue
        got = False
        for p in obj.get("vectorDataPoint") or []:
            ref, raw = p.get("refPer"), p.get("value")
            if not ref or raw in (None, ""):
                continue
            try:
                q = date.fromisoformat(str(ref)[:10])
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if q.month not in (1, 4, 7, 10) or q.day != 1:
                errors.append(f"{key}: odd quarter start {q}")
                continue
            rows.append({"ref_quarter": q, "item_key": key, "value_millions": value,
                         "vector_id": obj["vectorId"], "source_table": QUARTERLY_TABLE,
                         "release_time": _release_time(p.get("releaseTime"))})
            got = True
        if not got:
            errors.append(f"{key}: no usable quarterly points")
    return rows, errors


def build_gdp_rows(payload: list[dict]) -> tuple[list[dict], list[str]]:
    """Calendar-year nominal GDP = mean of that year's four quarterly values
    (each is already a seasonally-adjusted ANNUAL rate). Only COMPLETE years
    are emitted: a partial year averaged over 2 quarters would quietly
    understate/overstate the ratio. Marked derived=True — it is computed here,
    not published as an annual figure by this table."""
    errors: list[str] = []
    by_year: dict[int, list[float]] = defaultdict(list)
    for item in payload:
        obj = item.get("object") or {}
        if item.get("status") != "SUCCESS":
            errors.append(f"gdp: WDS status={item.get('status')!r}")
            continue
        for p in obj.get("vectorDataPoint") or []:
            ref, raw = p.get("refPer"), p.get("value")
            if not ref or raw in (None, ""):
                continue
            try:
                d = date.fromisoformat(str(ref)[:10])
                by_year[d.year].append(float(raw))
            except (TypeError, ValueError):
                continue
    rows = [{"ref_year": y, "item_key": "gdp_nominal", "value_millions": sum(v) / 4.0,
             "vector_id": GDP_VECTOR, "source_table": GDP_TABLE, "derived": True,
             "release_time": None}
            for y, v in sorted(by_year.items()) if len(v) == 4]
    if not rows:
        errors.append("gdp: no complete calendar year in response")
    return rows, errors


def _upsert(engine, rows: list[dict]) -> int:
    n = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS market_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_watch.fiscal_federal_annual (
                ref_year       INTEGER NOT NULL,
                item_key       TEXT NOT NULL,
                value_millions NUMERIC(16,1) NOT NULL,
                vector_id      BIGINT NOT NULL,
                source_table   TEXT NOT NULL,
                derived        BOOLEAN NOT NULL DEFAULT FALSE,
                release_time   TIMESTAMPTZ,
                fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (ref_year, item_key)
            )
        """))
        for r in rows:
            n += conn.execute(text("""
                INSERT INTO market_watch.fiscal_federal_annual
                    (ref_year, item_key, value_millions, vector_id, source_table, derived, release_time)
                VALUES (:ref_year, :item_key, :value_millions, :vector_id, :source_table, :derived, :release_time)
                ON CONFLICT (ref_year, item_key) DO UPDATE
                    SET value_millions = EXCLUDED.value_millions,
                        vector_id = EXCLUDED.vector_id,
                        source_table = EXCLUDED.source_table,
                        derived = EXCLUDED.derived,
                        release_time = EXCLUDED.release_time,
                        fetched_at = now()
            """), r).rowcount
    return n


def _upsert_quarterly(engine, rows: list[dict]) -> int:
    n = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS market_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_watch.fiscal_federal_quarterly (
                ref_quarter    DATE NOT NULL,
                item_key       TEXT NOT NULL,
                value_millions NUMERIC(16,1) NOT NULL,
                vector_id      BIGINT NOT NULL,
                source_table   TEXT NOT NULL,
                release_time   TIMESTAMPTZ,
                fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (ref_quarter, item_key)
            )
        """))
        for r in rows:
            n += conn.execute(text("""
                INSERT INTO market_watch.fiscal_federal_quarterly
                    (ref_quarter, item_key, value_millions, vector_id, source_table, release_time)
                VALUES (:ref_quarter, :item_key, :value_millions, :vector_id, :source_table, :release_time)
                ON CONFLICT (ref_quarter, item_key) DO UPDATE
                    SET value_millions = EXCLUDED.value_millions,
                        vector_id = EXCLUDED.vector_id,
                        source_table = EXCLUDED.source_table,
                        release_time = EXCLUDED.release_time,
                        fetched_at = now()
            """), r).rowcount
    return n


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log on BOTH paths — same never-raise contract as boc_rates."""
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
                c.execute(text("INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                          {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:  # noqa: BLE001
        logger.exception("%s heartbeat write failed", task)


def run_fiscal_federal(engine) -> dict:
    """Fetch + upsert. Never raises; a failure lands in the return dict and ingest_log."""
    task = "fiscal_federal"
    out: dict = {}
    exc: Exception | None = None
    try:
        annual_payload, gdp_payload, q_payload = _fetch()
        a_rows, a_err = build_annual_rows(annual_payload)
        g_rows, g_err = build_gdp_rows(gdp_payload)
        q_rows, q_err = build_quarterly_rows(q_payload)
        errors = a_err + g_err + q_err
        # Revenue and expense are the page's spine: without both, refuse the run rather
        # than publish a half-built picture that looks complete.
        have = {r["item_key"] for r in a_rows}
        if not {"revenue", "expense"} <= have:
            out["error"] = "revenue/expense missing: " + "; ".join(errors)[:300]
        else:
            n = _upsert(engine, a_rows + g_rows)
            if q_rows:
                n += _upsert_quarterly(engine, q_rows)
            years = sorted({r["ref_year"] for r in a_rows})
            out.update(fetched=len(a_rows) + len(g_rows) + len(q_rows), upserted=n,
                       latest_year=years[-1], first_year=years[0],
                       latest_quarter=str(max((r["ref_quarter"] for r in q_rows), default="")))
            if errors:
                out["partial"] = errors[:6]
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
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
    result = run_fiscal_federal(create_engine(DB_URL))
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(result)


if __name__ == "__main__":
    ingest()
