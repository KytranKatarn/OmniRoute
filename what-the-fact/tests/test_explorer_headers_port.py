"""Shared page header + container (PORT-STATUS rows 12 & 14, slice a). Generic .wtf-pg-* classes so
the remaining data pages reuse them. Template comments are stripped: assert markup only."""
import re
from pathlib import Path

C = Path(__file__).resolve().parents[1] / "consumer"
CSS = (C / "static" / "style.css").read_text(encoding="utf-8")


def markup(name):
    raw = (C / "templates" / name).read_text(encoding="utf-8")
    return raw, re.sub(r"\{#.*?#\}", "", raw, flags=re.S)


PAGES = {
    "blindspot.html": ("What one side is not seeing", "Blindspot"),
    "clusters.html": ("I.N.K. &middot; one event, many tellings", "Story clusters"),
}


def test_each_page_uses_the_design_header():
    for name, (eyebrow, title) in PAGES.items():
        _, m = markup(name)
        assert f'class="wtf-pg-eyebrow">{eyebrow}<' in m, name
        assert f'<h1 class="wtf-pg-title">{title}</h1>' in m, name


def test_each_page_is_wrapped_exactly_once():
    for name in PAGES:
        raw, m = markup(name)
        assert m.count('<div class="wtf-pg-wrap">') == 1 and "{# /.wtf-pg-wrap #}" in raw, name


def test_old_left_aligned_headers_are_gone():
    _, bs = markup("blindspot.html")
    _, cl = markup("clusters.html")
    assert "wtf-bs-header" not in bs and "wtf-bs-title" not in bs
    assert 'style="padding:16px 0;border-bottom' not in cl


def test_blindspot_keeps_its_definition_and_adds_the_not_suppression_caveat():
    _, m = markup("blindspot.html")
    assert "A left blindspot means right-leaning outlets stayed quiet" in m
    assert "not proof that a story is being suppressed" in m


def test_css_block_is_generic_and_scoped():
    block = CSS[CSS.index("Generic page header + container"):]
    for sel in re.findall(r"^(\.[\w-]+[^{]*)\{", block, re.M):
        assert sel.strip().startswith(".wtf-pg-"), sel
