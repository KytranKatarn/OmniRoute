"""LinkedIn post skill — publishes a text post to the LinkedIn feed."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_post"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def execute(page, params: dict) -> dict:
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    if not content:
        raise ValueError("content is required for linkedin_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Take screenshot before attempting to click (helps debug selector failures)
    page.screenshot(path=f"{_SCREENSHOTS_DIR}/linkedin_before_click.png")

    # Try multiple selectors — LinkedIn changes their UI frequently
    clicked = False
    _share_selectors = [
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.locator('.share-box-feed-entry__trigger').first.click(timeout=8000),
        lambda: page.locator('[class*="share-box"]').first.click(timeout=8000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=8000),
        lambda: page.locator('button:has-text("Start a post")').click(timeout=8000),
    ]
    for attempt in _share_selectors:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        raise RuntimeError("Could not find LinkedIn share box — screenshot saved to " + f"{_SCREENSHOTS_DIR}/linkedin_before_click.png")

    page.wait_for_timeout(2000)

    # Fill the editor
    editor = None
    for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        raise RuntimeError("Could not find post editor after opening share box")

    editor.click(timeout=5000)
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(1000)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_post_{ts}.png"
    page.screenshot(path=screenshot_path)

    page.get_by_role("button", name="Post", exact=True).click(timeout=10000)
    page.wait_for_timeout(4000)

    # Try to capture the URL of the just-published post
    post_url = ""
    try:
        page.goto("https://www.linkedin.com/in/me/recent-activity/all/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        # Find the first post link in the activity feed
        link = page.locator('a[href*="feed/update/"], a[href*="activity"]').first
        href = link.get_attribute("href", timeout=4000) or ""
        if "linkedin.com" in href and ("feed/update" in href or "activity" in href):
            post_url = href.split("?")[0]
    except Exception:
        pass

    return {
        "success": True,
        "result": f"Posted {len(content)} characters to LinkedIn",
        "post_url": post_url,
        "screenshot_path": screenshot_path,
    }
