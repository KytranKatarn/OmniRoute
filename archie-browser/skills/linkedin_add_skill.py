"""LinkedIn add skill — adds a single skill via the add-skill ROUTE.

Live-verified 2026-06-30 (Terry/377): the old "Add profile section" button path is
DEAD (probe + live run both failed "Could not find Add profile section button").
The working surface is the ROUTE https://www.linkedin.com/in/me/add-edit/SKILL_AND_ASSOCIATION/
which renders a form with a single ``Skill*`` typeahead input + a Save button
(final URL /skills/edit/forms/new). Mirrors the proven add_experience rewrite:
route + wait-for-Save + fill + pick the canonical suggestion + Save + HONEST verify
(reload the skills detail page and confirm the skill now appears — the old skill
returned success unconditionally, a phantom-success).
"""

SKILL_NAME = "linkedin_add_skill"
PLATFORMS = ["linkedin"]
MUTATING = True

_SHOT_DIR = "/profiles"


def _shot(page, name):
    try:
        page.screenshot(path=f"{_SHOT_DIR}/_skill_{name}.png", full_page=False, timeout=15000, animations="disabled")
        return f"{_SHOT_DIR}/_skill_{name}.png"
    except Exception:
        return None


def _skill_listed(page, skill):
    """HONEST verify on /in/me/details/skills/. The old check grepped
    document.body.innerText — that (a) does not cross shadow roots and (b) misses
    anything the virtualized/paginated list hasn't rendered, so it reported
    confirmed=False for skills that WERE added (cont-112 false-negative).
    Playwright locators pierce shadow DOM (KB #277237); scrolling + 'Show more
    results' defeats the pagination."""
    page.goto("https://www.linkedin.com/in/me/details/skills/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    for _ in range(8):
        try:
            if page.get_by_text(skill, exact=False).first.is_visible(timeout=1500):
                return True
        except Exception:
            pass
        try:
            page.get_by_role("button", name="Show more results", exact=False).first.click(timeout=1200)
        except Exception:
            try:
                page.mouse.wheel(0, 2500)
            except Exception:
                return False
        page.wait_for_timeout(900)
    return False


def execute(page, params: dict) -> dict:
    skill = (params.get("skill") or "").strip()
    if not skill:
        raise ValueError("skill is required for linkedin_add_skill")

    # ── verify_only: READ-ONLY presence check (no form, nothing added) ────────
    if params.get("verify_only"):
        listed = _skill_listed(page, skill)
        _shot(page, "verify")
        return {
            "success": True,
            "verify_only": True,
            "confirmed": listed,
            "skill": skill,
            "result": f"'{skill}' {'IS' if listed else 'is NOT'} listed on the skills page",
        }

    # ── Open the add-skill form via its ROUTE + wait for it to render ─────────
    page.goto("https://www.linkedin.com/in/me/add-edit/SKILL_AND_ASSOCIATION/", wait_until="domcontentloaded")
    rendered = False
    for make in [
        lambda: page.get_by_label("Skill", exact=False).first,
        lambda: page.get_by_placeholder("Skill", exact=False).first,
    ]:
        try:
            make().wait_for(state="visible", timeout=15000)
            rendered = True
            break
        except Exception:
            continue
    _shot(page, "form")
    if not rendered:
        return {"success": False, "result": "add_skill_form_not_rendered", "errors": ["form_not_rendered"]}

    # ── Fill the Skill typeahead ──────────────────────────────────────────────
    filled = False
    for make in [
        lambda: page.get_by_label("Skill", exact=False).first,
        lambda: page.get_by_placeholder("Skill", exact=False).first,
    ]:
        try:
            f = make()
            f.click(timeout=4000)
            f.fill(skill, timeout=5000)
            filled = True
            break
        except Exception:
            continue
    if not filled:
        _shot(page, "field_fail")
        return {"success": False, "result": "skill_field_not_found", "errors": ["field_not_found"]}
    # The Skill* search runs SERVER-SIDE — wait for the dropdown, then SELECT the
    # match so it becomes a removable PILL. Typing alone does NOT add the skill;
    # Save with no pill selected is a silent no-op (verified live 2026-06-30).
    page.wait_for_timeout(2200)
    _shot(page, "typeahead")
    picked = False
    for make in [
        lambda: page.get_by_role("option", name=skill, exact=False).first,
        lambda: page.locator('[role="listbox"] [role="option"]').filter(has_text=skill.split()[0]).first,
        lambda: page.locator('.basic-typeahead__selectable').filter(has_text=skill.split()[0]).first,
        lambda: page.locator('[role="option"]').first,
        lambda: page.locator('.basic-typeahead__selectable').first,
    ]:
        try:
            opt = make()
            opt.wait_for(state="visible", timeout=3000)
            opt.click(timeout=3000)
            picked = True
            break
        except Exception:
            continue
    page.wait_for_timeout(1000)
    _shot(page, "after_pick")
    # Belt-and-suspenders: a selected skill shows as a pill inside the dialog. If
    # nothing was picked, Save would be a no-op — surface that instead of a phantom.
    pill_seen = False
    try:
        pill_seen = (
            page.locator('[role="dialog"], .artdeco-modal')
            .get_by_text(skill, exact=False)
            .count()
            > 0
        )
    except Exception:
        pass

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
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    # ── HONEST verify — locator-based, shadow-safe, pagination-aware ──────────
    confirmed = False
    try:
        confirmed = _skill_listed(page, skill)
    except Exception:
        pass
    _shot(page, "verify")

    return {
        "success": bool(confirmed),
        "result": f"Added skill: {skill}" if confirmed
        else f"NOT confirmed (save_clicked={saved}) — skill not found on the skills page",
        "confirmed": confirmed,
        "save_clicked": saved,
        "picked": picked,
        "pill_seen": pill_seen,
        "skill": skill,
        "screenshot_dir": _SHOT_DIR,
    }
