"""LinkedIn article — publishes a long-form article via LinkedIn's article editor."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_article"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    title = params.get("title", "").strip()
    body = params.get("body", "").strip()  # plain text or light markdown
    cover_image_path = params.get("cover_image_path", "").strip()

    if not title:
        raise ValueError("title is required for linkedin_article")
    if not body:
        raise ValueError("body is required for linkedin_article")

    # Navigate to article editor
    page.goto("https://www.linkedin.com/article/new/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _screenshot(page, "article_editor_loaded")

    # Cover image (optional)
    if cover_image_path and os.path.exists(cover_image_path):
        try:
            for btn in [
                lambda: page.get_by_role("button", name="Add cover image", exact=False).click(timeout=6000),
                lambda: page.locator('button[aria-label*="cover" i]').first.click(timeout=5000),
            ]:
                try:
                    btn()
                    page.wait_for_timeout(1000)
                    break
                except Exception:
                    continue

            file_input = page.locator('input[type="file"]').first
            file_input.wait_for(state="attached", timeout=6000)
            file_input.set_input_files(cover_image_path)
            page.wait_for_timeout(3000)

            for apply in [
                lambda: page.get_by_role("button", name="Apply", exact=True).click(timeout=5000),
                lambda: page.get_by_role("button", name="Done", exact=True).click(timeout=5000),
            ]:
                try:
                    apply()
                    page.wait_for_timeout(1000)
                    break
                except Exception:
                    continue
        except Exception as img_err:
            pass  # cover image optional — continue without it

    # Fill title
    for field in [
        lambda: page.get_by_placeholder("Headline", exact=False).fill(title, timeout=8000),
        lambda: page.locator('[data-placeholder*="Headline"], [data-placeholder*="title" i]').first.fill(title, timeout=6000),
        lambda: page.locator('.article-editor-title, .editor-title').first.fill(title, timeout=6000),
    ]:
        try:
            field()
            break
        except Exception:
            continue

    page.wait_for_timeout(500)

    # Fill body — click the body area and type
    for field in [
        lambda: page.get_by_placeholder("Write here. Add photos, links, videos and more.", exact=False).click(timeout=8000),
        lambda: page.locator('.article-editor-content .ql-editor, .editor-content').first.click(timeout=6000),
        lambda: page.locator('[data-placeholder*="Write here"]').first.click(timeout=6000),
    ]:
        try:
            field()
            break
        except Exception:
            continue

    page.wait_for_timeout(500)

    # Type body in chunks (articles can be long)
    chunk_size = 2000
    for i in range(0, len(body), chunk_size):
        chunk = body[i:i + chunk_size]
        page.keyboard.type(chunk, delay=10)
        page.wait_for_timeout(200)

    page.wait_for_timeout(1000)
    _screenshot(page, "article_filled")

    # Publish
    for pub_btn in [
        lambda: page.get_by_role("button", name="Publish", exact=True).click(timeout=10000),
        lambda: page.get_by_role("button", name="Publish article", exact=False).click(timeout=8000),
        lambda: page.locator('button:has-text("Publish")').last.click(timeout=8000),
    ]:
        try:
            pub_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(3000)
    _screenshot(page, "article_publish_confirm")

    # Confirm publish if a dialog appears
    for confirm in [
        lambda: page.get_by_role("button", name="Publish now", exact=False).click(timeout=5000),
        lambda: page.get_by_role("button", name="Confirm", exact=False).click(timeout=5000),
    ]:
        try:
            confirm()
            page.wait_for_timeout(3000)
            break
        except Exception:
            continue

    article_url = page.url
    return {
        "success": True,
        "result": f"Article published: {title[:60]}",
        "article_url": article_url,
        "screenshot_path": _screenshot(page, "article_done"),
    }
