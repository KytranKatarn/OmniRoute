"""Auth service — shared queries for login, logout, signup, session management.

Owner: app.py core auth routes (login, logout, signup, verify_2fa)
Tables: users, failed_logins, audit_log, user_activity_log, active_sessions

Import:
    from services.auth_service import get_user_by_username, record_failed_login
"""

import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import threading

from psycopg2.extras import RealDictCursor
from database import get_db_connection

# In-memory IP rate limiter (resets on restart — intentional)
_ip_attempts = defaultdict(list)
_ip_lock = threading.Lock()

# Security constants
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
IP_RATE_LIMIT = 10  # max attempts per IP per window
IP_RATE_WINDOW = 300  # 5 minutes in seconds

logger = logging.getLogger(__name__)


def get_user_by_username(username):
    """Lookup user by username OR email. Accepts either — Project Alpha 2026-05-06."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT * FROM users WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)",
                (username, username),
            )
            return cur.fetchone()
        finally:
            cur.close()


def get_active_user_by_id(user_id):
    """Lookup active user by ID. Returns full user row dict or None."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT * FROM users WHERE id = %s AND is_active = TRUE",
                (user_id,),
            )
            return cur.fetchone()
        finally:
            cur.close()


def check_username_exists(username):
    """Returns True if username is taken."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            return cur.fetchone() is not None
        finally:
            cur.close()


def check_email_exists(email):
    """Returns True if email is taken."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            return cur.fetchone() is not None
        finally:
            cur.close()


def create_inactive_user(username, email, password_hash):
    """Create a new user with is_active=False (pending admin approval). Returns user ID."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO users (username, email, password_hash, role, is_active, is_admin)
                   VALUES (%s, %s, %s, 'user', FALSE, FALSE) RETURNING id""",
                (username, email, password_hash),
            )
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
        finally:
            cur.close()


def update_last_login(user_id, ip_address):
    """Update last_login timestamp and IP for a user."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE users SET last_login = %s, last_login_ip = %s WHERE id = %s",
                (datetime.now(), ip_address, user_id),
            )
            conn.commit()
        finally:
            cur.close()


def reset_failed_login_count(user_id):
    """Reset failed_login_count to 0 after successful login."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE users SET failed_login_count = 0 WHERE id = %s",
                (user_id,),
            )
            conn.commit()
        finally:
            cur.close()


def increment_failed_login_count(user_id):
    """Increment failed_login_count by 1."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE users SET failed_login_count = COALESCE(failed_login_count, 0) + 1 WHERE id = %s",
                (user_id,),
            )
            conn.commit()
        finally:
            cur.close()


def record_failed_login(username, ip_address, user_agent, reason):
    """Insert a row into failed_logins table."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO failed_logins (username, ip_address, user_agent, reason) VALUES (%s, %s, %s, %s)",
                    (username, ip_address, user_agent, reason),
                )
                conn.commit()
            finally:
                cur.close()
    except Exception as e:
        logger.debug("record_failed_login error: %s", e)
    # C.R.E.E.D. privacy event — PIPEDA: safeguards + access control
    try:
        from services.creed_privacy_logger import log_privacy_event

        log_privacy_event(
            event_type="access_control_check",
            action="authenticate",
            outcome="failed",
            data_category="personal",
            description=f"Failed login: {reason}",
            details={
                "ip_address": ip_address,
                "pipeda_principle": "safeguards",
            },
        )
    except Exception:
        pass


def log_auth_event(user_id, action, ip_address, user_agent=""):
    """Insert into both audit_log and user_activity_log."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO audit_log (user_id, action, ip_address, user_agent) VALUES (%s, %s, %s, %s)",
                    (user_id, action, ip_address, user_agent),
                )
                if user_id:
                    cur.execute(
                        "INSERT INTO user_activity_log (user_id, username, action, module, ip_address, user_agent) "
                        "VALUES (%s, (SELECT username FROM users WHERE id = %s), %s, 'auth', %s, %s)",
                        (user_id, user_id, action, ip_address, user_agent),
                    )
                conn.commit()
            finally:
                cur.close()
    except Exception as e:
        logger.debug("log_auth_event error: %s", e)


def log_signup_audit(username, ip_address):
    """Log a signup event to audit_log."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO audit_log (action, details, ip_address) VALUES (%s, %s, %s)",
                    ("user_signup", f"New signup: {username}", ip_address),
                )
                conn.commit()
            finally:
                cur.close()
    except Exception as e:
        logger.debug("log_signup_audit error: %s", e)


