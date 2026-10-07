"""MP stints with their party — the dated history behind party-switch tracking and cost attribution.

WHY THIS EXISTS. parliament.mps keeps one party per person (the current one) and only the sitting
members; mp_movements only records changes seen since we started watching. So "which party carried this
MP's costs in 2009" and "when did this MP cross the floor" were unanswerable. The House's own member list
does not fix it: it returns ONE record per person — their latest stint (measured 2026-10-06: 1,236
persons, none with a second record; Chris d'Entremont's House profile shows only "Liberal"). openparliament.ca
exposes dated stints split on every party change, back to 1994:

    Conservative  2019-10-21 .. 2025-04-28  West Nova
    Conservative  2025-04-28 .. 2025-11-04  Acadie—Annapolis
    Liberal       2025-11-05 ..             Acadie—Annapolis

CUTOFF: owner decision 2026-10-06 — nothing that ended before 2000-01-01 is stored (CUTOFF below).

Former MPs are added to parliament.mps as is_current=false rows (they are needed to attach historical
expenses to a person). Sitting members are never modified here; the openparl sync owns them.

Politeness: openparliament.ca is a volunteer service — one request at a time, ~0.6s apart, and the weekly
run refreshes only the sitting members (~340), not all ~1,300 politicians.

Run: python -m ingest.parliament.mp_terms            # full backfill (~15 min)
     python -m ingest.parliament.mp_terms --current  # sitting members only (weekly)
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
import urllib.request
from datetime import date

from sqlalchemy import text

from ingest.parliament._retry import fetch_with_retry

logger = logging.getLogger("wtf-ingest.mp_terms")

CUTOFF = date(2000, 1, 1)
_API = "https://api.openparliament.ca"
_HEADERS = {"User-Agent": "WTFIngest (+https://what-the-fact.com)", "Accept": "application/json"}
_SLEEP = 0.6


def _get_json(path: str, timeout: int = 40):
    def _once():
        req = urllib.request.Request(_API + path, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    return fetch_with_retry(_once, label="mp_terms " + path[-40:])


def _d(value):
    """'2025-11-05' -> date; None/'' -> None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _en(node):
    """{'en': 'Liberal'} or {'name': {'en': ...}} tolerant extraction."""
    if isinstance(node, dict):
        return node.get("en")
    return node if isinstance(node, str) else None


def parse_terms(detail: dict, slug: str) -> list[dict]:
    """The dated stints in one politician's record. Pure; tolerant of missing pieces."""
    out = []
    name = detail.get("name") or slug
    for m in detail.get("memberships") or []:
        start = _d(m.get("start_date"))
        if start is None:
            continue
        party = m.get("party") or {}
        riding = m.get("riding") or {}
        mid = re.search(r"/memberships/(\d+)/", m.get("url") or "")
        out.append({
            "op_slug": slug,
            "op_membership_id": int(mid.group(1)) if mid else None,
            "name": name,
            "party": _en(party.get("short_name")) or _en(party.get("name")),
            "riding": _en(riding.get("name")),
            "province": riding.get("province") if isinstance(riding, dict) else None,
            "start_date": start,
            "end_date": _d(m.get("end_date")),
            "source_url": f"https://openparliament.ca/politicians/{slug}/",
        })
    return out


def within_cutoff(term: dict, cutoff: date = CUTOFF) -> bool:
    """Keep a stint that was still running on or after the cutoff (open-ended stints always qualify)."""
    return term["end_date"] is None or term["end_date"] >= cutoff


def party_changes(terms: list[dict]) -> list[dict]:
    """Dated party changes within one person's stints (mirror of parliament.v_mp_party_changes)."""
    ordered = sorted(terms, key=lambda t: (t["start_date"], t.get("end_date") or date.max))
    changes = []
    for prev, cur in zip(ordered, ordered[1:]):
        if prev["party"] and cur["party"] and prev["party"] != cur["party"]:
            gap = (cur["start_date"] - prev["end_date"]).days if prev["end_date"] else None
            changes.append({"changed_on": cur["start_date"], "from_party": prev["party"],
                            "to_party": cur["party"], "gap_days": gap})
    return changes


def _slug_ok(slug: str) -> bool:
    return bool(slug) and bool(re.fullmatch(r"[a-z0-9-]+", slug))


