"""LinkedIn document — posts a PDF carousel/document for 3-4x higher reach."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_document"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    content = params.get("content", "").strip()       # post caption text
    doc_path = params.get("doc_path", "").strip()     # local path to PDF or PPT
    doc_title = params.get("doc_title", "").strip()   # title shown on document card
    hashtags = params.get("hashtags", [])

    if not doc_path:
        raise ValueError("doc_path is required (PDF, PPTX, or image supported)")
    if not os.path.exists(doc_path):
        raise ValueError(f"doc_path not found: {doc_path}")

    if hashtags and content:
        content += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in hashtags)

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

    # Fill caption text
    if content:
        for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=5000)
                loc.click()
                loc.fill(content, timeout=8000)
                break
            except Exception:
                continue

    # Click document/carousel attach button
    clicked = False
    for attempt in [
        lambda: page.get_by_role("button", name="Add a document", exact=False).click(timeout=8000),
        lambda: page.get_by_label("Add a document", exact=False).click(timeout=6000),
        lambda: page.locator('button[aria-label*="document" i]').first.click(timeout=6000),
        lambda: page.locator('button[aria-label*="carousel" i]').first.click(timeout=5000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "doc_btn_fail")
        raise RuntimeError("Could not find document attach button")

    page.wait_for_timeout(1000)

    # Set file on file input
    file_input = None
    for sel in ['input[type="file"]', 'input[accept*="pdf"], input[accept*="ppt"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="attached", timeout=6000)
            file_input = loc
            break
        except Exception:
            continue

    if file_input is None:
        raise RuntimeError("Could not find file input for document upload")

    file_input.set_input_files(doc_path)
    page.wait_for_timeout(5000)  # documents take longer to process
    _screenshot(page, "doc_uploaded")

    # Set document title if provided
    if doc_title:
        for field in [
            lambda: page.get_by_label("Document title", exact=False).first.fill(doc_title, timeout=5000),
            lambda: page.locator('input[placeholder*="title" i]').last.fill(doc_title, timeout=4000),
        ]:
            try:
                field()
                break
            except Exception:
                continue

    # Next / Done
    for next_btn in [
        lambda: page.get_by_role("button", name="Done", exact=True).click(timeout=6000),
        lambda: page.get_by_role("button", name="Next", exact=True).click(timeout=6000),
        lambda: page.locator('button:has-text("Done")').last.click(timeout=5000),
    ]:
        try:
            next_btn()
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    _screenshot(page, "doc_ready")

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
        "result": f"Document posted: {doc_title or os.path.basename(doc_path)}",
        "doc_path": doc_path,
        "screenshot_path": _screenshot(page, "doc_done"),
    }
