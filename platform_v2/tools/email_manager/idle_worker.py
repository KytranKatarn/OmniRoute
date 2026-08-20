"""IMAP IDLE workers — one daemon thread per mailbox, writes to email_push_events on EXISTS.

Runs inside archie_scheduler (ARCHIE_RUN_SCHEDULER=1, single process).
SSE clients in archie_platform poll email_push_events via DB — no in-process
Queue needed.
"""

from __future__ import annotations

import imaplib
import logging
import re
import ssl
import threading
import time

logger = logging.getLogger(__name__)

_IMAP_HOST = "stalwart_mail"
_IMAP_PORT = 993
_IDLE_TIMEOUT = 25 * 60  # 25 min — re-IDLE before server drops at RFC-mandated 29 min
_RETRY_DELAY = 60  # seconds between reconnect attempts on a TRANSIENT error

# #5844 — a PERMANENT auth failure must not be retried at the transient rate.
#
# `[AUTHENTICATIONFAILED]` means the server accepted the connection, read the LOGIN, and
# REJECTED the credential. It cannot fix itself: it needs a human to correct the stored
# password. Retrying it every 60s is not resilience, it is a credential-guessing loop.
#
# Measured 2026-08-19: kytran@ produced 215 failures in 3 hours (60/h here plus the 5-min
# poll path) while every other mailbox authenticated fine. Two harms:
#   1. it buries real errors in the scheduler log, and
#   2. Stalwart bans on scan-like behaviour. KB #290279: ONE "Invalid IMAP command" banned
#      an internal IP for 20 HOURS, across EVERY listener, taking all 156 mailboxes down.
#      A hundreds-per-day failed-auth stream from one container IP is exactly that shape.
#
# So back OFF, but never give UP: the delay grows 5min -> 1h and resets on the next
# successful login, so a corrected password self-heals without a restart.
_AUTH_FAIL_BACKOFF_START = 300  # 5 min
_AUTH_FAIL_BACKOFF_MAX = 3600  # 1 h

# Deliberately narrow: ONLY an explicit credential rejection counts as permanent. Anything
# else (timeout, TLS, protocol desync, server restart) keeps the fast transient retry,
# because misreading a transient fault as permanent would silently slow a healthy mailbox.
_PERMANENT_AUTH_RE = re.compile(
    r"AUTHENTICATIONFAILED|AUTHORIZATIONFAILED|invalid\s+credentials|authentication\s+failed",
    re.I,
)


# How many fast attempts a TRANSIENT fault gets before it, too, starts escalating.
_TRANSIENT_FAST_ATTEMPTS = 5


def is_permanent_auth_failure(exc) -> bool:
    """True when the server explicitly REJECTED the credential (vs any transient fault)."""
    return bool(_PERMANENT_AUTH_RE.search(str(exc or "")))


def retry_delay_for(consecutive_failures: int, permanent: bool) -> int:
    """Seconds to wait before the next attempt. Pure, so it is testable in isolation.

    Raised in review of PR #2718: `_PERMANENT_AUTH_RE` is deliberately narrow, so a
    credential rejection phrased some OTHER way would be classified transient and fall back
    to retrying every 60s forever — precisely the hammering this change exists to stop.
    That was a fair objection, and widening the regex is the wrong answer: it trades a false
    negative for a false POSITIVE, and a false positive silently slows a HEALTHY mailbox.

    So the backoff no longer depends on classification alone. EVERY repeated failure escalates
    once it has proven persistent; the classifier only decides HOW FAST:

      * permanent  -> straight to the long ladder (5min -> 1h). A rejected credential will
        not fix itself, so there is nothing to gain from fast retries.
      * transient  -> `_TRANSIENT_FAST_ATTEMPTS` quick tries first, because a dropped socket
        or a server restart really does clear on its own, and a healthy mailbox must not be
        punished for a blip. Only after that does it escalate to the same 1h ceiling.

    Both paths are capped, and the caller resets the counter on a successful login, so any
    recovery — fixed password, server back up — returns to normal with no restart.
    """
    n = max(1, int(consecutive_failures))
    if permanent:
        return min(_AUTH_FAIL_BACKOFF_START * (2 ** (n - 1)), _AUTH_FAIL_BACKOFF_MAX)
    if n <= _TRANSIENT_FAST_ATTEMPTS:
        return _RETRY_DELAY
    return min(_RETRY_DELAY * (2 ** (n - _TRANSIENT_FAST_ATTEMPTS)), _AUTH_FAIL_BACKOFF_MAX)


_workers: dict[int, threading.Thread] = {}
_workers_lock = threading.Lock()
_started = False
_started_lock = threading.Lock()


