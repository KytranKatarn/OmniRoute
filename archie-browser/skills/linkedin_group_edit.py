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
  function ctx(el){
    // nearest ancestor text that names an unlabeled control (file inputs)
    let p = el.parentElement, tries = 0;
    while (p && tries < 6){
      const t = (p.innerText || '').replace(/\s+/g,' ').trim();
      if (t && t.length > 2 && t.length < 120) return t.slice(0, 60);
      p = p.parentElement; tries++;
    }
    return '';
  }
  function geom(el){
    // hidden file inputs have no box — walk up to the first ancestor with one;
    // a WIDE box = the cover/hero uploader, a ~square box = the logo tile.
    let p = el, tries = 0;
    while (p && tries < 6){
      const r = p.getBoundingClientRect();
      if (r.width > 8 && r.height > 8) return { w: Math.round(r.width), h: Math.round(r.height) };
      p = p.parentElement; tries++;
    }
    return { w: 0, h: 0 };
  }
  const fields = Array.from(dlg.querySelectorAll('input, textarea, [contenteditable="true"]'))
    .filter(x => !['checkbox','radio','hidden'].includes(x.type))
    .map(x => ({ tag: x.tagName, type: (x.type || ''), acc: accName(x).slice(0, 50),
                 ph: (x.placeholder || '').slice(0, 50), val: ((x.value || x.innerText || '') + '').trim().slice(0, 60),
                 ctx: (x.type === 'file' ? ctx(x) : ''),
                 box: (x.type === 'file' ? geom(x) : null) }));
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
    if not probe_only and not (
        description or rules or params.get("logo_path") or params.get("banner_path")
        or params.get("probe_upload")
    ):
        raise ValueError("description, rules, logo_path, banner_path or probe_upload required (or probe_only)")

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

    # ── probe_upload: set ONE file on ONE input, dump the resulting dialog
    # state (crop/confirm UI), screenshot, then ABANDON (Escape x2 — nothing
    # committed). Diagnoses the replace flow without touching live state.
    probe_upload = (params.get("probe_upload") or "").strip().lower()  # 'cover' | 'logo'
    if probe_upload:
        path = (params.get("path") or "").strip()
        if probe_upload not in ("cover", "logo") or not path:
            return {"success": False, "error": "probe_upload needs 'cover'|'logo' + path"}
        dlg0 = page.locator('[role="dialog"], .artdeco-modal').first
        idx = 0 if probe_upload == "cover" else 1
        try:
            dlg0.locator('input[type="file"]').nth(idx).set_input_files(path)
        except Exception as exc:
            return {"success": False, "error": f"set_input_files failed: {type(exc).__name__}"}
        page.wait_for_timeout(3500)
        state = page.evaluate(r"""
        () => {
          const dlgs = Array.from(document.querySelectorAll('[role="dialog"], .artdeco-modal'));
          return {
            dialog_count: dlgs.length,
            dialogs: dlgs.map(d => ({
              heading: (d.innerText || '').split('\n').filter(Boolean)[0] || '',
              buttons: Array.from(d.querySelectorAll('button')).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 30),
              file_inputs: d.querySelectorAll('input[type="file"]').length,
              imgs: d.querySelectorAll('img').length,
            })),
          };
        }
        """)
        upshot = _shot(page, f"probe_upload_{probe_upload}")
        for _ in range(2):
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(700)
            except Exception:
                pass
        return {"success": True, "probe_upload": probe_upload, "index_used": idx,
                "state": state, "screenshot": upshot}

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

    # ── IMAGES — the modal has 2 UNLABELED file inputs (logo + cover); pick by
    # the nearest ancestor text captured in the dump ('logo' vs 'cover'/'banner'/
    # 'hero'); fall back to document order logo-first only if context is silent.
    logo_path = (params.get("logo_path") or "").strip()
    banner_path = (params.get("banner_path") or "").strip()
    if logo_path or banner_path:
        file_fields = [f for f in dump.get("fields", []) if f.get("type") == "file"]

        def _pick_indices():
            """ctx regex first; else DOM ORDER: input 0 = COVER, input 1 = LOGO.
            LIVE-PROVEN 2026-07-02: both inputs are context-silent and the
            ancestor-geometry heuristic picked INVERTED (logo landed on the
            cover, banner on the logo tile) — the modal's DOM order matches the
            visual layout, cover uploader first."""
            import re as _re
            logo_i = banner_i = None
            for i, f in enumerate(file_fields):
                c = f.get("ctx") or ""
                if logo_i is None and _re.search(r"logo", c, _re.I):
                    logo_i = i
                if banner_i is None and _re.search(r"cover|banner|hero|background", c, _re.I):
                    banner_i = i
            if len(file_fields) >= 2:
                if banner_i is None:
                    banner_i = 0
                if logo_i is None:
                    logo_i = 1 if banner_i == 0 else 0
            elif len(file_fields) == 1 and logo_i is None and banner_i is None:
                logo_i = 0
            return logo_i, banner_i

        def _upload(idx, path, label):
            """Probe-mapped replace flow (2026-07-02): setting a file flips the
            modal into a full IMAGE EDITOR ('Edit cover photo' / logo — Crop/
            Filters/Adjust) whose confirm is the LAST 'Apply' button. The old
            fixed-sleep + blind-click version raced the editor render and
            silently abandoned the edit. Explicit state-waits per step."""
            if idx is None or not os.path.exists(path):
                errors.append(f"{label}_input_or_file_missing")
                return False
            try:
                dlg.locator('input[type="file"]').nth(idx).set_input_files(path)
            except Exception as exc:
                errors.append(f"{label}_set_files_failed: {type(exc).__name__}")
                return False
            try:
                apply_btn = page.get_by_role("button", name="Apply", exact=True).last
                apply_btn.wait_for(state="visible", timeout=12000)
                apply_btn.click(timeout=6000)
            except Exception as exc:
                errors.append(f"{label}_apply_not_clicked: {type(exc).__name__}")
                _shot(page, f"{label}_editor_stuck")
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(700)
                except Exception:
                    pass
                return False
            # wait for the editor to hand back to the edit modal before the
            # next image touches the (re-queried) file inputs
            try:
                page.get_by_role("button", name="Apply", exact=True).last.wait_for(state="hidden", timeout=8000)
            except Exception:
                page.wait_for_timeout(1500)
            page.wait_for_timeout(800)
            updated.append(label)
            return True

        logo_idx, banner_idx = _pick_indices()
        if logo_path:
            _upload(logo_idx, logo_path, "logo")
        if banner_path:
            _upload(banner_idx, banner_path, "banner")
        _shot(page, "images")

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
