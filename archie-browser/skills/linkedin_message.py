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
    page.screenshot(path=screenshot_path)

    # Click Message button
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Message", exact=True).first.click(timeout=6000),
        lambda: page.locator('button:has-text("Message")').first.click(timeout=6000),
        lambda: page.locator('[aria-label*="message"]').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        page_text = page.locator("body").inner_text(timeout=3000)
        if "Connect" in page_text and "Message" not in page_text:
            return {"success": False, "reason": "not_connected", "screenshot_path": screenshot_path}
        raise RuntimeError("Could not find Message button — screenshot saved to " + screenshot_path)

    page.wait_for_timeout(2000)

    # Find message input
    editor = None
    for sel in [
        ".msg-form__contenteditable",
        '[role="textbox"]',
        '[contenteditable="true"]',
        "div.ql-editor",
    ]:
        try:
            loc = page.locator(sel).last
            loc.wait_for(state="visible", timeout=6000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        raise RuntimeError("Could not find message input after opening chat")

    editor.click(timeout=5000)
    editor.fill(message, timeout=10000)
    page.wait_for_timeout(1000)

    page.screenshot(path=screenshot_path)

    # Send
    for send_sel in [
        lambda: page.get_by_role("button", name="Send", exact=True).last.click(timeout=8000),
        lambda: page.locator('button[class*="send"]').last.click(timeout=5000),
        lambda: page.keyboard.press("Enter"),
    ]:
        try:
            send_sel()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    page.screenshot(path=screenshot_path)

    return {
        "success": True,
        "result": f"Message sent ({len(message)} chars)",
        "profile_url": clean_url,
        "screenshot_path": screenshot_path,
    }
