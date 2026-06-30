"""LinkedIn add experience — adds a position via the add-position ROUTE wizard.

Live-verified 2026-06-30 (Terry/377): https://www.linkedin.com/in/me/add-edit/POSITION/
opens the "Add a role to your profile" 3-STEP WIZARD. Step 1 ("the basics") has
labels **Job title** + **Organization** (+ Location / Employment type / "I currently
work here" / Start month-year) and a **Next** button — the final step has Save/Done.

Fixes over the old skill: it used the dead "Add profile section" button, wrong
labels (Title/Company), only clicked "Save" (missing Next), and verified with a
single-occurrence check that the HEADLINE faked. Now: route + wait + correct
labels + drive Next→Save + verify the company name appears >=2x on the experience
list (header headline + the real entry).
"""

SKILL_NAME = "linkedin_add_experience"
PLATFORMS = ["linkedin"]

_SHOT_DIR = "/profiles"


def _shot(page, name):
    try:
        page.screenshot(path=f"{_SHOT_DIR}/_exp_{name}.png", full_page=False, timeout=15000, animations="disabled")
        return f"{_SHOT_DIR}/_exp_{name}.png"
    except Exception:
        return None


def _click_first(page, attempts):
    for fn in attempts:
        try:
            fn()
            return True
        except Exception:
            continue
    return False


def _fill(page, labels, value, placeholders=()):
    for n in labels:
        try:
            page.get_by_label(n, exact=False).first.fill(value, timeout=5000)
            return True
        except Exception:
            pass
    for ph in placeholders:
        try:
            page.get_by_placeholder(ph, exact=False).first.fill(value, timeout=4000)
            return True
        except Exception:
            pass
    return False


def _select_label(page, field_label, option_label):
    """Select an <option> by its visible label (e.g. month name 'January')."""
    try:
        page.get_by_label(field_label, exact=False).first.select_option(label=str(option_label), timeout=5000)
        return True
    except Exception:
        pass
    try:
        page.get_by_label(field_label, exact=False).first.select_option(value=str(option_label), timeout=4000)
        return True
    except Exception:
        return False


def execute(page, params: dict) -> dict:
    title = params.get("title", "").strip()
    company = params.get("company", "").strip()
    location = params.get("location", "").strip()
    description = params.get("description", "").strip()
    start_month = str(params.get("start_month", "January"))
    start_year = str(params.get("start_year", "2024"))
    current = params.get("currently_working", True)
    end_month = str(params.get("end_month", ""))
    end_year = str(params.get("end_year", ""))

    if not title or not company:
        raise ValueError("title and company are required for linkedin_add_experience")

    page.goto("https://www.linkedin.com/in/me/add-edit/POSITION/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    rendered = False
    for make in [
        lambda: page.get_by_label("Job title", exact=False).first,
        lambda: page.get_by_placeholder("Example: Senior", exact=False).first,
    ]:
        try:
            make().wait_for(state="visible", timeout=15000)
            rendered = True
            break
        except Exception:
            continue
    _shot(page, "form")
    if not rendered:
        return {"success": False, "result": "add_position_form_not_rendered",
                "confirmed": False, "errors": ["form_not_rendered"]}

    errors = []
    # ── Step 1 — the basics (labels: "Job title", "Organization") ────────────
    if not _fill(page, ["Job title", "Title"], title, ["Example: Senior Product Manager"]):
        errors.append("title_not_filled")
    page.wait_for_timeout(400)

    if not _fill(page, ["Organization", "Company name", "Company"], company, ["Example: Microsoft"]):
        errors.append("company_not_filled")
    page.wait_for_timeout(1300)
    # Organization typeahead: link a matching real company page, else keep typed text.
    try:
        page.locator('[role="option"]').filter(has_text=company.split()[0]).first.click(timeout=2500)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
    page.wait_for_timeout(400)

    if current:
        _click_first(page, [
            lambda: page.get_by_label("currently work", exact=False).first.check(timeout=4000),
            lambda: page.locator('input[type="checkbox"]').first.check(timeout=4000),
        ])

    # Start date — select by the month NAME label (value-based select mis-picked).
    _select_label(page, "Start month", start_month)
    _select_label(page, "Start year", start_year)
    if not current and end_month and end_year:
        _select_label(page, "End month", end_month)
        _select_label(page, "End year", end_year)

    if location:
        if _fill(page, ["Location"], location, ["City or region"]):
            page.wait_for_timeout(700)
            try:
                page.locator('[role="option"]').first.click(timeout=2000)
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

    _shot(page, "step1")

    # Dismiss any lingering typeahead dropdown (org/location) so it can't intercept
    # the Next click — diag confirmed Next is ENABLED once the basics are filled.
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # ── Drive the wizard: Next → … → Save/Done. Description only via a clearly
    #    labeled field (no generic-textarea guessing -> no wrong-field writes).
    saved = False
    for _ in range(5):
        if description:
            try:
                page.get_by_label("Description", exact=False).first.fill(description, timeout=2500)
            except Exception:
                pass
        if _click_first(page, [
            lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=4000),
            lambda: page.get_by_role("button", name="Done", exact=True).last.click(timeout=3000),
        ]):
            saved = True
            break
        if not _click_first(page, [
            lambda: page.get_by_role("button", name="Next", exact=True).last.click(timeout=5000),
            lambda: page.get_by_text("Next", exact=True).last.click(timeout=3000),
        ]):
            break
        page.wait_for_timeout(1800)
    page.wait_for_timeout(2500)

    _click_first(page, [
        lambda: page.get_by_role("button", name="No thanks", exact=False).click(timeout=2500),
        lambda: page.keyboard.press("Escape"),
    ])

    # ── HONEST verification — the headline ALSO contains the company name, so a
    #    single hit is a false positive. Require the company key >=2x (header + entry).
    confirmed = False
    occurrences = 0
    try:
        page.goto("https://www.linkedin.com/in/me/details/experience/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        body = (page.evaluate("() => document.body.innerText || ''") or "").lower()
        key = company.split()[0].lower()
        occurrences = body.count(key)
        confirmed = occurrences >= 2 and title.split()[0].lower() in body
    except Exception:
        pass
    _shot(page, "verify")

    return {
        "success": bool(confirmed),
        "result": f"Added: {title} at {company}" if confirmed
        else f"NOT confirmed (company key x{occurrences}, save_clicked={saved})",
        "confirmed": confirmed,
        "save_clicked": saved,
        "errors": errors,
        "screenshot_dir": _SHOT_DIR,
    }
