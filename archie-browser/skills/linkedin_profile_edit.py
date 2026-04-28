"""LinkedIn profile edit skill — updates headline and about section."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_profile_edit"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def execute(page, params: dict) -> dict:
    headline = params.get("headline", "").strip()
    about = params.get("about", "").strip()

    if not headline and not about:
        raise ValueError("At least one of headline or about is required")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    updated_fields = []
    if headline:
        try:
            page.get_by_role("button", name="Edit intro").click(timeout=10000)
        except Exception:
            page.locator('[aria-label="Edit intro"]').click(timeout=10000)
        page.wait_for_timeout(1500)

        headline_field = page.locator('#single-line-text-form-component-profileEditFormElement-SUMMARY-headline')
        if not headline_field.is_visible():
            headline_field = page.get_by_label("Headline")
        headline_field.fill(headline, timeout=10000)
        page.get_by_role("button", name="Save").click(timeout=10000)
        page.wait_for_timeout(2000)
        updated_fields.append("headline")

    if about:
        page.locator('section[data-section="summary"] button[aria-label*="Edit"]').first.click(timeout=10000)
        page.wait_for_timeout(1000)
        ta = page.locator('textarea[id*="summary"], div.ql-editor[data-placeholder*="summary"]').first
        ta.clear()
        ta.fill(about, timeout=10000)
        page.locator('button[aria-label="Save"]').first.click(timeout=10000)
        page.wait_for_timeout(2000)
        updated_fields.append("about")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_profile_{ts}.png"
    page.screenshot(path=screenshot_path)
    return {
        "success": True,
        "result": f"Updated LinkedIn profile fields: {', '.join(updated_fields)}",
        "updated_fields": updated_fields,
        "screenshot_path": screenshot_path,
    }
