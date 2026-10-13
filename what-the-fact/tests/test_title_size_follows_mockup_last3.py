"""elections, journalists and sources titles follow the mockup's 38px (task #6604, found by the design-port rig).

They carried an inline 30px; the mockup sets Newsreader 38px/600/-.015em, phones step down to 30px. The computed style is read from the REAL
`.wtf-pg-h1` rule in style.css in a real browser. The control (the old inline 30px markup) must read 30px, proving the check can fail.
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
STYLE_CSS = (C / "static" / "style.css").read_text(encoding="utf-8")
PAGES = ["elections.html", "journalists.html", "sources.html"]


def _h1(name):
    html = (C / "templates" / name).read_text(encoding="utf-8")
    m = re.search(r"<h1[^>]*>.*?</h1>", html, flags=re.S)
    assert m, f"{name}: no h1 found"
    return m.group(0)


def _size(markup, width):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser title checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser title checks did NOT run")
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.set_content(f"<!doctype html><meta name=viewport content='width=device-width'><style>{STYLE_CSS}</style>{markup}")
        out = page.evaluate("() => { const c = getComputedStyle(document.querySelector('h1')); return [c.fontSize, c.fontWeight, parseFloat(c.letterSpacing) / parseFloat(c.fontSize)]; }")
        browser.close()
        return out
    finally:
        pw.stop()


@pytest.mark.parametrize("name", PAGES)
def test_title_is_38px_on_desktop_and_30px_on_phone(name):
    size, weight, ls = _size(_h1(name), 1280)
    assert (size, weight) == ("38px", "600") and abs(ls + 0.015) < 0.001
    assert _size(_h1(name), 390)[0] == "30px"


def test_control_old_inline_30px_markup_reads_30px_on_desktop():
    old = '<h1 style="font-family:var(--wtf-font-serif);font-size:30px;font-weight:600;margin:0 0 4px;">T</h1>'
    assert _size(old, 1280)[0] == "30px"


@pytest.mark.parametrize("name", PAGES)
def test_no_inline_font_size_left_on_the_title(name):
    assert "font-size" not in _h1(name)
