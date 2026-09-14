"""Every terminal token this service mints must name the lane it may open.

`scripts/ttyd_auth_proxy.py` fronts both coder lanes from ONE script against ONE
`terminal_auth_tokens` table, distinguished only by `PROXY_LANE`. It refuses a token whose
`lane` does not match its own, and refuses a NULL lane outright (fail-closed).

So a mint that omits the lane does not fail loudly — it produces a token the proxy
silently rejects, and the terminal drawer falls back to a Basic Auth password prompt
inside the page. That is exactly what happened when the proxy-side gate was deployed ahead
of the minting side: the drawer degraded with nothing in the logs to say why.

⚠️ The scan below deliberately walks the WHOLE service rather than one file. Pinning the
INSERT to a single module means the test goes green the moment someone adds a second
minting site somewhere else — which is the failure it exists to catch.
"""

import os
import re

import pytest

COMMS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.skipif(
    not os.path.isdir(COMMS), reason=f"archie-comms not reachable at {COMMS}"
)

VALID_LANES = {"claude", "codex", "archie-tui", "opencode"}


def _python_sources():
    for root, dirs, files in os.walk(COMMS):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "tests", "node_modules"}]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    yield path, fh.read()


# ---------------------------------------------------------------------------
# The invariant: no mint anywhere may omit the lane
# ---------------------------------------------------------------------------


def test_no_terminal_token_insert_anywhere_omits_the_lane():
    found = 0
    for path, source in _python_sources():
        for columns in re.findall(
            r"INSERT INTO terminal_auth_tokens\s*\(([^)]*)\)", source, re.IGNORECASE
        ):
            found += 1
            cols = {c.strip() for c in columns.split(",")}
            assert "lane" in cols, (
                f"{os.path.relpath(path, COMMS)} mints a terminal token without a lane. "
                f"The proxy fails closed on NULL and the drawer degrades to a Basic Auth "
                f"prompt with no error. Columns: {sorted(cols)}"
            )
    assert found >= 1, "no terminal-token INSERT found at all — did the mint move out of comms?"


def test_there_is_exactly_one_minting_site():
    """Two mint paths with different gates is the 'second gate for shell access' the design forbids."""
    sites = [
        os.path.relpath(path, COMMS)
        for path, source in _python_sources()
        if re.search(r"INSERT INTO terminal_auth_tokens", source, re.IGNORECASE)
    ]
    assert len(sites) == 1, f"expected exactly one minting site, found {sites}"
    assert sites[0] == os.path.join("services", "terminal_lanes.py"), sites


# ---------------------------------------------------------------------------
# The lane registry
# ---------------------------------------------------------------------------


@pytest.fixture
def lanes():
    import sys

    if COMMS not in sys.path:
        sys.path.insert(0, COMMS)
    from services import terminal_lanes

    return terminal_lanes


def test_only_the_real_lanes_exist(lanes):
    """The engine is NOT a lane — :9090 is a bearer-auth websocket API with no shell.

    VALID_LANES is deliberately FROZEN. Every lane is a shell someone can reach, so
    adding one must trip a test and be updated on purpose — never arrive as a silent
    registry edit. Updating this set is the deliberate act.
    """
    assert set(lanes.LANES) == VALID_LANES
    assert "engine" not in lanes.LANES


def test_the_claude_lane_is_marked_as_the_host_not_a_sandbox(lanes):
    """The most important label on the page: claude has NO container boundary."""
    assert lanes.LANES["claude"]["contained"] is False
    # option B 2026-09-13: codex holds /var/run/docker.sock, so no boundary remains.
    assert lanes.LANES["codex"]["contained"] is False


def test_lane_urls_are_distinct_and_https(lanes):
    urls = [c["url"] for c in lanes.LANES.values()]
    assert len(set(urls)) == len(urls), "two lanes share a URL — one would open the other"
    assert all(u.startswith("https://") for u in urls)


def test_lane_ports_are_distinct(lanes):
    """Two lanes sharing a proxy port would silently open the wrong terminal.

    This asserted a literal [7681, 7683] — which broke on the third lane while
    checking nothing its own name promises. Distinctness is the property; the
    768x range is the other half (backends live on 1768x, bound to 127.0.0.1, and
    a backend in the proxy range would be published straight to the LAN).
    """
    ports = [c["proxy_port"] for c in lanes.LANES.values()]
    assert len(set(ports)) == len(ports), f"two lanes share a proxy port: {ports}"
    assert all(7680 <= p <= 7699 for p in ports), f"proxy ports outside the 768x range: {ports}"


