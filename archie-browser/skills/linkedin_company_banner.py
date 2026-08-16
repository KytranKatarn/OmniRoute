"""LinkedIn company banner — generates a branded cover image and uploads to company page."""
import os
import sys
from datetime import datetime

_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
# Guard the insert (#5650): skill_runner._discover_skills() re-imports EVERY skill on
# EVERY execute(), so an unguarded insert added a duplicate path per skill per run —
# measured sys.path 6 -> 33 after only 3 discoveries in a long-lived container.
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_DIR)
from _linkedin_common import get_company_slug

SKILL_NAME = "linkedin_company_banner"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# LinkedIn company cover image: 1128 x 191 px
BANNER_W, BANNER_H = 1128, 191


def _hex_to_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _generate_company_banner(params: dict) -> str:
    from PIL import Image, ImageDraw, ImageFont

    title = params.get("title", "KYTRAN EMPOWERMENT INC.")
    tagline = params.get("tagline", "Building AI that actually works.")
    bg_color = params.get("bg_color", "#0a0f1e")
    accent = params.get("accent", "#00c8c8")
    text_color = params.get("text_color", "#ffffff")
    logo_path = params.get("logo_path", "")

    img = Image.new("RGB", (BANNER_W, BANNER_H), bg_color)
    draw = ImageDraw.Draw(img)

    # Accent left bar
    draw.rectangle([0, 0, 6, BANNER_H], fill=accent)
    draw.rectangle([BANNER_W - 4, 0, BANNER_W, BANNER_H], fill=accent)

    # Dot grid
    dot_color = tuple(max(0, c + 18) for c in _hex_to_rgb(bg_color))
    for x in range(30, BANNER_W, 50):
        for y in range(15, BANNER_H, 30):
            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=dot_color)

    # Horizontal divider
    draw.rectangle([6, BANNER_H - 50, BANNER_W - 4, BANNER_H - 48], fill=accent)

    def _font(size):
        for name in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass
        return ImageFont.load_default()

    has_logo = bool(logo_path and os.path.exists(logo_path))
    text_zone_w = int(BANNER_W * 0.68) if has_logo else BANNER_W
    text_pad = 30

    title_size = 40
    title_font = _font(title_size)

    def _cx(text, font):
        bb = draw.textbbox((0, 0), text, font=font)
        w = bb[2] - bb[0]
        x = text_pad + (text_zone_w - text_pad * 2 - w) // 2
        return max(text_pad, x)

    # Auto-shrink title
    title_bb = draw.textbbox((0, 0), title, font=title_font)
    while (title_bb[2] - title_bb[0]) > (text_zone_w - text_pad * 2) and title_size > 22:
        title_size -= 2
        title_font = _font(title_size)
        title_bb = draw.textbbox((0, 0), title, font=title_font)

    tagline_font = _font(20)

    # Title
    draw.text((_cx(title, title_font) + 2, 32), title, font=title_font, fill="#00000040")
    draw.text((_cx(title, title_font), 30), title, font=title_font, fill=text_color)

    # Tagline
    draw.text((_cx(tagline, tagline_font), 90), tagline, font=tagline_font, fill=accent)

    # Logo — right zone
    if has_logo:
        try:
            from PIL import Image as PILImage
            logo = PILImage.open(logo_path).convert("RGBA")
            logo_max_h = int(BANNER_H * 0.80)
            logo_max_w = int(BANNER_W * 0.25)
            logo.thumbnail((logo_max_w, logo_max_h), PILImage.LANCZOS)
            lw, lh = logo.size
            lx = text_zone_w + (BANNER_W - 4 - text_zone_w - lw) // 2
            ly = (BANNER_H - lh) // 2
            img.paste(logo, (lx, ly), logo.split()[3])
        except Exception:
            pass

    out_path = f"/tmp/linkedin_company_banner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    img.save(out_path, "PNG")
    return out_path


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
    company_slug = get_company_slug(params)
    banner_path = params.get("banner_path", "")
    if not banner_path:
        banner_path = _generate_company_banner(params)
    if not os.path.exists(banner_path):
        raise ValueError(f"banner_path not found: {banner_path}")

    company_url = f"https://www.linkedin.com/company/{company_slug}/"
    page.goto(company_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "company_banner_before")

    # Click the cover/banner edit button
    clicked = False
    for attempt in [
        lambda: page.locator('[aria-label*="cover"]').first.click(timeout=8000),
        lambda: page.locator('[aria-label*="background"]').first.click(timeout=8000),
        lambda: page.locator('button.cover-img__btn').first.click(timeout=6000),
        lambda: page.locator('[data-control-name*="cover"]').first.click(timeout=6000),
        lambda: page.locator('.org-top-card-photo__click-area').first.click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "company_banner_btn_fail")
        raise RuntimeError("Could not find company cover image edit button")

    page.wait_for_timeout(2000)
    _screenshot(page, "company_banner_modal")

    # Upload option — "Edit cover image" or "Add cover image"
    for upload_opt in [
        lambda: page.get_by_text("Edit cover image", exact=False).first.click(timeout=5000),
        lambda: page.get_by_text("Add cover image", exact=False).first.click(timeout=5000),
        lambda: page.get_by_role("menuitem", name="cover image", exact=False).click(timeout=5000),
        lambda: page.get_by_role("button", name="Upload", exact=False).click(timeout=5000),
    ]:
        try:
            upload_opt()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # File input
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
        _screenshot(page, "company_banner_input_fail")
        raise RuntimeError("Could not find file input for banner upload")

    file_input.set_input_files(banner_path)
    page.wait_for_timeout(3000)
    _screenshot(page, "company_banner_crop")

    # HONEST commit tracking (#4611 follow-up): the old skill returned
    # success:True unconditionally even when every Apply/Save attempt below
    # fell through — a phantom-success. Track what actually clicked.
    applied = False
    for apply_btn in [
        lambda: page.get_by_role("button", name="Apply", exact=True).click(timeout=8000),
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
        lambda: page.locator('button:has-text("Apply")').last.click(timeout=5000),
    ]:
        try:
            apply_btn()
            applied = True
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    saved = False
    for save_btn in [
        lambda: page.get_by_role("button", name="Save", exact=True).last.click(timeout=6000),
        lambda: page.locator('button[type="submit"]').last.click(timeout=5000),
    ]:
        try:
            save_btn()
            saved = True
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    final = _screenshot(page, "company_banner_final")
    committed = applied or saved
    return {
        "success": committed,
        "result": "Company banner uploaded" if committed
        else "banner_file_set_but_NOT_committed — no Apply/Save affordance clicked",
        "applied_clicked": applied,
        "save_clicked": saved,
        "banner_path": banner_path,
        "screenshot_path": final,
    }
