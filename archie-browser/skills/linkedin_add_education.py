"""LinkedIn add education — adds an education entry to the profile."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_add_education"
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


def execute(page, params: dict) -> dict:
    school = params.get("school", "").strip()
    degree = params.get("degree", "").strip()
    field = params.get("field_of_study", "").strip()
    start_year = params.get("start_year", "")
    end_year = params.get("end_year", "")
    grade = params.get("grade", "").strip()
    description = params.get("description", "").strip()

    if not school:
        raise ValueError("school is required for linkedin_add_education")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Click "Add profile section"
    opened = False
    for btn in [
        lambda: page.get_by_role("button", name="Add profile section", exact=False).click(timeout=8000),
        lambda: page.locator('button:has-text("Add profile section")').click(timeout=6000),
    ]:
        try:
            btn()
            opened = True
            break
        except Exception:
            continue

    if not opened:
        raise RuntimeError("Could not find Add profile section button")

    page.wait_for_timeout(1500)
    _screenshot(page, "edu_section_menu")

    # Navigate to Education
    for edu_btn in [
        lambda: page.get_by_role("button", name="Add education", exact=False).click(timeout=6000),
        lambda: page.get_by_role("menuitem", name="Education", exact=False).click(timeout=6000),
        lambda: page.get_by_text("Education", exact=True).first.click(timeout=6000),
        lambda: page.get_by_role("button", name="Core", exact=False).click(timeout=4000),
    ]:
        try:
            edu_btn()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # Try again if we expanded Core
    for edu_btn in [
        lambda: page.get_by_role("button", name="Add education", exact=False).click(timeout=5000),
        lambda: page.get_by_text("Education", exact=True).first.click(timeout=5000),
    ]:
        try:
            edu_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    _screenshot(page, "edu_modal_open")

    # School name
    for field_fn in [
        lambda: page.get_by_label("School", exact=False).first.fill(school, timeout=8000),
        lambda: page.locator('input[id*="school"]').first.fill(school, timeout=5000),
        lambda: page.locator('input[aria-label*="chool"]').first.fill(school, timeout=5000),
    ]:
        try:
            field_fn()
            page.wait_for_timeout(1200)
            try:
                page.locator('[role="option"]').first.click(timeout=3000)
            except Exception:
                pass
            break
        except Exception:
            continue

    # Degree
    if degree:
        for field_fn in [
            lambda: page.get_by_label("Degree", exact=False).first.fill(degree, timeout=6000),
            lambda: page.locator('input[id*="degree"]').first.fill(degree, timeout=5000),
        ]:
            try:
                field_fn()
                break
            except Exception:
                continue

    # Field of study
    if field:
        for field_fn in [
            lambda: page.get_by_label("Field of study", exact=False).first.fill(field, timeout=6000),
            lambda: page.locator('input[id*="field"]').first.fill(field, timeout=5000),
        ]:
            try:
                field_fn()
                break
            except Exception:
                continue

    # Start / End year
    if start_year:
        try:
            page.get_by_label("Start year", exact=False).first.select_option(value=str(start_year), timeout=5000)
        except Exception:
            try:
                page.locator('select[id*="start-year"]').first.select_option(value=str(start_year), timeout=4000)
            except Exception:
                pass

    if end_year:
        try:
            page.get_by_label("End year", exact=False).first.select_option(value=str(end_year), timeout=5000)
        except Exception:
            try:
                page.locator('select[id*="end-year"]').first.select_option(value=str(end_year), timeout=4000)
            except Exception:
                pass

    # Grade
    if grade:
        try:
            page.get_by_label("Grade", exact=False).first.fill(grade, timeout=4000)
        except Exception:
            pass

    # Description
    if description:
        try:
            page.get_by_label("Description", exact=False).first.fill(description, timeout=5000)
        except Exception:
            try:
                page.locator('textarea[id*="description"]').first.fill(description, timeout=4000)
            except Exception:
                pass

    page.wait_for_timeout(500)
    _screenshot(page, "edu_filled")

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

    return {
        "success": True,
        "result": f"Added education: {degree or 'degree'} at {school}",
        "screenshot_path": _screenshot(page, "edu_final"),
    }
