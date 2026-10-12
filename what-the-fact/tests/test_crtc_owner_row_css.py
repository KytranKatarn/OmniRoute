"""/crtc ownership-concentration rows: the per-owner stat column must fit its content.

It was `width:60px` against content that measures up to ~187px live ("9 outlets · -0.22
[CENTER LEFT]"), so every row wrapped to three lines (62px tall beside a 12px bar) and the lean
chip split "CENTER / LEFT". Source-level guard on the template's own <style>; the rendered
before/after (62px -> 23px rows at 1280px, no horizontal scroll at 400px) was measured in Chrome.
"""

import pathlib
import re

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates" / "crtc.html"


def _rule(selector_re):
    css = TPL.read_text()
    # the base (non-media) rule is the first match
    m = re.search(selector_re + r"\s*\{([^}]*)\}", css)
    assert m, "rule not found: " + selector_re
    return m.group(1)


def test_stat_column_is_wide_enough_for_its_content():
    body = _rule(r"\.wtf-crtc-own-stat")
    w = re.search(r"(?<![-\w])width\s*:\s*(\d+)px", body)
    assert w, "stat column needs an explicit px width"
    assert int(w.group(1)) >= 160, "stat column is narrower than its content and will wrap"


def test_stat_column_and_chip_do_not_wrap():
    assert "white-space:nowrap" in _rule(r"\.wtf-crtc-own-stat").replace(" ", "")
    assert "white-space:nowrap" in _rule(r"\.wtf-crtc-own-stat\s+\.wtf-a-chip").replace(" ", "")


def test_narrow_screens_stack_the_stat_instead_of_squeezing_the_bar():
    css = TPL.read_text().replace(" ", "")
    assert "@media(max-width:640px)" in css
    assert ".wtf-crtc-own-row{flex-wrap:wrap" in css
