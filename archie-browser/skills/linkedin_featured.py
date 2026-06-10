"""LinkedIn featured — add or update items in the Featured section of the profile."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_featured"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    # Diagnostic only — non-fatal. Bare page.screenshot() times out at 30s on
    # LinkedIn's animated composer and falsely fails posts (#3953). 5s timeout
    # + animations disabled + swallow errors.
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def execute(page, params: dict) -> dict:
    """Add a link, post, or media to the LinkedIn Featured section.

    params:
        item_type: 'link' | 'post'  (default: 'link')
        url: the URL to feature (for link type)
        title: display title for the link
        description: optional description
        post_url: URL of a LinkedIn post to feature (for post type)
    """
    item_type = params.get("item_type", "link")
    url = params.get("url", "").strip()
    title = params.get("title", "").strip()
    description = params.get("description", "").strip()

    if item_type == "link" and not url:
        raise ValueError("url is required for linkedin_featured (link type)")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    _screenshot(page, "featured_before")

    # Scroll to Featured section
    featured_exists = False
    try:
        page.locator("#featured").first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(1000)
        featured_exists = True
    except Exception:
        pass

    if featured_exists:
        # Click the + button inside Featured section
        clicked = page.evaluate("""() => {
            const h = document.getElementById('featured');
            if (!h) return false;
            const section = h.closest('section');
            if (!section) return false;
            const btns = section.querySelectorAll('button');
            for (const b of btns) {
                const lbl = (b.getAttribute('aria-label') || b.textContent || '').toLowerCase();
                if (lbl.includes('add') || lbl.includes('+')) { b.click(); return true; }
            }
            return false;
        }""")
        if not clicked:
            featured_exists = False

    if not featured_exists:
        # Add via "Add profile section"
        for btn in [
            lambda: page.get_by_role("button", name="Add profile section", exact=False).click(timeout=8000),
        ]:
            try:
                btn()
                page.wait_for_timeout(1500)
                break
            except Exception:
                continue
        # Click Featured
        for feat_btn in [
            lambda: page.get_by_role("button", name="Featured", exact=False).click(timeout=6000),
            lambda: page.get_by_text("Featured", exact=True).first.click(timeout=6000),
        ]:
            try:
                feat_btn()
                page.wait_for_timeout(1000)
                break
            except Exception:
                continue

    page.wait_for_timeout(2000)
    _screenshot(page, "featured_menu")

    if item_type == "link":
        # Click "Add a link"
        for link_btn in [
            lambda: page.get_by_role("button", name="Add a link", exact=False).click(timeout=6000),
            lambda: page.get_by_text("Add a link", exact=False).first.click(timeout=5000),
            lambda: page.get_by_role("menuitem", name="link", exact=False).click(timeout=5000),
        ]:
            try:
                link_btn()
                page.wait_for_timeout(2000)
                break
            except Exception:
                continue

        # Fill URL
        for field in [
            lambda: page.get_by_label("URL", exact=False).first.fill(url, timeout=6000),
            lambda: page.locator('input[id*="url"], input[type="url"]').first.fill(url, timeout=5000),
        ]:
            try:
                field()
                page.wait_for_timeout(2000)  # wait for LinkedIn to fetch preview
                break
            except Exception:
                continue

        # Override title if provided
        if title:
            for field in [
                lambda: page.get_by_label("Title", exact=False).first.clear(),
                lambda: page.get_by_label("Title", exact=False).first.fill(title, timeout=5000),
            ]:
                try:
                    field()
                    break
                except Exception:
                    continue

        # Description
        if description:
            try:
                page.get_by_label("Description", exact=False).first.fill(description, timeout=5000)
            except Exception:
                pass

    _screenshot(page, "featured_filled")

    # Save
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=8000),
        lambda: page.get_by_role("button", name="Add", exact=True).last.click(timeout=6000),
    ]:
        try:
            save_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(3000)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    return {
        "success": True,
        "result": f"Added to Featured: {title or url}",
        "screenshot_path": _screenshot(page, "featured_done"),
    }
