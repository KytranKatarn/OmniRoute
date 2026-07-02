"""LinkedIn comment like — like a SPECIFIC comment under a post (cross-boost).

Built for S.I.G.N.A.L. cross-account boosting (Terry likes Kytran's comments and
vice versa) but works for any comment. Input is ideally a comment DEEP-LINK
(``comment_url`` containing ?commentUrn=...) — only the deep-link reliably renders
the thread in the automated session; a plain post permalink usually renders ZERO
comments (KB #274178). Fallback targeting by ``comment_author``/``comment_contains``
mirrors linkedin_comment_reply.

Honesty contract: success ONLY on state evidence — the target comment's Like
button reports pressed (aria-pressed / active class) after the click. Already-liked
is returned as success with ``already=True`` (idempotent).
"""
import os
import re
from datetime import datetime
from urllib.parse import unquote

SKILL_NAME = "linkedin_comment_like"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

_COMMENT_SEL = (
    "article.comments-comment-entity, .comments-comment-item, "
    ".comments-comments-list__comment-item, [data-id*='comment']"
)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _dismiss_overlays(page):
    for attempt in [
        lambda: page.locator('button[aria-label="Dismiss"]').first.click(timeout=2000),
        lambda: page.locator(".artdeco-modal__dismiss").first.click(timeout=2000),
        lambda: page.keyboard.press("Escape"),
    ]:
        try:
            attempt()
            page.wait_for_timeout(400)
        except Exception:
            continue


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def _target_comment_id(comment_url):
    # commentUrn=urn:li:comment:(activity:<act>,<commentId>) — grab <commentId>.
    dec = unquote(comment_url or "")
    m = re.search(r"comment:\(activity:\d+,(\d+)\)", dec)
    return m.group(1) if m else ""


def _like_button(target):
    """The target comment's own Like toggle — scoped to the comment node so we can
    never hit the POST's like button by accident."""
    for getter in [
        lambda: target.locator('button[aria-label^="Like"], button[aria-label*=" Like"]').first,
        lambda: target.get_by_role("button", name=re.compile(r"^Like\b", re.I)).first,
        lambda: target.locator("button.comments-comment-social-bar__reaction-action").first,
    ]:
        try:
            btn = getter()
            btn.wait_for(state="visible", timeout=3000)
            return btn
        except Exception:
            continue
    return None


def _is_pressed(btn) -> bool:
    """State evidence that the like is registered (aria-pressed / active class /
    label flipped to a reacted form)."""
    try:
        if (btn.get_attribute("aria-pressed", timeout=1500) or "").lower() == "true":
            return True
    except Exception:
        pass
    try:
        cls = btn.get_attribute("class", timeout=1500) or ""
        if "active" in cls or "reacted" in cls:
            return True
    except Exception:
        pass
    try:
        label = (btn.get_attribute("aria-label", timeout=1500) or "").lower()
        if "unreact" in label or "unlike" in label:
            return True
    except Exception:
        pass
    return False


def execute(page, params: dict) -> dict:
    comment_url = (params.get("comment_url") or "").strip()
    post_url = (params.get("post_url") or "").strip()
    comment_author = (params.get("comment_author") or "").strip()
    comment_contains = (params.get("comment_contains") or "").strip()

    nav_url = comment_url or post_url
    if not nav_url:
        raise ValueError("comment_url (preferred) or post_url is required for linkedin_comment_like")

    page.goto(nav_url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _dismiss_overlays(page)

    # Pull the thread in (lazy-loaded). The deep-link renders it; scroll to be sure.
    for _ in range(3):
        try:
            page.mouse.wheel(0, 1100)
        except Exception:
            pass
        page.wait_for_timeout(800)
    for _ in range(2):
        try:
            page.locator('button[aria-label*="more comment"], button:has-text("Load more comments")').first.click(
                timeout=2500
            )
            page.wait_for_timeout(1200)
        except Exception:
            break

    comments = page.locator(_COMMENT_SEL)
    n = comments.count()
    if n == 0:
        _screenshot(page, "clike_no_comments")
        return {
            "success": False,
            "confirmed": False,
            "error": "no_comments_rendered",
            "result": "No comments rendered — pass a comment_url deep-link (?commentUrn=), not a plain post URL (KB #274178)",
            "post_url": nav_url,
        }

    # 1) Precise: the comment whose data-id matches the commentUrn id.
    target = None
    target_idx = -1
    cid = _target_comment_id(comment_url)
    if cid:
        try:
            cand = page.locator(f"[data-id*='{cid}']").first
            cand.wait_for(state="visible", timeout=3000)
            target = cand
            target_idx = -2  # matched by id
        except Exception:
            target = None

    # 2) Fallback: author/text match across rendered comments.
    if target is None:
        a_needle = _norm(comment_author)
        c_needle = _norm(comment_contains)
        if not (a_needle or c_needle):
            _screenshot(page, "clike_no_selector")
            return {
                "success": False,
                "confirmed": False,
                "error": "no_target_selector",
                "result": "No commentUrn deep-link and no comment_author/comment_contains — refusing to like an arbitrary comment",
                "post_url": nav_url,
            }
        for i in range(n):
            node = comments.nth(i)
            try:
                txt = _norm(node.inner_text())
            except Exception:
                txt = ""
            if ((not a_needle) or a_needle in txt) and ((not c_needle) or c_needle in txt):
                target = node
                target_idx = i
                break

    if target is None:
        _screenshot(page, "clike_target_miss")
        return {
            "success": False,
            "confirmed": False,
            "error": "target_comment_not_found",
            "result": f"Thread rendered ({n} comments) but no match for id='{cid}' author='{comment_author}' contains='{comment_contains}'",
            "post_url": nav_url,
        }

    try:
        target.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    btn = _like_button(target)
    if btn is None:
        _screenshot(page, "clike_btn_miss")
        return {
            "success": False,
            "confirmed": False,
            "error": "like_button_not_found",
            "result": "Found the comment but not its Like button",
            "post_url": nav_url,
        }

    matched_by = "comment_id" if target_idx == -2 else f"index {target_idx}"

    if _is_pressed(btn):
        return {
            "success": True,
            "confirmed": True,
            "already": True,
            "result": f"Comment already liked ({matched_by})",
            "post_url": nav_url,
            "matched_by": matched_by,
            "error": None,
            "screenshot_path": _screenshot(page, "clike_already"),
        }

    try:
        btn.click(timeout=5000)
    except Exception:
        try:
            btn.click(timeout=4000, force=True)
        except Exception:
            _screenshot(page, "clike_click_fail")
            return {
                "success": False,
                "confirmed": False,
                "error": "like_click_failed",
                "result": "Like button found but the click did not register",
                "post_url": nav_url,
            }

    # Verify on STATE, not hope: poll the same button for pressed evidence.
    confirmed = False
    for _ in range(4):
        page.wait_for_timeout(1200)
        if _is_pressed(btn):
            confirmed = True
            break

    return {
        "success": confirmed,
        "confirmed": confirmed,
        "already": False,
        "result": (
            f"Comment liked ({matched_by})" if confirmed else "Clicked Like but the pressed state was NOT confirmed"
        ),
        "post_url": nav_url,
        "matched_by": matched_by,
        "error": None if confirmed else "like_not_confirmed",
        "screenshot_path": _screenshot(page, "clike_done"),
    }
