# archie-scraper/skills/ux_audit.py
"""Skill: ux_audit — Multi-viewport screenshot walk-through."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        viewport  str  "WIDTHxHEIGHT" (default "1280x800")
    """
    viewport_str = params.get("viewport") or "1280x800"
    try:
        parts = viewport_str.split("x")
        w, h = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        w, h = 1280, 800

    screenshots = []
    console_errors: list = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

    # Desktop
    page.set_viewport_size({"width": w, "height": h})
    page.goto(url, wait_until="networkidle", timeout=45000)
    path = save_screenshot(job_id, "desktop_homepage", page)
    screenshots.append(screenshot_entry("desktop_homepage", path, "Desktop homepage"))

    title = page.title()
    h1s = [el.inner_text().strip() for el in page.query_selector_all("h1")]

    # Mobile
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="networkidle", timeout=30000)
    path = save_screenshot(job_id, "mobile_homepage", page)
    screenshots.append(screenshot_entry("mobile_homepage", path, "Mobile (390px)"))

    findings_parts = [f"Title: {title}", f"H1s: {', '.join(h1s) or 'none found'}"]
    if console_errors:
        findings_parts.append(
            f"Console errors ({len(console_errors)}): {'; '.join(console_errors[:3])}"
        )

    logger.info(
        "[ux_audit] job #%d: %d screenshots, %d console errors",
        job_id,
        len(screenshots),
        len(console_errors),
    )

    return {
        "data": {
            "title": title,
            "h1s": h1s,
            "console_errors": console_errors[:10],
            "viewports_tested": [f"{w}x{h}", "390x844"],
        },
        "screenshots": screenshots,
        "network_log": [],
        "findings": "\n".join(findings_parts),
        "auto_approve": False,
    }