def former_mp_row(detail: dict, slug: str, terms: list[dict]) -> dict | None:
    """The parliament.mps row for a former MP (is_current=false). None if it cannot be built safely."""
    if not terms or not _slug_ok(slug):
        return None
    last = max(terms, key=lambda t: (t["start_date"], t["end_date"] or date.max))
    info = detail.get("other_info") or {}
    pid = info.get("parl_mp_id")
    return {
        "slug": slug,
        "name": detail.get("name") or slug,
        "given": detail.get("given_name"),
        "family": detail.get("family_name"),
        "party": last["party"],
        "riding": last["riding"],
        "prov": (last["province"] or None) if last["province"] and len(last["province"]) == 2 else None,
        # mps.parl_mp_id stores the list repr "['84672']" for every row (committees.py digs digit-runs out).
        "pid": str(pid) if pid else None,
        "url": f"https://openparliament.ca/politicians/{slug}/",
    }


def _upsert_terms(c, terms: list[dict]) -> int:
    n = 0
    for t in terms:
        c.execute(text("""
            INSERT INTO parliament.mp_terms
                (op_slug, op_membership_id, name, party, riding, province, start_date, end_date, source_url)
            VALUES (:op_slug, :op_membership_id, :name, :party, :riding, :province, :start_date, :end_date, :source_url)
            ON CONFLICT (op_slug, start_date, riding, party) DO UPDATE SET
                end_date = EXCLUDED.end_date, name = EXCLUDED.name,
                op_membership_id = EXCLUDED.op_membership_id, synced_at = now()"""), t)
        n += 1
    return n


def run_mp_terms_sync(engine, only_current: bool = False, add_former: bool = True,
                      sleep: float = _SLEEP, limit: int | None = None, get_json=_get_json) -> dict:
    """Fetch stints for every politician (or just the sitting ones), store them, link them to parliament.mps."""
    with engine.connect() as c:
        mps = {r[0]: (r[1], r[2]) for r in c.execute(text(
            "SELECT slug, id, is_current FROM parliament.mps")).fetchall()}

    listing, path = [], "/politicians/?format=json&limit=500&include=all"
    while path:
        page = get_json(path)
        listing += page.get("objects", [])
        path = (page.get("pagination") or {}).get("next_url")
        time.sleep(sleep)
    slugs = [(p.get("url") or "").strip("/").split("/")[-1] for p in listing]
    slugs = [s for s in slugs if s]
    if only_current:
        slugs = [s for s in slugs if mps.get(s, (None, False))[1]]
    if limit:
        slugs = slugs[:limit]

    stats = {"listed": len(listing), "fetched": 0, "terms": 0, "former_added": 0, "skipped_pre_cutoff": 0,
             "fetch_failed": [], "unlinked": 0}
    for slug in slugs:
        try:
            detail = get_json(f"/politicians/{slug}/?format=json")
        except Exception as exc:  # one bad politician must not abort the run
            stats["fetch_failed"].append(slug)
            logger.warning("mp_terms: %s failed: %s", slug, exc)
            time.sleep(sleep)
            continue
        stats["fetched"] += 1
        terms = [t for t in parse_terms(detail, slug) if within_cutoff(t)]
        if not terms:
            stats["skipped_pre_cutoff"] += 1
            time.sleep(sleep)
            continue
        with engine.begin() as c:
            if slug not in mps and add_former:
                row = former_mp_row(detail, slug, terms)
                if row and terms and all(t["end_date"] for t in terms):   # only people who have left
                    got = c.execute(text("""
                        INSERT INTO parliament.mps
                            (slug, name, given_name, family_name, party, riding_name, province_code,
                             parl_mp_id, openparl_url, is_current)
                        VALUES (:slug, :name, :given, :family, :party, :riding, :prov, :pid, :url, false)
                        ON CONFLICT (slug) DO NOTHING RETURNING id"""), row).scalar()
                    if got:
                        mps[slug] = (got, False)
                        stats["former_added"] += 1
            stats["terms"] += _upsert_terms(c, terms)
            if slug in mps:
                c.execute(text("UPDATE parliament.mp_terms SET mp_id = :m WHERE op_slug = :s AND mp_id IS DISTINCT FROM :m"),
                          {"m": mps[slug][0], "s": slug})
            else:
                stats["unlinked"] += 1
        time.sleep(sleep)

    if stats["terms"] == 0:
        stats["error"] = "mp_terms stored 0 stints — the openparliament.ca API may have changed"
        logger.error(stats["error"])
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted, error) "
                           "VALUES ('mp_terms', :f, :u, :e)"),
                      {"f": stats["fetched"], "u": stats["terms"], "e": stats.get("error")})
    except Exception as exc:
        logger.warning("mp_terms: ingest_log write failed: %s", exc)
    return stats


if __name__ == "__main__":
    import os
    import sys
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    print(run_mp_terms_sync(eng, only_current="--current" in sys.argv))
