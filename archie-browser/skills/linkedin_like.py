"""LinkedIn like — likes a post by URL or from the feed."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_like"
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
    reaction = params.get("reaction", "like").lower()  # like, celebrate, support, love, insightful, funny

    if not post_url:
        raise ValueError("post_url is required for linkedin_like")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "like_before")

    # Check if already liked
    already_liked = False
    try:
        like_btn = page.locator('button[aria-label*="Like"][aria-pressed="true"]').first
        like_btn.wait_for(state="visible", timeout=2000)
        already_liked = True
    except Exception:
        pass

    if already_liked:
        return {
            "success": True,
            "result": "Post already liked",
            "screenshot_path": _screenshot(page, "like_already"),
        }

    # For non-default reactions (celebrate, support, etc.) — hold Like to open reaction picker
    if reaction != "like":
        try:
            like_btn = page.locator(
                'button[aria-label*="Like"], button[aria-label*="React"]'
            ).first
            like_btn.hover(timeout=5000)
            page.wait_for_timeout(1500)
            _screenshot(page, "like_reaction_picker")

            # Map reaction name to aria-label
            reaction_map = {
                "celebrate": "Celebrate",
                "support": "Support",
                "love": "Love",
                "insightful": "Insightful",
                "funny": "Funny",
                "like": "Like",
            }
            label = reaction_map.get(reaction, "Like")
            page.get_by_role("button", name=label, exact=True).click(timeout=5000)
            page.wait_for_timeout(1500)
            return {
                "success": True,
                "result": f"Reacted with {label}",
                "screenshot_path": _screenshot(page, "like_reacted"),
            }
        except Exception:
            pass  # Fall through to simple Like

    # Simple Like click
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Like", exact=True).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="Like"]').first.click(timeout=6000),
        lambda: page.locator('.reactions-react-button, button[class*="react"]').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "like_fail")
        raise RuntimeError("Could not find Like button")

    page.wait_for_timeout(1500)
    return {
        "success": True,
        "result": "Post liked",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "like_done"),
    }
