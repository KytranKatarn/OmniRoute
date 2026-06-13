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

    # domcontentloaded (not networkidle): ad/tracker-heavy news sites never reach
    # network-idle within 30s, so networkidle always timed out → every job failed.
    # DOM-parsed is enough for selector extraction; pass `wait_for` for JS-rendered bodies.
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    logger.info("[web_scrape] job #%d: landed on %s", job_id, page.url[:120])

    # Google News RSS URLs use a JS redirect. If Playwright settles on the
    # Google intermediate page, resolve the real article URL and follow it.
    if "news.google.com" in page.url:
        try:
            actual_url = page.evaluate(
                """
                () => {
                    let a = document.querySelector('[data-n-au]');
                    if (a) return a.getAttribute('data-n-au');
                    a = document.querySelector('main a[href^="http"]');
                    if (a && !a.href.includes('google.com')) return a.href;
                    a = document.querySelector('c-wiz a[href^="http"]');
                    if (a && !a.href.includes('google.com')) return a.href;
                    return null;
                }
                """
            )
            if actual_url and "google.com" not in actual_url:
                logger.info(
                    "[web_scrape] job #%d: Google News → %s", job_id, actual_url[:80]
                )
                page.goto(actual_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            logger.warning(
                "[web_scrape] job #%d: Google News redirect resolve failed: %s",
                job_id,
                exc,
            )

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
