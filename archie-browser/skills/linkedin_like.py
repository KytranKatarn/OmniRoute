"""LinkedIn like — reacts to a post by URL (like/celebrate/support/love/insightful/funny)."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_like"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _dismiss_overlays(page) -> bool:
    """Dismiss LinkedIn interstitial modals (Premium upsell, etc.) that can overlay
    the action bar. Harmless when none is present."""
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
    reaction = params.get("reaction", "like").lower()  # like/celebrate/support/love/insightful/funny

    if not post_url:
        raise ValueError("post_url is required for linkedin_like")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _dismiss_overlays(page)
    _screenshot(page, "like_before")

    # The reaction toggle's aria-label is "Reaction button state: <state>" — it's
    # "no reaction" before reacting, otherwise the chosen reaction. (Old "Like"
    # selectors went stale — KB.) Fall back to legacy labels just in case.
    react_btn = None
    for sel in [
        'button[aria-label^="Reaction button state"]',
        'button[aria-label*="Reaction button state"]',
        'button[aria-label="Like"]',
        'button[aria-label*="Like"]',
        ".reactions-react-button",
    ]:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=4000)
            react_btn = loc
            break
        except Exception:
            continue
    if react_btn is None:
        _screenshot(page, "like_fail")
        raise RuntimeError("Could not find reaction button")

    # Already reacted? (state label is anything other than "no reaction")
    try:
        cur_label = (react_btn.get_attribute("aria-label", timeout=2000) or "").lower()
    except Exception:
        cur_label = ""
    if "reaction button state" in cur_label and "no reaction" not in cur_label:
        return {
            "success": True,
            "result": f"Post already reacted ({cur_label})",
            "post_url": post_url,
            "screenshot_path": _screenshot(page, "like_already"),
        }

    # Non-default reaction → open the reactions menu and pick the named reaction.
    if reaction != "like":
        reaction_map = {
            "celebrate": "Celebrate",
            "support": "Support",
            "love": "Love",
            "insightful": "Insightful",
            "funny": "Funny",
            "like": "Like",
        }
        label = reaction_map.get(reaction, "Like")
        opened = False
        for attempt in [
            lambda: page.locator('button[aria-label="Open reactions menu"]').first.click(timeout=4000),
            lambda: react_btn.hover(timeout=4000),
        ]:
            try:
                attempt()
                page.wait_for_timeout(1200)
                opened = True
                break
            except Exception:
                continue
        if opened:
            try:
                page.get_by_role("button", name=label, exact=True).click(timeout=4000)
                page.wait_for_timeout(1200)
                return {
                    "success": True,
                    "result": f"Reacted with {label}",
                    "post_url": post_url,
                    "screenshot_path": _screenshot(page, "like_reacted"),
                }
            except Exception:
                pass  # fall through to a default Like

    # Default like — click the reaction toggle.
    react_btn.click(timeout=8000)
    page.wait_for_timeout(1500)
    return {
        "success": True,
        "result": "Post liked",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "like_done"),
    }
