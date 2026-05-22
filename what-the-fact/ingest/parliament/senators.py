"""senators.py — Senate of Canada enrichment: bio, contact, committees, DOB, appointing PM.

Scrapes sencanada.ca individual senator profiles for:
  - Biography text
  - Office phone + email
  - Committee memberships (abbr, name, role)

Gets date_of_birth from Wikidata SPARQL (WHERE position = Senator of Canada).

Computes appointed_by (Prime Minister name) from appointed_at date using
canonical PM date ranges — no scraping required.

Env: WTF_DATABASE_URL
Run: python -m ingest.parliament.senators   (from what-the-fact/ root)
     or pass --dry-run to print without writing
"""
import logging
import re
import time
import sys
from datetime import date, datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.senators")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_SEN_BASE = "https://sencanada.ca"
_HEADERS = {
    "User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)",
    "Accept": "text/html,application/xhtml+xml",
}
_PROFILE_SLEEP = 1.2   # seconds between senator profile requests
_WIKIDATA_URL  = "https://query.wikidata.org/sparql"

# ── Prime Ministers date ranges (descending) ─────────────────────────────────
# Each tuple: (first day in office, PM name)
_PM_RANGES = [
    (date(2025, 3, 14), "Mark Carney"),
    (date(2015, 11, 4), "Justin Trudeau"),
    (date(2006,  2,  6), "Stephen Harper"),
    (date(2003, 12, 12), "Paul Martin"),
    (date(1993, 11,  4), "Jean Chrétien"),
    (date(1993,  6, 25), "Kim Campbell"),
    (date(1984,  9, 17), "Brian Mulroney"),
    (date(1984,  6, 30), "John Turner"),
    (date(1980,  3,  3), "Pierre Elliott Trudeau"),
    (date(1979,  6,  4), "Joe Clark"),
    (date(date.min.year, 1, 1), "Pierre Elliott Trudeau"),  # fallback pre-1979
]


def _appointing_pm(appointment_date: Optional[date]) -> Optional[str]:
    """Return name of PM who would have appointed a senator on appointment_date."""
    if not appointment_date:
        return None
    for start, pm in _PM_RANGES:
        if appointment_date >= start:
            return pm
    return None


# ── Wikidata DOB lookup ───────────────────────────────────────────────────────

_WIKIDATA_QUERY = """
SELECT DISTINCT ?personLabel ?dob WHERE {
  {
    ?person wdt:P39 wd:Q4172 ; wdt:P569 ?dob .
  } UNION {
    ?person wdt:P39 wd:Q29371 ; wdt:P569 ?dob .
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr" . }
  FILTER(LANG(?personLabel) = "en")
}
"""
# Q4172 = Senator of Canada (position), Q29371 = fallback

def _fetch_wikidata_dobs() -> dict[str, date]:
    """Return {normalized_name: date_of_birth} for all Canadian senators on Wikidata."""
    try:
        resp = requests.get(
            _WIKIDATA_URL,
            params={"query": _WIKIDATA_QUERY, "format": "json"},
            headers={"User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com)"},
            timeout=30,
        )
        resp.raise_for_status()
        bindings = resp.json()["results"]["bindings"]
        out = {}
        for b in bindings:
            label = b.get("personLabel", {}).get("value", "")
            dob_str = b.get("dob", {}).get("value", "")
            if label and dob_str:
                try:
                    dob = date.fromisoformat(dob_str[:10])
                    out[_norm_name(label)] = dob
                except ValueError:
                    pass
        logger.info("Wikidata: %d senator DOBs fetched", len(out))
        return out
    except Exception as exc:
        logger.warning("Wikidata DOB fetch failed: %s", exc)
        return {}


def _norm_name(name: str) -> str:
    """Lowercase, strip titles, collapse spaces for fuzzy name matching."""
    name = name.lower()
    for title in ("the honourable ", "hon. ", "senator ", "dr. ", "mr. ", "ms. ", "mrs. "):
        name = name.replace(title, "")
    return re.sub(r"\s+", " ", name).strip()


# ── sencanada.ca scraper ──────────────────────────────────────────────────────

