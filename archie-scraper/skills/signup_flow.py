"""Skill: signup_flow — Automate registration and capture result."""
import logging
from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    fields = params.get("fields") or {}
    submit_sel = params.get("submit_selector", "button[type=submit]")
    success_sel = params.get("success_selector")

    screenshots = []
    page.goto(url, wait_until="networkidle", timeout=30000)
    path = save_screenshot(job_id, "signup_form", page)
    screenshots.append(screenshot_entry("signup_form", path, "Signup form"))

    filled, errors = [], []
    for selector, value in fields.items():
        try:
            page.fill(selector, str(value))
            filled.append(selector)
        except Exception as exc:
            errors.append(f"{selector}: {exc}")

    try:
        btn = page.query_selector(submit_sel)
        if btn:
            btn.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        errors.append(f"Submit: {exc}")

    path = save_screenshot(job_id, "post_signup", page)
    screenshots.append(screenshot_entry("post_signup", path, "Post-signup state"))

    success = False
    if success_sel:
        try:
            page.wait_for_selector(success_sel, timeout=5000)
            success = True
        except Exception:
            pass

    findings = f"Filled {len(filled)}/{len(fields)} fields. " + (f"Errors: {'; '.join(errors)}" if errors else "No errors.")
    return {
        "data": {"fields_filled": filled, "errors": errors, "success": success, "final_url": page.url},
        "screenshots": screenshots, "network_log": [], "findings": findings, "auto_approve": False,
    }
