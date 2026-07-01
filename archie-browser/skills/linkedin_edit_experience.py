"""LinkedIn edit experience — edits an EXISTING position via its direct edit-form URL.

Verified live Terry/377 2026-06-30 (headed). CURRENT / present experience entries do
NOT expose a clickable edit pencil to automation (they render lazily / in shadow DOM,
so Playwright clicks time out and the anchors don't appear in naive DOM dumps). BUT
every entry's edit form has a STABLE URL: /in/me/details/experience/edit/forms/<id>/.

This skill shadow-walks the experience list to find that URL by matching the entry's
visible company/title text, navigates DIRECTLY to it, GUARDS on the Organization field
(so it can only edit the intended entry), then updates Job title / Organization /
Description / end-date, and Saves. No pencil click involved.

Params:
  match_company (required): text identifying the entry, matched against its visible
      text (e.g. "C.R.E.E.D.", "What The Factory", "Public Services").
  new_title (opt): replace the Job title (e.g. "Co-Founder").
  new_company (opt): replace the Organization — typed as FREE TEXT, no typeahead pick
      (avoids the add-flow's wrong-company match).
  new_description (opt): replace the Description.
  set_end_month / set_end_year (opt): end the role — unchecks "I currently work here"
      and sets the end date (e.g. "January" / "2026").

Returns {success, result, edit_url, applied, errors}. success=True only when the entry
was found + guard-matched, at least one field applied, and Save clicked.
"""

SKILL_NAME = "linkedin_edit_experience"
PLATFORMS = ["linkedin"]
MUTATING = True

_FINDER = r"""
(match) => {
  function* walk(root){ for (const el of root.querySelectorAll('*')) { yield el; if (el.shadowRoot) yield* walk(el.shadowRoot); } }
  for (const el of walk(document)) {
    if (el.tagName !== 'A') continue;
    const h = el.getAttribute('href') || '';
    if (!/details\/experience\/edit\/forms\/\d+/.test(h)) continue;
    const li = el.closest('li');
    const t = (li ? li.innerText : el.innerText) || '';
    if (t.toLowerCase().includes(match.toLowerCase())) return h;
  }
  return null;
}
"""


def _norm(s):
    return (s or "").lower().replace(".", "").replace(" ", "")


def execute(page, params: dict) -> dict:
    match = (params.get("match_company") or "").strip()
    if not match:
        raise ValueError("match_company is required for linkedin_edit_experience")
    new_title = (params.get("new_title") or "").strip()
    new_company = (params.get("new_company") or "").strip()
    new_desc = (params.get("new_description") or "").strip()
    end_month = (params.get("set_end_month") or "").strip()
    end_year = str(params.get("set_end_year") or "").strip()

    errors = []

    # 1. Find the entry's edit-form URL (shadow-walk; retry with scroll for lazy render).
    page.goto("https://www.linkedin.com/in/me/details/experience/", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    url = None
    for _ in range(3):
        try:
            url = page.evaluate(_FINDER, match)
        except Exception:
            url = None
        if url:
            break
        page.evaluate("() => window.scrollBy(0, 800)")
        page.wait_for_timeout(1500)
    if not url:
        return {"success": False, "result": "entry_not_found", "errors": ["entry_not_found:" + match]}

    # 2. Navigate directly to the edit form + wait for it to render.
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.get_by_role("button", name="Save", exact=True).first.wait_for(state="visible", timeout=15000)
    except Exception:
        page.wait_for_timeout(4000)
    page.wait_for_timeout(800)

    # 3. GUARD — confirm the open form is the intended entry (never edit the wrong one).
    org = ""
    try:
        org = page.get_by_label("Organization", exact=False).first.input_value(timeout=4000)
    except Exception:
        pass
    if _norm(match) not in _norm(org):
        return {"success": False, "result": "guard_mismatch", "edit_url": url, "errors": ["guard org=" + org]}

    applied = []

    # 4. Apply edits.
    if new_title:
        try:
            jt = page.get_by_label("Job title", exact=False).first
            jt.click()
            jt.press("Control+a")
            jt.press("Delete")
            jt.type(new_title, delay=25)
            applied.append("title")
        except Exception:
            errors.append("title_fail")

    if new_company:
        try:
            oc = page.get_by_label("Organization", exact=False).first
            oc.click()
            oc.press("Control+a")
            oc.press("Delete")
            oc.type(new_company, delay=35)
            page.wait_for_timeout(1400)
            page.keyboard.press("Escape")  # keep free-text; do NOT pick a typeahead option
            applied.append("company")
        except Exception:
            errors.append("company_fail")

    if new_desc:
        try:
            d = page.get_by_label("Description", exact=False).first
            d.click()
            d.press("Control+a")
            d.press("Delete")
            d.fill(new_desc)
            applied.append("description")
        except Exception:
            errors.append("description_fail")

    if end_month and end_year:
        try:
            page.get_by_label("currently", exact=False).first.uncheck(timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        ok = False
        try:
            page.get_by_label("End month", exact=False).first.select_option(label=end_month, timeout=4000)
            ok = True
        except Exception:
            errors.append("end_month_fail")
        try:
            page.get_by_label("End year", exact=False).first.select_option(label=end_year, timeout=4000)
        except Exception:
            errors.append("end_year_fail")
        if ok:
            applied.append("end_date")

    if not applied:
        return {"success": False, "result": "nothing_applied", "edit_url": url, "errors": errors}

    # 5. Save.
    page.wait_for_timeout(400)
    saved = False
    for nm in ["Save", "Done"]:
        try:
            page.get_by_role("button", name=nm, exact=True).last.click(timeout=6000)
            saved = True
            break
        except Exception:
            continue
    page.wait_for_timeout(3000)

    return {
        "success": bool(saved and applied),
        "result": f"Edited '{match}': {', '.join(applied)}" if saved else "save_failed",
        "edit_url": url,
        "applied": applied,
        "errors": errors,
    }
