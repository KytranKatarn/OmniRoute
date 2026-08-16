"""LinkedIn feed — reads the home feed and returns recent posts."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_feed"
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


# Home-feed extraction, anchored on the SDUI feed-card component key (#5649).
#
# ROOT CAUSE: LinkedIn moved the home feed to its server-driven UI
# (`data-sdui-screen="com.linkedin.sdui.flagshipnav.feed.MainFeed"`), which emits HASHED
# css class names. Measured 2026-08-16: `.feed-shared-update-v2`, `.occludable-update`
# and `[data-urn*="activity"]` ALL matched zero (the page has NO data-urn attributes at
# all), so this returned `success: True, posts: []` forever — a selector break that looked
# exactly like an empty feed.
#
# ⚠️ post_url IS NOT RECOVERABLE from the SDUI feed, and that is not a bug in this code.
# Measured on a loaded feed: `a[href*="/feed/update/"]` -> 0 and `[data-urn]` -> 0. The
# card's componentkey is an opaque TRACKING id (e.g. `my56wSYwzxvZOnQ...`), not an
# activity urn, so there is nothing to build a permalink from. The field is returned EMPTY
# rather than guessed. If a caller needs permalinks, open the post and use
# linkedin_post_comments' componentkey urn, or come in via the notification bell.
_JS_FEED = r"""
(limit) => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  // LinkedIn renders names twice for a11y and the aria-hidden copy is normally the
  // visible one — but on cards carrying a Verified/Premium badge that subtree is EMPTY.
  // Fall back to the full textContent, or the author silently comes back blank.
  const vis = el => {
    if (!el) return '';
    const a = el.querySelector('[aria-hidden="true"]');
    const t = clean(a ? a.textContent : el.textContent);
    return t || clean(el.textContent);
  };

  let strategy = 'sdui_feedtype_key';
  let cards = [...document.querySelectorAll('[componentkey*="FeedType_MAIN_FEED"]')];
  if (!cards.length) {
    cards = [...document.querySelectorAll('.feed-shared-update-v2, .occludable-update, [data-urn*="activity"]')];
    strategy = cards.length ? 'legacy_class' : 'none';
  }

  const out = [], seen = new Set();
  for (const card of cards) {
    if (out.length >= limit) break;
    // The FIRST profile anchor is the avatar and has no <p> — take the first that does.
    let anchor = null, ps = [];
    for (const a of card.querySelectorAll('a[href*="/in/"], a[href*="/company/"]')) {
      const q = a.querySelectorAll('p');
      if (q.length) { anchor = a; ps = q; break; }
      if (!anchor) anchor = a;
    }
    let author = ps.length ? vis(ps[0]) : '';
    author = author.replace(/\s*[•·]\s*(1st|2nd|3rd|Following|You)\b.*$/i, '').trim();
    const author_title = ps.length > 1 ? vis(ps[1]) : '';

    const body = card.querySelector('[data-testid="expandable-text-box"]')
              || card.querySelector('.update-components-text, .feed-shared-text__text-view');
    let content = body ? clean(body.textContent) : '';
    content = content.replace(/\s*[…\.]{1,3}\s*(see )?more\s*$/i, '').trim();

    let timestamp = '';
    for (const q of card.querySelectorAll('p, time')) {
      const t = clean(q.textContent);
      // feed stamps render like "15h •" — tolerate the trailing bullet
      if (/^\d+\s*(s|m|h|d|w|mo|y)\b/i.test(t) && t.length < 16) {
        timestamp = t.replace(/\s*[•·]\s*$/, '').trim();
        break;
      }
    }

    if (!author && !content) continue;
    const key = author + '|' + content.substring(0, 60);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      author,
      author_title: author_title.substring(0, 160),
      content: content.substring(0, 300),
      post_url: '',   // deliberately empty — see the note above
      author_url: anchor ? (anchor.getAttribute('href') || '').split('?')[0] : '',
      timestamp,
      _strategy: strategy,
    });
  }
  return out;
}
"""


def execute(page, params: dict) -> dict:
    limit = int(params.get("limit", 10))
    feed_url = params.get("feed_url", "https://www.linkedin.com/feed/")

    page.goto(feed_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Scroll to load posts. The SDUI feed is lazily mounted, so this is load-bearing —
    # without it the card list is not in the DOM at all.
    for _ in range(3):
        try:
            page.mouse.wheel(0, 1600)
        except Exception:
            page.evaluate("window.scrollBy(0, 1600)")
        page.wait_for_timeout(1100)

    _screenshot(page, "feed_loaded")

    posts = page.evaluate(_JS_FEED, limit)

    # Which selector family matched. This is the regression tripwire: the #5649 outage was
    # invisible because a selector break and an empty feed produced identical output.
    strategy = posts[0].get("_strategy") if posts else None
    for p in posts:
        p.pop("_strategy", None)

    body = ""
    try:
        body = (page.inner_text("body", timeout=3000) or "")[:3000].lower()
    except Exception:
        pass
    walled = ("sign in to view" in body) or ("join linkedin" in body) or ("authwall" in page.url.lower())

    out = {
        "success": not walled,
        "total": len(posts),
        "posts": posts,
        "strategy": strategy or "none",
        "screenshot_path": _screenshot(page, "feed_result"),
    }
    if walled:
        out["result"] = "auth_wall — session not logged in for this profile"
    elif not posts:
        out["result"] = (
            "no posts extracted — either a genuinely empty feed, or LinkedIn moved the "
            "markup again. Distinguish before assuming: if the page shows posts but "
            "strategy=='none', the selectors broke (see #5649)."
        )
    return out
