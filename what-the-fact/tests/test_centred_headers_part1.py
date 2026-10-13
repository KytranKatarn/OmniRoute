"""Page headers are centred as in the mockup, part 1 of 3: governance, score, chain, cross-watch, elections (task #6604).

The rig's corrected alignment check (the text's own first line, not the heading's box) found 18 pages whose title is left-aligned where the mockup
centres it. `.wtf-pg-centre` (style.css) is the one shared helper: on a header WRAPPER it centres the label, title and intro together; on individual
elements it centres just those. The behaviour is tested in a real browser against the real helper CSS, with a control that has no class and must
stay left; the templates are checked for the class on the right element.
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
STYLE_CSS = (C / "static" / "style.css").read_text(encoding="utf-8")
T = C / "templates"


def _tpl(name):
    return (T / name).read_text(encoding="utf-8")


# ---- templates: the class is on the right element ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "template,needle",
    [
        ("governance.html", '<div class="wtf-gv-header wtf-pg-centre">'),
        ("score.html", '<header class="wtf-score-head wtf-pg-centre">'),
        ("chain.html", '<div class="chain-head wtf-pg-centre">'),
        ("cross_watch.html", '<h1 class="wtf-cw-title wtf-pg-centre">'),
        ("cross_watch.html", '<p class="wtf-cw-intro wtf-pg-centre">'),
        ("elections.html", '<div class="wtf-pg-centre" style="padding:16px 0;border-bottom:1px solid var(--wtf-border);margin-bottom:16px;">'),
    ],
)
def test_template_marks_its_header_for_centring(template, needle):
    assert needle in _tpl(template)


def test_the_helper_exists_once_and_beats_an_inline_margin():
    assert STYLE_CSS.count(".wtf-pg-centre { text-align:center; }") == 1
    assert re.search(r"p\.wtf-pg-centre, \.wtf-pg-centre > p[^{]*\{[^}]*margin-left:auto !important; margin-right:auto !important;", STYLE_CSS)


# ---- real browser: the helper centres, a header without it stays left ---------------------------------------------------------------------
def _measure(body, width=1280):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser centring checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser centring checks did NOT run")
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.set_content(f"<!doctype html><style>body{{margin:0}}{STYLE_CSS}</style><div id=c style='max-width:900px;margin:0 auto'>{body}</div>")
        out = page.evaluate(
            """() => { const c = document.getElementById('c').getBoundingClientRect(); const cx = c.left + c.width / 2;
              const mid = (e) => { const r = document.createRange(); r.selectNodeContents(e); const q = r.getClientRects()[0]; return Math.abs(q.left + q.width / 2 - cx); };
              const p = document.querySelector('p'); const pr = p && p.getBoundingClientRect();
              return { h1: Math.round(mid(document.querySelector('h1'))), eyebrow: Math.round(mid(document.querySelector('.eb'))),
                       lede: p ? Math.round(mid(p)) : null, ledeBlock: pr ? Math.round(Math.abs(pr.left + pr.width / 2 - cx)) : null, over: document.documentElement.scrollWidth - innerWidth }; }"""
        )
        browser.close()
        return out
    finally:
        pw.stop()


WRAPPED = '<div class="{c}"><div class="eb">SHARED ENTITY GRAPH</div><h1>Accountability Chain Explorer</h1><p style="max-width:360px;margin:0">Follow the money through public life, from a donation to the contract it shadows.</p></div>'
ELEMENTS = '<div class="eb {c}">Label</div><h1 class="{c}">Cross-Watch</h1><p class="{c}" style="max-width:360px;margin:0">People and organizations resolved across the Watch Series.</p>'


def test_a_wrapper_centres_its_label_title_and_intro_together():
    m = _measure(WRAPPED.format(c="wtf-pg-centre"))
    assert m["h1"] <= 2 and m["eyebrow"] <= 2 and m["lede"] <= 3, m
    assert m["ledeBlock"] <= 2, "the max-width intro must be centred as a BLOCK despite its inline margin:0"
    assert m["over"] <= 1


def test_individual_elements_centre_when_there_is_no_wrapper():
    m = _measure(ELEMENTS.format(c="wtf-pg-centre"))
    assert m["h1"] <= 2 and m["eyebrow"] <= 2 and m["ledeBlock"] <= 2, m


def test_without_the_class_the_same_header_is_left_aligned():
    """Control: the checks above must be able to fail."""
    assert _measure(WRAPPED.format(c="plain"))["h1"] > 150
    assert _measure(ELEMENTS.format(c="plain"))["ledeBlock"] > 100


def test_the_header_still_centres_on_a_phone_without_overflow():
    m = _measure(WRAPPED.format(c="wtf-pg-centre"), width=390)
    assert m["over"] <= 1 and m["h1"] <= 2
