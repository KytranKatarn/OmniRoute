"""LinkedIn add skill skill — adds a single skill to the profile."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_add_skill"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    skill = params.get("skill", "").strip()
    if not skill:
        raise ValueError("skill is required for linkedin_add_skill")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Scroll to Skills section if it exists and click the + button
    has_skills_section = False
    try:
        page.locator("#skills").first.wait_for(state="attached", timeout=3000)
        has_skills_section = True
    except Exception:
        pass

    if has_skills_section:
        try:
            page.locator("#skills").first.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(1000)
            # Click the + add button inside the skills section
            result = page.evaluate("""() => {
                const h = document.getElementById('skills');
                if (!h) return false;
                const section = h.closest('section');
                if (!section) return false;
                const btns = section.querySelectorAll('button');
                for (const b of btns) {
                    const lbl = (b.getAttribute('aria-label') || b.textContent || '').toLowerCase();
                    if (lbl.includes('add') || lbl.includes('+')) { b.click(); return true; }
                }
                return false;
            }""")
            if not result:
                raise Exception("Skills add button not found via JS")
            page.wait_for_timeout(1500)
        except Exception:
            has_skills_section = False

    if not has_skills_section:
        # Add via "Add profile section" → Skills
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
            _screenshot(page, "skill_add_section_fail")
            raise RuntimeError("Could not find Add profile section button")

        page.wait_for_timeout(1500)

        # Navigate to Skills
        for skills_btn in [
            lambda: page.get_by_role("button", name="Add skills", exact=False).click(timeout=6000),
            lambda: page.get_by_role("menuitem", name="Skills", exact=False).click(timeout=6000),
            lambda: page.get_by_text("Skills", exact=True).first.click(timeout=6000),
            lambda: page.get_by_role("button", name="Recommended", exact=False).click(timeout=4000),
        ]:
            try:
                skills_btn()
                page.wait_for_timeout(1000)
                break
            except Exception:
                continue

        # Try expanding "Recommended" or "Skills" sub-category
        for sub in [
            lambda: page.get_by_text("Skills", exact=True).first.click(timeout=4000),
            lambda: page.get_by_role("button", name="Add skills", exact=False).click(timeout=4000),
        ]:
            try:
                sub()
                break
            except Exception:
                continue

    page.wait_for_timeout(2000)
    _screenshot(page, "skill_modal_open")

    # Fill the skill search field
    filled = False
    for field in [
        lambda: page.get_by_label("Skill", exact=False).first.fill(skill, timeout=8000),
        lambda: page.locator('input[id*="skill"]').first.fill(skill, timeout=5000),
        lambda: page.locator('input[aria-label*="kill"]').first.fill(skill, timeout=5000),
        lambda: page.locator('input[placeholder*="skill"], input[placeholder*="Skill"]').first.fill(skill, timeout=5000),
        lambda: page.locator('input[type="text"]').first.fill(skill, timeout=5000),
    ]:
        try:
            field()
            filled = True
            break
        except Exception:
            continue

    if not filled:
        _screenshot(page, "skill_field_fail")
        raise RuntimeError(f"Could not find skill input field for: {skill}")

    page.wait_for_timeout(1500)
    _screenshot(page, "skill_typeahead")

    # Select first matching suggestion, or press Enter
    for select in [
        lambda: page.locator('[role="option"]').first.click(timeout=4000),
        lambda: page.locator('[role="listbox"] li').first.click(timeout=4000),
        lambda: page.keyboard.press("Enter"),
    ]:
        try:
            select()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # Save
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
        lambda: page.locator('button[aria-label="Save"]').last.click(timeout=5000),
        lambda: page.get_by_role("button", name="Add", exact=True).last.click(timeout=5000),
    ]:
        try:
            save_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)

    # Dismiss any follow-up
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

    final = _screenshot(page, f"skill_added_{skill[:20].replace(' ','_')}")
    return {
        "success": True,
        "result": f"Added skill: {skill}",
        "skill": skill,
        "screenshot_path": final,
    }
