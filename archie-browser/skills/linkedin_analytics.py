"""LinkedIn analytics — reads profile and post performance metrics."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_analytics"
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


# Profile analytics, read from the analytics LINKS (#5649).
#
# ROOT CAUSE: two independent faults, both silent.
#   1. The profile moved to server-driven UI
#      (`data-sdui-screen="com.linkedin.sdui.flagshipnav.profile.Profile"`) with HASHED
#      css classes, so `.analytics-module`, `.artdeco-stat`, `.pv-top-card--list` and
#      `.pv-profile-section__analytics-results` all matched zero.
#   2. The href selectors that WOULD have survived a class rename were pointed at URLs
#      LinkedIn no longer uses: `a[href*="profileViewers"]`, `[href*="postImpressions"]`
#      and `[href*="searchAppearances"]` each matched ZERO (measured 2026-08-16). The
#      analytics links now live under `/analytics/...`.
# Result: `analytics: {}` with `success: True` on every run.
#
# The numbers were reachable the whole time — `a[href*="/analytics/"]` matched 14 and
# `a[href*="follower"]` matched 2, carrying text like "1,007 profile views" and
# "838 followers".
#
# ⚠️ Every stat renders TWICE (LinkedIn's a11y duplicate), so dedupe by href or each
# value is counted twice.
_JS_PROFILE_ANALYTICS = r"""
() => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  // href fragment -> canonical key. Keeps the output stable even if the visible label
  // is reworded, and is what makes this resilient to the next copy change.
  const MAP = [
    ['/analytics/profile-view',   'profile_views'],
    ['/analytics/creator/conten', 'post_impressions'],
    ['/analytics/search-app',     'search_appearances'],
    ['/feed/followers',           'followers'],
  ];
  const data = {}, items = [], seenHref = new Set();
  for (const a of document.querySelectorAll('a[href*="/analytics/"], a[href*="follower"]')) {
    const href = (a.getAttribute('href') || '').split('?')[0];
    const txt = clean(a.innerText);
    if (!href || !txt || seenHref.has(href)) continue;
    // "1,007 profile views Discover who’s viewed your profile." -> value + label
    const m = txt.match(/^([\d,\.]+\s*[KM]?)\s+(.+)$/);
    if (!m) continue;
    seenHref.add(href);
    const value = m[1].trim();
    const label = m[2].slice(0, 60);
    items.push({value, label, href});
    for (const [frag, key] of MAP) {
      if (href.includes(frag) && !(key in data)) data[key] = value;
    }
  }
  // `items` is kept so a NEW stat LinkedIn adds is still visible even though no
  // canonical key maps to it — an unmapped stat should surface, not vanish.
  data.items = items;
  data._strategy = items.length ? 'sdui_analytics_links' : 'none';
  return data;
}
"""


# Creator post analytics (mode='posts'), rebuilt on the SDUI module keys (#5649).
#
# MEASURED 2026-08-16 on /analytics/creator/content/ — the old table scrape could never
# have worked, and not merely because of renamed classes:
#     .analytics-table__row            -> 0
#     tr[data-test-analytics-table-row]-> 0
#     table / tr / td                  -> 0 / 0 / 0
# There is NO TABLE on the page at all, so the original code iterated `td` cells that do
# not exist. LinkedIn rebuilt this surface out of SDUI modules instead:
#     [componentkey*="FeedType_CREATOR_ANALYTICS"]  -> the top-post cards
#     [componentkey="topPostFeature"]               -> "1K impressions • 3 engagements ..."
#     [componentkey="impressionsBreakdownCA"]       -> "In-network 16% Out-of-network 84%"
#     [componentkey="membersReachedFeatureCA"]      -> reach summary
#
# Per-card impression counts are NOT exposed on this view — only the top post carries
# metrics — so `impressions`/`engagements` stay EMPTY on the other cards rather than
# being invented. The legacy table branch is retained purely as a fallback in case the
# surface is served un-migrated somewhere.
_JS_POST_ANALYTICS = r"""
() => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  const metric = (txt, word) => {
    const m = clean(txt).match(new RegExp('([\\d.,]+\\s*[KM]?)\\s+' + word, 'i'));
    return m ? m[1].trim() : '';
  };
  const posts = [];
  let strategy = 'sdui_creator_cards';

  for (const c of document.querySelectorAll('[componentkey*="FeedType_CREATOR_ANALYTICS"]')) {
    const t = clean(c.innerText).replace(/^Feed post\s*/i, '');
    if (!t) continue;
    posts.push({
      post: t.slice(0, 200),
      impressions: metric(c.innerText, 'impressions'),
      engagements: metric(c.innerText, 'engagements'),
    });
    if (posts.length >= 10) break;
  }

  if (!posts.length) {
    // Legacy fallback — see the note above; measured absent on the live surface.
    for (const row of document.querySelectorAll('.analytics-table__row, tr[data-test-analytics-table-row]')) {
      const cells = row.querySelectorAll('td');
      if (cells.length < 3) continue;
      posts.push({
        post: clean(cells[0].textContent).slice(0, 200),
        impressions: clean(cells[1].textContent),
        engagements: clean(cells[2].textContent),
      });
      if (posts.length >= 10) break;
    }
    strategy = posts.length ? 'legacy_table' : 'none';
  }

  const grab = k => {
    const el = document.querySelector('[componentkey="' + k + '"]');
    return el ? clean(el.innerText).slice(0, 200) : '';
  };
  const topRaw = grab('topPostFeature');

  return {
    posts,
    top_post: topRaw ? {
      impressions: metric(topRaw, 'impressions'),
      engagements: metric(topRaw, 'engagements'),
      post: topRaw.replace(/^.*?Feed post\s*/i, '').slice(0, 200),
    } : null,
    impressions_breakdown: grab('impressionsBreakdownCA'),
    members_reached: grab('membersReachedFeatureCA'),
    _strategy: strategy,
  };
}
"""


def execute(page, params: dict) -> dict:
    mode = params.get("mode", "profile")  # profile or posts

    if mode == "posts":
        page.goto("https://www.linkedin.com/analytics/creator/content/?metricType=IMPRESSIONS&timeRange=past_28_days", wait_until="domcontentloaded")
    else:
        page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    # SDUI mounts modules lazily — both surfaces need a scroll before the stats/cards
    # are in the DOM at all.
    for _ in range(3):
        try:
            page.mouse.wheel(0, 1400)
        except Exception:
            pass
        page.wait_for_timeout(1000)
    _screenshot(page, "analytics_loaded")

    if mode == "profile":
        analytics = page.evaluate(_JS_PROFILE_ANALYTICS)
    else:
        analytics = page.evaluate(_JS_POST_ANALYTICS)

    strategy = analytics.pop("_strategy", None) if isinstance(analytics, dict) else None

    body = ""
    try:
        body = (page.inner_text("body", timeout=3000) or "")[:3000].lower()
    except Exception:
        pass
    walled = ("sign in to view" in body) or ("join linkedin" in body) or ("authwall" in page.url.lower())

    out = {
        "success": not walled,
        "mode": mode,
        "analytics": analytics,
        # Never assert a strategy the extractor did not actually report — that is the
        # same dishonest-status shape this PR exists to remove.
        "strategy": strategy or "none",
        "screenshot_path": _screenshot(page, "analytics_result"),
    }
    if walled:
        out["result"] = "auth_wall — session not logged in for this profile"
    elif mode == "profile" and not analytics.get("items"):
        out["result"] = (
            "no analytics extracted — LinkedIn moved the markup again. The stats live on "
            "links: check a[href*='/analytics/'] and a[href*='follower'] (see #5649)."
        )
    elif mode != "profile" and not analytics.get("posts"):
        out["result"] = (
            "no post analytics extracted — LinkedIn moved the markup again. This surface "
            "has NO table; the data is in SDUI modules: check "
            "[componentkey*='FeedType_CREATOR_ANALYTICS'] and [componentkey='topPostFeature'] "
            "(see #5649)."
        )
    return out
