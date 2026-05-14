# archie-scraper/skills/web_scrape.py
"""Skill: web_scrape — General selector-based page extraction."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        selectors  dict  field_name -> CSS selector
        wait_for   str   CSS selector to wait for before extracting (optional)
        max_items  int   limit per selector (default 100)
    """
    selectors = params.get("selectors") or {}
    wait_for = params.get("wait_for")
    max_items = int(params.get("max_items") or 100)

    page.goto(url, wait_until="networkidle", timeout=30000)
    if wait_for:
        page.wait_for_selector(wait_for, timeout=10000)

    data: dict = {}
    for field, selector in selectors.items():
        els = page.query_selector_all(selector)[:max_items]
        data[field] = [el.inner_text().strip() for el in els]

    total = sum(len(v) for v in data.values())
    findings = f"Extracted {total} items across {len(selectors)} selectors from {url}"
    logger.info("[web_scrape] job #%d: %s", job_id, findings)

    return {
        "data": data,
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
