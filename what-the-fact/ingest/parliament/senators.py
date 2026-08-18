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
import json
import logging
import re
import time
import sys
from datetime import date, datetime, timezone
from typing import Optional

import requests
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

def _name_from_slug(slug: str) -> str:
    """'martel-richard' → 'Richard Martel' (sencanada slugs are family-given).

    Best-effort display name for a brand-new appointee whose list-view anchor
    text came back empty — the raw slug is what previously landed in `name`
    and rendered on /mps. Multi-part given/family names come out imperfect;
    enrichment or curation refines them later."""
    parts = [p for p in slug.split("-") if p]
    if len(parts) < 2:
        return slug.replace("-", " ").title()
    family, given = parts[0], parts[1:]
    return " ".join(w.capitalize() for w in given + [family])


def _scrape_profile(slug: str, page=None) -> dict:
    """Scrape one senator's sencanada.ca profile. Returns partial dict of enrichment fields.

    sencanada.ca is fully JavaScript-rendered — requests.get() only returns the nav
    shell with no biography content.  Pass a live Playwright `page` object (reused
    across all senators) for proper JS rendering.  Falls back to plain requests if
    Playwright is unavailable, but bio extraction will not succeed in that mode.

    Committee memberships are NOT on profile pages — fetched separately via _scrape_committees().
    """
    url = f"{_SEN_BASE}/en/senators/{slug}/"
    result: dict = {}

    if page is not None:
        # ── Playwright path (preferred) ───────────────────────────────────────
        try:
            page.goto(url, wait_until="networkidle", timeout=25000)
            # Give JS components extra time to hydrate bio section
            page.wait_for_timeout(2500)
        except Exception as exc:
            logger.warning("Playwright nav failed for %s: %s", slug, exc)
            result["committees"] = []
            return result

        # Biography — class sc-senator-bio-senatorbiography
        bio_el = page.query_selector(".sc-senator-bio-senatorbiography")
        if bio_el:
            raw = bio_el.inner_text().strip()
            # Strip leading "Biography" heading word
            raw = re.sub(r"^Biography\s*", "", raw, flags=re.IGNORECASE).strip()
            if raw:
                result["biography"] = re.sub(r"\s{2,}", " ", raw)[:4000]

        # Contact card list items — "Label: Value" text pairs
        card_items = page.query_selector_all(".sc-senator-bio-senatorheader-content-card-list-item")
        for item in card_items:
            txt = item.inner_text().strip()
            # Phone
            if txt.startswith("Telephone:"):
                phone_raw = txt.replace("Telephone:", "").strip()
                phone_m = re.search(r"613[-.\s]?\d{3}[-.\s]?\d{4}", phone_raw)
                if phone_m:
                    result["office_phone"] = re.sub(r"\s+", "-", phone_m.group(0))
            # Email
            elif txt.startswith("Email:"):
                email_m = re.search(r"[\w.+-]+@sen\.parl\.gc\.ca", txt, re.IGNORECASE)
                if email_m:
                    result["office_email"] = email_m.group(0).lower()

        # Twitter / X handle from social icon links
        tw_m = re.search(r'(?:twitter|x)\.com/([A-Za-z0-9_]{1,50})', page.content())
        if tw_m:
            result["twitter_handle"] = tw_m.group(1)

    else:
        # ── Plain-requests fallback (bio will not be extracted) ───────────────
        logger.warning(
            "No Playwright page supplied for %s — contact info only (bio requires JS)",
            slug,
        )
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            text = resp.text
            phone_m = re.search(r"613[-.\s]\d{3}[-.\s]\d{4}", text)
            if phone_m:
                result["office_phone"] = re.sub(r"\s+", "-", phone_m.group(0).strip())
            email_m = re.search(r"[\w.+-]+@sen\.parl\.gc\.ca", text, re.IGNORECASE)
            if email_m:
                result["office_email"] = email_m.group(0).lower()
        except Exception as exc:
            logger.warning("Profile fetch failed for %s: %s", slug, exc)

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


# ── senator roster scrape (the "fetched set" for change detection) ────────────

def _scrape_senator_roster(page) -> dict:
    """Scrape the current-senators list view → {slug: name} (the fetched set).

    Unlike enrichment (which iterates the DB-loaded current senators), this is an
    INDEPENDENT fetch of who is currently a senator — the signal needed to detect
    departures/appointments.  sencanada.ca is fully JS-rendered, so a live
    Playwright `page` is required; returns {} on any failure so the caller's
    plausibility guard falls back to enrichment-only (no false departures).

    NOTE: the list/standings-view selectors are best-effort and NOT verified
    against a live headless render in this change (live scraping was out of
    scope).  The caller's >=80%-of-prior-current guard makes a wrong/empty
    result a safe no-op rather than a data-corrupting mass-departure.
    """
    if page is None:
        return {}
    roster: dict = {}
    for view in ("?v=list", "?v=contact", ""):
        url = f"{_SEN_BASE}/en/senators/{view}"
        try:
            page.goto(url, wait_until="networkidle", timeout=25000)
            page.wait_for_timeout(2000)
        except Exception as exc:
            logger.warning("senator roster nav failed (%s): %s", url, exc)
            continue
        for link in page.query_selector_all("a[href*='/senators/']"):
            href = link.get_attribute("href") or ""
            m = re.search(r"/senators/([\w-]+)/?$", href, re.IGNORECASE)
            if not m:
                continue
            slug = m.group(1).lower()
            if slug in ("", "list", "contact"):
                continue
            roster.setdefault(slug, (link.inner_text() or "").strip())
        if len(roster) >= 50:      # plausible full roster obtained — stop trying views
            break
    logger.info("senator roster scrape: %d slugs", len(roster))
    return roster


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_engine():
    import os
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url)


