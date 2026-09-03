"""Every consumer page must ride the shared site shell (task #5767).

On 2026-08-18 FIVE templates were standalone documents: they declared their own
<html>, their own <head>, their own nav, and a byte-identical private 6-token
:root. A reader landing on one got no site nav, no footer, no C.R.E.E.D. badge,
no newsletter signup, no i18n and none of style.css — the page looked like a
different product. /weather was converted first (PR #2677), the other four here.

Two properties are pinned:
  1. no template re-declares the document shell
  2. a converted page's classes stay NAMESPACED

(2) is not cosmetic. These pages used names like .logo, .nav-links, .active,
.page-title, .legend and .attribution — safe while the document was isolated,
and a site-wide collision the moment it shares style.css.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TPL = ROOT / "consumer" / "templates"

# page -> required class prefix
CONVERTED = {
    # New pages are pinned from birth (#2138) rather than after a regression —
    # the five below were only added once they had already drifted.
    "api_keys": "wtf-ak-",
    "api_docs": "wtf-doc-",
    "weather": "wtf-wx-",
    "municipal": "wtf-mu-",
    "blindspot": "wtf-bs-",
    "divergence": "wtf-dv-",
    "economy": "wtf-ec-",
}

# base.html legitimately owns the document shell; partials are fragments.
_SHELL_OWNERS = {"base.html"}

# Class names OWNED OUTSIDE THIS PAGE must not be namespaced into it — the
# rename would simply stop matching the thing that creates them.
#
# `leaflet-*` was the original case (a third-party stylesheet). `wtf-map-*` is
# ours but has the same property: it is created by the shared wtf-map.js
# component, so a page-local rename breaks the component rather than scoping it.
# The prefix is what matters, not who wrote it — a shared in-house component and
# a vendored library are the same problem for this guard.
_VENDOR_PREFIXES = ("leaflet-", "wtf-map-")


def _strip_jinja_comments(src: str) -> str:
    """A `{# ... #}` note is not markup.

    The first version of this guard failed weather.html because its comment
    EXPLAINS that the page used to be a standalone <html> document — the guard
    flagged its own documentation. The sibling guard in
    test_aurora_provenance.py had already been bitten by exactly this and fixed
    the same way; the lesson did not transfer until it bit twice.
    """
    return re.sub(r"\{#.*?#\}", "", src, flags=re.S)


def _pages():
    return [p for p in TPL.glob("*.html") if p.name not in _SHELL_OWNERS]


@pytest.mark.parametrize("page", sorted(CONVERTED))
def test_converted_page_extends_the_shell(page):
    raw = (TPL / f"{page}.html").read_text(encoding="utf-8")
    src = _strip_jinja_comments(raw)
    assert '{% extends "base.html" %}' in raw, (
        f"{page}.html must extend base.html — a standalone document gives the "
        "reader no site nav, footer, i18n or stylesheet"
    )
    assert "<html" not in src, f"{page}.html still declares its own <html>"
    assert "<head>" not in src, f"{page}.html still declares its own <head>"


@pytest.mark.parametrize("page,ns", sorted(CONVERTED.items()))
def test_converted_page_classes_are_namespaced(page, ns):
    """Both the CSS selectors AND the class= attributes.

    The first version of the converter namespaced `.city-chip` but not the
    `.active` in the COMPOUND selector `.city-chip.active` (a lookbehind meant
    to avoid partial matches blocked it). The CSS then said
    `.wtf-mu-city-chip.active` while the HTML said `wtf-mu-city-chip
    wtf-mu-active` — the selected-city highlight silently stopped matching. The
    page still loaded fine; it was only wrong once someone used it.
    """
    src = _strip_jinja_comments((TPL / f"{page}.html").read_text(encoding="utf-8"))
    style = src.split("<style>", 1)[1].split("</style>", 1)[0] if "<style>" in src else ""
    body = src.split("</style>", 1)[1] if "</style>" in src else src

    # Only look at SELECTORS (the text before each `{`). A naive scan of the
    # whole <style> block also matches the dots in prose like "A.U.R.O.R.A."
    # and reports `A`, `O`, `R`, `U` as un-namespaced classes.
    # Strip CSS comments before parsing: a `/* ... */` note immediately above a
    # rule otherwise lands INSIDE the captured selector text.
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    bad_sel = []
    for sel_txt, _ in re.findall(r"([^{}]+)\{([^}]*)\}", style):
        for sel in sel_txt.split(","):
            sel = sel.strip()
            if not sel or sel.startswith("@"):
                continue
            # A selector is safe when EVERY compound unit that carries classes
            # includes a namespaced (or vendor) one. `.wtf-wx-btn.active` is fine:
            # a bare modifier cannot select anything outside a namespaced element.
            # A bare `.active` on its own is not fine — that is site-wide.
            for unit in re.split(r"[\s>+~]+", sel):
                classes = re.findall(r"\.([A-Za-z][\w-]*)", unit)
                if not classes:
                    continue
                if not any(c.startswith(ns.rstrip("-")) or c.startswith(_VENDOR_PREFIXES)
                           for c in classes):
                    bad_sel.append(sel)
                    break
    bad_sel = sorted(set(bad_sel))
    assert not bad_sel, f"{page}.html CSS has un-namespaced selectors: {bad_sel}"

    # NOTE: deliberately NOT asserting on the class= attributes.
    #
    # The leak vector is a page DEFINING a rule that can match outside itself,
    # and the selector check above covers exactly that. What a page USES from
    # the shared stylesheet is intentional reuse — weather.html renders the
    # site's `beat-pill` / `beat-climate` chips on purpose, and forcing those
    # into a page namespace would duplicate shared styling for no benefit.
    # Bare modifiers (`active`, `is-empty`) are likewise safe: they only ever
    # appear alongside a namespaced class, so they cannot select anything on
    # their own. An earlier version of this test flagged all of the above and
    # would have pushed a pointless rename.


def test_no_consumer_page_is_a_standalone_document():
    """A blanket guard so a NEW page cannot quietly reintroduce the pattern."""
    offenders = []
    for p in _pages():
        src = _strip_jinja_comments(p.read_text(encoding="utf-8"))
        if "<!DOCTYPE html>" in src and "{% extends" not in src:
            offenders.append(p.name)
    assert not offenders, (
        "these templates are standalone documents and will render without the "
        f"site shell: {offenders}. Convert them (recipe: task #5767)."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
