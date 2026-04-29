"""LinkedIn company claim — claims an existing company page via the LinkedIn claim flow."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_company_claim"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    company_name = params.get("name", "Kytran Empowerment Inc.").strip()

    # Navigate to company setup to trigger the URL conflict and get the "view existing page" link
    page.goto("https://www.linkedin.com/company/setup/new/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Select Company type if shown
    for btn in [
        lambda: page.get_by_role("button", name="Company", exact=True).click(timeout=5000),
        lambda: page.locator('button:has-text("Company")').first.click(timeout=4000),
    ]:
        try:
            btn()
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    # Fill company name to trigger URL conflict
    for field in [
        lambda: page.get_by_label("Name", exact=True).fill(company_name, timeout=6000),
        lambda: page.locator('input[placeholder*="organization"]').first.fill(company_name, timeout=5000),
        lambda: page.locator('form input[type="text"]').first.fill(company_name, timeout=5000),
    ]:
        try:
            field()
            page.wait_for_timeout(2500)
            break
        except Exception:
            continue

    _screenshot(page, "claim_form")

    # Wait for conflict message to appear
    try:
        page.locator('text=already in use').wait_for(state="visible", timeout=6000)
    except Exception:
        pass

    _screenshot(page, "claim_conflict")

    # Click "view the existing Page" link
    clicked_view = False
    for link in [
        lambda: page.get_by_text("view the existing Page", exact=False).first.click(timeout=6000),
        lambda: page.get_by_role("link", name="view the existing Page", exact=False).click(timeout=6000),
        lambda: page.locator('a:has-text("view the existing")').first.click(timeout=6000),
        lambda: page.locator('a:has-text("existing Page")').first.click(timeout=5000),
    ]:
        try:
            link()
            clicked_view = True
            break
        except Exception:
            continue

    if not clicked_view:
        _screenshot(page, "claim_view_fail")
        raise RuntimeError("Could not find 'view the existing Page' link — company may not exist yet")

    page.wait_for_timeout(3000)
    _screenshot(page, "claim_existing_page")

    current_url = page.url

    # Look for Claim / Request admin access button
    claimed = False
    for claim_btn in [
        lambda: page.get_by_role("button", name="Claim", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Request admin access", exact=False).click(timeout=6000),
        lambda: page.get_by_text("Claim this page", exact=False).first.click(timeout=6000),
        lambda: page.get_by_text("Request admin", exact=False).first.click(timeout=6000),
        lambda: page.locator('[data-control-name*="claim"]').first.click(timeout=5000),
    ]:
        try:
            claim_btn()
            claimed = True
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    _screenshot(page, "claim_after_click")

    # If a verification modal appeared, take screenshot and report
    final_url = page.url
    page_text = ""
    try:
        page_text = page.locator("body").inner_text(timeout=3000)[:500]
    except Exception:
        pass

    final = _screenshot(page, "claim_final")
    return {
        "success": claimed,
        "result": "Claim initiated — check screenshot for verification step" if claimed else "Could not find Claim button",
        "page_url": current_url,
        "final_url": final_url,
        "page_text_preview": page_text,
        "screenshot_path": final,
    }
