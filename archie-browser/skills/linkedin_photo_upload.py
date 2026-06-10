"""LinkedIn photo upload skill — sets profile photo from a local file path."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_photo_upload"
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
    photo_path = params.get("photo_path", "").strip()
    if not photo_path:
        raise ValueError("photo_path is required for linkedin_photo_upload")
    if not os.path.exists(photo_path):
        raise ValueError(f"photo_path not found: {photo_path}")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "photo_before")

    # Click the profile photo circle / camera icon
    clicked = False
    for attempt in [
        lambda: page.locator('.pv-top-card-profile-picture button').first.click(timeout=8000),
        lambda: page.locator('button.profile-photo-edit__edit-btn').first.click(timeout=8000),
        lambda: page.locator('[aria-label*="profile photo"]').first.click(timeout=8000),
        lambda: page.locator('[aria-label*="Edit your profile photo"]').first.click(timeout=8000),
        # The + button on the empty photo circle
        lambda: page.locator('.pv-top-card-profile-picture__edit-container button').first.click(timeout=8000),
        lambda: page.locator('button[class*="profile-photo"]').first.click(timeout=8000),
        lambda: page.locator('.pv-top-card__non-self-photo-wrapper button').first.click(timeout=6000),
        # Fallback: click the photo area directly
        lambda: page.locator('.pv-top-card__photo-wrapper button').first.click(timeout=6000),
        lambda: page.locator('button.artdeco-button--circle').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "photo_click_fail")
        raise RuntimeError("Could not find profile photo button")

    page.wait_for_timeout(2000)
    _screenshot(page, "photo_modal_open")

    # Click "Upload photo" option if presented
    for upload_btn in [
        lambda: page.get_by_role("button", name="Upload photo", exact=False).click(timeout=5000),
        lambda: page.get_by_text("Upload photo", exact=False).first.click(timeout=5000),
        lambda: page.locator('label[for*="photo"], input[type="file"]').first.click(timeout=5000),
    ]:
        try:
            upload_btn()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # Set the file on the hidden file input
    file_input = None
    for sel in ['input[type="file"]', 'input[accept*="image"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=8000)
            file_input = loc
            break
        except Exception:
            continue

    if file_input is None:
        _screenshot(page, "photo_input_fail")
        raise RuntimeError("Could not find file input for photo upload")

    file_input.set_input_files(photo_path)
    page.wait_for_timeout(3000)
    _screenshot(page, "photo_crop_ui")

    # Handle crop UI — click Apply/Save to accept default crop
    for apply_btn in [
        lambda: page.get_by_role("button", name="Apply", exact=True).click(timeout=8000),
        lambda: page.get_by_role("button", name="Save photo", exact=False).click(timeout=8000),
        lambda: page.locator('button:has-text("Apply")').last.click(timeout=5000),
        lambda: page.locator('button[data-crop-save]').click(timeout=5000),
    ]:
        try:
            apply_btn()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    _screenshot(page, "photo_after_apply")

    # Final save if another modal appears
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
        lambda: page.locator('button[aria-label="Save"]').last.click(timeout=5000),
    ]:
        try:
            save_btn()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    # Dismiss any follow-up modal
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    final = _screenshot(page, "photo_final")
    return {
        "success": True,
        "result": "Profile photo uploaded",
        "photo_path": photo_path,
        "screenshot_path": final,
    }