def _write_push_event(mailbox_id: int, count: int) -> None:
    """Write a new-mail event to the DB so SSE pollers in archie_platform pick it up."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO email_push_events (mailbox_id, count) VALUES (%s, %s)",
                (mailbox_id, count),
            )
    except Exception as exc:
        logger.debug("[IDLE] push event write failed mailbox %d: %s", mailbox_id, exc)


def _idle_loop(mailbox_id: int, address: str, password: str) -> None:
    """Blocking IMAP IDLE loop for one mailbox. Reconnects forever on error."""
    username = address.split("@")[0]
    # Stalwart mail uses a Let's Encrypt cert (for mail.kytranempowerment.com).
    # The system CA bundle trusts Let's Encrypt, so CERT_REQUIRED works without
    # any pinning file.  check_hostname stays False because we connect to the
    # Docker-internal hostname "stalwart_mail", not the cert's CN — hostname
    # verification would always fail here regardless of cert validity.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    # CERT_REQUIRED is the default for create_default_context(); stated explicitly
    # so the intent is obvious and a future reader cannot accidentally revert it.
    ctx.verify_mode = ssl.CERT_REQUIRED

    consecutive = 0

    while True:
        imap = None
        try:
            imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, ssl_context=ctx)
            imap.login(username, password)
            # Logged in — a corrected password (or a recovered server) resets the ladder
            # here, so recovery needs no restart.
            consecutive = 0
            imap.select("INBOX")

            _, data = imap.search(None, "ALL")
            last_count = len(data[0].split()) if data[0] else 0

            # Send IDLE command
            tag = imap._new_tag().decode()
            imap.send(f"{tag} IDLE\r\n".encode())
            imap.readline()  # "+ idling" continuation

            imap.socket().settimeout(_IDLE_TIMEOUT)
            try:
                while True:
                    line = imap.readline()
                    if not line:
                        break
                    text = line.decode(errors="replace").strip()

                    if "EXISTS" in text:
                        # New message arrived — exit IDLE, sync count, notify
                        imap.send(b"DONE\r\n")
                        imap.readline()  # tagged OK

                        _, data = imap.search(None, "ALL")
                        new_count = len(data[0].split()) if data[0] else 0
                        delta = max(0, new_count - last_count)
                        if delta > 0:
                            _write_push_event(mailbox_id, delta)
                            last_count = new_count
                            # Slice 1: pull the new message body NOW (don't wait for the
                            # 5-min poll). Uses its own IMAP connection; isolated so a sync
                            # error can never kill this IDLE loop. This also drives the
                            # Slice 2 A.R.C.H.I.E. advisory in near-real-time.
                            try:
                                from .sync_jobs import sync_single_mailbox_full

                                sync_single_mailbox_full(mailbox_id, address, password)
                            except Exception as _sync_exc:
                                logger.debug("[IDLE] instant body-fetch failed %s: %s", address, _sync_exc)
                        break  # re-IDLE on next loop iteration
            except OSError:
                # socket timeout or connection drop — reconnect
                pass

        except imaplib.IMAP4.error as exc:
            consecutive += 1
            permanent = is_permanent_auth_failure(exc)
            delay = retry_delay_for(consecutive, permanent)
            if permanent and consecutive == 1:
                # Log LOUD once with the remedy — the first line is the actionable one and
                # every repeat after it only hides other failures.
                logger.warning(
                    "[IDLE] %s: credential REJECTED by the server (%s). Backing off to %ds "
                    "(max %ds) — this needs the stored imap_password corrected; retrying "
                    "fast would risk a Stalwart scan-ban (KB #290279).",
                    address,
                    exc,
                    delay,
                    _AUTH_FAIL_BACKOFF_MAX,
                )
            elif not permanent and consecutive <= _TRANSIENT_FAST_ATTEMPTS:
                logger.warning("[IDLE] IMAP protocol error %s: %s", address, exc)
            else:
                logger.debug(
                    "[IDLE] %s: failure %d (permanent=%s); next try in %ds", address, consecutive, permanent, delay
                )
            time.sleep(delay)
        except Exception as exc:
            consecutive += 1
            delay = retry_delay_for(consecutive, False)
            if consecutive <= _TRANSIENT_FAST_ATTEMPTS:
                logger.warning("[IDLE] connection error %s: %s", address, exc)
            else:
                logger.debug("[IDLE] %s: connection failure %d; next try in %ds", address, consecutive, delay)
            time.sleep(delay)
        finally:
            if imap is not None:
                try:
                    imap.send(b"DONE\r\n")
                except Exception:
                    pass
                try:
                    imap.logout()
                except Exception:
                    pass


def start_idle_workers() -> None:
    """Start one daemon IMAP IDLE thread per provisioned mailbox. Safe to call once at startup."""
    global _started
    with _started_lock:
        if _started:
            return
        _started = True

    try:
        from database import get_db_cursor
    except Exception as exc:
        logger.error("[IDLE] startup aborted — import error: %s", exc)
        return

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, address, imap_password FROM email_mailboxes "
                "WHERE provisioned = TRUE AND active = TRUE AND imap_password IS NOT NULL"
            )
            mailboxes = cur.fetchall()
    except Exception as exc:
        logger.error("[IDLE] DB query failed: %s", exc)
        return

    with _workers_lock:
        for row in mailboxes:
            mid = row["id"]
            if mid in _workers and _workers[mid].is_alive():
                continue
            t = threading.Thread(
                target=_idle_loop,
                args=(mid, row["address"], row["imap_password"]),
                daemon=True,
                name=f"email-idle-{row['address']}",
            )
            t.start()
            _workers[mid] = t

    logger.info("[IDLE] Started %d IMAP IDLE workers", len(_workers))
