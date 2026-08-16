"""LinkedIn post with image — publishes a text post with an attached image."""
import os
import sys
from datetime import datetime

_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
# Guard the insert (#5650): skill_runner._discover_skills() re-imports EVERY skill on
# EVERY execute(), so an unguarded insert added a duplicate path per skill per run —
# measured sys.path 6 -> 33 after only 3 discoveries in a long-lived container.
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_DIR)
from _linkedin_common import get_company_slug

SKILL_NAME = "linkedin_post_image"
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
    content = params.get("content", "").strip()
    image_path = params.get("image_path", "").strip()
    hashtags = params.get("hashtags", [])
    post_as_company = params.get("post_as_company", False)
    company_slug = get_company_slug(params)

    if not content:
        raise ValueError("content is required")
    if not image_path or not os.path.exists(image_path):
        raise ValueError(f"image_path not found: {image_path}")

    if hashtags:
        content += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in hashtags)

    if post_as_company:
        page.goto(f"https://www.linkedin.com/company/{company_slug}/admin/overview/", wait_until="domcontentloaded")
    else:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Open share box
    for attempt in [
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Start a post", exact=False).first.click(timeout=8000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=6000),
        lambda: page.get_by_role("button", name="Create a post", exact=False).first.click(timeout=6000),
    ]:
        try:
            attempt()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    _screenshot(page, "post_img_box_open")

    # Fill text content first
    editor = None
    for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=6000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        raise RuntimeError("Could not find post editor")

    editor.click()
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(500)

    # Click image/media attach button
    clicked_media = False
    for attempt in [
        lambda: page.get_by_role("button", name="Add a photo", exact=False).click(timeout=6000),
        lambda: page.get_by_label("Add a photo", exact=False).click(timeout=5000),
        lambda: page.locator('button[aria-label*="photo" i], button[aria-label*="image" i], button[aria-label*="media" i]').first.click(timeout=5000),
        lambda: page.locator('.share-creation-state__additional-toolbar button').first.click(timeout=5000),
    ]:
        try:
            attempt()
            clicked_media = True
            break
        except Exception:
            continue

    if not clicked_media:
        _screenshot(page, "post_img_media_fail")
        raise RuntimeError("Could not find image attach button")

    page.wait_for_timeout(1000)

    # Set file on file input
    file_input = None
    for sel in ['input[type="file"]', 'input[accept*="image"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=6000)
            file_input = loc
            break
        except Exception:
            continue

    if file_input is None:
        raise RuntimeError("Could not find file input for image")

    file_input.set_input_files(image_path)
    page.wait_for_timeout(3000)
    _screenshot(page, "post_img_attached")

    # Done / Next button (LinkedIn shows image preview step)
    for next_btn in [
        lambda: page.get_by_role("button", name="Done", exact=True).click(timeout=6000),
        lambda: page.get_by_role("button", name="Next", exact=True).click(timeout=6000),
        lambda: page.locator('button:has-text("Done")').last.click(timeout=5000),
    ]:
        try:
            next_btn()
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    _screenshot(page, "post_img_ready")

    # Post
    for post_btn in [
        lambda: page.get_by_role("button", name="Post", exact=True).click(timeout=10000),
        lambda: page.locator('button:has-text("Post")').last.click(timeout=8000),
    ]:
        try:
            post_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(3000)
    return {
        "success": True,
        "result": f"Posted with image ({len(content)} chars)",
        "image_path": image_path,
        "screenshot_path": _screenshot(page, "post_img_done"),
    }
