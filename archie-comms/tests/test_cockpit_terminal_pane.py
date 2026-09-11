"""The Terminal pane must not repeat the Phase 4b grid-cell defect, or blur the two lanes.

Two things this file exists to stop:

1. THE SHARED GRID CELL. `#pane-terminal` sits in the SAME cell as `#pane-builder`
   (grid-column 2 at >=768, column 3 at >=1024). In Phase 4b the equivalent pair put two
   panes in one cell after a resize, and a grid ITEM carrying a non-auto z-index paints as
   if positioned even at `position: static` — so the later element in DOM order silently
   covered a full-width button. Measured then: 4 of 10 sampled points across "Create task"
   returned the wrong element. The bare-id `display: none` default is what prevents it.

2. THE HOST/SANDBOX LABEL. The claude lane is the HOST shell with no container boundary;
   codex is a container. Spec section 6 calls this the most important label on the page,
   because the two lanes look identical otherwise and their blast radii are not.
"""

import os
import re

import pytest

COMMS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE = os.path.join(COMMS, "templates", "cockpit.html")
CSS = os.path.join(COMMS, "static", "css", "cockpit.css")
JS = os.path.join(COMMS, "static", "js", "cockpit.js")

pytestmark = pytest.mark.skipif(
    not os.path.exists(TEMPLATE), reason=f"cockpit.html not reachable at {TEMPLATE}"
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _media_block(css: str, min_width: str) -> str:
    """The body of `@media (min-width: N)` — brace-matched, not line-sliced.

    A naive split on the next '@media' would stop at a nested at-rule and silently return a
    truncated block, which reads as "the rule is missing" and would fail for the wrong reason.
    """
    marker = f"@media (min-width: {min_width})"
    start = css.index(marker) + len(marker)
    start = css.index("{", start)
    depth, i = 0, start
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start : i + 1]
        i += 1
    raise AssertionError(f"unterminated media block for {min_width}")


# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------


def test_the_terminal_pane_exists():
    assert 'id="pane-terminal"' in _read(TEMPLATE)


def test_the_phone_tab_exists():
    """Below 768 the tab bar is the ONLY way to reach a pane (.ck-tabs is the phone nav)."""
    assert 'data-pane="terminal"' in _read(TEMPLATE)


def test_the_right_column_switcher_exists_in_both_panes():
    """At >=768 the tab bar is display:none, so the switcher is the only desktop affordance.

    It must appear in BOTH panes: whichever one is showing has to offer the way back.
    """
    html = _read(TEMPLATE)
    assert html.count('data-right="terminal"') >= 2, (
        "the Builder pane needs a way INTO the terminal and the Terminal pane needs to stay switchable"
    )
    assert html.count('data-right="builder"') >= 2


def test_exactly_one_iframe_slot():
    """One slot whose src is swapped — never two live terminals, never a second host shell."""
    html = _read(TEMPLATE)
    terminal = html[html.index('id="pane-terminal"') :]
    terminal = terminal[: terminal.index("</section>")]
    assert terminal.count("<iframe") == 1, "the pane must hold exactly one iframe slot"


def _lane_button(html: str, lane: str) -> str:
    """Just that lane's <button>…</button>.

    Scoped deliberately: a fixed-size window runs past the button into its NEIGHBOUR, and
    would read the other lane's label as this one's (that mistake passed a 400-char window
    while the markup was correct).
    """
    start = html.index(f'data-lane="{lane}"')
    start = html.rindex("<button", 0, start)
    return html[start : html.index("</button>", start)]


def test_the_claude_lane_is_marked_as_the_host():
    """The label that matters: claude has NO container boundary."""
    html = _read(TEMPLATE)
    claude = _lane_button(html, "claude")
    codex = _lane_button(html, "codex")
    assert "HOST" in claude, "the claude lane must carry a visible host marker"
    assert "sandbox" not in claude.lower(), "the claude lane must NOT be described as sandboxed"
    assert "sandbox" in codex.lower(), "the codex lane must be marked sandboxed"
    assert "HOST" not in codex, "only the claude lane is the host"


def test_the_iframe_is_not_auto_mounted():
    """A host shell must not open itself on page load — the owner opens it deliberately."""
    html = _read(TEMPLATE)
    terminal = html[html.index('id="pane-terminal"') :]
    terminal = terminal[: terminal.index("</section>")]
    iframe = terminal[terminal.index("<iframe") :]
    iframe = iframe[: iframe.index(">") + 1]
    assert 'src="' not in iframe or 'src=""' in iframe or "about:blank" in iframe, (
        "the iframe must start empty; mountLane() sets src after an explicit Open"
    )


