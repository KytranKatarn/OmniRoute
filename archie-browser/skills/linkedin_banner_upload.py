"""LinkedIn banner upload — generates a branded banner and sets it as profile background."""
import os
import io
from datetime import datetime

SKILL_NAME = "linkedin_banner_upload"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)

# LinkedIn banner: 1584 x 396 px
BANNER_W, BANNER_H = 1584, 396


def _generate_banner(params: dict) -> str:
    """Generate a branded banner with PIL and return the file path."""
    from PIL import Image, ImageDraw, ImageFont

    title = params.get("title", "KYTRAN EMPOWERMENT")
    tagline = params.get("tagline", "Building AI that actually works.")
    sub = params.get("sub", "A.R.C.H.I.E. Platform  ·  C.R.E.E.D. Institute  ·  Montreal")
    bg_color = params.get("bg_color", "#0a0f1e")
    accent = params.get("accent", "#00c8c8")
    text_color = params.get("text_color", "#ffffff")
    logo_path = params.get("logo_path", "")

    img = Image.new("RGB", (BANNER_W, BANNER_H), bg_color)
    draw = ImageDraw.Draw(img)

    # Accent bar — left edge
    draw.rectangle([0, 0, 8, BANNER_H], fill=accent)

    # Subtle grid dots for tech feel
    dot_color = tuple(max(0, c + 20) for c in _hex_to_rgb(bg_color))
    for x in range(40, BANNER_W, 60):
        for y in range(20, BANNER_H, 40):
            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=dot_color)

    # Determine text zone — full width if no logo, left 65% if logo present
    has_logo = bool(logo_path and os.path.exists(logo_path))
    text_zone_w = int(BANNER_W * 0.62) if has_logo else BANNER_W
    text_pad = 60  # left padding from accent bar

    # Accent right strip
    draw.rectangle([BANNER_W - 6, 0, BANNER_W, BANNER_H], fill=accent)

    # Horizontal accent line
    draw.rectangle([8, BANNER_H // 2 + 60, BANNER_W - 6, BANNER_H // 2 + 63], fill=accent)

    # Load fonts
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

    title_size = 72
    title_font = _font(title_size)
    tagline_font = _font(34)
    sub_font = _font(24)

    # Text x-center within the text zone — never clip left edge
    def _cx(text, font):
        bb = draw.textbbox((0, 0), text, font=font)
        w = bb[2] - bb[0]
        x = text_pad + (text_zone_w - text_pad * 2 - w) // 2
        return max(text_pad, x)  # clamp — never go past the left accent bar

    # Auto-shrink title font if it's wider than the text zone
    title_bb = draw.textbbox((0, 0), title, font=title_font)
    while (title_bb[2] - title_bb[0]) > (text_zone_w - text_pad * 2) and title_size > 40:
        title_size -= 4
        title_font = _font(title_size)
        title_bb = draw.textbbox((0, 0), title, font=title_font)

    # Title
    tx = _cx(title, title_font)
    title_y = 75
    draw.text((tx + 3, title_y + 3), title, font=title_font, fill="#00000040")
    draw.text((tx, title_y), title, font=title_font, fill=text_color)

    # Tagline
    draw.text((_cx(tagline, tagline_font), 185), tagline, font=tagline_font, fill=accent)

    # Sub-line
    sub_dim = tuple(max(0, c - 60) for c in _hex_to_rgb(text_color))
    draw.text((_cx(sub, sub_font), 298), sub, font=sub_font, fill=sub_dim)

    # Logo — right side, vertically centred
    if has_logo:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo_max_h = int(BANNER_H * 0.88)
            logo_max_w = int(BANNER_W * 0.26)
            logo.thumbnail((logo_max_w, logo_max_h), Image.LANCZOS)
            lw, lh = logo.size
            logo_zone_x = text_zone_w
            logo_zone_w = BANNER_W - 6 - logo_zone_x
            lx = logo_zone_x + (logo_zone_w - lw) // 2
            ly = (BANNER_H - lh) // 2
            # Paste with alpha mask
            img.paste(logo, (lx, ly), logo.split()[3])
        except Exception:
            pass

    out_path = f"/tmp/linkedin_banner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    img.save(out_path, "PNG")
    return out_path


def _hex_to_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    # Use provided banner_path or generate one
    banner_path = params.get("banner_path", "").strip()
    if not banner_path:
        banner_path = _generate_banner(params)

    if not os.path.exists(banner_path):
        raise ValueError(f"banner_path not found: {banner_path}")

    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "banner_before")

    # Click the background/banner edit button (camera icon on the banner area)
    clicked = False
    for attempt in [
        lambda: page.locator('[aria-label*="Edit background"]').first.click(timeout=8000),
        lambda: page.locator('[aria-label*="background photo"]').first.click(timeout=8000),
        lambda: page.locator('button.profile-background-image__edit-btn').first.click(timeout=8000),
        lambda: page.locator('button[class*="background"]').first.click(timeout=6000),
        # Camera icon on the banner area (top section)
        lambda: page.locator('.profile-background-image button').first.click(timeout=6000),
        lambda: page.locator('section.artdeco-card').first.locator('button').nth(1).click(timeout=6000),
    ]:
        try:
            attempt()
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        _screenshot(page, "banner_btn_fail")
        raise RuntimeError("Could not find banner edit button")

    page.wait_for_timeout(2000)
    _screenshot(page, "banner_modal")

    # Menu text differs based on whether a banner already exists:
    # No banner → "Add cover image" | Existing banner → "Edit cover image"
    for upload_opt in [
        lambda: page.get_by_text("Edit cover image", exact=False).first.click(timeout=5000),
        lambda: page.get_by_text("Add cover image", exact=False).first.click(timeout=5000),
        lambda: page.get_by_role("menuitem", name="cover image", exact=False).click(timeout=5000),
        lambda: page.get_by_role("button", name="Upload photo", exact=False).click(timeout=5000),
        lambda: page.get_by_text("Upload photo", exact=False).first.click(timeout=5000),
    ]:
        try:
            upload_opt()
            page.wait_for_timeout(1000)
            break
        except Exception:
            continue

    # Set file on the input
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
        _screenshot(page, "banner_input_fail")
        raise RuntimeError("Could not find file input for banner upload")

    file_input.set_input_files(banner_path)
    page.wait_for_timeout(3000)
    _screenshot(page, "banner_crop")

    # Apply crop (accept default)
    for apply_btn in [
        lambda: page.get_by_role("button", name="Apply", exact=True).click(timeout=8000),
        lambda: page.get_by_role("button", name="Save photo", exact=False).click(timeout=6000),
        lambda: page.locator('button:has-text("Apply")').last.click(timeout=5000),
    ]:
        try:
            apply_btn()
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    # Final save
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

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    final = _screenshot(page, "banner_final")
    return {
        "success": True,
        "result": "Banner uploaded",
        "banner_path": banner_path,
        "screenshot_path": final,
    }
