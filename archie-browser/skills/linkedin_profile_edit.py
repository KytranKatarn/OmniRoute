"""LinkedIn profile edit skill — updates headline."""
SKILL_NAME = "linkedin_profile_edit"
PLATFORMS = ["linkedin"]


def execute(page, params: dict) -> dict:
    headline = params.get("headline", "").strip()
    summary = params.get("summary", "").strip()

    if not headline and not summary:
        raise ValueError("At least one of headline or summary is required")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    updated = []
    if headline:
        try:
            page.get_by_role("button", name="Edit intro").click()
        except Exception:
            page.locator('[aria-label="Edit intro"]').click()
        page.wait_for_timeout(1500)

        headline_field = page.locator('#single-line-text-form-component-profileEditFormElement-SUMMARY-headline')
        if not headline_field.is_visible():
            headline_field = page.get_by_label("Headline")
        headline_field.fill(headline)
        page.get_by_role("button", name="Save").click()
        page.wait_for_timeout(2000)
        updated.append("headline")

    screenshot_path = "/tmp/linkedin_profile_edit.png"
    page.screenshot(path=screenshot_path)
    return {"success": True, "updated_fields": updated, "screenshot_path": screenshot_path}
