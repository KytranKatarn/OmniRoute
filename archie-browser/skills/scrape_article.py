"""Article scraper skill — fetches full article body text from a URL via Playwright.

No login required. Handles JS-rendered pages, paywalls that require JS, and
sites that block plain HTTP requests. Returns the extracted body text.
"""

import re

SKILL_NAME = "scrape_article"
PLATFORMS = []  # No authentication needed

# Vocabulary that appears in navigation furniture and never in article prose.
# Used to cut a recommendation rail off the end of an extracted body — see the
# truncation step in execute(). Anchored to line starts where possible so a
# sentence that merely mentions a duration is not mistaken for a rail.
_NAV_MARKER = re.compile(
    r"(?:^|\n)\s*(?:\d+\s+(?:seconds?|minutes?|mins?|hours?|days?)\s+ago"
    r"|\d+\s+min(?:ute)?s?\s+read"
    r"|Trending\b|Most Read\b|Related Stories\b|More From\b|Read Next\b"
    r"|Recommended for you\b|You may also like\b)",
    re.I,
)


def execute(page, params: dict) -> dict:
    url = params.get("url", "").strip()
    if not url:
        raise ValueError("url is required for scrape_article")

    page.set_extra_http_headers(
        {
            "Accept-Language": "en-CA,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as exc:
        return {"success": False, "error": f"Navigation failed: {exc}", "url": url}

    # Google News RSS URLs (news.google.com/rss/articles/CBM...) redirect to the
    # actual article via JS. Wait up to 8s for the redirect to complete.
    if "news.google.com" in page.url:
        try:
            page.wait_for_url(
                lambda u: "news.google.com" not in u and "google.com" not in u,
                timeout=8000,
            )
        except Exception:
            return {"success": False, "error": "Google News redirect did not complete", "url": url}

    # Brief wait for JS-rendered content
    page.wait_for_timeout(1500)

    # Remove noise elements
    page.evaluate(
        """() => {
        // ⚠️ Related-content rails are the big contaminant, and the original
        // list missed them entirely. SaltWire bled a car review and a
        // back-to-school listicle into a hockey story's body; 563 of 4,509
        // captured bodies (12.5%) carry "N hours ago" timestamps, which only
        // appear in navigation furniture, never in article prose.
        const remove = ['script','style','nav','header','footer','aside',
                        '.ad','[class*="cookie"]','[id*="cookie"]',
                        '[class*="banner"]','[class*="popup"]','[class*="modal"]',
                        '[class*="newsletter"]','[class*="subscribe"]',
                        '[class*="related"]','[id*="related"]',
                        '[class*="recommend"]','[class*="trending"]',
                        '[class*="most-read"]','[class*="mostread"]',
                        '[class*="sidebar"]','[id*="sidebar"]',
                        '[class*="promo"]','[class*="teaser"]',
                        '[class*="more-from"]','[class*="read-next"]',
                        '[class*="outbrain"]','[class*="taboola"]'];
        remove.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => el.remove());
        });
    }"""
    )

    # Try content selectors in priority order.
    #
    # ⚠️ "body" IS DELIBERATELY NOT IN THIS LIST. It was the last entry, and it
    # does not return the ARTICLE — it returns the PAGE: nav, rails, promos and
    # whatever other stories the publisher renders alongside. Measured on a
    # SaltWire hockey story, the captured body contained a car review and a
    # back-to-school listicle, and those sentences then surfaced as that
    # article's own content in the excerpt and in analysis.
    #
    # Returning NOTHING is the correct outcome when no article container is
    # found. A stub is honest — the page already says "full article content is
    # not available for this source" — whereas a page-dump is the WRONG
    # ARTICLE's text presented as this one's, which then feeds bias scoring,
    # fact-checking and the reader-facing excerpt. Absence beats a false
    # measurement; that principle is why signal_detected and content_type
    # exist, and it applies to the body itself.
    #
    # "#content" is kept: it is a content-region id, not the document root.
    selectors = [
        "article",
        "main",
        "[role='main']",
        ".article-body",
        ".story-body",
        ".post-content",
        ".entry-content",
        ".article-content",
        "#article-body",
        "#content",
    ]

    body = None
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            text = el.inner_text()
            # Collapse whitespace WITHIN a line, but keep the line breaks.
            #
            # This was `" ".join(text.split())`, which flattened the whole
            # article to a single line. inner_text() already reflects the page's
            # block structure as newlines, so that threw away every paragraph
            # boundary at capture time — unrecoverably, since only the flattened
            # string was stored. It went unnoticed while the page rendered a
            # 600-char excerpt; at 2,500 the same body is a wall of text.
            #
            # ⚠️ Forward-looking only. Bodies already captured hold zero
            # newlines and cannot be repaired without re-scraping.
            _lines = [" ".join(ln.split()) for ln in text.splitlines()]
            text = "\n\n".join(ln for ln in _lines if ln)

            # ⚠️ TRUNCATE AT THE FIRST NAVIGATION MARKER.
            #
            # Removing "body" from the ladder and stripping related/sidebar
            # classes fixed Financial Post but NOT SaltWire, whose rail is
            # lazy-loaded or shadow-rooted and so matches no static selector.
            # Chasing each publisher's DOM does not scale and silently rots.
            #
            # This is the generic form: a relative timestamp ("3 hours ago") or
            # a read-time badge is furniture vocabulary — it does not occur in
            # article prose but always heads a recommendation rail. Everything
            # from the first such marker onward belongs to the page, not the
            # article, so it is cut.
            #
            # Conservative by construction: it only ever REMOVES trailing text,
            # never adds or reorders, and if no marker is present the body is
            # untouched. A short article is honest; another article's text
            # presented as this one's is not.
            _nav = _NAV_MARKER.search(text)
            if _nav and _nav.start() > 200:
                text = text[: _nav.start()].rstrip()
            if len(text) > 200:
                body = text[:8000]
                break
        except Exception:
            continue

    if body:
        return {"success": True, "body": body, "url": url, "chars": len(body)}

    return {"success": False, "error": "No content extracted — page may be paywalled or empty", "url": url}
