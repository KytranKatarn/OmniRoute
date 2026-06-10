"""Twitter/X post skill — publishes a tweet to X (formerly Twitter)."""
import os

SKILL_NAME = "twitter_post"
PLATFORMS = ["twitter"]


def execute(page, params: dict) -> dict:
    content = params.get("content", "").strip()
    if not content:
        raise ValueError("content is required for twitter_post")
    if len(content) > 280:
        raise ValueError(f"content exceeds 280 characters ({len(content)} chars)")

    screenshots_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    screenshot_path = os.path.join(screenshots_dir, "twitter_post.png")

    page.goto("https://x.com/home", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Click the tweet compose area
    page.locator('[data-testid="tweetTextarea_0"]').click(timeout=10000)
    page.wait_for_timeout(500)
    page.locator('[data-testid="tweetTextarea_0"]').fill(content, timeout=10000)
    page.wait_for_timeout(500)

    # Screenshot before submitting
    try:
        page.screenshot(path=screenshot_path, timeout=5000, animations="disabled")
    except Exception:
        pass
    # Click the Post/Tweet button
    page.locator('[data-testid="tweetButtonInline"]').click(timeout=10000)
    page.wait_for_timeout(3000)

    return {
        "success": True,
        "result": f"Posted {len(content)}-character tweet to X",
        "screenshot_path": screenshot_path,
    }
