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


# ── Federal election history ────────────────────────────────────────────────
# Polling day per general election — historical fact, NOT derivable from the results
# tables and left absent for any election not listed (never guessed). ONE definition:
# the ingest (ingest/elections/results.py) and the /elections history both read it.
FEDERAL_ELECTION_DATES = {
    45: "2025-04-28",
    44: "2021-09-20",
    43: "2019-10-21",
    42: "2015-10-19",
    41: "2011-05-02",
    40: "2008-10-14",
    39: "2006-01-23",
    38: "2004-06-28",
}


def federal_history(db_rows: list[dict], last_n: int = 5, known: dict | None = None) -> list[dict]:
    """The last ``last_n`` federal elections, each marked held / not_held.

    ``db_rows``: (ge_number, election_date, party, seats) — ELECTED candidates only,
    one row per party per election. An election with no rows is ``not_held`` and is
    still listed: a gap the reader can see beats a table that silently starts later.
    Nothing here is typed in; seats come from the ingested results.
    """
    known = known or FEDERAL_ELECTION_DATES
    by: dict[int, dict] = {}
    for r in db_rows:
        g = int(r["ge_number"])
        e = by.setdefault(g, {"date": _d(r.get("election_date")), "parties": []})
        if r.get("party"):
            e["parties"].append((r["party"], int(r["seats"])))
    nums = sorted(set(known) | set(by), reverse=True)[:last_n]
    out = []
    for g in nums:
        e = by.get(g)
        parties = sorted(e["parties"], key=lambda x: (-x[1], x[0])) if e else []
        iso = known.get(g)
        out.append({
            "ge": g,
            "date": (e["date"] if e and e["date"] else (dt.date.fromisoformat(iso) if iso else None)),
            "status": "held" if parties else "not_held",
            "seats": sum(n for _, n in parties),
            "parties": parties,
        })
    return out
