"""Roll the /elections calendar forward from statute rules + ingested election dates.

No network: the inputs are rows we already hold (parliament.elections for the federal
date, parliament.election_history for curated provincial results) plus the encoded
fixed-date rules in shared/election_rules.py. House pattern: never raises, heartbeat
on BOTH paths (parliament.ingest_log task `elections_calendar`).

Never overwrites a HUMAN-verified row (verified_at set): a disagreement between the
computed date and the verified one is REPORTED as an error so the drift guard alarms —
silently trusting either side would hide whichever is wrong.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import text

from shared.election_rules import RULES, anchor_for, next_latest_date
from .results import _heartbeat

logger = logging.getLogger(__name__)


def plan(rows: dict, history_last: dict, federal_last, today: dt.date) -> tuple[list, list]:
    """Pure: -> (updates, conflicts). rows = {code: calendar row dict}."""
    updates, conflicts = [], []
    for code, (_m, _w, _n, _y, rule, src) in RULES.items():
        row = rows.get(code)
        if row is None:
            continue
        hist = federal_last if code == "CA" else history_last.get(code)
        last = anchor_for(code, row.get("last_election"), hist)
        nxt = next_latest_date(code, last)
        if nxt is None:
            continue
        if row.get("verified_at") is not None:
            if row.get("next_latest_date") and row["next_latest_date"] != nxt:
                conflicts.append("%s: verified %s != rule-derived %s" % (code, row["next_latest_date"], nxt))
            continue
        # A date already in the past with no newer election means "awaiting results":
        # still written (the page shows roll-forward), the drift guard flags it.
        updates.append({"code": code, "last": last, "next": nxt, "rule": rule, "src": src})
    return updates, conflicts


def run_election_calendar(engine, dry_run: bool = False) -> dict:
    task = "elections_calendar"
    out: dict = {}
    exc: Exception | None = None
    try:
        with engine.connect() as c:
            rows = {r["jurisdiction_code"]: dict(r) for r in c.execute(text(
                "SELECT jurisdiction_code, last_election, next_latest_date, verified_at "
                "FROM parliament.election_calendar")).mappings().all()}
            hist = {r["jurisdiction_code"]: r["d"] for r in c.execute(text(
                "SELECT jurisdiction_code, max(election_date) AS d "
                "FROM parliament.election_history GROUP BY 1")).mappings().all()}
            fed = c.execute(text("SELECT max(election_date) FROM parliament.elections")).scalar()
        updates, conflicts = plan(rows, hist, fed, dt.date.today())
        out["updates"] = len(updates)
        if conflicts:
            out["error"] = "; ".join(conflicts)[:400]
        if not dry_run and updates:
            with engine.begin() as c:
                for u in updates:
                    c.execute(text(
                        "UPDATE parliament.election_calendar SET last_election = :l, "
                        "next_latest_date = :n, rule = :r, source_url = :s, derived_at = now() "
                        "WHERE jurisdiction_code = :c AND verified_at IS NULL"),
                        {"l": u["last"], "n": u["next"], "r": u["rule"], "s": u["src"], "c": u["code"]})
        out["upserted"] = 0 if dry_run else len(updates)
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        logger.exception("%s failed", task)
    _heartbeat(engine, task, out, exc)
    return out
