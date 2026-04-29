"""LinkedIn company logo upload — sets the company page logo image."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_company_logo"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    company_slug = params.get("company_slug", "kytran-empowerment")
    logo_path = params.get("logo_path", "").strip()
    if not logo_path:
        raise ValueError("logo_path is required")
    if not os.path.exists(logo_path):
        raise ValueError(f"logo_path not found: {logo_path}")

    company_url = f"https://www.linkedin.com/company/{company_slug}/"
    page.goto(company_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "company_logo_before")

    # Click the logo edit area (pencil on logo or camera icon)
    clicked = False
    for attempt in [
        lambda: page.locator('[aria-label*="logo"]').first.click(timeout=8000),
        lambda: page.locator('[aria-label*="Logo"]').first.click(timeout=8000),
        lambda: page.locator('button.org-photo-edit__photo-btn').first.click(timeout=6000),
        lambda: page.locator('.org-top-card-summary-info-list button').first.click(timeout=6000),
        lambda: page.locator('img[class*="logo"]').locator('..').locator('button').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        # Try via Edit page → logo section
        try:
            page.get_by_role("button", name="Edit page", exact=False).first.click(timeout=8000)
            page.wait_for_timeout(2000)
            page.locator('[data-test-id*="logo"], [aria-label*="logo"]').first.click(timeout=6000)
            clicked = True
        except Exception:
            pass

    if not clicked:
        _screenshot(page, "company_logo_btn_fail")
        raise RuntimeError("Could not find company logo edit button")

    page.wait_for_timeout(2000)
    _screenshot(page, "company_logo_modal")

    # Upload option
    for upload_opt in [
        lambda: page.get_by_role("button", name="Upload photo", exact=False).click(timeout=5000),
        lambda: page.get_by_text("Upload photo", exact=False).first.click(timeout=5000),
        lambda: page.get_by_role("button", name="Upload", exact=False).click(timeout=5000),
    ]:
        try:
            upload_opt()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # File input
    file_input = None
    for sel in ['input[type="file"]', 'input[accept*="image"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=8000)
            file_input = loc
            break
        except Exception:
            continue

    if file_input is None:
        _screenshot(page, "company_logo_input_fail")
        raise RuntimeError("Could not find file input for logo upload")

    file_input.set_input_files(logo_path)
    page.wait_for_timeout(3000)
    _screenshot(page, "company_logo_crop")

    # Apply crop
    for apply_btn in [
        lambda: page.get_by_role("button", name="Apply", exact=True).click(timeout=8000),
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
        lambda: page.locator('button:has-text("Apply")').last.click(timeout=5000),
    ]:
        try:
            apply_btn()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    # Final save
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
        lambda: page.locator('button[type="submit"]').last.click(timeout=5000),
    ]:
        try:
            save_btn()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    final = _screenshot(page, "company_logo_final")
    return {
        "success": True,
        "result": "Company logo uploaded",
        "logo_path": logo_path,
        "screenshot_path": final,
    }
