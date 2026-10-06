"""committees.py — House of Commons committee membership ingest (ourcommons.ca).

Fills parliament.mp_committees, which had ZERO rows since inception (#5728 —
the Senate side has had committees for months; the House side simply never
had a scraper). ourcommons.ca is server-rendered and NOT bot-walled, so this
runs in the wtf-ingest container on the normal weekly phase-3 loop.

Flow:
  1. GET /Committees/en/List → the 30 top-level committees (accordion
     headings id="heading-<ABBR>"; subcommittees never appear as headings,
     so they are excluded by construction).
  2. GET /Committees/en/<ABBR>/Members per committee → member profile links
     carry the ourcommons person id ("/members/en/Karina-Gould(88715)"),
     with role derived from the section marker (id="committee-chair" /
     "committee-vice-chairs" / "committee-members[-only]") preceding each
     link. Verified against live FINA 2026-08-18: 1 chair / 2 vice-chairs /
     9 members.
  3. Match to parliament.mps by the ourcommons id in mps.parl_mp_id — exact
     ID matching, no name heuristics (parl_mp_id is populated for all 339
     current MPs, stored as the string "['88715']").
  4. Mark-and-sweep upsert: present pairs upserted is_current=true, absent
     pairs flipped is_current=false (membership churns mid-session).

Known gap (accepted v1): the four JOINT House–Senate committees (AMAD, BCAN,
BILI, REGS) 404 on /Committees/en/<ABBR>/Members — they are hosted on the
parl.ca joint-committee site with a different URL shape. They log a warning
and are skipped (26/30 committees, 318 memberships, 0 unmatched on the
2026-08-18 dry-run).

Run: python -m ingest.parliament.committees [--dry-run]
"""
import logging
import os
import re
import time
import urllib.request

from sqlalchemy import create_engine, text

from ingest.parliament._retry import fetch_with_retry

logger = logging.getLogger("wtf-ingest.committees")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_BASE = "https://www.ourcommons.ca"
_LIST_URL = f"{_BASE}/Committees/en/List"
_HEADERS = {"User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)"}
_PAGE_SLEEP = 0.5

_HEADING_RE = re.compile(
    r'id="heading-([A-Z]{3,5})".*?aria-controls="[^"]*"[^>]*>\s*(.*?)\s*</a>', re.S)
_MEMBER_LINK_RE = re.compile(r'href="[^"]*?/members/en/[a-z0-9-]+?\((\d+)\)"', re.I)
_SECTION_RE = re.compile(r'id="committee-([a-z-]+)"')
_ROLE_MAP = {"chair": "chair", "vice-chairs": "vice-chair",
             "members": "member", "members-only": "member"}


def _fetch(url: str) -> str:
    def _once() -> str:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    # A short ourcommons.ca outage (403 on the list page, 2026-10-04) must not become a "last run FAILED" row.
    return fetch_with_retry(_once, label="committees " + url[-40:])


def _parse_committee_list(html: str) -> list[tuple[str, str]]:
    """[(abbr, display_name)] from the accordion headings. The heading text
    leads with the abbr ('FINA Finance') — strip that token."""
    out = []
    for abbr, inner in _HEADING_RE.findall(html):
        name = re.sub(r"<[^>]+>", " ", inner)
        name = re.sub(r"\s+", " ", name).strip()
        if name.startswith(abbr):
            name = name[len(abbr):].strip()
        out.append((abbr, name or abbr))
    return out


def _parse_members(html: str) -> dict[str, str]:
    """{ourcommons_person_id: role} — role from the nearest preceding
    section marker; links before any marker default to 'member'."""
    markers = [(m.start(), m.group(1)) for m in _SECTION_RE.finditer(html)]
    roles: dict[str, str] = {}
    for m in _MEMBER_LINK_RE.finditer(html):
        role = "member"
        for mpos, sec in markers:
            if mpos < m.start():
                role = _ROLE_MAP.get(sec, "member")
        roles.setdefault(m.group(1), role)
    return roles


def _mp_id_index(engine) -> dict[str, int]:
    """{ourcommons_id: mp_db_id}. mps.parl_mp_id stores "['88715']" — pull
    every digit-run out rather than assuming the wrapper format."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, parl_mp_id FROM parliament.mps WHERE parl_mp_id IS NOT NULL"
        )).fetchall()
    idx: dict[str, int] = {}
    for mp_id, raw in rows:
        for tok in re.findall(r"\d{3,}", raw or ""):
            idx[tok] = mp_id
    return idx


def run_committees_sync(engine, dry_run: bool = False) -> dict:
    """Scrape all committees' member rosters and mark-and-sweep mp_committees."""
    try:
        committees = _parse_committee_list(_fetch(_LIST_URL))
    except Exception as exc:
        return {"error": f"committee list fetch failed: {exc}"}
    if not committees:
        return {"error": "no committees parsed from the List page — markup changed?"}
    logger.info("committees: %d top-level committees", len(committees))

    idx = _mp_id_index(engine)
    present: list[dict] = []
    unmatched = 0
    fetch_failed = 0
    for abbr, name in committees:
        try:
            roles = _parse_members(_fetch(f"{_BASE}/Committees/en/{abbr}/Members"))
        except Exception as exc:
            logger.warning("committees: %s members fetch failed: %s", abbr, exc)
            fetch_failed += 1
            continue
        for person_id, role in roles.items():
            mp_id = idx.get(person_id)
            if not mp_id:
                unmatched += 1     # e.g. a member who just resigned their seat
                continue
            present.append({"mid": mp_id, "abbr": abbr, "name": name, "role": role})
        time.sleep(_PAGE_SLEEP)

    result = {"fetched": len(committees), "memberships": len(present),
              "unmatched": unmatched, "fetch_failed": fetch_failed}
    if not present:
        return {"error": f"0 memberships parsed across {len(committees)} committees — markup changed?"}
    if dry_run:
        logger.info("committees DRY RUN: %s", result)
        return result

    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO parliament.mp_committees
                (member_id, committee_abbr, committee_name, role, is_current)
            VALUES (:mid, :abbr, :name, :role, true)
            ON CONFLICT (member_id, committee_abbr) DO UPDATE SET
                committee_name = EXCLUDED.committee_name,
                role = EXCLUDED.role,
                is_current = true
        """), present)
        # Sweep: pairs no longer on any roster page go historical, not deleted.
        # VALUES list is fully bound-parameterized — never interpolate into SQL.
        placeholders = ",".join(f"(:m{i}, :a{i})" for i in range(len(present)))
        sweep_params = {}
        for i, r in enumerate(present):
            sweep_params[f"m{i}"] = r["mid"]
            sweep_params[f"a{i}"] = r["abbr"]
        swept = c.execute(text(f"""
            UPDATE parliament.mp_committees mc SET is_current = false
            WHERE mc.is_current
              AND NOT EXISTS (
                  SELECT 1 FROM (VALUES {placeholders}) AS p(member_id, committee_abbr)
                  WHERE p.member_id = mc.member_id
                    AND p.committee_abbr = mc.committee_abbr)
        """), sweep_params).rowcount
    result["swept_stale"] = swept
    logger.info("committees: %s", result)
    return result


if __name__ == "__main__":
    import sys
    eng = create_engine(os.environ["WTF_DATABASE_URL"])
    print(run_committees_sync(eng, dry_run="--dry-run" in sys.argv))
