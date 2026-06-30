"""LinkedIn GROUP comment — comment on a post inside a LinkedIn group.

The "engage" half of the WTF-group presence. Two modes:
  * ``post_url`` given  → comment on that specific post (our own group post, OR
    another member's post you want to engage). A group post permalink is a
    standard ``feed/update/urn:li:activity:`` URL.
  * ``group_id`` only   → navigate to the group and comment on its LATEST post
    (e.g. a follow-up first-comment with sources on the post we just published).

Reuses linkedin_comment's open→fill→submit flow and its verify-before-success
honesty gate: the comment must render in-session, else we report failure — never
a phantom success (mirrors #4327 / #1805). Comments work the same in a group as
in the feed, so this re-points the proven comment flow at the group context
rather than duplicating it elsewhere.

Params: comment (or content) — required; one of post_url / group_id — required.
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_group_comment"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    # Diagnostic only — non-fatal. Bare page.screenshot() times out at 30s on
    # LinkedIn's animated composer; 5s + animations disabled + swallow errors.
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def execute(page, params: dict) -> dict:
    comment = (params.get("comment") or params.get("content") or "").strip()
    post_url = (params.get("post_url") or "").strip()
    group_id = str(params.get("group_id") or os.getenv("LINKEDIN_WTF_GROUP_ID", "")).strip()

    if not comment:
        raise ValueError("comment is required for linkedin_group_comment")
    if not post_url and not group_id:
        raise ValueError("one of post_url / group_id is required for linkedin_group_comment")

    # 1. Land on the target — a specific post, or the group feed (newest post first).
    if post_url:
        target = post_url
    else:
        target = f"https://www.linkedin.com/groups/{group_id}/"
    page.goto(target, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    _screenshot(page, "group_comment_landed")

    # 2. Open the comment box. ``.first`` targets the post's Comment button (on a
    # permalink page) or the TOP post's Comment button (in the group feed).
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Comment", exact=True).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="Comment" i]').first.click(timeout=6000),
        lambda: page.locator('button:has-text("Comment")').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        _screenshot(page, "group_comment_btn_fail")
        raise RuntimeError(
            "Could not find a Comment button (no post to engage, or not a posting "
            f"member of group {group_id or '(permalink)'})"
        )
    page.wait_for_timeout(1500)

    # 3. Find the comment editor and fill it.
    editor = None
    for sel in [
        '.comments-comment-box__detour-container .ql-editor',
        '.comments-comment-texteditor .ql-editor',
        '.ql-editor[contenteditable="true"]',
        '[role="textbox"][contenteditable="true"]',
        'div.ql-editor',
        '[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(sel).last
            loc.wait_for(state="visible", timeout=5000)
            editor = loc
            break
        except Exception:
            continue
    if editor is None:
        _screenshot(page, "group_comment_editor_fail")
        raise RuntimeError("Could not find the comment editor")

    editor.click(timeout=5000)
    editor.fill(comment, timeout=10000)
    page.wait_for_timeout(800)
    _screenshot(page, "group_comment_filled")

    # 4. Submit.
    for submit_btn in [
        lambda: page.get_by_role("button", name="Post comment", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Submit", exact=False).click(timeout=6000),
        lambda: page.locator("button.comments-comment-box__submit-button").click(timeout=5000),
        lambda: page.locator('button[class*="submit"]').last.click(timeout=5000),
    ]:
        try:
            submit_btn()
            break
        except Exception:
            continue
    page.wait_for_timeout(2500)

    # 5. Verify-before-success: our just-posted comment must render in-session (a
    # fresh load collapses to "most relevant" — verify HERE). Punctuation/emoji-
    # insensitive substring match; on failure report failure, not a phantom.
    needle = _norm(comment)[:40]
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

    return {
        "success": confirmed,
        "confirmed": confirmed,
        "result": (
            f"Commented ({len(comment)} chars) in group {group_id or '(post)'}"
            if confirmed
            else "Submitted but the comment could NOT be confirmed on the page after posting"
        ),
        "group_id": group_id,
        "post_url": post_url,
        "error": None if confirmed else "comment_not_confirmed",
        "screenshot_path": _screenshot(page, "group_comment_done"),
    }
