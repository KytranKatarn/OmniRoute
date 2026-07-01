"""LinkedIn conversation delete — delete a messaging thread by participant name.

Uses the "Manage conversations" bulk-select UI (See more messaging options →
Manage conversations) which exposes PERSISTENT checkboxes + a bulk Delete button —
the per-conversation/per-message hover overflow menus do NOT reliably interact under
headless Playwright (KB — 8 click techniques failed). Selects ONLY the conversation
whose card matches `name`, deletes it, confirms, and verifies it's gone from the
inbox before claiming success (mirrors #4327 / #1805 honesty).

DESTRUCTIVE + IRREVERSIBLE — so it carries the same anti-"bulk / wrong delete"
guards as linkedin_delete (#4611 part 2):
  * ``name`` must be ONE string (a list/tuple/set is rejected) and >= 2 chars —
    a 1-char / empty name would substring-match half the inbox.
  * AMBIGUITY GUARD: ``name`` is a substring match over conversation cards; if it
    matches MORE THAN ONE visible thread the skill REFUSES (returns
    ``ambiguous_match`` with the count) unless ``allow_multiple=True`` is passed
    explicitly. This is the core "can't wrong-delete" protection.
  * ``dry_run`` (default False) — enter Manage mode + tick the target checkbox but
    DO NOT click Delete; report the single thread that *would* be deleted.
There is intentionally NO "delete all" path — exactly one named thread per call.
NOTE: the inbox is virtualized, so the ambiguity count only sees currently-rendered
cards; it can't guarantee global uniqueness, but it stops any obvious multi-match.
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


def _match_count(page, name):
    """How many currently-rendered conversation cards contain `name`?"""
    try:
        return (
            page.locator('li.msg-conversation-listitem, .msg-conversation-card')
            .filter(has_text=name)
            .count()
        )
    except Exception:
        return 0


def execute(page, params: dict) -> dict:
    # ── Guard 1: exactly one name, as a non-trivial string (NO bulk delete) ───
    raw_name = params.get("name")
    if isinstance(raw_name, (list, tuple, set)):
        raise ValueError(
            "linkedin_conversation_delete deletes ONE thread at a time — pass a "
            "single participant name string, not a collection."
        )
    name = (raw_name or "").strip()
    if not name:
        raise ValueError("name (conversation participant) is required for linkedin_conversation_delete")
    if len(name) < 2:
        raise ValueError(
            f"name {name!r} is too short (>=2 chars required) — a 1-char name would "
            "substring-match many conversations. Refusing."
        )

    dry_run = bool(params.get("dry_run", False))
    allow_multiple = bool(params.get("allow_multiple", False))

    page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)

    matches = _match_count(page, name)
    if matches == 0:
        return {"success": True, "already_gone": True,
                "result": f"No conversation with '{name}' found (nothing to delete)"}

    # ── Guard 2: AMBIGUITY — refuse a multi-match unless explicitly overridden ─
    if matches > 1 and not allow_multiple:
        _screenshot(page, "convdel_ambiguous")
        return {
            "success": False,
            "error": "ambiguous_match",
            "match_count": matches,
            "result": (
                f"Refusing to delete: '{name}' matches {matches} conversations. "
                "Pass a more specific name, or allow_multiple=True to delete the first."
            ),
        }

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

    # ── dry_run: the target thread is selected — stop here, do NOT delete ─────
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "match_count": matches,
            "result": f"Selected the '{name}' conversation for deletion — NOT deleted (dry_run).",
            "screenshot_path": _screenshot(page, "convdel_dryrun"),
        }

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
