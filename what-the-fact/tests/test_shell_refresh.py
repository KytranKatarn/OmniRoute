"""Guard: the Phase 1 shell refresh (#6149 follow-on / Design handoff).

Pure file reads — no app, no DB, no network — so this cannot silently SKIP.

🔴 THE LOAD-BEARING TEST IS test_no_css_variable_is_used_without_being_defined.
An undefined custom property with no fallback is an INVALID declaration: the
browser drops the whole line and paints nothing, with no error anywhere. That is
exactly what nearly shipped here — the handoff uses `var(--wtf-brand)` 201 times
and our stylesheet had NO --wtf-brand at all, so the focus ring would have been
invisible while the CSS "looked" correct in review.
"""
from __future__ import annotations

import pathlib
import re

_CSS = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "static" / "style.css"


def _css() -> str:
    return _CSS.read_text()


# ------------------------------------------------- 🔴 the class-level guard

def test_no_css_variable_is_used_without_being_defined():
    """Generalises beyond this change: ANY var() must resolve, or it paints nothing.

    Only flags bare `var(--x)`. `var(--x, fallback)` is legitimate precisely
    because it survives the property being undefined.
    """
    css = _css()
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    bare_used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*\)", css))
    missing = sorted(bare_used - defined)
    assert not missing, f"used with no definition and no fallback: {missing}"


def test_brand_token_exists():
    """The specific instance of the above. The handoff leans on it heavily."""
    assert re.search(r"--wtf-brand\s*:\s*#14bef0", _css()), "--wtf-brand must be defined"


# ------------------------------------------------------ accessibility floor

def test_a_visible_keyboard_focus_ring_exists():
    """Before this change the stylesheet had TWO :focus rules, both :focus-within
    on the nav dropdown — keyboard users had no ring anywhere else on the site."""
    css = _css()
    assert ":focus-visible" in css
    assert "outline-offset" in css


def test_reduced_motion_is_honoured():
    """The handoff's live pill blinks forever; there was no reduced-motion block."""
    css = _css()
    assert "prefers-reduced-motion" in css
    m = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}", css, re.DOTALL)
    assert m, "reduced-motion block not found"
    assert "animation-duration" in m.group(1) and "transition-duration" in m.group(1)


# ------------------------------------------------- ⚠️ the documented trap

def test_the_nav_is_never_given_overflow():
    """A scroll container cannot have visible overflow on the other axis, so one
    `overflow-x:auto` on the nav silently clips EVERY dropdown. The guard rule
    must stay, and nothing may set a non-visible overflow on those selectors."""
    css = _css()
    assert re.search(r"\.wtf-nav[^{]*\{[^}]*overflow:\s*visible", css), "clipping guard missing"
    for sel in (r"\.wtf-nav", r"\.wtf-navgrp", r"\.wtf-nav-links"):
        for block in re.findall(sel + r"[^{]*\{([^}]*)\}", css):
            bad = re.search(r"overflow(-x|-y)?:\s*(auto|hidden|scroll)", block)
            assert not bad, f"{sel} sets {bad.group(0)!r} — this clips the dropdowns"


# ---------------------------------------------------------- typography

def test_optical_sizing_is_on():
    """base.html already requests Newsreader's opsz 6..72 axis; without this
    declaration the browser never uses it."""
    assert re.search(r"html\s*\{[^}]*font-optical-sizing:\s*auto", _css())


def test_numerals_do_not_jitter():
    assert "tabular-nums" in _css()
