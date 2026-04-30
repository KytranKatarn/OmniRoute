"""LinkedIn follow — follows a person or company page."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_follow"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    url = params.get("url", "").strip()
    name = params.get("name", url).strip()  # display name for logging

    if not url:
        raise ValueError("url is required for linkedin_follow")

    page.goto(url.split("?")[0], wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Check if already following
    already = False
    try:
        page.locator('button[aria-label*="Following"]').first.wait_for(state="visible", timeout=2000)
        already = True
    except Exception:
        pass

    if already:
        return {
            "success": True,
            "result": f"Already following: {name}",
            "url": url,
            "screenshot_path": _screenshot(page, "follow_already"),
        }

    # Click Follow button
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Follow", exact=True).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="Follow"]').first.click(timeout=6000),
        lambda: page.locator('button:has-text("Follow")').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "follow_fail")
        return {
            "success": False,
            "result": f"Could not find Follow button for: {name}",
            "url": url,
            "screenshot_path": _screenshot(page, "follow_fail"),
        }

    page.wait_for_timeout(1500)
    return {
        "success": True,
        "result": f"Now following: {name}",
        "url": url,
        "screenshot_path": _screenshot(page, "follow_done"),
    }
