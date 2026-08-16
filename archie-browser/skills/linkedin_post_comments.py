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


# Shadow-DOM-piercing comment extraction (#5644).
#
# THE BUG THIS REPLACES: the previous version called `document.querySelectorAll(...)`
# once, at document level. LinkedIn renders the comment thread inside SHADOW ROOTS, and
# `querySelectorAll` does NOT cross a shadow boundary (KB #277237) — so it matched an
# empty NodeList on every post, the loop never ran, and the skill returned
# `success: True, total: 0` forever. Verified 2026-08-16: zero comments returned against
# a plain permalink AND against `?commentUrn=` deep-links built two different ways,
# because the URL was never the problem — the extractor could not see the DOM at all.
#
# This is the SAME defect `linkedin_profile_view` carried until #4612 ("stale class
# selectors + a non-shadow-piercing About extract"), and the walk below is that skill's
# fix applied here. `pick()` re-walks each node's own subtree for the same reason: a
# node.querySelector will not descend into that node's shadow root either.
_JS_COMMENTS = r"""
(limit) => {
  function* walk(root){
    for (const el of root.querySelectorAll('*')) {
      yield el;
      if (el.shadowRoot) yield* walk(el.shadowRoot);
    }
  }
  const SEL = 'article.comments-comment-entity, .comments-comment-item, [data-id*="comment"], '
            + '.comments-comments-list__comment-item, article[class*="comment"]';
  // Collect every element once, so both node discovery and field extraction below
  // operate over a shadow-flattened view of the page rather than the light DOM only.
  const all = [];
  for (const el of walk(document)) all.push(el);

  const nodes = all.filter(el => { try { return el.matches && el.matches(SEL); } catch (e) { return false; } });

  // Field lookup that also pierces: search this node's descendants in the flattened
  // list rather than calling node.querySelector (which stops at its own shadow root).
  const pick = (node, sel) => {
    for (const el of all) {
      if (node.contains(el) || (node.shadowRoot && node.shadowRoot.contains(el))) {
        try { if (el.matches && el.matches(sel)) return el; } catch (e) {}
      }
    }
    try { return node.querySelector(sel); } catch (e) { return null; }
  };

  const out = [];
  const seen = new Set();
  let count = 0;
  for (const node of nodes) {
    if (count >= limit) break;
    const nameEl = pick(node,
      '.comments-comment-meta__description-title, .comments-post-meta__name-text, '
      + 'span.comments-comment-meta__description-title, [class*="meta__description-title"]');
    const author = nameEl ? nameEl.textContent.trim() : '';
    const headEl = pick(node,
      '.comments-comment-meta__description-subtitle, .comments-post-meta__headline, '
      + '[class*="meta__description-subtitle"]');
    const headline = headEl ? headEl.textContent.trim() : '';
    const bodyEl = pick(node,
      '.comments-comment-item__main-content, .update-components-text, '
      + '.comments-comment-entity__content, span.comments-comment-item-content-body, '
      + '[class*="comment-item-content-body"], [class*="comment-entity__content"]');
    const text = bodyEl ? bodyEl.textContent.trim() : '';
    const timeEl = pick(node, 'time, .comments-comment-meta__data, [class*="meta__data"]');
    const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';
    const urn = node.getAttribute('data-id') || node.getAttribute('data-urn') || '';
    let is_reply = false;
    try {
      is_reply = !!node.closest('.comments-comment-item__nested-items, .comments-replies-list, [class*="nested-items"]');
    } catch (e) {}

    if (!text && !author) continue;
    const key = urn || (author + '|' + text.substring(0, 60));
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      urn,
      author,
      headline: headline.substring(0, 160),
      text: text.substring(0, 1200),
      timestamp,
      is_reply,
    });
    count++;
  }
  return out;
}
"""


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

    comments = page.evaluate(_JS_COMMENTS, limit)

    # HONEST READ (#5644). `success: True` used to be hardcoded, so this returned
    # "success" with total:0 whether the thread was empty, the session was walled, or
    # the extractor simply could not see the DOM — which is precisely how the shadow-root
    # bug above stayed invisible. An empty thread IS a legitimate answer (plenty of posts
    # have no comments), so success only goes False when the page did not render a post
    # surface at all.
    body_txt = ""
    try:
        body_txt = (page.inner_text("body", timeout=3000) or "")[:4000].lower()
    except Exception:
        pass
    walled = ("sign in to view" in body_txt) or ("join linkedin" in body_txt) or ("authwall" in page.url.lower())

    result = {
        "success": not walled,
        "post_url": post_url,
        "final_url": page.url,
        "total": len(comments),
        "comments": comments,
        "screenshot_path": _screenshot(page, "post_comments"),
    }
    if walled:
        result["result"] = "auth_wall — session not logged in for this profile"
    elif not comments:
        result["result"] = (
            "no comments extracted — an empty thread, or LinkedIn changed the comment "
            "markup (selectors are class-name based and do churn)"
        )
    return result
