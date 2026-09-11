"""Every registered lane gets a landing page, a terminal page, and a menu-bar entry.

The defect these pin is not a crash — it is a page that is quietly incomplete.
Measured 2026-09-11: three coder lanes were live (claude, codex, archie-tui) and
/chat carried a tab for exactly one of them, because the tab list was literal
markup in chat.html. Nothing failed; the other two lanes simply had no way in.

So the invariant under test is a NEGATIVE one: no template may name a lane. Every
lane surface is generated from services.terminal_lanes.LANES, which is what makes
adding opencode a registry entry rather than an edit across four files.

The second family here is the HOST marker. claude and archie-tui are shells on the
host with no container boundary; codex is contained. The lanes render identically
otherwise, so the marker is the only thing separating "edit a file" from "edit the
host's files" — an unmarked host lane is the expensive failure, not a cosmetic one.
"""

import pathlib
import re

import pytest
from jinja2 import Environment, FileSystemLoader

# The tests run from several roots (repo, archie-comms, inside the container), so
# resolve the templates dir by looking rather than by assuming a parent depth.
# A skipped test cannot fail, and a silently-skipped suite is how three of these
# went unnoticed in the container before.
_CANDIDATES = [
    pathlib.Path(__file__).resolve().parents[1] / "templates",
    pathlib.Path(__file__).resolve().parents[2] / "archie-comms" / "templates",
    pathlib.Path("/app/templates"),
]
TEMPLATES = next((p for p in _CANDIDATES if (p / "lane_landing.html").exists()), None)

pytestmark = pytest.mark.skipif(
    TEMPLATES is None, reason="comms templates not reachable from this test root"
)

# A deliberately ODD set: two host lanes and one sandboxed, none of them named in
# any template. If a template hardcodes "Claude", these fixtures will not match it.
LANES = [
    {
        "key": "alpha",
        "label": "Alpha Lane",
        "blurb": "first lane blurb",
        "accent": "#a78bfa",
        "sandboxed": False,
    },
    {
        "key": "bravo",
        "label": "Bravo Lane",
        "blurb": "second lane blurb",
        "accent": "#22d3ee",
        "sandboxed": True,
    },
    {
        "key": "charlie-tui",
        "label": "Charlie TUI",
        "blurb": "third lane blurb",
        "accent": "#34d399",
        "sandboxed": False,
    },
]


def _env():
    return Environment(loader=FileSystemLoader(str(TEMPLATES)))


def _code_only(src: str) -> str:
    """Strip comments before scanning for a forbidden pattern.

    A comment that NAMES the defect it fixed reads as the defect to a naive grep.
    That has now cost this repo five separate false findings — including on the
    first run of this very check, where the JS comment explaining the removal of
    `http://192.168.1.200:7681` matched the search for it.
    """
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    return src


def _render(name, **ctx):
    return _env().get_template(name).render(**ctx)


class TestEveryLaneIsReachable:
    def test_chat_has_a_tab_and_a_panel_for_every_lane(self):
        """The original defect: one tab, three lanes."""
        html = _render("chat.html", lanes=LANES)
        for lane in LANES:
            assert f'id="panel-tty-{lane["key"]}"' in html, f"{lane['key']} has no panel"
            assert lane["label"] in html, f"{lane['key']} is not named in the tab row"

    def test_chat_menu_bar_links_every_lane(self):
        html = _render("chat.html", lanes=LANES)
        for lane in LANES:
            assert f'href="/{lane["key"]}"' in html, f"{lane['key']} missing from the strip"

    def test_landing_lists_every_lane(self):
        html = _render("lane_landing.html", lane=LANES[0], lanes=LANES)
        for lane in LANES:
            assert f'href="/{lane["key"]}"' in html

    def test_terminal_menu_bar_links_the_other_lanes(self):
        html = _render("lane_terminal.html", lane=LANES[0], lanes=LANES)
        for lane in LANES[1:]:
            assert f'href="/{lane["key"]}/terminal"' in html


