"""LinkedIn delete — permanently delete a SINGLE post by its permalink URL (#4326).

Safety is the whole point of this skill — deletion is destructive and irreversible.
Hard guards against bulk / accidental deletion:
  * ``post_url`` must be ONE string (a list/tuple/set is rejected) AND a valid
    LinkedIn post/activity permalink that carries a post id — feed/home/profile
    URLs are refused so we can never delete "whatever is on screen".
  * optional ``expect_contains`` — refuse unless the loaded post body contains this
    text (verify you are deleting the RIGHT post, e.g. "Just as Expected").
  * ``dry_run`` (default False) — open the post's ⋯ menu + reach the Delete dialog
    but DO NOT confirm; report what *would* be deleted.
There is intentionally NO iteration / "delete all" path here.
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_delete"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# A post_url is only accepted if it points at a SPECIFIC post — i.e. it carries a
# post/activity id. This rejects /feed/, /in/<profile>, /company/<slug> and bare
# domains, which is the core anti-"bulk/wrong delete" guard.
_POST_ID_RE = re.compile(
    r"(urn:li:(?:activity|ugcpost|share):\d+"
    r"|activity[:%\-]\d{6,}"
    r"|/posts/[^?\s]*\d{6,})",
    re.IGNORECASE,
)


def _screenshot(page, name):
    # Diagnostic only — non-fatal (bare page.screenshot() can time out on
    # LinkedIn animations; 5s + animations disabled + swallow errors). Mirrors
    # the linkedin_first_comment pattern.
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def execute(page, params: dict) -> dict:
    raw_url = params.get("post_url")
    expect_contains = (params.get("expect_contains") or "").strip()
    dry_run = bool(params.get("dry_run", False))

    # ── Guard 1: exactly one URL, as a string (NO bulk delete) ───────────────
    if isinstance(raw_url, (list, tuple, set)):
        raise ValueError(
            "linkedin_delete deletes ONE post at a time — pass a single post_url "
            "string, not a collection. Bulk delete is intentionally unsupported."
        )
    post_url = (raw_url or "").strip()
    if not post_url:
        raise ValueError("post_url is required for linkedin_delete")

    # ── Guard 2: must be a real single-post permalink (carries a post id) ─────
    low = post_url.lower()
    if "linkedin.com/" not in low or not _POST_ID_RE.search(low):
        raise ValueError(
            f"post_url is not a single LinkedIn post permalink: {post_url!r}. "
            "Refusing to operate on feed / home / profile / company URLs."
        )

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "delete_before")

    # ── Guard 3 (optional): confirm we're on the RIGHT post ──────────────────
    if expect_contains:
        body_text = ""
        for getter in (
            lambda: page.locator("main").inner_text(timeout=8000),
            lambda: page.content(),
        ):
            try:
                body_text = getter() or ""
                if body_text:
                    break
            except Exception:
                continue
        if expect_contains.lower() not in body_text.lower():
            raise RuntimeError(
                f"Refusing to delete: post body does not contain expected text "
                f"{expect_contains!r}. Wrong post, or the post did not load."
            )

    # Open the post's control (⋯ / "more actions") menu.
    opened = False
    for attempt in [
        lambda: page.get_by_role(
            "button", name=re.compile("control menu|more actions|open options", re.I)
        ).first.click(timeout=8000),
        lambda: page.locator('button[aria-label*="control menu" i]').first.click(timeout=6000),
        lambda: page.locator('button[aria-label*="more actions" i]').first.click(timeout=6000),
        lambda: page.locator(".feed-shared-control-menu__trigger").first.click(timeout=6000),
    ]:
        try:
            attempt()
            opened = True
            break
        except Exception:
            continue
    if not opened:
        raise RuntimeError("Could not open the post control (⋯) menu — wrong post layout or not the author")
    page.wait_for_timeout(1200)

    # Click "Delete post" in the dropdown.
    delete_clicked = False
    for attempt in [
        lambda: page.get_by_role("menuitem", name=re.compile("delete post|delete", re.I)).first.click(timeout=6000),
        lambda: page.get_by_text(re.compile(r"^\s*Delete post\s*$", re.I)).first.click(timeout=6000),
        lambda: page.locator('div[role="button"]:has-text("Delete post")').first.click(timeout=5000),
        lambda: page.locator('.feed-shared-control-menu__item:has-text("Delete")').first.click(timeout=5000),
    ]:
        try:
            attempt()
            delete_clicked = True
            break
        except Exception:
            continue
    if not delete_clicked:
        raise RuntimeError(
            "Could not find 'Delete post' in the control menu — the session may not "
            "be the post's author (you can only delete your own posts)."
        )
    page.wait_for_timeout(1200)
    _screenshot(page, "delete_dialog")

    # ── dry_run: stop at the confirmation dialog, do NOT delete ──────────────
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "result": "Reached the Delete confirmation dialog — NOT confirmed (dry_run).",
            "post_url": post_url,
            "screenshot_path": _screenshot(page, "delete_dryrun"),
        }

    # Confirm in the modal (the confirm button is itself labelled "Delete").
    confirmed = False
    for attempt in [
        lambda: page.locator('[role="dialog"]')
        .get_by_role("button", name=re.compile(r"^\s*Delete\s*$", re.I))
        .first.click(timeout=6000),
        lambda: page.locator('.artdeco-modal button:has-text("Delete")').first.click(timeout=5000),
        lambda: page.get_by_role("button", name=re.compile(r"^\s*Delete\s*$", re.I)).last.click(timeout=5000),
    ]:
        try:
            attempt()
            confirmed = True
            break
        except Exception:
            continue
    if not confirmed:
        raise RuntimeError("Reached the delete dialog but could not click the final 'Delete' confirm button")

    page.wait_for_timeout(2500)
    return {
        "success": True,
        "result": "Post deleted",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "delete_done"),
    }
