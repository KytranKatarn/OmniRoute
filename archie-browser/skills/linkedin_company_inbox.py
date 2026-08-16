"""LinkedIn company inbox — reads messages sent to the company page."""
import os
import sys
from datetime import datetime

_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
# Guard the insert (#5650): skill_runner._discover_skills() re-imports EVERY skill on
# EVERY execute(), so an unguarded insert added a duplicate path per skill per run —
# measured sys.path 6 -> 33 after only 3 discoveries in a long-lived container.
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_DIR)
from _linkedin_common import get_company_slug

SKILL_NAME = "linkedin_company_inbox"
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
    company_slug = get_company_slug(params)
    limit = int(params.get("limit", 10))

    # Navigate to company messaging via admin
    page.goto(f"https://www.linkedin.com/company/{company_slug}/admin/inbox/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "co_inbox_loaded")

    # If admin inbox doesn't load, try via messaging with page switcher
    page_text = ""
    try:
        page_text = page.locator("body").inner_text(timeout=2000)[:200]
    except Exception:
        pass

    if "isn't available" in page_text or "not found" in page_text.lower():
        # Try via main messaging → switch to company inbox
        page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        # Click the company page inbox in "Page inboxes" section
        for attempt in [
            lambda: page.get_by_text("Kytran Empowerment", exact=False).first.click(timeout=5000),
            lambda: page.locator('.msg-sidebar-page-inboxes a').first.click(timeout=5000),
            lambda: page.locator('[aria-label*="Kytran"]').first.click(timeout=5000),
        ]:
            try:
                attempt()
                page.wait_for_timeout(2000)
                break
            except Exception:
                continue
        _screenshot(page, "co_inbox_switched")

    conversations = page.evaluate(f"""() => {{
        const threads = [];
        const items = document.querySelectorAll(
            '.msg-conversation-listitem, .msg-conversation-card__participant-names'
        );
        let count = 0;
        for (const item of items) {{
            if (count >= {limit}) break;
            const nameEl = item.querySelector(
                '.msg-conversation-listitem__participant-names, .t-16.t-black.t-bold'
            );
            const name = nameEl ? nameEl.textContent.trim() : '';
            const msgEl = item.querySelector('.msg-conversation-card__message-snippet');
            const last_message = msgEl ? msgEl.textContent.trim() : '';
            const timeEl = item.querySelector('time');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';
            const is_unread = item.classList.contains('is-unread') ||
                              !!item.querySelector('.notification-badge');
            if (name) {{
                threads.push({{ name, last_message: last_message.substring(0, 200), timestamp, is_unread }});
                count++;
            }}
        }}
        return threads;
    }}""")

    return {
        "success": True,
        "company_slug": company_slug,
        "total": len(conversations),
        "conversations": conversations,
        "screenshot_path": _screenshot(page, "co_inbox_result"),
    }