def _scrape_profile(slug: str) -> dict:
    """Scrape one senator's sencanada.ca profile. Returns partial dict of enrichment fields.

    sencanada.ca renders contact info as plain text (not structured dt/dd), so we use
    regex on the raw HTML for phone/email, and find the Biography section via text markers.
    Committee memberships are NOT on profile pages — fetched separately via _scrape_committees().
    """
    url = f"{_SEN_BASE}/en/senators/{slug}/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Profile fetch failed for %s: %s", slug, exc)
        return {}

    text = resp.text
    result: dict = {}

    # ── Biography — extract text after the Biography heading ─────────────────
    bio_m = re.search(r"Biography\s*</h[2-5]>(.*?)(?=<h[2-5]|<footer|</main)", text, re.DOTALL | re.IGNORECASE)
    if bio_m:
        soup_bio = BeautifulSoup(bio_m.group(1), "html.parser")
        raw = soup_bio.get_text(" ", strip=True)
        result["biography"] = re.sub(r"\s{2,}", " ", raw)[:4000] or None

    # ── Phone — 613-xxx-xxxx pattern ─────────────────────────────────────────
    phone_m = re.search(r"613[-.\s]\d{3}[-.\s]\d{4}", text)
    if phone_m:
        result["office_phone"] = re.sub(r"\s+", "-", phone_m.group(0).strip())

    # ── Email — @sen.parl.gc.ca ───────────────────────────────────────────────
    email_m = re.search(r"[\w.+-]+@sen\.parl\.gc\.ca", text, re.IGNORECASE)
    if email_m:
        result["office_email"] = email_m.group(0).lower()

    # ── Twitter handle ────────────────────────────────────────────────────────
    tw_m = re.search(r'twitter\.com/([A-Za-z0-9_]{1,50})', text)
    if tw_m:
        result["twitter_handle"] = tw_m.group(1)

    result["committees"] = []  # populated separately by _scrape_committees()
    return result


