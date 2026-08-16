"""LinkedIn company logo upload — sets the company page logo via the Edit Page modal.

Live-probed 2026-07-01 (KE/CREED, agent 342): the reliable path is the "Edit Page"
editor modal, which contains an ``input[aria-label="Upload logo"]`` file input right
there (the old click-the-logo-pencil selectors were stale). Open the editor, set the
file on that input, accept the crop, Save. Screenshots go to the MOUNTED /profiles
volume so a result shot is retrievable.
"""
import os
import sys

_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
# Guard the insert (#5650): skill_runner._discover_skills() re-imports EVERY skill on
# EVERY execute(), so an unguarded insert added a duplicate path per skill per run —
# measured sys.path 6 -> 33 after only 3 discoveries in a long-lived container.
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_DIR)
from _linkedin_common import get_company_slug

SKILL_NAME = "linkedin_company_logo"
PLATFORMS = ["linkedin"]
MUTATING = True


def _shot(page, name):
    # full_page=False is INTENTIONAL: full-page screenshots TIME OUT on LinkedIn's
    # animated editor (established pattern across the linkedin_* skills). Viewport
    # shots go to the MOUNTED /profiles volume so a result shot is retrievable.
    path = f"/profiles/_clogo_{name}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path
    except Exception:
        return None


def execute(page, params: dict) -> dict:
    company_slug = get_company_slug(params)
    logo_path = (params.get("logo_path") or "").strip()
    if not logo_path:
        raise ValueError("logo_path is required for linkedin_company_logo")
    if not os.path.exists(logo_path):
        raise ValueError(f"logo_path not found: {logo_path}")

    company_url = f"https://www.linkedin.com/company/{company_slug}/"
    page.goto(company_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    try:
        page.keyboard.press("Escape")  # dismiss the Premium upsell overlay
        page.wait_for_timeout(500)
    except Exception:
        pass

    # ── Open the Edit Page editor (proven reliable in company_edit) ───────────
    opened = False
    for btn in [
        lambda: page.get_by_role("link", name="Edit Page", exact=True).click(timeout=8000),
        lambda: page.locator('a:has-text("Edit Page")').first.click(timeout=8000),
        lambda: page.get_by_role("link", name="Edit page", exact=False).first.click(timeout=6000),
    ]:
        try:
            btn()
            opened = True
            break
        except Exception:
            continue
    if not opened:
        _shot(page, "edit_btn_fail")
        return {"success": False, "result": "edit_page_not_opened", "error": "edit_page_not_opened"}
    page.wait_for_timeout(2500)
    _shot(page, "editor_open")

    # ── Set the file on the "Upload logo" input (present in the editor modal) ──
    file_set = False
    for sel in [
        'input[aria-label="Upload logo"]',
        'input[aria-label*="logo" i][type="file"]',
        'input[type="file"]',
    ]:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=6000)
            loc.set_input_files(logo_path, timeout=6000)
            file_set = True
            break
        except Exception:
            continue
    if not file_set:
        _shot(page, "input_fail")
        return {"success": False, "result": "logo_input_not_found", "error": "logo_input_not_found"}
    page.wait_for_timeout(3000)
    _shot(page, "crop")

    # ── Accept the crop/preview modal ─────────────────────────────────────────
    for a in [
        lambda: page.get_by_role("button", name="Apply", exact=True).last.click(timeout=6000),
        lambda: page.get_by_role("button", name="Save changes", exact=True).last.click(timeout=5000),
        lambda: page.get_by_role("button", name="Save photo", exact=False).last.click(timeout=5000),
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=5000),
    ]:
        try:
            a()
            page.wait_for_timeout(1800)
            break
        except Exception:
            continue

    # ── Save the page (editor Save) ───────────────────────────────────────────
    for a in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
        lambda: page.locator('button[type="submit"]').last.click(timeout=5000),
    ]:
        try:
            a()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    page.wait_for_timeout(1500)

    final = _shot(page, "final")
    return {
        "success": bool(file_set),
        "result": "Company logo uploaded (verify via screenshot)" if file_set else "logo not set",
        "file_set": file_set,
        "logo_path": logo_path,
        "screenshot_path": final,
    }
