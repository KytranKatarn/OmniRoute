"""LinkedIn company create — creates a new LinkedIn company page."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_company_create"
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
    name = params.get("name", "Kytran Empowerment Inc.").strip()
    website = params.get("website", "https://kytranempowerment.com").strip()
    industry = params.get("industry", "Technology, Information and Internet").strip()
    tagline = params.get("tagline", "Building AI that actually works.").strip()
    slug_override = params.get("slug", "").strip()

    page.goto("https://www.linkedin.com/company/setup/new/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "cc_start")

    # Step 1 — Select "Company" page type
    for btn in [
        lambda: page.get_by_role("button", name="Company", exact=True).click(timeout=8000),
        lambda: page.get_by_role("link", name="Company", exact=True).click(timeout=6000),
        lambda: page.locator('button:has-text("Company")').first.click(timeout=6000),
        lambda: page.locator('[aria-label*="Company"]').first.click(timeout=6000),
    ]:
        try:
            btn()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    _screenshot(page, "cc_type")

    # Name
    for field in [
        lambda: page.get_by_label("Name", exact=True).fill(name, timeout=8000),
        lambda: page.locator('input[id*="name"][id*="company"], input[name="name"]').first.fill(name, timeout=6000),
        lambda: page.locator('input[autocomplete="organization"]').first.fill(name, timeout=6000),
        lambda: page.locator('form input[type="text"]').first.fill(name, timeout=5000),
    ]:
        try:
            field()
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    # Handle URL slug — check for conflict, modify if needed
    if slug_override:
        try:
            slug_field = page.locator('input[id*="vanityName"], input[id*="url"], input[name*="vanity"]').first
            slug_field.clear()
            slug_field.fill(slug_override, timeout=5000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
    else:
        # Check for URL conflict and auto-fix
        page.wait_for_timeout(1500)
        has_conflict = False
        try:
            page.locator('text=already in use').wait_for(state="visible", timeout=3000)
            has_conflict = True
        except Exception:
            pass

        if has_conflict:
            # Try alternative slugs
            for alt_slug in ["kytranempowerment", "kytran-empowerment-ai", "kytran-emp-inc"]:
                try:
                    slug_field = page.locator(
                        'input[id*="vanityName"], input[id*="url"], input[name*="vanity"], '
                        'input[aria-label*="URL"], input[aria-label*="url"]'
                    ).first
                    slug_field.triple_click(timeout=3000)
                    slug_field.fill(alt_slug, timeout=5000)
                    page.wait_for_timeout(1500)
                    try:
                        page.locator('text=already in use').wait_for(state="visible", timeout=2000)
                        continue  # Still conflicting, try next
                    except Exception:
                        break  # No conflict — good
                except Exception:
                    continue

    # Website
    for field in [
        lambda: page.get_by_label("Website", exact=False).first.fill(website, timeout=6000),
        lambda: page.locator('input[id*="website"], input[name*="website"]').first.fill(website, timeout=5000),
    ]:
        try:
            field()
            page.wait_for_timeout(500)
            break
        except Exception:
            continue

    # Industry typeahead
    try:
        ind = page.get_by_label("Industry", exact=False).first
        ind.fill(industry, timeout=5000)
        page.wait_for_timeout(1000)
        page.locator('[role="option"]').first.click(timeout=4000)
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Organization size — try all common label/value combinations
    size_filled = False
    for size_val in ["2", "B", "1-10", "11"]:
        for sel in [
            f'select[id*="size"], select[name*="size"]',
            'select[aria-label*="size" i], select[aria-label*="Size" i]',
        ]:
            try:
                page.locator(sel).first.select_option(index=1, timeout=3000)
                size_filled = True
                break
            except Exception:
                continue
        if size_filled:
            break

    if not size_filled:
        try:
            page.get_by_label("Company size", exact=False).first.select_option(index=1, timeout=5000)
        except Exception:
            try:
                page.get_by_label("Organization size", exact=False).first.select_option(index=1, timeout=5000)
            except Exception:
                pass

    # Organization type
    for sel in [
        lambda: page.get_by_label("Company type", exact=False).first.select_option(label="Privately held", timeout=5000),
        lambda: page.get_by_label("Organization type", exact=False).first.select_option(label="Privately held", timeout=5000),
        lambda: page.locator('select[id*="type"]').first.select_option(label="Privately held", timeout=4000),
    ]:
        try:
            sel()
            break
        except Exception:
            continue

    # Tagline
    try:
        page.get_by_label("Tagline", exact=False).first.fill(tagline, timeout=5000)
    except Exception:
        try:
            page.locator('textarea[id*="tagline"]').first.fill(tagline, timeout=4000)
        except Exception:
            pass

    page.wait_for_timeout(500)
    _screenshot(page, "cc_filled")

    # Terms checkbox — scroll then force-click via JS
    try:
        cb = page.locator('input[type="checkbox"]').last
        cb.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(600)
    except Exception:
        pass
    # Try multiple methods to check it
    checked = False
    for method in [
        lambda: page.evaluate("document.querySelector('input[type=\"checkbox\"]').click()"),
        lambda: page.locator('input[type="checkbox"]').last.click(timeout=4000),
        lambda: page.locator('label:has(input[type="checkbox"])').last.click(timeout=4000),
        lambda: page.locator('input[type="checkbox"]').last.check(force=True, timeout=4000),
    ]:
        try:
            method()
            page.wait_for_timeout(500)
            checked = True
            break
        except Exception:
            continue

    _screenshot(page, "cc_terms")

    # Create page button
    for btn in [
        lambda: page.get_by_role("button", name="Create page", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Agree & create page", exact=False).click(timeout=6000),
        lambda: page.locator('button[type="submit"]:has-text("Create")').click(timeout=6000),
        lambda: page.locator('button[type="submit"]').last.click(timeout=5000),
    ]:
        try:
            btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(5000)
    _screenshot(page, "cc_result")

    final_url = page.url
    slug = ""
    if "/company/" in final_url and "setup" not in final_url:
        parts = final_url.split("/company/")
        slug = parts[1].split("/")[0].split("?")[0]

    return {
        "success": "setup" not in final_url,
        "result": f"Company page {'created' if slug else 'may have failed — check screenshot'}. Slug: {slug or 'unknown'}",
        "final_url": final_url,
        "slug": slug,
        "screenshot_path": _screenshot(page, "cc_final"),
    }