class TestHostMarker:
    """An unmarked host lane is the expensive failure — never a cosmetic one."""

    @pytest.mark.parametrize("lane", LANES, ids=lambda l: l["key"])
    def test_each_page_marks_host_vs_sandboxed(self, lane):
        for page in ("lane_landing.html", "lane_terminal.html"):
            html = _code_only(_render(page, lane=lane, lanes=LANES))
            if lane["sandboxed"]:
                assert "sandboxed" in html, f"{page}/{lane['key']}: no sandboxed marker"
            else:
                assert "HOST" in html, f"{page}/{lane['key']}: HOST lane not marked"

    def test_chat_marks_every_lane_in_its_own_panel(self):
        html = _code_only(_render("chat.html", lanes=LANES))
        # one marker per lane — a HOST lane that renders without one is the bug
        assert html.count("ac-tty-badge host") == sum(1 for l in LANES if not l["sandboxed"])
        assert html.count("ac-tty-badge sandboxed") == sum(1 for l in LANES if l["sandboxed"])


class TestMintingGoesThroughTheOneGate:
    def test_no_hardcoded_ttyd_url_survives(self):
        """`frame.src = 'http://192.168.1.200:7681'` was broken three ways at once:
        plain http inside an https page (mixed content, blocked on the public
        hostname), a LAN IP (unreachable off-LAN), and no token at all — so it
        worked only from a LAN browser that already held a cookie from elsewhere."""
        for page, ctx in (
            ("chat.html", {"lanes": LANES}),
            ("lane_terminal.html", {"lane": LANES[0], "lanes": LANES}),
        ):
            code = _code_only(_render(page, **ctx))
            assert "192.168.1.200:7681" not in code, f"{page} still hardcodes a ttyd URL"
            assert not re.search(r"src\s*=\s*['\"]https?://\d+\.\d+\.\d+\.\d+", code), (
                f"{page} points a frame at a raw IP instead of a minted URL"
            )

    def test_every_lane_mints_through_the_admin_gated_route(self):
        """ONE minting path. A second mint site with its own idea of the gate is
        what this design forbids — `/api/cockpit/terminal/<lane>/token` carries
        `_require_admin` and is the only place a shell token is created."""
        for page, ctx in (
            ("chat.html", {"lanes": LANES}),
            ("lane_terminal.html", {"lane": LANES[0], "lanes": LANES}),
        ):
            code = _code_only(_render(page, **ctx))
            assert "/api/cockpit/terminal/" in code, f"{page} does not mint"

    def test_a_lane_is_never_auto_mounted_on_page_load(self):
        """Opening a host shell because someone loaded a page is not acceptable.
        The frame starts at about:blank and waits for an explicit action."""
        html = _render("lane_terminal.html", lane=LANES[0], lanes=LANES)
        assert 'src="about:blank"' in html
        assert 'id="lt-open"' in html, "no explicit Open control"


class TestFailuresAreExplained:
    """A blank frame tells the reader nothing. Every failure names its reason."""

    def test_the_terminal_page_states_each_failure_mode(self):
        code = _code_only(_render("lane_terminal.html", lane=LANES[0], lanes=LANES))
        assert "admin account" in code, "403 must say a terminal needs an admin account"
        assert "Signed out" in code, "401 must say the session is gone"
        assert "not registered" in code, "404 must say the lane is unknown"

    def test_a_failed_mount_does_not_latch_the_lane_as_loaded(self):
        """chat.html caches per-lane so a tab switch does not re-mint. If a failure
        left that cache set, the lane could never recover without a page reload."""
        code = _code_only(_render("chat.html", lanes=LANES))
        assert re.search(r"loaded\[lane\]\s*=\s*false", code), (
            "a failed mount must clear the loaded flag, or Reconnect cannot recover"
        )
