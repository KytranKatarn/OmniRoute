"""LinkedIn profile view — navigate to any profile, screenshot, extract key info."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_profile_view"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def execute(page, params: dict) -> dict:
    profile_url = params.get("profile_url", "").strip()
    if not profile_url:
        raise ValueError("profile_url is required for linkedin_profile_view")

    # Strip tracking params — navigate to clean profile URL
    clean_url = profile_url.split("?")[0].rstrip("/")

    page.goto(clean_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Extract profile info — multiple selector fallbacks per field
    def _try(fns, default=""):
        for fn in fns:
            try:
                result = fn()
                if result:
                    return result.strip()
            except Exception:
                continue
        return default

    name = _try([
        lambda: page.locator("h1").first.inner_text(timeout=5000),
        lambda: page.locator(".pv-text-details__left-panel h1").inner_text(timeout=3000),
    ])

    headline = _try([
        lambda: page.locator(".text-body-medium.break-words").first.inner_text(timeout=5000),
        lambda: page.locator("h1").first.locator("~ div").first.inner_text(timeout=3000),
    ])

    # Location appears as plain span below headline — grab text before "· Contact info"
    location = _try([
        lambda: page.locator(".text-body-small.inline.t-black--light").first.inner_text(timeout=5000).split("·")[0].strip(),
        lambda: page.locator(".pv-text-details__left-panel span.text-body-small").first.inner_text(timeout=3000).split("·")[0].strip(),
    ])

    # Followers / connections line
    connections = _try([
        lambda: page.locator("span.t-bold").filter(has_text="connections").first.inner_text(timeout=3000),
        lambda: page.locator("a").filter(has_text="connections").first.inner_text(timeout=3000),
        lambda: page.locator("span").filter(has_text="followers").first.inner_text(timeout=3000),
    ])

    # Scroll to About section, expand "see more", grab text via JS
    try:
        page.locator("#about").first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(1000)
        # Expand "see more" if present
        for btn_text in ["see more", "…more", "Show more"]:
            try:
                page.get_by_role("button", name=btn_text, exact=False).first.click(timeout=2000)
                page.wait_for_timeout(500)
                break
            except Exception:
                pass
    except Exception:
        pass

    about = _try([
        # JS: find the section containing #about heading, return all visible text excluding the heading itself
        lambda: page.evaluate("""() => {
            const heading = document.getElementById('about');
            if (!heading) return '';
            const section = heading.closest('section');
            if (!section) return '';
            // Get all span[aria-hidden=true] text nodes that aren't just 'About'
            const spans = section.querySelectorAll('span[aria-hidden="true"]');
            for (const s of spans) {
                const t = s.textContent.trim();
                if (t && t !== 'About' && t.length > 20) return t;
            }
            return '';
        }"""),
        lambda: page.locator("#about ~ div .inline-show-more-text").inner_text(timeout=5000),
    ])

    # open_to_work badge
    open_to_work = False
    try:
        page.locator(".open-to-work-banner, [class*='open-to-work']").first.wait_for(state="visible", timeout=2000)
        open_to_work = True
    except Exception:
        try:
            if "opentowork" in page.locator(".pv-open-to-work-banner").first.get_attribute("class", timeout=2000).lower():
                open_to_work = True
        except Exception:
            pass

    # Scroll back to top for screenshot
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_profile_{ts}.png"
    page.screenshot(path=screenshot_path, full_page=False)

    return {
        "success": True,
        "profile_url": clean_url,
        "name": name,
        "headline": headline,
        "location": location,
        "about": about[:800] if about else "",
        "connections": connections,
        "open_to_work": open_to_work,
        "screenshot_path": screenshot_path,
    }
