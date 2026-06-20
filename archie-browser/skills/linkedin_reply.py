"""LinkedIn reply — finds an existing conversation and sends a reply."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_reply"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    # Diagnostic only — non-fatal. Bare page.screenshot() times out at 30s on
    # LinkedIn's animated composer and falsely fails posts (#3953). 5s timeout
    # + animations disabled + swallow errors.
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def execute(page, params: dict) -> dict:
    reply_to = params.get("reply_to", "").strip()   # person name OR conversation index (int)
    message = params.get("message", "").strip()
    conversation_url = params.get("conversation_url", "").strip()

    if not message:
        raise ValueError("message is required for linkedin_reply")
    if not reply_to and not conversation_url:
        raise ValueError("reply_to (name) or conversation_url is required")

    if conversation_url:
        page.goto(conversation_url, wait_until="domcontentloaded")
    else:
        page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "reply_inbox")

    if not conversation_url:
        # Find the conversation by name
        opened = False

        # Try clicking thread matching the name
        for attempt in [
            lambda: page.locator(
                '.msg-conversation-listitem, .msg-conversation-card__participant-names'
            ).filter(has_text=reply_to).first.click(timeout=8000),
            lambda: page.get_by_text(reply_to, exact=False).first.click(timeout=6000),
        ]:
            try:
                attempt()
                opened = True
                break
            except Exception:
                continue

        if not opened:
            # Try search in messaging
            try:
                search = page.locator('input[placeholder*="Search"], input[aria-label*="Search"]').first
                search.fill(reply_to, timeout=5000)
                page.wait_for_timeout(1500)
                page.locator('.msg-conversation-listitem').first.click(timeout=5000)
                opened = True
            except Exception:
                pass

        if not opened:
            _screenshot(page, "reply_thread_fail")
            raise RuntimeError(f"Could not find conversation with: {reply_to}")

        page.wait_for_timeout(2000)

    _screenshot(page, "reply_thread_open")

    # Find the reply input at the bottom of the conversation
    editor = None
    for sel in [
        '.msg-form__contenteditable',
        'div.msg-form__compose-box [contenteditable="true"]',
        '[role="textbox"]',
        'div[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(sel).last
            loc.wait_for(state="visible", timeout=6000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        _screenshot(page, "reply_editor_fail")
        raise RuntimeError("Could not find reply input field")

    editor.click(timeout=5000)
    editor.fill(message, timeout=10000)
    page.wait_for_timeout(800)
    _screenshot(page, "reply_filled")

    # Send — the messaging send button first (most reliable), then role-based, then a
    # focused Enter (LinkedIn messaging sends on Enter when the composer has focus).
    sent = False
    for send_btn in [
        lambda: page.locator("button.msg-form__send-button").last.click(timeout=6000),
        lambda: page.get_by_role("button", name="Send", exact=True).last.click(timeout=5000),
        lambda: (editor.click(timeout=2000) or editor.press("Enter")),
    ]:
        try:
            send_btn()
            sent = True
            break
        except Exception:
            continue

    page.wait_for_timeout(2500)

    # Honest success: a sent reply CLEARS the composer. If the text is still in the box,
    # it did not send (mirrors #4327 / #1805 / linkedin_message — clicking Send != sent).
    confirmed = sent
    try:
        if (editor.inner_text(timeout=1500) or "").strip():
            confirmed = False
    except Exception:
        pass  # composer cleared / detached after send → treat as sent

    return {
        "success": confirmed,
        "confirmed": confirmed,
        "result": (
            f"Replied to {reply_to or conversation_url} ({len(message)} chars)"
            if confirmed
            else "Sent action ran but the reply did not clear the composer (not confirmed sent)"
        ),
        "error": None if confirmed else "reply_not_confirmed",
        "screenshot_path": _screenshot(page, "reply_sent"),
    }
