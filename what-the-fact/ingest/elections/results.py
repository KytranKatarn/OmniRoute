"""Fetch + persist Elections Canada general-election results.

Same shape as ingest/weather/cwfis.py: discovery → fetch → pure parse → upsert →
heartbeat on BOTH paths, and the entry point never raises. A dead ingest must
alarm through its heartbeat, not take the loop down with it.

Parsing lives in results_parse.py (stdlib-only, no DB, no network) so its guard
tests cannot silently SKIP on a box without psycopg2 — KB #290497.

SOURCE. open.canada.ca CKAN, org `elections`.
  package_search  -> the "<n>th General Election: Official Voting Results" dataset
  package_show    -> its resources
  Table 12        -> one row per candidate

🔴 HOST ALLOWLIST IS LOAD-BEARING, NOT DEFENSIVE DECORATION.
CKAN resource URLs do NOT all live on open.canada.ca. GE43/GE44 do, but **GE42's
point back to www.elections.ca**, whose robots.txt returns HTTP 500 — RFC 9309
says a 5xx there means assume COMPLETE DISALLOW. So "it came from CKAN" is not
permission to fetch the bytes; the resource HOST is what decides. A resource on
a disallowed host is skipped and reported, never fetched.

🔴 THE WINNER IS THE MAJORITY COLUMN, NOT THE `**` MARKER — see results_parse.py
and KB mistake #301957. This module persists `incumbent` and `elected` as
separate facts and refuses to write a district whose two winner signals disagree.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request

from sqlalchemy import text

from .results_parse import parse_table12

logger = logging.getLogger(__name__)

CKAN = "https://open.canada.ca/data/api/3/action"
_ALLOWED_HOSTS = {"open.canada.ca"}
_UA = "what-the-fact.com newsroom ingest (+https://what-the-fact.com/methodology)"
_TIMEOUT = 120

# Polling day per general election. Historical fact, not derivable from Table 12,
# and left NULL rather than guessed for any election not listed here.
_ELECTION_DATES = {
    44: "2021-09-20",
    43: "2019-10-21",
    42: "2015-10-19",
    41: "2011-05-02",
    40: "2008-10-14",
    39: "2006-01-23",
    38: "2004-06-28",
}


def _get(url: str) -> bytes:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in _ALLOWED_HOSTS:
        # Not an exception: a disallowed host is an expected, reportable
        # condition (GE42), and raising would make one old election able to
        # fail the whole run.
        raise PermissionError(f"host not allowed: {host}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read()


def _json(url: str) -> dict:
    import json

    return json.loads(_get(url).decode("utf-8"))


def find_table(ge_number: int, table_label: str = "table 12") -> dict:
    """Locate one CSV resource by its table label for a general election.

    Returns {"url", "dataset_id", "title"} or {"error": ...}. Never raises.
    """
    try:
        q = urllib.parse.quote(f'organization:elections AND title:"Official Voting Results"')
        found = _json(f"{CKAN}/package_search?q={q}&rows=40").get("result", {})
        for d in found.get("results", []):
            title = (d.get("title_translated", {}) or {}).get("en") or d.get("title") or ""
            # "44th General Election: Official Voting Results"
            if not title.lower().startswith(f"{ge_number}th") and \
               not title.lower().startswith(f"{ge_number}nd") and \
               not title.lower().startswith(f"{ge_number}rd") and \
               not title.lower().startswith(f"{ge_number}st"):
                continue
            for res in d.get("resources", []):
                if (res.get("format") or "").upper() != "CSV":
                    continue
                name = (res.get("name_translated", {}) or {}).get("en") or res.get("name") or ""
                if table_label not in name.lower():
                    continue
                url = res.get("url") or ""
                host = urllib.parse.urlparse(url).hostname or ""
                if host not in _ALLOWED_HOSTS:
                    return {"error": f"GE{ge_number} {table_label} is hosted on {host}, "
                                     f"which is not fetchable (see module docstring)"}
                return {"url": url, "dataset_id": d.get("id"), "title": title}
        return {"error": f"no {table_label} resource found for GE{ge_number}"}
    except Exception as exc:  # discovery must not raise into the caller
        return {"error": f"discovery failed: {exc}"}


def _upsert(engine, ge_number: int, dataset_id: str, source_url: str, rep) -> dict:
    with engine.begin() as c:
        eid = c.execute(text("""
            INSERT INTO parliament.elections (ge_number, election_date, dataset_id, source_url)
            VALUES (:g, CAST(:d AS date), :ds, :u)
            ON CONFLICT (ge_number) DO UPDATE
               SET dataset_id = EXCLUDED.dataset_id,
                   source_url = EXCLUDED.source_url,
                   election_date = COALESCE(EXCLUDED.election_date,
                                            parliament.elections.election_date),
                   updated_at = now()
            RETURNING id
        """), {"g": ge_number, "d": _ELECTION_DATES.get(ge_number),
               "ds": dataset_id, "u": source_url}).scalar()

        # REPLACE, don't upsert. Table 12 is a complete snapshot of one
        # election, so the file is authoritative for the whole set.
        #
        # ⚠️ An ON CONFLICT key that includes a PARSED field is unstable: when
        # the candidate-name parse was corrected, the fixed names no longer
        # collided with the broken ones and a re-run ADDED 1,007 rows instead of
        # replacing them — 5,163 candidates where the source has 4,156, and 672
        # distinct "parties". The stale rows were invisible in the return value
        # (upserted: 2010, error: None) and only showed up in the data.
        # Deleting first makes a re-parse idempotent by construction. Same
        # transaction, so a failed insert cannot leave the election empty.
        c.execute(text("DELETE FROM parliament.election_candidates "
                       "WHERE election_id = :e"), {"e": eid})
        n = 0
        for cand in rep.candidates:
            c.execute(text("""
                INSERT INTO parliament.election_candidates
                    (election_id, district_number, district_name, province,
                     candidate_name, party, party_raw, incumbent, votes,
                     vote_share, majority, elected)
                VALUES (:e, :dn, :dname, :prov, :name, :party, :praw, :inc,
                        :votes, :share, :maj, :elected)
                ON CONFLICT (election_id, district_number, candidate_name, party) DO UPDATE
                   SET party = EXCLUDED.party, party_raw = EXCLUDED.party_raw,
                       incumbent = EXCLUDED.incumbent, votes = EXCLUDED.votes,
                       vote_share = EXCLUDED.vote_share, majority = EXCLUDED.majority,
                       elected = EXCLUDED.elected, district_name = EXCLUDED.district_name,
                       province = EXCLUDED.province
            """), {"e": eid, "dn": cand.district_number, "dname": cand.district_name,
                   "prov": cand.province, "name": cand.name, "party": cand.party,
                   "praw": cand.party_raw, "inc": cand.incumbent, "votes": cand.votes,
                   "share": cand.vote_share, "maj": cand.majority,
                   "elected": cand.elected})
            n += 1
    return {"election_id": eid, "upserted": n}


def _heartbeat(engine, task: str, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log row on BOTH paths — including a SWALLOWED
    {"error": ...} return. A swallowed error that never reaches the log is how
    an ingest rots for months while every dashboard stays green."""
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES (:t, :f, :u)"),
                    {"t": task, "f": int(result.get("candidates") or 0),
                     "u": int(result.get("upserted") or 0)})
            else:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task, "e": str(exc or swallowed)[:500]})
    except Exception:
        logger.exception("%s heartbeat write failed", task)