# ---------------------------------------------------------------------------
# The CSS invariant — the Phase 4b regression guard
# ---------------------------------------------------------------------------


def test_pane_terminal_is_hidden_by_default_in_the_desktop_block():
    """The bare-id form (0,1,0,0) — NOT a :not() form.

    It must lose to `body.ck-right-terminal #pane-terminal` (0,1,1,1) and beat a stale
    `.ck-show` (0,0,2,0) left over from the phone tab switch, regardless of source order.
    """
    block = _media_block(_read(CSS), "768px")
    assert re.search(r"#pane-terminal\s*\{\s*display:\s*none", block), (
        "#pane-terminal must default to display:none inside the >=768 block, or a stale "
        ".ck-show puts it in the same grid cell as #pane-builder"
    )
    assert re.search(r"body\.ck-right-terminal\s+#pane-terminal\s*\{\s*display:\s*flex", block)


def test_the_builder_pane_hides_when_the_terminal_shows():
    """Both in one cell with both visible is the Phase 4b defect exactly."""
    block = _media_block(_read(CSS), "768px")
    assert re.search(r"body\.ck-right-terminal\s+#pane-builder\s*\{\s*display:\s*none", block)


def test_the_two_panes_share_one_grid_cell_at_both_breakpoints():
    """If their placements diverge, one silently lands somewhere unintended."""
    css = _read(CSS)
    for width, column in (("768px", "2"), ("1024px", "3")):
        block = _media_block(css, width)
        placement = re.search(
            r"#pane-builder,\s*#pane-terminal\s*\{([^}]*)\}", block
        )
        assert placement, f"no shared placement rule for #pane-builder/#pane-terminal at {width}"
        body = placement.group(1)
        assert f"grid-column: {column}" in body, f"expected grid-column {column} at {width}: {body}"


def test_the_switcher_is_hidden_below_the_desktop_breakpoint():
    """Mirrors .ck-switch: hidden at base, shown at >=768. On the phone the tabs do this job."""
    css = _read(CSS)
    base = css[: css.index("@media")]
    assert re.search(r"\.ck-switch-right\s*\{[^}]*display:\s*none", base), (
        ".ck-switch-right must be display:none at base like .ck-switch"
    )
    assert re.search(r"\.ck-switch-right\s*\{\s*display:\s*flex", _media_block(css, "768px"))


# ---------------------------------------------------------------------------
# JS wiring
# ---------------------------------------------------------------------------


def test_the_pane_is_registered_in_the_panes_map():
    """Absent from PANES, showPane('terminal') hides every pane and shows nothing."""
    assert re.search(r"PANES\s*=\s*\{[^}]*terminal:\s*'pane-terminal'", _read(JS))


def test_set_right_persists_only_on_a_deliberate_click():
    """Mirrors setLeft: showPane() also runs on arrival from /chat, and writing there
    silently reset a saved preference (the bug that shaped setLeft)."""
    js = _read(JS)
    assert "function setRight(" in js
    match = re.search(r"function setRight\([^)]*\)\s*\{(.*?)\n  \}", js, re.S)
    assert match, "setRight not found in the expected shape"
    body = match.group(1)
    assert "if (persist)" in body, "setRight must guard its localStorage write on `persist`"


def test_the_mint_route_is_never_called_with_a_hardcoded_lane():
    """A hardcoded lane mints for one lane while the iframe points at the other.

    Asserts the INVARIANT, not a syntax: string concat with encodeURIComponent and a
    template literal are both fine — baking a lane name into the path is not.
    """
    js = _read(JS)
    assert "/api/cockpit/terminal/" in js, "the mint route is never called"
    for lane in ("claude", "codex"):
        assert f"/api/cockpit/terminal/{lane}" not in js, (
            f"the mint URL hardcodes {lane!r}; it must be built from the selected lane"
        )


def test_the_codex_seat_is_never_reported_as_free():
    """busy is null (UNKNOWN). Rendering it as availability would be a false claim.

    Tied to the phrase actually rendered — asserting a bare 'unknown' appears somewhere in
    the file passed before any of this was written, which is no assertion at all.
    """
    js = _read(JS)
    assert "Seat state unknown" in js, "the pane must say the codex seat state is unknown"
    assert not re.search(r"busy\s*===?\s*false", js), (
        "do not branch on busy === false — the API never asserts the seat is free"
    )
    assert not re.search(r"['\"]seat[^'\"]*free", js, re.I), "never render the seat as free"
