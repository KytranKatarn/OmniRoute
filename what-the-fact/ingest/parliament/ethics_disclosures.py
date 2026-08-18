"""ethics_disclosures.py — Ethics Commissioner disclosure ingest.

The CIEC rebranded in 2026: the old SharePoint portal
(prciec-rpccie.parl.gc.ca/...PublicRegistryCode.aspx) now 301s to
www.ethicscanada.ca, whose registry search is a plain ASP.NET site with an
UNAUTHENTICATED HTML-partial endpoint — GET /en/public-registry/Cards —
serving the whole registry as parseable cards (30/page with a
"page N of M" counter, real per-entry "Disclosed on" dates back to 2009,
server-side df/dt ISO date filtering). The site's own JS fetches exactly
this endpoint; there is no JSON API. Verified live 2026-08-18: 1,645
Disclosure Summaries (Code), 55 pages, every card role
'Member of Parliament'.

No Playwright, no bs4 — plain urllib + regex — so this runs in the
wtf-ingest container on the normal weekly loop (the old scraper needed
Playwright, which is deliberately hub-only, and therefore returned
{'error': ...} on every container run: the 88-day silent freeze).

Rows land in parliament.mp_disclosures with the pre-existing contract:
(mp_id, disclosure_year, disclosure_type='public', disclosure_url),
UNIQUE (mp_id, disclosure_year, disclosure_type). disclosure_year now
comes from the card's real Disclosed-on date (the old code hardcoded the
current year), which unlocks the 2009+ history; the newest summary of a
given (mp, year) wins.
"""
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.ethics")

_CARDS_URL = "https://www.ethicscanada.ca/en/public-registry/Cards"
_DETAILS_BASE = "https://www.ethicscanada.ca/en/public-registry/Details?declarationId="
# select[name=t] option "Disclosure Summaries (Code)" — the Members' Code registry
_CODE_TYPE_GUID = "5924f660-7f25-4702-a727-bc15b1b85dba"
_HEADERS = {
    "User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)",
    "Accept": "text/html",
}
_PAGE_SLEEP = 0.4
_MAX_PAGES = 80  # 55 pages live today at 30/page — ceiling for growth

_TOTAL_RE = re.compile(r"page\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
_DECL_RE = re.compile(r"Details\?declarationId=([0-9a-fA-F-]{36})")
_NAME_RE = re.compile(r"<strong>([^<]+)</strong>")
_DATE_RE = re.compile(r"Disclosed on\s+([A-Z][a-z]+ \d{1,2}, \d{4})")


def _fetch_page(p: int) -> str:
    qs = urllib.parse.urlencode(
        # sort=date&dir=asc so that when two summaries share a (mp, year),
        # iteration order makes the NEWER one overwrite in the dedup dict.
        {"t": _CODE_TYPE_GUID, "sort": "date", "dir": "asc", "p": p}
    )
    req = urllib.request.Request(f"{_CARDS_URL}?{qs}", headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _parse_cards(html: str) -> tuple[list[dict], int | None]:
    """Parse the Cards HTML partial → ([{declaration_id, name_raw, disclosed}], total_pages).

    Each card leads with its Details?declarationId anchor, then the client
    link wrapping <strong>First Last</strong>, then 'Disclosed on Month D, YYYY'
    — so splitting on the declarationId anchor pairs each card's fields.
    """
    m = _TOTAL_RE.search(html)
    total_pages = int(m.group(2)) if m else None
    entries: list[dict] = []
    for chunk in re.split(r"(?=Details\?declarationId=)", html)[1:]:
        dm = _DECL_RE.search(chunk[:200])
        nm = _NAME_RE.search(chunk)
        dtm = _DATE_RE.search(chunk)
        if not (dm and nm and dtm):
            continue
        try:
            disclosed = datetime.strptime(dtm.group(1), "%B %d, %Y").date()
        except ValueError:
            continue
        entries.append({
            "declaration_id": dm.group(1),
            "name_raw": nm.group(1).strip(),
            "disclosed": disclosed,
        })
    return entries, total_pages


def _build_mp_index(engine) -> tuple[dict, dict, dict]:
    """Three name→mp_id maps, most→least specific. ALL MPs, not just current
    — historical summaries (2009+) belong to former members.

    ⚠️ Never match on bare family name unless it is UNIQUE: parliament.mps
    holds SEVEN current MPs surnamed Gill — the old family-first index
    silently collapsed all of them onto one id.
    """
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, name, family_name, is_current FROM parliament.mps"
        )).fetchall()
    rows = sorted(rows, key=lambda r: bool(r[3]))  # current LAST → wins collisions
    exact: dict = {}
    token: dict = {}
    token_owner: dict = {}
    family_owner: dict = {}
    for mp_id, name, fam, _cur in rows:
        n = (name or "").strip().lower()
        if not n:
            continue
        exact[n] = mp_id
        toks = n.replace(".", "").split()
        if len(toks) >= 2:
            key = (toks[0], toks[-1])
            token_owner.setdefault(key, set()).add(mp_id)
            token[key] = mp_id
        fam_l = (fam or (toks[-1] if toks else "")).strip().lower()
        if fam_l:
            family_owner.setdefault(fam_l, set()).add(mp_id)
    for key, ids in token_owner.items():
        if len(ids) > 1:
            token.pop(key, None)  # ambiguous first+last — never guess
    family = {f: next(iter(ids)) for f, ids in family_owner.items() if len(ids) == 1}
    return exact, token, family


