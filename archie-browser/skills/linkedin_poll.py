"""LinkedIn poll — creates a poll post with up to 4 options."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_poll"
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
    question = params.get("question", "").strip()
    options = params.get("options", [])  # list of 2-4 strings
    duration_days = int(params.get("duration_days", 7))  # 1, 3, 7, or 14
    preamble = params.get("preamble", "").strip()  # optional text above the poll

    if not question:
        raise ValueError("question is required for linkedin_poll")
    if len(options) < 2:
        raise ValueError("At least 2 options are required for linkedin_poll")

    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Open share box
    for attempt in [
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=8000),
        lambda: page.get_by_role("button", name="Start a post", exact=False).first.click(timeout=8000),
    ]:
        try:
            attempt()
            break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    _screenshot(page, "poll_box_open")

    # Add preamble text if provided
    if preamble:
        for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=5000)
                loc.click()
                loc.fill(preamble, timeout=6000)
                break
            except Exception:
                continue

    # Click poll button in toolbar
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Create a poll", exact=False).click(timeout=8000),
        lambda: page.get_by_label("Add a poll", exact=False).click(timeout=6000),
        lambda: page.locator('button[aria-label*="poll" i]').first.click(timeout=6000),
        lambda: page.locator('button[data-control-name*="poll"]').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "poll_btn_fail")
        raise RuntimeError("Could not find poll button — LinkedIn may have changed the toolbar")

    page.wait_for_timeout(2000)
    _screenshot(page, "poll_modal_open")

    # Fill question
    for field in [
        lambda: page.get_by_label("Question", exact=False).first.fill(question, timeout=6000),
        lambda: page.locator('input[placeholder*="question" i], textarea[placeholder*="question" i]').first.fill(question, timeout=5000),
    ]:
        try:
            field()
            break
        except Exception:
            continue

    # Fill options
    option_fields = page.locator('input[placeholder*="option" i], input[placeholder*="Option" i]').all()
    for i, opt_text in enumerate(options[:4]):
        if i < len(option_fields):
            try:
                option_fields[i].fill(opt_text, timeout=4000)
            except Exception:
                pass
        elif i == len(option_fields):
            # Click "Add option" to get a new field
            try:
                page.get_by_role("button", name="Add option", exact=False).click(timeout=4000)
                page.wait_for_timeout(500)
                new_fields = page.locator('input[placeholder*="option" i]').all()
                if new_fields:
                    new_fields[-1].fill(opt_text, timeout=4000)
            except Exception:
                pass

    # Set duration
    try:
        dur_map = {1: "1 day", 3: "3 days", 7: "1 week", 14: "2 weeks"}
        label = dur_map.get(duration_days, "1 week")
        page.get_by_role("combobox").first.select_option(label=label, timeout=5000)
    except Exception:
        pass

    page.wait_for_timeout(500)
    _screenshot(page, "poll_filled")

    # Done / insert poll
    for done_btn in [
        lambda: page.get_by_role("button", name="Done", exact=True).click(timeout=6000),
        lambda: page.get_by_role("button", name="Insert poll", exact=False).click(timeout=6000),
        lambda: page.locator('button:has-text("Done")').last.click(timeout=5000),
    ]:
        try:
            done_btn()
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    # Post
    for post_btn in [
        lambda: page.get_by_role("button", name="Post", exact=True).click(timeout=10000),
        lambda: page.locator('button:has-text("Post")').last.click(timeout=8000),
    ]:
        try:
            post_btn()
            break
        except Exception:
            continue

    page.wait_for_timeout(3000)
    return {
        "success": True,
        "result": f"Poll posted: {question[:60]}... ({len(options)} options)",
        "screenshot_path": _screenshot(page, "poll_done"),
    }
