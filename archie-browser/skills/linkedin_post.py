"""LinkedIn post skill — publishes a text post to the LinkedIn feed."""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_post"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _dismiss_overlays(page) -> bool:
    """Dismiss LinkedIn interstitial modals (e.g. the 'Premium Company Page'
    upsell) that overlay the feed composer and block the share box — the #1 cause
    of 'share box not found' (the feed + composer ARE loaded behind it). Harmless
    when none is present. Returns True if something was dismissed."""
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
    # Escape closes most artdeco modals; harmless if there's nothing to close.
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    return False


def execute(page, params: dict) -> dict:
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    if not content:
        raise ValueError("content is required for linkedin_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Take screenshot before attempting to click (helps debug selector failures).
    # Non-fatal: bare screenshot times out 30s on LinkedIn's animated feed (#3953).
    try:
        page.screenshot(path=f"{_SCREENSHOTS_DIR}/linkedin_before_click.png", timeout=5000, animations="disabled")
    except Exception:
        pass

    # Dismiss any interstitial modal (Premium upsell, etc.) overlaying the composer
    # before looking for the share box.
    _dismiss_overlays(page)

    # Try multiple selectors — LinkedIn changes their UI frequently
    _share_selectors = [
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.locator('.share-box-feed-entry__trigger').first.click(timeout=8000),
        lambda: page.locator('[class*="share-box"]').first.click(timeout=8000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=8000),
        lambda: page.locator('button:has-text("Start a post")').click(timeout=8000),
    ]

    def _try_share_box():
        for attempt in _share_selectors:
            try:
                attempt()
                return True
            except Exception:
                continue
        return False

    clicked = _try_share_box()
    if not clicked:
        # A modal may have appeared late (after the first dismiss) — dismiss + retry once.
        _dismiss_overlays(page)
        clicked = _try_share_box()

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
    try:
        page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
    except Exception:
        screenshot_path = None

    page.get_by_role("button", name="Post", exact=True).click(timeout=10000)
    page.wait_for_timeout(4000)

    # Capture the permalink of the just-published post. Build it from the first
    # activity URN on the author's recent-activity page — more reliable than
    # scraping <a href>, which can match Premium/promo links carrying "activity"
    # in their query string (the old code returned /premium/products/).
    post_url = ""
    try:
        page.goto("https://www.linkedin.com/in/me/recent-activity/all/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        _dismiss_overlays(page)
        m = re.search(r"urn:li:activity:\d+", page.content() or "")
        if m:
            post_url = f"https://www.linkedin.com/feed/update/{m.group(0)}/"
    except Exception:
        pass

    return {
        "success": True,
        "result": f"Posted {len(content)} characters to LinkedIn",
        "post_url": post_url,
        "screenshot_path": screenshot_path,
    }
