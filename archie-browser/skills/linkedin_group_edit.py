"""LinkedIn group edit — update the group's description (and rules) as an admin.

#4603: Terry (377) owns the WTF group (37040054). Probe-verified 2026-07-02:
there is NO /groups/<id>/edit/ route (it bounces back to the group page) — the
"Edit group" affordance in the left admin sidebar opens a MODAL. This skill:
  goto group -> click "Edit group" -> modal -> fill description -> Save ->
  HONEST verify (re-open the modal and confirm the text committed).

Params:
  group_id     - defaults to env LINKEDIN_WTF_GROUP_ID
  description  - new group description text (optional)
  rules        - new group rules text (optional)
  probe_only   - dump the modal's fields + screenshot, change nothing

House rules: verify-before-success, honest failures, screenshots to the
mounted /profiles volume (host: /mnt/data2/browser-profiles/).
"""
import os
from datetime import datetime

SKILL_NAME = "linkedin_group_edit"
PLATFORMS = ["linkedin"]
MUTATING = True

_SHOT_DIR = "/profiles"


def _shot(page, name):
    path = f"{_SHOT_DIR}/_group_edit_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path if os.path.exists(path) else "shot_failed: file_not_written"
    except Exception as exc:
        return f"shot_failed: {type(exc).__name__}"


# Modal field dump — accessible-name walk (mirrors linkedin_profile_probe._JS_FORMS)
_JS_MODAL = r"""
() => {
  function accName(el){
    let n = el.getAttribute('aria-label'); if (n) return n.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb){ const t = lb.split(/\s+/).map(id => { const e = document.getElementById(id); return e ? (e.innerText || '') : ''; }).join(' ').trim(); if (t) return t; }
    let p = el.parentElement, tries = 0;
    while (p && tries < 5){ const lab = p.querySelector('label'); if (lab && (lab.innerText || '').trim()) return (lab.innerText || '').trim(); p = p.parentElement; tries++; }
    return '';
  }
  const dlg = document.querySelector('[role="dialog"], .artdeco-modal');
  if (!dlg) return { modal: false };
  const fields = Array.from(dlg.querySelectorAll('input, textarea, [contenteditable="true"]'))
    .filter(x => !['checkbox','radio','hidden'].includes(x.type))
    .map(x => ({ tag: x.tagName, type: (x.type || ''), acc: accName(x).slice(0, 50),
                 ph: (x.placeholder || '').slice(0, 50), val: ((x.value || x.innerText || '') + '').trim().slice(0, 60) }));
  const buttons = Array.from(dlg.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean);
  return { modal: true, title: (dlg.innerText || '').split('\n')[0].slice(0, 60),
           fields: fields.slice(0, 14), buttons: buttons.slice(0, 12) };
}
"""


def _open_edit_modal(page, group_id):
    page.goto(f"https://www.linkedin.com/groups/{group_id}/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    for make in [
        lambda: page.get_by_role("link", name="Edit group", exact=False).first.click(timeout=6000),
        lambda: page.get_by_role("button", name="Edit group", exact=False).first.click(timeout=5000),
        lambda: page.get_by_text("Edit group", exact=True).first.click(timeout=5000),
    ]:
        try:
            make()
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    return False


def _fill_labeled(page, dlg, label_token, value):
    """Fill the modal field whose accessible name/placeholder/nearby label
    contains label_token. Locator attempts first (pierce shadow DOM), then a
    positional textarea fallback."""
    for make in [
        lambda: dlg.get_by_label(label_token, exact=False).first,
        lambda: dlg.get_by_placeholder(label_token, exact=False).first,
        lambda: dlg.locator(f'textarea[name*="{label_token.lower()}"]').first,
    ]:
        try:
            f = make()
            f.click(timeout=3000)
            f.fill(value, timeout=5000)
            return True
        except Exception:
            continue
    return False


def execute(page, params: dict) -> dict:
    group_id = str(params.get("group_id") or os.getenv("LINKEDIN_WTF_GROUP_ID", "")).strip()
    if not group_id:
        raise ValueError("group_id is required (or set LINKEDIN_WTF_GROUP_ID)")
    description = (params.get("description") or "").strip()
    rules = (params.get("rules") or "").strip()
    probe_only = bool(params.get("probe_only"))
    if not probe_only and not (description or rules):
        raise ValueError("description or rules required (or probe_only)")

    if not _open_edit_modal(page, group_id):
        _shot(page, "no_modal")
        return {"success": False, "error": "edit_group_affordance_not_found", "group_id": group_id}

    try:
        dump = page.evaluate(_JS_MODAL)
    except Exception as exc:
        dump = {"modal": False, "dump_error": f"{type(exc).__name__}"}
    shot = _shot(page, "modal")

    if probe_only:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return {"success": True, "probe_only": True, "group_id": group_id, "modal": dump, "screenshot": shot}

    if not dump.get("modal"):
        return {"success": False, "error": "edit_modal_not_rendered", "group_id": group_id, "screenshot": shot}

    dlg = page.locator('[role="dialog"], .artdeco-modal').first
    updated, errors = [], []
    if description:
        updated.append("description") if _fill_labeled(page, dlg, "Description", description) \
            else errors.append("description_field_not_found")
    if rules:
        updated.append("rules") if _fill_labeled(page, dlg, "Rules", rules) \
            else errors.append("rules_field_not_found")

    saved = False
    if updated:
        for make in [
            lambda: dlg.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
            lambda: dlg.locator('button:has-text("Save")').last.click(timeout=5000),
        ]:
            try:
                make()
                saved = True
                page.wait_for_timeout(2500)
                break
            except Exception:
                continue
        if not saved:
            errors.append("save_not_clicked")

    # HONEST verify — re-open the modal, confirm the committed value renders.
    confirmed = False
    if saved and description:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        except Exception:
            pass
        if _open_edit_modal(page, group_id):
            try:
                redump = page.evaluate(_JS_MODAL)
                needle = description[:60].lower()
                confirmed = any(needle in (f.get("val") or "").lower() for f in redump.get("fields", []))
            except Exception:
                pass
    _shot(page, "verify")
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    ok = bool(updated) and saved and (confirmed or not description)
    return {
        "success": ok,
        "group_id": group_id,
        "updated": updated,
        "saved": saved,
        "confirmed": confirmed,
        "errors": errors,
        "screenshot": shot,
        "result": f"Updated {', '.join(updated)} (confirmed={confirmed})" if ok
        else f"NOT committed — errors: {errors or ['verify_failed']}",
    }