def delete_session_token(session_token):
    """Remove an active session row by token."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM active_sessions WHERE session_token = %s",
                    (session_token,),
                )
                conn.commit()
            finally:
                cur.close()
    except Exception as e:
        logger.debug("delete_session_token error: %s", e)


# ============================================================================
# SECURITY — Account lockout, password complexity, IP rate limiting
# ============================================================================


def _as_utc(dt):
    """An aware UTC datetime from a database timestamp.

    ``failed_logins.attempted_at`` is ``timestamp WITHOUT time zone`` filled by ``CURRENT_TIMESTAMP`` in a UTC
    session, so a naive value IS UTC (storage is UTC everywhere — see .claude/rules/timezone.md). An aware value
    is converted, not merely stripped, so a non-UTC offset cannot shift the lockout window.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_account_locked(user_data):
    """Check if account is locked due to too many failed login attempts.
    Returns (is_locked, minutes_remaining) tuple.

    2026-10-06: this used to strip the timezone off ``last_attempt`` and then compare it to an AWARE
    ``datetime.now(timezone.utc)`` — Python raises ``TypeError: can't compare offset-naive and offset-aware
    datetimes`` for that, on every call where it got that far (failed_login_count >= MAX_FAILED_ATTEMPTS). The login
    route's catch-all turned it into "An error occurred. Please try again.", so an account with a stale count
    could never sign in, a genuine lockout crashed instead of saying "locked for N minutes", and the
    expired-lockout reset below was unreachable. ``probe`` (the QA harness) was stuck this way since June.
    """
    failed_count = user_data.get("failed_login_count", 0) or 0
    if failed_count < MAX_FAILED_ATTEMPTS:
        return False, 0

    # Check when the last failed login happened
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT MAX(attempted_at) as last_attempt FROM failed_logins WHERE username = %s",
                (user_data["username"],),
            )
            row = cur.fetchone()
            if row and row["last_attempt"]:
                last_attempt = _as_utc(row["last_attempt"])
                unlock_at = last_attempt + timedelta(minutes=LOCKOUT_MINUTES)
                now = datetime.now(timezone.utc)
                if now < unlock_at:
                    remaining = int((unlock_at - now).total_seconds() / 60) + 1
                    # C.R.E.E.D. privacy event — PIPEDA: safeguards (lockout enforced)
                    try:
                        from services.creed_privacy_logger import log_privacy_event

                        log_privacy_event(
                            event_type="access_control_check",
                            action="lockout_gate",
                            outcome="denied",
                            data_category="personal",
                            description=(
                                f"Account locked: {user_data.get('username', 'unknown')} "
                                f"({remaining} min remaining)"
                            ),
                            details={
                                "minutes_remaining": remaining,
                                "failed_count": failed_count,
                                "pipeda_principle": "safeguards",
                            },
                        )
                    except Exception:
                        pass
                    return True, remaining
                else:
                    # Lockout expired — reset count
                    reset_failed_login_count(user_data["id"])
                    return False, 0
        finally:
            cur.close()

    return False, 0


