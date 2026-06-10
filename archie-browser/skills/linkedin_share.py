"""LinkedIn share — reposts/shares a post with optional commentary."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_share"
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
    commentary = params.get("commentary", "").strip()  # optional text to add when sharing
    hashtags = params.get("hashtags", [])

    if not post_url:
        raise ValueError("post_url is required for linkedin_share")

    if hashtags and commentary:
        commentary += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in hashtags)
    elif hashtags:
        commentary = " ".join(f"#{t.lstrip('#')}" for t in hashtags)

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "share_before")

    # Click Share / Repost button
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Repost", exact=False).first.click(timeout=8000),
        lambda: page.get_by_role("button", name="Share", exact=False).first.click(timeout=6000),
        lambda: page.locator('button[aria-label*="share" i], button[aria-label*="repost" i]').first.click(timeout=6000),
        lambda: page.locator('button:has-text("Repost")').first.click(timeout=6000),
        lambda: page.locator('button:has-text("Share")').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "share_btn_fail")
        raise RuntimeError("Could not find Share/Repost button")

    page.wait_for_timeout(1500)
    _screenshot(page, "share_menu")

    # If commentary, choose "Repost with your thoughts" / "Share with thoughts"
    if commentary:
        for thoughts_btn in [
            lambda: page.get_by_role("button", name="Repost with your thoughts", exact=False).click(timeout=5000),
            lambda: page.get_by_text("Repost with your thoughts", exact=False).first.click(timeout=5000),
            lambda: page.get_by_role("button", name="Add a comment", exact=False).click(timeout=5000),
            lambda: page.get_by_text("Add a comment", exact=False).first.click(timeout=5000),
        ]:
            try:
                thoughts_btn()
                page.wait_for_timeout(2000)
                break
            except Exception:
                continue

        # Fill commentary in editor
        for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=5000)
                loc.click()
                loc.fill(commentary, timeout=8000)
                break
            except Exception:
                continue

        page.wait_for_timeout(500)
        _screenshot(page, "share_filled")

        # Post
        for post_btn in [
            lambda: page.get_by_role("button", name="Post", exact=True).last.click(timeout=8000),
            lambda: page.get_by_role("button", name="Repost", exact=True).last.click(timeout=6000),
        ]:
            try:
                post_btn()
                break
            except Exception:
                continue
    else:
        # Direct repost without commentary
        for repost_btn in [
            lambda: page.get_by_role("button", name="Repost", exact=True).last.click(timeout=6000),
            lambda: page.get_by_text("Repost", exact=True).last.click(timeout=5000),
        ]:
            try:
                repost_btn()
                break
            except Exception:
                continue

    page.wait_for_timeout(2000)
    return {
        "success": True,
        "result": f"Shared post {'with commentary' if commentary else 'directly'}",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "share_done"),
    }
