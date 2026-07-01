"""LinkedIn profile edit — updates headline + about via the edit ROUTES.

Live-verified 2026-06-30 (Terry/377, screenshot-confirmed): clicking "Edit
profile" opens the "Edit intro" modal AT THE ROUTE /in/<vanity>/edit/intro/.
The modal's fields are NOT inside a <form> and are shadow-DOM-ish: raw
document.querySelectorAll misses them, but Playwright locators pierce them.

The previous skill failed on TIMING — it filled ~2s after the click, before the
route + modal finished rendering -> "headline_field_not_found". Fix: navigate to
the route directly, WAIT for the modal (its Save button) to render, then fill via
Playwright locators.
"""

SKILL_NAME = "linkedin_profile_edit"
PLATFORMS = ["linkedin"]

# Screenshots to the MOUNTED /profiles volume (host: /mnt/data2/browser-profiles)
# so a verification shot survives — /tmp isn't mounted.
_SHOT_DIR = "/profiles"


def _shot(page, name):
    try:
        page.screenshot(path=f"{_SHOT_DIR}/_edit_{name}.png", timeout=20000, animations="disabled")
        return f"{_SHOT_DIR}/_edit_{name}.png"
    except Exception:
        return None


def _wait_modal(page, timeout=18000):
    """Wait for the edit modal to render. The Save button is the clearest signal."""
    try:
        page.get_by_role("button", name="Save", exact=True).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        page.wait_for_timeout(4000)
        return False


def _fill_first(page, strategies, value):
    for make in strategies:
        try:
            loc = make().first
            loc.wait_for(state="visible", timeout=6000)
            loc.click(timeout=3000)
            try:
                loc.fill(value, timeout=5000)
            except Exception:
                loc.press("Control+a")
                page.wait_for_timeout(120)
                loc.press("Delete")
                loc.type(value, delay=6)
            return True
        except Exception:
            continue
    return False


def _fill_typeahead(page, label, value):
    """Fill a labelled typeahead (Country/Region, City), clearing any existing text,
    then pick the matching suggestion so the value is actually committed."""
    try:
        loc = page.get_by_label(label, exact=False).first
        loc.click(timeout=4000)
        loc.press("Control+a")
        loc.press("Delete")
        loc.type(value, delay=30)
        page.wait_for_timeout(1400)
        for make in [
            lambda: page.get_by_role("option", name=value, exact=False).first,
            lambda: page.locator('[role="option"]').filter(has_text=value.split(",")[0]).first,
            lambda: page.locator('[role="option"]').first,
        ]:
            try:
                opt = make()
                opt.wait_for(state="visible", timeout=2500)
                opt.click(timeout=2500)
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _save(page):
    for make in [
        lambda: page.get_by_role("button", name="Save", exact=True).last,
        lambda: page.locator('button[aria-label="Save"]').last,
        lambda: page.locator('button:has-text("Save")').last,
    ]:
        try:
            make().click(timeout=8000)
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    return False


def execute(page, params: dict) -> dict:
    headline = params.get("headline", "").strip()
    about = params.get("about", "").strip()
    if not any([headline, about, params.get("country"), params.get("city")]):
        raise ValueError("At least one of headline / about / country / city is required")

    updated, errors = [], []

    # ── HEADLINE — /edit/intro/ ──────────────────────────────────────────────
    if headline:
        page.goto("https://www.linkedin.com/in/me/edit/intro/", wait_until="domcontentloaded")
        rendered = _wait_modal(page)
        page.wait_for_timeout(800)
        # Verified Terry/377 via shadow-pierce: the Headline is a
        # <div contenteditable="true" role="textbox"> with NO accessible name
        # (so get_by_label/get_by_role(name=) all miss). It's the ONLY
        # contenteditable among the intro fields -> target it directly.
        filled = _fill_first(page, [
            lambda: page.locator('div[contenteditable="true"][role="textbox"]'),
            lambda: page.locator('[role="textbox"][contenteditable="true"]'),
            lambda: page.get_by_role("textbox").filter(has_text="Coordinator"),
            lambda: page.get_by_role("textbox").nth(3),
        ], headline)
        if filled:
            updated.append("headline") if _save(page) else errors.append("headline_save_failed")
        else:
            errors.append("headline_field_not_found" if rendered else "intro_modal_not_rendered")
        _shot(page, "headline")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass

    # ── LOCATION — Country/Region + City in the /edit/intro/ modal ───────────
    # Both are typeaheads; set Country FIRST (the City list depends on it). Verified
    # field labels via probe 2026-06-30: "Country/Region*" + "City".
    # NOTE (2026-06-30): Country editing is VERIFIED live (Kytran US→Canada). The
    # City typeahead is FLAKY — changing the country re-renders/clears it, and a
    # city-only pass didn't reliably commit (returns city_not_set, never a phantom
    # success). City is best-effort; country is the reliable lever. #4611 follow-up.
    country = params.get("country", "").strip()
    city = params.get("city", "").strip()
    if country or city:
        page.goto("https://www.linkedin.com/in/me/edit/intro/", wait_until="domcontentloaded")
        _wait_modal(page)
        page.wait_for_timeout(800)
        if country:
            updated.append("country") if _fill_typeahead(page, "Country/Region", country) else errors.append("country_not_set")
            page.wait_for_timeout(600)
        if city:
            updated.append("city") if _fill_typeahead(page, "City", city) else errors.append("city_not_set")
        _shot(page, "location")
        if not _save(page):
            errors.append("location_save_failed")

    # ── ABOUT — /edit/about/ (gated on the modal actually rendering, so a
    #    non-About page can't make us fill the wrong field) ────────────────────
    if about:
        page.goto("https://www.linkedin.com/in/me/edit/about/", wait_until="domcontentloaded")
        rendered = _wait_modal(page, timeout=15000)
        page.wait_for_timeout(800)
        if not rendered:
            errors.append("about_route_not_rendered")
        else:
            filled = _fill_first(page, [
                lambda: page.locator('[role="dialog"] div.ql-editor, .artdeco-modal div.ql-editor'),
                lambda: page.locator('[role="dialog"] [contenteditable="true"], .artdeco-modal [contenteditable="true"]'),
                lambda: page.locator('[role="dialog"] textarea, .artdeco-modal textarea'),
            ], about)
            if filled:
                updated.append("about") if _save(page) else errors.append("about_save_failed")
            else:
                errors.append("about_field_not_found")
        _shot(page, "about")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    return {
        "success": len(updated) > 0,
        "result": f"Updated: {', '.join(updated)}" if updated else "No fields updated",
        "updated_fields": updated,
        "errors": errors,
        "screenshot_dir": _SHOT_DIR,
    }
