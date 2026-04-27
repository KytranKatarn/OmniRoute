"""Meta developer portal navigation skill."""
SKILL_NAME = "meta_portal_setup"
PLATFORMS = ["facebook"]


def execute(page, params: dict) -> dict:
    action = params.get("action", "list_apps")
    page.goto("https://developers.facebook.com/apps/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    screenshot_path = f"/tmp/meta_portal_{action}.png"

    if action == "list_apps":
        page.screenshot(path=screenshot_path)
        app_elements = page.locator('[data-testid="app-list-item"], .app-name').all()
        apps = [el.text_content().strip() for el in app_elements if el.text_content()]
        return {"success": True, "action": "list_apps", "apps": apps, "screenshot_path": screenshot_path}

    elif action == "check_products":
        app_id = params.get("app_id", "")
        if not app_id:
            raise ValueError("app_id required for check_products")
        page.goto(f"https://developers.facebook.com/apps/{app_id}/settings/basic/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        page.screenshot(path=screenshot_path)
        return {"success": True, "action": "check_products", "app_id": app_id, "screenshot_path": screenshot_path}

    else:
        raise ValueError(f"Unknown action: {action}")
