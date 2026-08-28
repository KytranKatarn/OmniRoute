"""
Account Center Routes
=====================
API routes for account CRUD, permissions, subscriptions, sessions,
API keys, bulk operations, and activity tracking.
"""

from flask import render_template, jsonify, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from functools import wraps
from werkzeug.security import generate_password_hash
from psycopg2.extras import Json as PgJson
import secrets
import hashlib
import json
import csv
import io
import re
from datetime import datetime, timedelta

from . import account_center_bp
from database import get_db_cursor

# Rate limiting storage (in-memory, resets on restart)
# For production, use Redis-backed rate limiting
_rate_limit_store = {}


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not getattr(current_user, "is_admin", False):
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


def rate_limit(max_requests, window_seconds, key_func=None):
    """
    Simple rate limiting decorator.

    Args:
        max_requests: Maximum requests allowed in window
        window_seconds: Time window in seconds
        key_func: Optional function to generate rate limit key (default: IP + endpoint)
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate rate limit key
            if key_func:
                key = key_func()
            else:
                key = f"{request.remote_addr}:{request.endpoint}"

            now = datetime.now()
            window_start = now - timedelta(seconds=window_seconds)

            # Clean old entries and count recent requests
            if key in _rate_limit_store:
                _rate_limit_store[key] = [t for t in _rate_limit_store[key] if t > window_start]
            else:
                _rate_limit_store[key] = []

            if len(_rate_limit_store[key]) >= max_requests:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Rate limit exceeded. Max {max_requests} requests per {window_seconds} seconds.",
                        }
                    ),
                    429,
                )

            _rate_limit_store[key].append(now)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def validate_password(password):
    """
    Validate password meets security requirements.

    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters"

    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"

    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"

    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit"

    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;\'`~]', password):
        return (
            False,
            "Password must contain at least one special character (!@#$%^&*...)",
        )

    return True, None


def log_activity(
    user_id,
    action,
    module="account_center",
    details=None,
    resource_type=None,
    resource_id=None,
):
    """Log user activity with proper connection handling"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO user_activity_log
                (user_id, username, action, module, resource_type, resource_id, details, ip_address, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    user_id,
                    current_user.username if current_user.is_authenticated else None,
                    action,
                    module,
                    resource_type,
                    resource_id,
                    PgJson(details) if details else None,
                    request.remote_addr,
                    request.headers.get("User-Agent", "")[:500],
                ),
            )
    except Exception as e:
        print(f"Error logging activity: {e}")


# ============================================================================
# PAGE ROUTES
# ============================================================================


@account_center_bp.route("/")
@login_required
@admin_required
def index():
    """User Management dashboard"""
    stats = {
        "total_users": 0,
        "admins": 0,
        "premium": 0,
        "free": 0,
        "active_today": 0,
        "active_sessions": 0,
        "api_keys": 0,
        "organizations": 0,
        "pending_approval": 0,
    }

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Consolidated user stats — single query instead of 5 separate COUNTs
            cur.execute(
                """
                SELECT
                    SUM(CASE WHEN is_active = true THEN 1 ELSE 0 END)::int            AS total_users,
                    SUM(CASE WHEN is_admin = true THEN 1 ELSE 0 END)::int             AS admins,
                    SUM(CASE WHEN subscription_tier IN ('pro','business','enterprise','kytran') THEN 1 ELSE 0 END)::int AS premium,
                    SUM(CASE WHEN subscription_tier = 'free' OR subscription_tier IS NULL THEN 1 ELSE 0 END)::int AS free,
                    SUM(CASE WHEN is_active = false AND last_login IS NULL THEN 1 ELSE 0 END)::int AS pending_approval
                FROM users
                """
            )
            row = cur.fetchone()
            stats["total_users"] = row["total_users"] or 0
            stats["admins"] = row["admins"] or 0
            stats["premium"] = row["premium"] or 0
            stats["free"] = row["free"] or 0
            stats["pending_approval"] = row["pending_approval"] or 0

            cur.execute(
                "SELECT COUNT(DISTINCT user_id) as count FROM user_activity_log"
                " WHERE created_at > NOW() - INTERVAL '24 hours'"
            )
            stats["active_today"] = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM active_sessions")
            stats["active_sessions"] = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM mcp_api_keys WHERE is_active = true")
            stats["api_keys"] = cur.fetchone()["count"]

            try:
                cur.execute("SELECT COUNT(*) as count FROM organizations WHERE status = 'active'")
                stats["organizations"] = cur.fetchone()["count"]
            except Exception:
                stats["organizations"] = 0
    except Exception as e:
        print(f"Error getting stats: {e}")

    return render_template("tools/account_center.html", stats=stats)


# ============================================================================
# OVERVIEW API
# ============================================================================


@account_center_bp.route("/api/overview")
@login_required
@admin_required
def api_overview():
    """Account Center overview — active users, recent logins, security alerts."""
    from services.time_utils import format_local

    result = {
        "active_users": [],
        "recent_activity": [],
        "failed_logins_24h": 0,
        "active_sessions": 0,
        "alerts": [],
    }
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Active users
            cur.execute(
                """SELECT id, username, email, role, is_admin, subscription_tier, last_login
                   FROM users WHERE is_active = true ORDER BY last_login DESC NULLS LAST"""
            )
            system_usernames = {"claude", "archie", "probe"}
            for row in cur.fetchall():
                is_system = row["username"] in system_usernames
                result["active_users"].append(
                    {
                        "id": row["id"],
                        "username": row["username"],
                        "email": row["email"],
                        "role": row["role"],
                        "is_admin": row["is_admin"],
                        "tier": row["subscription_tier"] or "free",
                        "is_system": is_system,
                        "last_login": row["last_login"].isoformat() if row["last_login"] else None,
                        "last_login_display": format_local(row["last_login"]) if row["last_login"] else "Never",
                    }
                )

            # Recent login activity (last 48h)
            cur.execute(
                """SELECT u.username, al.action, al.created_at
                   FROM audit_log al
                   JOIN users u ON al.user_id = u.id
                   WHERE al.action IN ('login_success', 'login_failed')
                   AND al.created_at > NOW() - INTERVAL '48 hours'
                   ORDER BY al.created_at DESC LIMIT 15"""
            )
            for row in cur.fetchall():
                result["recent_activity"].append(
                    {
                        "username": row["username"],
                        "action": row["action"],
                        "created_at": row["created_at"].isoformat(),
                        "display": format_local(row["created_at"]),
                    }
                )

            # Failed logins last 24h
            cur.execute(
                "SELECT COUNT(*) as count FROM audit_log WHERE action = 'login_failed' AND created_at > NOW() - INTERVAL '24 hours'"
            )
            result["failed_logins_24h"] = cur.fetchone()["count"]

            # Active sessions
            cur.execute("SELECT COUNT(*) as count FROM active_sessions")
            result["active_sessions"] = cur.fetchone()["count"]

            # Security alerts — deactivated accounts that logged in today
            cur.execute(
                """SELECT u.username, MAX(al.created_at) as last_seen
                   FROM audit_log al JOIN users u ON al.user_id = u.id
                   WHERE al.action = 'login_success'
                   AND u.is_active = false
                   AND al.created_at > NOW() - INTERVAL '24 hours'
                   GROUP BY u.username"""
            )
            for row in cur.fetchall():
                result["alerts"].append(
                    {
                        "type": "deactivated_login",
                        "message": f"Deactivated account '{row['username']}' logged in today",
                        "severity": "high",
                    }
                )

    except Exception as e:
        print(f"Overview API error: {e}")

    return jsonify(result)


# ============================================================================
# USER CRUD API
# ============================================================================


@account_center_bp.route("/api/users")
@login_required
@admin_required
def api_list_users():
    """List all users with optional filtering"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Get filter parameters — default to active users only
            role_filter = request.args.get("role", "")
            tier_filter = request.args.get("tier", "")
            search = request.args.get("search", "")
            status_filter = request.args.get("status", "active")  # active | inactive | all
            limit = request.args.get("limit", 100, type=int)
            offset = request.args.get("offset", 0, type=int)

            # Build query with session and API key counts
            query = """
                SELECT u.id, u.username, u.email, u.role, u.subscription_tier, u.subscription_status,
                       u.is_admin, u.is_active, u.created_at, u.last_login,
                       COALESCE(s.session_count, 0) as session_count,
                       COALESCE(k.api_key_count, 0) as api_key_count
                FROM users u
                LEFT JOIN (
                    SELECT user_id, COUNT(*) as session_count
                    FROM active_sessions GROUP BY user_id
                ) s ON s.user_id = u.id
                LEFT JOIN (
                    SELECT user_id, COUNT(*) as api_key_count
                    FROM mcp_api_keys WHERE is_active = true GROUP BY user_id
                ) k ON k.user_id = u.id
                WHERE 1=1
            """
            params = []

            if status_filter == "active":
                query += " AND u.is_active = true"
            elif status_filter == "inactive":
                query += " AND u.is_active = false"

            if role_filter:
                query += " AND u.role = %s"
                params.append(role_filter)

            if tier_filter:
                query += " AND u.subscription_tier = %s"
                params.append(tier_filter)

            if search:
                query += " AND (u.username ILIKE %s OR u.email ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

            query += " ORDER BY u.last_login DESC NULLS LAST LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            users = cur.fetchall()

            # Get total count
            count_query = "SELECT COUNT(*) as count FROM users WHERE 1=1"
            count_params = []

            if status_filter == "active":
                count_query += " AND is_active = true"
            elif status_filter == "inactive":
                count_query += " AND is_active = false"
            if role_filter:
                count_query += " AND role = %s"
                count_params.append(role_filter)
            if tier_filter:
                count_query += " AND subscription_tier = %s"
                count_params.append(tier_filter)
            if search:
                count_query += " AND (username ILIKE %s OR email ILIKE %s)"
                count_params.extend([f"%{search}%", f"%{search}%"])

            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]

            return jsonify(
                {
                    "success": True,
                    "users": [dict(u) for u in users],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>")
@login_required
@admin_required
def api_get_user(user_id):
    """Get single user details"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, username, email, role, subscription_tier, subscription_status,
                       is_admin, is_active, created_at, last_login, last_login_ip,
                       preferences, metadata, totp_enabled, totp_verified_at,
                       failed_login_count, locked_until
                FROM users WHERE id = %s
            """,
                (user_id,),
            )
            user = cur.fetchone()

            if not user:
                return jsonify({"success": False, "error": "User not found"}), 404

            # Get user stats including session/API key counts
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM conversations WHERE user_id = %s) as conversations,
                    (SELECT COUNT(*) FROM app_builder_projects WHERE user_id = %s) as app_projects,
                    (SELECT COUNT(*) FROM website_builder_projects WHERE user_id = %s) as website_projects,
                    (SELECT COUNT(*) FROM active_sessions WHERE user_id = %s) as session_count,
                    (SELECT COUNT(*) FROM mcp_api_keys WHERE user_id = %s AND is_active = true) as api_key_count
            """,
                (user_id, user_id, user_id, user_id, user_id),
            )
            stats = cur.fetchone()

            # Get recent activity
            cur.execute(
                """
                SELECT action, module, created_at
                FROM user_activity_log
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 10
            """,
                (user_id,),
            )
            recent_activity = cur.fetchall()

            # Get recent failed login attempts for this user (by username)
            cur.execute(
                """
                SELECT username, ip_address, reason, attempted_at
                FROM failed_logins
                WHERE LOWER(username) = LOWER(%s)
                ORDER BY attempted_at DESC
                LIMIT 10
            """,
                (user["username"],),
            )
            failed_logins = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "user": dict(user),
                    "stats": dict(stats) if stats else {},
                    "recent_activity": [dict(a) for a in recent_activity],
                    "failed_logins": [dict(f) for f in failed_logins],
                }
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users", methods=["POST"])
@login_required
@admin_required
@rate_limit(max_requests=10, window_seconds=60)  # Max 10 user creations per minute
def api_create_user():
    """Create a new user with strong password validation"""
    try:
        data = request.get_json()

        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "")
        role = data.get("role", "user")
        subscription_tier = data.get("subscription_tier", "free")
        is_admin = data.get("is_admin", False)

        if not username:
            return jsonify({"success": False, "error": "Username required"}), 400

        # Validate password strength
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            return jsonify({"success": False, "error": error_msg}), 400

        with get_db_cursor() as (conn, cur):
            # Check if username exists
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return (
                    jsonify({"success": False, "error": "Username already exists"}),
                    400,
                )

            # Create user
            password_hash = generate_password_hash(password)
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role, subscription_tier, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (username, email, password_hash, role, subscription_tier, is_admin),
            )

            new_id = cur.fetchone()["id"]

        log_activity(
            current_user.id,
            "user_created",
            details={"new_user_id": new_id, "username": username},
        )

        return jsonify({"success": True, "user_id": new_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# INVITE SYSTEM
# ============================================================================

_INVITE_SMTP_HOST = "192.168.1.200"
_INVITE_SMTP_PORT = 587
_INVITE_FROM = "admin@kytranempowerment.com"


def _send_invite_email(to_email, invite_link, inviter_name, message=None):
    """Send invite email via Stalwart SMTP. Returns (ok, error_msg)."""
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT imap_password FROM email_mailboxes WHERE address = %s AND provisioned = TRUE AND active = TRUE",
            (_INVITE_FROM,),
        )
        row = cur.fetchone()
    if not row:
        return False, "Invite mailbox not provisioned"

    body = f"""You've been invited by {inviter_name} to join the Kytran Empowerment platform.

