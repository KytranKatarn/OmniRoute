"""LinkedIn comment — posts a comment on a LinkedIn post by URL."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_comment"
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
    post_url = params.get("post_url", "").strip()
    comment = params.get("comment", "").strip()

    if not post_url:
        raise ValueError("post_url is required for linkedin_comment")
    if not comment:
        raise ValueError("comment is required for linkedin_comment")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "comment_before")

    # Click the Comment button to open the reply box
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Comment", exact=True).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="Comment"]').first.click(timeout=6000),
        lambda: page.locator('.comment-button, button:has-text("Comment")').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "comment_btn_fail")
        raise RuntimeError("Could not find Comment button")

    page.wait_for_timeout(1500)
    _screenshot(page, "comment_box_open")

    # Find comment editor
    editor = None
    for sel in [
        '.ql-editor[contenteditable="true"]',
        '.comments-comment-box__detour-container .ql-editor',
        '[role="textbox"][contenteditable="true"]',
        '.comments-comment-texteditor .ql-editor',
        'div.ql-editor',
        '[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(sel).last
            loc.wait_for(state="visible", timeout=5000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        _screenshot(page, "comment_editor_fail")
        raise RuntimeError("Could not find comment editor")

    editor.click(timeout=5000)
    editor.fill(comment, timeout=10000)
    page.wait_for_timeout(800)
    _screenshot(page, "comment_filled")

    # Submit
    for submit_btn in [
        lambda: page.get_by_role("button", name="Post comment", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Submit", exact=False).click(timeout=6000),
        lambda: page.locator('button.comments-comment-box__submit-button').click(timeout=5000),
        lambda: page.locator('button[class*="submit"]').last.click(timeout=5000),
    ]:
        try:
            submit_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    return {
        "success": True,
        "result": f"Commented ({len(comment)} chars) on post",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "comment_done"),
    }
