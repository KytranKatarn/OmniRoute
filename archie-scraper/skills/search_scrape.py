"""Skill: search_scrape — Navigate search engine and extract results."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    result_sel = params.get("result_selector") or "h3,h2"
    max_results = int(params.get("max_results") or 20)
    wait_for = params.get("wait_for")

    page.goto(url, wait_until="networkidle", timeout=30000)
    if wait_for:
        page.wait_for_selector(wait_for, timeout=10000)

    result_els = page.query_selector_all(result_sel)[:max_results]
    results = []
    for el in result_els:
        text = el.inner_text().strip()
        if not text:
            continue
        href = None
        try:
            link = el.query_selector("a")
            if link:
                href = link.get_attribute("href")
        except Exception:
            pass
        results.append({"text": text[:300], "url": href})

    findings = f"Found {len(results)} results from {url}"
    return {"data": {"results": results, "source": url}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True}
