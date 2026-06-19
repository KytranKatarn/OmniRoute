"""LinkedIn recent activity — list a target profile/company's recent posts (read-only).

Engagement-discovery source for the S.I.G.N.A.L. engagement monitor (Phase 2.6).
Unlike the home feed + content search (which LinkedIn withholds from automation),
a profile's /recent-activity/all/ page and a company's /posts/ page ARE served to
the authenticated headless session — so this is how we surface OTHERS' posts to
(human-approved) like/comment on.

Returns post permalinks (+ a text snippet each). Read-only — no writes.
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_recent_activity"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

_ACTIVITY_RE = re.compile(r"urn:li:activity:\d+")


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _dismiss_overlays(page) -> bool:
    """Dismiss LinkedIn interstitial modals (Premium upsell, etc.). Harmless if none."""
    for attempt in [
        lambda: page.locator(".artdeco-modal__dismiss").first.click(timeout=2000),
        lambda: page.locator('button[aria-label="Dismiss"]').first.click(timeout=2000),
        lambda: page.get_by_role("button", name="Dismiss").first.click(timeout=2000),
    ]:
        try:
            attempt()
            page.wait_for_timeout(500)
            return True
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    return False


def _activity_url(profile_url: str) -> str:
    """Map a profile/company URL to its posts/recent-activity listing URL."""
    base = profile_url.split("?")[0].rstrip("/")
    low = base.lower()
    if "/recent-activity" in low or low.endswith("/posts"):
        return base + "/"
    if "/company/" in low or "/showcase/" in low:
        return base + "/posts/"
    # personal profile (/in/<vanity>) — also handles /in/me
    return base + "/recent-activity/all/"


def execute(page, params: dict) -> dict:
    profile_url = (params.get("profile_url") or "").strip()
    limit = int(params.get("limit", 3))
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_recent_activity")

    url = _activity_url(profile_url)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _dismiss_overlays(page)
    page.wait_for_timeout(1000)
    _screenshot(page, "recent_activity")

    html = page.content() or ""
    urns = list(dict.fromkeys(_ACTIVITY_RE.findall(html)))
    posts = []
    for u in urns:
        if len(posts) >= limit:
            break
        snippet = ""
        try:
            snippet = (page.locator(f'[data-urn="{u}"]').first.inner_text(timeout=2000) or "")[:200]
        except Exception:
            pass
        posts.append(
            {
                "post_url": f"https://www.linkedin.com/feed/update/{u}/",
                "snippet": snippet.replace("\n", " ").strip(),
            }
        )

    return {
        "success": True,
        "profile_url": profile_url,
        "activity_url": url,
        "total": len(posts),
        "posts": posts,
    }