def test_an_unknown_lane_is_refused(lanes):
    with pytest.raises(lanes.UnknownLane):
        lanes.mint_token(4, "engine")
    with pytest.raises(lanes.UnknownLane):
        lanes.mint_token(4, "")


# ---------------------------------------------------------------------------
# mint_token — functional, with the DB seam replaced
# ---------------------------------------------------------------------------


def test_mint_records_the_requested_lane(lanes, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        lanes, "_insert_token", lambda tok, uid, exp, lane: seen.update(token=tok, uid=uid, lane=lane)
    )
    result = lanes.mint_token(4, "codex")

    assert seen["lane"] == "codex", "the lane reaching the database must be the one requested"
    assert seen["uid"] == 4
    assert result["lane"] == "codex"
    assert result["token"] == seen["token"], "the returned token must be the one persisted"


def test_mint_points_the_url_at_the_matching_lane(lanes, monkeypatch):
    """A token minted for one lane but pointed at the other's URL is refused on arrival."""
    monkeypatch.setattr(lanes, "_insert_token", lambda *a, **k: None)
    for lane in VALID_LANES:
        result = lanes.mint_token(4, lane)
        assert result["url"].startswith(lanes.LANES[lane]["url"]), result["url"]
        assert f"token={result['token']}" in result["url"]


def test_mint_surfaces_whether_the_lane_is_contained(lanes, monkeypatch):
    monkeypatch.setattr(lanes, "_insert_token", lambda *a, **k: None)
    assert lanes.mint_token(4, "claude")["contained"] is False
    assert lanes.mint_token(4, "codex")["contained"] is False


def test_each_token_is_unique(lanes, monkeypatch):
    monkeypatch.setattr(lanes, "_insert_token", lambda *a, **k: None)
    tokens = {lanes.mint_token(4, "claude")["token"] for _ in range(20)}
    assert len(tokens) == 20


# ---------------------------------------------------------------------------
# lane_status
# ---------------------------------------------------------------------------


def test_lane_status_shape(lanes, monkeypatch):
    monkeypatch.setattr(lanes, "_probe", lambda port: True)
    rows = lanes.lane_status()
    assert {r["lane"] for r in rows} == VALID_LANES
    for row in rows:
        assert set(row) >= {"lane", "label", "reachable", "contained", "single_seat", "busy"}


def test_reachable_reflects_the_probe(lanes, monkeypatch):
    monkeypatch.setattr(lanes, "_probe", lambda port: port == 7681)
    by_lane = {r["lane"]: r for r in lanes.lane_status()}
    assert by_lane["claude"]["reachable"] is True
    assert by_lane["codex"]["reachable"] is False


def test_busy_is_unknown_not_false(lanes, monkeypatch):
    """The codex seat is not observable from outside without consuming it.

    Reporting False would be a confident wrong answer; None means 'unknown' and the UI
    must render it that way rather than as availability.
    """
    monkeypatch.setattr(lanes, "_probe", lambda port: True)
    for row in lanes.lane_status():
        assert row["busy"] is None


def test_a_401_counts_as_reachable(lanes):
    """An unauthenticated probe SHOULD be refused — 401 is the healthy answer.

    Treating only 200 as reachable would report every lane permanently down, because the
    proxy refuses every request that carries no token or credentials.
    """
    import http.client

    class _Resp:
        status = 401

    class _Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return _Resp()

        def close(self):
            pass

    original = http.client.HTTPConnection
    http.client.HTTPConnection = _Conn
    try:
        assert lanes._probe(7681) is True
    finally:
        http.client.HTTPConnection = original


def test_a_dead_proxy_is_not_reachable(lanes):
    import http.client

    class _Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            raise OSError("connection refused")

        def close(self):
            pass

    original = http.client.HTTPConnection
    http.client.HTTPConnection = _Conn
    try:
        assert lanes._probe(7681) is False
    finally:
        http.client.HTTPConnection = original
