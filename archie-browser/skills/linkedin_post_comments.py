"""LinkedIn post comments — READ-ONLY scrape of the comment thread on a post.

Part of #3964 (S.I.G.N.A.L. comment-reply integration), READ scope. Posts
NOTHING — it only navigates to a post URL, expands the comment thread, and
returns the comments (author, headline, text, timestamp, reply depth). Works
on our own posts AND posts we merely commented on (e.g. an accountability
thread), so the engagement monitor can watch for replies to our comments.

Pure read = does NOT trip the step-up posting wall (KB #272122).
Contract matches the other skills: execute(page, params) -> dict.
"""
import os
from datetime import datetime

SKILL_NAME = "linkedin_post_comments"
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
    limit = int(params.get("limit", 50))
    if not post_url:
        raise ValueError("post_url is required for linkedin_post_comments")

    # Normalize to an ABSOLUTE url — a relative '/feed/update/urn:...' makes chromium
    # raise "Cannot navigate to invalid URL", which (pre-fix) wedged the profile. (#4372)
    if not post_url.startswith(("http://", "https://")):
        post_url = "https://www.linkedin.com/" + post_url.lstrip("/")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Best-effort: sort by most recent + expand "load more comments" a few times
    # so replies to our comment surface. All optional — never fail the read.
    try:
        page.get_by_role("button", name="Most recent", exact=False).first.click(timeout=4000)
        page.wait_for_timeout(1500)
    except Exception:
        pass
    for _ in range(4):
        try:
            loaded = page.locator(
                'button:has-text("Load more comments"), button:has-text("more comments"), '
                'button[aria-label*="more comment"]'
            ).first
            loaded.click(timeout=3000)
            page.wait_for_timeout(1200)
        except Exception:
            break

    comments = page.evaluate(
        f"""() => {{
        const out = [];
        const seen = new Set();
        const nodes = document.querySelectorAll(
            'article.comments-comment-entity, .comments-comment-item, [data-id*="comment"], .comments-comments-list__comment-item'
        );
        let count = 0;
        for (const node of nodes) {{
            if (count >= {limit}) break;
            const nameEl = node.querySelector(
                '.comments-comment-meta__description-title, .comments-post-meta__name-text, span.comments-comment-meta__description-title'
            );
            const author = nameEl ? nameEl.textContent.trim() : '';
            const headEl = node.querySelector(
                '.comments-comment-meta__description-subtitle, .comments-post-meta__headline'
            );
            const headline = headEl ? headEl.textContent.trim() : '';
            const bodyEl = node.querySelector(
                '.comments-comment-item__main-content, .update-components-text, .comments-comment-entity__content, span.comments-comment-item-content-body'
            );
            const text = bodyEl ? bodyEl.textContent.trim() : '';
            const timeEl = node.querySelector('time, .comments-comment-meta__data');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';
            const urn = node.getAttribute('data-id') || node.getAttribute('data-urn') || '';
            // Reply depth: replies are nested inside a replies container.
            const is_reply = !!node.closest('.comments-comment-item__nested-items, .comments-replies-list');

            if (!text && !author) continue;
            const key = urn || (author + '|' + text.substring(0, 60));
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({{
                urn,
                author,
                headline: headline.substring(0, 160),
                text: text.substring(0, 1200),
                timestamp,
                is_reply,
            }});
            count++;
        }}
        return out;
    }}"""
    )

    return {
        "success": True,
        "post_url": post_url,
        "total": len(comments),
        "comments": comments,
        "screenshot_path": _screenshot(page, "post_comments"),
    }
