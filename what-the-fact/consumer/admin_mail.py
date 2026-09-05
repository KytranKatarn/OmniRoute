"""WTF Consumer — Admin Mail Dashboard (Citadel-resident, Hub-independent).

Reads and sends mail for the 5 what-the-fact.com business mailboxes
(contact/tip/press/api/admin@what-the-fact.com) directly over Hostinger
IMAP/SMTP — the same approach as the platform's WTF Hub mail reader
(platform_v2/tools/wtf_hub/mail_routes.py), ported here so mail management
keeps working even when the Hub (and its login) is unreachable. WTF's public
site (wtf-consumer/wtf-tech) already lives on Citadel; this closes the last
Hub dependency for day-to-day mail triage.

DELIBERATELY NOT PORTED: the AI triage/draft-reply endpoints. Those call
platform_v2's `department_dispatcher.dispatch()` as a direct IN-PROCESS
PYTHON IMPORT — there is no HTTP-callable form of the Bridge dispatcher
anywhere on the platform (ADR-013) — and their result table (`wtf_mail_ai`)
lives in the platform's own `archie` database, not WTF's `wtf` database.
Building a networked dispatch endpoint on the Hub is a separate, larger
project; this dashboard is read/send only. Do not add AI triage/draft here
without that prerequisite existing first — an import of
`department_dispatcher` or a reference to `wtf_mail_ai` anywhere in this file
is a sign the boundary was crossed back (see tests/test_admin_mail.py).

Read-only IMAP: select(..., readonly=True), BODY.PEEK (never sets \\Seen),
no delete/move. Passwords come from env only — never stored in a DB, never
logged.

Auth: HTTP Basic (WTF_ADMIN_MAIL_USER / WTF_ADMIN_MAIL_PASSWORD), gated at
the BLUEPRINT level via before_request so it protects the dashboard page
itself, not just the API. FAILS CLOSED — if either env var is unset, every
route under this blueprint refuses with 503 rather than silently allowing
every request through (mirrors `_password()`'s no-password-configured-means
-refuse behaviour for the mailboxes themselves). This is deliberately NOT
the platform's admin-session login and NOT WTF's public OAuth subscriber
login — both depend on infrastructure this dashboard exists to route around.
"""

import email
import html as htmllib
import imaplib
import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from flask import Blueprint, Response, jsonify, render_template, request

logger = logging.getLogger(__name__)

admin_mail_bp = Blueprint("admin_mail", __name__)

_IMAP_HOST = os.getenv("WTF_MAIL_IMAP_HOST", "imap.hostinger.com")
_IMAP_PORT = int(os.getenv("WTF_MAIL_IMAP_PORT") or 993)
_SMTP_HOST = os.getenv("WTF_MAIL_SMTP_HOST", "smtp.hostinger.com")
_SMTP_PORT = int(os.getenv("WTF_MAIL_SMTP_PORT") or 465)
_TIMEOUT = 15  # seconds — fail fast rather than wedge the web thread

# box key (what the client sends as ?box=) -> (address, env password key)
_BOXES = {
    "contact": ("contact@what-the-fact.com", "WTF_MAIL_CONTACT_PASSWORD"),
    "tip": ("tip@what-the-fact.com", "WTF_MAIL_TIP_PASSWORD"),
    "press": ("press@what-the-fact.com", "WTF_MAIL_PRESS_PASSWORD"),
    "api": ("api@what-the-fact.com", "WTF_MAIL_API_PASSWORD"),
    "admin": ("admin@what-the-fact.com", "WTF_MAIL_ADMIN_PASSWORD"),
}


def _password(box_key):
    """Per-box password, falling back to a single shared password if set."""
    _, envk = _BOXES[box_key]
    return os.getenv(envk) or os.getenv("WTF_MAIL_SHARED_PASSWORD") or ""


def _connect(box_key):
    """Return (imap_conn, address) logged in for box_key, or raise."""
    addr, _ = _BOXES[box_key]
    pw = _password(box_key)
    if not pw:
        raise RuntimeError("no password configured for this mailbox")
    m = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, timeout=_TIMEOUT)
    m.login(addr, pw)
    return m, addr


def _dec(s):
    """Decode an RFC2047 header to a plain unicode string (never raises)."""
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return str(s)


def _iso(raw_date):
    try:
        dt = parsedate_to_datetime(raw_date)
        return dt.isoformat() if dt else None
    except Exception:
        return None


