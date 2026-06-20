"""LinkedIn conversation delete — delete a messaging thread by participant name.

Uses the "Manage conversations" bulk-select UI (See more messaging options →
Manage conversations) which exposes PERSISTENT checkboxes + a bulk Delete button —
the per-conversation/per-message hover overflow menus do NOT reliably interact under
headless Playwright (KB — 8 click techniques failed). Selects ONLY the conversation
whose card matches `name`, deletes it, confirms, and verifies it's gone from the
inbox before claiming success (mirrors #4327 / #1805 honesty). DESTRUCTIVE — scoped
to a single named thread.
"""
import os
from datetime import datetime

SKILL_NAME = "linkedin_conversation_delete"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _in_inbox(page, name):
    """Is a conversation with `name` currently listed?"""
    try:
        return (
            page.locator('li.msg-conversation-listitem, .msg-conversation-card')
            .filter(has_text=name)
            .count()
            > 0
        )
    except Exception:
        return False


def execute(page, params: dict) -> dict:
    name = (params.get("name") or "").strip()
    if not name:
        raise ValueError("name (conversation participant) is required for linkedin_conversation_delete")

    page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)

    if not _in_inbox(page, name):
        return {"success": True, "already_gone": True,
                "result": f"No conversation with '{name}' found (nothing to delete)"}

    # Enter "Manage conversations" bulk-select mode (persistent checkboxes).
    try:
        page.locator('button[aria-label="See more messaging options"]').first.click(timeout=5000)
        page.wait_for_timeout(1000)
    except Exception:
        return {"success": False, "error": "options_menu_fail",
                "result": "Could not open the messaging options menu"}
    opened = False
    for a in [
        lambda: page.get_by_text("Manage conversations", exact=True).first.click(timeout=4000),
        lambda: page.get_by_role("menuitem", name="Manage conversations").first.click(timeout=4000),
    ]:
        try:
            a()
            opened = True
            break
        except Exception:
            continue
    if not opened:
        return {"success": False, "error": "manage_mode_fail",
                "result": "Could not enter Manage conversations mode"}
    page.wait_for_timeout(2500)

    # Check ONLY the target conversation's checkbox.
    li = page.locator('li.msg-conversation-listitem, .msg-conversation-card').filter(has_text=name).first
    try:
        li.scroll_into_view_if_needed(timeout=4000)
        page.wait_for_timeout(400)
    except Exception:
        pass
    checked = False
    for a in [
        lambda: li.locator('input[type="checkbox"]').first.click(timeout=4000, force=True),
        lambda: li.locator('input[type="checkbox"]').first.evaluate("e => e.click()"),
        lambda: li.click(timeout=3000),
    ]:
        try:
            a()
            checked = True
            break
        except Exception:
            continue
    if not checked:
        _screenshot(page, "convdel_check_fail")
        return {"success": False, "error": "checkbox_fail",
                "result": f"Found the '{name}' conversation but could not select its checkbox"}
    page.wait_for_timeout(800)

    # Bulk Delete.
    deleted_click = False
    for a in [
        lambda: page.get_by_role("button", name="Delete", exact=True).first.click(timeout=5000),
        lambda: page.locator('button:has-text("Delete")').first.click(timeout=4000),
    ]:
        try:
            a()
            deleted_click = True
            break
        except Exception:
            continue
    if not deleted_click:
        return {"success": False, "error": "delete_btn_fail",
                "result": "Selected the conversation but could not click Delete"}
    page.wait_for_timeout(1200)

    # Confirm dialog — scope to the modal so we hit the dialog's Delete (not the
    # action-bar's). Dialog buttons are [Dismiss, Cancel, Delete].
    dlg = page.locator('[role="dialog"], .artdeco-modal')
    for a in [
        lambda: dlg.get_by_role("button", name="Delete", exact=True).first.click(timeout=4000),
        lambda: dlg.locator('button:has-text("Delete")').last.click(timeout=3000),
    ]:
        try:
            a()
            break
        except Exception:
            continue
    page.wait_for_timeout(2500)

    # Verify it's gone (reload the inbox; honest success).
    page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    gone = not _in_inbox(page, name)

    return {
        "success": gone,
        "confirmed": gone,
        "result": (
            f"Deleted the conversation with {name}"
            if gone
            else f"Clicked Delete but the conversation with {name} is still listed"
        ),
        "error": None if gone else "delete_not_confirmed",
        "screenshot_path": _screenshot(page, "convdel_done"),
    }
