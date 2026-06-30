"""LinkedIn GROUP post — publishes a post INTO a LinkedIn group's feed.

A LinkedIn *group* is neither a personal profile nor a company page: a member
posts INTO the group from the group page. There is no actor-switcher (you post
as yourself, the member). So this is the personal-post pattern
(linkedin_post.py) re-pointed at the group URL — open the in-group share box →
fill → Post → verify — plus two group-specific guards:

  1. MEMBERSHIP: if the running identity is not a member, the group page shows
     a Join / Ask-to-join affordance and NO composer. We detect that and raise a
     clear, honest error instead of silently falling back to the personal feed.
  2. AUDIENCE: the in-group "Start a post" composer is pre-scoped to the group.
     We capture the composer's audience label during dry-run so a human can
     confirm it targets the group before any real post is published.

Verify-before-success (honesty gate, mirrors #1805): success is returned ONLY
after the Post click lands; every failure path raises BEFORE any post exists.

Params: group_id (required), content (required), hashtags (list, optional),
dry_run (bool, optional — compose + diagnostics, do NOT submit).
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_group_post"
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
    """Dismiss LinkedIn interstitial modals that overlay the composer — the #1
    cause of 'share box not found'. Harmless when none is present."""
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


def _membership_blocker(page) -> str | None:
    """Return the text of a group-join affordance if the identity is NOT a posting
    member, else None. Only checked when the composer is ABSENT — and scoped to
    specific CTAs ('Ask to join' / 'Request to join' / 'Pending'). We deliberately
    do NOT match a bare 'Join', because the recommended-groups sidebar renders
    'Join <other group>' buttons that falsely trip a naive membership check."""
    for name in ("Ask to join", "Request to join", "Pending"):
        try:
            loc = page.get_by_role("button", name=name, exact=False).first
            if loc.is_visible(timeout=1500):
                return name
        except Exception:
            continue
    # Some group states render the join CTA as a link.
    try:
        loc = page.get_by_text("Ask to join", exact=False).first
        if loc.is_visible(timeout=1000):
            return "Ask to join"
    except Exception:
        pass
    return None


def _open_share_box(page) -> bool:
    """Open the in-group share-box composer (dismissing any interstitial modal
    first). On a group page the composer is pre-scoped to the group."""
    attempts = [
        # Group-specific composer trigger (verified live 2026-06-30): the in-group
        # share box reads "Start a post in this group". Try it first.
        lambda: page.get_by_text("Start a post in this group", exact=False).first.click(timeout=8000),
        lambda: page.locator('button:has-text("Start a post in this group")').first.click(timeout=8000),
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.locator(".share-box-feed-entry__trigger").first.click(timeout=8000),
        lambda: page.locator('[class*="share-box"]').first.click(timeout=8000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=8000),
        lambda: page.locator('button:has-text("Start a post")').click(timeout=8000),
        # Group-specific affordance some layouts render before the share box.
        lambda: page.get_by_role("button", name="Post", exact=False).first.click(timeout=4000),
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
    _dismiss_overlays(page)
    return _try()


def _composer_audience(page) -> str:
    """Best-effort read of the composer's audience/scope label so a human can
    confirm the post targets the group (not the personal feed). Non-fatal."""
    for sel in (
        ".share-unified-settings-entry-button",
        '[class*="share-actor"]',
        '[class*="audience"]',
    ):
        try:
            txt = (page.locator(sel).first.inner_text(timeout=2000) or "").strip()
            if txt:
                return txt[:120]
        except Exception:
            continue
    return ""


def _find_editor(page):
    for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            return loc
        except Exception:
            continue
    return None


def _capture_group_post_url(page, group_id) -> str:
    """Best-effort, non-fatal: re-read the group feed and return the newest
    post permalink (our just-published item floats to the top). Empty on
    failure."""
    try:
        page.goto(
            f"https://www.linkedin.com/groups/{group_id}/",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        page.wait_for_timeout(2500)
        _dismiss_overlays(page)
        m = re.search(r"urn:li:activity:\d+", page.content() or "")
        if m:
            return f"https://www.linkedin.com/feed/update/{m.group(0)}/"
    except Exception:
        pass
    return ""


def execute(page, params: dict) -> dict:
    content = (params.get("content") or "").strip()
    hashtags = params.get("hashtags", [])
    group_id = str(
        params.get("group_id") or os.getenv("LINKEDIN_WTF_GROUP_ID", "")
    ).strip()
    dry_run = bool(params.get("dry_run")) or os.getenv("ARCHIE_LINKEDIN_DRY_RUN") == "1"

    if not group_id:
        raise ValueError("group_id is required for linkedin_group_post")
    if not content:
        raise ValueError("content is required for linkedin_group_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    group_url = f"https://www.linkedin.com/groups/{group_id}/"

    # 1. Land on the group page.
    page.goto(group_url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    _screenshot(page, "group_post_landed")

    if f"groups/{group_id}" not in page.url:
        diag = _diagnostic_dump(page, "group_redirected")
        raise RuntimeError(
            f"Group page unreachable; landed on {page.url}. diagnostics={diag}"
        )

    # 2. Open the in-group share box. The composer ("Start a post in this group")
    # is the GROUND TRUTH for "can post" — a non-member simply has no composer. We
    # do NOT pre-check for a "Join" button: recommended-groups sidebars render
    # their own "Join <other group>" buttons that falsely trip a naive check
    # (observed live 2026-06-30 — the WTF group page surfaced a sidebar "Join Power
    # BI…"). Only if the composer is absent do we run the scoped membership probe.
    if not _open_share_box(page):
        blocker = _membership_blocker(page)
        diag = _diagnostic_dump(page, "share_box_miss")
        _screenshot(page, "group_post_share_miss")
        if blocker:
            raise RuntimeError(
                f"Cannot post — the running identity is not a posting member of "
                f"group {group_id} (saw '{blocker}'). Join/approve membership first. "
                f"diagnostics={diag}"
            )
        raise RuntimeError(
            f"Could not find the group share box. diagnostics={diag}"
        )
    page.wait_for_timeout(2500)
    audience = _composer_audience(page)
    _screenshot(page, "group_post_share_open")

    # 4. Fill the editor.
    editor = _find_editor(page)
    if editor is None:
        diag = _diagnostic_dump(page, "editor_miss")
        _screenshot(page, "group_post_editor_miss")
        raise RuntimeError(f"Editor not found after opening share box. diagnostics={diag}")

    editor.click(timeout=5000)
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(1000)
    _screenshot(page, "group_post_filled")

    if dry_run:
        return {
            "success": True,
            "result": (
                f"DRY RUN — composed {len(content)} chars for group {group_id}; "
                f"audience='{audience or 'unknown'}'; did NOT submit"
            ),
            "group_id": group_id,
            "audience": audience,
            "dry_run": True,
            "screenshot_path": _screenshot(page, "group_post_dryrun"),
        }

    # 5. Publish.
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
        _screenshot(page, "group_post_publish_miss")
        raise RuntimeError("Could not click Post button after composing group post")

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

    final = _screenshot(page, "group_post_final")
    return {
        "success": True,
        "result": f"Posted {len(content)} characters into group {group_id}",
        "group_id": group_id,
        "audience": audience,
        "post_url": _capture_group_post_url(page, group_id),
        "screenshot_path": final,
    }
