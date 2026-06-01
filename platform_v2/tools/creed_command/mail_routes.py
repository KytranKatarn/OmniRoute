"""C.R.E.E.D. Command — mail reader (Phase 1, #3608/#3609/#3610).

Reads the five creed-ai.org Hostinger mailboxes over IMAP so E.T.H.O.S. can
triage them from the Command Center Inbox tab.

Self-contained on purpose: it connects DIRECTLY to imap.hostinger.com:993 using
per-box CREED_MAIL_*_PASSWORD env secrets. It deliberately does NOT route through
the platform Email Manager — that sync (tools/email_manager/idle_worker.py) is
hardcoded to the internal Stalwart server and email_mailboxes has no per-row host,
so it cannot reach an external Hostinger box. Keeping CREED mail here means zero
risk to the 70 Stalwart mailboxes.

Read-only: select(..., readonly=True), BODY.PEEK (never sets \\Seen), no delete/move.
Passwords come from env only — never stored in the DB, never logged. Admin-only.
"""

import email
import html as htmllib
import imaplib
import logging
import os
import re
import threading
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from flask import current_app, jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

_IMAP_HOST = os.getenv("CREED_MAIL_IMAP_HOST", "imap.hostinger.com")
_IMAP_PORT = int(os.getenv("CREED_MAIL_IMAP_PORT") or 993)
_TIMEOUT = 15  # seconds — fail fast rather than wedge the web thread

# box key (what the client sends as ?box=) -> (address, env password key)
_BOXES = {
    "contact": ("contact@creed-ai.org", "CREED_MAIL_CONTACT_PASSWORD"),
    "grants": ("grants@creed-ai.org", "CREED_MAIL_GRANTS_PASSWORD"),
    "research": ("research@creed-ai.org", "CREED_MAIL_RESEARCH_PASSWORD"),
    "press": ("press@creed-ai.org", "CREED_MAIL_PRESS_PASSWORD"),
    "admin": ("admin@creed-ai.org", "CREED_MAIL_ADMIN_PASSWORD"),
}


def _password(box_key):
    """Per-box password, falling back to a single shared password if set."""
    _, envk = _BOXES[box_key]
    return os.getenv(envk) or os.getenv("CREED_MAIL_SHARED_PASSWORD") or ""


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
_BLANKS_RE = re.compile(r"\n[ \t]*\n[ \t]*\n+")


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


def _triage_prompt(addr, msg):
    return (
        "You are E.T.H.O.S., the AI ethics analyst and inbox manager for the "
        "C.R.E.E.D. Institute (a Canadian nonprofit advancing preventive AI ethics, "
        "governance, and non-exploitative AI). Triage this inbound email to "
        + addr
        + ". Reply in exactly these six short labelled lines, nothing else:\n"
        "Category: [inquiry|grant|press|research|partnership|spam|admin|legal|other]\n"
        "Urgency: [low|medium|high]\n"
        "Sentiment: [positive|neutral|negative]\n"
        "Summary: <one sentence>\n"
        "Action: <the single next step a human should take>\n"
        "Owner: <which C.R.E.E.D. function should handle it>\n\n"
        "Email:\nFrom: " + msg["from"] + "\nSubject: " + msg["subject"] + "\n\n" + (msg["body"] or "")[:3000]
    )


def _draft_prompt(addr, msg):
    return (
        "You are E.T.H.O.S., the contact for the C.R.E.E.D. Institute (a Canadian "
        "nonprofit advancing preventive AI ethics, governance, and non-exploitative "
        "AI). Draft a professional, concise reply (about 150 words) to the email "
        "below, for a human to review before sending. Warm but precise. Do NOT invent "
        "facts, figures, funding, partnerships, deadlines, or commitments. If the "
        "request needs information you do not have, say a team member will follow up. "
        "Sign off as 'E.T.H.O.S. - C.R.E.E.D. Institute'. Write ONLY the reply body.\n\n"
        "Email:\nFrom: " + msg["from"] + "\nSubject: " + msg["subject"] + "\n\n" + (msg["body"] or "")[:3000]
    )


def _run_mail_ai_bg(app_obj, box, uid, kind, addr, msg):
    """Background: E.T.H.O.S. triages or drafts a reply, stores result in creed_mail_ai.

    Runs OFF the web request (the 7B dispatch can exceed 60s). Routes to E.T.H.O.S.
    on the GPU cluster (Starship-246/245) for speed, falling back automatically.
    """
    with app_obj.app_context():
        result, status = "", "error"
        try:
            from tools.department_hq.services.department_dispatcher import dispatch

            prompt = _triage_prompt(addr, msg) if kind == "triage" else _draft_prompt(addr, msg)
            res = dispatch(
                capability="policy_assessment",
                prompt=prompt,
                prefer_agent="E.T.H.O.S.",
                source_product="archie_platform",
                preferred_node=["Starship-246", "Starship-245"],
            )
            if res is not None and getattr(res, "success", False):
                result = (getattr(res, "response", "") or "").strip()
                status = "done" if result else "error"
        except Exception as e:
            logger.error("mail AI %s %s/%s failed: %s", kind, box, uid, e)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE creed_mail_ai SET result=%s, status=%s, updated_at=now() "
                    "WHERE box=%s AND uid=%s AND kind=%s",
                    (result, status, box, uid, kind),
                )
        except Exception as e:
            logger.error("mail AI store %s %s/%s failed: %s", kind, box, uid, e)


