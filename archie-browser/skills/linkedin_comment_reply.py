"""LinkedIn comment reply — posts a THREADED reply nested under a specific comment.

Input is a comment DEEP-LINK (``comment_url`` containing ?commentUrn=...), the form
LinkedIn puts in "X commented on your post" notifications (see linkedin_notifications,
field ``comment_url``). Only this deep-link renders the existing comment thread in the
automated session — a plain post permalink does NOT (KB #274178). The target comment
is located by the commentUrn's id (precise), falling back to author/text match.

Verifies the reply rendered in-session before claiming success (mirrors #4327 +
linkedin_comment, PR #1805).
"""
import os
import re
import sys
from datetime import datetime
from urllib.parse import unquote

# Skills are loaded by spec_from_file_location, which does NOT put the skills
# dir on sys.path — see the _linkedin_common docstring.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _linkedin_common import (  # noqa: E402
    COMMENT_NODE_SEL,
    comment_ids_from_urn,
    comment_node_selector_for_id,
)

SKILL_NAME = "linkedin_comment_reply"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# Shared with linkedin_comment / linkedin_comment_like (#5650) — the three used
# to carry byte-identical copies, so one LinkedIn markup change broke all three.
_COMMENT_SEL = COMMENT_NODE_SEL


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
    # Shape-tolerant (#5650): SDUI renders the LONG urn (urn:li:activity: inside
    # the parens) while we store the SHORT one, and the old regex accepted only
    # the short shape — a long-form deep-link silently yielded no target id and
    # fell through to fuzzy author/text matching.
    _act, cid = comment_ids_from_urn(unquote(comment_url or ""))
    return cid or ""


def execute(page, params: dict) -> dict:
    comment_url = (params.get("comment_url") or "").strip()
    post_url = (params.get("post_url") or "").strip()
    reply = (params.get("reply") or "").strip()
    comment_author = (params.get("comment_author") or "").strip()
    comment_contains = (params.get("comment_contains") or "").strip()

    nav_url = comment_url or post_url
    if not nav_url:
        raise ValueError("comment_url (preferred) or post_url is required for linkedin_comment_reply")
    if not reply:
        raise ValueError("reply is required for linkedin_comment_reply")

    page.goto(nav_url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _dismiss_overlays(page)
    _screenshot(page, "creply_before")

    # Pull the thread in (lazy-loaded). The deep-link renders it; scroll to be sure.
    for _ in range(3):
        try:
            page.mouse.wheel(0, 1100)
        except Exception:
            pass
        page.wait_for_timeout(800)
    for _ in range(2):
        try:
            page.locator(
                'button[aria-label*="more comment"], button:has-text("Load more comments")'
            ).first.click(timeout=2500)
            page.wait_for_timeout(1200)
        except Exception:
            break

    comments = page.locator(_COMMENT_SEL)
    n = comments.count()
    if n == 0:
        _screenshot(page, "creply_no_comments")
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
            cand = page.locator(comment_node_selector_for_id(cid)).first
            cand.wait_for(state="visible", timeout=3000)
            target = cand
            target_idx = -2  # matched by id
        except Exception:
            target = None

    # 2) Fallback: author/text match across rendered comments. Else first comment.
    if target is None:
        a_needle = _norm(comment_author)
        c_needle = _norm(comment_contains)
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
        _screenshot(page, "creply_target_miss")
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

    # Open that comment's Reply box.
    clicked = False
    for attempt in [
        lambda: target.get_by_role("button", name=re.compile("Reply", re.I)).first.click(timeout=5000),
        lambda: target.locator('button[aria-label*="Reply"]').first.click(timeout=4000),
        lambda: target.locator('button:has-text("Reply")').first.click(timeout=4000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        _screenshot(page, "creply_btn_fail")
        return {
            "success": False,
            "confirmed": False,
            "error": "reply_button_not_found",
            "result": "Found the comment but could not open its Reply box",
            "post_url": nav_url,
        }

    page.wait_for_timeout(1500)

    # Reply editor — prefer one scoped to the target, else the last visible editor.
    editor = None
    for getter in [
        lambda: target.locator('.ql-editor[contenteditable="true"]').last,
        lambda: page.locator('.ql-editor[contenteditable="true"]').last,
        lambda: page.locator('[role="textbox"][contenteditable="true"]').last,
    ]:
        try:
            loc = getter()
            loc.wait_for(state="visible", timeout=4000)
            editor = loc
            break
        except Exception:
            continue
    if editor is None:
        _screenshot(page, "creply_editor_fail")
        return {
            "success": False,
            "confirmed": False,
            "error": "reply_editor_not_found",
            "result": "Reply box opened but the editor was not found",
            "post_url": nav_url,
        }

    editor.click(timeout=5000)
    editor.fill(reply, timeout=10000)
    page.wait_for_timeout(800)
    _screenshot(page, "creply_filled")

    # Submit — class-based first (unambiguous vs the "Reply" toggle), then role, then Ctrl+Enter.
    submitted = False
    for submit_btn in [
        lambda: page.locator("button.comments-comment-box__submit-button").last.click(timeout=6000),
        lambda: page.get_by_role("button", name=re.compile(r"^(Reply|Post comment)$", re.I)).last.click(timeout=5000),
        lambda: page.locator('button[class*="submit"]').last.click(timeout=5000),
    ]:
        try:
            submit_btn()
            submitted = True
            break
        except Exception:
            continue
    if not submitted:
        try:
            editor.press("Control+Enter")
        except Exception:
            pass

    page.wait_for_timeout(2500)

    # Verify the reply ACTUALLY rendered in-session before claiming success.
    needle = _norm(reply)[:40]
    confirmed = False
    for _ in range(3):
        try:
            page_txt = _norm(page.inner_text("body"))
        except Exception:
            page_txt = ""
        if needle and needle in page_txt:
            confirmed = True
            break
        page.wait_for_timeout(1500)

    matched_by = "comment_id" if target_idx == -2 else f"index {target_idx}"
    return {
        "success": confirmed,
        "confirmed": confirmed,
        "result": (
            f"Replied ({len(reply)} chars) to comment ({matched_by})"
            if confirmed
            else "Submitted but the reply could NOT be confirmed on the page"
        ),
        "post_url": nav_url,
        "matched_by": matched_by,
        "error": None if confirmed else "reply_not_confirmed",
        "screenshot_path": _screenshot(page, "creply_done"),
    }
