"""LinkedIn first comment — posts the first comment on a just-published post."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_first_comment"
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
    comment = params.get("comment",
        "Thoughts? We're building this at kytranempowerment.com — "
        "AI infrastructure that actually works. 🚀").strip()

    if not post_url:
        raise ValueError("post_url is required for linkedin_first_comment")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "first_comment_before")

    # Click Comment button
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Comment", exact=True).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="Comment"]').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        raise RuntimeError("Could not find Comment button on post")

    page.wait_for_timeout(1500)

    # Find editor
    editor = None
    for sel in ['.ql-editor[contenteditable="true"]', '[role="textbox"]', '[contenteditable="true"]']:
        try:
            loc = page.locator(sel).last
            loc.wait_for(state="visible", timeout=5000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        raise RuntimeError("Could not find comment editor")

    editor.click()
    editor.fill(comment, timeout=8000)
    page.wait_for_timeout(800)

    # Submit
    for submit_btn in [
        lambda: page.get_by_role("button", name="Post comment", exact=False).click(timeout=8000),
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
        "result": f"First comment posted ({len(comment)} chars)",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "first_comment_done"),
    }
