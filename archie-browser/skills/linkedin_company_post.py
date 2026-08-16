"""LinkedIn company post — publishes a post AS the Kytran Empowerment Inc. organization page.

Same /feed/ + actor-switcher pattern as linkedin_creed_post.py (which was
verified live on 2026-05-04 via PR #539). Mirrors the pinned selector chain
documented in KB vault #263350.

Old approach: navigate /company/<slug>/admin/page-posts/published/ — this
auth-walls in archie_browser even when the session is valid for /feed/, and
has been failing every run today (10+ failures in linkedin_post_log). Task
#2598 root cause.

New approach: /feed/  →  share box  →  Post settings  →  Posting as  →
"Kytran Empowerment Inc." radio  →  Save  →  Done  →  fill  →  Post.
"""
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

SKILL_NAME = "linkedin_company_post"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# Display labels LinkedIn renders for the company page in the "Posting as"
# radio list. Order matters — first match wins. Verified via DOM probe on
# 2026-05-04: probe3 dialog [03] showed text='Kytran Empowerment Inc.'.
_COMPANY_PAGE_NAMES = [
    "Kytran Empowerment Inc.",
    "Kytran Empowerment Inc",
    "Kytran Empowerment",
    "KE Inc.",
    "KE Inc",
]


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


def _diagnostic_dump(page, label: str) -> dict:
    info: dict = {"label": label, "url": "", "title": "", "buttons": []}
    try:
        info["url"] = page.url
    except Exception:
        pass
    try:
        info["title"] = page.title()
    except Exception:
        pass
    try:
        btns = page.locator("button:visible").all()[:30]
        info["buttons"] = [(b.inner_text(timeout=500) or "").strip()[:60] for b in btns]
    except Exception:
        pass
    return info


def _dismiss_overlays(page) -> bool:
    """Dismiss LinkedIn interstitial modals (e.g. the 'Premium Company Page'
    upsell) that overlay the feed composer and block the share box — the #1 cause
    of 'share box not found'. Harmless when none is present."""
    for attempt in [
        lambda: page.locator(".artdeco-modal__dismiss").first.click(timeout=2000),
        lambda: page.locator('button[aria-label="Dismiss"]').first.click(timeout=2000),
        lambda: page.get_by_role("button", name="Dismiss").first.click(timeout=2000),
    ]:
        try:
            attempt()
            page.wait_for_timeout(600)
            return True
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    return False


def _open_share_box(page) -> bool:
    """Open the feed-level share-box composer (dismissing any interstitial modal
    that overlays it first)."""
    attempts = [
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.locator(".share-box-feed-entry__trigger").first.click(timeout=8000),
        lambda: page.locator('[class*="share-box"]').first.click(timeout=8000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=8000),
        lambda: page.locator('button:has-text("Start a post")').click(timeout=8000),
    ]

    def _try():
        for attempt in attempts:
            try:
                attempt()
                return True
            except Exception:
                continue
        return False

    _dismiss_overlays(page)
    if _try():
        return True
    # A modal may have appeared late — dismiss + retry once.
    _dismiss_overlays(page)
    return _try()


def _open_post_settings(page) -> bool:
    """Click the unified settings entry (shows current actor + audience)."""
    attempts = [
        lambda: page.locator(".share-unified-settings-entry-button").first.click(timeout=5000),
        lambda: page.locator("button.share-unified-settings-entry-button").first.click(timeout=5000),
    ]
    for attempt in attempts:
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def _open_actor_toggle(page) -> bool:
    """Inside Post settings, click the actor toggle to open page list."""
    attempts = [
        lambda: page.locator(".share-unified-settings-menu__actor-toggle").first.click(timeout=5000),
        lambda: page.locator('button[class*="actor-toggle"]').first.click(timeout=5000),
    ]
    for attempt in attempts:
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def _select_company_page(page) -> str | None:
    """Pick the Kytran Empowerment Inc. radio from the 'Posting as' list."""
    for name in _COMPANY_PAGE_NAMES:
        try:
            page.locator(
                '.sharing-shared-generic-list__item-button:has-text("{}")'.format(name)
            ).first.click(timeout=2500)
            return name
        except Exception:
            pass
        try:
            page.get_by_role("radio", name=name, exact=False).first.click(timeout=2500)
            return name
        except Exception:
            continue
    return None


