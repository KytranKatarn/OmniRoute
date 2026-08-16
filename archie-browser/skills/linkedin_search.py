"""LinkedIn search — find people by keyword, title, company, or location."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_search"
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


# People-search extraction, anchored on the profile ANCHOR (#5649).
#
# ROOT CAUSE: LinkedIn moved search to its server-driven UI
# (`data-sdui-screen="com.linkedin.sdui.flagshipnav.search.SearchResultsPeople"`), which
# emits HASHED css class names. Measured 2026-08-16: `.entity-result__*` and
# `.reusable-search__result-container` matched ZERO elements, so this returned
# `success: True, results: []` on every query — indistinguishable from "no matches".
#
# ⚠️ componentkey is NOT the hook here, unlike the comment skills. `SearchResults<urn>`
# keys exist but sit on the Follow/Message BUTTONS, not the result cards — filtering
# nodes by them collapsed 10 results to 1. The stable anchor is the profile link that
# carries a <p> (the NAME link; the avatar link has none). Measured: 10 such anchors and
# 10 distinct hrefs on a 10-result page.
#
# The name anchor itself holds the whole card: <p>[0] name (+ degree), [1] headline,
# [2] location, [3] "Current: ...". Do NOT walk up to a parent for the headline — 4
# levels up starts bleeding into the NEXT result.
_JS_PEOPLE = r"""
(limit) => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  // LinkedIn renders names twice for a11y and the aria-hidden copy is normally the
  // visible one — but on cards carrying a Verified/Premium badge that subtree is EMPTY.
  // Fall back to the full textContent, or the name silently comes back blank.
  const vis = el => {
    if (!el) return '';
    const a = el.querySelector('[aria-hidden="true"]');
    const t = clean(a ? a.textContent : el.textContent);
    return t || clean(el.textContent);
  };
  const anchors = [...document.querySelectorAll('a[href*="/in/"]')]
      .filter(a => a.querySelectorAll('p').length);
  const out = [], seen = new Set();
  for (const a of anchors) {
    if (out.length >= limit) break;
    const url = (a.getAttribute('href') || '').split('?')[0];
    if (!url || seen.has(url)) continue;
    // ⚠️ DO NOT filter falsy entries out of this list. The <p> order IS the schema
    // (name / headline / location / "Current:"), and dropping an empty name shifts every
    // field up one — which silently wrote a HEADLINE into `name` and a LOCATION into
    // `title`, i.e. mislabelled rows into linkedin_outreach_queue rather than no rows.
    const ps = [...a.querySelectorAll('p')].map(vis);
    if (!ps.length) continue;
    let name = ps[0] || '', connection = '';
    const deg = name.match(/[•·]\s*(1st|2nd|3rd)\b/i);
    if (deg) connection = deg[1];
    name = name.replace(/\s*[•·]\s*(1st|2nd|3rd|Following|You)\b.*$/i, '').trim();
    // A card whose name cannot be read is SKIPPED, never back-filled from another field.
    if (!name) continue;
    seen.add(url);
    out.push({
      name,
      title: (ps[1] || '').slice(0, 220),      // key kept as `title` — signal_outreach_search reads it
      location: (ps[2] || '').slice(0, 120),
      profile_url: url,
      connection,
      _strategy: 'sdui_profile_anchor',
    });
  }
  return out;
}
"""

# Non-people searches (posts/companies/jobs) share the hashed-class problem. There is no
# single stable card key across those surfaces, so this takes the honest generic route:
# every result links somewhere, so anchor on the link and read its own text. Verified only
# for `people` — the other three types are UNVERIFIED and will report strategy so an empty
# result is not mistaken for "no matches".
_JS_GENERIC = r"""
(limit) => {
  const clean = s => (s||'').replace(/\s+/g,' ').trim();
  const sel = 'a[href*="/company/"], a[href*="/jobs/view/"], a[href*="/feed/update/"]';
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll(sel)) {
    if (out.length >= limit) break;
    const url = (a.getAttribute('href') || '').split('?')[0];
    const title = clean(a.innerText).split('\n')[0];
    if (!url || !title || seen.has(url)) continue;
    seen.add(url);
    out.push({title: title.slice(0,160), subtitle: '', url, _strategy: 'sdui_link_anchor'});
  }
  return out;
}
"""


def execute(page, params: dict) -> dict:
    query = params.get("query", "").strip()
    search_type = params.get("type", "people")  # people, posts, companies, jobs
    filters = params.get("filters", {})  # title, company, location, connection_degree
    limit = int(params.get("limit", 10))

    if not query:
        raise ValueError("query is required for linkedin_search")

    # Build search URL
    type_map = {"people": "PEOPLE", "posts": "CONTENT", "companies": "COMPANY", "jobs": "JOBS"}
    origin = type_map.get(search_type, "PEOPLE")
    search_url = f"https://www.linkedin.com/search/results/{search_type.lower()}/?keywords={query.replace(' ', '%20')}"

    # Append filters
    if filters.get("title"):
        search_url += f"&title={filters['title'].replace(' ', '%20')}"
    if filters.get("company"):
        search_url += f"&company={filters['company'].replace(' ', '%20')}"

    page.goto(search_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "search_loaded")

    # The SDUI result list is lazily mounted — scrolling is what materialises it.
    for _ in range(2):
        try:
            page.mouse.wheel(0, 1500)
        except Exception:
            pass
        page.wait_for_timeout(1100)

    if search_type == "people":
        results = page.evaluate(_JS_PEOPLE, limit)
    else:
        results = page.evaluate(_JS_GENERIC, limit)

    strategy = results[0].pop("_strategy", None) if results else None
    for r in results:
        r.pop("_strategy", None)

    body = ""
    try:
        body = (page.inner_text("body", timeout=3000) or "")[:3000].lower()
    except Exception:
        pass
    walled = ("sign in to view" in body) or ("join linkedin" in body) or ("authwall" in page.url.lower())

    out = {
        "success": not walled,
        "query": query,
        "type": search_type,
        "total": len(results),
        "results": results,
        "strategy": strategy or "none",
        "screenshot_path": _screenshot(page, "search_result"),
    }
    if walled:
        out["result"] = "auth_wall — session not logged in for this profile"
    elif not results:
        out["result"] = (
            "no results extracted — either a genuinely empty search, or LinkedIn moved the "
            "markup again. Distinguish before assuming: if the page shows names but "
            "strategy=='none', the selectors broke (see #5649)."
        )
    return out
