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
import logging
import os
import signal
import sys
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


def validate_token(token: str) -> bool:
    """Validate a one-time terminal auth token against the DB.

    Looks up the token in ``terminal_auth_tokens``. If the token is valid
    (exists, not yet used, and not expired) it is immediately marked as
    used so it cannot be replayed.

    Returns True if the token was valid and consumed, False otherwise.
    """
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, user_id FROM terminal_auth_tokens "
                    "WHERE token = %s AND used = FALSE AND expires_at > NOW()",
                    (token,),
                )
                row = cur.fetchone()
                if row is None:
                    return False
                token_id, user_id = row
                cur.execute(
                    "UPDATE terminal_auth_tokens SET used = TRUE WHERE id = %s",
                    (token_id,),
                )
                conn.commit()
                logger.info("Token auth OK token_id=%s user_id=%s", token_id, user_id)
                return True
        finally:
            conn.close()
    except Exception:
        logger.exception("Token validation DB error")
        return False


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


async def proxy_http(reader, writer, raw_request: bytes):
    """Forward a plain HTTP request to ttyd and relay the response."""
    try:
        upstream_r, upstream_w = await asyncio.open_connection(TTYD_HOST, TTYD_PORT)
        upstream_w.write(raw_request)
        await upstream_w.drain()

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
    token, stripped_request = parse_token_from_request(raw_request)
    if token is not None and token:
        if validate_token(token):
            logger.info("Token auth succeeded from %s", peer)
            ws = is_websocket_upgrade(stripped_request)
            if ws:
                await proxy_websocket(reader, writer, stripped_request)
            else:
                await proxy_http(reader, writer, stripped_request)
            return
        else:
            # Token not recognized as SSO — could be a ttyd internal token.
            # Fall through to Basic Auth instead of hard 403.
            logger.info("Token not SSO, falling through to Basic Auth from %s", peer)
            raw_request = stripped_request  # use URL with token stripped

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