def _click_settings_dialog_button(page, label: str) -> bool:
    """Click a footer button (Save / Done / Back) in the open settings dialog."""
    attempts = [
        lambda: page.locator(
            f'.share-box-footer__primary-btn:has-text("{label}")'
        ).first.click(timeout=4000),
        lambda: page.get_by_role("button", name=label, exact=True).first.click(timeout=4000),
    ]
    for attempt in attempts:
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def _capture_page_post_url(page, slug):
    # Best-effort, non-fatal: read the page's PUBLIC posts feed for the newest
    # post link. Never use /admin/ paths (auth-wall + drafts mixed with
    # published — KB mistake). Empty string on any failure.
    if not slug:
        return ""
    try:
        page.goto(
            f"https://www.linkedin.com/company/{slug}/posts/",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        page.wait_for_timeout(2500)
        href = (
            page.locator('a[href*="feed/update/"]').first.get_attribute(
                "href", timeout=4000
            )
            or ""
        )
        if "feed/update" in href:
            return href.split("?")[0]
    except Exception:
        pass
    return ""


def execute(page, params: dict) -> dict:
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    # company_slug is no longer used to navigate (the /admin/ route is broken),
    # but we keep it in the response for log-row continuity with old call sites.
    company_slug = get_company_slug(params)
    if not content:
        raise ValueError("content is required for linkedin_company_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    # 1. Land on /feed/.
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    _screenshot(page, "company_post_feed_landed")

    if "feed" not in page.url:
        diag = _diagnostic_dump(page, "feed_redirected")
        raise RuntimeError(f"Feed unreachable; landed on {page.url}. diagnostics={diag}")

    # 2. Open share box.
    if not _open_share_box(page):
        diag = _diagnostic_dump(page, "share_box_miss")
        _screenshot(page, "company_post_share_miss")
        raise RuntimeError(f"Could not find feed share box. diagnostics={diag}")
    page.wait_for_timeout(2500)
    _screenshot(page, "company_post_share_open")

    # 3. Open Post settings dialog.
    if not _open_post_settings(page):
        diag = _diagnostic_dump(page, "post_settings_miss")
        _screenshot(page, "company_post_settings_miss")
        raise RuntimeError(f"Could not open Post settings dialog. diagnostics={diag}")
    page.wait_for_timeout(2000)
    _screenshot(page, "company_post_settings_open")

    # 4. Open actor toggle.
    if not _open_actor_toggle(page):
        diag = _diagnostic_dump(page, "actor_toggle_miss")
        _screenshot(page, "company_post_actor_toggle_miss")
        raise RuntimeError(f"Could not open actor toggle. diagnostics={diag}")
    page.wait_for_timeout(2000)
    _screenshot(page, "company_post_actor_list")

    # 5. Pick Kytran Empowerment Inc. radio.
    matched = _select_company_page(page)
    if not matched:
        diag = _diagnostic_dump(page, "company_pick_miss")
        _screenshot(page, "company_post_pick_miss")
        raise RuntimeError(
            "Could not find Kytran Empowerment Inc. in actor list — admin "
            f"grant may have lapsed. diagnostics={diag}"
        )
    page.wait_for_timeout(800)
    _screenshot(page, f"company_post_picked_{matched.replace(' ', '_').replace('.', '')}")

    # 6. Save (closes Posting-as sheet).
    if not _click_settings_dialog_button(page, "Save"):
        diag = _diagnostic_dump(page, "save_miss")
        _screenshot(page, "company_post_save_miss")
        raise RuntimeError(f"Could not click Save in Posting-as sheet. diagnostics={diag}")
    page.wait_for_timeout(1500)

    # 7. Done (closes Post-settings dialog).
    if not _click_settings_dialog_button(page, "Done"):
        diag = _diagnostic_dump(page, "done_miss")
        _screenshot(page, "company_post_done_miss")
        raise RuntimeError(f"Could not click Done in Post-settings dialog. diagnostics={diag}")
    page.wait_for_timeout(1500)
    _screenshot(page, "company_post_settings_closed")

    # 8. Fill the editor.
    editor = None
    for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            editor = loc
            break
        except Exception:
            continue
    if editor is None:
        _screenshot(page, "company_post_editor_miss")
        raise RuntimeError("Editor not found after closing settings dialogs")

    editor.click(timeout=5000)
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(1000)
    _screenshot(page, "company_post_filled")

    if os.getenv("ARCHIE_LINKEDIN_DRY_RUN") == "1":
        return {
            "success": True,
            "result": f"DRY RUN — composed {len(content)} chars as {matched}, did not submit",
            "actor": matched,
            "company_slug": company_slug,
            "dry_run": True,
            "screenshot_path": _screenshot(page, "company_post_dryrun"),
        }

    # 9. Publish.
    posted = False
    for post_btn in [
        lambda: page.get_by_role("button", name="Post", exact=True).click(timeout=10000),
        lambda: page.locator('button:has-text("Post")').last.click(timeout=8000),
        lambda: page.locator(".share-actions__primary-action").first.click(timeout=8000),
    ]:
        try:
            post_btn()
            posted = True
            break
        except Exception:
            continue
    if not posted:
        _screenshot(page, "company_post_publish_miss")
        raise RuntimeError("Could not click Post button after composing")

    page.wait_for_timeout(4000)

    # Dismiss any follow-up modal.
    try:
        page.get_by_role("button", name="No thanks", exact=False).first.click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    final = _screenshot(page, "company_post_final")
    return {
        "success": True,
        "result": f"Posted {len(content)} characters as {matched} via /feed/ + actor switcher",
        "actor": matched,
        "company_slug": company_slug,
        "post_url": _capture_page_post_url(page, company_slug),
        "screenshot_path": final,
    }
