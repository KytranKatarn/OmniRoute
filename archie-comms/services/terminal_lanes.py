"""The two coder lanes, and the ONE place a terminal token is minted.

One mint path on purpose. `scripts/ttyd_auth_proxy.py` fronts both lanes from a single
script against a single `terminal_auth_tokens` table, distinguished only by `PROXY_LANE`,
and it refuses a token whose lane does not match — a NULL lane outright. So a second route
minting tokens with its own idea of the gate is precisely the "second gate for shell
access" the design exists to avoid.

⚠️ The two lanes have very different blast radii and nothing here may blur them:

    claude — the real `claude` CLI on the HOST as user kytran, inside tmux `claude-code`.
             NO container boundary. `sandboxed` is False and the UI must say so.
    codex  — `codex` inside the archie_codex_terminal container, --max-clients 1, its own
             volumes, on a bridge network with no reach to any platform container.

The engine is NOT a lane: `archie_engine` publishes a bearer-auth websocket API on :9090
with no shell behind it. Do not add it.

Routing measured live against Citadel's Caddyfile (2026-09-10), not assumed:
    terminal.kytranempowerment.com -> http://100.64.0.4:7681   (claude)
    codex.kytranempowerment.com    -> http://100.64.0.4:7683   (codex)
"""

import http.client
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# How this container reaches the proxies, which run on the HOST. Matches the convention
# comms already uses for the Claude CLI proxy (CLAUDE_PROXY_URL=host.docker.internal:7682).
# A container's own 127.0.0.1 is NOT the host's, so a loopback probe here would report
# every lane down.
PROBE_HOST = os.getenv("TERMINAL_PROBE_HOST", "host.docker.internal")
PROBE_TIMEOUT_SECONDS = 3

TOKEN_TTL_SECONDS = 300

LANES = {
    "claude": {
        "label": "Claude",
        "url": "https://terminal.kytranempowerment.com",
        "proxy_port": 7681,
        # The HOST shell. This is the single most important fact on the page.
        "sandboxed": False,
        "single_seat": False,
    },
    "codex": {
        "label": "Codex",
        "url": "https://codex.kytranempowerment.com",
        "proxy_port": 7683,
        "sandboxed": True,
        "single_seat": True,  # ttyd --max-clients 1
    },
}


class UnknownLane(ValueError):
    """Raised for any lane not in LANES — including 'engine', which is not a lane."""


def _insert_token(token: str, user_id: int, expires_at, lane: str) -> None:
    """Persist a minted token. Split out so mint_token is testable without a database."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO terminal_auth_tokens (token, user_id, expires_at, lane)
            VALUES (%s, %s, %s, %s)
            """,
            (token, user_id, expires_at, lane),
        )


def mint_token(user_id: int, lane: str) -> dict:
    """Mint a one-time, LANE-BOUND token and return it with the URL to open.

    The lane is stored on the row, so the proxy for the OTHER lane will refuse it. Minting
    without a lane produces a token every proxy rejects — and it fails invisibly from the
    UI's side, as a surprise password prompt rather than an error.
    """
    config = LANES.get(lane)
    if config is None:
        raise UnknownLane(f"Unknown terminal lane: {lane!r}")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS)
    _insert_token(token, user_id, expires_at, lane)

    logger.info("Minted terminal token user_id=%s lane=%s", user_id, lane)
    return {
        "token": token,
        "url": f"{config['url']}?token={token}",
        "expires_in": TOKEN_TTL_SECONDS,
        "lane": lane,
        "sandboxed": config["sandboxed"],
    }


def _probe(port: int) -> bool:
    """Is the proxy on *port* answering?

    ⚠️ ANY HTTP status means reachable — including 401, which is what an unauthenticated
    probe SHOULD get and is the normal healthy answer. Checking for 200 would report every
    lane as permanently down. Only a connection failure or timeout means unreachable.
    """
    conn = None
    try:
        conn = http.client.HTTPConnection(PROBE_HOST, port, timeout=PROBE_TIMEOUT_SECONDS)
        conn.request("GET", "/")
        conn.getresponse()
        return True
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def lane_status() -> list:
    """Per-lane status for the cockpit, in a stable order.

    ``reachable`` is a REAL probe of the proxy, never a guess.

    ``busy`` is ``None`` — meaning UNKNOWN, not "free". The codex lane runs ttyd with
    --max-clients 1, but its seat count is not observable from outside without opening a
    websocket, which would CONSUME the seat when it is free. Reporting False here would be
    a confident wrong answer, so the UI must render None as "seat state unknown" rather
    than as availability.
    """
    out = []
    for lane, config in LANES.items():
        out.append(
            {
                "lane": lane,
                "label": config["label"],
                "reachable": _probe(config["proxy_port"]),
                "sandboxed": config["sandboxed"],
                "single_seat": config["single_seat"],
                "busy": None,
            }
        )
    return out