def _record_movement(conn, movement_type: str, *, subject_slug=None, subject_id=None,
                     name=None, before=None, after=None) -> None:
    """Append a senator movement to parliament.mp_movements (migration 038).

    Mirrors openparl.record_movement — kept local so senators.py stays runnable
    standalone via `python -m ingest.parliament.senators`.
    """
    conn.execute(text("""
        INSERT INTO parliament.mp_movements
            (subject_type, subject_slug, subject_id, name, movement_type,
             before_value, after_value)
        VALUES
            ('senator', :slug, :sid, :name, :mt, CAST(:bv AS JSONB), CAST(:av AS JSONB))
    """), {
        "slug": subject_slug, "sid": subject_id, "name": name, "mt": movement_type,
        "bv": json.dumps(before) if before is not None else None,
        "av": json.dumps(after) if after is not None else None,
    })


def _snapshot_senators(engine) -> dict:
    """{slug: {name, is_current}} for ALL senators — captured before any writes."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, name, is_current FROM parliament.senators"
        )).fetchall()
    return {r[0]: {"name": r[1], "is_current": r[2]} for r in rows}


def _reconcile_senator_roster(engine, snapshot: dict, roster: dict,
                              dry_run: bool, stats: dict) -> None:
    """Flip is_current for departed/appointed senators + record movements.

    `roster` = {slug: name} scraped as the current set.  Guarded: only acts when
    the scrape returned a plausible roster (>=80% of prior current count); a
    failed/empty scrape falls back to enrichment-only (zero movements, no flips).
    A no-op run where roster == the current set emits ZERO movements.
    """
    stats.setdefault("departed", 0)
    stats.setdefault("appointed", 0)
    prior_current = [slug for slug, v in snapshot.items() if v["is_current"]]
    seen = set(roster)
    if not seen or len(seen) < max(1, int(0.8 * len(prior_current))):
        if prior_current:
            logger.warning(
                "senator roster diff skipped — scraped %d vs %d prior-current (guard); "
                "enrichment-only this run", len(seen), len(prior_current))
        return

    current_set = set(prior_current)

    # Departures: is_current=true but not in the scraped roster
    for slug in prior_current:
        if slug in seen:
            continue
        if not dry_run:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE parliament.senators SET is_current = false, synced_at = NOW() "
                    "WHERE slug = :s"), {"s": slug})
                _record_movement(conn, "departed", subject_slug=slug,
                                 name=snapshot[slug].get("name"),
                                 before={"is_current": True}, after={"is_current": False})
        stats["departed"] += 1

    # Appointments: in the roster but not currently is_current=true
    for slug, name in roster.items():
        if slug in current_set:
            continue
        # The list-view anchor's inner_text is often EMPTY (the 2026-08-18
        # appointees landed with name == slug and caucus NULL, and the /mps
        # template's `groupby('caucus')` 500'd on the NULL for ~2.5h). Derive
        # a display name from the slug (sencanada slugs are family-given) and
        # start every appointee 'Non-affiliated' — factually what a brand-new
        # senator is until they join a group; enrichment refines later.
        display = name if (name and name != slug) else _name_from_slug(slug)
        if not dry_run:
            with engine.begin() as conn:
                if slug in snapshot:      # returning senator → reactivate
                    conn.execute(text(
                        "UPDATE parliament.senators SET is_current = true, synced_at = NOW() "
                        "WHERE slug = :s"), {"s": slug})
                else:                     # brand-new → sane stub (enrichment fills the rest)
                    conn.execute(text(
                        "INSERT INTO parliament.senators "
                        "  (slug, name, caucus, profile_url, is_current, synced_at) "
                        "VALUES (:s, :n, 'Non-affiliated', :u, true, NOW()) "
                        "ON CONFLICT (slug) DO UPDATE SET is_current = true, synced_at = NOW()"),
                        {"s": slug, "n": display,
                         "u": f"{_SEN_BASE}/en/senators/{slug}/"})
                _record_movement(conn, "appointed", subject_slug=slug, name=display,
                                 after={"is_current": True})
        stats.setdefault("appointed_slugs", []).append(slug)
        stats["appointed"] += 1

    logger.info("senator roster diff: departed=%d appointed=%d",
                stats["departed"], stats["appointed"])


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
    snapshot = _snapshot_senators(engine)   # prior state for change detection
    logger.info("Enriching %d senators…", len(senators))

    # Fetch all Wikidata DOBs once
    dob_map = _fetch_wikidata_dobs()

    # Fetch all committee memberships once (keyed by senator slug)
    slug_committees = _scrape_committees()

    # Build slug → senator_id map for committee lookup
    slug_to_id = {s["slug"]: s["id"] for s in senators}

    stats = {"total": len(senators), "updated": 0, "no_bio": 0, "committees_total": 0, "dob_matched": 0}

    # Open one Playwright browser for all profile scrapes (bio requires JS render)
    _pw_ctx = None
    _pw_browser = None
    _pw_page = None
    roster: dict = {}
    try:
        from playwright.sync_api import sync_playwright as _sync_playwright
        _pw_ctx = _sync_playwright().__enter__()
        _pw_browser = _pw_ctx.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage", "--headless", "--disable-gpu"],
        )
        _pw_page = _pw_browser.new_page()
        _pw_page.set_extra_http_headers(_HEADERS)
        logger.info("Playwright browser ready for profile scraping")
        # Fetch the current senator roster (the independent "seen set") while the
        # page is live — used after enrichment to detect departures/appointments.
        roster = _scrape_senator_roster(_pw_page)
    except Exception as exc:
        logger.warning("Playwright unavailable — bios will not be extracted: %s", exc)

    try:
        for s in senators:
            slug = s["slug"]
            logger.info("  → %s (%s)", s["name"], slug)

            fields = _scrape_profile(slug, page=_pw_page)

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

    finally:
        if _pw_page:
            try:
                _pw_page.close()
            except Exception:
                pass
        if _pw_browser:
            try:
                _pw_browser.close()
            except Exception:
                pass
        if _pw_ctx:
            try:
                _pw_ctx.__exit__(None, None, None)
            except Exception:
                pass

    # ── roster diff → is_current flips + movements (guarded; safe no-op if the
    #    roster scrape came back implausible) ──────────────────────────────────
    _reconcile_senator_roster(engine, snapshot, roster, dry_run, stats)

    # ── same-run enrichment of NEW appointees ─────────────────────────────────
    # _load_senators() ran BEFORE the reconcile inserted them, so without this
    # pass a new senator sits as a bare stub until the NEXT weekly run — that
    # 7-day window is exactly how the 2026-08-18 appointees reached /mps as
    # slug-named NULL-caucus rows (and NULL caucus 500'd the page).
    _enrich_new_appointees(engine, stats.get("appointed_slugs") or [], dry_run)

    logger.info("Done. updated=%d no_bio=%d committees=%d dob_matched=%d "
                "departed=%d appointed=%d",
                stats["updated"], stats["no_bio"], stats["committees_total"],
                stats["dob_matched"], stats.get("departed", 0), stats.get("appointed", 0))
    return stats


def _enrich_new_appointees(engine, slugs: list, dry_run: bool) -> None:
    """Profile-enrich freshly-appointed senators in the SAME run.

    Opens its own short-lived browser (the main enrichment browser is closed
    before the reconcile runs). Best-effort: a failure here leaves the sane
    stub in place — never breaks the sync."""
    if not slugs or dry_run:
        return
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/usr/bin/google-chrome",
                args=["--no-sandbox", "--disable-dev-shm-usage", "--headless", "--disable-gpu"],
            )
            page = browser.new_page()
            page.set_extra_http_headers(_HEADERS)
            for slug in slugs:
                try:
                    with engine.connect() as c:
                        row = c.execute(text(
                            "SELECT id FROM parliament.senators WHERE slug = :s"),
                            {"s": slug}).fetchone()
                    if not row:
                        continue
                    fields = _scrape_profile(slug, page=page)
                    fields.pop("committees", None)
                    if fields:
                        _update_senator(engine, row[0], fields, dry_run=False)
                    logger.info("appointee enriched same-run: %s (%s)",
                                slug, ", ".join(sorted(fields)))
                except Exception as exc:
                    logger.warning("appointee enrichment failed for %s: %s", slug, exc)
            browser.close()
    except Exception as exc:
        logger.warning("appointee enrichment pass unavailable: %s", exc)


def run_roster_sync_hub() -> dict:
    """sync_senators + a parliament.ingest_log heartbeat (task='senators_roster').

    HUB-side entrypoint (weekly cron beside senate_votes): the roster +
    committees scrape needs Playwright/Chrome, which the ingest container
    lacks — the container's weekly run is enrichment-only and scrapes 0
    (proven on the 2026-08-18 backfill), so its 'senators_sync' success rows
    must NOT be the roster's freshness signal. drift_guard watches
    'senators_roster' instead."""
    engine = _get_engine()
    try:
        stats = sync_senators()
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                "VALUES ('senators_roster', :f, :u)"),
                {"f": int(stats.get("total") or 0),
                 "u": int((stats.get("updated") or 0) + (stats.get("appointed") or 0)
                          + (stats.get("departed") or 0))})
        return stats
    except Exception as exc:
        try:
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) "
                    "VALUES ('senators_roster', :e)"), {"e": str(exc)[:500]})
        except Exception:
            logger.exception("senators_roster heartbeat write failed")
        raise


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        sync_senators(dry_run=True)
    else:
        run_roster_sync_hub()
