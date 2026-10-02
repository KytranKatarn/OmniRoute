"""Provincial/territorial general-election history from Wikipedia (MediaWiki API).

No official feed exists; this is the same pragmatic pattern as cabinet.py (public page,
fail-soft, never wipe on a bad scrape). Titles are "<year> <Name> general election";
a year with no such article is simply absent. A page whose infobox does not parse or
is internally inconsistent is SKIPPED and counted, never written.

Rows land in parliament.election_history (source_url = the article, so every row is
traceable). `calendar.py` then rolls the calendar forward from the newest date here.
Run: python -m ingest.elections.wiki_history [--dry-run]   (needs WTF_DATABASE_URL)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sys
import urllib.parse
import urllib.request

from sqlalchemy import text

from .results import _heartbeat
from .wiki_parse import parse_election, parse_mayoral

logger = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
_UA = "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)"
FIRST_YEAR = 2005
NAMES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}


# Wikipedia names per canonical city slug (shared.city_identity). Both "municipal" and
# "mayoral" titles are tried; a title that does not exist is simply absent. Sydney NS is
# a community in Cape Breton Regional Municipality, not a municipality — no article, omitted.
MUNICIPAL = {
    "calgary": ["Calgary"], "edmonton": ["Edmonton"], "kelowna": ["Kelowna"],
    "vancouver": ["Vancouver"], "victoria": ["Victoria", "Victoria, British Columbia"],
    "winnipeg": ["Winnipeg"], "fredericton": ["Fredericton"], "moncton": ["Moncton"],
    "saint-john": ["Saint John", "Saint John, New Brunswick"], "st-johns": ["St. John's"],
    "halifax": ["Halifax"], "yellowknife": ["Yellowknife"], "iqaluit": ["Iqaluit"],
    "hamilton": ["Hamilton", "Hamilton, Ontario"], "london": ["London", "London, Ontario"],
    "ottawa": ["Ottawa"], "toronto": ["Toronto"], "windsor": ["Windsor", "Windsor, Ontario"],
    "charlottetown": ["Charlottetown"], "montreal": ["Montreal"],
    "quebec": ["Quebec City"], "regina": ["Regina"], "saskatoon": ["Saskatoon"],
    "whitehorse": ["Whitehorse"],
}


def municipal_titles(slug: str, today: dt.date) -> dict:
    return {f"{y} {n} {kind} election": y for y in range(FIRST_YEAR, today.year + 1)
            for n in MUNICIPAL[slug] for kind in ("municipal", "mayoral")}


def titles_for(code: str, today: dt.date) -> dict:
    return {f"{y} {NAMES[code]} general election": y for y in range(FIRST_YEAR, today.year + 1)}


def _fetch(titles: list[str]) -> dict:
    q = urllib.parse.urlencode({
        "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "redirects": 1, "format": "json", "formatversion": 2, "titles": "|".join(titles)})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    q = data.get("query", {})
    back = {}
    for key in ("normalized", "redirects"):
        for e in q.get(key, []):
            back[e["from"]] = e["to"]
    pages = {p["title"]: p for p in q.get("pages", [])}
    out = {}
    for t in titles:
        tt = t
        while tt in back:
            tt = back[tt]
        p = pages.get(tt)
        if p and not p.get("missing"):
            try:
                out[t] = (tt, p["revisions"][0]["slots"]["main"]["content"])
            except (KeyError, IndexError):
                pass
    return out


def collect(today: dt.date, fetch=_fetch) -> tuple[list[dict], list[str]]:
    rows, skipped = [], []
    for code in NAMES:
        titles = titles_for(code, today)
        for t, (real, wt) in fetch(list(titles)).items():
            rec = parse_election(wt, expect_year=titles[t])
            if rec is None:
                skipped.append(real)
                continue
            rec.update(code=code, source_url="https://en.wikipedia.org/wiki/" + real.replace(" ", "_"))
            rows.append(rec)
    for slug in MUNICIPAL:
        titles = municipal_titles(slug, today)
        seen = set()
        for t, (real, wt) in fetch(list(titles)).items():
            rec = parse_mayoral(wt, expect_year=titles[t])
            if rec is None:
                skipped.append(real)
                continue
            if rec["election_date"] in seen:      # municipal + mayoral titles redirect to one page
                continue
            seen.add(rec["election_date"])
            rec.update(code="MUN-" + slug,
                       source_url="https://en.wikipedia.org/wiki/" + real.replace(" ", "_"))
            rows.append(rec)
    return rows, skipped


def run_wiki_history(engine, dry_run: bool = False, fetch=_fetch) -> dict:
    task = "elections_history"
    out: dict = {}
    exc: Exception | None = None
    try:
        rows, skipped = collect(dt.date.today(), fetch)
        out.update(candidates=len(rows), skipped=len(skipped))
        if not rows:
            out["error"] = "no election articles parsed (API unreachable or page shape changed)"
        elif not dry_run:
            with engine.begin() as c:
                for r in rows:
                    c.execute(text("""
                        INSERT INTO parliament.election_history
                            (jurisdiction_code, election_date, turnout_pct, seats_total, results, source_url)
                        VALUES (:c, :d, :t, :s, CAST(:r AS jsonb), :u)
                        ON CONFLICT (jurisdiction_code, election_date) DO UPDATE
                           SET turnout_pct = EXCLUDED.turnout_pct, seats_total = EXCLUDED.seats_total,
                               results = EXCLUDED.results, source_url = EXCLUDED.source_url,
                               verified_at = now()"""),
                        {"c": r["code"], "d": r["election_date"], "t": r["turnout_pct"],
                         "s": r["seats_total"], "r": json.dumps(r["results"]), "u": r["source_url"]})
            out["upserted"] = len(rows)
        if skipped:
            logger.warning("elections_history: %d article(s) skipped: %s", len(skipped), "; ".join(skipped[:5]))
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        logger.exception("%s failed", task)
    if not dry_run:
        _heartbeat(engine, task, out, exc)
    return out


if __name__ == "__main__":
    import os
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["WTF_DATABASE_URL"])
    print(run_wiki_history(eng, dry_run="--dry-run" in sys.argv))
