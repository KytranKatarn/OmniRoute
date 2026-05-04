"""Account Center — alternate email linking service (Project #311).

Source-of-truth: ``users.alternate_emails text[]`` holds VERIFIED alternates.
This service stages verifications in ``alternate_email_verifications``
(SHA-256-hashed tokens, never raw) and promotes to the array on click.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────
TOKEN_BYTES = 32
VERIFICATION_TOKEN_TTL_HOURS = 24
MAX_ALTERNATES_PER_USER = 5

VERIFY_BASE_URL = os.getenv("ARCHIE_PUBLIC_BASE_URL", "https://platform.kytranempowerment.com")


def generate_token() -> str:
    """32 bytes of URL-safe randomness → ~43-char base64 string."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Raw tokens are NEVER stored — only this hash."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── Email regex ─────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _send_verification_email(to_address: str, username: str, token: str) -> None:
    """Send the verification email via Stalwart SMTP.

    Failure must NOT crash request_alternate_email — logs and returns silently.
    """
    # Token is base64url (secrets.token_urlsafe) — no characters that need
    # url-encoding when concatenated as a query-string value.
    verify_url = f"{VERIFY_BASE_URL}/account/verify-alternate?token={token}"
    subject = "Verify your alternate email — A.R.C.H.I.E."
    body = (
        f"Hi {username or ''},\n\n"
        f"You requested to link {to_address} to your A.R.C.H.I.E. account.\n\n"
        f"Click within 24 hours to confirm ownership:\n"
        f"{verify_url}\n\n"
        f"If you didn't request this, ignore this email — no action will be taken.\n\n"
        f"— A.R.C.H.I.E."
    )

    smtp_host = os.getenv("SMTP_HOST", "192.168.1.200")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        smtp_port = 587  # malformed env value must not crash the caller
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "archie@kytranempowerment.com")

    if not smtp_user or not smtp_password:
        logger.error(
            "[account_link] SMTP credentials missing; cannot send verification to %s",
            to_address,
        )
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_address

    try:
        # Stalwart self-signed cert on internal Docker network — intentional;
        # matches compose_routes.py and sync_jobs.py SMTP pattern. If Stalwart
        # ever moves off-hub, tighten to CERT_REQUIRED.
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl_ctx)
            smtp.login(smtp_user, smtp_password)
            smtp.sendmail(smtp_from, [to_address], msg.as_string())
        logger.info(
            "[account_link] verification email sent to %s (token=%s...)",
            to_address,
            token[:6],
        )
    except Exception:  # noqa: BLE001 — never crash caller
        logger.exception(
            "[account_link] verification email send failed for %s",
            to_address,
        )