def _uid_list(m, limit):
    """Newest-first list of up to `limit` UIDs in the selected mailbox."""
    typ, data = m.uid("SEARCH", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    uids = data[0].split()
    return [u.decode() for u in reversed(uids)][:limit]


def _header_summary(m, uid):
    typ, data = m.uid("FETCH", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None
    meta = data[0][0] or b""
    hdr = email.message_from_bytes(data[0][1] or b"")
    return {
        "uid": uid,
        "subject": _dec(hdr.get("Subject")) or "(no subject)",
        "from": _dec(hdr.get("From")),
        "date": _iso(hdr.get("Date")),
        "seen": b"\\Seen" in meta,
    }


def _part_text(part):
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


_TAG_BLOCK_RE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_BR_RE = re.compile(r"(?i)<(br|/p|/div|/tr|/h[1-6])\s*/?>")
_ANYTAG_RE = re.compile(r"(?s)<[^>]+>")


def _html_to_text(s):
    """Best-effort HTML→plain text for readable display (output is rendered via
    textContent on the client, so this is for legibility, not safety)."""
    s = _TAG_BLOCK_RE.sub(" ", s)
    s = _BR_RE.sub("\n", s)
    s = _ANYTAG_RE.sub("", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[\u200b\u200c\u200d\u034f\ufeff\u00ad]", "", s)  # strip email preheader spacers
    out, blank = [], False
    for line in s.replace("\r", "").split("\n"):
        line = line.strip()
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")  # collapse runs of blank lines to one
            blank = True
    return "\n".join(out).strip()


def _extract_body(msg):
    plain = html_body = None
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition") or "").lower():
                continue
            ct = part.get_content_type()
            if ct == "text/plain" and plain is None:
                plain = _part_text(part)
            elif ct == "text/html" and html_body is None:
                html_body = _part_text(part)
    elif msg.get_content_type() == "text/html":
        html_body = _part_text(msg)
    else:
        plain = _part_text(msg)
    if plain and plain.strip():
        return plain[:20000]
    if html_body:
        return _html_to_text(html_body)[:20000]
    return ""


def _fetch_message(box_key, uid):
    """Return {subject,from,to,date,body} for one message, or None."""
    m = None
    try:
        m, addr = _connect(box_key)
        m.select("INBOX", readonly=True)
        typ, data = m.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        msg = email.message_from_bytes(data[0][1])
        return {
            "subject": _dec(msg.get("Subject")) or "(no subject)",
            "from": _dec(msg.get("From")),
            "to": _dec(msg.get("To")),
            "date": _iso(msg.get("Date")),
            "body": _extract_body(msg),
        }
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


def _original_message_id(box_key, uid):
    """Message-ID of the message being replied to (for In-Reply-To/References)."""
    m = None
    try:
        m, _ = _connect(box_key)
        m.select("INBOX", readonly=True)
        typ, data = m.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        if typ == "OK" and data and isinstance(data[0], tuple):
            hdr = email.message_from_bytes(data[0][1] or b"")
            return hdr.get("Message-ID")
    except Exception as e:
        logger.warning("could not read Message-ID for %s/%s: %s", box_key, uid, e)
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass
    return None


def _append_sent(box_key, raw_bytes):
    """Best-effort: copy a sent message into the mailbox's Sent folder so it
    shows up in webmail. Never raises — a failed append must not fail the send."""
    m = None
    try:
        m, _ = _connect(box_key)
        stamp = imaplib.Time2Internaldate(time.time())
        for folder in ("INBOX.Sent", "Sent", "Sent Items", "INBOX.Sent Items"):
            try:
                typ, _ = m.append(folder, "\\Seen", stamp, raw_bytes)
                if typ == "OK":
                    return
            except Exception:
                continue
    except Exception as e:
        logger.warning("append-to-Sent failed for %s: %s", box_key, e)
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Auth — HTTP Basic, blueprint-wide, fail-closed
# ---------------------------------------------------------------------------

def _admin_mail_credentials():
    """Read the shared credential pair from the environment on EVERY call
    (not cached at import time) so a rotated `.env` + container restart takes
    effect without a rebuild."""
    return os.getenv("WTF_ADMIN_MAIL_USER", ""), os.getenv("WTF_ADMIN_MAIL_PASSWORD", "")


def _auth_error(status, message):
    resp = Response(json.dumps({"error": message}), status=status, mimetype="application/json")
    if status == 401:
        resp.headers["WWW-Authenticate"] = 'Basic realm="WTF Admin Mail"'
    return resp


@admin_mail_bp.before_request
def _require_admin_mail_auth():
    """Gate EVERY route in this blueprint — the dashboard page as well as
    every API endpoint — behind HTTP Basic Auth. FAILS CLOSED: an unset
    credential pair refuses with 503 for every request, never allow-if-unset.
    Uses `secrets.compare_digest` (not `==`) for the password comparison to
    avoid a timing side-channel."""
    want_user, want_pw = _admin_mail_credentials()
    if not want_user or not want_pw:
        return _auth_error(
            503,
            "admin mail dashboard is not configured "
            "(set WTF_ADMIN_MAIL_USER and WTF_ADMIN_MAIL_PASSWORD)",
        )
    auth = request.authorization
    got_user = (auth.username if auth else None) or ""
    got_pw = (auth.password if auth else None) or ""
    user_ok = secrets.compare_digest(got_user, want_user)
    pw_ok = secrets.compare_digest(got_pw, want_pw)
    if not (auth and user_ok and pw_ok):
        return _auth_error(401, "unauthorized")
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@admin_mail_bp.get("/admin/mail")
def admin_mail_dashboard():
    """The dashboard shell. All data + actions come from the /api/* routes
    below, gated by the same before_request as this page."""
    return render_template("admin_mail.html", boxes=list(_BOXES.keys()))


@admin_mail_bp.get("/admin/mail/api/status")
def admin_mail_status():
    """Per-mailbox health + unseen/total counts. Best-effort per box — one
    box's IMAP failure must not blank out the rest of the status list."""
    out = []
    for key, (addr, _envk) in _BOXES.items():
        row = {
            "key": key,
            "address": addr,
            "configured": bool(_password(key)),
            "unseen": None,
            "total": None,
            "error": None,
        }
        if not row["configured"]:
            row["error"] = "no password"
            out.append(row)
            continue
        m = None
        try:
            m, _addr = _connect(key)
            typ, data = m.select("INBOX", readonly=True)
            row["total"] = int(data[0]) if typ == "OK" and data and data[0] else 0
            typ, un = m.uid("SEARCH", None, "UNSEEN")
            row["unseen"] = len(un[0].split()) if typ == "OK" and un and un[0] else 0
        except Exception as e:
            row["error"] = type(e).__name__
            logger.warning("admin_mail_status %s failed: %s", key, e)
        finally:
            if m is not None:
                try:
                    m.logout()
                except Exception:
                    pass
        out.append(row)
    return jsonify({"mailboxes": out})


@admin_mail_bp.get("/admin/mail/api/inbox")
def admin_mail_inbox():
    box = (request.args.get("box") or "").strip().lower()
    if box not in _BOXES:
        return jsonify({"error": "unknown mailbox"}), 400
    try:
        limit = max(1, min(int(request.args.get("limit") or 25), 50))
    except (TypeError, ValueError):
        limit = 25
    m = None
    try:
        m, addr = _connect(box)
        m.select("INBOX", readonly=True)
        msgs = []
        for uid in _uid_list(m, limit):
            s = _header_summary(m, uid)
            if s:
                msgs.append(s)
        return jsonify({"box": box, "address": addr, "messages": msgs, "count": len(msgs)})
    except Exception as e:
        logger.error("admin_mail_inbox %s failed: %s", box, e)
        return jsonify({"error": "could not load inbox", "detail": type(e).__name__}), 502
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


@admin_mail_bp.get("/admin/mail/api/message")
def admin_mail_message():
    box = (request.args.get("box") or "").strip().lower()
    uid = (request.args.get("uid") or "").strip()
    if box not in _BOXES:
        return jsonify({"error": "unknown mailbox"}), 400
    if not uid.isdigit():
        return jsonify({"error": "invalid uid"}), 400
    try:
        msg = _fetch_message(box, uid)
    except Exception as e:
        logger.error("admin_mail_message %s/%s failed: %s", box, uid, e)
        return jsonify({"error": "could not load message", "detail": type(e).__name__}), 502
    if not msg:
        return jsonify({"error": "message not found"}), 404
    addr = _BOXES[box][0]
    return jsonify({"box": box, "address": addr, "uid": uid, **msg})


@admin_mail_bp.post("/admin/mail/api/send")
def admin_mail_send():
    """Send an admin-composed reply FROM a what-the-fact.com mailbox via
    Hostinger SMTP. Outbound action — gated on an explicit human Send click
    in the UI; nothing here auto-sends anything."""
    j = request.get_json(silent=True) or {}
    box = (j.get("box") or "").strip().lower()
    to = (j.get("to") or "").strip()
    subject = (j.get("subject") or "").strip()
    text = (j.get("body") or "").strip()
    uid = (j.get("uid") or "").strip()  # optional — original message, for threading
    if box not in _BOXES:
        return jsonify({"error": "unknown mailbox"}), 400
    if "@" not in to or " " in to or to.count("@") != 1:
        return jsonify({"error": "invalid recipient"}), 400
    if not subject or not text:
        return jsonify({"error": "subject and body are required"}), 400
    addr = _BOXES[box][0]
    pw = _password(box)
    if not pw:
        return jsonify({"error": "mailbox not configured"}), 400
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if uid.isdigit():
        mid = _original_message_id(box, uid)
        if mid:
            msg["In-Reply-To"] = mid
            msg["References"] = mid
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=ctx, timeout=_TIMEOUT) as s:
            s.login(addr, pw)
            s.send_message(msg)
    except Exception as e:
        logger.error("admin_mail_send %s -> %s failed: %s", box, to, e)
        return jsonify({"error": "send failed", "detail": type(e).__name__}), 502
    _append_sent(box, msg.as_bytes())
    logger.info("WTF admin mail sent from %s to %s (subject=%.80s)", addr, to, subject)
    return jsonify({"sent": True, "from": addr, "to": to})