def run_election_results(engine, ge_number: int = 44, dry_run: bool = False) -> dict:
    """Ingest one general election. Never raises."""
    task = "elections_results"
    out: dict = {"ge": ge_number}
    exc: Exception | None = None
    try:
        loc = find_table(ge_number, "table 12")
        if loc.get("error"):
            out.update(loc)
        else:
            # The party vocabulary is derived from Table 12 itself — Table 9
            # carries REGISTERED names where Table 12 carries BALLOT names, so
            # it is the wrong list (1,715 of 2,010 cells did not match it).
            rep = parse_table12(_get(loc["url"]).decode("utf-8-sig"))
            out.update(candidates=len(rep.candidates), districts=rep.districts,
                       winners=rep.winners, incumbents=rep.incumbents,
                       anomalies=len(rep.anomalies),
                       party_unresolved=len(rep.party_unresolved))
            if rep.party_unresolved:
                # Reported, not fatal: a party fielding a single candidate has
                # no derivable name boundary. Withholding 338 real results over
                # one minor-party row would be the wrong trade.
                logger.warning("GE%s: %d candidate(s) with unresolved party: %s",
                               ge_number, len(rep.party_unresolved),
                               "; ".join(rep.party_unresolved[:3]))
            if rep.anomalies:
                # The two winner signals disagreed, or a district had no single
                # winner. That means the file changed shape — refuse to write a
                # result set that could name the wrong MP, and say so loudly.
                out["error"] = ("refusing to persist: " + "; ".join(rep.anomalies[:3]))
            elif rep.districts and rep.winners != rep.districts:
                out["error"] = (f"refusing to persist: {rep.winners} winners for "
                                f"{rep.districts} districts")
            elif not dry_run:
                out.update(_upsert(engine, ge_number, loc.get("dataset_id"),
                                   loc.get("url"), rep))
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        logger.exception("%s failed", task)
    _heartbeat(engine, task, out, exc)
    logger.info("%s: %s", task, out)
    return out
