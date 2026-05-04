"""LinkedIn creed post — publishes a post as the C.R.E.E.D. Institute organization page."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_creed_post"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def _diagnostic_dump(page, label: str) -> dict:
    """Capture page URL + title + first ~30 visible button labels."""
    info: dict = {"label": label, "url": "", "title": "", "buttons": []}
    try:
        info["url"] = page.url
    except Exception:
        pass
    try:
        info["title"] = page.title()
    except Exception:
        pass
    try:
        btns = page.locator("button:visible").all()[:30]
        info["buttons"] = [
            (b.inner_text(timeout=500) or "").strip()[:60] for b in btns
        ]
    except Exception:
        pass
    return info


def _open_share_box(page) -> bool:
    """Try every known selector for the share-box trigger."""
    attempts = [
        lambda: page.get_by_role("button", name="Create a post", exact=False).click(timeout=8000),
        lambda: page.locator('button:has-text("Create a post")').first.click(timeout=8000),
        lambda: page.get_by_placeholder("Start a post", exact=False).click(timeout=6000),
        lambda: page.get_by_role("button", name="Start a post", exact=False).click(timeout=6000),
        lambda: page.locator('button:has-text("Start a post")').first.click(timeout=6000),
        lambda: page.locator('[class*="share-box"] button').first.click(timeout=6000),
        lambda: page.locator('[class*="share-creation"] button').first.click(timeout=6000),
        lambda: page.get_by_text("Create a post", exact=False).first.click(timeout=5000),
        lambda: page.get_by_text("Start a post", exact=False).first.click(timeout=5000),
        lambda: page.locator('header').get_by_role("button", name="Post", exact=True).click(timeout=5000),
    ]
    for attempt in attempts:
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def execute(page, params: dict) -> dict:
    # Slug priority: explicit param > LINKEDIN_CREED_SLUG env > numeric default.
    # Creed-AI Institute lives at /company/115977300/ (numeric ID required for /admin paths,
    # see KB #263310). Kytran is super-admin on this organization page.
    company_slug = (
        params.get("company_slug")
        or os.getenv("LINKEDIN_CREED_SLUG")
        or "115977300"
    )
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    if not content:
        raise ValueError("content is required for linkedin_creed_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    candidate_urls = [
        f"https://www.linkedin.com/company/{company_slug}/admin/page-posts/published/",
        f"https://www.linkedin.com/company/{company_slug}/admin/feed/",
        f"https://www.linkedin.com/company/{company_slug}/admin/dashboard/",
    ]

    opened = False
    diagnostics: list = []
    for url in candidate_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            diagnostics.append({"url": url, "goto": "failed"})
            continue
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        _screenshot(page, f"creed_post_landed_{url.rsplit('/admin/', 1)[-1].replace('/', '_')}")

        if _open_share_box(page):
            opened = True
            break
        diagnostics.append(_diagnostic_dump(page, f"share_box_miss:{url}"))

    if not opened:
        _screenshot(page, "creed_post_btn_fail")
        raise RuntimeError(
            "Could not find Start/Create a post button on Creed-AI page; "
            f"tried {len(candidate_urls)} URLs. diagnostics={diagnostics}"
        )

    page.wait_for_timeout(2000)
    _screenshot(page, "creed_post_editor_open")

    editor = None
    for sel in ['.ql-editor', '[role="textbox"]', '[contenteditable="true"]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            editor = loc
            break
        except Exception:
            continue

    if editor is None:
        _screenshot(page, "creed_post_editor_fail")
        raise RuntimeError("Could not find post editor")

    editor.click(timeout=5000)
    editor.fill(content, timeout=10000)
    page.wait_for_timeout(1000)
    _screenshot(page, "creed_post_filled")

    if os.getenv("ARCHIE_LINKEDIN_DRY_RUN") == "1":
        return {
            "success": True,
            "result": f"DRY RUN — composed {len(content)} chars as {company_slug}, did not submit",
            "company_slug": company_slug,
            "dry_run": True,
            "screenshot_path": _screenshot(page, "creed_post_dryrun"),
        }

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

    try:
        page.get_by_role("button", name="No thanks", exact=False).click(timeout=3000)
        page.wait_for_timeout(500)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    final = _screenshot(page, "creed_post_final")
    return {
        "success": True,
        "result": f"Posted {len(content)} characters as {company_slug}",
        "company_slug": company_slug,
        "screenshot_path": final,
    }
