"""LinkedIn notifications — reads the notification bell and returns recent alerts."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_notifications"
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
    limit = int(params.get("limit", 15))
    unread_only = params.get("unread_only", False)

    page.goto("https://www.linkedin.com/notifications/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "notif_loaded")

    notifications = page.evaluate(f"""() => {{
        const items = [];
        const cards = document.querySelectorAll(
            '.nt-card, .notification-item, article.nt-card, li[data-urn]'
        );
        let count = 0;
        for (const card of cards) {{
            if (count >= {limit}) break;

            // Text content
            const textEl = card.querySelector(
                '.nt-card__text, .notification-item__text, p.t-14, .nt-card__headline'
            );
            const text = textEl ? textEl.textContent.trim() : '';
            // Full card text — headline above is often just "X commented on your
            // post"; the comment body lives elsewhere in the card. Needed to draft
            // a grounded reply.
            const full_text = (card.innerText || '').replace(/\s+/g, ' ').trim();

            // Timestamp
            const timeEl = card.querySelector('time, .nt-card__time-ago, span.t-12.t-black--light');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';

            // Is unread
            const is_unread = card.classList.contains('nt-card--unread') ||
                              card.querySelector('.nt-card__badge') !== null;

            // Link (post permalink — query stripped, back-compat)
            const linkEl = card.querySelector('a');
            const link = linkEl ? linkEl.href.split('?')[0] : '';

            // Comment deep-link — the FULL href incl. ?commentUrn= (lives in a
            // non-first <a>). Required for threaded replies: only this deep-link
            // renders the specific comment thread in the automated session.
            const _anchors = Array.from(card.querySelectorAll('a[href]')).map(a => a.href);
            const comment_url = _anchors.find(h => h.includes('commentUrn')) || '';

            // Type detection from text
            let type = 'other';
            const t = text.toLowerCase();
            if (t.includes('liked') || t.includes('reaction')) type = 'like';
            else if (t.includes('commented')) type = 'comment';
            else if (t.includes('connected') || t.includes('accepted')) type = 'connection';
            else if (t.includes('mentioned')) type = 'mention';
            else if (t.includes('shared')) type = 'share';
            else if (t.includes('message') || t.includes('messaged')) type = 'message';
            else if (t.includes('view') || t.includes('profile')) type = 'profile_view';
            else if (t.includes('followed')) type = 'follow';

            if (text) {{
                items.push({{ text: text.substring(0, 200), full_text: full_text.substring(0, 400), timestamp, is_unread, type, link, comment_url }});
                count++;
            }}
        }}
        return items;
    }}""")

    if unread_only:
        notifications = [n for n in notifications if n.get("is_unread")]

    # Group by type
    by_type = {}
    for n in notifications:
        t = n["type"]
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "success": True,
        "total": len(notifications),
        "unread": sum(1 for n in notifications if n.get("is_unread")),
        "by_type": by_type,
        "notifications": notifications,
        "screenshot_path": _screenshot(page, "notif_result"),
    }
