"""LinkedIn connect skill — send a connection request with optional note."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_connect"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def execute(page, params: dict) -> dict:
    profile_url = params.get("profile_url", "").strip()
    note = params.get("note", "").strip()
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_connect")

    clean_url = profile_url.split("?")[0].rstrip("/")
    page.goto(clean_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_connect_{ts}.png"
    page.screenshot(path=screenshot_path)

    # Try direct Connect button first
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Connect", exact=True).first.click(timeout=6000),
        lambda: page.locator('button:has-text("Connect")').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    # If not found directly, try More dropdown
    if not clicked:
        for more_sel in [
            lambda: page.get_by_role("button", name="More…").click(timeout=5000),
            lambda: page.get_by_role("button", name="More").click(timeout=5000),
            lambda: page.locator('[aria-label*="More actions"]').click(timeout=5000),
        ]:
            try:
                more_sel()
                page.wait_for_timeout(1000)
                page.get_by_role("menuitem", name="Connect", exact=False).click(timeout=5000)
                clicked = True
                break
            except Exception:
                continue

    if not clicked:
        # Check if already connected / pending
        page_text = page.locator("body").inner_text(timeout=3000)
        if "Message" in page_text and "Connect" not in page_text:
            return {"success": False, "reason": "already_connected", "screenshot_path": screenshot_path}
        if "Pending" in page_text:
            return {"success": False, "reason": "request_pending", "screenshot_path": screenshot_path}
        raise RuntimeError("Could not find Connect button — screenshot saved to " + screenshot_path)

    page.wait_for_timeout(1500)

    # Add note if provided
    if note:
        for note_btn in [
            lambda: page.get_by_role("button", name="Add a note").click(timeout=5000),
            lambda: page.locator('button:has-text("Add a note")').click(timeout=5000),
        ]:
            try:
                note_btn()
                page.wait_for_timeout(1000)
                page.locator('textarea[name="message"]').fill(note[:300], timeout=5000)
                break
            except Exception:
                continue

    # Send the request
    for send_sel in [
        lambda: page.get_by_role("button", name="Send", exact=True).click(timeout=8000),
        lambda: page.get_by_role("button", name="Send without a note").click(timeout=5000),
        lambda: page.locator('button:has-text("Send")').last.click(timeout=5000),
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
        "result": "Connection request sent",
        "note_included": bool(note),
        "profile_url": clean_url,
        "screenshot_path": screenshot_path,
    }
