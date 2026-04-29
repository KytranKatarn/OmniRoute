"""LinkedIn inbox — reads the messaging inbox and returns unread conversations."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_inbox"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    limit = int(params.get("limit", 10))
    unread_only = params.get("unread_only", False)

    page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "inbox_loaded")

    # Extract conversations via JS
    conversations = page.evaluate(f"""() => {{
        const threads = [];
        const items = document.querySelectorAll(
            '.msg-conversation-listitem, [data-test-id="message-listitem"], .msg-conversations-container__convo-item'
        );
        let count = 0;
        for (const item of items) {{
            if (count >= {limit}) break;

            // Name
            const nameEl = item.querySelector(
                '.msg-conversation-listitem__participant-names, ' +
                '.msg-conversation-card__participant-names, ' +
                '.t-16.t-black.t-bold'
            );
            const name = nameEl ? nameEl.textContent.trim() : '';

            // Last message
            const msgEl = item.querySelector(
                '.msg-conversation-card__message-snippet, ' +
                '.msg-conversation-listitem__message-snippet'
            );
            const last_message = msgEl ? msgEl.textContent.trim() : '';

            // Timestamp
            const timeEl = item.querySelector(
                'time, .msg-conversation-listitem__time-stamp, .msg-conversation-card__time-stamp'
            );
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';

            // Unread indicator
            const unreadEl = item.querySelector(
                '.msg-conversation-card__unread-count, .notification-badge, [class*="unread"]'
            );
            const is_unread = !!unreadEl || item.classList.contains('is-unread');

            if (name) {{
                threads.push({{
                    name,
                    last_message: last_message.substring(0, 200),
                    timestamp,
                    is_unread,
                    index: count
                }});
                count++;
            }}
        }}
        return threads;
    }}""")

    if unread_only:
        conversations = [c for c in conversations if c.get("is_unread")]

    return {
        "success": True,
        "total": len(conversations),
        "conversations": conversations,
        "screenshot_path": _screenshot(page, "inbox_result"),
    }
