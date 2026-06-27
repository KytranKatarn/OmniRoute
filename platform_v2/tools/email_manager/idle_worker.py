"""IMAP IDLE workers — one daemon thread per mailbox, writes to email_push_events on EXISTS.

Runs inside archie_scheduler (ARCHIE_RUN_SCHEDULER=1, single process).
SSE clients in archie_platform poll email_push_events via DB — no in-process
Queue needed.
"""

from __future__ import annotations

import imaplib
import logging
import ssl
import threading
import time

logger = logging.getLogger(__name__)

_IMAP_HOST = "stalwart_mail"
_IMAP_PORT = 993
_IDLE_TIMEOUT = 25 * 60  # 25 min — re-IDLE before server drops at RFC-mandated 29 min
_RETRY_DELAY = 60  # seconds between reconnect attempts on error

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

    while True:
        imap = None
        try:
            imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, ssl_context=ctx)
            imap.login(username, password)
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
            logger.warning("[IDLE] IMAP auth/protocol error %s: %s", address, exc)
            time.sleep(_RETRY_DELAY)
        except Exception as exc:
            logger.warning("[IDLE] connection error %s: %s", address, exc)
            time.sleep(_RETRY_DELAY)
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
