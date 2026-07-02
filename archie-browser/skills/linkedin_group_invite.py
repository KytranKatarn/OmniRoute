"""LinkedIn group invite — invite a 1st-degree connection to a group (admin).

#4603: Terry (377) owns the WTF group (37040054); "Invite connections" is a
button on the group page (probe-verified 2026-07-02). Flow:
  goto group -> click "Invite connections" -> modal -> search the connection
  by name -> select their row -> Invite -> HONEST verify (the row flips to an
  invited/pending state or disappears from the invitable list).

Params:
  group_id         - defaults to env LINKEDIN_WTF_GROUP_ID
  connection_name  - required, e.g. "Kytran Katarn" (must be a 1st-degree
                     connection of the acting profile)
  probe_only       - dump the modal + screenshot, invite nothing

Safety: single-target only — exactly one name per run, the row clicked must
contain the requested name (no bulk, no fuzzy first-row grabs).
"""
import os
from datetime import datetime

SKILL_NAME = "linkedin_group_invite"
PLATFORMS = ["linkedin"]
MUTATING = True

_SHOT_DIR = "/profiles"


def _shot(page, name):
    path = f"{_SHOT_DIR}/_group_invite_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path if os.path.exists(path) else "shot_failed: file_not_written"
    except Exception as exc:
        return f"shot_failed: {type(exc).__name__}"


_JS_MODAL = r"""
() => {
  const dlg = document.querySelector('[role="dialog"], .artdeco-modal');
  if (!dlg) return { modal: false };
  const inputs = Array.from(dlg.querySelectorAll('input'))
    .filter(x => !['checkbox','radio','hidden'].includes(x.type))
    .map(x => ({ type: x.type || '', aria: (x.getAttribute('aria-label') || '').slice(0, 50),
                 ph: (x.placeholder || '').slice(0, 50) }));
  const buttons = Array.from(dlg.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean);
  const text = (dlg.innerText || '').replace(/\s+/g, ' ').slice(0, 400);
  return { modal: true, inputs: inputs.slice(0, 8), buttons: buttons.slice(0, 14), text };
}
"""


def execute(page, params: dict) -> dict:
    group_id = str(params.get("group_id") or os.getenv("LINKEDIN_WTF_GROUP_ID", "")).strip()
    if not group_id:
        raise ValueError("group_id is required (or set LINKEDIN_WTF_GROUP_ID)")
    name = (params.get("connection_name") or "").strip()
    probe_only = bool(params.get("probe_only"))
    if not name and not probe_only:
        raise ValueError("connection_name is required for linkedin_group_invite")

    page.goto(f"https://www.linkedin.com/groups/{group_id}/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)

    opened = False
    for make in [
        lambda: page.get_by_role("button", name="Invite connections", exact=False).first.click(timeout=6000),
        lambda: page.get_by_text("Invite connections", exact=True).first.click(timeout=5000),
    ]:
        try:
            make()
            opened = True
            page.wait_for_timeout(2500)
            break
        except Exception:
            continue
    if not opened:
        _shot(page, "no_button")
        return {"success": False, "error": "invite_connections_button_not_found", "group_id": group_id}

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
        return {"success": False, "error": "invite_modal_not_rendered", "group_id": group_id, "screenshot": shot}

    dlg = page.locator('[role="dialog"], .artdeco-modal').first

    # Search the connection by name (narrows the list; also loads non-rendered rows)
    for make in [
        lambda: dlg.get_by_placeholder("Search", exact=False).first,
        lambda: dlg.get_by_role("textbox").first,
    ]:
        try:
            f = make()
            f.click(timeout=3000)
            f.fill(name, timeout=4000)
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    # Select the row CONTAINING the requested name — single-target guard.
    row_clicked = False
    for make in [
        lambda: dlg.locator("li").filter(has_text=name).first.locator('input[type="checkbox"]').first.check(timeout=4000, force=True),
        lambda: dlg.locator("li").filter(has_text=name).first.click(timeout=4000),
        lambda: dlg.get_by_text(name, exact=False).first.click(timeout=4000),
    ]:
        try:
            make()
            row_clicked = True
            page.wait_for_timeout(800)
            break
        except Exception:
            continue
    if not row_clicked:
        _shot(page, "row_not_found")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return {"success": False, "error": f"connection_row_not_found: {name}", "group_id": group_id,
                "modal": dump, "screenshot": shot}

    # Send the invite
    sent = False
    for make in [
        lambda: dlg.get_by_role("button", name="Invite", exact=True).last.click(timeout=5000),
        lambda: dlg.locator('button:has-text("Invite")').last.click(timeout=4000),
    ]:
        try:
            make()
            sent = True
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    # HONEST verify — the modal closes on success, or the row shows Invited/Pending.
    confirmed = False
    if sent:
        try:
            confirmed = page.locator('[role="dialog"], .artdeco-modal').count() == 0
        except Exception:
            pass
        if not confirmed:
            try:
                confirmed = dlg.get_by_text("Invited", exact=False).first.is_visible(timeout=2000) or \
                    dlg.get_by_text("Pending", exact=False).first.is_visible(timeout=1000)
            except Exception:
                pass
    final_shot = _shot(page, "after")
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    ok = row_clicked and sent and confirmed
    return {
        "success": ok,
        "group_id": group_id,
        "connection_name": name,
        "invite_clicked": sent,
        "confirmed": confirmed,
        "screenshot": final_shot,
        "result": f"Invited {name}" if ok
        else f"NOT confirmed (row={row_clicked}, invite_clicked={sent}, confirmed={confirmed})",
    }
