"""Skill: ancestry_research — Ancestry.com record search behind login."""
import logging
from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    username = params.get("username", "")
    password = params.get("password", "")
    search_name = params.get("search_name", "")
    birth_year = params.get("birth_year", "")

    screenshots = []
    page.goto("https://www.ancestry.com/account/signin", wait_until="networkidle", timeout=30000)
    try:
        page.fill("#username", username)
        page.fill("#password", password)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        logger.warning("[ancestry_research] job #%d: login interaction failed", job_id)

    search_url = url or "https://search.ancestry.com/search/"
    page.goto(search_url, wait_until="networkidle", timeout=30000)
    try:
        page.fill("#sb_firstName", search_name.split()[0] if search_name else "")
        if " " in search_name:
            page.fill("#sb_lastName", " ".join(search_name.split()[1:]))
        if birth_year:
            page.fill("[name*='birthYear'],[name*='BirthYear']", str(birth_year))
        page.click("button[type=submit],[id*=search]")
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    path = save_screenshot(job_id, "results", page)
    screenshots.append(screenshot_entry("results", path, f"Ancestry results for {search_name}"))

    records = []
    try:
        for el in page.query_selector_all(".searchResultItem,.card-body,.result-item")[:20]:
            text = el.inner_text().strip()
            if text:
                records.append({"text": text[:300]})
    except Exception:
        pass

    findings = f"Found {len(records)} record(s) for '{search_name}' on Ancestry"
    return {
        "data": {"records": records, "search_name": search_name},
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
