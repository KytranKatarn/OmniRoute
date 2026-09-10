"""Every terminal token this service mints must name the lane it may open.

`scripts/ttyd_auth_proxy.py` fronts both coder lanes from ONE script against ONE
`terminal_auth_tokens` table, distinguished only by `PROXY_LANE`. It therefore refuses a
token whose `lane` does not match its own, and refuses a NULL lane outright (fail-closed).

So a mint that omits the lane does not fail loudly — it produces a token the proxy
silently rejects, and the terminal drawer falls back to a Basic Auth password prompt
inside the page. That is exactly what happened when the proxy-side gate was deployed
ahead of this: the drawer degraded with nothing in the logs to say why.

The assertions below are deliberately coupled — the column list AND the bound value —
so deleting either one turns the test red.
"""

import os
import re

import pytest

APP = os.path.join(os.path.dirname(__file__), "..", "app_comms.py")

pytestmark = pytest.mark.skipif(
    not os.path.exists(APP), reason=f"app_comms.py not reachable at {APP}"
)

VALID_LANES = {"claude", "codex"}


def _source():
    with open(APP) as fh:
        return fh.read()


def test_every_terminal_token_insert_names_the_lane_column():
    """A mint without `lane` yields a token the proxy refuses — silently, from the UI's side."""
    source = _source()
    inserts = re.findall(
        r"INSERT INTO terminal_auth_tokens\s*\(([^)]*)\)", source, re.IGNORECASE
    )
    assert inserts, "no INSERT INTO terminal_auth_tokens found — did the route move?"
    for columns in inserts:
        cols = {c.strip() for c in columns.split(",")}
        assert "lane" in cols, (
            "a terminal token is minted without a lane; the proxy fails closed on NULL "
            f"and the drawer degrades to a Basic Auth prompt. Columns were: {sorted(cols)}"
        )


def test_the_lane_constant_is_a_real_lane():
    """A typo'd lane mints tokens no proxy will ever accept."""
    source = _source()
    match = re.search(r'^TERMINAL_LANE\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    assert match, "TERMINAL_LANE is not defined at module level"
    assert match.group(1) in VALID_LANES, (
        f"TERMINAL_LANE={match.group(1)!r} is not one of {sorted(VALID_LANES)}"
    )


def test_the_bound_value_is_the_lane_constant_not_a_literal():
    """The lane passed to the INSERT must be the constant that sits beside the URL.

    A second hardcoded literal is how the lane and the URL drift apart — the token would
    be minted for one lane and the iframe pointed at the other.
    """
    source = _source()
    assert "TERMINAL_LANE)" in source or "TERMINAL_LANE," in source, (
        "TERMINAL_LANE is defined but never bound into the INSERT"
    )


def test_the_url_and_the_lane_live_together():
    """Whoever changes one must see the other."""
    source = _source()
    assert re.search(r"^TERMINAL_LANE_URL\s*=", source, re.MULTILINE), (
        "TERMINAL_LANE_URL is not defined at module level"
    )
    lane_line = source.index("TERMINAL_LANE =")
    url_line = source.index("TERMINAL_LANE_URL =")
    assert abs(lane_line - url_line) < 200, (
        "the lane and its URL must be declared adjacently so they cannot drift"
    )
