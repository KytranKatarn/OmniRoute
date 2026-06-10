"""LinkedIn company page edit — updates tagline, description, website, industry."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_company_edit"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    # Diagnostic only — non-fatal. Bare page.screenshot() times out at 30s on
    # LinkedIn's animated composer and falsely fails posts (#3953). 5s timeout
    # + animations disabled + swallow errors.
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def execute(page, params: dict) -> dict:
    company_slug = params.get("company_slug", "kytran-empowerment")
    tagline = params.get("tagline", "").strip()
    description = params.get("description", "").strip()
    website = params.get("website", "").strip()
    industry = params.get("industry", "").strip()

    if not any([tagline, description, website, industry]):
        raise ValueError("At least one field required: tagline, description, website, industry")

    # Navigate to company page — LinkedIn auto-redirects admins to admin view
    company_url = f"https://www.linkedin.com/company/{company_slug}/"
    page.goto(company_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "company_before")

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Click "Edit Page" — appears in left sidebar on admin view
    opened = False
    for btn in [
        lambda: page.get_by_role("link", name="Edit Page", exact=True).click(timeout=8000),
        lambda: page.locator('a:has-text("Edit Page")').first.click(timeout=8000),
        lambda: page.get_by_role("link", name="Edit page", exact=False).first.click(timeout=8000),
        lambda: page.locator('nav a:has-text("Edit")').first.click(timeout=6000),
        # Fallback: top-right edit button on public view
        lambda: page.get_by_role("button", name="Edit page", exact=False).first.click(timeout=6000),
        lambda: page.locator('[data-control-name="page_edit"]').first.click(timeout=6000),
    ]:
        try:
            btn()
            opened = True
            break
        except Exception:
            continue

    if not opened:
        _screenshot(page, "company_edit_btn_fail")
        raise RuntimeError("Could not find Edit page button — check admin access")

    page.wait_for_timeout(2000)
    _screenshot(page, "company_edit_open")

    updated_fields = []
    errors = []

    # Tagline is on the default "Page info" tab
    if tagline:
        for field in [
            lambda: page.get_by_label("Tagline", exact=False).first.fill(tagline, timeout=6000),
            lambda: page.locator('input[id*="tagline"], textarea[id*="tagline"]').first.fill(tagline, timeout=5000),
            lambda: page.locator('input[name*="tagline"]').first.fill(tagline, timeout=5000),
        ]:
            try:
                field()
                updated_fields.append("tagline")
                break
            except Exception:
                continue

    # Description, website, industry are under "About → Details" tab in the edit modal
    if description or website or industry:
        for details_btn in [
            lambda: page.get_by_role("button", name="Details", exact=True).click(timeout=6000),
            lambda: page.locator('button:has-text("Details")').first.click(timeout=6000),
            lambda: page.get_by_text("Details", exact=True).first.click(timeout=6000),
        ]:
            try:
                details_btn()
                page.wait_for_timeout(1500)
                break
            except Exception:
                continue

    # Description / Overview
    if description:
        for field in [
            lambda: page.get_by_label("Overview", exact=False).first.fill(description, timeout=6000),
            lambda: page.get_by_label("Description", exact=False).first.fill(description, timeout=6000),
            lambda: page.locator('textarea[id*="overview"]').first.fill(description, timeout=5000),
            lambda: page.locator('textarea[id*="description"]').first.fill(description, timeout=5000),
            lambda: page.locator('textarea[name*="description"]').first.fill(description, timeout=5000),
            lambda: page.locator('textarea').last.fill(description, timeout=5000),
        ]:
            try:
                field()
                updated_fields.append("description")
                break
            except Exception:
                continue

    # Website
    if website:
        for field in [
            lambda: page.get_by_label("Website", exact=False).first.fill(website, timeout=6000),
            lambda: page.locator('input[id*="website"], input[name*="website"]').first.fill(website, timeout=5000),
        ]:
            try:
                field()
                updated_fields.append("website")
                break
            except Exception:
                continue

    # Industry
    if industry:
        try:
            ind = page.get_by_label("Industry", exact=False).first
            ind.fill(industry, timeout=5000)
            page.wait_for_timeout(800)
            page.locator('[role="option"]').first.click(timeout=3000)
            updated_fields.append("industry")
        except Exception:
            errors.append("industry_field_not_found")

    page.wait_for_timeout(500)
    _screenshot(page, "company_filled")

    # Save
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
        lambda: page.get_by_role("button", name="Save changes", exact=False).last.click(timeout=6000),
        lambda: page.locator('button[type="submit"]').last.click(timeout=5000),
    ]:
        try:
            save_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)

    # Dismiss follow-up
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    final = _screenshot(page, "company_after")
    return {
        "success": len(updated_fields) > 0,
        "result": f"Updated company: {', '.join(updated_fields)}" if updated_fields else "No fields updated",
        "updated_fields": updated_fields,
        "errors": errors,
        "screenshot_path": final,
    }
