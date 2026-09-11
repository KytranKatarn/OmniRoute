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
        "icon": "\U0001F5A5",
        "role": "Direct CLI Access \u2014 Kytran Empowerment",
        "status": "TTYd Online \u2014 Claude CLI Ready",
        "features": [
            ("\U0001F4BB", "Full Claude CLI",
             "Direct terminal access to Claude Code. Run commands, edit files, build features."),
            ("\U0001F512", "Persistent Session",
             "tmux-backed session. Disconnect and reconnect without losing context."),
            ("\U0001F91D", "Trio Collaboration",
             "Work alongside A.R.C.H.I.E. and Claude together. She escalates when her team needs backup."),
        ],
        "label": "Claude",
        "blurb": "The shared Claude Code session — one session, every viewer sees the same screen.",
        "accent": "#a78bfa",
        # `url` is where the TERMINAL BYTES come from (the ttyd auth proxy).
        # `landing_host` is the PUBLIC front door that serves the landing page.
        # They are deliberately DIFFERENT hostnames: the landing page embeds the
        # proxy in an iframe, so one hostname cannot be both without the page
        # trying to frame itself.
        "url": "https://terminal.kytranempowerment.com",
        "landing_host": "claude.kytranempowerment.com",
        "proxy_port": 7681,
        # The HOST shell. This is the single most important fact on the page.
        "sandboxed": False,
        "single_seat": False,
    },
    "codex": {
        "icon": "\U0001F9EA",
        "role": "Contained Coding Lane \u2014 Kytran Empowerment",
        "status": "TTYd Online \u2014 Codex CLI Ready",
        "features": [
            ("\U0001F4E6", "Fully Containerised",
             "Runs in its own container with its own volumes. The filesystem it sees is not the host's."),
            ("\U0001F464", "One Seat",
             "ttyd --max-clients 1. A single viewer at a time, so two people never fight over one keyboard."),
            ("\U0001F6E1", "Scoped by Design",
             "On a bridge network with no reach into any platform container. Blast radius is the box it lives in."),
        ],
        "label": "Codex",
        "blurb": "The containerised Codex CLI lane. One viewer at a time.",
        "accent": "#22d3ee",
        # ⚠️ codex.kytranempowerment.com served the ttyd PROXY directly until
        # 2026-09-11. It is now the LANDING host (matching claude), and the proxy
        # moved to codex-tty. — a lane cannot serve its own landing page and be
        # framed by it at the same time.
        "url": "https://codex-tty.kytranempowerment.com",
        "landing_host": "codex.kytranempowerment.com",
        "proxy_port": 7683,
        "sandboxed": True,
        "single_seat": True,  # ttyd --max-clients 1
    },
    "archie-tui": {
        "icon": "\U0001F6F8",
        "role": "The Lane That Builds The Platform \u2014 Kytran Empowerment",
        "status": "TTYd Online \u2014 A.R.C.H.I.E. TUI Ready",
        "features": [
            ("\u2699", "Wired To The Engine",
             "Speaks to archie_engine over a websocket. Not a shell \u2014 a purpose-built terminal UI."),
            ("\U0001F3D7", "Edits The Platform Itself",
             "The lane A.R.C.H.I.E. uses to change her own code, beside the engine rather than behind a container wall."),
            ("\U0001F465", "Built For Approved Staff",
             "Earmarked for an explicit per-user allowlist, so trusted humans can work with A.R.C.H.I.E. directly."),
        ],
        "label": "ARCHIE TUI",
        "blurb": "A.R.C.H.I.E.'s own terminal UI, wired to the engine. The lane that builds the platform.",
        "accent": "#34d399",
        # Same split as codex: tui. is the landing host, tui-tty. the proxy.
        "url": "https://tui-tty.kytranempowerment.com",
        "landing_host": "tui.kytranempowerment.com",
        "proxy_port": 7684,
        # ⚠️ HOST, deliberately — owner decision 2026-09-11. This is the lane that edits
        # the PLATFORM, so it runs beside the engine on the host rather than in a
        # container: archie_engine publishes on 127.0.0.1:9090 only, and a container
        # would have to be given a path to it. The blast radius is the price of the
        # capability, so it carries the same HOST marker as the claude lane.
        #
        # Unlike claude/codex it is NOT a shell — it is a Go TUI that speaks to the
        # engine over a websocket, which is why it is the lane earmarked for approved
        # staff later (explicit per-user allowlist, owner decision 2026-09-11). That
        # widening is NOT in this change: the mint stays admin-only.
        "sandboxed": False,
        "single_seat": False,
    },
    "opencode": {
        "label": "OpenCode",
        "blurb": "The containerised OpenCode lane \u2014 a second sandboxed coder, so a task never waits on one tool.",
        "accent": "#fbbf24",
        # Same split as the others: opencode. is the landing host, opencode-tty. the proxy.
        "url": "https://opencode-tty.kytranempowerment.com",
        "landing_host": "opencode.kytranempowerment.com",
        "proxy_port": 7685,
        # CONTAINED, like codex. Owner's call ("the codex and opencode can be
        # container") and the right default for a tool new to this cluster: a host
        # lane has to earn that placement the way archie-tui did.
        "sandboxed": True,
        "single_seat": True,  # ttyd --max-clients 1
        "icon": "\U0001F7E1",
        "role": "Second Sandboxed Coder \u2014 Kytran Empowerment",
        "status": "TTYd Online \u2014 OpenCode Ready",
        "features": [
            ("\U0001F501", "A Second Opinion",
             "A different coding agent on the same work. When one tool gets stuck, the other is already warm."),
            ("\U0001F4E6", "Fully Containerised",
             "Its own container, its own volumes, cap_drop ALL. The filesystem it sees is not the host's."),
            ("\U0001F464", "One Seat",
             "ttyd --max-clients 1, like Codex. A single viewer at a time."),
        ],
    },
}


