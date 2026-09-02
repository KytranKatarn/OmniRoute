"""Guards for the homepage STYLESHEET half of the design (#6149, Phase 2).

Split from the markup guards (tests/test_home_design_markup.py) so each half
ships in the PR carrying the lines it guards — a source-asserting test in the
wrong half fails there and teaches the next person to delete it.

Each test pins a property that was ACTUALLY broken, not a restatement of the
CSS. All of them were run against a planted reintroduction of their own defect;
that exercise caught a vacuous assertion, noted inline below.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STYLE_CSS = ROOT / "consumer" / "static" / "style.css"


@pytest.fixture(scope="module")
def css() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def phase2(css: str) -> str:
    """Just the Phase 2 homepage block, so these assertions cannot be satisfied
    by some unrelated rule elsewhere in a 1,200-line stylesheet."""
    marker = "Phase 2: the HOMEPAGE"
    assert marker in css, "the Phase 2 homepage block is gone from style.css"
    return css[css.index(marker):]


def test_the_editorial_feed_split_collapses_on_a_phone(phase2: str):
    """#wtf-main was `display:flex` with no media query ANYWHERE, so a phone
    got a 38/62 squeeze instead of stacking. Verified before the change: the
    only rule was `#wtf-main { display:flex; min-height:400px; }`."""
    main = re.search(r"#wtf-main\s*\{[^}]*\}", phase2)
    assert main, "#wtf-main has no rule in the Phase 2 block"
    # Match the `display` declaration itself. A bare `"grid" in rule` check is
    # VACUOUS here — `grid-template-columns` keeps that substring present even
    # after display flips back to flex. (Caught by the non-vacuity run.)
    assert re.search(r"display:\s*grid\b", main.group(0)), (
        "#wtf-main must be display:grid"
    )

    collapse = re.search(
        r"@media\s*\(max-width:\s*960px\)\s*\{.*?#wtf-main\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)",
        phase2,
        re.S,
    )
    assert collapse, "#wtf-main must collapse to one column on a narrow viewport"


def test_headlines_are_serif(phase2: str):
    """The typography move. The old rules were 12px/14.5px sans on #e0e0e0 —
    swapping the palette alone never touched them."""
    for sel in (".wtf-card-title", ".wtf-top-story a"):
        rule = re.search(re.escape(sel) + r"\s*\{[^}]*\}", phase2)
        assert rule, f"{sel} has no rule in the Phase 2 block"
        assert "--wtf-font-serif" in rule.group(0), f"{sel} must be serif"


def test_the_lean_spectrum_is_never_a_literal(css: str):
    """Colour encodes data exactly once on this page: the card's left border.
    `.wtf-article-card--center` was a hardcoded #334455 while every sibling
    used a token — the page <style> block had been masking it, so removing
    that block would have silently darkened centre-lean cards."""
    for band in ("left", "center-left", "center", "center-right", "right"):
        rule = re.search(
            r"\.wtf-article-card--" + re.escape(band) + r"\s*\{[^}]*\}", css
        )
        assert rule, f"missing lean modifier for {band}"
        assert f"var(--wtf-{band})" in rule.group(0), (
            f".wtf-article-card--{band} must use var(--wtf-{band}), not a literal"
        )


def test_every_custom_property_the_homepage_uses_is_defined(css: str, phase2: str):
    """An undefined custom property with no fallback is an invalid declaration:
    the browser drops the whole line, silently."""
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", phase2))
    assert used, "no custom properties used — the block is probably empty"
    assert not (used - defined), f"undefined: {sorted(used - defined)}"
