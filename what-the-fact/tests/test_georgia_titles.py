"""The four hard-coded-Georgia pages now follow the mockup's type (task #6604, found by the design-port rig, PR #3829).

/governance, /creed, /literacy and the outlet page (source.html) set `font-family:Georgia,serif` literally, so their titles rendered in Georgia while
the mockup (and 32 of the 49 live pages) use Newsreader via var(--wtf-font-serif). The Georgia was left literal during a token sweep only to avoid
silently changing the rendered font, never because Georgia was the design. The mockup's outlet stat values are monospace, so those follow the mockup.

The browser checks run the REAL template CSS + style.css and read the computed font, once with the shipped CSS and once with the old Georgia put back.
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
T = C / "templates"
STYLE_CSS = (C / "static" / "style.css").read_text(encoding="utf-8")
PAGES = ["governance.html", "creed.html", "literacy.html", "source.html"]


def _template(name):
    return (T / name).read_text(encoding="utf-8")


def _style(name):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", _template(name), flags=re.S))


def _without_comments(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(r"\{#.*?#\}", "", css, flags=re.S)


@pytest.mark.parametrize("name", PAGES)
def test_no_hard_coded_georgia_declaration_remains(name):
    assert not re.search(r"font-family\s*:\s*Georgia", _without_comments(_template(name))), f"{name} still hard-codes Georgia"


# (template, class, expected first family)
CASES = [
    ("governance.html", "wtf-gv-title", "Newsreader"),
    ("governance.html", "wtf-gv-score-big", "Newsreader"),
    ("governance.html", "wtf-gv-pillar-score", "Newsreader"),
    ("creed.html", "wtf-cd-title", "Newsreader"),
    ("creed.html", "wtf-cd-quote", "Newsreader"),
    ("literacy.html", "wtf-lt2-title", "Newsreader"),
    ("literacy.html", "wtf-lt2-tip-h", "Newsreader"),
    ("source.html", "wtf-src-title", "Newsreader"),
    ("source.html", "wtf-src-stat-value", "IBM Plex Mono"),
]


def _computed_fonts(css, classes):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser font checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser font checks did NOT run")
        page = browser.new_page()
        body = "".join(f'<div class="{c}">x</div>' for c in classes)
        page.set_content(f"<!doctype html><style>{css}</style>{body}")
        out = page.evaluate(
            "(cs) => cs.map(c => getComputedStyle(document.querySelector('.' + c)).fontFamily.split(',')[0].replace(/[\"']/g, '').trim())", classes
        )
        browser.close()
        return dict(zip(classes, out))
    finally:
        pw.stop()


@pytest.mark.parametrize("name", PAGES)
def test_computed_fonts_follow_the_mockup(name):
    cases = [(c, f) for n, c, f in CASES if n == name]
    got = _computed_fonts(STYLE_CSS + "\n" + _style(name), [c for c, _ in cases])
    for cls, want in cases:
        assert got[cls] == want, f"{name} .{cls}: {got[cls]!r}, mockup uses {want!r}"


def test_the_old_georgia_css_would_have_failed_these_checks():
    """Control: put Georgia back on the governance title and the same check must see it, or the checks above prove nothing."""
    css = _style("governance.html")
    assert "font-family:var(--wtf-font-serif); font-size:1.8rem" in css
    old = css.replace("font-family:var(--wtf-font-serif); font-size:1.8rem", "font-family:Georgia,serif; font-size:1.8rem")
    assert _computed_fonts(STYLE_CSS + "\n" + old, ["wtf-gv-title"])["wtf-gv-title"] == "Georgia"


def test_templates_still_compile():
    import jinja2

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(T)))
    for name in PAGES:
        env.get_template(name)
