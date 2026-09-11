"""An element the JS hides with `.hidden` must actually disappear.

Found by the Phase 5 Task 7 live drive, 2026-09-11. `mountLane()` ends with
`state.hidden = true`, and the browser confirmed the attribute WAS set — yet the
pane still read "Opening the claude lane…" on top of a live, rendering host shell.

Cause: `.ck-lane-state { display: flex }` is a class rule (0,0,1,0) and the UA
stylesheet's `[hidden] { display: none }` is weaker, so the attribute changed
nothing. The JS was correct; the CSS silently defeated it.

⚠️ WHY NO STATIC TEST CAUGHT IT, and why this one is shaped the way it is. Every
existing check asked "does the code set `hidden`?" — it does. The question that
matters is whether setting it has any EFFECT, and that is a cascade fact spanning
three files (js sets it, html supplies the classes, css decides). This test is the
join.

⚠️ AND WHY NOT A BLANKET RESET. `#ck-agent[hidden]` and `#ck-task[hidden]` are set
to `display: flex` ON PURPOSE — those sheets carry `hidden` while being shown via
`.ck-show`. A global `[hidden] { display: none !important }` would break both, so
they are listed as deliberate inversions rather than silently passing.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js" / "cockpit.js"
CSS = ROOT / "static" / "css" / "cockpit.css"
HTML = ROOT / "templates" / "cockpit.html"

# Elements that deliberately render WHILE carrying `hidden` (toggled by .ck-show).
# Each must be backed by an explicit `#id[hidden]` rule, which the test verifies.
DELIBERATE_INVERSIONS = {"ck-agent", "ck-task"}


def _src(p):
    if not p.exists():
        pytest.skip(f"{p} not reachable from this test root")
    return p.read_text()


def _ids_toggled_by_hidden():
    """ids the JS hides/shows via the `hidden` property."""
    js = _src(JS)
    return set(re.findall(r"\$\('([a-zA-Z0-9_-]+)'\)\.hidden\s*=", js))


def _classes_for(el_id):
    m = re.search(r'id="%s"[^>]*?class="([^"]*)"' % re.escape(el_id), _src(HTML))
    return set(m.group(1).split()) if m else set()


def _display_rules():
    """[(selector, display_value)] for every rule in cockpit.css that sets display."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _src(CSS)):
        m = re.search(r"(?<![-\w])display\s*:\s*([a-z-]+)", body)
        if not m:
            continue
        for one in sel.split(","):
            out.append((one.strip(), m.group(1)))
    return out


def _hidden_rule_covers(el_id, classes):
    """Is there a `[hidden]` rule setting display:none that outranks the plain rule?"""
    for sel, val in _display_rules():
        if "[hidden]" not in sel or val != "none":
            continue
        if f"#{el_id}[hidden]" in sel:
            return True
        if any(f".{c}[hidden]" in sel for c in classes):
            return True
        if sel.strip() == "[hidden]":
            return True
    return False


class TestHiddenActuallyHides:
    def test_the_js_really_does_toggle_hidden(self):
        """Non-vacuity: if this set is empty the whole file proves nothing."""
        ids = _ids_toggled_by_hidden()
        assert ids, "no `$('id').hidden =` sites found — the extraction broke, not the code"

    @pytest.mark.parametrize("el_id", sorted(_ids_toggled_by_hidden() or {"ck-lane-state"}))
    def test_setting_hidden_has_an_effect(self, el_id):
        classes = _classes_for(el_id)
        # ⚠️ SOURCE ORDER MATTERS. Among rules of EQUAL specificity the LAST one in
        # the file wins, so collecting every matching rule and flagging any non-none
        # display reports false positives: #ck-hire is `.ck-form` (display:flex, L46)
        # AND `.ck-sheet` (display:none, L61), and .ck-sheet wins. The browser
        # confirmed it genuinely hides. Take the last matching rule, not any.
        matching = [
            (sel, val)
            for sel, val in _display_rules()
            if "[hidden]" not in sel
            and (sel == f"#{el_id}" or any(sel == f".{c}" for c in classes))
        ]
        winner = matching[-1] if matching else None
        blocking = [winner] if winner and winner[1] != "none" else []
        if not blocking:
            return  # nothing outranks the UA rule; `hidden` works
        if el_id in DELIBERATE_INVERSIONS:
            return  # covered by its own test below
        assert _hidden_rule_covers(el_id, classes), (
            f"#{el_id} is hidden via the `hidden` property, but {blocking} sets a "
            f"display that OUTRANKS the UA `[hidden]` rule and no `[hidden]` override "
            f"exists — setting .hidden will silently do nothing"
        )

    def test_the_lane_state_override_is_present(self):
        """The specific regression: the terminal pane's status line."""
        assert re.search(r"\.ck-lane-state\[hidden\]\s*\{[^}]*display\s*:\s*none", _src(CSS)), (
            "the .ck-lane-state[hidden] override is gone — the pane will read "
            "'Opening the … lane…' forever over a live terminal"
        )

    def test_deliberate_inversions_are_explicit_not_accidental(self):
        """#ck-agent / #ck-task render WHILE hidden on purpose. Require the rule to
        say so, so the next reader can tell intent from an oversight."""
        css = _src(CSS)
        for el_id in DELIBERATE_INVERSIONS:
            assert f"#{el_id}[hidden]" in css, (
                f"#{el_id} is treated as a deliberate inversion by this test but no "
                f"`#{el_id}[hidden]` rule exists to prove it"
            )

    def test_no_blanket_hidden_reset(self):
        """A global `[hidden] { display: none !important }` would break the two
        deliberate inversions. Keep overrides targeted."""
        for sel, val in _display_rules():
            assert sel.strip() != "[hidden]" or val != "none" or "!important" not in _src(CSS), (
                "a blanket [hidden] reset would break #ck-agent / #ck-task"
            )