def _match_mp(name_raw: str, exact: dict, token: dict, family: dict):
    """Portal names are 'First Last' (e.g. 'Amanpreet Singh Gill'); DB may
    hold initials ('Amanpreet S. Gill') — dot-stripped (first, last) tokens
    bridge both. Bare family only when unique."""
    n = name_raw.strip().lower()
    if n in exact:
        return exact[n]
    toks = n.replace(".", "").split()
    if len(toks) >= 2:
        mp_id = token.get((toks[0], toks[-1]))
        if mp_id:
            return mp_id
    return family.get(toks[-1]) if toks else None


def run_ethics_sync(engine) -> dict:
    """Fetch every Disclosure Summary (Code) card and upsert per (mp, year)."""
    entries: list[dict] = []
    total_pages = None
    p = 1
    while p <= _MAX_PAGES:
        try:
            html = _fetch_page(p)
        except Exception as exc:
            if entries:
                logger.warning("ethics: page %d fetch failed (%s) — proceeding with %d entries",
                               p, exc, len(entries))
                break
            return {"error": f"ethicscanada.ca Cards fetch failed on page {p}: {exc}"}
        page_entries, tp = _parse_cards(html)
        if total_pages is None and tp:
            total_pages = tp
            logger.info("ethics: %d pages of Code disclosure summaries", total_pages)
        if not page_entries:
            break
        entries.extend(page_entries)
        if total_pages is not None and p >= total_pages:
            break
        p += 1
        time.sleep(_PAGE_SLEEP)

    if not entries:
        return {"error": "no disclosure cards parsed from ethicscanada.ca — markup changed?"}

    exact, token, family = _build_mp_index(engine)
    latest: dict = {}  # (mp_id, year) -> entry; asc iteration → newest wins
    unmatched = 0
    for e in entries:
        mp_id = _match_mp(e["name_raw"], exact, token, family)
        if not mp_id:
            unmatched += 1
            continue
        latest[(mp_id, e["disclosed"].year)] = e

    upserted = 0
    failed = 0
    for (mp_id, yr), e in latest.items():
        try:
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.mp_disclosures
                        (mp_id, disclosure_year, disclosure_type, disclosure_url)
                    VALUES (:mp, :yr, 'public', :url)
                    ON CONFLICT (mp_id, disclosure_year, disclosure_type) DO UPDATE SET
                        disclosure_url = EXCLUDED.disclosure_url,
                        synced_at = NOW()
                """), {"mp": mp_id, "yr": yr,
                       "url": _DETAILS_BASE + e["declaration_id"]})
            upserted += 1
        except Exception as exc:
            logger.debug("ethics: upsert failed mp_id=%s yr=%s: %s", mp_id, yr, exc)
            failed += 1

    logger.info("ethics: fetched=%d upserted=%d unmatched=%d failed=%d pages=%d",
                len(entries), upserted, unmatched, failed, p)
    return {"fetched": len(entries), "upserted": upserted,
            "unmatched": unmatched, "failed": failed, "pages": p}
