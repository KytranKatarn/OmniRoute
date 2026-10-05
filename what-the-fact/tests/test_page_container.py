"""Page container — 13 pages ran edge to edge because nothing wrapped their content.

base.html's <main> is a bare element. A page that does not wrap itself in a container
renders with its left-aligned title flush at x=0, cards touching the viewport edge and
(on /weather) a horizontal scrollbar. A live layout audit on 2026-10-05 measured 41 pages
at 1280px: 13 had no container at all; several of those were marked `reconciled` in
design-handoff/PORT-STATUS.md without ever being looked at.

These tests pin the fix at the level that actually regressed: the wrapper must ENCLOSE the
whole content block (an unbalanced or partial wrapper would still "contain" a title while
leaving the rest of the page edge to edge) and the CSS must be the design shell's `.wrap`.
Previewed in a real browser before the templates were edited: with this wrapper, none of the
13 pages overflowed at 1280, 1440, 768 or 390px.
"""
from __future__ import annotations

import pathlib
import re
from html.parser import HTMLParser

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TPL = ROOT / "consumer" / "templates"
CSS = (ROOT / "consumer" / "static" / "style.css").read_text(encoding="utf-8")
DESIGN_SHELL = (ROOT / "design-handoff" / "wtf-shell.css").read_text(encoding="utf-8")

WRAPPED = ["municipal", "economy", "weather", "divergence", "lobbying", "gic", "ethics", "officers", "elections",
           "rates", "markets", "owners", "journalists", "crtc", "cross_watch"]

_OPEN = re.compile(r"\{%-?\s*block content\s*-?%\}")
_CLOSE = re.compile(r"\{%-?\s*endblock[^%]*%\}")


def _content_block(name: str) -> str:
    src = (TPL / f"{name}.html").read_text(encoding="utf-8")
    opens = _OPEN.findall(src)
    assert len(opens) == 1, f"{name}: expected exactly one content block, found {len(opens)}"
    m = _OPEN.search(src)
    c = _CLOSE.search(src, m.end())
    assert c, f"{name}: content block is never closed"
    # Jinja comments can quote markup (`<div>` in prose) — they are not part of the page.
    return re.sub(r"\{#.*?#\}", "", src[m.end():c.start()], flags=re.S)


class _Divs(HTMLParser):
    """Tracks <div> depth. <script>/<style> bodies are not parsed as tags, so markup
    inside JS strings does not skew the count."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.first_class, self.min_depth, self.closed_wrapper_at = 0, None, 0, None
        self.zero_crossings = 0
        self.n_tags = self.tag_idx = 0

    def handle_starttag(self, tag, attrs):
        self.tag_idx += 1
        if tag == "div":
            if self.first_class is None:
                self.first_class = dict(attrs).get("class")
            self.depth += 1

    def handle_endtag(self, tag):
        self.tag_idx += 1
        if tag == "div":
            self.depth -= 1
            self.min_depth = min(self.min_depth, self.depth)
            if self.depth == 0:
                self.closed_wrapper_at = self.tag_idx
                self.zero_crossings += 1


def _parse(name: str) -> _Divs:
    p = _Divs()
    p.feed(_content_block(name))
    p.close()
    p.n_tags = p.tag_idx
    return p


class TestEveryFlaggedPageIsContained:
    @pytest.mark.parametrize("name", WRAPPED)
    def test_the_first_element_is_the_page_wrapper(self, name):
        p = _parse(name)
        assert p.first_class and "wtf-pg-container" in p.first_class.split(), (
            f"{name}.html: content does not open with <div class=\"wtf-pg-container\"> — it will run "
            f"edge to edge (left-aligned title at x=0, no side margin)")

    @pytest.mark.parametrize("name", WRAPPED)
    def test_the_wrapper_encloses_the_whole_content_block(self, name):
        p = _parse(name)
        assert p.depth == 0 and p.min_depth == 0, f"{name}.html: unbalanced <div>s in the content block"
        # Depth must return to 0 EXACTLY ONCE, and on the LAST tag: the wrapper closes at the very
        # end, so nothing sits outside it. Checking only "the last close is at the end" is not
        # enough — a wrapper that closed early followed by a second top-level <div> also ends at
        # depth 0, and would leave everything between them uncontained (caught by mutation M2).
        assert p.zero_crossings == 1 and p.closed_wrapper_at == p.n_tags, (
            f"{name}.html: the wrapper closes before the end of the content block — "
            f"everything after it is uncontained")


class TestTheCssIsTheDesignShellsContainer:
    @staticmethod
    def _rule(css: str, selector: str) -> str:
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert m, f"{selector} is not defined"
        return re.sub(r"\s+", "", m.group(1))

    def test_wtf_wrap_is_defined_with_the_design_values(self):
        live = self._rule(CSS, ".wtf-pg-container")
        design = self._rule(DESIGN_SHELL, ".wrap")
        assert "max-width:1180px" in live and "max-width:1180px" in design
        assert "margin:0auto" in live and "margin:0auto" in design
        # The design pads with the shared gutter token; a fixed px padding would not track it.
        assert "padding:26pxvar(--gut)60px" in live and "padding:26pxvar(--gut)60px" in design

    def test_the_gutter_token_it_depends_on_exists(self):
        assert re.search(r"--gut\s*:\s*max\(18px,\s*calc\(\(100vw\s*-\s*1180px\)\s*/\s*2\)\)", CSS), (
            "--gut is missing or changed; .wtf-pg-container pads with it")

    def test_the_older_1080_wrapper_is_untouched(self):
        # blindspot/echo/clusters/debt/global use it; this change must not alter them.
        assert "max-width:1080px" in self._rule(CSS, ".wtf-pg-wrap")


def test_pages_that_already_had_a_wrapper_were_not_double_wrapped():
    for name in ("blindspot", "echo", "clusters", "debt", "global"):
        src = (TPL / f"{name}.html").read_text(encoding="utf-8")
        assert "wtf-pg-wrap" in src and 'class="wtf-pg-container"' not in src, name


class TestTeamKeepsItsFullBleedHero:
    """/team has a deliberately full-bleed hero band; only what FOLLOWS it is contained. Wrapping the
    whole block would shrink the hero, and wrapping nothing left the section label at x=0 while the
    card grid sat inset (seen live 2026-10-05)."""

    def test_container_opens_after_the_hero_and_closes_at_the_end(self):
        src = _content_block("team")
        hero = re.search(r'<div class="wtf-team-hero">.*?\n</div>\n', src, re.S)
        assert hero, "team hero block not found"
        assert "wtf-pg-container" not in src[: hero.end()], "the hero must stay outside the container"
        assert src[hero.end():].lstrip().startswith('<div class="wtf-pg-container">')
        assert src.rstrip().endswith("</div>"), "container must close at the end of the content block"
