"""Generic web form fill skill — navigates to a URL and fills/clicks/selects fields."""
import logging
import os

SKILL_NAME = "web_form_fill"
PLATFORMS = []  # works on any site

logger = logging.getLogger(__name__)


def execute(page, params: dict) -> dict:
    url = params.get("url", "").strip()
    fields = params.get("fields", [])
    submit_selector = params.get("submit_selector", "")
    wait_ms = params.get("wait_ms", 2000)

    if not url:
        raise ValueError("url is required for web_form_fill")
    if not fields:
        raise ValueError("fields is required for web_form_fill")

    screenshots_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    screenshot_path = os.path.join(screenshots_dir, "web_form_fill.png")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)

    filled_count = 0
    failed_fields = []
    for field in fields:
        selector = field.get("selector", "")
        value = field.get("value", "")
        action = field.get("action", "fill")
        if not selector:
            continue
        try:
            element = page.locator(selector).first
            if action == "fill":
                element.fill(str(value), timeout=10000)
            elif action == "click":
                element.click(timeout=10000)
            elif action == "select":
                element.select_option(str(value), timeout=10000)
            filled_count += 1
        except Exception as exc:
            logger.debug("web_form_fill: field %s failed: %s", selector, type(exc).__name__)
            failed_fields.append(selector)

    submit_error = None
    if submit_selector:
        try:
            page.locator(submit_selector).first.click(timeout=10000)
            page.wait_for_timeout(params.get("wait_ms", 2000))
        except Exception as exc:
            submit_error = type(exc).__name__
            logger.warning("web_form_fill: submit click failed: %s", submit_error)

    page.screenshot(path=screenshot_path)

    return {
        "success": True,
        "result": f"Filled {filled_count}/{len(fields)} fields on {url}",
        "filled_count": filled_count,
        "failed_fields": failed_fields,
        "submit_error": submit_error,
        "screenshot_path": screenshot_path,
    }
