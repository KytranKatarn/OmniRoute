"""Page titles on 7 header pages (municipal, economy, ethics, markets, chain, cross-watch, entity) follow the mockup's type (task #6604, found by the design-port rig, PR #3829).

The mockup sets every page title in Newsreader, 38px / 600 with -.015em tracking (person names 31px / -.022em, the article headline -.026em). Live
used IBM Plex Mono on /municipal /ethics /economy /markets /chain /cross-watch /mp /senator and IBM Plex Sans on /claims /api /methodology /article
/weather/accuracy, mostly 18-26px bold. The computed style of each title is read from the REAL template CSS + style.css in a real browser, at desktop
and phone width (phones step down: the mockup has no phone rule and 38px takes three lines on 390px).
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
T = C / "templates"
STYLE_CSS = (C / "static" / "style.css").read_text(encoding="utf-8")


def _style(name):
    html = (T / name).read_text(encoding="utf-8")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S))
    # The server renders Jinja; the browser here would see {% if %} / {{ x }} as CSS garbage and drop the rule that follows it.
    return re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", "", css, flags=re.S)


# (template, markup for the title, desktop px, phone px, letter-spacing em)
CASES = [
    ("municipal.html", '<h1 class="wtf-mu-page-title">T</h1>', 38, 30, -0.015),
    ("economy.html", '<h1 class="wtf-ec-page-title">T</h1>', 38, 30, -0.015),
    ("ethics.html", '<h1 class="wtf-eth-title">T</h1>', 38, 30, -0.015),
    ("markets.html", '<h1 class="mk-h1">T</h1>', 38, 30, -0.015),
    ("chain.html", '<h1 class="chain-title">T</h1>', 38, 30, -0.015),
    ("cross_watch.html", '<h1 class="wtf-cw-title">T</h1>', 38, 30, -0.015),
    ("entity.html", '<h1 class="wtf-cw-title">T</h1>', 38, 30, -0.015),
]
IDS = [c[0] for c in CASES]


def _computed(css, markup, width):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser title checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser title checks did NOT run")
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.set_content(f"<!doctype html><meta name=viewport content='width=device-width'><style>{css}</style>{markup}")
        out = page.evaluate(
            "() => { const c = getComputedStyle(document.querySelector('h1')); return {font: c.fontFamily.split(',')[0].replace(/[\"']/g, '').trim(),"
            " size: c.fontSize, weight: c.fontWeight, ls: parseFloat(c.letterSpacing) / parseFloat(c.fontSize)}; }"
        )
        browser.close()
        return out
    finally:
        pw.stop()


@pytest.mark.parametrize("name,markup,desktop,phone,tracking", CASES, ids=IDS)
def test_title_matches_the_mockup_on_desktop_and_steps_down_on_a_phone(name, markup, desktop, phone, tracking):
    css = STYLE_CSS + "\n" + _style(name)
    big = _computed(css, markup, 1280)
    assert big["font"] == "Newsreader", f"{name}: title font {big['font']!r}, mockup uses Newsreader"
    assert big["weight"] == "600", f"{name}: weight {big['weight']}"
    assert big["size"] == f"{desktop}px", f"{name}: desktop size {big['size']}, mockup {desktop}px"
    assert abs(big["ls"] - tracking) < 0.002, f"{name}: tracking {big['ls']:.4f}em, mockup {tracking}em"
    small = _computed(css, markup, 390)
    assert small["size"] == f"{phone}px", f"{name}: phone size {small['size']}, expected {phone}px"
    assert small["font"] == "Newsreader"


def test_the_old_mono_styling_would_have_failed_these_checks():
    """Control: put the old mono title back on /ethics and the same read must see it, or the checks above prove nothing."""
    css = _style("ethics.html")
    old = re.sub(r"\.wtf-eth-title \{[^}]*\}", ".wtf-eth-title { font-family:var(--wtf-font-mono); font-size:20px; color:#e5e7eb; margin:0 0 6px; }", css, count=1)
    assert old != css
    got = _computed(STYLE_CSS + "\n" + old, '<h1 class="wtf-eth-title">T</h1>', 1280)
    assert got["font"] == "IBM Plex Mono" and got["size"] == "20px"


def test_the_two_all_caps_titles_are_sentence_case_like_the_mockup():
    muni = (T / "municipal.html").read_text(encoding="utf-8")
    econ = (T / "economy.html").read_text(encoding="utf-8")
    assert "Municipal &amp; local government</h1>" in muni and "MUNICIPAL &amp; LOCAL GOVERNMENT" not in muni
    assert "Economy &amp; Markets</h1>" in econ and "ECONOMY &amp; MARKETS" not in econ


def test_every_template_in_this_group_compiles():
    import jinja2

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(T)))
    for name in IDS:
        env.get_template(name)
