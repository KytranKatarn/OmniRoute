"""mailbox_extract_service.py — Mailbox Story Extractor extraction engine.

Uses pffexport (libpff / pff-tools) — NOT readpst (libpst). libpff is dramatically more
thorough: it recovers emails, attachments, AND messages embedded inside other items
(e.g. forwarded email threads attached to calendar invites) that readpst silently drops.
(Proven on a real 495MB PST: readpst exported 1,341 bare calendar items; pffexport produced
4,175 items including 96 real emails readpst never surfaced.)

pffexport writes one DIRECTORY per item under <out>/pff.export/<folder path>/<ItemNNNNN>/, each
containing OutlookHeaders.txt, Recipients.txt, InternetHeaders.txt, Message.txt (+ Attachments/).
Email items are named "MessageNNNNN"; we parse those into mailbox_emails rows.

PRIVACY: everything is local — pffexport is a local binary, files stay on local disk, no network.
Enrichment (Phase 2) runs on local-only fleet LLMs.

Usage (from the upload route's background job):
    n = extract_pst(import_id, '/mnt/data2/mailbox_story/<id>/source.pst',
                    '/mnt/data2/mailbox_story/<id>/eml')
"""

import logging
import os
import re
import subprocess
from datetime import timezone
from email.header import decode_header, make_header

from database import get_db_cursor


def _dh(s):
    """Decode RFC2047 MIME encoded-words (=?utf-8?B?...?=) to readable text. Best-effort."""
    if not s or "=?" not in s:
        return s
    try:
        return str(make_header(decode_header(s))) or s
    except Exception:
        return s


logger = logging.getLogger(__name__)

_BODY_CAP = 100_000  # chars of plain-text body stored per email
_PFF_TIMEOUT = 3600  # a big PST can take a while; bounded
# "Oct 05, 2022 18:34:59.000000000 UTC" -> grab "Oct 05, 2022 18:34:59"
_PFF_DATE_RE = re.compile(r"([A-Z][a-z]{2} \d{2}, \d{4} \d{2}:\d{2}:\d{2})")


def _mark_error(import_id, message):
    """Flip an import to 'error' with a bounded message. Never raises (best-effort)."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE mailbox_imports SET status='error', error=%s WHERE id=%s",
                ((message or "extraction failed")[:1000], import_id),
            )
    except Exception:
        logger.exception("could not mark import %s as error", import_id)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def _kv(text):
    """Parse pffexport's 'Key:<tabs>Value' lines into a dict (first occurrence wins)."""
    out = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if k and v and k not in out:
                out[k] = v
    return out