Click the link below to accept your invitation (expires in 7 days):

{invite_link}

{("Personal message: " + message) if message else ""}

If you did not expect this invitation, you can ignore this email.
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Invitation to join Kytran Empowerment Platform"
    msg["From"] = _INVITE_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        smtp_user = _INVITE_FROM.split("@")[0]
        with smtplib.SMTP(_INVITE_SMTP_HOST, _INVITE_SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.login(smtp_user, row["imap_password"])
            smtp.sendmail(_INVITE_FROM, [to_email], msg.as_string())
        return True, None
    except Exception as exc:
        return False, str(exc)


@account_center_bp.route("/api/invites", methods=["POST"])
@login_required
@admin_required
def api_create_invite():
    """Send a platform invite to an email address."""
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        role = data.get("role", "collaborator")
        tier = data.get("subscription_tier", "collaborator")
        message = data.get("message", "").strip() or None

        if not email or "@" not in email:
            return jsonify({"success": False, "error": "Valid email required"}), 400

        token = secrets.token_urlsafe(48)
        with get_db_cursor() as (conn, cur):
            # Expire any previous pending invites for this email
            cur.execute(
                "UPDATE user_invites SET status='expired' WHERE email=%s AND status='pending'",
                (email,),
            )
            cur.execute(
                """INSERT INTO user_invites (email, role, subscription_tier, invited_by, token, message)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (email, role, tier, current_user.id, token, message),
            )
            invite_id = cur.fetchone()["id"]

        base_url = request.url_root.rstrip("/")
        invite_link = f"{base_url}/accept-invite?token={token}"

        email_sent, email_err = _send_invite_email(
            email, invite_link, current_user.display_name or current_user.username, message
        )

        log_activity(current_user.id, "invite_sent", details={"email": email, "role": role})

        return jsonify(
            {
                "success": True,
                "invite_id": invite_id,
                "invite_link": invite_link,
                "email_sent": email_sent,
                "email_error": email_err,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/invites", methods=["GET"])
@login_required
@admin_required
def api_list_invites():
    """List all platform invites."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT i.id, i.email, i.role, i.subscription_tier, i.status,
                      i.created_at, i.expires_at, i.accepted_at,
                      u.username AS invited_by_name
               FROM user_invites i
               JOIN users u ON u.id = i.invited_by
               ORDER BY i.created_at DESC LIMIT 100""",
        )
        rows = cur.fetchall()
    return jsonify({"success": True, "invites": [dict(r) for r in rows]})


@account_center_bp.route("/api/invites/<int:invite_id>", methods=["DELETE"])
@login_required
@admin_required
def api_revoke_invite(invite_id):
    """Revoke a pending invite."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "UPDATE user_invites SET status='revoked' WHERE id=%s AND status='pending' RETURNING id",
            (invite_id,),
        )
        if not cur.fetchone():
            return jsonify({"success": False, "error": "Invite not found or already actioned"}), 404
    return jsonify({"success": True})


@account_center_bp.route("/api/invites/<int:invite_id>/resend", methods=["POST"])
@login_required
@admin_required
def api_resend_invite(invite_id):
    """Resend an invite email."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT email, token, message FROM user_invites WHERE id=%s AND status='pending'",
            (invite_id,),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "Invite not found or not pending"}), 404

    base_url = request.url_root.rstrip("/")
    invite_link = f"{base_url}/accept-invite?token={row['token']}"
    ok, err = _send_invite_email(
        row["email"], invite_link, current_user.display_name or current_user.username, row["message"]
    )
    return jsonify({"success": ok, "email_sent": ok, "email_error": err, "invite_link": invite_link})


# ============================================================================


@account_center_bp.route("/api/users/<int:user_id>", methods=["PUT"])
@login_required
@admin_required
def api_update_user(user_id):
    """Update user details"""
    try:
        data = request.get_json()

        # Build update query
        updates = []
        params = []

        # Whitelist of allowed update fields (for reference/documentation)
        # allowed: email, role, subscription_tier, is_admin, is_active, password

        if "email" in data:
            updates.append("email = %s")
            params.append(data["email"])
        if "role" in data:
            updates.append("role = %s")
            params.append(data["role"])
        if "subscription_tier" in data:
            updates.append("subscription_tier = %s")
            params.append(data["subscription_tier"])
        if "is_admin" in data:
            updates.append("is_admin = %s")
            params.append(data["is_admin"])
        if "is_active" in data:
            updates.append("is_active = %s")
            params.append(data["is_active"])
        if "password" in data and data["password"]:
            updates.append("password_hash = %s")
            params.append(generate_password_hash(data["password"]))

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        params.append(user_id)

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "UPDATE users SET " + ", ".join(updates) + " WHERE id = %s",
                params,
            )

        log_activity(
            current_user.id,
            "user_updated",
            details={"target_user_id": user_id, "fields": list(data.keys())},
        )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_user(user_id):
    """Delete a user (soft delete - set inactive)"""
    try:
        # Prevent deleting yourself
        if user_id == current_user.id:
            return (
                jsonify({"success": False, "error": "Cannot delete your own account"}),
                400,
            )

        with get_db_cursor() as (conn, cur):
            cur.execute("UPDATE users SET is_active = false WHERE id = %s", (user_id,))

        log_activity(current_user.id, "user_deleted", details={"target_user_id": user_id})

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/password", methods=["POST"])
@login_required
@admin_required
@rate_limit(max_requests=5, window_seconds=60)  # Max 5 password resets per minute
def api_reset_password(user_id):
    """Reset user password with strong validation"""
    try:
        data = request.get_json()
        new_password = data.get("password") if data else None

        # Validate password strength
        is_valid, error_msg = validate_password(new_password)
        if not is_valid:
            return jsonify({"success": False, "error": error_msg}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            password_hash = generate_password_hash(new_password)
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (password_hash, user_id),
            )

        log_activity(current_user.id, "password_reset", details={"target_user_id": user_id})

        return jsonify({"success": True, "message": "Password reset successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# USER APPROVAL API
# ============================================================================


@account_center_bp.route("/api/users/pending")
@login_required
@admin_required
def api_pending_users():
    """List users pending admin approval (inactive, never logged in)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, username, email, role, created_at
                FROM users
                WHERE is_active = false AND last_login IS NULL
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
            users = []
            for row in rows:
                users.append(
                    {
                        "id": row["id"],
                        "username": row["username"],
                        "email": row["email"],
                        "role": row["role"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    }
                )
            return jsonify({"success": True, "users": users, "total": len(users)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/approve", methods=["POST"])
@login_required
@admin_required
def api_approve_user(user_id):
    """Approve a pending user — sets is_active = true"""
    try:
        with get_db_cursor() as (conn, cur):
            # Verify user exists and is pending
            cur.execute(
                "SELECT id, username, email FROM users WHERE id = %s AND is_active = false AND last_login IS NULL",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "User not found or not pending approval",
                        }
                    ),
                    404,
                )

            # Activate the user
            cur.execute("UPDATE users SET is_active = true WHERE id = %s", (user_id,))

        log_activity(
            current_user.id,
            "user_approved",
            details={
                "target_user_id": user_id,
                "username": user["username"],
            },
        )

        # Try to send Telegram notification to admin channel
        _notify_user_approved(user["username"], user["email"])

        return jsonify(
            {
                "success": True,
                "message": f"User '{user['username']}' has been approved and activated.",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/deny", methods=["POST"])
@login_required
@admin_required
def api_deny_user(user_id):
    """Deny and delete a pending user registration"""
    try:
        with get_db_cursor() as (conn, cur):
            # Verify user exists and is pending
            cur.execute(
                "SELECT id, username FROM users WHERE id = %s AND is_active = false AND last_login IS NULL",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "User not found or not pending approval",
                        }
                    ),
                    404,
                )

            # Delete the pending user
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

        log_activity(
            current_user.id,
            "user_denied",
            details={
                "target_user_id": user_id,
                "username": user["username"],
            },
        )

        return jsonify(
            {
                "success": True,
                "message": f"User '{user['username']}' registration has been denied and removed.",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _notify_user_approved(username, email):
    """Best-effort Telegram notification when a user is approved"""
    try:

        # Notify via platform's internal notification system
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO system_notifications (type, title, message, created_at)
                VALUES ('info', %s, %s, NOW())
                """,
                (
                    "User Approved",
                    f"User '{username}' ({email}) has been approved and can now log in.",
                ),
            )
    except Exception:
        pass  # Best-effort — don't fail the approval


# ============================================================================
# ROLES & PERMISSIONS API
# ============================================================================


@account_center_bp.route("/api/roles")
@login_required
@admin_required
def api_list_roles():
    """List available roles with permission counts and tier mappings"""
    from rbac import ROLE_PERMISSIONS, Role

    # Tier-to-role mapping (role_level from subscription_tiers table)
    tier_role_map = {
        0: ["PUBLIC"],
        5: ["Guest"],
        10: ["Free"],
        15: ["Collaborator"],
        20: ["Pro", "Business", "Enterprise"],
        90: ["Admin (manual)"],
        100: ["Super Admin (manual)", "Kytran"],
    }

    roles = [
        {
            "name": "PUBLIC",
            "level": 0,
            "color": "#6b7280",
            "icon": "globe",
            "description": "Unauthenticated visitors with read-only access to public pages",
        },
        {
            "name": "GUEST",
            "level": 5,
            "color": "#9ca3af",
            "icon": "eye",
            "description": "Demo/tour mode — view-only access to see the platform without modifying anything",
        },
        {
            "name": "USER",
            "level": 10,
            "color": "#06b6d4",
            "icon": "user",
            "description": "Free registered users with basic tools, chat, and limited app building",
        },
        {
            "name": "COLLABORATOR",
            "level": 15,
            "color": "#7c3aed",
            "icon": "users",
            "description": "Invited partners with shared access, own agent, social & creative tools — no admin",
        },
        {
            "name": "PREMIUM",
            "level": 20,
            "color": "#f97316",
            "icon": "crown",
            "description": "Paid subscribers with full creation tools, analytics, and deployment",
        },
        {
            "name": "ADMIN",
            "level": 90,
            "color": "#ef4444",
            "icon": "shield",
            "description": "Administrators with system management, backups, and user control",
        },
        {
            "name": "SUPER_ADMIN",
            "level": 100,
            "color": "#a855f7",
            "icon": "shield-check",
            "description": "System owner with unrestricted access to all permissions",
        },
    ]

    for role_info in roles:
        role_enum = Role[role_info["name"]]
        perms = ROLE_PERMISSIONS.get(role_enum, set())
        role_info["permission_count"] = len(perms)
        role_info["subscription_tiers"] = tier_role_map.get(role_info["level"], [])

    return jsonify({"success": True, "roles": roles})


@account_center_bp.route("/api/permissions")
@login_required
@admin_required
def api_list_permissions():
    """List permissions grouped by category with human-readable labels"""
    try:
        from rbac import Permission, ROLE_PERMISSIONS

        # Human-readable labels and category groupings
        PERM_META = {
            "public:view": {"label": "View Public Pages", "category": "Public Access"},
            "archie:chat": {
                "label": "Chat with A.R.C.H.I.E.",
                "category": "Core Features",
            },
            "code_editor:read": {
                "label": "Code Editor (Read)",
                "category": "Core Features",
            },
            "code_editor:write": {
                "label": "Code Editor (Write)",
                "category": "Core Features",
            },
            "user:settings": {"label": "User Settings", "category": "Core Features"},
            "read:own": {"label": "Read Own Data", "category": "Core Features"},
            "write:own": {"label": "Write Own Data", "category": "Core Features"},
            "task_planner:schedule": {
                "label": "Schedule Tasks",
                "category": "Automation & Tasks",
            },
            "task_planner:calendar": {
                "label": "Calendar Access",
                "category": "Automation & Tasks",
            },
            "google:email": {"label": "Google Email", "category": "Google Workspace"},
            "google:contacts": {
                "label": "Google Contacts",
                "category": "Google Workspace",
            },
            "google:calendar": {
                "label": "Google Calendar",
                "category": "Google Workspace",
            },
            "app_builder:create": {"label": "Create Apps", "category": "App Building"},
            "app_builder:deploy": {"label": "Deploy Apps", "category": "App Building"},
            "app_builder:unlimited": {
                "label": "Unlimited Projects",
                "category": "App Building",
            },
            "website_builder:create": {
                "label": "Create Websites",
                "category": "Website & Store",
            },
            "website_builder:deploy": {
                "label": "Deploy Websites",
                "category": "Website & Store",
            },
            "store:create": {"label": "Create Store", "category": "Website & Store"},
            "store:manage": {"label": "Manage Store", "category": "Website & Store"},
            "telephony:access": {
                "label": "Phone System Access",
                "category": "Website & Store",
            },
            "telephony:admin": {
                "label": "Phone System Admin",
                "category": "Website & Store",
            },
            "social_media:create": {
                "label": "Create Social Posts",
                "category": "Content & Media",
            },
            "social_media:schedule": {
                "label": "Schedule Social Posts",
                "category": "Content & Media",
            },
            "figma:import": {"label": "Figma Import", "category": "Content & Media"},
            "analytics:view": {
                "label": "View Analytics",
                "category": "Content & Media",
            },
            "stock_bot:scan": {"label": "Stock Scanner", "category": "Finance"},
            "stock_bot:alerts": {"label": "Stock Alerts", "category": "Finance"},
            "admin:access": {
                "label": "Admin Panel Access",
                "category": "Administration",
            },
            "admin:agents": {"label": "Manage Agents", "category": "Administration"},
            "admin:improvements": {
                "label": "Improvement Workflow",
                "category": "Administration",
            },
            "admin:users": {"label": "Manage Users", "category": "Administration"},
            "admin:backups": {
                "label": "Backup Management",
                "category": "Administration",
            },
            "admin:logs": {"label": "View System Logs", "category": "Administration"},
            "admin:sandbox": {"label": "Sandbox Access", "category": "Administration"},
            "admin:fine_tuning": {
                "label": "AI Fine-Tuning",
                "category": "Administration",
            },
            "admin:ide": {"label": "IDE Access", "category": "Administration"},
            "admin:testing": {"label": "Testing Tools", "category": "Administration"},
            "admin:projects": {
                "label": "Project Management",
                "category": "Administration",
            },
            "read:all": {"label": "Read All Data", "category": "Administration"},
            "write:all": {"label": "Write All Data", "category": "Administration"},
            "admin:mining": {"label": "Mining Operations", "category": "Super Admin"},
            "admin:system": {"label": "System Operations", "category": "Super Admin"},
            "admin:security": {
                "label": "Security Management",
                "category": "Super Admin",
            },
            "superadmin:all": {
                "label": "Full System Access",
                "category": "Super Admin",
            },
        }

        all_roles = ["PUBLIC", "USER", "PREMIUM", "ADMIN", "SUPER_ADMIN"]

        # Build grouped permissions
        groups = {}
        for perm in Permission:
            meta = PERM_META.get(
                perm.value,
                {
                    "label": perm.value.replace(":", " ").replace("_", " ").title(),
                    "category": "Other",
                },
            )
            category = meta["category"]
            if category not in groups:
                groups[category] = []

            granted_roles = [role.name for role, perms in ROLE_PERMISSIONS.items() if perm in perms]

            groups[category].append(
                {
                    "value": perm.value,
                    "name": perm.name,
                    "label": meta["label"],
                    "roles": {r: r in granted_roles for r in all_roles},
                }
            )

        # Define category order
        CATEGORY_ORDER = [
            "Public Access",
            "Core Features",
            "Automation & Tasks",
            "Google Workspace",
            "App Building",
            "Website & Store",
            "Content & Media",
            "Finance",
            "Obsidian Vault",
            "Administration",
            "Super Admin",
            "Other",
        ]

        ordered_groups = []
        for cat in CATEGORY_ORDER:
            if cat in groups:
                ordered_groups.append({"category": cat, "permissions": groups[cat]})

        # Include any categories not in the predefined order
        for cat in groups:
            if cat not in CATEGORY_ORDER:
                ordered_groups.append({"category": cat, "permissions": groups[cat]})

        return jsonify({"success": True, "groups": ordered_groups, "roles": all_roles})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/role", methods=["PUT"])
@login_required
@admin_required
def api_update_user_role(user_id):
    """Update user's role"""
    if user_id == current_user.id:
        return jsonify({"success": False, "error": "Cannot change your own role"}), 403
    try:
        data = request.get_json()
        role = data.get("role", "user")
        is_admin = role in ["ADMIN", "SUPER_ADMIN"]

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                UPDATE users SET role = %s, is_admin = %s WHERE id = %s
            """,
                (role.lower(), is_admin, user_id),
            )

        log_activity(
            current_user.id,
            "role_changed",
            details={"target_user_id": user_id, "new_role": role},
        )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SUBSCRIPTIONS API
# ============================================================================


@account_center_bp.route("/api/tiers")
@login_required
@admin_required
def api_list_tiers():
    """List subscription tiers with role mapping, permissions, and module access"""
    try:
        from rbac import Role, ROLE_PERMISSIONS
        from module_registry import get_enabled_modules

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, name, display_name, description, price_monthly, price_yearly,
                       features, limits, role_level, color, enabled, currency,
                       stripe_product_id, stripe_price_id_monthly, stripe_price_id_yearly,
                       kbs_product_slug
                FROM subscription_tiers
                WHERE enabled = TRUE
                ORDER BY sort_order
            """
            )
            tiers = cur.fetchall()

            # Get user counts per tier
            cur.execute(
                """
                SELECT COALESCE(subscription_tier, 'free') as tier, COUNT(*) as count
                FROM users
                GROUP BY COALESCE(subscription_tier, 'free')
            """
            )
            tier_counts = {row["tier"]: row["count"] for row in cur.fetchall()}

        # Map role_level to Role enum
        level_to_role = {r.value: r for r in Role}

        # Get all enabled modules for access counting
        all_modules = get_enabled_modules()

        # Previous tier permissions for computing "gained" permissions
        prev_perms = set()

        result = []
        for t in tiers:
            t = dict(t)
            role_level = t.get("role_level", 10)
            role = level_to_role.get(role_level, Role.USER)
            role_perms = ROLE_PERMISSIONS.get(role, set())

            # Permissions gained over previous tier
            gained = role_perms - prev_perms
            prev_perms = role_perms

            # Modules accessible at this role level
            accessible_modules = []
            for mod in all_modules:
                try:
                    mod_role = Role[mod.minimum_role]
                    if role.value >= mod_role.value:
                        accessible_modules.append({"id": mod.id, "name": mod.name, "icon": mod.icon})
                except (KeyError, AttributeError):
                    pass

            t["mapped_role"] = role.name
            t["permission_count"] = len(role_perms)
            t["permissions_gained"] = [p.value for p in sorted(gained, key=lambda x: x.value)]
            t["module_count"] = len(accessible_modules)
            t["modules"] = accessible_modules
            t["user_count"] = tier_counts.get(t["name"], 0)
            result.append(t)

        return jsonify({"success": True, "tiers": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/subscription")
@login_required
@admin_required
def api_get_subscription(user_id):
    """Get user subscription details, usage, and available tiers"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Get user + subscription tier + user_subscriptions data
            cur.execute(
                """
                SELECT u.id, u.username, u.subscription_tier, u.subscription_status,
                       t.id as tier_id, t.name as tier_name, t.display_name, t.color,
                       t.price_monthly, t.features, t.limits, t.role_level,
                       us.status as sub_status, us.started_at, us.expires_at, us.payment_method
                FROM users u
                LEFT JOIN subscription_tiers t ON t.name = u.subscription_tier
                LEFT JOIN user_subscriptions us ON us.user_id = u.id
                WHERE u.id = %s
            """,
                (user_id,),
            )
            row = cur.fetchone()

            if not row:
                return jsonify({"success": False, "error": "User not found"}), 404

            # Map role_level to role name
            role_level = row.get("role_level") or 10
            level_role_map = {
                0: "PUBLIC",
                10: "USER",
                20: "PREMIUM",
                90: "ADMIN",
                100: "SUPER_ADMIN",
            }
            mapped_role = level_role_map.get(role_level, "USER")

            subscription = {
                "tier_id": row["tier_id"],
                "tier_name": row["tier_name"] or row["subscription_tier"] or "free",
                "display_name": row["display_name"] or "Free",
                "color": row["color"] or "#6b7280",
                "price": row["price_monthly"] or 0,
                "features": row["features"] or [],
                "limits": row["limits"] or {},
                "role_level": role_level,
                "mapped_role": mapped_role,
                "status": row["sub_status"] or row["subscription_status"] or "active",
                "started_at": row["started_at"],
                "expires_at": row["expires_at"],
                "payment_method": row["payment_method"],
            }

            # Get usage counts
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*)
                        FROM app_builder_projects
                        WHERE user_id = %s) as app_projects,
                    (SELECT COUNT(*)
                        FROM website_builder_projects
                        WHERE user_id = %s) as website_projects,
                    (SELECT COUNT(*)
                        FROM token_usage_log
                        WHERE user_id = %s
                        AND created_at > NOW() - INTERVAL '1 day'
                    ) as api_calls_today
            """,
                (user_id, user_id, user_id),
            )
            usage = dict(cur.fetchone()) if cur.rowcount else {}

            # Get all enabled tiers
            cur.execute(
                """
                SELECT id, name, display_name, color, price_monthly, features, limits, role_level
                FROM subscription_tiers
                WHERE enabled = true
                ORDER BY sort_order
            """
            )
            available_tiers = [dict(t) for t in cur.fetchall()]

        return jsonify(
            {
                "success": True,
                "subscription": subscription,
                "usage": usage,
                "available_tiers": available_tiers,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/subscription", methods=["PUT"])
@login_required
@admin_required
def api_update_subscription(user_id):
    """Update user's subscription tier, status, and expiry"""
    try:
        data = request.get_json()
        tier = data.get("tier", "free")
        status = data.get("status", "active")
        expires_at = data.get("expires_at")  # ISO date string or null

        with get_db_cursor() as (conn, cur):
            # Update users table
            cur.execute(
                """
                UPDATE users SET subscription_tier = %s, subscription_status = %s WHERE id = %s
            """,
                (tier, status, user_id),
            )

            # Upsert user_subscriptions table
            # Look up tier_id from subscription_tiers
            cur.execute("SELECT id FROM subscription_tiers WHERE name = %s", (tier,))
            tier_row = cur.fetchone()
            tier_id = tier_row["id"] if tier_row else None

            if tier_id:
                # Parse expires_at if provided
                parsed_expires = None
                if expires_at:
                    try:
                        parsed_expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        parsed_expires = None

                cur.execute(
                    """
                    INSERT INTO user_subscriptions (user_id, tier_id, status, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET tier_id = EXCLUDED.tier_id,
                        status = EXCLUDED.status,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                """,
                    (user_id, tier_id, status, parsed_expires),
                )

        log_activity(
            current_user.id,
            "subscription_changed",
            details={
                "target_user_id": user_id,
                "new_tier": tier,
                "status": status,
                "expires_at": expires_at,
            },
        )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SELF-SERVICE BILLING (user-facing, uses platform Stripe Core)
# ============================================================================


@account_center_bp.route("/api/my/aliases")
@login_required
def api_my_aliases_get():
    """List email aliases linked to the current user's canonical account (T23)."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, alias_email, verified, created_at
                   FROM account_email_aliases
                   WHERE canonical_user_id = %s
                   ORDER BY created_at ASC""",
                (current_user.id,),
            )
            aliases = [
                {
                    "id": r["id"],
                    "email": r["alias_email"],
                    "verified": r["verified"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in cur.fetchall()
            ]
        return jsonify({"aliases": aliases})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@account_center_bp.route("/api/my/aliases", methods=["POST"])
@login_required
def api_my_aliases_add():
    """Add an email alias to the current user's canonical account (T23).

    Body: { "email": "alias@example.com" }
    The alias is initially unverified. Verification is out-of-scope for Phase 1.
    Admins can add aliases for any user; regular users can only alias their own.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        alias_email = (data.get("email") or "").strip().lower()
        if not alias_email or "@" not in alias_email:
            return jsonify({"error": "valid email required"}), 400

        # Prevent aliasing an existing canonical user email
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT id FROM users WHERE LOWER(email) = %s", (alias_email,))
            if cur.fetchone():
                return jsonify({"error": "That email is already a canonical account — cannot also be an alias"}), 409

            cur.execute(
                """INSERT INTO account_email_aliases
                   (canonical_user_id, alias_email, verified, added_by)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (alias_email) DO NOTHING
                   RETURNING id""",
                (current_user.id, alias_email, False, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "That email is already an alias of another account"}), 409

        return jsonify({"ok": True, "id": row["id"], "email": alias_email, "verified": False})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@account_center_bp.route("/api/my/aliases/<int:alias_id>", methods=["DELETE"])
@login_required
def api_my_aliases_delete(alias_id: int):
    """Remove an email alias (T23). User can only delete their own aliases."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """DELETE FROM account_email_aliases
                   WHERE id = %s AND canonical_user_id = %s
                   RETURNING alias_email""",
                (alias_id, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Alias not found or not yours"}), 404
        return jsonify({"ok": True, "removed": row["alias_email"]})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@account_center_bp.route("/api/my/subscription")
@login_required
def api_my_subscription():
    """Get the current user's subscription status and billing info."""
    try:
        from services.stripe_service import get_active_subscription, get_customer

        subscription = get_active_subscription(current_user.id)
        customer = get_customer(current_user.id)

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT subscription_tier, subscription_status, subscription_expires_at FROM users WHERE id = %s",
                (current_user.id,),
            )
            user = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "tier": user["subscription_tier"] if user else "free",
                "status": user["subscription_status"] if user else None,
                "expires_at": (
                    user["subscription_expires_at"].isoformat()
                    if user and user.get("subscription_expires_at")
                    else None
                ),
                "has_billing_customer": customer is not None,
                "subscription": (
                    {
                        "stripe_subscription_id": subscription["stripe_subscription_id"],
                        "module": subscription["module"],
                        "status": subscription["status"],
                        "billing_cycle": subscription["billing_cycle"],
                        "cancel_at_period_end": subscription["cancel_at_period_end"],
                        "current_period_end": (
                            subscription["current_period_end"].isoformat()
                            if subscription.get("current_period_end")
                            else None
                        ),
                    }
                    if subscription
                    else None
                ),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/my/billing-portal", methods=["POST"])
@login_required
def api_my_billing_portal():
    """Create a Stripe Billing Portal session for the current user.

    The portal lets users manage subscriptions, payment methods, and invoices
    without custom UI. Redirects to Stripe-hosted portal.
    """
    try:
        from services.stripe_service import get_customer, create_portal_session

        customer = get_customer(current_user.id)
        if not customer:
            return jsonify({"success": False, "error": "No billing account found. Subscribe to a plan first."}), 404

        data = request.get_json(silent=True) or {}
        return_url = data.get("return_url") or request.referrer or "/tools/account-center"

        url = create_portal_session(
            customer_id=customer["stripe_customer_id"],
            return_url=return_url,
        )
        return jsonify({"success": True, "portal_url": url})
    except Exception as e:
        current_app.logger.error(f"[AccountCenter] Billing portal error: {e}")
        return jsonify({"success": False, "error": "Failed to create billing portal session"}), 502


@account_center_bp.route("/api/my/checkout", methods=["POST"])
@login_required
def api_my_checkout():
    """Create a Stripe Checkout session for the current user to subscribe.

    Body: {price_id, success_url (optional), cancel_url (optional)}
    """
    try:
        from services.stripe_service import (
            get_or_create_customer,
            create_checkout_session,
        )

        data = request.get_json(silent=True) or {}
        price_id = data.get("price_id")
        if not price_id:
            return jsonify({"success": False, "error": "price_id is required"}), 400

        customer_id = get_or_create_customer(
            user_id=current_user.id,
            email=current_user.email,
            name=getattr(current_user, "display_name", current_user.email),
        )

        base_url = request.host_url.rstrip("/")
        success_url = data.get("success_url") or f"{base_url}/tools/account-center?billing=success"
        cancel_url = data.get("cancel_url") or f"{base_url}/tools/account-center?billing=cancel"

        url = create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": str(current_user.id)},
        )

        return jsonify({"success": True, "checkout_url": url})
    except Exception as e:
        current_app.logger.error(f"[AccountCenter] Checkout error: {e}")
        return jsonify({"success": False, "error": "Failed to create checkout session"}), 502


@account_center_bp.route("/api/my/payment-methods")
@login_required
def api_my_payment_methods():
    """List the current user's saved payment methods from Stripe."""
    try:
        import stripe
        from services.stripe_service import get_customer, is_stripe_configured

        if not is_stripe_configured():
            return jsonify({"success": True, "payment_methods": []})

        customer = get_customer(current_user.id)
        if not customer:
            return jsonify({"success": True, "payment_methods": []})

        try:
            methods = stripe.PaymentMethod.list(
                customer=customer["stripe_customer_id"],
                type="card",
            )
        except stripe.error.StripeError as e:
            current_app.logger.warning("[AccountCenter] Stripe payment-methods fetch failed: %s", e)
            return jsonify({"success": True, "payment_methods": []})

        return jsonify(
            {
                "success": True,
                "payment_methods": [
                    {
                        "id": pm.id,
                        "brand": pm.card.brand,
                        "last4": pm.card.last4,
                        "exp_month": pm.card.exp_month,
                        "exp_year": pm.card.exp_year,
                    }
                    for pm in methods.data
                ],
            }
        )
    except Exception as e:
        current_app.logger.exception("[AccountCenter] payment-methods unexpected error")
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/usage")
@login_required
@admin_required
def api_get_usage(user_id):
    """Get user's usage statistics against limits"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Get user's tier and limits
            cur.execute(
                """
                SELECT u.subscription_tier, t.limits
                FROM users u
                LEFT JOIN subscription_tiers t ON t.name = u.subscription_tier
                WHERE u.id = %s
            """,
                (user_id,),
            )
            result = cur.fetchone()

            tier = result["subscription_tier"] if result else "free"
            limits = result["limits"] if result and result["limits"] else {}

            # Get actual usage
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*)
                        FROM app_builder_projects
                        WHERE user_id = %s) as app_projects,
                    (SELECT COUNT(*)
                        FROM website_builder_projects
                        WHERE user_id = %s) as website_projects,
                    (SELECT COUNT(*)
                        FROM token_usage_log
                        WHERE user_id = %s
                        AND created_at > NOW() - INTERVAL '1 day'
                    ) as api_calls_today
            """,
                (user_id, user_id, user_id),
            )
            usage = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "tier": tier,
                "limits": limits,
                "usage": dict(usage) if usage else {},
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ACTIVITY API
# ============================================================================


@account_center_bp.route("/api/activity")
@login_required
@admin_required
def api_get_activity():
    """Get activity log"""
    try:
        # Get filter parameters
        user_id = request.args.get("user_id", type=int)
        module = request.args.get("module", "")
        action = request.args.get("action", "")
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        with get_db_cursor(commit=False) as (conn, cur):
            query = """
                SELECT a.*, u.username as user_name
                FROM user_activity_log a
                LEFT JOIN users u ON a.user_id = u.id
                WHERE 1=1
            """
            params = []

            if user_id:
                query += " AND a.user_id = %s"
                params.append(user_id)
            if module:
                query += " AND a.module = %s"
                params.append(module)
            if action:
                query += " AND a.action = %s"
                params.append(action)

            query += " ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            activities = cur.fetchall()

            # Get total count
            count_query = "SELECT COUNT(*) as count FROM user_activity_log WHERE 1=1"
            count_params = []
            if user_id:
                count_query += " AND user_id = %s"
                count_params.append(user_id)
            if module:
                count_query += " AND module = %s"
                count_params.append(module)
            if action:
                count_query += " AND action = %s"
                count_params.append(action)

            cur.execute(count_query, count_params)
            total = cur.fetchone()["count"]

        return jsonify(
            {
                "success": True,
                "activities": [dict(a) for a in activities],
                "total": total,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/activity/modules")
@login_required
@admin_required
def api_get_activity_modules():
    """Get list of modules with activity"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT module, COUNT(*) as count
                FROM user_activity_log
                WHERE module IS NOT NULL
                GROUP BY module
                ORDER BY count DESC
            """
            )
            modules = cur.fetchall()

        return jsonify({"success": True, "modules": [dict(m) for m in modules]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/activity/summary")
@login_required
@admin_required
def api_activity_summary():
    """Get activity summary for dashboard"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Last 7 days activity by day
            cur.execute(
                """
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM user_activity_log
                WHERE created_at > NOW() - INTERVAL '7 days'
                GROUP BY DATE(created_at)
                ORDER BY date
            """
            )
            by_day = cur.fetchall()

            # Top actions
            cur.execute(
                """
                SELECT action, COUNT(*) as count
                FROM user_activity_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY action
                ORDER BY count DESC
                LIMIT 10
            """
            )
            top_actions = cur.fetchall()

            # Most active users
            cur.execute(
                """
                SELECT u.username, COUNT(*) as count
                FROM user_activity_log a
                JOIN users u ON a.user_id = u.id
                WHERE a.created_at > NOW() - INTERVAL '24 hours'
                GROUP BY u.username
                ORDER BY count DESC
                LIMIT 5
            """
            )
            top_users = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "by_day": [dict(d) for d in by_day],
                "top_actions": [dict(a) for a in top_actions],
                "top_users": [dict(u) for u in top_users],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SESSION MANAGEMENT API
# ============================================================================


@account_center_bp.route("/api/sessions")
@login_required
@admin_required
def api_list_sessions():
    """List all active sessions"""
    try:
        user_id = request.args.get("user_id", type=int)
        search = request.args.get("search", "")

        with get_db_cursor(commit=False) as (conn, cur):
            query = """
                SELECT s.*, u.username
                FROM active_sessions s
                LEFT JOIN users u ON s.user_id = u.id
                WHERE 1=1
            """
            params = []

            if user_id:
                query += " AND s.user_id = %s"
                params.append(user_id)
            if search:
                query += " AND s.ip_address ILIKE %s"
                params.append(f"%{search}%")

            query += " ORDER BY s.last_activity DESC LIMIT 100"

            cur.execute(query, params)
            sessions = cur.fetchall()

            # Get users for filter dropdown
            cur.execute(
                """
                SELECT DISTINCT u.id, u.username
                FROM active_sessions s
                JOIN users u ON s.user_id = u.id
                ORDER BY u.username
            """
            )
            users = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "sessions": [dict(s) for s in sessions],
                "users": [dict(u) for u in users],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/sessions/<int:session_id>", methods=["DELETE"])
@login_required
@admin_required
def api_revoke_session(session_id):
    """Revoke a specific session"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("DELETE FROM active_sessions WHERE id = %s", (session_id,))

        log_activity(current_user.id, "session_revoked", details={"session_id": session_id})

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/sessions/expired", methods=["DELETE"])
@login_required
@admin_required
def api_revoke_expired_sessions():
    """Revoke all expired sessions"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                DELETE FROM active_sessions
                WHERE expires_at IS NOT NULL AND expires_at < NOW()
                RETURNING id
            """
            )
            deleted = cur.fetchall()
            count = len(deleted)

        log_activity(current_user.id, "expired_sessions_revoked", details={"count": count})

        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# API KEYS MANAGEMENT
# ============================================================================


@account_center_bp.route("/api/api-keys")
@login_required
@admin_required
def api_list_api_keys():
    """List all API keys"""
    try:
        user_id = request.args.get("user_id", type=int)
        status = request.args.get("status", "")

        with get_db_cursor(commit=False) as (conn, cur):
            query = """
                SELECT k.*, u.username
                FROM mcp_api_keys k
                LEFT JOIN users u ON k.user_id = u.id
                WHERE 1=1
            """
            params = []

            if user_id:
                query += " AND k.user_id = %s"
                params.append(user_id)
            if status == "active":
                query += " AND k.is_active = true AND (k.expires_at IS NULL OR k.expires_at > NOW())"
            elif status == "inactive":
                query += " AND k.is_active = false"
            elif status == "expired":
                query += " AND k.expires_at IS NOT NULL AND k.expires_at <= NOW()"

            query += " ORDER BY k.created_at DESC"

            cur.execute(query, params)
            keys = cur.fetchall()

            # Get users for filter dropdown
            cur.execute("SELECT id, username FROM users WHERE is_active = true ORDER BY username")
            users = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "keys": [dict(k) for k in keys],
                "users": [dict(u) for u in users],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/api-keys", methods=["POST"])
@login_required
@admin_required
@rate_limit(max_requests=10, window_seconds=60)  # Max 10 API keys per minute
def api_create_api_key():
    """Generate a new API key"""
    try:
        data = request.get_json()

        user_id = data.get("user_id")
        name = data.get("name", "").strip()
        description = data.get("description", "")
        permissions = data.get("permissions", ["read"])
        expires_in_days = data.get("expires_in_days")
        rate_limit_val = data.get("rate_limit_per_hour", 1000)

        if not user_id or not name:
            return (
                jsonify({"success": False, "error": "User and name are required"}),
                400,
            )

        # Generate a secure API key
        raw_key = secrets.token_urlsafe(32)
        key_prefix = "arch_" + raw_key[:6]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now() + timedelta(days=int(expires_in_days))

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO mcp_api_keys
                (user_id, key_hash, key_prefix, name, description, permissions,
                 rate_limit_per_hour, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    user_id,
                    key_hash,
                    key_prefix,
                    name,
                    description,
                    PgJson(permissions),
                    rate_limit_val,
                    expires_at,
                ),
            )

            new_id = cur.fetchone()["id"]

        log_activity(
            current_user.id,
            "api_key_created",
            details={"key_id": new_id, "user_id": user_id, "name": name},
        )

        # Return the full key only once - it won't be retrievable later
        full_key = f"arch_{raw_key}"

        return jsonify(
            {
                "success": True,
                "key_id": new_id,
                "api_key": full_key,
                "key_prefix": key_prefix,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/api-keys/<int:key_id>", methods=["PUT"])
@login_required
@admin_required
def api_update_api_key(key_id):
    """Update an API key (activate/deactivate)"""
    try:
        data = request.get_json()

        with get_db_cursor() as (conn, cur):
            if "is_active" in data:
                cur.execute(
                    "UPDATE mcp_api_keys SET is_active = %s WHERE id = %s",
                    (data["is_active"], key_id),
                )

        log_activity(
            current_user.id,
            "api_key_updated",
            details={"key_id": key_id, "changes": list(data.keys())},
        )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/api-keys/<int:key_id>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_api_key(key_id):
    """Delete an API key"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("DELETE FROM mcp_api_keys WHERE id = %s", (key_id,))

        log_activity(current_user.id, "api_key_deleted", details={"key_id": key_id})

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# BULK OPERATIONS API
# ============================================================================


@account_center_bp.route("/api/bulk/export")
@login_required
@admin_required
def api_bulk_export():
    """Export users to CSV or JSON"""
    try:
        format_type = request.args.get("format", "csv")
        scope = request.args.get("scope", "all")

        with get_db_cursor(commit=False) as (conn, cur):
            query = """
                SELECT id, username, email, role, subscription_tier, subscription_status,
                       is_admin, is_active, created_at, last_login
                FROM users
                WHERE 1=1
            """

            if scope == "active":
                query += " AND is_active = true"
            elif scope == "admins":
                query += " AND is_admin = true"
            elif scope == "premium":
                query += " AND subscription_tier IN ('pro', 'business', 'enterprise')"

            query += " ORDER BY created_at DESC"

            cur.execute(query)
            users = cur.fetchall()

        log_activity(
            current_user.id,
            "users_exported",
            details={"format": format_type, "scope": scope, "count": len(users)},
        )

        if format_type == "json":
            # Convert datetime objects to ISO format strings
            for user in users:
                for key in ["created_at", "last_login"]:
                    if user[key]:
                        user[key] = user[key].isoformat()
            return Response(
                json.dumps([dict(u) for u in users], indent=2),
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=users_export.json"},
            )
        else:
            # CSV export
            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            headers = [
                "id",
                "username",
                "email",
                "role",
                "subscription_tier",
                "subscription_status",
                "is_admin",
                "is_active",
                "created_at",
                "last_login",
            ]
            writer.writerow(headers)

            # Data
            for user in users:
                row = [user.get(h, "") for h in headers]
                writer.writerow(row)

            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=users_export.csv"},
            )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/bulk/preview", methods=["POST"])
@login_required
@admin_required
def api_bulk_preview():
    """Preview bulk update operation"""
    try:
        data = request.get_json()
        target = data.get("target", "free")
        action = data.get("action", "upgrade")
        tier = data.get("tier", "pro")

        with get_db_cursor(commit=False) as (conn, cur):
            # Build query based on target
            query = "SELECT id, username, email, subscription_tier FROM users WHERE is_active = true"

            if target == "free":
                query += " AND (subscription_tier = 'free' OR subscription_tier IS NULL)"
            elif target == "inactive":
                query = "SELECT id, username, email, subscription_tier FROM users WHERE is_active = false"
            # 'selected' would require client-side selected IDs

            cur.execute(query)
            users = cur.fetchall()

        # Generate action description
        action_descriptions = {
            "upgrade": f"Upgrade to {tier.upper()} tier",
            "downgrade": f"Downgrade to {tier.upper()} tier",
            "deactivate": "Deactivate accounts",
            "reactivate": "Reactivate accounts",
        }

        return jsonify(
            {
                "success": True,
                "count": len(users),
                "users": [dict(u) for u in users[:50]],  # Limit preview
                "action_description": action_descriptions.get(action, action),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/bulk/update", methods=["POST"])
@login_required
@admin_required
@rate_limit(max_requests=3, window_seconds=60)  # Max 3 bulk operations per minute
def api_bulk_update():
    """Execute bulk update operation with confirmation for large operations"""
    try:
        data = request.get_json()
        target = data.get("target", "free")
        action = data.get("action", "upgrade")
        tier = data.get("tier", "pro")
        confirmed = data.get("confirmed", False)

        with get_db_cursor() as (conn, cur):
            # First, count affected users
            if target == "free":
                cur.execute(
                    """SELECT COUNT(*) as count FROM users
                       WHERE is_active = true
                       AND (subscription_tier = 'free' OR subscription_tier IS NULL)"""
                )
            elif target == "inactive":
                cur.execute("SELECT COUNT(*) as count FROM users WHERE is_active = false")
            else:
                cur.execute("SELECT COUNT(*) as count FROM users")

            affected_count = cur.fetchone()["count"]

            # Require confirmation for operations affecting more than 10 users
            if affected_count > 10 and not confirmed:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Confirmation required",
                            "requires_confirmation": True,
                            "affected_count": affected_count,
                            "message": f"This operation will affect {affected_count} users. Please confirm to proceed.",
                        }
                    ),
                    400,
                )

            # Build update based on action
            if action in ["upgrade", "downgrade"]:
                if target == "free":
                    cur.execute(
                        """
                        UPDATE users SET subscription_tier = %s
                        WHERE is_active = true AND (subscription_tier = 'free' OR subscription_tier IS NULL)
                    """,
                        (tier,),
                    )
                elif target == "inactive":
                    cur.execute(
                        """
                        UPDATE users SET subscription_tier = %s
                        WHERE is_active = false
                    """,
                        (tier,),
                    )

            elif action == "deactivate":
                if target == "free":
                    cur.execute(
                        """
                        UPDATE users SET is_active = false
                        WHERE is_active = true AND (subscription_tier = 'free' OR subscription_tier IS NULL)
                    """
                    )
                elif target == "inactive":
                    pass  # Already inactive

            elif action == "reactivate":
                if target == "inactive":
                    cur.execute("UPDATE users SET is_active = true WHERE is_active = false")

            count = cur.rowcount

        log_activity(
            current_user.id,
            "bulk_update_executed",
            details={
                "target": target,
                "action": action,
                "tier": tier,
                "count": count,
                "confirmed": confirmed,
            },
        )

        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/bulk/import", methods=["POST"])
@login_required
@admin_required
def api_bulk_import():
    """Import users from CSV data"""
    try:
        data = request.get_json()
        users_to_import = data.get("users", [])

        if not users_to_import:
            return jsonify({"success": False, "error": "No users to import"}), 400

        if len(users_to_import) > 1000:
            return (
                jsonify({"success": False, "error": "Maximum 1000 users per import"}),
                400,
            )

        created = 0
        skipped = 0

        with get_db_cursor() as (conn, cur):
            for user_data in users_to_import:
                username = user_data.get("username", "").strip()
                email = user_data.get("email", "").strip()
                password = user_data.get("password", "")
                role = user_data.get("role", "user")
                tier = user_data.get("subscription_tier", "free")

                if not username or not password or not password.strip():
                    skipped += 1
                    continue

                # Check if username exists
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    skipped += 1
                    continue

                password_hash = generate_password_hash(password)
                is_admin = role.lower() in ["admin", "super_admin"]

                cur.execute(
                    """
                    INSERT INTO users (username, email, password_hash, role, subscription_tier, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    (
                        username,
                        email or None,
                        password_hash,
                        role.lower(),
                        tier,
                        is_admin,
                    ),
                )
                created += 1

        log_activity(
            current_user.id,
            "users_imported",
            details={"created": created, "skipped": skipped},
        )

        return jsonify({"success": True, "created": created, "skipped": skipped})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SECURITY API
# ============================================================================


@account_center_bp.route("/api/security/overview")
@login_required
@admin_required
def api_security_overview():
    """Get security overview stats"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # Failed logins in last 24 hours
            cur.execute(
                """
                SELECT COUNT(*) as count FROM failed_logins
                WHERE attempted_at > NOW() - INTERVAL '24 hours'
            """
            )
            failed_logins = cur.fetchone()["count"]

            # Locked accounts
            cur.execute(
                """
                SELECT COUNT(*) as count FROM users
                WHERE locked_until IS NOT NULL AND locked_until > NOW()
            """
            )
            locked_accounts = cur.fetchone()["count"]

            # 2FA enabled users
            cur.execute("SELECT COUNT(*) as count FROM users WHERE totp_enabled = true")
            totp_enabled = cur.fetchone()["count"]

        return jsonify(
            {
                "success": True,
                "failed_logins_24h": failed_logins,
                "locked_accounts": locked_accounts,
                "totp_enabled": totp_enabled,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/security/failed-logins")
@login_required
@admin_required
def api_failed_logins():
    """Get recent failed login attempts with pagination"""
    try:
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) as count FROM failed_logins
                WHERE attempted_at > NOW() - INTERVAL '24 hours'
            """
            )
            total = cur.fetchone()["count"]

            cur.execute(
                """
                SELECT username, ip_address, user_agent, attempted_at, reason
                FROM failed_logins
                WHERE attempted_at > NOW() - INTERVAL '24 hours'
                ORDER BY attempted_at DESC
                LIMIT %s OFFSET %s
            """,
                (limit, offset),
            )
            logins = cur.fetchall()

        return jsonify({"success": True, "logins": [dict(row) for row in logins], "total": total})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/security/2fa")
@login_required
@admin_required
def api_list_2fa_users():
    """List users with 2FA status"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, username, email, totp_enabled, totp_verified_at,
                       failed_login_count, locked_until
                FROM users
                WHERE is_active = true
                ORDER BY totp_enabled DESC, username ASC
            """
            )
            users = cur.fetchall()

        return jsonify({"success": True, "users": [dict(u) for u in users]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/security/2fa/<int:user_id>", methods=["PUT"])
@login_required
@admin_required
def api_toggle_2fa(user_id):
    """Enable, disable, or reset 2FA for a user"""
    try:
        import pyotp
        import qrcode
        import qrcode.constants
        import base64
        from io import BytesIO

        data = request.get_json()
        enabled = data.get("enabled", False)
        reset = data.get("reset", False)

        totp_secret = None
        qr_code_data = None
        username = None

        with get_db_cursor() as (conn, cur):
            if enabled and reset:
                # Reset: generate new TOTP secret, keep enabled
                totp_secret = pyotp.random_base32()
                cur.execute(
                    """
                    UPDATE users SET totp_secret = %s, totp_enabled = true, totp_verified_at = NOW()
                    WHERE id = %s
                """,
                    (totp_secret, user_id),
                )
                action = "2fa_reset"
            elif enabled:
                # Enable: generate TOTP secret
                totp_secret = pyotp.random_base32()
                cur.execute(
                    """
                    UPDATE users SET totp_secret = %s, totp_enabled = true, totp_verified_at = NOW()
                    WHERE id = %s
                """,
                    (totp_secret, user_id),
                )
                action = "2fa_enabled"
            else:
                # Disable 2FA - clear secret and status
                cur.execute(
                    """
                    UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_verified_at = NULL
                    WHERE id = %s
                """,
                    (user_id,),
                )
                action = "2fa_disabled"

            # Get username for provisioning URI if we have a new secret
            if totp_secret:
                cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
                user_row = cur.fetchone()
                username = user_row["username"] if user_row else f"user_{user_id}"

        # Generate QR code if we have a new secret (outside DB context)
        if totp_secret:
            totp = pyotp.TOTP(totp_secret)
            provisioning_uri = totp.provisioning_uri(name=username, issuer_name="A.R.C.H.I.E.")

            # Generate QR code as base64 PNG
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=6,
                border=4,
            )
            qr.add_data(provisioning_uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            qr_code_data = "data:image/png;base64," + base64.b64encode(buffer.read()).decode("utf-8")

        log_activity(current_user.id, action, details={"target_user_id": user_id})

        result = {"success": True}
        if totp_secret:
            result["totp_secret"] = totp_secret
            result["qr_code"] = qr_code_data
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/preferences", methods=["GET", "POST"])
@login_required
def api_preferences():
    """Get or update the current user's preferences including language.

    GET  — returns {preferred_language}
    POST — body {preferred_language: "en"} updates the preference
    """
    user_id = current_user.id
    try:
        if request.method == "GET":
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT preferred_language FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
            return jsonify(
                {
                    "success": True,
                    "preferred_language": (row["preferred_language"] if row else "en") or "en",
                }
            )

        # POST — update language preference
        body = request.get_json(silent=True) or {}
        lang = (body.get("preferred_language") or "en").strip()[:10]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE users SET preferred_language = %s WHERE id = %s",
                (lang, user_id),
            )
        return jsonify({"success": True, "preferred_language": lang})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/security/unlock/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def api_unlock_user(user_id):
    """Unlock a locked user account"""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                UPDATE users SET locked_until = NULL, failed_login_count = 0
                WHERE id = %s
            """,
                (user_id,),
            )

        log_activity(current_user.id, "user_unlocked", details={"target_user_id": user_id})

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SUBSCRIPTION MANAGEMENT (Phase 2 — entitlements, trials, revoke)
# ============================================================================


@account_center_bp.route("/api/users/<int:user_id>/entitlements")
@login_required
@admin_required
def api_get_entitlements(user_id):
    """Get computed entitlements for a user via subscription_service"""
    try:
        from services.subscription_service import (
            get_user_subscriptions,
            get_user_entitlements,
            get_user_membership_tier,
        )

        # Get user role from DB
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "User not found"}), 404
            user_role = row["role"]

        membership_tier = get_user_membership_tier(user_id, user_role)
        subscriptions = get_user_subscriptions(user_id)
        entitlements = get_user_entitlements(user_id, user_role)

        # Serialize datetimes in subscriptions
        for sub in subscriptions:
            for key in ("expires_at", "created_at"):
                if sub.get(key) and hasattr(sub[key], "isoformat"):
                    sub[key] = sub[key].isoformat()

        # Serialize datetimes in entitlements
        for module_key, ent in entitlements.items():
            if isinstance(ent, dict) and ent.get("expires_at"):
                if hasattr(ent["expires_at"], "isoformat"):
                    ent["expires_at"] = ent["expires_at"].isoformat()

        return jsonify(
            {
                "success": True,
                "user_id": user_id,
                "membership_tier": membership_tier,
                "subscriptions": subscriptions,
                "entitlements": entitlements,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/trial", methods=["POST"])
@login_required
@admin_required
def api_grant_trial(user_id):
    """Grant a time-limited trial subscription to a user"""
    try:
        from services.subscription_service import grant_trial

        data = request.get_json(silent=True) or {}
        module = data.get("module")
        tier_price_id = data.get("tier_price_id", "")
        duration_days = data.get("duration_days")

        if not module:
            return (
                jsonify({"success": False, "error": "module is required"}),
                400,
            )
        if not duration_days:
            return (
                jsonify({"success": False, "error": "duration_days is required"}),
                400,
            )

        try:
            duration_days = int(duration_days)
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "duration_days must be an integer"}),
                400,
            )

        if duration_days < 1 or duration_days > 90:
            return (
                jsonify({"success": False, "error": "duration_days must be between 1 and 90"}),
                400,
            )

        result = grant_trial(user_id, module, tier_price_id, duration_days, current_user.id)
        if not result:
            return (
                jsonify({"success": False, "error": "Failed to grant trial"}),
                500,
            )

        # Audit log
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, details, ip_address, created_at)
                VALUES (%s, 'grant_trial', %s, %s, NOW())
                """,
                (
                    current_user.id,
                    PgJson(
                        {
                            "target_user_id": user_id,
                            "module": module,
                            "tier_price_id": tier_price_id,
                            "duration_days": duration_days,
                        }
                    ),
                    request.remote_addr,
                ),
            )

        log_activity(
            current_user.id,
            "grant_trial",
            details={
                "target_user_id": user_id,
                "module": module,
                "duration_days": duration_days,
            },
        )

        # Serialize expires_at
        expires_at = result.get("expires_at")
        if expires_at and hasattr(expires_at, "isoformat"):
            expires_at = expires_at.isoformat()

        return jsonify(
            {
                "success": True,
                "trial": {"id": result["id"], "expires_at": expires_at},
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@account_center_bp.route("/api/users/<int:user_id>/revoke-subscription", methods=["POST"])
@login_required
@admin_required
def api_revoke_subscription(user_id):
    """Revoke a trial or admin-override subscription"""
    try:
        from services.subscription_service import revoke_subscription

        data = request.get_json(silent=True) or {}
        subscription_id = data.get("subscription_id")
        if not subscription_id:
            return (
                jsonify({"success": False, "error": "subscription_id is required"}),
                400,
            )

        success = revoke_subscription(subscription_id, current_user.id)
        if not success:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Could not revoke. Only trial/override subscriptions can be revoked.",
                    }
                ),
                400,
            )

        # Audit log
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, details, ip_address, created_at)
                VALUES (%s, 'revoke_subscription', %s, %s, NOW())
                """,
                (
                    current_user.id,
                    PgJson(
                        {
                            "target_user_id": user_id,
                            "subscription_id": subscription_id,
                        }
                    ),
                    request.remote_addr,
                ),
            )

        log_activity(
            current_user.id,
            "revoke_subscription",
            details={
                "target_user_id": user_id,
                "subscription_id": subscription_id,
            },
        )

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 2FA Backup Codes (#2063)
# ---------------------------------------------------------------------------


@account_center_bp.route("/api/security/backup-codes/generate", methods=["POST"])
@login_required
def generate_backup_codes_route():
    """Generate new 2FA backup codes for the current user."""
    from services.auth_service import generate_backup_codes

    codes = generate_backup_codes(current_user.id)
    return jsonify({"success": True, "codes": codes})


@account_center_bp.route("/api/security/backup-codes/count", methods=["GET"])
@login_required
def backup_codes_count():
    """Return how many unused backup codes the current user has."""
    from psycopg2.extras import RealDictCursor
    from database import get_db_connection

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM user_backup_codes WHERE user_id=%s AND used_at IS NULL",
                (current_user.id,),
            )
            row = cur.fetchone()
        finally:
            cur.close()
    return jsonify({"unused_count": row["cnt"] if row else 0})


# ---------------------------------------------------------------------------
# Password Reset — public routes, no login required (#2063)
# ---------------------------------------------------------------------------


@account_center_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Initiate email-based password reset."""
    if request.method == "GET":
        return render_template("tools/account_center/forgot_password.html")
    email = (request.form.get("email") or "").strip()
    if not email:
        return jsonify({"error": "Email required"}), 400
    from services.auth_service import initiate_password_reset

    base_url = request.host_url.rstrip("/")
    initiate_password_reset(email, base_url)
    return jsonify(
        {
            "success": True,
            "message": "If that email exists, a reset link has been sent.",
        }
    )


@account_center_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_via_token(token):
    """Complete password reset from email link."""
    if request.method == "GET":
        return render_template("tools/account_center/reset_password.html", token=token)
    new_password = request.form.get("password", "")
    from services.auth_service import complete_password_reset

    ok, err = complete_password_reset(token, new_password)
    if ok:
        return jsonify({"success": True, "message": "Password updated. You can now log in."})
    return jsonify({"success": False, "error": err}), 400


# ---------------------------------------------------------------------------
# Internal access grant/revoke/check/list API (token-authenticated)
# ---------------------------------------------------------------------------
from .access_routes import access_bp as _access_bp  # noqa: E402

account_center_bp.register_blueprint(_access_bp)

# account_link_verify_bp is registered directly on the Flask app in app.py
# (no url_prefix) so /account/verify-alternate is a short public URL for emails.