def request_alternate_email(user_id: int, email: str) -> Dict[str, Any]:
    """Stage a verification for `email` against `user_id`.

    Returns ``{"success": True, "pending_email": str, "expires_at": iso}``
    on success, ``{"success": False, "error": str}`` on validation failure.
    """
    email_lower = (email or "").strip().lower()

    if not _EMAIL_RE.match(email_lower):
        return {"success": False, "error": "Invalid email format"}

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, username, email, alternate_emails FROM users WHERE id = %s",
            (user_id,),
        )
        user = cur.fetchone()
        if not user:
            return {"success": False, "error": "User not found"}

        primary = (user.get("email") or "").strip().lower()
        if email_lower == primary:
            return {"success": False, "error": "Email is your primary"}

        existing = [a.lower() for a in (user.get("alternate_emails") or [])]
        if email_lower in existing:
            return {"success": False, "error": "Email is already verified"}

        if len(existing) >= MAX_ALTERNATES_PER_USER:
            return {
                "success": False,
                "error": f"Max {MAX_ALTERNATES_PER_USER} alternates per user",
            }

        # Cancel any prior pending row for the same (user, email) — idempotent re-issue.
        cur.execute(
            """UPDATE alternate_email_verifications
                  SET used_at = NOW()
                WHERE user_id = %s AND lower(alternate_email) = %s
                  AND used_at IS NULL""",
            (user_id, email_lower),
        )

        token = generate_token()
        expires = datetime.utcnow() + timedelta(hours=VERIFICATION_TOKEN_TTL_HOURS)
        cur.execute(
            """INSERT INTO alternate_email_verifications
                   (user_id, alternate_email, token_hash, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (user_id, email_lower, hash_token(token), expires),
        )

    _send_verification_email(email_lower, user.get("username") or "", token)

    return {
        "success": True,
        "pending_email": email_lower,
        "expires_at": expires.isoformat(),
    }


def verify_alternate_email(token: str) -> Dict[str, Any]:
    """Confirm a verification token. Promotes the email to users.alternate_emails.

    Returns ``{"success": True, "user_id": int, "alternate_email": str}``
    on success, ``{"success": False, "error": str}`` on miss/expiry/reuse.
    """
    if not token:
        return {"success": False, "error": "Invalid token"}

    th = hash_token(token)

    # commit=True on guard-return paths commits an empty no-op transaction —
    # cheap and idiomatic in this codebase. Restructuring to a 2-cursor
    # pattern would buy negligible perf at the cost of a read-then-write race.
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """SELECT id, user_id, alternate_email, expires_at, used_at
                 FROM alternate_email_verifications
                WHERE token_hash = %s""",
            (th,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Invalid or unknown token"}

        if row["used_at"] is not None:
            return {"success": False, "error": "Token already used"}

        if row["expires_at"] < datetime.utcnow():
            return {"success": False, "error": "Token expired"}

        # Promote: append to array (lower-cased dedup) + mark used.
        # Defensive .lower() — request_alternate_email already stores lowercased
        # but we don't want correctness to depend on that upstream invariant.
        cur.execute(
            """UPDATE users
                  SET alternate_emails = (
                      SELECT ARRAY(
                          SELECT DISTINCT lower(unnest(
                              COALESCE(alternate_emails, ARRAY[]::text[]) || ARRAY[%s]
                          ))
                      )
                  )
                WHERE id = %s""",
            (row["alternate_email"].lower(), row["user_id"]),
        )
        cur.execute(
            "UPDATE alternate_email_verifications SET used_at = NOW() WHERE id = %s",
            (row["id"],),
        )

    return {
        "success": True,
        "user_id": row["user_id"],
        "alternate_email": row["alternate_email"],
    }


def find_user_by_any_email(email: str, *, active_only: bool = False) -> Optional[dict]:
    """Look up user by primary email or any verified alternate. Case-insensitive.

    Mirrors the semantics of the existing ``idx_users_email_lower`` index for
    primary, and uses ``ANY(alternate_emails)`` for the alternates path.
    Returns the full user row dict (RealDictRow) or None.
    """
    if not email:
        return None
    email_lower = email.strip().lower()
    if not email_lower:
        return None
    active_clause = " AND is_active = TRUE" if active_only else ""

    with get_db_cursor() as (_conn, cur):
        cur.execute(
            f"""SELECT * FROM users
                  WHERE (lower(email) = %s
                         OR %s = ANY(alternate_emails))
                  {active_clause}
                  LIMIT 1""",
            (email_lower, email_lower),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def remove_alternate_email(user_id: int, email: str) -> Dict[str, Any]:
    """Remove email from user's alternate_emails array and cancel pending rows.

    Returns ``{"success": True, "removed": bool}``.
    """
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return {"success": False, "error": "email is required"}

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE users
                  SET alternate_emails = array_remove(alternate_emails, %s)
                WHERE id = %s
                  AND %s = ANY(alternate_emails)
                RETURNING id""",
            (email_lower, user_id, email_lower),
        )
        removed = cur.fetchone() is not None

        cur.execute(
            """UPDATE alternate_email_verifications
                  SET used_at = NOW()
                WHERE user_id = %s
                  AND lower(alternate_email) = %s
                  AND used_at IS NULL""",
            (user_id, email_lower),
        )

    return {"success": True, "removed": removed}
