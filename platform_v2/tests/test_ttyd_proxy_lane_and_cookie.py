"""A terminal token must open only the lane it was minted for.

`scripts/ttyd_auth_proxy.py` fronts BOTH coder lanes. The two instances differ only by
environment — `PROXY_PORT`/`TTYD_PORT` — and consult the SAME `terminal_auth_tokens`
table:

    claude: :7681 -> 127.0.0.1:17681   the HOST tmux session, no container boundary
    codex:  :7683 -> 127.0.0.1:17682   container archie_codex_terminal, --max-clients 1

Until this change the table had no `lane` column and `validate_token()` looked a token up
by value alone, so a token minted for the SANDBOXED codex lane was accepted by the claude
HOST-shell proxy, and the reverse.

⚠️ Severity, stated precisely: the only mint path requires `session["user_id"]`, which is
set solely inside the branch that has already rejected `role != "admin"`
(`app_comms.py:131`). Every token holder is therefore already an admin who can open the
claude lane directly, so this was never an escalation for an unprivileged party. It is a
least-privilege failure — and it becomes load-bearing the moment the cockpit pane starts
*asserting* that codex is sandboxed, because that label would then be false.

These tests drive the module directly with the DB seams replaced; no socket, no database.

⚠️ `validate_token` returns the token's `user_id` (int) or None, NOT a bool — the caller
needs to know WHOSE session cookie to mint. A truthiness-only assertion would pass on a
bool regression, so every assertion here checks the id.
"""

import importlib.util
import sys

import pytest

from tests.repo_root import repo_path

PROXY_PATH = repo_path("scripts", "ttyd_auth_proxy.py")

pytestmark = pytest.mark.skipif(
    not PROXY_PATH.exists(),
    reason=f"ttyd_auth_proxy.py not reachable at {PROXY_PATH}",
)

USER_ID = 7


