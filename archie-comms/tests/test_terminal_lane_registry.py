"""Invariants for the terminal lane registry — a third lane made these load-bearing.

Adding archie-tui (2026-09-11) exposed two failure shapes that no test covered:

1. `setLane` in cockpit.js was `lane === 'codex' ? 'codex' : 'claude'` — a hardcoded
   TWO-lane ternary. A third lane fell through to 'claude', so clicking the new lane's
   button would have opened the HOST SHELL. Adding a lane must never silently route to
   a different, more privileged lane.

2. The repo copy of ttyd-claude.service said `TTYD_PORT=7681` while 7681 is the AUTH
   PROXY's port and start_ttyd.sh defaults the BACKEND to 17681. Installing that copy
   starts a backend on a proxy port — which is exactly the orphaned `ttyd -p 7681` in
   task #6698. Backends live in 1768x; proxies live in 768x; they must never cross.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
JS = ROOT / "static" / "js" / "cockpit.js"
HTML = ROOT / "templates" / "cockpit.html"


def _code_only(js: str) -> str:
    """JS with // line comments and /* block */ comments removed.

    A check about CODE must look at code. This module's own fix comments quote the
    defective pattern verbatim to explain it."""
    import re as _re

    js = _re.sub(r"/\*.*?\*/", "", js, flags=_re.S)
    return "\n".join(_re.sub(r"//.*$", "", ln) for ln in js.splitlines())

def _lanes():
    import sys

    sys.path.insert(0, str(ROOT))
    from services import terminal_lanes as tl

    return tl.LANES


class TestLaneRegistry:
    def test_the_three_lanes_are_registered(self):
        assert set(_lanes()) >= {"claude", "codex", "archie-tui"}

    def test_proxy_ports_are_unique(self):
        ports = [c["proxy_port"] for c in _lanes().values()]
        assert len(ports) == len(set(ports)), f"two lanes share a proxy port: {sorted(ports)}"

    def test_a_proxy_port_is_never_a_backend_port(self):
        """768x fronts; 1768x is behind. A lane whose PUBLIC port is in the backend
        range (or vice versa) is the #6698 collision."""
        for lane, cfg in _lanes().items():
            p = cfg["proxy_port"]
            assert 7680 <= p <= 7699, f"{lane}: proxy_port {p} is outside the 768x front range"

    def test_every_lane_declares_its_isolation(self):
        """`sandboxed` drives the ⚠ HOST marker — the most important label on the page.
        A lane that forgets it renders as if it were contained."""
        for lane, cfg in _lanes().items():
            assert "sandboxed" in cfg, f"{lane} does not declare `sandboxed`"

    def test_archie_tui_is_marked_host_not_sandboxed(self):
        """It runs beside the engine on the host, deliberately. If this ever flips to
        True the UI stops warning about a host surface."""
        assert _lanes()["archie-tui"]["sandboxed"] is False



def _render_cockpit():
    """Render cockpit.html with the REAL registry, as the route does.

    The lane buttons are a Jinja loop over `lanes`, so these assertions have to run
    against output. A raw-source scan for data-lane="claude" passed for as long as
    the markup was hand-written and would now fail on a template that works.
    """
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(HTML.parent)))
    lanes = [
        {"key": k, "label": c.get("label", k), "sandboxed": bool(c.get("sandboxed"))}
        for k, c in _lanes().items()
    ]
    return env.get_template(HTML.name).render(lanes=lanes)


class TestLaneSelectionIsNotHardcoded:
    def test_no_two_lane_ternary(self):
        """The exact regression: a ternary that can only ever yield two lanes.

        ⚠️ Strips comments FIRST. The fix's own comment quotes the bad pattern to explain
        it, so a naive scan matches the explanation and reports the bug as still present.
        Grepping one's own commentary instead of the code has produced false results in
        this repo four times now — always compare against code only."""
        src = _code_only(JS.read_text())
        assert not re.search(r"lane\s*===\s*'codex'\s*\?\s*'codex'\s*:\s*'claude'", src), (
            "setLane is back to a hardcoded two-lane ternary — a third lane would "
            "silently open the HOST claude shell"
        )

    def test_selection_is_driven_by_the_rendered_buttons(self):
        src = _code_only(JS.read_text())
        i = src.find("function setLane")
        assert i > 0, "setLane not found"
        body = src[i : i + 900]
        assert "#ck-lanes button" in body and "dataset.lane" in body, (
            "setLane no longer derives the valid lanes from the rendered buttons"
        )

    def test_every_registered_lane_has_a_button(self):
        html = _render_cockpit()
        for lane in _lanes():
            assert f'data-lane="{lane}"' in html, f"lane {lane} is registered but has no button"

    def test_every_button_names_a_registered_lane(self):
        """The other direction: a button for a lane the server does not know mints 404."""
        html = _render_cockpit()
        buttons = set(re.findall(r'data-lane="([a-z0-9-]+)"', html))
        unknown = sorted(buttons - set(_lanes()))
        assert not unknown, f"buttons for unregistered lanes: {unknown}"

    def test_host_lanes_carry_the_host_marker_in_the_markup(self):
        html = _render_cockpit()
        for lane, cfg in _lanes().items():
            m = re.search(r'data-lane="%s"(.*?)</button>' % re.escape(lane), html, re.S)
            assert m, f"no button block for {lane}"
            has_host_pill = "ck-pill-host" in m.group(1)
            assert has_host_pill == (not cfg["sandboxed"]), (
                f"{lane}: sandboxed={cfg['sandboxed']} but host pill present={has_host_pill}"
            )


class TestTtydUnitsPointAtBackends:
    """#6698: a unit pointing a BACKEND at a PROXY port is how the orphan was born."""

    def _units(self):
        return sorted((REPO / "scripts").glob("ttyd-*.service"))

    def test_units_exist(self):
        assert self._units(), "no ttyd unit files found"

    def test_backend_units_use_the_1768x_range(self):
        for u in self._units():
            txt = u.read_text()
            if "auth-proxy" in u.name or "PROXY_LANE" in txt:
                continue  # a proxy unit: its TTYD_PORT is the UPSTREAM it dials
            for port in re.findall(r"^Environment=TTYD_PORT=(\d+)", txt, re.M):
                assert 17680 <= int(port) <= 17699, (
                    f"{u.name}: TTYD_PORT={port} is not a 1768x backend port — a backend "
                    f"on a proxy port is the #6698 collision"
                )

    def test_no_unit_carries_credentials(self):
        """The installed ttyd-claude.service still has stale plaintext TTYD_USER/PASS
        (see #6698). Keep the repo clean so no install can reintroduce them."""
        for u in self._units():
            txt = u.read_text()
            for var in ("TTYD_USER", "TTYD_PASS"):
                assert not re.search(r"^Environment=%s=" % var, txt, re.M), (
                    f"{u.name} carries a plaintext {var} — auth belongs to the proxy"
                )
