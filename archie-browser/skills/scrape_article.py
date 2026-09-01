"""Article scraper skill — fetches full article body text from a URL via Playwright.

No login required. Handles JS-rendered pages, paywalls that require JS, and
sites that block plain HTTP requests. Returns the extracted body text.
"""

SKILL_NAME = "scrape_article"
PLATFORMS = []  # No authentication needed


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
        const remove = ['script','style','nav','header','footer','aside',
                        '.ad','[class*="cookie"]','[id*="cookie"]',
                        '[class*="banner"]','[class*="popup"]','[class*="modal"]',
                        '[class*="newsletter"]','[class*="subscribe"]'];
        remove.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => el.remove());
        });
    }"""
    )

    # Try content selectors in priority order
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
        "body",
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
            if len(text) > 200:
                body = text[:8000]
                break
        except Exception:
            continue

    if body:
        return {"success": True, "body": body, "url": url, "chars": len(body)}

    return {"success": False, "error": "No content extracted — page may be paywalled or empty", "url": url}
