"""LinkedIn post skill — publishes a text post to the LinkedIn feed."""
SKILL_NAME = "linkedin_post"
PLATFORMS = ["linkedin"]


def execute(page, params: dict) -> dict:
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    if not content:
        raise ValueError("content is required for linkedin_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    try:
        page.get_by_text("Start a post", exact=False).first.click()
    except Exception:
        page.locator('[data-control-name="share.sharebox_click"]').click()
    page.wait_for_timeout(1500)

    editor = page.locator('.ql-editor').first
    editor.click()
    editor.fill(content)
    page.wait_for_timeout(1000)

    page.get_by_role("button", name="Post", exact=True).click()
    page.wait_for_timeout(3000)

    screenshot_path = "/tmp/linkedin_post.png"
    page.screenshot(path=screenshot_path)

    return {"success": True, "platform": "linkedin", "content_preview": content[:80], "screenshot_path": screenshot_path}
