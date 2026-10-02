"""PURE fixed-date election rules (no DB, no network) — the calendar's automatic path.

No feed publishes "latest legal date per legislature", but most Canadian
legislatures fix it by statute as "the Nth <weekday> of <month> in the 4th calendar
year after the last general election". Given the last election that is arithmetic,
so the ingest (ingest/elections/calendar.py) COMPUTES it and the calendar rolls
forward by itself once a newer election date is known.

Honesty rules (same as shared/election_calendar.py):
  * a computed date is "projected", never "verified" — verified_at stays NULL until a
    human checks the statute (scripts/elections_admin.py verify);
  * a jurisdiction whose rule is NOT fixed-date (AB, NS, NT, YT, NU) has NO entry here
    and stays manual — we never invent a rule to fill a cell;
  * ANCHORS are the last general-election dates used ONLY when nothing ingested is
    newer; they are typed-in reference values and are labelled as such.
"""
from __future__ import annotations

import datetime as dt

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
LAST = -1

# code -> (month, weekday, nth, years_after, rule text, source_url)
RULES = {
    "CA": (10, MON, 3, 4, "Canada Elections Act s.56.1(2): third Monday of October in the 4th calendar year after the last general election",
           "https://laws-lois.justice.gc.ca/eng/acts/E-2.01/"),
    "ON": (6, THU, 1, 4, "Election Act (Ontario) s.9: first Thursday in June in the 4th calendar year after the last general election",
           "https://www.elections.on.ca/"),
    "BC": (10, SAT, 3, 4, "Constitution Act (BC) s.23: third Saturday in October in the 4th calendar year after the last general election",
           "https://elections.bc.ca/"),
    "QC": (10, MON, 1, 4, "Election Act (Québec) s.6: first Monday in October in the 4th calendar year after the last general election",
           "https://www.electionsquebec.qc.ca/"),
    "MB": (10, TUE, 1, 4, "Elections Act (Manitoba): first Tuesday in October in the 4th calendar year after the last general election",
           "https://electionsmanitoba.ca/"),
    "SK": (10, MON, LAST, 4, "Legislative Assembly Act (Saskatchewan): last Monday in October in the 4th calendar year after the last general election",
           "https://www.elections.sk.ca/"),
    "NB": (10, MON, 3, 4, "Legislative Assembly Act (New Brunswick): third Monday in October in the 4th calendar year after the last general election",
           "https://www.electionsnb.ca/"),
    "PE": (10, MON, 1, 4, "Election Act (Prince Edward Island): first Monday in October in the 4th calendar year after the last general election",
           "https://www.electionspei.ca/"),
    "NL": (10, TUE, 2, 4, "House of Assembly Act (Newfoundland and Labrador): second Tuesday in October in the 4th calendar year after the last general election",
           "https://www.elections.gov.nl.ca/"),
}

# Last general election per jurisdiction — a typed-in reference, used only when the
# database holds nothing newer (a federal GE comes from the ingested results).
ANCHORS = {
    "CA": "2025-04-28", "ON": "2025-02-27", "BC": "2024-10-19", "QC": "2022-10-03",
    "MB": "2023-10-03", "SK": "2024-10-28", "NB": "2024-10-21", "PE": "2023-04-03",
    "NL": "2025-10-14",
}


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> dt.date:
    """nth (1-based) weekday of a month; nth == -1 is the last one."""
    if nth == LAST:
        d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
        return d - dt.timedelta(days=(d.weekday() - weekday) % 7)
    first = dt.date(year, month, 1)
    d = first + dt.timedelta(days=(weekday - first.weekday()) % 7)
    return d + dt.timedelta(weeks=nth - 1)


def next_latest_date(code: str, last_election) -> dt.date | None:
    """Latest legal date of the next general election, or None when ``code`` has no
    encoded fixed-date rule (the caller must leave that row manual)."""
    rule = RULES.get(code)
    if rule is None or last_election is None:
        return None
    if isinstance(last_election, str):
        last_election = dt.date.fromisoformat(last_election)
    if isinstance(last_election, dt.datetime):
        last_election = last_election.date()
    month, wd, nth, years, _, _ = rule
    return nth_weekday(last_election.year + years, month, wd, nth)


def anchor_for(code: str, db_last=None, history_last=None) -> dt.date | None:
    """Newest known last-election date: ingested/curated beats the typed anchor."""
    cands = [d for d in (db_last, history_last) if d]
    a = ANCHORS.get(code)
    if a:
        cands.append(dt.date.fromisoformat(a))
    cands = [c.date() if isinstance(c, dt.datetime) else c for c in cands]
    return max(cands) if cands else None
