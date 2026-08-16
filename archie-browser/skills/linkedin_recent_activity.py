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
from urllib.parse import quote

SKILL_NAME = "linkedin_recent_activity"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

_ACTIVITY_RE = re.compile(r"urn:li:activity:\d+")
# Comment URNs on the /recent-activity/comments/ tab (#5644). A plain post permalink
# renders ZERO comments to headless automation — only the `?commentUrn=` deep-link
# makes LinkedIn render the thread (KB #274178/#274179, the same finding that drove the
# threaded-reply rewrite in PRs #1805-#1807). Capturing these is what lets the owner's
# OWN comments be read back: the notification-bell path only ever sees INBOUND comments
# on his posts, never the ones he leaves on other people's.
_COMMENT_RE = re.compile(r"urn:li:comment:\([^)]*?(\d{6,})[^)]*?\)|urn:li:comment:\d+")
_COMMENT_RAW_RE = re.compile(r"urn:li:comment:\(?[^\s\"'<>]{6,}\)?")


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
    # Comment URNs are collected page-wide and zipped positionally to the activity URNs
    # below. LinkedIn renders one comment URN per item on the comments tab, in DOM order,
    # so index alignment holds there; when it does not (any other tab, or a layout
    # change) the count simply will not match and comment_urn stays None rather than
    # being guessed — a WRONG deep-link would silently scrape someone else's comment.
    comment_urns = list(dict.fromkeys(_COMMENT_RAW_RE.findall(html)))
    aligned = len(comment_urns) >= len(urns) and bool(comment_urns)

    posts = []
    for idx, u in enumerate(urns):
        if len(posts) >= limit:
            break
        snippet = ""
        try:
            snippet = (page.locator(f'[data-urn="{u}"]').first.inner_text(timeout=2000) or "")[:200]
        except Exception:
            pass
        curn = comment_urns[idx] if aligned and idx < len(comment_urns) else None
        item = {
            "post_url": f"https://www.linkedin.com/feed/update/{u}/",
            "snippet": snippet.replace("\n", " ").strip(),
        }
        if curn:
            item["comment_urn"] = curn
            # THE deep-link. Only this form renders the thread to automation.
            item["comment_url"] = f"https://www.linkedin.com/feed/update/{u}/?commentUrn={quote(curn, safe='')}"
        posts.append(item)

    # HONEST READ (#5644). `success: True` used to be hardcoded, so an auth wall or a
    # renderer change returned "success" with an empty list and the caller could not tell
    # a genuinely quiet profile from a broken read. An EMPTY result is still a legitimate
    # answer (a target may simply have no activity), so success only goes False when the
    # page itself did not render an activity surface — never merely because it was empty.
    low = html.lower()
    walled = ("authwall" in low) or ("sign in to view" in low) or ("join linkedin" in low)
    result = {
        "success": not walled,
        "profile_url": profile_url,
        "activity_url": url,
        "total": len(posts),
        "posts": posts,
        # Diagnostics: makes "found nothing" self-explaining instead of a silent zero.
        "activity_urns_seen": len(urns),
        "comment_urns_seen": len(comment_urns),
        "comment_urns_aligned": aligned,
    }
    if walled:
        result["result"] = "auth_wall — the session is not logged in for this profile"
    elif not posts:
        result["result"] = "no activity items rendered (empty tab, or a LinkedIn layout change)"
    return result