def _parse_date(s):
    if not s:
        return None
    m = _PFF_DATE_RE.search(s)
    if not m:
        return None
    try:
        from datetime import datetime

        return datetime.strptime(m.group(1), "%b %d, %Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_recipients(path):
    """Recipients.txt -> {'to': '...', 'cc': '...'} of display names (or SMTP if present)."""
    to, cc = [], []
    name = addr = rtype = None
    for line in (_read(path) + "\n").splitlines() + [""]:
        s = line.strip()
        if not s:  # blank line ends a recipient block
            if name or addr:
                who = name or addr
                if addr and "@" in addr:
                    who = f"{name} <{addr}>" if name else addr
                (cc if (rtype or "").lower() == "cc" else to).append(who)
            name = addr = rtype = None
            continue
        k, _, v = s.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "display name":
            name = v
        elif k == "email address":
            addr = v
        elif k == "recipient type":
            rtype = v
    return {"to": "; ".join(to) or None, "cc": "; ".join(cc) or None}


def _internet_headers(path):
    """InternetHeaders.txt (raw RFC822) -> dict of From/To/Cc/Message-ID/Subject when present."""
    out = {}
    cur_key = None
    for line in _read(path).splitlines():
        if line[:1] in (" ", "\t") and cur_key:  # header continuation
            out[cur_key] += " " + line.strip()
        elif ":" in line:
            k, _, v = line.partition(":")
            cur_key = k.strip().lower()
            out[cur_key] = v.strip()
        elif not line.strip():
            break  # end of headers
    return out


def _parse_pff_message(item_dir, folder):
    """One pffexport 'MessageNNNNN' dir -> mailbox_emails column dict. Never raises."""
    oh = _kv(_read(os.path.join(item_dir, "OutlookHeaders.txt")))
    ih = _internet_headers(os.path.join(item_dir, "InternetHeaders.txt"))
    rcpt = _parse_recipients(os.path.join(item_dir, "Recipients.txt"))

    # Prefer real SMTP headers (forwarded mail), fall back to Outlook/Exchange fields.
    sender = oh.get("Sender email address", "")
    sender_smtp = sender if "@" in sender else None
    sname = oh.get("Sender name")
    from_addr = ih.get("from") or (f"{sname} <{sender_smtp}>" if (sname and sender_smtp) else (sname or sender_smtp))

    subject = ih.get("subject") or oh.get("Subject") or oh.get("Conversation topic")
    sent = _parse_date(oh.get("Client submit time") or oh.get("Delivery time"))
    body = _read(os.path.join(item_dir, "Message.txt"))
    has_attach = os.path.isdir(os.path.join(item_dir, "Attachments"))

    return {
        "folder": folder,
        "message_id": (ih.get("message-id") or None),
        "in_reply_to": (ih.get("in-reply-to") or None),
        "from_addr": (_dh(from_addr) or None),
        "to_addrs": _dh(ih.get("to") or rcpt["to"]),
        "cc_addrs": _dh(ih.get("cc") or rcpt["cc"]),
        "sent_at": sent,
        "subject": (_dh(subject) or None),
        "body_text": (body or "")[:_BODY_CAP],
        "has_attachments": has_attach,
    }


def _clean_folder(rel):
    """Tidy a pffexport relative path into a folder label for display."""
    rel = rel.replace("Top of Outlook data file/", "").replace("Top of Outlook data file", "")
    rel = rel.strip("/.")
    # Embedded messages live under .../Attachments/AttachmentNNNN — flag them.
    if "/Attachments/" in ("/" + rel):
        base = rel.split("/Attachments/")[0]
        return (base + " (attached)") if base else "(attached)"
    return rel or "(root)"


def extract_pst(import_id, pst_path, out_dir):
    """Run pffexport on `pst_path`, parse every email item into mailbox_emails, update the row.
    Returns the number of emails ingested. Marks the import 'error' on any failure."""
    os.makedirs(out_dir, exist_ok=True)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("UPDATE mailbox_imports SET status='extracting' WHERE id=%s", (import_id,))

    target = os.path.join(out_dir, "pff")  # pffexport appends '.export'
    export_root = target + ".export"
    # -m all = items + recovered/deleted; -q quiet; -t target. Local binary, no network.
    try:
        proc = subprocess.run(
            ["pffexport", "-m", "all", "-q", "-t", target, pst_path],
            capture_output=True,
            text=True,
            timeout=_PFF_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("pffexport timed out after %ss for import %s", _PFF_TIMEOUT, import_id)
        _mark_error(import_id, f"pffexport timed out after {_PFF_TIMEOUT}s")
        return 0
    except Exception as exc:  # FileNotFoundError (pffexport missing), OSError, etc.
        logger.exception("pffexport could not run for import %s", import_id)
        _mark_error(import_id, f"pffexport failed to start: {exc}")
        return 0
    # pffexport returns non-zero on partial/odd items but still exports — only fail if no output.
    if not os.path.isdir(export_root):
        logger.error("pffexport produced no output (%s): %s", proc.returncode, (proc.stderr or "")[:500])
        _mark_error(import_id, (proc.stderr or "pffexport produced no output")[:1000])
        return 0

    count = 0
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            for root, _dirs, files in os.walk(export_root):
                # An item dir is one that directly holds OutlookHeaders.txt; emails are 'Message*'.
                if "OutlookHeaders.txt" not in files:
                    continue
                if not os.path.basename(root).startswith("Message"):
                    continue  # skip Appointment/Contact/Task items — emails only
                folder = _clean_folder(os.path.relpath(os.path.dirname(root), export_root))
                try:
                    rec = _parse_pff_message(root, folder)
                except Exception as exc:
                    logger.warning("pff parse failed for %s: %s", root, exc)
                    continue
                if not (rec["subject"] or rec["from_addr"] or rec["body_text"]):
                    continue  # empty/degenerate item
                rec["i"] = import_id
                cur.execute(
                    """
                    INSERT INTO mailbox_emails
                        (import_id, folder, message_id, in_reply_to, from_addr, to_addrs,
                         cc_addrs, sent_at, subject, body_text, has_attachments)
                    VALUES (%(i)s, %(folder)s, %(message_id)s, %(in_reply_to)s, %(from_addr)s,
                            %(to_addrs)s, %(cc_addrs)s, %(sent_at)s, %(subject)s, %(body_text)s,
                            %(has_attachments)s)
                """,
                    rec,
                )
                count += 1
            cur.execute(
                "UPDATE mailbox_imports SET status='extracted', email_count=%s WHERE id=%s",
                (count, import_id),
            )
    except Exception as exc:
        logger.exception("mailbox import %s failed during email ingest", import_id)
        _mark_error(import_id, f"ingest failed after {count} emails: {exc}")
        return 0
    logger.info("mailbox import %s: extracted %d emails (pffexport)", import_id, count)
    return count
