"""Skill: login_test — Test auth flow, capture all states."""
import logging
from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    username_sel = params.get("username_selector", "input[type=email],input[name=email],input[name=username]")
    password_sel = params.get("password_selector", "input[type=password]")
    submit_sel = params.get("submit_selector", "button[type=submit]")
    expected = params.get("expected_redirect", "")

    screenshots = []
    findings_parts = []

    page.goto(url, wait_until="networkidle", timeout=30000)
    path = save_screenshot(job_id, "login_form", page)
    screenshots.append(screenshot_entry("login_form", path, "Login form"))

    try:
        page.fill(username_sel, params.get("username", ""))
        page.fill(password_sel, params.get("password", ""))
        path = save_screenshot(job_id, "login_filled", page)
        screenshots.append(screenshot_entry("login_filled", path, "Credentials filled"))
        btn = page.query_selector(submit_sel)
        if btn:
            btn.click()
        else:
            page.press(password_sel, "Enter")
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        findings_parts.append(f"Submit error: {exc}")

    path = save_screenshot(job_id, "post_login", page)
    screenshots.append(screenshot_entry("post_login", path, "Post-login state"))
    final_url = page.url
    success = bool(expected) and expected in final_url
    findings_parts.append(f"Final URL: {final_url}")
    if expected:
        findings_parts.append(f"Expected redirect '{expected}': {'ok' if success else 'not found'}")

    return {
        "data": {"final_url": final_url, "login_success": success, "expected_redirect": expected},
        "screenshots": screenshots, "network_log": [], "findings": "\n".join(findings_parts), "auto_approve": False,
    }