def _scrape_committees() -> dict[str, list[dict]]:
    """Fetch all Senate committees and return {senator_slug: [committee_dicts]}.

    sencanada.ca is now fully JavaScript-rendered — committee member pages
    (/committees/ABBR/members/) return 404 or an error page.  Members are visible
    on the base committee URL (/committees/ABBR/) after JS execution.

    Requires: playwright + system Chrome at /usr/bin/google-chrome
    Install:  pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "playwright not installed — cannot scrape committees. "
            "Run: pip install playwright && playwright install chromium"
        )
        return {}

    # Hard-coded fallback list — used when index-page discovery finds < 5 committees.
    # Reflects 42nd Parliament standing committees (update if committees are renamed).
    _FALLBACK_COMMITTEES: dict[str, str] = {
        "AGFO": "Agriculture and Forestry",
        "BANC": "Banking, Commerce and the Economy",
        "CIBA": "Internal Economy, Budgets and Administration",
        "ENEV": "Energy, the Environment and Natural Resources",
        "ETHE": "Ethics and Conflict of Interest for Senators",
        "FORE": "Foreign Affairs and International Trade",
        "HUMA": "Social Affairs, Science and Technology",
        "LCJC": "Legal and Constitutional Affairs",
        "NFFN": "National Finance",
        "OLLO": "Official Languages",
        "PAHO": "Indigenous Peoples",
        "RIDR": "Human Rights",
        "RPRD": "Rules, Procedures and the Rights of Parliament",
        "SECD": "National Security, Defence and Veterans",
        "SOCI": "Social Affairs, Science and Technology",
        "TRCM": "Transport and Communications",
        "VEAC": "Veterans Affairs",
    }

    slug_committees: dict[str, list] = {}
    comm_abbrs: dict[str, str] = {}

    _chrome_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--headless",
        "--disable-gpu",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            args=_chrome_args,
        )
        try:
            page = browser.new_page()
            page.set_extra_http_headers(_HEADERS)

            # ── Step 1: Discover committee abbreviations from index page ──────
            index_url = f"{_SEN_BASE}/en/committees/"
            logger.info("Fetching committee index via Playwright: %s", index_url)
            page.goto(index_url, wait_until="networkidle", timeout=30000)

            for link in page.query_selector_all("a[href]"):
                href = link.get_attribute("href") or ""
                # Match /en/committees/AGFO/ or /en/committees/agfo (upper or lower)
                m = re.search(r"/committees/([A-Za-z]{2,8})/?(?:$|\?|#)", href)
                if not m:
                    continue
                abbr = m.group(1).upper()
                # Skip navigation / language fragments
                if abbr in {"EN", "FR", "HOME", "BACK", "NEXT", "PREV", "ALL"}:
                    continue
                if len(abbr) < 2:
                    continue
                name_text = (link.inner_text() or "").strip()
                if name_text and abbr not in comm_abbrs:
                    comm_abbrs[abbr] = name_text

            logger.info(
                "Index discovery: %d committees found — %s",
                len(comm_abbrs),
                sorted(comm_abbrs.keys()),
            )

            if len(comm_abbrs) < 5:
                logger.warning(
                    "Fewer than 5 committees discovered (got %d); switching to fallback list",
                    len(comm_abbrs),
                )
                comm_abbrs = _FALLBACK_COMMITTEES.copy()

            # ── Step 2: Scrape each committee's base page for members ─────────
            for abbr, comm_name in comm_abbrs.items():
                comm_url = f"{_SEN_BASE}/en/committees/{abbr.lower()}/"
                logger.info("Scraping members: %s → %s", abbr, comm_url)
                try:
                    page.goto(comm_url, wait_until="networkidle", timeout=20000)

                    # Bail if the page returned an error
                    title = (page.title() or "").lower()
                    if "error" in title or "not found" in title or "404" in title:
                        logger.warning("  %s → error page ('%s'), skipping", abbr, page.title())
                        continue

                    # Navigate to MEMBERSHIP tab if present.
                    # sencanada.ca uses ?v=committee-members query param (not a path),
                    # so we extract the href and goto() it — more reliable than click().
                    membership_href = None
                    for link in page.query_selector_all("a[href*='committees']"):
                        txt = (link.inner_text() or "").strip().upper()
                        if txt in ("MEMBERSHIP", "MEMBERS"):
                            membership_href = link.get_attribute("href")
                            break
                    if membership_href:
                        mem_url = (
                            membership_href
                            if membership_href.startswith("http")
                            else f"{_SEN_BASE}{membership_href}"
                        )
                        try:
                            page.goto(mem_url, wait_until="networkidle", timeout=15000)
                        except Exception as exc:
                            logger.warning("  %s → MEMBERSHIP nav failed: %s", abbr, exc)

                    # Extract senator links
                    seen: set[str] = set()
                    member_count = 0

                    for link in page.query_selector_all("a[href*='/senators/']"):
                        href = link.get_attribute("href") or ""
                        slug_m = re.search(r"/senators/([\w-]+)/?$", href, re.IGNORECASE)
                        if not slug_m:
                            continue
                        sen_slug = slug_m.group(1).lower()
                        if sen_slug in seen:
                            continue
                        seen.add(sen_slug)

                        # Determine role from nearest block container
                        role = "member"
                        try:
                            ctx = link.evaluate(
                                "(el) => {"
                                "  const p = el.closest('li, tr, [class*=member], [class*=senator], [class*=card]');"
                                "  return (p || el.parentElement || el).textContent || '';"
                                "}"
                            )
                            ctx_l = ctx.lower()
                            if "deputy chair" in ctx_l or "vice-chair" in ctx_l or "vice chair" in ctx_l:
                                role = "deputy_chair"
                            elif "chair" in ctx_l:
                                role = "chair"
                        except Exception:
                            pass

                        slug_committees.setdefault(sen_slug, []).append(
                            {"abbr": abbr, "name": comm_name, "role": role}
                        )
                        member_count += 1

                    logger.info("  %s: %d unique members", abbr, member_count)

                except Exception as exc:
                    logger.warning("Failed to scrape committee %s: %s", abbr, exc)

                time.sleep(0.5)

        finally:
            browser.close()

    logger.info(
        "Committee scrape complete — %d senators with at least one membership",
        len(slug_committees),
    )
    return slug_committees


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_engine():
    import os
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url)


def _load_senators(engine) -> list[dict]:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, slug, name, appointed_at
            FROM parliament.senators
            WHERE is_current = true
            ORDER BY name
        """)).mappings().all()
    return [dict(r) for r in rows]


