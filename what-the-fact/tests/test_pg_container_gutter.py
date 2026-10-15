"""The shared page container must not apply the --gut gutter twice (found live 2026-10-15: /team and /weather collapsed to a 440px strip at 1920 wide,
and to ~30px at 2560).

--gut = max(18px, (100vw - 1180px) / 2): the padding that pushes a FULL-WIDTH band into a centred 1180px column. A box that is already centred by
max-width + margin:auto must use a fixed side padding instead, or its content width falls as the screen widens.
"""

import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1] / "consumer" / "static" / "style.css").read_text(encoding="utf-8")
RULE = re.compile(r"(?m)^([^\s{}/@][^{}]*)\{([^{}]*)\}")


def _rule(selector):
    for m in RULE.finditer(CSS):
        if m.group(1).strip() == selector:
            return m.group(2)
    raise AssertionError(f"{selector} not found")


def _content_width(viewport, body):
    """Content-box width of a self-centred max-width box with side padding `p` (fixed px), at a given viewport width."""
    maxw = int(re.search(r"max-width:\s*(\d+)px", body).group(1))
    pad = int(re.search(r"padding:\s*\d+px\s+(\d+)px", body).group(1))
    return min(maxw, viewport) - 2 * pad


def test_page_container_does_not_use_the_full_bleed_gutter():
    body = _rule(".wtf-pg-container")
    assert "--gut" not in body, "the container already centres itself; --gut would pad it a second time"


def test_content_width_never_shrinks_as_the_screen_widens():
    body = _rule(".wtf-pg-container")
    widths = [_content_width(v, body) for v in (1024, 1280, 1440, 1920, 2560, 3840)]
    assert widths == sorted(widths), widths
    assert min(widths[1:]) >= 1000, f"a desktop-width page must keep a usable column: {widths}"


def test_no_self_centred_box_pads_itself_with_the_gutter():
    """Generic guard: any rule that both centres itself (max-width + margin auto) and pads with var(--gut) repeats the bug."""
    bad = []
    for m in RULE.finditer(CSS):
        body = m.group(2)
        if "max-width" in body and re.search(r"margin:\s*[^;]*\bauto\b", body) and re.search(r"padding[^;]*var\(--gut\)", body):
            bad.append(m.group(1).strip())
    assert not bad, f"self-centred boxes padded with --gut: {bad}"


def test_full_width_bands_still_use_the_gutter():
    """The variable is right for bands with no max-width; do not strip it from them."""
    assert "padding: 0 var(--gut)" in _rule(".wtf-nav")
