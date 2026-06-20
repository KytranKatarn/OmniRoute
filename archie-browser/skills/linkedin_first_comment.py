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


def _dismiss_overlays(page) -> bool:
    """Dismiss LinkedIn interstitial modals (e.g. the 'Premium Company Page'
    upsell) that can overlay the post's comment controls. Harmless when none."""
    for attempt in [
        lambda: page.locator(".artdeco-modal__dismiss").first.click(timeout=2000),
        lambda: page.locator('button[aria-label="Dismiss"]').first.click(timeout=2000),
        lambda: page.get_by_role("button", name="Dismiss").first.click(timeout=2000),
    ]:
        try:
            attempt()
            page.wait_for_timeout(600)
            return True
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    return False


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
    _dismiss_overlays(page)

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

    page.wait_for_timeout(2500)

    # Verify the comment actually rendered before claiming success (mirrors #4327 +
    # linkedin_comment). Our own just-posted comment is in the open thread in-session.
    import re as _re

    def _norm(s):
        return _re.sub(r"\s+", " ", _re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()

    needle = _norm(comment)[:40]
    confirmed = False
    for _ in range(3):
        try:
            page_txt = _norm(page.inner_text("body"))
        except Exception:
            page_txt = ""
        if needle and needle in page_txt:
            confirmed = True
            break
        page.wait_for_timeout(1500)

    return {
        "success": confirmed,
        "confirmed": confirmed,
        "result": (
            f"First comment posted ({len(comment)} chars)"
            if confirmed
            else "Submitted but the first comment could NOT be confirmed on the page"
        ),
        "post_url": post_url,
        "error": None if confirmed else "comment_not_confirmed",
        "screenshot_path": _screenshot(page, "first_comment_done"),
    }
