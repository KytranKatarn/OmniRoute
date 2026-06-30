"""LinkedIn profile edit skill — updates headline and about section."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_profile_edit"
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


def _click_first(page, attempts, label="button"):
    for fn in attempts:
        try:
            fn()
            return True
        except Exception:
            continue
    return False


def _fill_modal_field(page, field_label_hints, value, timeout=10000):
    """Try multiple strategies to fill a field inside an open modal."""
    for hint in field_label_hints:
        try:
            page.get_by_label(hint, exact=False).first.fill(value, timeout=timeout)
            return True
        except Exception:
            pass
    # Fallback: input/textarea with matching id fragment
    for frag in field_label_hints:
        try:
            page.locator(f'input[id*="{frag}"], textarea[id*="{frag}"]').first.fill(value, timeout=5000)
            return True
        except Exception:
            pass
    return False


def execute(page, params: dict) -> dict:
    headline = params.get("headline", "").strip()
    about = params.get("about", "").strip()
    location = params.get("location", "").strip()
    industry = params.get("industry", "Technology, Information and Internet").strip()

    if not headline and not about and not location:
        raise ValueError("At least one of headline, about, or location is required")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Close any stuck modal from a previous run
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    _screenshot(page, "profile_before")

    updated_fields = []
    errors = []

    # ── HEADLINE + LOCATION (both use the same intro modal) ──────────────────
    if headline or location:
        opened = _click_first(page, [
            # Confirmed live 2026-06-30 (Terry/377): intro edit is <a aria-label="Edit profile">
            lambda: page.locator('a[aria-label="Edit profile"]').first.click(timeout=8000),
            lambda: page.get_by_role("link", name="Edit profile", exact=True).first.click(timeout=8000),
            # Older LinkedIn UI fallbacks — pencil near name/headline
            lambda: page.locator('[aria-label*="Edit your name"]').first.click(timeout=8000),
            lambda: page.locator('[aria-label*="Edit intro"]').first.click(timeout=8000),
            lambda: page.get_by_role("button", name="Edit intro", exact=False).first.click(timeout=8000),
            # Pencil icon at top-right of intro card (circle button near profile photo)
            lambda: page.locator('section.artdeco-card button.artdeco-button--circle').first.click(timeout=8000),
            lambda: page.locator('div.pv-text-details__left-panel').locator('..').locator('button').first.click(timeout=8000),
        ], "headline edit button")

        if opened:
            page.wait_for_timeout(2000)
            _screenshot(page, "headline_modal_open")

            # Headline (optional)
            if headline:
                filled = _fill_modal_field(page,
                    ["headline", "Headline", "SUMMARY-headline", "professional-headline"],
                    headline)
                if filled:
                    updated_fields.append("headline")
                else:
                    errors.append("headline_field_not_found")

            # Industry — required field, fill to unblock Save
            try:
                ind_field = page.get_by_label("Industry", exact=False).first
                ind_field.fill(industry, timeout=5000)
                page.wait_for_timeout(800)
                page.locator('[role="option"]').first.click(timeout=4000)
                page.wait_for_timeout(500)
            except Exception:
                pass

            # Location — scroll modal down to reveal Country/City fields
            if location:
                try:
                    # Scroll the modal body to bottom to reveal location fields
                    page.evaluate("""() => {
                        const modals = document.querySelectorAll('[role="dialog"], .artdeco-modal__content');
                        for (const m of modals) { m.scrollTop = m.scrollHeight; }
                    }""")
                    page.wait_for_timeout(800)
                except Exception:
                    pass

                # Country/Region — select Canada
                try:
                    page.get_by_label("Country/Region", exact=False).first.select_option(
                        label="Canada", timeout=4000)
                    page.wait_for_timeout(500)
                except Exception:
                    try:
                        page.locator('select[id*="country"], select[id*="region"]').first.select_option(
                            label="Canada", timeout=3000)
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

                # City field
                city_filled = False
                for city_sel in [
                    lambda: page.get_by_label("City", exact=False).first,
                    lambda: page.locator('input[id*="city"]').first,
                    lambda: page.locator('input[placeholder*="ity"]').first,
                ]:
                    try:
                        f = city_sel()
                        f.scroll_into_view_if_needed(timeout=3000)
                        f.fill(location, timeout=4000)
                        page.wait_for_timeout(800)
                        try:
                            page.locator('[role="option"]').first.click(timeout=3000)
                        except Exception:
                            pass
                        city_filled = True
                        break
                    except Exception:
                        continue

                if city_filled:
                    updated_fields.append("location")
                else:
                    errors.append("location_field_not_found")

            # Save
            _click_first(page, [
                lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
                lambda: page.locator('button[aria-label="Save"]').last.click(timeout=5000),
            ], "save intro")
            page.wait_for_timeout(2000)
            # Dismiss post-save modal
            for dismiss in [
                lambda: page.get_by_role("button", name="No thanks", exact=False).click(timeout=3000),
                lambda: page.keyboard.press("Escape"),
            ]:
                try:
                    dismiss()
                    page.wait_for_timeout(500)
                    break
                except Exception:
                    pass
            page.wait_for_timeout(1000)
        else:
            errors.append("intro_edit_button_not_found")
            _screenshot(page, "headline_button_fail")

    # ── ABOUT ─────────────────────────────────────────────────────────────────
    if about:
        # Scroll the page so the About card (or its add-affordance) is in the DOM.
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(600)
        except Exception:
            pass

        # Open the About editor. Confirmed live 2026-06-30 (Terry/377): the control is
        # an <a aria-label="Edit about"> (present whether About exists OR is being added).
        opened = _click_first(page, [
            lambda: page.locator('a[aria-label="Edit about"]').first.click(timeout=6000),
            lambda: page.locator('[aria-label="Edit About section"]').first.click(timeout=5000),
            lambda: page.locator('[aria-label*="Edit about"]').first.click(timeout=5000),
        ], "about edit link")

        if not opened:
            # No existing About — add it via the "Add section" entry (an <a>, not a button),
            # then expand Core and pick About.
            added = _click_first(page, [
                lambda: page.get_by_role("link", name="Add section", exact=False).first.click(timeout=6000),
                lambda: page.locator('a:has-text("Add section")').first.click(timeout=6000),
                lambda: page.get_by_role("button", name="Add profile section", exact=False).click(timeout=6000),
            ], "add section entry")
            if added:
                page.wait_for_timeout(1500)
                _screenshot(page, "add_section_menu")
                # LinkedIn groups About under the "Core" category — expand it if collapsed.
                _click_first(page, [
                    lambda: page.get_by_role("button", name="Add core", exact=False).click(timeout=4000),
                    lambda: page.locator('button:has-text("Core")').first.click(timeout=3000),
                ], "expand core")
                page.wait_for_timeout(800)
                opened = _click_first(page, [
                    lambda: page.get_by_role("button", name="Add about", exact=False).click(timeout=5000),
                    lambda: page.get_by_role("menuitem", name="About", exact=False).click(timeout=5000),
                    lambda: page.get_by_text("Add about", exact=False).first.click(timeout=5000),
                    lambda: page.locator('button:has-text("About")').first.click(timeout=5000),
                    lambda: page.get_by_text("About", exact=True).first.click(timeout=6000),
                ], "about menu item")

        if opened:
            page.wait_for_timeout(2000)
            _screenshot(page, "about_modal_open")
            # Fill the about textarea — try multiple approaches
            filled = False
            for sel in [
                'textarea[id*="summary"]',
                'textarea[id*="about"]',
                'div.ql-editor',
                '[contenteditable="true"]',
                'textarea',
            ]:
                try:
                    loc = page.locator(sel).last
                    loc.wait_for(state="visible", timeout=5000)
                    loc.click(timeout=3000)
                    loc.fill(about, timeout=15000)
                    filled = True
                    break
                except Exception:
                    pass

            if filled:
                page.wait_for_timeout(500)
                _click_first(page, [
                    lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
                    lambda: page.locator('button[aria-label="Save"]').last.click(timeout=5000),
                ], "save about")
                page.wait_for_timeout(2000)
                updated_fields.append("about")
            else:
                errors.append("about_field_not_found")
        else:
            errors.append("about_section_button_not_found")
            _screenshot(page, "about_button_fail")

    final_screenshot = _screenshot(page, "profile_after")
    return {
        "success": len(updated_fields) > 0,
        "result": f"Updated: {', '.join(updated_fields)}" if updated_fields else "No fields updated",
        "updated_fields": updated_fields,
        "errors": errors,
        "screenshot_path": final_screenshot,
    }
