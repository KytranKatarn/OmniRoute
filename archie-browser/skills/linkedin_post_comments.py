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


# Comment extraction, anchored on server-driven-UI component keys (#5644).
#
# ROOT CAUSE (measured 2026-08-16, authenticated load of a post with 2 known comments):
# LinkedIn migrated the post-detail surface to its **server-driven UI** stack
# (`data-sdui-screen="com.linkedin.sdui.flagshipnav.feed.UpdateDetail"`), which emits
# HASHED css class names — `_18f99264`, `d6191816`, `_7f078b28`. A page-wide sweep found
# **zero** class tokens containing the substring "comment", so every one of the five
# class-based selectors this replaces matched an empty NodeList. The comment TEXT was
# present in the DOM the whole time (28-45 element matches for a known comment body).
#
# SHADOW DOM WAS A RED HERRING. The page has exactly ONE shadow host; the comments are in
# the light DOM. A previous pass diagnosed this as a shadow-boundary bug (by analogy to
# `linkedin_profile_view` #4612), ported that skill's piercing walk here, and still got 0 —
# because the walk was never the missing piece. The selectors were. F.O.R.G.E. then
# APPROVED that non-fix on the strength of this comment block describing it (KB #288929,
# task #5647), which is why this block now states what was MEASURED, not what was inferred.
#
# THE STABLE HOOK: SDUI names each comment node with a semantic, non-hashed attribute that
# also carries the comment URN, on both `componentkey` and `id`:
#     componentkey="replaceableComment_urn:li:comment:(urn:li:activity:<post>,<comment>)"
# The URN is parsed straight out of it — no separate data-id lookup, and it is exactly the
# URN the `?commentUrn=` deep-link needs. Body text is `[data-testid="expandable-text-box"]`.
# Both survive a css-hash rebuild; class names do not. Prefer attributes over classes here.
_JS_COMMENTS = r"""
(limit) => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  // LinkedIn renders names twice for a11y: a screen-reader copy plus an aria-hidden
  // visible copy. Plain textContent therefore returns "Kytran Katarn 1stKytran Katarn • 1st".
  // Prefer the aria-hidden subtree, which is the single visible rendering.
  const vis = (el) => {
    if (!el) return '';
    const a = el.querySelector('[aria-hidden="true"]');
    return clean(a ? a.textContent : el.textContent);
  };

  const NODE_SEL = '[componentkey^="replaceableComment_urn:li:comment:"],'
                 + '[id^="replaceableComment_urn:li:comment:"]';
  // Legacy (pre-SDUI) surfaces — group posts and older renders may still ship these.
  // Kept as a fallback so this skill does not break the moment it meets an unmigrated page.
  const LEGACY_SEL = 'article.comments-comment-entity, .comments-comment-item, '
                   + '[data-id*="comment"], .comments-comments-list__comment-item';

  let strategy = 'sdui_componentkey';
  let nodes = Array.from(document.querySelectorAll(NODE_SEL));
  if (!nodes.length) {
    nodes = Array.from(document.querySelectorAll(LEGACY_SEL));
    strategy = nodes.length ? 'legacy_class' : 'none';
  }

  const out = [];
  const seen = new Set();
  for (const node of nodes) {
    if (out.length >= limit) break;

    const key = node.getAttribute('componentkey') || node.getAttribute('id') || '';
    const m = key.match(/urn:li:comment:\([^)]*\)/);
    // Each comment renders TWO elements carrying the same key (an outer componentkey-only
    // wrapper and an inner id+componentkey node), so dedupe on the URN, not the element.
    let urn = m ? m[0] : (node.getAttribute('data-id') || node.getAttribute('data-urn') || '');

    // Author + headline live in the NAME anchor. There are two profile anchors per comment
    // and the first is the AVATAR, which contains no <p> — pick the first anchor that does.
    let anchor = null, ps = [];
    for (const a of node.querySelectorAll('a[href*="/in/"], a[href*="/company/"]')) {
      const q = a.querySelectorAll('p');
      if (q.length) { anchor = a; ps = q; break; }
      if (!anchor) anchor = a;
    }
    let author = ps.length ? vis(ps[0]) : '';
    author = author.replace(/\s*[•·]\s*(1st|2nd|3rd|Following|You)\b.*$/i, '').trim();
    if (!author) {
      // Fallback: the avatar's a11y label — "View <name>’s profile".
      const lbl = node.querySelector('[aria-label*="profile"], img[alt*="profile"]');
      const raw = lbl ? (lbl.getAttribute('aria-label') || lbl.getAttribute('alt') || '') : '';
      const mm = raw.match(/View (.+?)[’']s profile/);
      if (mm) author = mm[1].trim();
    }
    const headline = ps.length > 1 ? vis(ps[1]) : '';

    const bodyEl = node.querySelector('[data-testid="expandable-text-box"]')
                || node.querySelector('.comments-comment-item__main-content, .update-components-text');
    let text = bodyEl ? clean(bodyEl.textContent) : '';
    text = text.replace(/\s*[…\.]{1,3}\s*(see )?more\s*$/i, '').trim();

    let timestamp = '';
    for (const p of node.querySelectorAll('p, time')) {
      const t = clean(p.textContent);
      if (/^\d+\s*(s|m|h|d|w|mo|y|second|minute|hour|day|week|month|year)s?(\s+ago)?$/i.test(t)) {
        timestamp = t;
        break;
      }
    }

    // ⚠️ UNRELIABLE ON A PLAIN PERMALINK. Measured against a post whose reply is recorded
    // is_reply=true in `linkedin_comments`: the permalink renders parent and reply as
    // SIBLINGS at identical indentation (left: 317 for both) with identical URN shape, so
    // there is no structural signal to read. This check is correct on the `?commentUrn=`
    // thread view, where replies ARE nested — do not treat a false here as "not a reply".
    let is_reply = false;
    try {
      const parent = node.parentElement ? node.parentElement.closest(NODE_SEL) : null;
      is_reply = !!parent
        || !!node.closest('.comments-comment-item__nested-items, .comments-replies-list');
    } catch (e) {}

    if (!text && !author) continue;
    const dedupe = urn || (author + '|' + text.substring(0, 60));
    if (seen.has(dedupe)) continue;
    seen.add(dedupe);

    out.push({
      urn,
      author,
      headline: headline.substring(0, 160),
      text: text.substring(0, 1200),
      timestamp,
      is_reply,
      profile_url: anchor ? (anchor.getAttribute('href') || '').split('?')[0] : '',
      _strategy: strategy,
    });
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

    # The SDUI comment list is lazily mounted — it is NOT in the initial paint. Scrolling
    # is what triggers the mount, so this is load-bearing, not cosmetic. (#5644)
    try:
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

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

    # Belt-and-braces "see more" expansion — NOT load-bearing on current markup.
    # Measured 2026-08-16: a folded 1,000-char comment already ships its FULL text in the
    # DOM and the "…more" is only a visual clamp, so the extractor gets the whole body
    # without this. Kept because the clamp could become a real truncation, but bounded
    # hard (5 buttons × 1.2s) — an unbounded loop here costs ~50s of pure latency per read
    # for no measured gain, which is worse than the fold it would be guarding against.
    try:
        buttons = page.locator('[data-testid="expandable-text-button"]')
        for i in range(min(buttons.count(), 5)):
            try:
                buttons.nth(i).click(timeout=1200)
            except Exception:
                continue
        page.wait_for_timeout(500)
    except Exception:
        pass

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

    # Which selector strategy actually matched. This is the regression tripwire: the #5644
    # outage was invisible for weeks because a selector break and an empty thread produced
    # byte-identical output. 'none' means NEITHER selector family matched any node, which
    # is a markup change to fix — never a quiet "no comments".
    strategy = comments[0].get("_strategy") if comments else None
    for c in comments:
        c.pop("_strategy", None)

    result = {
        "success": not walled,
        "post_url": post_url,
        "final_url": page.url,
        "total": len(comments),
        "comments": comments,
        "strategy": strategy or "none",
        "screenshot_path": _screenshot(page, "post_comments"),
    }
    if walled:
        result["result"] = "auth_wall — session not logged in for this profile"
    elif not comments:
        result["result"] = (
            "no comments extracted — either a genuinely empty thread, or LinkedIn moved the "
            "markup again. Distinguish before assuming: search the page for a known comment "
            "body; if the TEXT is present but strategy=='none', the selectors broke. The SDUI "
            "hook is componentkey^='replaceableComment_urn:li:comment:' (see #5644)."
        )
    return result
