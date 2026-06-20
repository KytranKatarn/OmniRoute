"""LinkedIn message skill — send a direct message to a connection."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_message"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def execute(page, params: dict) -> dict:
    profile_url = params.get("profile_url", "").strip()
    message = params.get("message", "").strip()
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_message")
    if not message:
        raise ValueError("message is required for linkedin_message")

    clean_url = profile_url.split("?")[0].rstrip("/")
    page.goto(clean_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_message_{ts}.png"
    try:
        page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
    except Exception:
        pass
    main = page.locator("main")
    # A real direct-Message affordance only exists for messageable members (1st-degree
    # connections, or open-profile/InMail). Scope to the profile top-card and be STRICT:
    # the button's aria-label is "Message <Name>". Do NOT match "Send profile in a
    # message", the nav messaging icon, or anything that opens the New-Message compose —
    # its recipient typeahead intercepts clicks and HANGS the skill (the bug being fixed).
    clicked = False
    for attempt in [
        lambda: main.locator('button[aria-label^="Message"]').first.click(timeout=5000),
        lambda: main.get_by_role("button", name="Message", exact=True).first.click(timeout=4000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        # No direct Message button on the profile → not a 1st-degree connection (or
        # messaging unavailable). Return cleanly instead of falling into a compose hang.
        return {
            "success": False,
            "reason": "not_connected",
            "result": "No direct Message button on the profile — not a connection or messaging unavailable",
            "profile_url": clean_url,
            "screenshot_path": screenshot_path,
        }

    page.wait_for_timeout(2000)

    # Guard: if the New-Message compose (recipient typeahead) opened, we did NOT land in
    # a direct thread — bail cleanly. This is the exact element that hung the old skill.
    try:
        if page.locator(
            ".msg-connections-typeahead-container, [class*='connections-typeahead']"
        ).first.is_visible(timeout=1500):
            return {
                "success": False,
                "reason": "not_connected",
                "result": "Opened the New-Message compose (recipient typeahead) — target is not directly messageable",
                "profile_url": clean_url,
                "screenshot_path": screenshot_path,
            }
    except Exception:
        pass

    # Find the direct-message overlay editor.
    editor = None
    for sel in [
        ".msg-form__contenteditable",
        ".msg-overlay-conversation-bubble [contenteditable='true']",
        '[role="textbox"]',
        "div.ql-editor",
    ]:
        try:
            loc = page.locator(sel).last
            loc.wait_for(state="visible", timeout=5000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        return {
            "success": False,
            "reason": "no_message_box",
            "result": "Clicked Message but no direct message box opened",
            "profile_url": clean_url,
            "screenshot_path": screenshot_path,
        }

    # Fill — guarded so a stuck/ intercepted click reports failure instead of hanging.
    try:
        editor.click(timeout=5000)
        editor.fill(message, timeout=8000)
    except Exception as fe:
        return {
            "success": False,
            "reason": "fill_failed",
            "result": f"Could not type into the message box: {str(fe)[:120]}",
            "profile_url": clean_url,
            "screenshot_path": screenshot_path,
        }
    page.wait_for_timeout(800)

    # Send.
    sent = False
    for send_sel in [
        lambda: page.get_by_role("button", name="Send", exact=True).last.click(timeout=6000),
        lambda: page.locator('button.msg-form__send-button, button[class*="send"]').last.click(timeout=4000),
        lambda: editor.press("Enter"),
    ]:
        try:
            send_sel()
            sent = True
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    try:
        page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
    except Exception:
        pass

    # Honest success: a sent message clears the composer. If the text is still in the
    # box, the send did not go through (mirrors #4327 / #1805 — clicking Send != sent).
    confirmed = sent
    try:
        if (editor.inner_text(timeout=1500) or "").strip():
            confirmed = False
    except Exception:
        pass  # editor detached/cleared after send → treat as sent

    return {
        "success": confirmed,
        "confirmed": confirmed,
        "result": (
            f"Message sent ({len(message)} chars)"
            if confirmed
            else "Clicked Send but the message did not clear the composer (not confirmed sent)"
        ),
        "profile_url": clean_url,
        "error": None if confirmed else "message_not_confirmed",
        "screenshot_path": screenshot_path,
    }
