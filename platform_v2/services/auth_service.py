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
from datetime import datetime, timedelta
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
    """Lookup user by username. Returns full user row dict or None."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
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


def is_account_locked(user_data):
    """Check if account is locked due to too many failed login attempts.
    Returns (is_locked, minutes_remaining) tuple.
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
                last_attempt = row["last_attempt"]
                # Strip timezone if present for comparison
                if hasattr(last_attempt, "tzinfo") and last_attempt.tzinfo:
                    last_attempt = last_attempt.replace(tzinfo=None)
                unlock_at = last_attempt + timedelta(minutes=LOCKOUT_MINUTES)
                now = datetime.utcnow()
                if now < unlock_at:
                    remaining = int((unlock_at - now).total_seconds() / 60) + 1
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
    now = datetime.utcnow()
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


def list_devices(status=None):
    """List registered devices, optionally filtered by status."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            if status:
                cur.execute(
                    "SELECT * FROM registered_devices WHERE status = %s ORDER BY registered_at DESC",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM registered_devices ORDER BY registered_at DESC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
