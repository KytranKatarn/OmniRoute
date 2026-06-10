"""LinkedIn add experience skill — adds a work experience entry to the profile."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_add_experience"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

_MONTHS = {
    "january": "1", "february": "2", "march": "3", "april": "4",
    "may": "5", "june": "6", "july": "7", "august": "8",
    "september": "9", "october": "10", "november": "11", "december": "12",
}


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


def _select_month_year(page, month_label, year_label, month_val, year_val):
    """Select month and year from LinkedIn date dropdowns."""
    try:
        page.get_by_label(month_label, exact=False).select_option(value=str(month_val), timeout=5000)
    except Exception:
        try:
            page.get_by_label(month_label, exact=False).select_option(label=month_val, timeout=5000)
        except Exception:
            pass
    try:
        page.get_by_label(year_label, exact=False).select_option(value=str(year_val), timeout=5000)
    except Exception:
        try:
            page.get_by_label(year_label, exact=False).fill(str(year_val), timeout=5000)
        except Exception:
            pass


def execute(page, params: dict) -> dict:
    title = params.get("title", "").strip()
    company = params.get("company", "").strip()
    location = params.get("location", "").strip()
    description = params.get("description", "").strip()
    start_month = params.get("start_month", "January")
    start_year = params.get("start_year", "2023")
    current = params.get("currently_working", True)
    end_month = params.get("end_month", "")
    end_year = params.get("end_year", "")

    if not title or not company:
        raise ValueError("title and company are required for linkedin_add_experience")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Close any open modal
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Open "Add profile section"
    opened = False
    for btn in [
        lambda: page.get_by_role("button", name="Add profile section", exact=False).click(timeout=8000),
        lambda: page.locator('button:has-text("Add profile section")').click(timeout=8000),
    ]:
        try:
            btn()
            opened = True
            break
        except Exception:
            continue

    if not opened:
        _screenshot(page, "exp_add_section_fail")
        raise RuntimeError("Could not find Add profile section button")

    page.wait_for_timeout(1500)
    _screenshot(page, "exp_section_menu")

    # Navigate to Work Experience
    for exp_btn in [
        lambda: page.get_by_role("button", name="Add position", exact=False).click(timeout=6000),
        lambda: page.get_by_role("menuitem", name="Work experience", exact=False).click(timeout=6000),
        lambda: page.get_by_text("Work experience", exact=False).first.click(timeout=6000),
        lambda: page.get_by_text("Add position", exact=False).first.click(timeout=6000),
        # Sometimes need to expand "Core" section first
        lambda: page.get_by_role("button", name="Core", exact=False).click(timeout=4000),
    ]:
        try:
            exp_btn()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # If we expanded Core, now try again
    for exp_btn in [
        lambda: page.get_by_role("button", name="Add position", exact=False).click(timeout=5000),
        lambda: page.get_by_text("Work experience", exact=False).first.click(timeout=5000),
    ]:
        try:
            exp_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    _screenshot(page, "exp_modal_open")

    # Fill Title
    for field in [
        lambda: page.get_by_label("Title", exact=False).first.fill(title, timeout=8000),
        lambda: page.locator('input[id*="title"]').first.fill(title, timeout=5000),
        lambda: page.locator('input[aria-label*="itle"]').first.fill(title, timeout=5000),
    ]:
        try:
            field()
            break
        except Exception:
            continue

    page.wait_for_timeout(500)

    # Fill Company (with typeahead)
    for field in [
        lambda: page.get_by_label("Company name", exact=False).first.fill(company, timeout=8000),
        lambda: page.locator('input[id*="company"]').first.fill(company, timeout=5000),
        lambda: page.locator('input[aria-label*="ompany"]').first.fill(company, timeout=5000),
    ]:
        try:
            field()
            break
        except Exception:
            continue

    page.wait_for_timeout(1200)
    # Dismiss company typeahead suggestion or press Escape to keep typed value
    try:
        page.locator('[role="option"]').first.click(timeout=3000)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    page.wait_for_timeout(500)

    # Currently working here checkbox
    if current:
        for chk in [
            lambda: page.get_by_label("I am currently working in this role", exact=False).check(timeout=5000),
            lambda: page.locator('input[type="checkbox"]').first.check(timeout=5000),
        ]:
            try:
                chk()
                break
            except Exception:
                continue

    # Start date
    month_num = _MONTHS.get(start_month.lower(), start_month)
    _select_month_year(page, "Start month", "Start year", month_num, start_year)

    # End date (if not current)
    if not current and end_month and end_year:
        end_num = _MONTHS.get(end_month.lower(), end_month)
        _select_month_year(page, "End month", "End year", end_num, end_year)

    # Location
    if location:
        for field in [
            lambda: page.get_by_label("Location", exact=False).first.fill(location, timeout=5000),
            lambda: page.locator('input[id*="location"]').first.fill(location, timeout=5000),
        ]:
            try:
                field()
                page.wait_for_timeout(800)
                # Dismiss typeahead
                try:
                    page.locator('[role="option"]').first.click(timeout=2000)
                except Exception:
                    page.keyboard.press("Escape")
                break
            except Exception:
                continue

    # Description
    if description:
        for field in [
            lambda: page.get_by_label("Description", exact=False).first.fill(description, timeout=5000),
            lambda: page.locator('textarea[id*="description"]').first.fill(description, timeout=5000),
        ]:
            try:
                field()
                break
            except Exception:
                continue

    page.wait_for_timeout(500)
    _screenshot(page, "exp_filled")

    # Save
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
        lambda: page.locator('button[aria-label="Save"]').last.click(timeout=5000),
    ]:
        try:
            save_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(3000)

    # Dismiss follow-up modals
    for dismiss in [
        lambda: page.get_by_role("button", name="No thanks", exact=False).click(timeout=3000),
        lambda: page.keyboard.press("Escape"),
    ]:
        try:
            dismiss()
            page.wait_for_timeout(500)
            break
        except Exception:
            continue

    final = _screenshot(page, "exp_final")
    return {
        "success": True,
        "result": f"Added experience: {title} at {company}",
        "screenshot_path": final,
    }