def validate_password_complexity(password):
    """Validate password meets complexity requirements.
    Returns (is_valid, error_message) tuple.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one number"
    return True, ""


def check_ip_rate_limit(ip_address):
    """Check if an IP has exceeded the login rate limit.
    Returns (is_limited, seconds_remaining) tuple.
    """
    # Loopback and Docker bridge IPs never rate-limited — internal tools (QA
    # runner, MCP server) call via 192.168.1.200:3000 which hairpins through the
    # Docker bridge gateway (172.x.x.x range), not 127.0.0.1
    if ip_address in ("127.0.0.1", "::1") or ip_address.startswith("172."):
        return False, 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=IP_RATE_WINDOW)

    with _ip_lock:
        # Clean old entries
        _ip_attempts[ip_address] = [t for t in _ip_attempts[ip_address] if t > cutoff]

        if len(_ip_attempts[ip_address]) >= IP_RATE_LIMIT:
            oldest = min(_ip_attempts[ip_address])
            remaining = int((oldest + timedelta(seconds=IP_RATE_WINDOW) - now).total_seconds()) + 1
            return True, max(remaining, 1)

        # Record this attempt
        _ip_attempts[ip_address].append(now)

    return False, 0


# ============================================================================
# DEVICE AUTHENTICATION — Registration, approval, API keys
# ============================================================================


def generate_api_key():
    """Generate a new API key: archie_ + 32 hex chars."""
    return f"archie_{secrets.token_hex(16)}"


def hash_api_key(key):
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def register_device(device_name, device_type, hostname=None, hardware_info=None, purpose=""):
    """Register a new device. Returns device_id. Status is 'pending' until approved."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO registered_devices (device_name, device_type, hostname, hardware_info, purpose)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (device_name, device_type, hostname, json.dumps(hardware_info or {}), purpose),
            )
            device_id = cur.fetchone()["id"]
            conn.commit()
        finally:
            cur.close()
    logger.info(
        "Device registered: #%d %s (%s) — pending approval",
        device_id,
        device_name,
        device_type,
    )
    return device_id


def approve_device(device_id, approved_by=None):
    """Approve a device and generate its API key. Returns the key (one-time)."""
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """UPDATE registered_devices
                   SET status = 'approved', api_key_hash = %s, approved_at = NOW(), approved_by = %s
                   WHERE id = %s AND status = 'pending' RETURNING id""",
                (key_hash, approved_by, device_id),
            )
            result = cur.fetchone()
            conn.commit()
            if not result:
                return None
        finally:
            cur.close()
    logger.info("Device #%d approved", device_id)
    return api_key


def deny_device(device_id):
    """Deny a pending device registration."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE registered_devices SET status = 'denied' WHERE id = %s AND status = 'pending'",
                (device_id,),
            )
            conn.commit()
        finally:
            cur.close()


def revoke_device(device_id):
    """Revoke an approved device's access."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE registered_devices SET status = 'revoked', api_key_hash = NULL WHERE id = %s",
                (device_id,),
            )
            conn.commit()
        finally:
            cur.close()
    logger.warning("Device #%d revoked", device_id)


