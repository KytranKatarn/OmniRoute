"""Meta developer portal navigation skill."""
import logging
import os
from datetime import datetime

SKILL_NAME = "meta_portal_setup"
PLATFORMS = ["facebook"]

logger = logging.getLogger(__name__)


def execute(page, params: dict) -> dict:
    action = params.get("action", "screenshot")  # default is "screenshot"
    screenshots_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{screenshots_dir}/meta_portal_{ts}.png"

    page.goto("https://developers.facebook.com/apps/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    try:
        page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
    except Exception:
        pass
    if action == "screenshot":
        return {
            "success": True,
            "result": "Screenshot of Meta developer portal captured",
            "screenshot_path": screenshot_path,
        }

    if action == "check_status":
        apps = page.locator(".app-item, ._5dz4").all_text_contents()
        return {
            "success": True,
            "result": f"Found {len(apps)} app(s) in Meta developer portal",
            "apps": apps,
            "screenshot_path": screenshot_path,
        }

    if action == "create_app":
        app_name = params.get("app_name", "").strip()
        if not app_name:
            raise ValueError("app_name is required for action=create_app")
        app_type = params.get("app_type", "business")
        _VALID_APP_TYPES = {"business", "consumer", "gaming"}
        if app_type not in _VALID_APP_TYPES:
            raise ValueError(f"app_type must be one of {sorted(_VALID_APP_TYPES)}, got: {app_type!r}")

        page.locator('a[href*="create_app"], button:text("Create App")').first.click(timeout=10000)
        page.wait_for_timeout(2000)
        type_btn = page.locator(f'[data-value="{app_type}"], label:has-text("{app_type.title()}")')
        if type_btn.count() > 0:
            type_btn.first.click(timeout=10000)
            page.wait_for_timeout(500)
        page.locator('input[name="app_display_name"], input[placeholder*="app name" i]').first.fill(app_name, timeout=10000)
        page.wait_for_timeout(500)
        page.locator('button:text("Create App"), button[type="submit"]').first.click(timeout=10000)
        page.wait_for_timeout(4000)
        try:
            page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
        except Exception:
            pass
        logger.info("meta_portal_setup: created app '%s'", app_name)
        return {
            "success": True,
            "result": f"Created Meta app: {app_name}",
            "screenshot_path": screenshot_path,
        }

    return {"success": False, "error": f"Unknown action: {action}"}
