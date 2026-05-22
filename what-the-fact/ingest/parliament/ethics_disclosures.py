"""ethics_disclosures.py — Ethics Commissioner disclosure link ingest.

Scrapes the CIEC Public Registry (prciec-rpccie.parl.gc.ca) using Playwright.
The site moved from ciec-ccie.parl.gc.ca/en/disclosures/ (404) to a
SharePoint-backed JS-rendered portal at prciec-rpccie.parl.gc.ca.

MP disclosure page links are stored in parliament.mp_disclosures.
The registry only lists *current* MPs; new MPs are added as they complete
the initial compliance process — run weekly to pick up new additions.

Pagination: 25 MPs per page, JS-driven (href="#"). Use page.evaluate()
click to advance pages — plain Playwright click() does not trigger the
DOM update; you must fire the click via JS and wait 5s for the update.

Requires: playwright + system Chrome at /usr/bin/google-chrome
"""
import logging
from datetime import date

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.ethics")

_BASE = "https://prciec-rpccie.parl.gc.ca"
_LIST_URL = f"{_BASE}/EN/PublicRegistries/Pages/PublicRegistryCode.aspx"
_CHROME_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--headless", "--disable-gpu"]
_HEADERS = {"User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)"}

_MAX_PAGES = 30  # safety ceiling (50 MPs/page would need 7 pages for all 343 MPs)


def _scrape_mp_disclosure_links() -> list[dict]:
    """Scrape all visible MP disclosure page links from the OCIEC public registry.

    Returns list of {name_raw: "Last, First", client_url: "https://..."}.
    Iterates pages until no new page link is found.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "playwright not installed — cannot scrape ethics disclosures. "
            "Run: pip install playwright && playwright install chromium"
        )
        return []

    all_links: list[dict] = []
    seen_names: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            args=_CHROME_ARGS,
        )
        try:
            page = browser.new_page()
            page.set_extra_http_headers(_HEADERS)
            page.goto(_LIST_URL, wait_until="networkidle", timeout=25000)

            current_page = 1

            while current_page <= _MAX_PAGES:
                # Scroll to reveal lazily-loaded items
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                # Extract MP Client.aspx links from current page
                raw = page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href*=\"Client.aspx\"]')).map(a => "
                    "({name: a.textContent.trim(), href: a.href})).filter(l => l.name && l.href)"
                )
                new_on_page = 0
                for item in raw:
                    if item["name"] not in seen_names:
                        seen_names.add(item["name"])
                        all_links.append({"name_raw": item["name"], "client_url": item["href"]})
                        new_on_page += 1

                logger.info(
                    "ethics: page %d — %d visible, %d new", current_page, len(raw), new_on_page
                )

                # Stop as soon as a page yields no new MPs — listing is exhausted
                if new_on_page == 0:
                    logger.info("ethics: page %d empty — listing complete", current_page)
                    break

                # Try to advance to next page via JS click on the page-number link.
                # The site uses href="#" with a JS handler; plain click() doesn't trigger
                # the DOM update — must use page.evaluate() to fire it.
                next_page_num = current_page + 1
                advanced = page.evaluate(
                    f"""() => {{
                        const all = Array.from(document.querySelectorAll('a'));
                        const link = all.find(a => a.textContent.trim() === '{next_page_num}');
                        if (link) {{ link.click(); return true; }}
                        return false;
                    }}"""
                )
                if not advanced:
                    logger.info("ethics: no page %d link — listing complete", next_page_num)
                    break

                # Wait for SharePoint to load the new page's results into the DOM
                page.wait_for_timeout(3000)
                current_page += 1

        finally:
            browser.close()

    logger.info("ethics: scraped %d total MP disclosure links across %d page(s)", len(all_links), current_page)
    return all_links


def run_ethics_sync(engine) -> dict:
    """Scrape OCIEC public registry and upsert MP disclosure page URLs."""
    mp_links = _scrape_mp_disclosure_links()
    if not mp_links:
        return {"error": "no MP links scraped — playwright may not be installed or site is down"}

    # Load current-MP name maps
    with engine.connect() as c:
        mp_rows = c.execute(text(
            "SELECT id, name, family_name FROM parliament.mps WHERE is_current = true"
        )).fetchall()

    family_idx = {(r[2] or "").strip().lower(): r[0] for r in mp_rows if r[2]}
    name_idx = {(r[1] or "").strip().lower(): r[0] for r in mp_rows if r[1]}

    current_year = date.today().year
    inserted = 0
    skipped = 0

    for item in mp_links:
        name_raw = item["name_raw"]   # OCIEC format: "Last, First" (e.g. "Trudeau, Justin")
        client_url = item["client_url"]

        # Parse "Last, First" → family + given
        if "," in name_raw:
            family, given = name_raw.split(",", 1)
            family = family.strip().lower()
            given = given.strip().lower()
        else:
            family = name_raw.strip().lower()
            given = ""

        # Match against DB by family name (most reliable), then full name variants
        mp_id = family_idx.get(family)
        if not mp_id and given:
            mp_id = name_idx.get(f"{given} {family}") or name_idx.get(f"{family} {given}")

        if not mp_id:
            logger.debug("ethics: no DB match for %r (family=%r)", name_raw, family)
            skipped += 1
            continue

        try:
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.mp_disclosures
                        (mp_id, disclosure_year, disclosure_type, disclosure_url)
                    VALUES (:mp, :yr, :dtype, :url)
                    ON CONFLICT (mp_id, disclosure_year, disclosure_type) DO UPDATE SET
                        disclosure_url = EXCLUDED.disclosure_url,
                        synced_at = NOW()
                """), {"mp": mp_id, "yr": current_year, "dtype": "public", "url": client_url})
            inserted += 1
        except Exception as exc:
            logger.debug("ethics: insert failed mp_id=%s: %s", mp_id, exc)
            skipped += 1

    logger.info("ethics: inserted=%d skipped=%d scraped=%d", inserted, skipped, len(mp_links))
    return {"inserted": inserted, "skipped": skipped, "scraped": len(mp_links)}
