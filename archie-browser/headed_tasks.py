"""Headed one-off tasks run inside the login sidecar (#4649 slice 1).

The task sidecar (archie_browser) is headless; some LinkedIn flows behave
differently or need the trusted headed context. This module runs SPECIFIC,
hardcoded tasks in a headed Chromium under the sidecar's permanent Xvfb :99,
using the same anti-detection launch recipe as login_browser.py.

First task: group_image_retry — weekly retry of the WTF group cover/logo
replace. ROOT CAUSE (KB #277261, network-captured 2026-07-02): the group
update PATCH (?heroImageUrn=) returns a silent HTTP 422 whenever the group
ALREADY has images — fresh-set works, replace is rejected server-side, and
LinkedIn's UI swallows the error. LinkedIn ships changes constantly, so we
retry weekly and report the PATCH status honestly each time.
"""

import logging
import os

logger = logging.getLogger("headed_tasks")

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--start-maximized",
    "--disable-blink-features=AutomationControlled",
]
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _open_edit_modal(page, group_id):
    page.goto(f"https://www.linkedin.com/groups/{group_id}/", wait_until="domcontentloaded")
    page.wait_for_timeout(4500)
    for make in [
        lambda: page.get_by_role("link", name="Edit group", exact=False).first.click(timeout=6000),
        lambda: page.get_by_role("button", name="Edit group", exact=False).first.click(timeout=5000),
        lambda: page.get_by_text("Edit group", exact=True).first.click(timeout=5000),
    ]:
        try:
            make()
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    return False


def _attempt_image(page, group_id, input_idx, path):
    """One modal session: upload one image, Apply in the editor, Save, and
    return the group-update PATCH status (0 = flow never reached Save)."""
    if not _open_edit_modal(page, group_id):
        return 0
    dlg = page.locator('[role="dialog"], .artdeco-modal').first
    try:
        dlg.locator('input[type="file"]').nth(input_idx).set_input_files(path)
        ap = page.get_by_role("button", name="Apply", exact=True).last
        ap.wait_for(state="visible", timeout=15000)
        page.wait_for_timeout(1200)
        ap.click(timeout=6000)
        page.wait_for_timeout(3500)
        with page.expect_response(
            lambda r: "voyagerGroupsDashGroups" in r.url and r.request.method == "POST",
            timeout=20000,
        ) as resp_info:
            page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000)
        status = resp_info.value.status
    except Exception as exc:
        logger.warning("group image attempt (input %s) failed: %s", input_idx, type(exc).__name__)
        status = 0
    # leave a clean page state for the next attempt
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)
        except Exception:
            break
    return status


def group_image_retry(group_id: str, banner_path: str, logo_path: str) -> dict:
    """Attempt cover (input 0) and logo (input 1) replaces in separate modal
    sessions; report each PATCH status. fixed=True only when BOTH commit."""
    os.environ.setdefault("DISPLAY", ":99")
    from playwright.sync_api import sync_playwright

    cover_status = logo_status = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            "/profiles/377-linkedin",
            headless=False,
            args=_LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
            user_agent=_UA,
            viewport=None,
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if banner_path:
                cover_status = _attempt_image(page, group_id, 0, banner_path)
            if logo_path:
                logo_status = _attempt_image(page, group_id, 1, logo_path)
        finally:
            ctx.close()

    fixed = (200 <= cover_status < 300) and (200 <= logo_status < 300)
    return {"cover_status": cover_status, "logo_status": logo_status, "fixed": fixed}