def _update_senator(engine, senator_id: int, fields: dict, dry_run: bool) -> None:
    scalar_fields = {k: v for k, v in fields.items() if k != "committees"}
    if scalar_fields and not dry_run:
        set_clause = ", ".join(f"{k} = :{k}" for k in scalar_fields)
        with engine.begin() as conn:
            conn.execute(
                text(f"UPDATE parliament.senators SET {set_clause}, synced_at = NOW() WHERE id = :id"),
                {"id": senator_id, **scalar_fields},
            )

    committees = fields.get("committees", [])
    if committees and not dry_run:
        with engine.begin() as conn:
            for c in committees:
                conn.execute(text("""
                    INSERT INTO parliament.senator_committees
                        (senator_id, committee_abbr, committee_name, role)
                    VALUES (:sid, :abbr, :name, :role)
                    ON CONFLICT (senator_id, committee_abbr)
                    DO UPDATE SET committee_name = EXCLUDED.committee_name,
                                  role = EXCLUDED.role,
                                  is_current = true
                """), {"sid": senator_id, "abbr": c["abbr"], "name": c["name"], "role": c["role"]})


# ── main sync ─────────────────────────────────────────────────────────────────

def sync_senators(dry_run: bool = False) -> dict:
    engine = _get_engine()
    senators = _load_senators(engine)
    logger.info("Enriching %d senators…", len(senators))

    # Fetch all Wikidata DOBs once
    dob_map = _fetch_wikidata_dobs()

    # Fetch all committee memberships once (keyed by senator slug)
    slug_committees = _scrape_committees()

    # Build slug → senator_id map for committee lookup
    slug_to_id = {s["slug"]: s["id"] for s in senators}

    stats = {"total": len(senators), "updated": 0, "no_bio": 0, "committees_total": 0, "dob_matched": 0}

    for s in senators:
        slug = s["slug"]
        logger.info("  → %s (%s)", s["name"], slug)

        fields = _scrape_profile(slug)

        # Inject committees from the batch-fetched map
        fields["committees"] = slug_committees.get(slug, [])

        # Appointed-by PM (computed from DB date — no scraping needed)
        appt = s.get("appointed_at")
        if isinstance(appt, datetime):
            appt = appt.date()
        fields["appointed_by"] = _appointing_pm(appt)

        # DOB from Wikidata
        norm = _norm_name(s["name"])
        if norm in dob_map:
            fields["date_of_birth"] = dob_map[norm]
            stats["dob_matched"] += 1
        else:
            # Try family name only as fallback
            family = norm.split(",")[0].strip() if "," in norm else norm.split()[-1]
            matches = {k: v for k, v in dob_map.items() if family in k}
            if len(matches) == 1:
                fields["date_of_birth"] = list(matches.values())[0]
                stats["dob_matched"] += 1

        if dry_run:
            committees = fields.pop("committees", [])
            logger.info("    DRY bio=%s phone=%s email=%s pm=%s dob=%s committees=%d",
                        bool(fields.get("biography")), fields.get("office_phone"),
                        fields.get("office_email"), fields.get("appointed_by"),
                        fields.get("date_of_birth"), len(committees))
            fields["committees"] = committees
        else:
            _update_senator(engine, s["id"], fields, dry_run=False)

        if fields.get("biography"):
            stats["updated"] += 1
        else:
            stats["no_bio"] += 1
        stats["committees_total"] += len(fields.get("committees", []))

        time.sleep(_PROFILE_SLEEP)

    logger.info("Done. updated=%d no_bio=%d committees=%d dob_matched=%d",
                stats["updated"], stats["no_bio"], stats["committees_total"], stats["dob_matched"])
    return stats


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sync_senators(dry_run=dry_run)
