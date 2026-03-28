"""Parse inbound emails into structured dicts for help desk intake."""

import re


# Matches: HD-0042, HD-123, etc.
_TICKET_RE = re.compile(r"\b(HD-\d+)\b", re.IGNORECASE)

# Matches: Re: / Fwd: / FW: prefixes (case-insensitive, repeating)
_REPLY_PREFIX_RE = re.compile(r"^(?:(?:re|fwd?)\s*:\s*)+", re.IGNORECASE)

# Matches: "Display Name <email@example.com>"
_NAME_EMAIL_RE = re.compile(r"^\s*(.+?)\s*<([^>]+)>\s*$")


def parse_inbound_email(raw: dict) -> dict:
    """Parse a raw inbound email dict into a structured help desk payload.

    Args:
        raw: dict with keys: from, subject, body_plain, body_html (optional)

    Returns:
        dict with keys: sender_email, sender_name, subject, body,
                        is_reply, ticket_number
    """
    # --- Parse sender ---
    from_field = (raw.get("from") or "").strip()
    name_email_match = _NAME_EMAIL_RE.match(from_field)
    if name_email_match:
        sender_name = name_email_match.group(1).strip()
        sender_email = name_email_match.group(2).strip()
    else:
        sender_name = ""
        sender_email = from_field

    # --- Parse subject / detect reply ---
    raw_subject = (raw.get("subject") or "").strip()

    ticket_match = _TICKET_RE.search(raw_subject)
    is_reply = ticket_match is not None
    ticket_number = ticket_match.group(1).upper() if ticket_match else None

    # Strip Re:/Fwd: prefixes
    clean_subject = _REPLY_PREFIX_RE.sub("", raw_subject).strip()

    # Strip ticket number prefix like "HD-0042: " or "HD-0042 - "
    if ticket_number:
        clean_subject = re.sub(
            rf"\b{re.escape(ticket_number)}\s*[:\-]\s*", "", clean_subject, flags=re.IGNORECASE
        ).strip()

    # --- Body ---
    body = raw.get("body_plain") or raw.get("body_html") or ""

    return {
        "sender_email": sender_email,
        "sender_name": sender_name,
        "subject": clean_subject,
        "body": body,
        "is_reply": is_reply,
        "ticket_number": ticket_number,
    }
