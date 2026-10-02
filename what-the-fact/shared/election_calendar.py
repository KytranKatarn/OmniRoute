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
    derived = row.get("derived_at") is not None
    nxt = _d(row.get("next_latest_date"))
    out = {
        "code": row["jurisdiction_code"], "name": row["jurisdiction"], "level": row["level"],
        "rule": row.get("rule"), "source_url": row.get("source_url"),
        "province_code": row.get("province_code"),
        "last_election": None, "next_latest_date": None, "days_until": None,
        "government_party": None, "head_of_government": None,
        "status": "unverified", "stale": False,
    }
    if verified_at is None:
        # A rule-derived date (shared/election_rules.py) is shown, labelled "projected":
        # it is arithmetic on a statute rule, not a human-checked fact.
        if derived and nxt is not None:
            out["last_election"] = _d(row.get("last_election"))
            out["status"] = "overdue" if nxt < today else "projected"
            if nxt >= today:
                out["next_latest_date"], out["days_until"] = nxt, (nxt - today).days
        return out
    # Who governs is verified WITH the dates (one verified_at) and withheld with them.
    out["government_party"] = row.get("government_party")
    out["head_of_government"] = row.get("head_of_government")
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
    unverified = sorted(r["jurisdiction_code"] for r in rows
                        if r.get("verified_at") is None and r.get("derived_at") is None)
    if unverified:
        shown = ", ".join(unverified[:8]) + (" +%d more" % (len(unverified) - 8) if len(unverified) > 8 else "")
        msgs.append("election_calendar: %d row(s) unverified, date withheld (%s)"
                    % (len(unverified), shown))
    for r in rows:
        c = classify(r, today)
        if c["status"] == "overdue":
            msgs.append("election_calendar: %s latest date %s has PASSED — roll forward"
                        % (c["code"], _d(r["next_latest_date"])))
        elif c["status"] == "projected":
            continue
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


# ── Seats versus votes (federal, DERIVED from ingested results) ───────────────
def seats_vs_votes(rows: list[dict], min_vote_pct: float = 0.5) -> dict:
    """rows: (party, seats, votes) — seats = ELECTED candidates, votes = ALL candidates'
    votes for that party. Returns shares and the gap (seat share − vote share, points).

    A positive gap means the party holds a larger share of seats than of votes; it is
    arithmetic, not a verdict on the electoral system. Parties under ``min_vote_pct`` of
    the vote and with no seats are folded into "other" so the table stays readable; the
    folded vote share is reported, never dropped. Returns {} if there are no votes.
    """
    clean = [(r["party"], int(r.get("seats") or 0), int(r.get("votes") or 0))
             for r in rows if r.get("party")]
    total_votes = sum(v for _, _, v in clean)
    total_seats = sum(n for _, n, _ in clean)
    if total_votes <= 0 or total_seats <= 0:
        return {}
    out, other_votes = [], 0
    for party, seats, votes in sorted(clean, key=lambda x: (-x[1], -x[2], x[0])):
        vp = 100.0 * votes / total_votes
        if seats == 0 and vp < min_vote_pct:
            other_votes += votes
            continue
        sp = 100.0 * seats / total_seats
        out.append({"party": party, "seats": seats, "votes": votes,
                    "seat_pct": round(sp, 1), "vote_pct": round(vp, 1),
                    "gap": round(sp - vp, 1)})
    return {"parties": out, "total_seats": total_seats, "total_votes": total_votes,
            "other_vote_pct": round(100.0 * other_votes / total_votes, 1)}


# ── Curated history (provincial / municipal) ──────────────────────────────────
def curated_history(rows: list[dict], last_n: int = 5) -> dict:
    """{jurisdiction_code: [newest-first rows, at most last_n]} from election_history.
    The table only ever holds verified, sourced rows (NOT NULL source_url + verified_at),
    so there is no unverified state to hide here."""
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["jurisdiction_code"], []).append({
            "date": _d(r["election_date"]), "turnout_pct": r.get("turnout_pct"),
            "seats_total": r.get("seats_total"), "source_url": r.get("source_url"),
            "results": sorted(r.get("results") or [], key=lambda x: (-int(x.get("seats") or 0), -int(x.get("votes") or 0),
                                                                      str(x.get("party") or x.get("candidate")))),
        })
    return {k: sorted(v, key=lambda x: x["date"], reverse=True)[:last_n] for k, v in by.items()}


# ── Admin-tool validation (scripts/elections_admin.py) ────────────────────────
class ValidationError(ValueError):
    pass


def _need_source(url) -> str:
    u = (url or "").strip()
    if not (u.startswith("https://") and len(u) > len("https://x.y")):
        raise ValidationError("a source URL (https://…) is required — no source, no row")
    return u


def validate_calendar_update(*, last_election, next_latest_date, rule, source_url,
                             today: dt.date | None = None) -> dict:
    """Checks a human-entered verification BEFORE it is written with verified_at=now()."""
    today = today or dt.date.today()
    last = dt.date.fromisoformat(str(last_election))
    nxt = dt.date.fromisoformat(str(next_latest_date))
    if last > today:
        raise ValidationError("last_election %s is in the future" % last)
    if nxt <= last:
        raise ValidationError("next_latest_date %s must be after last_election %s" % (nxt, last))
    if nxt < today:
        raise ValidationError("next_latest_date %s has already passed — enter the NEXT date" % nxt)
    if (nxt - last).days > 366 * 6:
        raise ValidationError("%d years between elections is implausible — check the dates"
                              % ((nxt - last).days // 365))
    if not (rule or "").strip():
        raise ValidationError("a rule (statute and section, in words) is required")
    return {"last_election": last, "next_latest_date": nxt, "rule": rule.strip(),
            "source_url": _need_source(source_url)}


def validate_history_row(*, election_date, results, source_url, seats_total=None,
                         turnout_pct=None, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    d = dt.date.fromisoformat(str(election_date))
    if d > today:
        raise ValidationError("election_date %s is in the future" % d)
    if not results:
        raise ValidationError("results must list at least one party")
    seats = 0
    for r in results:
        if not str(r.get("party") or "").strip():
            raise ValidationError("every result needs a party")
        n = int(r.get("seats", -1))
        if n < 0:
            raise ValidationError("%s: seats must be a non-negative integer" % r.get("party"))
        seats += n
    if seats_total is not None and int(seats_total) != seats:
        raise ValidationError("seats_total %s does not equal the sum of party seats %s"
                              % (seats_total, seats))
    if turnout_pct is not None and not (0 < float(turnout_pct) <= 100):
        raise ValidationError("turnout_pct must be in (0, 100]")
    return {"election_date": d, "results": results, "seats_total": seats_total,
            "turnout_pct": turnout_pct, "source_url": _need_source(source_url)}
