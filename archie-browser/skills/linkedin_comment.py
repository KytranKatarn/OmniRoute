"""LinkedIn comment — posts a comment on a LinkedIn post by URL."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_comment"
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


_COMMENT_NODE_SEL = (
    "article.comments-comment-entity, .comments-comment-item, "
    ".comments-comments-list__comment-item, [data-id*='comment']"
)


def _capture_comment_urn(page, needle, norm):
    """Best-effort: find OUR rendered comment's node and lift its comment URN from
    the data-id attribute (urn:li:comment:(activity:<a>,<c>) — the same id
    linkedin_comment_reply targets). Returns (urn, deep_link) or (None, None).
    The deep link is the only form that renders the thread for automation
    (KB #274178) and is what cross-boost needs to LIKE this comment later
    (#4632 follow-up: comments on THIRD-party posts have no notification-bell
    deep-link, so we must capture it at posting time)."""
    import re as _re
    from urllib.parse import quote

    try:
        nodes = page.locator(_COMMENT_NODE_SEL)
        n = min(nodes.count(), 15)
        for i in range(n):
            node = nodes.nth(i)
            try:
                if needle and needle not in norm(node.inner_text(timeout=800)):
                    continue
                did = node.get_attribute("data-id", timeout=800) or ""
                m = _re.search(r"urn:li:comment:\(activity:(\d+),\d+\)", did)
                if not m:
                    continue
                urn = m.group(0)
                link = (
                    f"https://www.linkedin.com/feed/update/urn:li:activity:{m.group(1)}/"
                    f"?commentUrn={quote(urn, safe='')}"
                )
                return urn, link
            except Exception:
                continue
    except Exception:
        pass
    return None, None


def execute(page, params: dict) -> dict:
    post_url = params.get("post_url", "").strip()
    comment = params.get("comment", "").strip()

    if not post_url:
        raise ValueError("post_url is required for linkedin_comment")
    if not comment:
        raise ValueError("comment is required for linkedin_comment")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "comment_before")

    # Click the Comment button to open the reply box
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Comment", exact=True).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="Comment"]').first.click(timeout=6000),
        lambda: page.locator('.comment-button, button:has-text("Comment")').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "comment_btn_fail")
        raise RuntimeError("Could not find Comment button")

    page.wait_for_timeout(1500)
    _screenshot(page, "comment_box_open")

    # Punctuation/emoji-insensitive matcher — used by BOTH the pre-submit retry
    # guard below and the post-submit verify at the end.
    import re as _re

    def _norm(s):
        return _re.sub(r"\s+", " ", _re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()

    needle = _norm(comment)[:40]

    # #4632 retry-safety: if OUR comment text is already rendered in the (now
    # expanded) thread, a previous attempt landed but its process died before
    # verifying — do NOT post again; return idempotent success. Best-effort:
    # LinkedIn ranks the viewer's own comment into the visible thread.
    try:
        if needle and needle in _norm(page.inner_text("body")):
            _urn, _curl = _capture_comment_urn(page, needle, _norm)
            return {
                "success": True,
                "confirmed": True,
                "already": True,
                "result": "Comment already present on post (previous attempt landed) — not re-posting",
                "post_url": post_url,
                "comment_urn": _urn,
                "comment_url": _curl,
                "error": None,
                "screenshot_path": _screenshot(page, "comment_already"),
            }
    except Exception:
        pass

    # Find comment editor
    editor = None
    for sel in [
        '.ql-editor[contenteditable="true"]',
        '.comments-comment-box__detour-container .ql-editor',
        '[role="textbox"][contenteditable="true"]',
        '.comments-comment-texteditor .ql-editor',
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
        _screenshot(page, "comment_editor_fail")
        raise RuntimeError("Could not find comment editor")

    editor.click(timeout=5000)
    editor.fill(comment, timeout=10000)
    page.wait_for_timeout(800)
    _screenshot(page, "comment_filled")

    # Submit
    for submit_btn in [
        lambda: page.get_by_role("button", name="Post comment", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Submit", exact=False).click(timeout=6000),
        lambda: page.locator('button.comments-comment-box__submit-button').click(timeout=5000),
        lambda: page.locator('button[class*="submit"]').last.click(timeout=5000),
    ]:
        try:
            submit_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(2500)

    # Verify the comment ACTUALLY rendered before claiming success. Our own just-
    # posted comment appears in the open thread in-session (a FRESH page load
    # collapses comments to "most relevant" — so verify HERE, not later).
    # Punctuation/emoji-insensitive substring match (needle/_norm defined above,
    # shared with the pre-submit retry guard). If it can't be confirmed, report
    # failure so the approval executor marks it 'failed' instead of a phantom
    # success (mirrors #4327 — drafted/submitted != posted).
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

    # Capture the new comment's URN + deep-link (best-effort) so cross-boost can
    # like this comment later — third-party posts have no other deep-link source.
    _urn, _curl = _capture_comment_urn(page, needle, _norm) if confirmed else (None, None)

    return {
        "success": confirmed,
        "confirmed": confirmed,
        "result": (
            f"Commented ({len(comment)} chars) on post"
            if confirmed
            else "Submitted but the comment could NOT be confirmed on the page after posting"
        ),
        "post_url": post_url,
        "comment_urn": _urn,
        "comment_url": _curl,
        "error": None if confirmed else "comment_not_confirmed",
        "screenshot_path": _screenshot(page, "comment_done"),
    }
