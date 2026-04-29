"""LinkedIn feed — reads the home feed and returns recent posts."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_feed"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    limit = int(params.get("limit", 10))
    feed_url = params.get("feed_url", "https://www.linkedin.com/feed/")

    page.goto(feed_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Scroll to load more posts
    for _ in range(2):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1000)

    _screenshot(page, "feed_loaded")

    posts = page.evaluate(f"""() => {{
        const results = [];
        const cards = document.querySelectorAll(
            '.feed-shared-update-v2, .occludable-update, [data-urn*="activity"]'
        );
        let count = 0;
        for (const card of cards) {{
            if (count >= {limit}) break;

            // Author name
            const authorEl = card.querySelector(
                '.update-components-actor__name, .feed-shared-actor__name, .update-components-actor__title span[aria-hidden="true"]'
            );
            const author = authorEl ? authorEl.textContent.trim() : '';

            // Author title/company
            const titleEl = card.querySelector(
                '.update-components-actor__description, .feed-shared-actor__description'
            );
            const author_title = titleEl ? titleEl.textContent.trim() : '';

            // Post content
            const textEl = card.querySelector(
                '.feed-shared-update-v2__description, .update-components-text, .feed-shared-text__text-view'
            );
            const content = textEl ? textEl.textContent.trim().substring(0, 300) : '';

            // Post URL (urn or link)
            const urn = card.getAttribute('data-urn') || '';
            let post_url = '';
            const linkEl = card.querySelector('a[href*="feed/update"], a[href*="activity"]');
            if (linkEl) post_url = linkEl.href;
            else if (urn) post_url = 'https://www.linkedin.com/feed/update/' + urn;

            // Like count
            const likeEl = card.querySelector(
                '.social-counts-reactions__count, .social-counts-reactions, .reactions-count'
            );
            const likes = likeEl ? likeEl.textContent.trim() : '0';

            // Comment count
            const commentEl = card.querySelector(
                '.social-details-social-counts__comments, [aria-label*="comment"]'
            );
            const comments = commentEl ? commentEl.textContent.trim() : '0';

            // Timestamp
            const timeEl = card.querySelector('time, .update-components-actor__sub-description time');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';

            if (author && content) {{
                results.push({{ author, author_title, content, post_url, likes, comments, timestamp }});
                count++;
            }}
        }}
        return results;
    }}""")

    return {
        "success": True,
        "total": len(posts),
        "posts": posts,
        "screenshot_path": _screenshot(page, "feed_result"),
    }
