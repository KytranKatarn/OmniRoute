"""Auth service — shared queries for login, logout, signup, session management.

Owner: app.py core auth routes (login, logout, signup, verify_2fa)
Tables: users, failed_logins, audit_log, user_activity_log, active_sessions

Import:
    from services.auth_service import get_user_by_username, record_failed_login
"""

import logging
from datetime import datetime

from psycopg2.extras import RealDictCursor
from database import get_db_connection

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