def validate_api_key(api_key):
    """Validate an API key. Returns device dict or None."""
    key_hash = hash_api_key(api_key)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT id, device_name, device_type, status
                   FROM registered_devices
                   WHERE api_key_hash = %s AND status = 'approved'""",
                (key_hash,),
            )
            device = cur.fetchone()
            if device:
                cur.execute(
                    "UPDATE registered_devices SET last_seen = NOW(), request_count = request_count + 1 WHERE id = %s",
                    (device["id"],),
                )
                conn.commit()
                return dict(device)
        finally:
            cur.close()
    return None


# NOTE: list_devices() was removed 2026-08-17 (#5706) — its only caller was the
# orphaned GET /api/auth/devices route (removed with it). The rest of the device
# API-key system (register/approve/deny/revoke/validate + registered_devices
# table) is live and stays.


# ---------------------------------------------------------------------------
# 2FA Backup Codes (#2063)
# ---------------------------------------------------------------------------


def generate_backup_codes(user_id: int) -> list:
    """Generate 10 one-time 2FA backup codes. Replaces any existing unused codes."""
    from database import get_db_cursor

    codes = []
    for _ in range(10):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")

    with get_db_cursor(commit=True) as (conn, cur):
        # Delete old codes and insert new ones in a single transaction
        cur.execute("DELETE FROM user_backup_codes WHERE user_id = %s", (user_id,))
        for code in codes:
            code_hash = hashlib.sha256(code.encode()).hexdigest()
            cur.execute(
                "INSERT INTO user_backup_codes (user_id, code_hash) VALUES (%s, %s)",
                (user_id, code_hash),
            )

    log_auth_event(user_id, "backup_codes_generated", "system")
    return codes


def verify_backup_code(user_id: int, code: str) -> bool:
    """Verify a backup code and mark it as used. Uses timing-safe comparison."""
    import hmac as _hmac
    import hashlib as _hashlib
    from database import get_db_cursor

    target = _hashlib.sha256(code.strip().upper().encode()).hexdigest()

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id, code_hash FROM user_backup_codes WHERE user_id = %s AND used_at IS NULL",
            (user_id,),
        )
        rows = cur.fetchall()
        matched = next(
            (r for r in rows if _hmac.compare_digest(r["code_hash"], target)),
            None,
        )
        if not matched:
            log_auth_event(user_id, "backup_code_failed", "system")
            return False
        cur.execute(
            "UPDATE user_backup_codes SET used_at = NOW() WHERE id = %s",
            (matched["id"],),
        )

    log_auth_event(user_id, "backup_code_used", "system")
    return True


# ---------------------------------------------------------------------------
# Password Reset — email-based (#2063)
# ---------------------------------------------------------------------------


def _send_reset_email(to_address: str, reset_url: str) -> None:
    """Send password reset email via Stalwart SMTP."""
    import smtplib
    import os
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.getenv("SMTP_HOST", "192.168.1.200")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "archie")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    if not smtp_pass:
        raise RuntimeError("SMTP_PASSWORD not configured — cannot send reset email")
    smtp_from = os.getenv("SMTP_FROM", "archie@kytranempowerment.com")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "A.R.C.H.I.E. Platform — Password Reset"
    msg["From"] = f"A.R.C.H.I.E. Platform <{smtp_from}>"
    msg["To"] = to_address

    text = (
        "You requested a password reset for your A.R.C.H.I.E. Platform account.\n\n"
        f"Click the link below to reset your password (expires in 1 hour):\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, ignore this email.\n"
    )
    html = (
        "<p>You requested a password reset for your A.R.C.H.I.E. Platform account.</p>"
        f"<p><a href='{reset_url}'>Reset your password</a></p>"
        "<p>This link expires in 1 hour. If you did not request this, ignore this email.</p>"
    )
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def initiate_password_reset(email: str, base_url: str = "https://platform.kytranempowerment.com") -> bool:
    """Create a password reset token and email it to the user.

    Returns True always — silent success prevents email enumeration.
    """
    from services.account_link_service import find_user_by_any_email  # noqa: PLC0415

    user = find_user_by_any_email(email.strip().lower(), active_only=True)

    if not user:
        return True  # Silent — don't reveal whether email exists

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            # Invalidate any existing tokens for this user
            cur.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() " "WHERE user_id = %s AND used_at IS NULL",
                (user["id"],),
            )
            cur.execute(
                "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) " "VALUES (%s, %s, %s)",
                (user["id"], token_hash, expires_at),
            )
            conn.commit()
        finally:
            cur.close()

    reset_url = f"{base_url}/tools/account-center/reset-password/{token}"
    try:
        _send_reset_email(user["email"], reset_url)
    except Exception as exc:
        logger.error("Password reset email failed: %s", exc)
        return False

    return True


def complete_password_reset(token: str, new_password: str) -> tuple:
    """Validate a reset token and update the user's password.

    Returns (success: bool, error_message: str). error_message is empty on success.
    """
    from werkzeug.security import generate_password_hash

    token_hash = hashlib.sha256(token.strip().encode()).hexdigest()

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT t.id, t.user_id, t.expires_at
                   FROM password_reset_tokens t
                   WHERE t.token_hash = %s AND t.used_at IS NULL""",
                (token_hash,),
            )
            row = cur.fetchone()
        finally:
            cur.close()

    if not row:
        return False, "Invalid or expired reset link."

    from datetime import timezone

    if row["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return False, "Reset link has expired. Please request a new one."

    valid, msg = validate_password_complexity(new_password)
    if not valid:
        return False, msg

    pw_hash = generate_password_hash(new_password)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (pw_hash, row["user_id"]),
            )
            cur.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE id = %s",
                (row["id"],),
            )
            conn.commit()
        finally:
            cur.close()

    log_auth_event(row["user_id"], "password_reset_completed", "system")
    return True, ""