class UnknownLane(ValueError):
    """Raised for any lane not in LANES — including 'engine', which is not a lane."""


def lane_for_host(host: str):
    """Resolve a request Host header to a lane key, or None for the comms host.

    Matches the FIRST LABEL exactly, never a substring. `"claude" in host` — the
    test this replaced — also matches `claude-cli.`, `notclaude.`, and any future
    hostname that merely contains the word, which would silently serve the wrong
    lane's landing page and send its Connect button to the wrong terminal.
    """
    if not host:
        return None
    label = host.lower().split(":")[0].split(".")[0]
    for key, cfg in LANES.items():
        landing = cfg.get("landing_host")
        if landing and landing.split(".")[0] == label:
            return key
    return None


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


# ---------------------------------------------------------------------------
# WHO may use a lane (#6700)
# ---------------------------------------------------------------------------

def _live_grant_exists(user_id: int, lane: str) -> bool:
    """Is there an un-revoked grant for this (user, lane)? Split out so may_use_lane
    is testable without a database."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT 1 FROM terminal_lane_grants
             WHERE user_id = %s AND lane = %s AND revoked_at IS NULL
             LIMIT 1
            """,
            (user_id, lane),
        )
        return cur.fetchone() is not None


def may_use_lane(user_id, role: str, lane: str) -> bool:
    """THE authorization answer for a terminal lane. ONE function, two callers.

    Admins get every lane, by ROLE. Everyone else gets only the lanes explicitly
    granted to them in terminal_lane_grants — the owner's "explicit per-user
    allowlist" (2026-09-11), which exists so approved staff can use the archie-tui
    lane without being full platform admins.

    ⚠️ This must be called at the PAGE and at the MINT, not at one of them. Gating a
    choke point is the rule here (#5194, #5862, #2738 were all a correct guard that
    existed and was wired in only one of the places that needed it). The page can be
    skipped by calling the API directly; the mint can be skipped by nothing, but a
    page that renders for someone who can never mint is its own bug.

    FAILS CLOSED. An unknown lane, a missing user, an unreadable database — all
    refuse. A terminal is the last thing that should fail open, and a DB blip is not
    a reason to hand someone a host shell.
    """
    if lane not in LANES:
        logger.warning("lane access refused: unknown lane %r", lane)
        return False
    if not user_id:
        return False
    if role == "admin":
        return True

    try:
        granted = _live_grant_exists(int(user_id), lane)
    except Exception:
        logger.exception(
            "lane access refused: grant lookup failed user_id=%s lane=%s", user_id, lane
        )
        return False

    if not granted:
        logger.warning(
            "lane access refused: user_id=%s role=%s has no grant for lane=%s",
            user_id,
            role,
            lane,
        )
    return granted


def grant_lane(user_id: int, lane: str, granted_by: int, note: str = "") -> None:
    """Give a non-admin access to ONE lane. Idempotent on a live grant."""
    if lane not in LANES:
        raise UnknownLane(f"Unknown terminal lane: {lane!r}")
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO terminal_lane_grants (user_id, lane, granted_by, note)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, lane) WHERE revoked_at IS NULL DO NOTHING
            """,
            (user_id, lane, granted_by, note or None),
        )
    logger.info("lane granted user_id=%s lane=%s by=%s", user_id, lane, granted_by)


def revoke_lane(user_id: int, lane: str, revoked_by: int) -> None:
    """Revoke by STAMPING, never deleting — historical access to a host shell has to
    stay answerable."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE terminal_lane_grants
               SET revoked_at = now(), revoked_by = %s
             WHERE user_id = %s AND lane = %s AND revoked_at IS NULL
            """,
            (revoked_by, user_id, lane),
        )
    logger.info("lane revoked user_id=%s lane=%s by=%s", user_id, lane, revoked_by)


def lane_grants(lane: str = None) -> list:
    """Live grants, for an admin surface. Never includes admins — they are allowed by
    role, and listing them here would invent a second source of truth."""
    from database import get_db_cursor

    sql = """SELECT user_id, lane, granted_by, granted_at, note
               FROM terminal_lane_grants WHERE revoked_at IS NULL"""
    args = ()
    if lane:
        sql += " AND lane = %s"
        args = (lane,)
    with get_db_cursor() as (conn, cur):
        cur.execute(sql + " ORDER BY lane, user_id", args)
        return [dict(r) for r in cur.fetchall()]


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
