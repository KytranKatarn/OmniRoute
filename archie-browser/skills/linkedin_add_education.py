"""LinkedIn add education — adds an education entry via the add-education ROUTE.

Live-probed 2026-06-30 (Terry/377): the old "Add profile section" button path is
DEAD. The working surface is the ROUTE https://www.linkedin.com/in/me/add-edit/EDUCATION/
(final URL /edit/forms/education/new) which renders: a School typeahead
(placeholder "Ex: Boston University"), ``Degree``, ``Field of study``, ``Grade``,
Activities, ``Description`` + Start/End year <select>s + a Save button.

Mirrors the proven add_experience rewrite: route + wait-for-Save + labelled fills +
pick the canonical school + HONEST verify (reload the education detail page and
confirm the school now appears). Year <select>s are chosen by LABEL, not value —
value-based select mis-picks (learned in add_experience). The old skill used the
dead button path, value-based year selects, and returned success unconditionally.
"""

SKILL_NAME = "linkedin_add_education"
PLATFORMS = ["linkedin"]
MUTATING = True

_SHOT_DIR = "/profiles"


def _shot(page, name):
    try:
        page.screenshot(path=f"{_SHOT_DIR}/_edu_{name}.png", full_page=False, timeout=15000, animations="disabled")
        return f"{_SHOT_DIR}/_edu_{name}.png"
    except Exception:
        return None


def _fill_label(page, label, value):
    try:
        page.get_by_label(label, exact=False).first.fill(value, timeout=5000)
        return True
    except Exception:
        return False


def _select_label(page, field_label, option_label):
    """Select an <option> by visible label (e.g. '2020'); value-based mis-picks."""
    for kw in ("label", "value"):
        try:
            page.get_by_label(field_label, exact=False).first.select_option(
                **{kw: str(option_label)}, timeout=4000
            )
            return True
        except Exception:
            continue
    return False


def execute(page, params: dict) -> dict:
    school = (params.get("school") or "").strip()
    degree = (params.get("degree") or "").strip()
    field = (params.get("field_of_study") or "").strip()
    start_year = str(params.get("start_year") or "").strip()
    end_year = str(params.get("end_year") or "").strip()
    grade = (params.get("grade") or "").strip()
    description = (params.get("description") or "").strip()
    dry_run = bool(params.get("dry_run", False))
    if not school:
        raise ValueError("school is required for linkedin_add_education")

    # ── Open the add-education form via its ROUTE + wait for render ───────────
    page.goto("https://www.linkedin.com/in/me/add-edit/EDUCATION/", wait_until="domcontentloaded")
    rendered = False
    for make in [
        lambda: page.get_by_placeholder("Boston University", exact=False).first,
        lambda: page.get_by_label("School", exact=False).first,
    ]:
        try:
            make().wait_for(state="visible", timeout=15000)
            rendered = True
            break
        except Exception:
            continue
    _shot(page, "form")
    if not rendered:
        return {"success": False, "result": "add_education_form_not_rendered", "errors": ["form_not_rendered"]}

    errors = []
    # ── School (typeahead → pick the canonical school) ────────────────────────
    school_filled = False
    for make in [
        lambda: page.get_by_placeholder("Boston University", exact=False).first,
        lambda: page.get_by_label("School", exact=False).first,
    ]:
        try:
            f = make()
            f.click(timeout=4000)
            f.fill(school, timeout=5000)
            school_filled = True
            break
        except Exception:
            continue
    if not school_filled:
        errors.append("school_not_filled")
    page.wait_for_timeout(1400)
    # SAFETY: only link a canonical school if an option matches the FULL typed
    # name (case-insensitive). Otherwise keep the typed free text — never grab a
    # wrong prestigious school on a partial match (cf. the "What The Factory" bug).
    linked_school = False
    for make in [
        lambda: page.get_by_role("option", name=school, exact=False).first,
        lambda: page.locator('[role="option"]').filter(has_text=school).first,
    ]:
        try:
            opt = make()
            opt.wait_for(state="visible", timeout=2500)
            opt.click(timeout=2500)
            linked_school = True
            break
        except Exception:
            continue
    if not linked_school:
        # Dismiss the typeahead by BLURRING (Tab), NOT Escape — Escape closes the
        # whole add-education modal, which killed Save (verified live 2026-06-30:
        # save_clicked=False, nothing saved). Tab keeps the typed free text.
        try:
            page.keyboard.press("Tab")
        except Exception:
            pass
    page.wait_for_timeout(500)

    if degree and not _fill_label(page, "Degree", degree):
        errors.append("degree_not_filled")
    if field and not _fill_label(page, "Field of study", field):
        errors.append("field_not_filled")
    if start_year and not _select_label(page, "Start year", start_year):
        errors.append("start_year_fail")
    if end_year and not _select_label(page, "End year", end_year):
        errors.append("end_year_fail")
    if grade and not _fill_label(page, "Grade", grade):
        errors.append("grade_not_filled")
    if description and not _fill_label(page, "Description", description):
        errors.append("description_not_filled")

    _shot(page, "filled")
    # NOTE: do NOT press Escape here — on the education route Escape closes the
    # whole modal, leaving no Save button (the save_clicked=False bug).

    # ── dry_run: confirm the form filled + Save is reachable, but do NOT save ──
    if dry_run:
        save_visible = False
        try:
            save_visible = page.get_by_role("button", name="Save", exact=True).last.is_visible(timeout=4000)
        except Exception:
            pass
        return {
            "success": bool(save_visible),
            "dry_run": True,
            "result": f"Form filled for '{school}'; Save reachable={save_visible} — NOT saved (dry_run).",
            "errors": errors,
            "screenshot_dir": _SHOT_DIR,
        }

    # ── Save ──────────────────────────────────────────────────────────────────
    saved = False
    for make in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
        lambda: page.locator('button[aria-label="Save"]').last.click(timeout=5000),
    ]:
        try:
            make()
            saved = True
            break
        except Exception:
            continue
    page.wait_for_timeout(2500)

    # ── HONEST verify — require Save actually fired, then reload + confirm the
    #    FULL school name. school.split()[0] alone false-positived on the existing
    #    "John F. Kennedy Business Centre" entry (matched "business"), 2026-06-30.
    confirmed = False
    if saved:
        try:
            page.goto("https://www.linkedin.com/in/me/details/education/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            body = (page.evaluate("() => document.body.innerText || ''") or "").lower()
            confirmed = school.lower() in body
        except Exception:
            pass
    _shot(page, "verify")

    return {
        "success": bool(confirmed),
        "result": f"Added education: {degree or 'degree'} at {school}" if confirmed
        else f"NOT confirmed (save_clicked={saved}) — school not found on the education page",
        "confirmed": confirmed,
        "save_clicked": saved,
        "errors": errors,
        "screenshot_dir": _SHOT_DIR,
    }
