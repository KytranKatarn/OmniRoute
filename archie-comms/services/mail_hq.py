"""Cockpit-side proxy to the platform Mail HQ endpoints. Server-side only — INTERNAL_API_KEY
never reaches the browser. Reads free; the SEND is gated (queue_reply creates an approval the
existing gate executes). Slice 3 of the COO command surface."""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def _timeout():
    return float(os.getenv("MAIL_TIMEOUT", "20"))


def inbox(limit=40):
    try:
        r = requests.get(
            f"{_base()}/api/internal/mail/inbox", headers=_headers(), params={"limit": limit}, timeout=_timeout()
        )
        if r.status_code == 200:
            return {"messages": r.json().get("messages", [])}
    except Exception as e:
        logger.warning("mail inbox proxy failed: %s", e)
    return {"messages": []}


def message(mid):
    try:
        r = requests.get(f"{_base()}/api/internal/mail/message/{int(mid)}", headers=_headers(), timeout=_timeout())
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("mail message proxy failed: %s", e)
    return {"success": False}


def draft_reply(mid):
    try:
        r = requests.post(
            f"{_base()}/api/internal/mail/draft-reply",
            json={"message_id": int(mid)},
            headers=_headers(),
            timeout=float(os.getenv("MAIL_DRAFT_TIMEOUT", "120")),
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("mail draft proxy failed: %s", e)
    return {"success": False}


def queue_reply(mid, body):
    try:
        r = requests.post(
            f"{_base()}/api/internal/mail/queue-reply",
            json={"message_id": int(mid), "body": body},
            headers=_headers(),
            timeout=_timeout(),
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("mail queue proxy failed: %s", e)
    return {"success": False}
