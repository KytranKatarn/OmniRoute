"""LinkedIn creed post — publishes a post AS the CREED AI organization page.

Selector chain pinned via DOM probe on 2026-05-04 (KB #263349):

  /feed/  →  share box  →  .share-unified-settings-entry-button
            →  "Post settings" dialog
            →  .share-unified-settings-menu__actor-toggle
            →  "Posting as" dialog (radio list)
            →  pick the "CREED AI" radio
            →  click "Save" (closes "Posting as")
            →  click "Done" (closes "Post settings")
            →  back at share modal: fill .ql-editor, click "Post"

The /admin/* path is NOT used — LinkedIn auth-walls admin URLs even when the
session is valid for /feed/ (task #2598). Posting via the actor switcher
sidesteps that auth wall entirely.

LinkedIn renamed the page "CREED AI" (not "C.R.E.E.D. Institute"). The
_CREED_PAGE_NAMES list keeps several variants in case the display label
changes; first hit wins.
"""
import os
from datetime import datetime

SKILL_NAME = "linkedin_creed_post"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# Display labels LinkedIn might render in the "Posting as" radio list.
# Order matters — first match wins. Keep both UPPER-CASE and dotted variants
# so a page rename doesn't silently break us.
_CREED_PAGE_NAMES = [
    "CREED AI",
    "Creed AI",
    "Creed-AI",
    "C.R.E.E.D. Institute",
    "C.R.E.E.D.",
    "Creed Institute",
    "Creed",
]


def _screenshot(page, name):
    # Diagnostic only — MUST NOT fail or hang a post. LinkedIn's company
    # composer animates continuously, so a default page.screenshot() never
    # gets a stable frame and times out at 30s, which falsely marked posts
    # 'failed' (and let one launch post submit-then-error). Short timeout +
    # animations disabled + non-fatal. (#3953 launch incident 2026-06-10)
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
    """Click the unified settings entry pill (shows current actor + audience)."""
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
    """Inside Post settings dialog, click the actor toggle to open page list."""
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


def _select_creed_page(page) -> str | None:
    """Pick the CREED AI radio from the 'Posting as' list. Returns matched label."""
    for name in _CREED_PAGE_NAMES:
        # The radio rows render with role=radio + class sharing-shared-generic-list__item-button
        # Locator with text= match (case-insensitive via has-text).
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
    if not content:
        raise ValueError("content is required for linkedin_creed_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    # 1. Land on /feed/.
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    _screenshot(page, "creed_post_feed_landed")

    if "feed" not in page.url:
        diag = _diagnostic_dump(page, "feed_redirected")
        raise RuntimeError(f"Feed unreachable; landed on {page.url}. diagnostics={diag}")

    # 2. Open share box.
    if not _open_share_box(page):
        diag = _diagnostic_dump(page, "share_box_miss")
        _screenshot(page, "creed_post_share_miss")
        raise RuntimeError(f"Could not find feed share box. diagnostics={diag}")
    page.wait_for_timeout(2500)
    _screenshot(page, "creed_post_share_open")

    # 3. Open Post settings dialog.
    if not _open_post_settings(page):
        diag = _diagnostic_dump(page, "post_settings_miss")
        _screenshot(page, "creed_post_settings_miss")
        raise RuntimeError(f"Could not open Post settings dialog. diagnostics={diag}")
    page.wait_for_timeout(2000)
    _screenshot(page, "creed_post_settings_open")

    # 4. Open actor toggle (page-list sub-sheet).
    if not _open_actor_toggle(page):
        diag = _diagnostic_dump(page, "actor_toggle_miss")
        _screenshot(page, "creed_post_actor_toggle_miss")
        raise RuntimeError(f"Could not open actor toggle. diagnostics={diag}")
    page.wait_for_timeout(2000)
    _screenshot(page, "creed_post_actor_list")

    # 5. Pick CREED AI radio.
    matched = _select_creed_page(page)
    if not matched:
        diag = _diagnostic_dump(page, "creed_pick_miss")
        _screenshot(page, "creed_post_pick_miss")
        raise RuntimeError(
            "Could not find CREED AI in actor list — page may be renamed or "
            f"super-admin grant lost. diagnostics={diag}"
        )
    page.wait_for_timeout(800)
    _screenshot(page, f"creed_post_picked_{matched.replace(' ', '_')}")

    # 6. Save (closes Posting-as sheet).
    if not _click_settings_dialog_button(page, "Save"):
        diag = _diagnostic_dump(page, "save_miss")
        _screenshot(page, "creed_post_save_miss")
        raise RuntimeError(f"Could not click Save in Posting-as sheet. diagnostics={diag}")
    page.wait_for_timeout(1500)

    # 7. Done (closes Post-settings dialog).
    if not _click_settings_dialog_button(page, "Done"):
        diag = _diagnostic_dump(page, "done_miss")
        _screenshot(page, "creed_post_done_miss")
        raise RuntimeError(f"Could not click Done in Post-settings dialog. diagnostics={diag}")
    page.wait_for_timeout(1500)
    _screenshot(page, "creed_post_settings_closed")

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
        _screenshot(page, "creed_post_editor_miss")
        raise RuntimeError("Editor not found after closing settings dialogs")

    editor.click(timeout=5000)
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(1000)
    _screenshot(page, "creed_post_filled")

    if os.getenv("ARCHIE_LINKEDIN_DRY_RUN") == "1":
        return {
            "success": True,
            "result": f"DRY RUN — composed {len(content)} chars as {matched}, did not submit",
            "actor": matched,
            "dry_run": True,
            "screenshot_path": _screenshot(page, "creed_post_dryrun"),
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
        _screenshot(page, "creed_post_publish_miss")
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

    final = _screenshot(page, "creed_post_final")
    return {
        "success": True,
        "result": f"Posted {len(content)} characters as {matched} via /feed/ + actor switcher",
        "actor": matched,
        "post_url": _capture_page_post_url(
            page, os.getenv("LINKEDIN_CREED_SLUG", "115977300")
        ),
        "screenshot_path": final,
    }
