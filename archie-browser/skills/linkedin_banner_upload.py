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
    # Viewport screenshot to the MOUNTED /profiles volume (host:
    # /mnt/data2/browser-profiles) with fixed names so they're retrievable;
    # full_page times out on this animated page.
    path = f"/profiles/_bup_{name}.png"
    try:
        page.screenshot(path=path, full_page=False, timeout=15000, animations="disabled")
        return path
    except Exception:
        return None


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

    # ── Open the cover uploader + set the file ───────────────────────────────
    # VERIFIED live Terry/377 (headed + headless). The real flow is:
    #   "Add background image" (button) -> "Add cover image" (menu modal) ->
    #   "Upload single photo" (triggers a NATIVE file-chooser) -> a PERSISTENT
    #   page.on('filechooser') handler feeds the banner -> "Save changes" finalizes.
    # The intermediate "Upload single photo" click is ESSENTIAL — without it no
    # chooser ever fires (that was the long-standing bug). A persistent handler is
    # required because the chooser fires after a delay; a scoped expect_file_chooser
    # around a single click misses it.
    _fc = {"set": False}

    def _on_filechooser(fc):
        try:
            fc.set_files(banner_path)
            _fc["set"] = True
        except Exception:
            pass

    page.on("filechooser", _on_filechooser)
    file_set = False
    try:
        # 1. Banner control (Add/Edit background image) -> menu.
        button_clicked = False
        for attempt in [
            lambda: page.locator('button[aria-label="Add background image"]').first.click(timeout=8000),
            lambda: page.locator('[aria-label*="background image"]').first.click(timeout=8000),
            lambda: page.locator('[aria-label*="Edit background"]').first.click(timeout=6000),
        ]:
            try:
                attempt()
                button_clicked = True
                break
            except Exception:
                continue
        if not button_clicked:
            _screenshot(page, "banner_btn_fail")
            raise RuntimeError("Could not find banner edit button")
        page.wait_for_timeout(1800)
        _screenshot(page, "banner_menu_open")

        # 2. "Add cover image" (or Edit/Change when one already exists) -> modal.
        for attempt in [
            lambda: page.get_by_text("Add cover image", exact=False).first.click(timeout=6000),
            lambda: page.get_by_text("Edit cover image", exact=False).first.click(timeout=5000),
            lambda: page.get_by_text("Change cover image", exact=False).first.click(timeout=5000),
        ]:
            try:
                attempt()
                break
            except Exception:
                continue
        page.wait_for_timeout(2500)

        # 3. "Upload single photo" -> NATIVE chooser -> handler feeds the file.
        for attempt in [
            lambda: page.get_by_text("Upload single photo", exact=False).first.click(timeout=6000),
            lambda: page.get_by_text("Upload photo", exact=False).first.click(timeout=4000),
            lambda: page.get_by_text("Change photo", exact=False).first.click(timeout=4000),
        ]:
            try:
                attempt()
                break
            except Exception:
                continue

        # 4. Wait for the handler to feed the file (DOM input as a fallback).
        for _ in range(20):
            if _fc["set"]:
                break
            page.wait_for_timeout(500)
        if not _fc["set"]:
            try:
                page.locator('input[type="file"]').first.set_input_files(banner_path, timeout=3000)
                _fc["set"] = True
            except Exception:
                pass
        if not _fc["set"]:
            _screenshot(page, "banner_upload_fail")
            raise RuntimeError("Could not upload banner file (no chooser/input found)")

        # 5. Crop/edit view -> "Save changes" finalizes (a separate "Save" may remain).
        page.wait_for_timeout(5000)
        _screenshot(page, "banner_crop")
        for attempt in [
            lambda: page.get_by_role("button", name="Save changes", exact=True).last.click(timeout=8000),
            lambda: page.get_by_role("button", name="Apply", exact=True).last.click(timeout=4000),
        ]:
            try:
                attempt()
                break
            except Exception:
                continue
        page.wait_for_timeout(2500)
        try:
            page.get_by_role("button", name="Save", exact=True).last.click(timeout=4000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    finally:
        try:
            page.remove_listener("filechooser", _on_filechooser)
        except Exception:
            pass
    file_set = _fc["set"]

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # ── Honest verification: reload + confirm a banner now exists ────────────
    # With a banner set, the control flips "Add background image" -> "Edit
    # background image". Success is reported ONLY when that flip is observed
    # (and the profile actually re-loaded), never on a bare "we clicked Save".
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page_loaded = False
    add_still = 0
    edit_now = 0
    try:
        page_loaded = page.locator('a[aria-label="Edit profile"]').count() > 0
    except Exception:
        pass
    try:
        add_still = page.locator('button[aria-label="Add background image"]').count()
    except Exception:
        pass
    try:
        edit_now = page.locator('[aria-label*="dit background"]').count()
    except Exception:
        pass
    confirmed = page_loaded and (edit_now > 0 or add_still == 0)
    final = _screenshot(page, "banner_final")
    return {
        "success": bool(confirmed),
        "result": "Banner set (verified)" if confirmed else "Upload attempted; banner NOT confirmed",
        "file_set": file_set,
        "banner_path": banner_path,
        "screenshot_path": final,
    }
