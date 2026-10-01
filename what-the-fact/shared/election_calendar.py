"""PURE election-calendar logic (no DB, no Flask) — shared by the /elections page
and the drift guard so both apply ONE definition of "this row is trustworthy".

The calendar is a CURATED reference table (parliament.election_calendar): no feed
publishes "latest legal date for each legislature". Hand-curated dates are the
failure mode, so the rules below make a wrong or stale date impossible to show
quietly:

  unverified  verified_at IS NULL            -> the date is NOT shown at all
  overdue     verified, latest date passed   -> "awaiting roll-forward", no countdown
  stale       verified_at older than 180d    -> shown, flagged, and alarmed
  upcoming    verified, latest date ahead    -> days remaining computed at read time

`days_until` is computed at read time and never stored, so it cannot go stale.
"""
from __future__ import annotations

import datetime as dt

VERIFY_STALE_DAYS = 180


def _d(v):
    if isinstance(v, dt.datetime):
        return v.date()
    return v


def classify(row: dict, today: dt.date) -> dict:
    """Row in, display dict out. Dates of unverified rows are withheld."""
    verified_at = _d(row.get("verified_at"))
    nxt = _d(row.get("next_latest_date"))
    out = {
        "code": row["jurisdiction_code"], "name": row["jurisdiction"], "level": row["level"],
        "rule": row.get("rule"), "source_url": row.get("source_url"),
        "last_election": None, "next_latest_date": None, "days_until": None,
        "status": "unverified", "stale": False,
    }
    if verified_at is None:
        return out
    out["last_election"] = _d(row.get("last_election"))
    out["stale"] = (today - verified_at).days > VERIFY_STALE_DAYS
    if nxt is None:
        out["status"] = "unverified"
        return out
    if nxt < today:
        out["status"] = "overdue"
        return out
    out["status"] = "upcoming"
    out["next_latest_date"] = nxt
    out["days_until"] = (nxt - today).days
    return out


def calendar_view(rows: list[dict], today: dt.date) -> list[dict]:
    """Classified rows, soonest first; rows without a shown date sort last."""
    out = [classify(r, today) for r in rows]
    out.sort(key=lambda r: (r["days_until"] is None, r["days_until"] or 0, r["name"]))
    return out


def problems(rows: list[dict], today: dt.date) -> list[str]:
    """Drift-guard problems. Empty list = calendar is trustworthy. An EMPTY table
    is a problem too (never seeded / migration not applied)."""
    if not rows:
        return ["election_calendar: table is empty (migration 085 not applied?)"]
    msgs = []
    unverified = [r["jurisdiction_code"] for r in rows if r.get("verified_at") is None]
    if unverified:
        msgs.append("election_calendar: %d row(s) unverified, date withheld (%s)"
                    % (len(unverified), ", ".join(sorted(unverified))))
    for r in rows:
        c = classify(r, today)
        if c["status"] == "overdue":
            msgs.append("election_calendar: %s latest date %s has PASSED — roll forward"
                        % (c["code"], _d(r["next_latest_date"])))
        elif c["stale"]:
            msgs.append("election_calendar: %s verified %s, > %dd ago — re-verify"
                        % (c["code"], _d(r["verified_at"]), VERIFY_STALE_DAYS))
    return msgs