def register_mail_routes(bp, admin_required):
    @bp.route("/api/mail/status", methods=["GET"])
    @login_required
    @admin_required
    def mail_status():
        """Per-mailbox health + unseen/total counts. Best-effort per box."""
        out = []
        for key, (addr, envk) in _BOXES.items():
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
                m, _ = _connect(key)
                typ, data = m.select("INBOX", readonly=True)
                row["total"] = int(data[0]) if typ == "OK" and data and data[0] else 0
                typ, un = m.uid("SEARCH", None, "UNSEEN")
                row["unseen"] = len(un[0].split()) if typ == "OK" and un and un[0] else 0
            except Exception as e:
                row["error"] = type(e).__name__
                logger.warning("mail_status %s failed: %s", key, e)
            finally:
                if m is not None:
                    try:
                        m.logout()
                    except Exception:
                        pass
            out.append(row)
        return jsonify({"mailboxes": out})

    @bp.route("/api/mail/inbox", methods=["GET"])
    @login_required
    @admin_required
    def mail_inbox():
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
            logger.error("mail_inbox %s failed: %s", box, e)
            return jsonify({"error": "could not load inbox", "detail": type(e).__name__}), 502
        finally:
            if m is not None:
                try:
                    m.logout()
                except Exception:
                    pass

    @bp.route("/api/mail/message", methods=["GET"])
    @login_required
    @admin_required
    def mail_message():
        box = (request.args.get("box") or "").strip().lower()
        uid = (request.args.get("uid") or "").strip()
        if box not in _BOXES:
            return jsonify({"error": "unknown mailbox"}), 400
        if not uid.isdigit():
            return jsonify({"error": "invalid uid"}), 400
        m = None
        try:
            m, addr = _connect(box)
            m.select("INBOX", readonly=True)
            typ, data = m.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                return jsonify({"error": "message not found"}), 404
            msg = email.message_from_bytes(data[0][1])
            return jsonify(
                {
                    "box": box,
                    "address": addr,
                    "uid": uid,
                    "subject": _dec(msg.get("Subject")) or "(no subject)",
                    "from": _dec(msg.get("From")),
                    "to": _dec(msg.get("To")),
                    "date": _iso(msg.get("Date")),
                    "body": _extract_body(msg),
                }
            )
        except Exception as e:
            logger.error("mail_message %s/%s failed: %s", box, uid, e)
            return jsonify({"error": "could not load message", "detail": type(e).__name__}), 502
        finally:
            if m is not None:
                try:
                    m.logout()
                except Exception:
                    pass

    def _kickoff_ai(kind):
        body = request.get_json(silent=True) or {}
        box = (body.get("box") or "").strip().lower()
        uid = (body.get("uid") or "").strip()
        if box not in _BOXES:
            return jsonify({"error": "unknown mailbox"}), 400
        if not uid.isdigit():
            return jsonify({"error": "invalid uid"}), 400
        msg = _fetch_message(box, uid)
        if not msg:
            return jsonify({"error": "message not found"}), 404
        addr = _BOXES[box][0]
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO creed_mail_ai (box, uid, kind, status) "
                    "VALUES (%s, %s, %s, 'pending') "
                    "ON CONFLICT (box, uid, kind) DO UPDATE SET "
                    "status='pending', result=NULL, updated_at=now()",
                    (box, uid, kind),
                )
        except Exception as e:
            logger.error("mail AI kickoff insert failed: %s", e)
            return jsonify({"error": "could not queue"}), 500
        app_obj = current_app._get_current_object()
        threading.Thread(
            target=_run_mail_ai_bg,
            args=(app_obj, box, uid, kind, addr, msg),
            daemon=True,
        ).start()
        return jsonify({"status": "pending", "box": box, "uid": uid, "kind": kind}), 202

    @bp.route("/api/mail/triage", methods=["POST"])
    @login_required
    @admin_required
    def mail_triage():
        """Kick off E.T.H.O.S. triage of a message (async). Poll GET /api/mail/ai."""
        return _kickoff_ai("triage")

    @bp.route("/api/mail/draft", methods=["POST"])
    @login_required
    @admin_required
    def mail_draft():
        """Kick off an E.T.H.O.S. draft reply (async). Poll GET /api/mail/ai."""
        return _kickoff_ai("draft")

    @bp.route("/api/mail/ai", methods=["GET"])
    @login_required
    @admin_required
    def mail_ai_get():
        """Current triage + draft state for one message."""
        box = (request.args.get("box") or "").strip().lower()
        uid = (request.args.get("uid") or "").strip()
        if box not in _BOXES or not uid.isdigit():
            return jsonify({"error": "bad params"}), 400
        out = {"triage": None, "draft": None}
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT kind, status, result, updated_at FROM creed_mail_ai " "WHERE box=%s AND uid=%s",
                    (box, uid),
                )
                for r in cur.fetchall() or []:
                    out[r["kind"]] = {
                        "status": r["status"],
                        "result": r["result"],
                        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    }
        except Exception as e:
            logger.error("mail_ai_get failed: %s", e)
            return jsonify({"error": "could not load"}), 500
        return jsonify(out)
