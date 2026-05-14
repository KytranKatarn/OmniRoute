# archie-scraper/skills/procurement_sync.py
"""Skill: procurement_sync — CanadaBuys tender listings via real browser."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://canadabuys.canada.ca/en/tender-opportunities"
_TENDER_SELECTORS = [
    "table tbody tr",
    ".tender-item",
    "[class*='tender-row']",
    "[class*='opportunity']",
]
_NEXT_SELECTORS = [
    "a[rel='next']",
    ".pagination-next a",
    "a:has-text('Next')",
    "[aria-label='Next page']",
]


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        max_pages  int  pages to paginate (default 3)
    """
    max_pages = int(params.get("max_pages") or 3)
    target = url or _DEFAULT_URL

    tenders: list = []
    screenshots = []
    pages_scraped = 0

    page.goto(target, wait_until="networkidle", timeout=45000)
    path = save_screenshot(job_id, "tenders_page_1", page)
    screenshots.append(screenshot_entry("tenders_page_1", path, "CanadaBuys page 1"))

    for page_num in range(1, max_pages + 1):
        pages_scraped = page_num
        rows: list = []
        for selector in _TENDER_SELECTORS:
            rows = page.query_selector_all(selector)
            if rows:
                break

        for row in rows:
            text = row.inner_text().strip()
            if not text or len(text) < 10:
                continue
            links = row.query_selector_all("a")
            href = links[0].get_attribute("href") if links else None
            tenders.append({"text": text[:500], "url": href, "page": page_num})

        if page_num >= max_pages:
            break
        next_btn = None
        for sel in _NEXT_SELECTORS:
            try:
                next_btn = page.query_selector(sel)
                if next_btn:
                    break
            except Exception:
                continue
        if not next_btn:
            break
        next_btn.click()
        page.wait_for_load_state("networkidle", timeout=15000)

    findings = (
        f"Found {len(tenders)} tenders across {pages_scraped} page(s) from {target}"
    )
    logger.info("[procurement_sync] job #%d: %s", job_id, findings)

    return {
        "data": {"tenders": tenders, "source": target, "pages_scraped": pages_scraped},
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