def _load_proxy():
    """Import the proxy by path — it is a script, not an installed module."""
    spec = importlib.util.spec_from_file_location("_ttyd_proxy_under_test", PROXY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def proxy():
    module = _load_proxy()
    yield module
    sys.modules.pop("_ttyd_proxy_under_test", None)


@pytest.fixture
def seam(proxy, monkeypatch):
    """Replace the two DB seams; record every token consumed."""
    consumed = []
    rows = {
        "tok-claude": (11, USER_ID, "claude"),
        "tok-codex": (22, USER_ID, "codex"),
        "tok-legacy": (33, USER_ID, None),
    }
    monkeypatch.setattr(proxy, "_lookup_token_row", lambda token: rows.get(token))
    monkeypatch.setattr(proxy, "_consume_token", lambda token_id: consumed.append(token_id))
    return consumed


# ---------------------------------------------------------------------------
# The lane gate
# ---------------------------------------------------------------------------


def test_a_token_opens_the_lane_it_was_minted_for(proxy, seam):
    assert proxy.validate_token("tok-claude", "claude") == USER_ID
    assert seam == [11], "a valid token must be consumed exactly once"


def test_a_codex_token_is_refused_by_the_claude_proxy(proxy, seam):
    """The sandbox token must never open the host shell."""
    assert proxy.validate_token("tok-codex", "claude") is None
    assert seam == [], "a refused token must NOT be consumed — that would burn it"


def test_a_claude_token_is_refused_by_the_codex_proxy(proxy, seam):
    """Refusal is symmetric; the host token is not a superset of the sandbox token."""
    assert proxy.validate_token("tok-claude", "codex") is None
    assert seam == []


def test_a_legacy_null_lane_token_fails_closed(proxy, seam):
    """Rows predating the lane column are one-time and 5-minute-lived; refusing costs nothing."""
    assert proxy.validate_token("tok-legacy", "claude") is None
    assert seam == []


def test_an_unconfigured_proxy_lane_refuses_everything(proxy, seam, monkeypatch):
    """An unset PROXY_LANE must make the proxy inert, never permissive."""
    monkeypatch.delenv("PROXY_LANE", raising=False)
    assert proxy.configured_lane() == ""
    assert proxy.validate_token("tok-claude", proxy.configured_lane()) is None
    assert seam == []


def test_an_unknown_token_is_refused(proxy, seam):
    assert proxy.validate_token("no-such-token", "claude") is None
    assert seam == []


def test_configured_lane_reads_the_environment_at_call_time(proxy, monkeypatch):
    """A rotated unit file takes effect on restart without a code change."""
    monkeypatch.setenv("PROXY_LANE", "claude")
    assert proxy.configured_lane() == "claude"
    monkeypatch.setenv("PROXY_LANE", "codex")
    assert proxy.configured_lane() == "codex"


def test_surrounding_whitespace_in_proxy_lane_is_tolerated(proxy, seam, monkeypatch):
    """A systemd Environment= line can carry stray spaces; that must not break the match."""
    monkeypatch.setenv("PROXY_LANE", "  claude  ")
    assert proxy.configured_lane() == "claude"
    assert proxy.validate_token("tok-claude", proxy.configured_lane()) == USER_ID


# ---------------------------------------------------------------------------
# The wiring — a gate nothing calls is not a gate
# ---------------------------------------------------------------------------


def test_the_connection_handler_passes_the_configured_lane(proxy):
    """`validate_token` must be called WITH the lane at its only call site.

    The guard existing but being called without the lane is the exact shape of the
    recurring "correct guard, never wired at the choke point" defect.
    """
    import inspect

    source = inspect.getsource(proxy.handle_connection)
    assert "validate_token(token, " in source, "handle_connection must pass a lane argument"
    assert "configured_lane()" in source, "handle_connection must use the configured lane"


def test_both_units_declare_a_distinct_lane():
    """Each proxy instance must name its own lane, and the two must differ."""
    lanes = {}
    for name in ("ttyd-auth-proxy.service", "ttyd-codex-auth-proxy.service"):
        unit = repo_path("scripts", name)
        if not unit.exists():
            pytest.skip(f"{name} not reachable at {unit}")
        for line in unit.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("Environment=PROXY_LANE="):
                lanes[name] = stripped.split("=", 2)[2].strip()
    assert len(lanes) == 2, f"both units must set PROXY_LANE, got {lanes}"
    assert len(set(lanes.values())) == 2, f"the two lanes must differ, got {lanes}"
    assert set(lanes.values()) == {"claude", "codex"}, lanes


# ---------------------------------------------------------------------------
# The sliding session cookie
#
# A one-time token authenticates exactly ONE request (measured against the live proxy).
# A ttyd page is a document, then its assets, then a websocket upgrade — so without a
# cookie the pane renders empty or prompts for a password inside the cockpit.
# ---------------------------------------------------------------------------

SECRET = "cookie-signing-secret-for-tests"


@pytest.fixture
def signed(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", SECRET)
    return proxy


def test_a_cookie_round_trips_for_its_own_lane(signed):
    value = signed.mint_cookie(USER_ID, "claude")
    assert signed.verify_cookie(value, "claude") == USER_ID


def test_a_cookie_is_rejected_for_a_different_lane(signed):
    """The lane binding survives into the cookie — not just the token."""
    value = signed.mint_cookie(USER_ID, "codex")
    assert signed.verify_cookie(value, "claude") is None


def test_a_tampered_cookie_is_rejected(signed):
    value = signed.mint_cookie(USER_ID, "claude")
    body, sig = value.rsplit(".", 1)
    assert signed.verify_cookie(f"{body}.dead{sig[4:]}", "claude") is None


def test_a_forged_payload_is_rejected(signed):
    """Re-encoding the payload without the key must not authenticate."""
    import base64

    raw = f"{USER_ID}:claude:99999999999".encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert signed.verify_cookie(f"{body}.{'0' * 64}", "claude") is None


def test_a_cookie_signed_with_another_secret_is_rejected(signed, monkeypatch):
    value = signed.mint_cookie(USER_ID, "claude")
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "a-different-secret")
    assert signed.verify_cookie(value, "claude") is None


def test_an_expired_cookie_is_rejected(signed, monkeypatch):
    monkeypatch.setattr(signed.time, "time", lambda: 1_000_000.0)
    value = signed.mint_cookie(USER_ID, "claude")
    monkeypatch.setattr(signed.time, "time", lambda: 1_000_000.0 + signed.COOKIE_TTL_SECONDS + 1)
    assert signed.verify_cookie(value, "claude") is None


def test_a_cookie_just_inside_its_window_is_accepted(signed, monkeypatch):
    """Guards against an off-by-one that would expire the cookie a full TTL early."""
    monkeypatch.setattr(signed.time, "time", lambda: 1_000_000.0)
    value = signed.mint_cookie(USER_ID, "claude")
    monkeypatch.setattr(signed.time, "time", lambda: 1_000_000.0 + signed.COOKIE_TTL_SECONDS - 1)
    assert signed.verify_cookie(value, "claude") == USER_ID


def test_an_unset_secret_mints_nothing_and_accepts_nothing(signed, monkeypatch):
    """Fail closed: no secret must mean no cookie auth, never 'skip the check'."""
    value = signed.mint_cookie(USER_ID, "claude")
    monkeypatch.delenv("TTYD_COOKIE_SECRET", raising=False)
    assert signed.verify_cookie(value, "claude") is None
    assert signed.mint_cookie(USER_ID, "claude") == ""


def test_a_garbage_cookie_never_raises(signed):
    """A malformed cookie must be a refusal, not a 500 inside the proxy."""
    for junk in ("", "no-dot", "...", "üñí.çødé", "a.b.c"):
        assert signed.verify_cookie(junk, "claude") is None


def test_the_ttl_is_fifteen_minutes(proxy):
    assert proxy.COOKIE_TTL_SECONDS == 900


def test_set_cookie_carries_exactly_the_required_attributes(signed):
    """Secure + SameSite=None is REQUIRED, not a preference.

    The cockpit is reached at http://192.168.1.200:3002 (a bare IP is its own site) while
    the terminal is *.kytranempowerment.com, so the iframe is CROSS-SITE and a Strict or
    Lax cookie is never sent at all — the pane would fail exactly as measured.
    """
    header = signed.build_set_cookie(USER_ID, "claude")
    assert header.startswith(f"{signed.COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=None" in header
    assert "SameSite=Strict" not in header and "SameSite=Lax" not in header
    assert f"Max-Age={signed.COOKIE_TTL_SECONDS}" in header
    assert "Path=/" in header


def test_no_set_cookie_when_the_secret_is_unset(signed, monkeypatch):
    monkeypatch.delenv("TTYD_COOKIE_SECRET", raising=False)
    assert signed.build_set_cookie(USER_ID, "claude") == ""


def test_the_cookie_is_parsed_out_of_a_raw_request(proxy):
    raw = b"GET / HTTP/1.1\r\nHost: x\r\nCookie: a=1; archie_tty=abc.def; b=2\r\n\r\n"
    assert proxy.parse_cookie_header(raw) == "abc.def"


def test_a_request_with_no_cookie_header_parses_to_none(proxy):
    assert proxy.parse_cookie_header(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n") is None


def test_an_unrelated_cookie_is_not_mistaken_for_ours(proxy):
    raw = b"GET / HTTP/1.1\r\nCookie: session=xyz; other=1\r\n\r\n"
    assert proxy.parse_cookie_header(raw) is None


# ---------------------------------------------------------------------------
# frame-ancestors — the required other half of SameSite=None
# ---------------------------------------------------------------------------


def test_frame_ancestors_fails_closed_when_unset(proxy, monkeypatch):
    """Unset must mean 'nobody may embed', never 'anybody'."""
    monkeypatch.delenv("TTYD_FRAME_ANCESTORS", raising=False)
    assert proxy.frame_ancestors() == "'none'"


def test_frame_ancestors_passes_through_the_allowlist(proxy, monkeypatch):
    monkeypatch.setenv(
        "TTYD_FRAME_ANCESTORS",
        "https://archie.kytranempowerment.com http://192.168.1.200:3002",
    )
    assert "archie.kytranempowerment.com" in proxy.frame_ancestors()
    assert "192.168.1.200:3002" in proxy.frame_ancestors()


def test_the_csp_header_is_injected_on_every_response(proxy, monkeypatch):
    """Present even with no cookie — SameSite=None without this lets any site embed us."""
    monkeypatch.setenv("TTYD_FRAME_ANCESTORS", "https://archie.kytranempowerment.com")
    head = proxy.inject_response_headers(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n", set_cookie="")
    assert b"Content-Security-Policy: frame-ancestors https://archie.kytranempowerment.com" in head
    assert b"Set-Cookie" not in head
    assert head.endswith(b"\r\n\r\n"), "the header block must stay terminated"


def test_the_set_cookie_is_injected_alongside_the_csp(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_FRAME_ANCESTORS", "https://archie.kytranempowerment.com")
    head = proxy.inject_response_headers(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n",
        set_cookie="archie_tty=v; Path=/",
    )
    assert b"Set-Cookie: archie_tty=v; Path=/" in head
    assert b"frame-ancestors" in head
    assert head.count(b"\r\n\r\n") == 1, "exactly one header terminator"


def test_the_original_upstream_headers_survive_injection(proxy):
    head = proxy.inject_response_headers(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nX-Ttyd: 1\r\n\r\n", set_cookie=""
    )
    assert b"HTTP/1.1 200 OK" in head
    assert b"Content-Type: text/html" in head
    assert b"X-Ttyd: 1" in head


def test_the_frame_ancestors_line_is_quoted_in_both_units():
    """systemd splits `Environment=` on whitespace — an unquoted list loses all but the first.

    Caught by `systemd-analyze verify`, which reported
    `Invalid environment assignment, ignoring: http://192.168.1.200:3002`. The unit LOOKED
    correct while the cockpit's own LAN origin was silently dropped from the allowlist, so
    the pane would have been refused embedding by its own CSP.
    """
    for name in ("ttyd-auth-proxy.service", "ttyd-codex-auth-proxy.service"):
        unit = repo_path("scripts", name)
        if not unit.exists():
            pytest.skip(f"{name} not reachable at {unit}")
        lines = [
            line.strip()
            for line in unit.read_text().splitlines()
            if line.strip().startswith("Environment=") and "TTYD_FRAME_ANCESTORS" in line
        ]
        assert lines, f"{name} does not set TTYD_FRAME_ANCESTORS"
        for line in lines:
            value = line[len("Environment=") :]
            if " " in value.split("=", 1)[-1]:
                assert value.startswith('"') and value.endswith('"'), (
                    f"{name}: a whitespace-containing Environment= value must be quoted, "
                    f"or systemd drops everything after the first space: {line}"
                )
