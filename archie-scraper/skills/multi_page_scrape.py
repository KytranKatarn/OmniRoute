"""Skill: multi_page_scrape — Pagination-aware multi-page extraction."""
import logging

logger = logging.getLogger(__name__)

_NEXT_SELECTORS = [
    "a[rel='next']", ".pagination-next a", "a:has-text('Next')",
    "[aria-label='Next page']", "button:has-text('Next')",
]


def run(page, url: str, params: dict, job_id: int) -> dict:
    selectors = params.get("selectors") or {}
    next_sel_override = params.get("next_selector")
    max_pages = int(params.get("max_pages") or 5)
    wait_for = params.get("wait_for")

    page.goto(url, wait_until="networkidle", timeout=30000)
    if wait_for:
        page.wait_for_selector(wait_for, timeout=10000)

    all_data: dict = {field: [] for field in selectors}
    pages_scraped = 0

    for page_num in range(1, max_pages + 1):
        pages_scraped = page_num
        for field, selector in selectors.items():
            els = page.query_selector_all(selector)
            all_data[field].extend(el.inner_text().strip() for el in els)

        next_selectors = [next_sel_override] if next_sel_override else _NEXT_SELECTORS
        next_btn = None
        for sel in next_selectors:
            try:
                next_btn = page.query_selector(sel)
                if next_btn:
                    break
            except Exception:
                continue
        if not next_btn or page_num >= max_pages:
            break
        next_btn.click()
        page.wait_for_load_state("networkidle", timeout=15000)

    total = sum(len(v) for v in all_data.values())
    findings = f"Extracted {total} items across {pages_scraped} page(s) from {url}"
    logger.info("[multi_page_scrape] job #%d: %s", job_id, findings)
    return {"data": all_data, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True}
