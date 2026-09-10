#!/usr/bin/env python3
"""
ttyd Auth Proxy for A.R.C.H.I.E.

Sits in front of ttyd, validating Basic Auth credentials against the
platform's `users` table (Werkzeug-hashed passwords).  Only active admin
users are allowed through.

Architecture:
    Browser --:7681--> this proxy --:17681--> ttyd (localhost, no auth)

Handles both regular HTTP (ttyd serves HTML/JS assets) and WebSocket
upgrade requests (the actual terminal session).
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import signal
import sys
import time
from urllib.parse import urlparse, parse_qs, urlencode

import psycopg2
import websockets
from werkzeug.security import check_password_hash

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LISTEN_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "7681"))
TTYD_HOST = os.environ.get("TTYD_HOST", "127.0.0.1")
TTYD_PORT = int(os.environ.get("TTYD_PORT", "17681"))

# Which coder lane THIS instance fronts. Both lanes run this same script and consult the
# same terminal_auth_tokens table, differing only in the environment below — so the lane is
# the only thing distinguishing "a token for the sandbox" from "a token for the host shell".
# Read at call time via configured_lane() so a unit-file change needs only a restart.
PROXY_LANE = os.environ.get("PROXY_LANE", "").strip()

DB_HOST = os.environ.get("DB_HOST", "192.168.1.200")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "archie")
DB_USER = os.environ.get("DB_USER", "archie")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

REALM = "Claude Terminal"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ttyd-auth] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _read_db_password():
    """Read DB password from env or from start_host_monitor.sh as fallback."""
    pw = DB_PASSWORD
    if pw:
        return pw
    # Fallback: read from start_host_monitor.sh
    monitor_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_host_monitor.sh")
    try:
        with open(monitor_script) as f:
            for line in f:
                if line.strip().startswith("export DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return pw
    except FileNotFoundError:
        pass
    return "archie_secure_2024"


_db_password_cached = None


def get_db_password():
    global _db_password_cached
    if _db_password_cached is None:
        _db_password_cached = _read_db_password()
    return _db_password_cached


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=get_db_password(),
    )


def authenticate(username: str, password: str) -> bool:
    """Validate credentials against the users table.

    Returns True only if the user exists, is_active=True, is_admin=True,
    and the password matches the stored Werkzeug hash.
    """
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users "
                    "WHERE lower(username) = lower(%s) "
                    "AND is_active = TRUE AND is_admin = TRUE",
                    (username,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if row is None:
            return False

        return check_password_hash(row[0], password)
    except Exception:
        logger.exception("Authentication DB error")
        return False


def configured_lane() -> str:
    """The lane this proxy instance serves; empty when unconfigured.

    Read from the environment at call time rather than captured at import, so rotating a
    unit file needs only a restart. An empty value means REFUSE — never "any lane".
    """
    return os.environ.get("PROXY_LANE", "").strip()


def _lookup_token_row(token: str):
    """``(id, user_id, lane)`` for a live, unused token, else ``None``.

    Split out from validate_token so the gate can be tested without a database.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, lane FROM terminal_auth_tokens "
                "WHERE token = %s AND used = FALSE AND expires_at > NOW()",
                (token,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def _consume_token(token_id: int) -> None:
    """Burn a token so it cannot be replayed."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE terminal_auth_tokens SET used = TRUE WHERE id = %s",
                (token_id,),
            )
        conn.commit()
    finally:
        conn.close()


def validate_token(token: str, lane: str):
    """Consume a one-time terminal token, but ONLY for the lane it was minted for.

    Returns the token's ``user_id`` when it is valid for *lane*, else ``None``. It returns
    the id rather than a bool because the caller needs to know whose session to establish.

    Both coder lanes run THIS script against THE SAME table and differ only in environment,
    so without this check a token minted for the sandboxed codex lane opens the claude HOST
    shell, and the reverse. Fails closed three ways: an unconfigured lane, a legacy NULL
    lane, and a mismatch. A refused token is deliberately NOT consumed — burning it would
    let anyone invalidate someone else's session by presenting it to the wrong proxy.
    """
    if not lane:
        logger.error(
            "Refusing token auth: PROXY_LANE is not configured (fail-closed). " "Set it on this unit and restart."
        )
        return None
    try:
        row = _lookup_token_row(token)
        if row is None:
            return None
        token_id, user_id, token_lane = row
        if token_lane != lane:
            logger.warning(
                "Refusing token auth: token was minted for lane=%r but presented to lane=%r",
                token_lane,
                lane,
            )
            return None
        _consume_token(token_id)
        logger.info("Token auth OK token_id=%s user_id=%s lane=%s", token_id, user_id, lane)
        return user_id
    except Exception:
        logger.exception("Token validation DB error")
        return None


# ---------------------------------------------------------------------------
# Session cookie
#
# A one-time token authenticates exactly ONE request. A ttyd page is the document, then
# its scripts and styles, then a websocket upgrade — so on a valid token we set a signed,
# short-lived cookie and accept that on the requests which follow.
# ---------------------------------------------------------------------------

COOKIE_NAME = "archie_tty"
COOKIE_TTL_SECONDS = 900  # 15 minutes, sliding — re-issued on every accepted request


def _cookie_secret() -> bytes:
    """The signing key, or b"" when unconfigured (which means: accept no cookies)."""
    return os.environ.get("TTYD_COOKIE_SECRET", "").strip().encode()


def _sign(payload: bytes) -> str:
    return hmac.new(_cookie_secret(), payload, hashlib.sha256).hexdigest()


def mint_cookie(user_id: int, lane: str) -> str:
    """``<b64(user_id:lane:expiry)>.<hmac>``, or "" when there is no signing secret."""
    if not _cookie_secret():
        logger.error("TTYD_COOKIE_SECRET is not set — cannot mint a session cookie.")
        return ""
    raw = f"{user_id}:{lane}:{int(time.time()) + COOKIE_TTL_SECONDS}".encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}.{_sign(body.encode())}"


def verify_cookie(value: str, lane: str):
    """The ``user_id`` when the cookie is valid FOR THIS LANE and unexpired, else ``None``.

    The lane binding carries through from the token: a codex cookie must not open claude.
    Fails closed on an unset secret, and never raises on malformed input — a garbage
    cookie is a refusal, not a 500 inside the proxy.
    """
    if not value or not _cookie_secret() or not lane:
        return None
    try:
        body, sig = value.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(body.encode()).encode(), sig.encode()):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        decoded = base64.urlsafe_b64decode(body + pad).decode()
        user_id, cookie_lane, expiry = decoded.split(":")
        if cookie_lane != lane or int(expiry) <= int(time.time()):
            return None
        return int(user_id)
    except Exception:
        return None


def build_set_cookie(user_id: int, lane: str) -> str:
    """The Set-Cookie header value, or "" when unconfigured.

    ``Secure; SameSite=None`` is REQUIRED, not a preference. The cockpit is reached at
    http://192.168.1.200:3002 — a bare IP is its own site — while the terminal is served
    from *.kytranempowerment.com, so the iframe is CROSS-SITE and a Strict or Lax cookie
    would never be sent at all. Do not "harden" this to Strict; that silently empties the
    pane. It is safe only because frame_ancestors() restricts who may embed us.
    """
    value = mint_cookie(user_id, lane)
    if not value:
        return ""
    return f"{COOKIE_NAME}={value}; Max-Age={COOKIE_TTL_SECONDS}; Path=/; " "HttpOnly; Secure; SameSite=None"


def parse_cookie_header(raw_request: bytes):
    """Our session cookie's value from a raw request, else ``None``."""
    for line in raw_request.split(b"\r\n"):
        if line.lower().startswith(b"cookie:"):
            for part in line.split(b":", 1)[1].split(b";"):
                name, _, value = part.strip().partition(b"=")
                if name == COOKIE_NAME.encode():
                    return value.decode("utf-8", errors="replace")
    return None


def frame_ancestors() -> str:
    """Who may embed this terminal. Fails CLOSED: unset means nobody.

    This is the required other half of ``SameSite=None``. Without it, any page anywhere
    could iframe the terminal and the browser would attach the owner's session cookie.
    """
    return os.environ.get("TTYD_FRAME_ANCESTORS", "").strip() or "'none'"


def inject_response_headers(head: bytes, set_cookie: str = "") -> bytes:
    """Add our headers to an upstream response's header block.

    *head* ends with the blank-line terminator; we splice before it so the block stays
    well-formed. The CSP goes on EVERY response, cookie or not.
    """
    extra = f"Content-Security-Policy: frame-ancestors {frame_ancestors()}\r\n"
    if set_cookie:
        extra += f"Set-Cookie: {set_cookie}\r\n"
    return head[:-2] + extra.encode() + b"\r\n"


# ---------------------------------------------------------------------------
# HTTP helpers – build raw HTTP responses
# ---------------------------------------------------------------------------


def _make_401_response() -> bytes:
    body = b"401 Unauthorized\nAdmin credentials required."
    return (
        b"HTTP/1.1 401 Unauthorized\r\n"
        b'WWW-Authenticate: Basic realm="' + REALM.encode() + b'"\r\n'
        b"Content-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + body
    )


def _make_403_response() -> bytes:
    body = b"403 Forbidden\nAdmin access required."
    return (
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + body
    )


# ---------------------------------------------------------------------------
# Extract credentials from raw HTTP request bytes
# ---------------------------------------------------------------------------


def parse_basic_auth(raw_request: bytes):
    """Return (username, password) or None if no valid Basic Auth header."""
    for line in raw_request.split(b"\r\n"):
        if line.lower().startswith(b"authorization: basic "):
            encoded = line.split(b" ", 2)[2]
            try:
                decoded = base64.b64decode(encoded).decode("utf-8")
                if ":" in decoded:
                    user, passwd = decoded.split(":", 1)
                    return user, passwd
            except Exception:
                return None
    return None


def parse_token_from_request(raw_request: bytes):
    """Extract a ``token`` query parameter from the request URL.

    Returns ``(token, stripped_request)`` where *stripped_request* has the
    ``token`` parameter removed from the URL so that ttyd never sees it.
    If no token is present, returns ``(None, raw_request)`` unchanged.
    """
    first_line, rest = raw_request.split(b"\r\n", 1)
    parts = first_line.split(b" ")
    if len(parts) < 3:
        return None, raw_request

    method, raw_url, version = parts[0], parts[1], parts[2]
    url_str = raw_url.decode("utf-8", errors="replace")

    parsed = urlparse(url_str)
    params = parse_qs(parsed.query, keep_blank_values=True)

    if "token" not in params:
        return None, raw_request

    # Grab the first token value
    token = params["token"][0]

    # Remove the token param and rebuild the URL
    del params["token"]
    # parse_qs returns lists; flatten back for urlencode
    cleaned_query = urlencode(
        {k: v[0] if len(v) == 1 else v for k, v in params.items()},
        doseq=True,
    )
    cleaned_path = parsed.path
    if cleaned_query:
        cleaned_path += "?" + cleaned_query

    new_first_line = method + b" " + cleaned_path.encode("utf-8") + b" " + version
    stripped_request = new_first_line + b"\r\n" + rest

    return token, stripped_request


def is_websocket_upgrade(raw_request: bytes) -> bool:
    lower = raw_request.lower()
    return b"upgrade: websocket" in lower


def extract_path(raw_request: bytes) -> str:
    """Extract the request path from the first line."""
    first_line = raw_request.split(b"\r\n", 1)[0]
    parts = first_line.split(b" ")
    if len(parts) >= 2:
        return parts[1].decode("utf-8", errors="replace")
    return "/"


# ---------------------------------------------------------------------------
# Plain HTTP proxy (non-WebSocket requests)
# ---------------------------------------------------------------------------


async def proxy_http(reader, writer, raw_request: bytes, set_cookie: str = ""):
    """Forward a plain HTTP request to ttyd and relay the response.

    The response's header block is read whole so our own headers can be spliced in — the
    frame-ancestors CSP always, and a Set-Cookie when the caller just authenticated.

    ⚠️ The websocket path deliberately does NOT do this: a 101 Switching Protocols cannot
    reliably carry Set-Cookie, and it does not need to — the document is fetched first, so
    the cookie is already set by the time the socket opens.
    """
    try:
        upstream_r, upstream_w = await asyncio.open_connection(TTYD_HOST, TTYD_PORT)
        upstream_w.write(raw_request)
        await upstream_w.drain()

        try:
            head = await upstream_r.readuntil(b"\r\n\r\n")
            writer.write(inject_response_headers(head, set_cookie))
            await writer.drain()
        except asyncio.IncompleteReadError as exc:
            # No complete header block (ttyd died mid-response). Relay what arrived
            # rather than silently truncating to nothing.
            writer.write(exc.partial)
            await writer.drain()

        while True:
            chunk = await upstream_r.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()

        upstream_w.close()
    except Exception:
        logger.exception("HTTP proxy error")
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# WebSocket proxy
# ---------------------------------------------------------------------------


async def proxy_websocket(reader, writer, raw_request: bytes):
    """Proxy a WebSocket connection to ttyd.

    We use the `websockets` library for the upstream (to ttyd) side,
    but handle the downstream (browser) side at the raw TCP level by
    forwarding the original upgrade request and then bridging frames.
    """
    path = extract_path(raw_request)

    try:
        # Forward the original upgrade request to ttyd verbatim.
        upstream_r, upstream_w = await asyncio.open_connection(TTYD_HOST, TTYD_PORT)
        upstream_w.write(raw_request)
        await upstream_w.drain()

        # Relay bytes bidirectionally until one side closes.
        async def forward(src, dst):
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass

        t1 = asyncio.create_task(forward(upstream_r, writer))
        t2 = asyncio.create_task(forward(reader, upstream_w))

        done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()

        upstream_w.close()
    except Exception:
        logger.exception("WebSocket proxy error")
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Main connection handler
# ---------------------------------------------------------------------------


async def handle_connection(reader, writer):
    """Handle one incoming connection: authenticate, then proxy."""
    peer = writer.get_extra_info("peername")
    try:
        raw_request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
        writer.close()
        return

    # --- Token-based auth (checked first) ---
    lane = configured_lane()
    token, stripped_request = parse_token_from_request(raw_request)
    if token is not None and token:
        token_user_id = validate_token(token, lane)
        if token_user_id is not None:
            logger.info("Token auth succeeded from %s lane=%s", peer, lane)
            ws = is_websocket_upgrade(stripped_request)
            if ws:
                await proxy_websocket(reader, writer, stripped_request)
            else:
                # The one-time token authenticates THIS request only; hand back a session
                # cookie so the page's assets and its websocket authenticate too.
                await proxy_http(
                    reader,
                    writer,
                    stripped_request,
                    set_cookie=build_set_cookie(token_user_id, lane),
                )
            return
        else:
            # Token not recognized as SSO — could be a ttyd internal token.
            # Fall through to Basic Auth instead of hard 403.
            logger.info("Token not SSO, falling through to Basic Auth from %s", peer)
            raw_request = stripped_request  # use URL with token stripped

    # --- Session cookie (set by a prior token request) ---
    # This is what makes the pane work at all: the token authenticates one request, and
    # a ttyd page is a document plus its assets plus a websocket. Re-issued on every
    # accepted request, which is what makes the 15-minute window SLIDING rather than
    # absolute — it lapses on idleness, not mid-session.
    cookie_user_id = verify_cookie(parse_cookie_header(raw_request) or "", lane)
    if cookie_user_id is not None:
        if is_websocket_upgrade(raw_request):
            await proxy_websocket(reader, writer, raw_request)
        else:
            await proxy_http(
                reader,
                writer,
                raw_request,
                set_cookie=build_set_cookie(cookie_user_id, lane),
            )
        return

    # --- Basic Auth fallback ---
    creds = parse_basic_auth(raw_request)
    if creds is None:
        writer.write(_make_401_response())
        await writer.drain()
        writer.close()
        return

    username, password = creds
    if not authenticate(username, password):
        logger.warning("Auth failed for user=%s from %s", username, peer)
        writer.write(_make_401_response())
        await writer.drain()
        writer.close()
        return

    logger.info("Auth OK user=%s from %s", username, peer)

    ws = is_websocket_upgrade(raw_request)
    logger.info(
        "BasicAuth request type: %s, path: %s",
        "WS" if ws else "HTTP",
        extract_path(raw_request),
    )
    if ws:
        await proxy_websocket(reader, writer, raw_request)
    else:
        await proxy_http(reader, writer, raw_request)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


async def main():
    server = await asyncio.start_server(handle_connection, LISTEN_HOST, LISTEN_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("ttyd auth proxy listening on %s", addrs)
    logger.info("Proxying to ttyd at %s:%s", TTYD_HOST, TTYD_PORT)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _signal_handler():
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    async with server:
        await stop
    logger.info("Shutting down")


if __name__ == "__main__":
    asyncio.run(main())
