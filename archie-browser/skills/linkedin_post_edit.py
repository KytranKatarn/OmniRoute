"""LinkedIn post edit — edit a SINGLE published post by its permalink URL (#2600).

Companion to linkedin_delete (#4326): same navigate-by-permalink → ⋯ menu flow,
but clicks "Edit" and rewrites the post body via the share editor, then Saves.
Motivating case: a live post published with typos (e.g. the FR Québécois post
#1112) with no way to correct it in place.

Guards (mirrors linkedin_delete — editing the wrong post is a real risk):
  * ``post_url`` must be ONE string that is a real single-post permalink carrying
    a post id (feed/home/profile/company URLs are refused).
  * optional ``expect_contains`` — refuse unless the loaded post body contains this
    text, so you can confirm you are editing the RIGHT post before rewriting it.
  * ``dry_run`` (default False) — open the ⋯ menu → Edit → the editor, report the
    CURRENT text, and DO NOT save. Non-destructive way to verify the flow.

Honesty gate: after Save we require the edit dialog to actually CLOSE before
reporting success. LinkedIn's editor can silently no-op (the modal stays open with
no error) — so a still-open dialog is reported as a FAILURE, never a phantom success.
"""
import os
import re
from datetime import datetime

SKILL_NAME = "linkedin_post_edit"
PLATFORMS = ["linkedin"]
MUTATING = True

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# Same single-post guard as linkedin_delete: the URL must carry a post/activity id.
_POST_ID_RE = re.compile(
    r"(urn:li:(?:activity|ugcpost|share):\d+"
    r"|activity[:%\-]\d{6,}"
    r"|/posts/[^?\s]*\d{6,})",
    re.IGNORECASE,
)


def _screenshot(page, name):
    # Diagnostic only — non-fatal (bare page.screenshot() times out on LinkedIn
    # animations; 5s + animations disabled + swallow errors).
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def _editor_locator(page):
    """The share editor's contenteditable box, scoped to the open dialog."""
    for sel in (
        '[role="dialog"] [role="textbox"][contenteditable="true"]',
        '[role="dialog"] .ql-editor[contenteditable="true"]',
        '[role="dialog"] div[contenteditable="true"]',
    ):
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=6000)
            return loc
        except Exception:
            continue
    return None


def execute(page, params: dict) -> dict:
    raw_url = params.get("post_url")
    new_content = (params.get("new_content") or "").strip()
    expect_contains = (params.get("expect_contains") or "").strip()
    dry_run = bool(params.get("dry_run", False))

    # ── Guard 1: exactly one URL, as a string ────────────────────────────────
    if isinstance(raw_url, (list, tuple, set)):
        raise ValueError(
            "linkedin_post_edit edits ONE post at a time — pass a single post_url "
            "string, not a collection."
        )
    post_url = (raw_url or "").strip()
    if not post_url:
        raise ValueError("post_url is required for linkedin_post_edit")

    # ── Guard 2: must be a real single-post permalink ────────────────────────
    low = post_url.lower()
    if "linkedin.com/" not in low or not _POST_ID_RE.search(low):
        raise ValueError(
            f"post_url is not a single LinkedIn post permalink: {post_url!r}. "
            "Refusing to operate on feed / home / profile / company URLs."
        )

    # ── Guard 3: non-dry-run edits need the replacement text ─────────────────
    if not dry_run and not new_content:
        raise ValueError("new_content is required to edit the post (or pass dry_run=True)")

    page.goto(post_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "edit_before")

    # ── Guard 4 (optional): confirm we're on the RIGHT post ──────────────────
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
                f"Refusing to edit: post body does not contain expected text "
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

    # Click "Edit post" in the dropdown (prefer the specific label over bare "Edit").
    edit_clicked = False
    for attempt in [
        lambda: page.get_by_role("menuitem", name=re.compile(r"edit post", re.I)).first.click(timeout=6000),
        lambda: page.get_by_text(re.compile(r"^\s*Edit post\s*$", re.I)).first.click(timeout=5000),
        lambda: page.get_by_role("menuitem", name=re.compile(r"^\s*edit\s*$", re.I)).first.click(timeout=5000),
        lambda: page.locator('.feed-shared-control-menu__item:has-text("Edit")').first.click(timeout=5000),
    ]:
        try:
            attempt()
            edit_clicked = True
            break
        except Exception:
            continue
    if not edit_clicked:
        raise RuntimeError(
            "Could not find 'Edit post' in the control menu — the session may not be "
            "the post's author (you can only edit your own posts)."
        )
    page.wait_for_timeout(1500)

    editor = _editor_locator(page)
    if editor is None:
        raise RuntimeError("Edit menu clicked but the post editor did not open")
    _screenshot(page, "edit_editor")

    current_text = ""
    try:
        current_text = editor.inner_text(timeout=4000) or ""
    except Exception:
        pass

    # ── dry_run: report the current text, do NOT save ────────────────────────
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "result": "Opened the post editor — NOT saved (dry_run).",
            "post_url": post_url,
            "current_text": current_text[:800],
            "screenshot_path": _screenshot(page, "edit_dryrun"),
        }

    # Replace the body: focus, select-all, delete, type the corrected content.
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(400)
    editor.type(new_content, delay=15)
    page.wait_for_timeout(800)

    # Save (edit modal's primary button is "Save"; a couple of fallbacks).
    saved = False
    for attempt in [
        lambda: page.locator('[role="dialog"]')
        .get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I))
        .first.click(timeout=6000),
        lambda: page.locator('.artdeco-modal button:has-text("Save")').first.click(timeout=5000),
        lambda: page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).last.click(timeout=5000),
    ]:
        try:
            attempt()
            saved = True
            break
        except Exception:
            continue
    if not saved:
        raise RuntimeError("Filled the editor but could not click the 'Save' button")

    # ── Honesty gate: the edit dialog must actually CLOSE (LinkedIn can silently
    # no-op and leave the modal open with no error). Still-open = FAILURE. ─────
    committed = False
    try:
        page.locator('[role="dialog"]').first.wait_for(state="detached", timeout=9000)
        committed = True
    except Exception:
        committed = False

    if not committed:
        return {
            "success": False,
            "result": "Clicked Save but the edit dialog did not close — LinkedIn did "
            "not commit the edit (silent no-op). Post left unchanged.",
            "post_url": post_url,
            "screenshot_path": _screenshot(page, "edit_notcommitted"),
        }

    page.wait_for_timeout(1500)
    return {
        "success": True,
        "result": "Post edited",
        "post_url": post_url,
        "screenshot_path": _screenshot(page, "edit_done"),
    }
