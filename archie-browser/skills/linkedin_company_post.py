"""LinkedIn company post — publishes a post as Kytran Empowerment Inc."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_company_post"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    company_slug = params.get("company_slug", "kytran-empowerment")
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    if not content:
        raise ValueError("content is required for linkedin_company_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    # Navigate to company admin page — posting as company happens from here
    admin_url = f"https://www.linkedin.com/company/{company_slug}/admin/overview/"
    page.goto(admin_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "company_post_before")

    # Click "Start a post" / "Create a post" share box
    clicked = False
    for attempt in [
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Start a post", exact=False).click(timeout=8000),
        lambda: page.locator('button:has-text("Start a post")').first.click(timeout=8000),
        lambda: page.locator('[class*="share-box"] button').first.click(timeout=8000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=8000),
        # Company pages sometimes have "Create a post" instead
        lambda: page.get_by_role("button", name="Create a post", exact=False).click(timeout=6000),
        lambda: page.get_by_text("Create a post", exact=False).first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "company_post_btn_fail")
        raise RuntimeError("Could not find Start a post button on company page")

    page.wait_for_timeout(2000)
    _screenshot(page, "company_post_editor_open")

    # Fill the post editor
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
        _screenshot(page, "company_post_editor_fail")
        raise RuntimeError("Could not find post editor")

    editor.click(timeout=5000)
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(1000)
    _screenshot(page, "company_post_filled")

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

    # Dismiss any follow-up modal
    try:
        page.get_by_role("button", name="No thanks", exact=False).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    final = _screenshot(page, "company_post_final")
    return {
        "success": True,
        "result": f"Posted {len(content)} characters as {company_slug}",
        "company_slug": company_slug,
        "screenshot_path": final,
    }
