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
import re
import time

logger = logging.getLogger("headed_tasks")

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
_SKILL_RE = re.compile(r"^[a-z0-9_]{2,64}$")

# KEEP IN SYNC with skill_runner._READ_ONLY_SKILLS (worker). Conservative
# default: an unknown/new skill is treated as MUTATING (live-test proven:
# linkedin_post declares no MUTATING flag — a default-False check let it
# through the deny_mutating guard).
_READ_ONLY_SKILLS = {
    "linkedin_feed", "linkedin_notifications", "linkedin_search", "linkedin_inbox",
    "linkedin_recent_activity", "linkedin_analytics", "linkedin_profile_view",
    "linkedin_post_comments", "linkedin_company_inbox", "session_probe",
}


def _is_mutating(skill_name, module):
    """Worker-parity semantics: explicit module-level MUTATING flag wins;
    otherwise everything NOT on the read-only allowlist is mutating."""
    flag = getattr(module, "MUTATING", None)
    if flag is not None:
        return bool(flag)
    return skill_name not in _READ_ONLY_SKILLS

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


def _load_skill(skill_name):
    """Worker-parity skill discovery (mirrors skill_runner._discover_skills):
    importlib each skills/*.py and match on the module-level SKILL_NAME attr
    (filename stem as the fallback name)."""
    import importlib.util
    from pathlib import Path

    for path in Path(SKILLS_DIR).glob("*.py"):
        if path.name == "__init__.py":
            continue
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            continue
        if getattr(mod, "SKILL_NAME", path.stem) == skill_name:
            return mod
    return None


def run_skill_headed(skill_name, params, agent_id=377, platform="linkedin", deny_mutating=False):
    """#4649 slice 2 — run ANY baked skill in the HEADED browser (Xvfb :99,
    same trusted profile + anti-detection recipe as the human noVNC login).

    deny_mutating: refuse skills flagged MUTATING at the module level —
    enforced HERE (where the flag lives) so the platform's hardened fallback
    can never accidentally double-fire a publish that half-landed headless.
    """
    started = time.time()
    if not _SKILL_RE.match(skill_name or ""):
        return {"success": False, "error": "invalid skill name"}
    mod = _load_skill(skill_name)
    if mod is None:
        return {"success": False, "error": f"unknown skill: {skill_name}"}
    mutating = _is_mutating(skill_name, mod)
    if deny_mutating and mutating:
        return {"success": False, "error": "mutating_fallback_denied", "_mutating": True, "_skill": skill_name}
    profile = f"/profiles/{int(agent_id)}-{platform}"
    if not os.path.isdir(profile) or not os.listdir(profile):
        return {"success": False, "error": f"profile_not_established: {profile}"}

    os.environ.setdefault("DISPLAY", ":99")
    from playwright.sync_api import sync_playwright

    result = None
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile,
            headless=False,
            args=_LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
            user_agent=_UA,
            viewport=None,
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                result = mod.execute(page, dict(params or {}))
            except Exception as exc:
                # a skill's own error (bad params, selector miss) is a normal
                # failed RESULT, not a 500 from the endpoint
                result = {"success": False, "error": f"skill_error: {type(exc).__name__}: {exc}"}
        finally:
            ctx.close()

    if not isinstance(result, dict):
        result = {"success": bool(result), "result": str(result)[:400]}
    result.setdefault("success", False)
    result["_headed"] = True
    result["_skill"] = skill_name
    result["_mutating"] = mutating
    result["_duration_ms"] = int((time.time() - started) * 1000)
    return result


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
