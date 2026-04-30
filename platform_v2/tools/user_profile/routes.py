"""
User Profile Routes
API endpoints for user profile, accessible modules, and password management.
"""

import os
import time

from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from psycopg2.extras import RealDictCursor

from . import user_profile_bp
from database import get_db_connection

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "static",
    "media",
    "users",
)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@user_profile_bp.route("/")
@login_required
def profile_page():
    return render_template("tools/user_profile.html")


@user_profile_bp.route("/api/profile")
@login_required
def get_profile():
    from rbac import get_accessible_modules
    from module_registry import get_module_by_id

    user = current_user
    module_ids = get_accessible_modules(user)

    # Build module details list
    modules = []
    for mid in module_ids:
        mod = get_module_by_id(mid)
        if mod and mod.enabled and mod.show_on_dashboard:
            modules.append(
                {
                    "id": mod.id,
                    "name": mod.name,
                    "description": mod.description,
                    "icon": mod.icon,
                    "url": mod.route,
                    "category": mod.category.value if mod.category else "",
                }
            )

    # Resolve profile picture (uploaded > oauth > none)
    profile_picture = getattr(user, "profile_picture", None) or getattr(user, "oauth_picture", None)

    return jsonify(
        {
            "success": True,
            "profile": {
                "id": user.id,
                "username": user.username,
                "email": getattr(user, "email", ""),
                "role": ("admin" if getattr(user, "is_admin", False) else getattr(user, "role", "user")),
                "subscription_tier": getattr(user, "subscription_tier", "free"),
                "created_at": (
                    user.created_at.isoformat() if hasattr(user, "created_at") and user.created_at else None
                ),
                "profile_picture": profile_picture,
            },
            "modules": modules,
        }
    )


@user_profile_bp.route("/api/profile/password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password or not new_password:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Both current and new password are required",
                }
            ),
            400,
        )

    from services.auth_service import validate_password_complexity

    pw_valid, pw_error = validate_password_complexity(new_password)
    if not pw_valid:
        return (
            jsonify(
                {
                    "success": False,
                    "error": pw_error,
                }
            ),
            400,
        )

    # Verify current password
    with get_db_connection(cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM users WHERE id = %s",
                (current_user.id,),
            )
            row = cur.fetchone()

            if not row or not check_password_hash(row["password_hash"], current_password):
                return (
                    jsonify({"success": False, "error": "Current password is incorrect"}),
                    403,
                )

            # Update password
            new_hash = generate_password_hash(new_password)
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (new_hash, current_user.id),
            )
            conn.commit()

    return jsonify({"success": True, "message": "Password updated successfully"})


# ============================================================================
# PROFILE PICTURE API
# ============================================================================


@user_profile_bp.route("/api/profile/picture", methods=["POST"])
@login_required
def upload_profile_picture():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "No file selected"}), 400

    # Validate extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
                }
            ),
            400,
        )

    # Validate size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"success": False, "error": "File too large (max 5MB)"}), 400

    # Save file
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"user_{current_user.id}_{int(time.time())}.{ext}"
    safe_name = secure_filename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(file_path)

    # URL path for serving via Flask static
    url_path = f"/static/media/users/{safe_name}"

    # Delete old uploaded picture if it exists
    with get_db_connection(cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_picture FROM users WHERE id = %s",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row["profile_picture"]:
                old_name = os.path.basename(row["profile_picture"])
                old_path = os.path.join(UPLOAD_DIR, old_name)
                if os.path.exists(old_path):
                    os.remove(old_path)

            cur.execute(
                "UPDATE users SET profile_picture = %s WHERE id = %s",
                (url_path, current_user.id),
            )
            conn.commit()

    return jsonify({"success": True, "profile_picture": url_path})


@user_profile_bp.route("/api/profile/picture", methods=["DELETE"])
@login_required
def delete_profile_picture():
    with get_db_connection(cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT profile_picture FROM users WHERE id = %s",
                (current_user.id,),
            )
            row = cur.fetchone()
            if row and row["profile_picture"]:
                old_name = os.path.basename(row["profile_picture"])
                old_path = os.path.join(UPLOAD_DIR, old_name)
                if os.path.exists(old_path):
                    os.remove(old_path)

            cur.execute(
                "UPDATE users SET profile_picture = NULL WHERE id = %s",
                (current_user.id,),
            )
            conn.commit()

    return jsonify({"success": True})


# ============================================================================
# THEME PREFERENCE API
# ============================================================================

VALID_THEMES = [
    "lcars-classic",
    "corporate-blue",
    "midnight-purple",
    "warm-minimal",
    "arctic-light",
    "rose-gold",
    "forest",
    "slate-pro",
]


# ============================================================================
# CONNECTED SERVICES API
# ============================================================================


@user_profile_bp.route("/api/profile/connected-services")
@login_required
def get_connected_services():
    """Return connected Google accounts and Telegram status for current user."""
    user_id = current_user.id
    result = {
        "google_accounts": [],
        "telegram": {"connected": False, "username": None},
        "total_connected": 0,
    }

    try:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                # Google accounts
                cur.execute(
                    """SELECT id, email, scopes, created_at, last_sync_at
                       FROM google_accounts
                       WHERE owner_type = 'user' AND owner_id = %s
                       ORDER BY created_at DESC""",
                    (user_id,),
                )
                for row in cur.fetchall():
                    scopes = row.get("scopes") or []
                    if isinstance(scopes, str):
                        scopes = [s.strip() for s in scopes.split(",") if s.strip()]
                    result["google_accounts"].append(
                        {
                            "email": row["email"],
                            "connected_at": row["created_at"].isoformat() if row["created_at"] else None,
                            "last_sync": row["last_sync_at"].isoformat() if row.get("last_sync_at") else None,
                            "scopes": scopes,
                            "has_gmail": any("gmail" in s or "mail" in s for s in scopes),
                            "has_calendar": any("calendar" in s for s in scopes),
                            "has_drive": any("drive" in s for s in scopes),
                        }
                    )

                # Telegram
                cur.execute(
                    """SELECT telegram_username, first_name, is_authorized
                       FROM telegram_users
                       WHERE user_id = %s
                       LIMIT 1""",
                    (user_id,),
                )
                tg_row = cur.fetchone()
                if tg_row and tg_row.get("is_authorized"):
                    result["telegram"] = {
                        "connected": True,
                        "username": tg_row.get("telegram_username") or tg_row.get("first_name"),
                    }

        # Count total connected services
        total = 0
        if result["google_accounts"]:
            total += 1  # Google counts as one service
        if result["telegram"]["connected"]:
            total += 1
        result["total_connected"] = total
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Connected services query failed: %s", e)

    return jsonify(result)


@user_profile_bp.route("/api/user/theme")
@login_required
def get_user_theme():
    """Get the resolved theme for current user (matches context processor logic)"""
    user_theme = getattr(current_user, "theme_preference", None)
    if user_theme and user_theme in [t for t in VALID_THEMES]:
        theme = user_theme
    else:
        # Org default fallback
        theme = "lcars-classic"
        try:
            with get_db_connection(cursor_factory=RealDictCursor) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT o.settings->>'default_theme' as default_theme
                           FROM organizations o JOIN org_users ou ON ou.org_id = o.id
                           WHERE ou.user_id = %s LIMIT 1""",
                        (current_user.id,),
                    )
                    row = cur.fetchone()
                    if row and row["default_theme"] in [t for t in VALID_THEMES]:
                        theme = row["default_theme"]
        except Exception:
            pass
    return jsonify({"success": True, "theme": theme, "available_themes": VALID_THEMES})


@user_profile_bp.route("/api/user/theme", methods=["PUT"])
@login_required
def set_user_theme():
    """Set user's theme preference"""
    data = request.get_json()
    if not data or "theme" not in data:
        return jsonify({"success": False, "error": "Missing 'theme' field"}), 400

    theme = data["theme"]
    if theme not in VALID_THEMES:
        return (
            jsonify({"success": False, "error": f"Invalid theme: {theme}"}),
            400,
        )

    with get_db_connection(cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET metadata = jsonb_set(
                       COALESCE(metadata, '{}'::jsonb),
                       '{theme_preference}',
                       %s::jsonb
                   )
                   WHERE id = %s""",
                (f'"{theme}"', current_user.id),
            )
            conn.commit()

    # Update in-memory user object
    current_user.theme_preference = theme

    return jsonify({"success": True, "theme": theme})


# ============================================================================
# PREFERENCES API (Task #880)
# ============================================================================


VALID_LANGUAGES = ["en", "fr", "es", "pt", "de", "zh", "ar", "he"]


@user_profile_bp.route("/api/preferences")
@login_required
def get_preferences():
    """Get user notification preferences and language preference."""
    prefs = {
        "email_enabled": True,
        "security_alerts": True,
        "system_updates": True,
        "user_approvals": True,
        "failed_logins": True,
        "language": "en",
    }

    try:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                # Notification preferences
                cur.execute(
                    "SELECT email_enabled, security_alerts, system_updates, user_approvals, failed_logins FROM notification_preferences WHERE user_id = %s",
                    (current_user.id,),
                )
                row = cur.fetchone()
                if row:
                    prefs.update(row)

                # Language preference — canonical source is users.language_preference
                cur.execute(
                    "SELECT language_preference FROM users WHERE id = %s",
                    (current_user.id,),
                )
                user_row = cur.fetchone()
                if user_row and user_row["language_preference"]:
                    prefs["language"] = user_row["language_preference"]
    except Exception:
        pass

    return jsonify({"success": True, "preferences": prefs})


@user_profile_bp.route("/api/preferences", methods=["PUT"])
@login_required
def update_preferences():
    """Update user notification preferences and/or language."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    try:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                # Notification preferences — upsert
                notif_fields = [
                    "email_enabled",
                    "security_alerts",
                    "system_updates",
                    "user_approvals",
                    "failed_logins",
                ]
                notif_data = {k: bool(v) for k, v in data.items() if k in notif_fields}
                if notif_data:
                    cur.execute(
                        "SELECT id FROM notification_preferences WHERE user_id = %s",
                        (current_user.id,),
                    )
                    if cur.fetchone():
                        sets = ", ".join(f"{k} = %s" for k in notif_data.keys())
                        cur.execute(
                            f"UPDATE notification_preferences SET {sets} WHERE user_id = %s",
                            list(notif_data.values()) + [current_user.id],
                        )
                    else:
                        cols = ", ".join(["user_id"] + list(notif_data.keys()))
                        placeholders = ", ".join(["%s"] * (len(notif_data) + 1))
                        cur.execute(
                            f"INSERT INTO notification_preferences ({cols}) VALUES ({placeholders})",
                            [current_user.id] + list(notif_data.values()),
                        )

                # Language preference — persist to users.language_preference (canonical)
                if "language" in data:
                    lang = data["language"]
                    if lang not in VALID_LANGUAGES:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Invalid language. Must be one of: {', '.join(VALID_LANGUAGES)}",
                                }
                            ),
                            400,
                        )
                    cur.execute(
                        "UPDATE users SET language_preference = %s WHERE id = %s",
                        (lang, current_user.id),
                    )

                conn.commit()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True, "message": "Preferences updated"})


# ============================================================================
# ACTIVITY LOG API (Task #881)
# ============================================================================


@user_profile_bp.route("/api/activity")
@login_required
def get_activity():
    """Get recent login sessions and failed login attempts for the current user."""
    activity = {
        "last_login": None,
        "last_login_ip": None,
        "active_sessions": [],
        "failed_logins": [],
    }

    try:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                # Last login info from users table
                cur.execute(
                    "SELECT last_login, last_login_ip FROM users WHERE id = %s",
                    (current_user.id,),
                )
                user_row = cur.fetchone()
                if user_row:
                    activity["last_login"] = user_row["last_login"].isoformat() if user_row["last_login"] else None
                    activity["last_login_ip"] = user_row["last_login_ip"]

                # Active sessions
                cur.execute(
                    """SELECT ip_address, user_agent, created_at, last_activity
                       FROM active_sessions
                       WHERE user_id = %s
                       ORDER BY last_activity DESC
                       LIMIT 20""",
                    (current_user.id,),
                )
                for row in cur.fetchall():
                    activity["active_sessions"].append(
                        {
                            "ip_address": row["ip_address"],
                            "user_agent": _shorten_ua(row["user_agent"]),
                            "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
                            "last_activity": (row["last_activity"].isoformat() if row["last_activity"] else None),
                        }
                    )

                # Recent failed logins (match by username)
                username = current_user.username
                cur.execute(
                    """SELECT ip_address, user_agent, attempted_at, reason
                       FROM failed_logins
                       WHERE LOWER(username) = LOWER(%s)
                       ORDER BY attempted_at DESC
                       LIMIT 10""",
                    (username,),
                )
                for row in cur.fetchall():
                    activity["failed_logins"].append(
                        {
                            "ip_address": row["ip_address"],
                            "user_agent": _shorten_ua(row["user_agent"]),
                            "attempted_at": (row["attempted_at"].isoformat() if row["attempted_at"] else None),
                            "reason": row["reason"],
                        }
                    )
    except Exception as e:
        import logging

        logging.getLogger(__name__).error("Activity API error for user %s: %s", current_user.id, e)

    return jsonify({"success": True, "activity": activity})


# ============================================================================
# SUBSCRIPTION API (Task #882)
# ============================================================================


@user_profile_bp.route("/api/subscriptions")
@login_required
def get_subscriptions():
    """Return membership tier, active subscriptions, and entitlements for current user."""
    try:
        from services.subscription_service import (
            get_user_subscriptions,
            get_user_entitlements,
            get_user_membership_tier,
        )

        user_id = current_user.id
        role = getattr(current_user, "role", "") or ""

        tier = get_user_membership_tier(user_id, user_role=role)
        subs = get_user_subscriptions(user_id)
        entitlements = get_user_entitlements(user_id, user_role=role)

        return jsonify(
            {
                "success": True,
                "membership_tier": tier,
                "subscriptions": subs,
                "entitlements": entitlements,
            }
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Subscriptions query failed: %s", e)
        return (
            jsonify({"success": False, "error": "Failed to load subscriptions"}),
            500,
        )


# ============================================================================
# CONNECTIONS API (Task #883)
# ============================================================================


@user_profile_bp.route("/api/connections")
@login_required
def get_connections():
    """Return OAuth providers, product connections, and API keys for current user."""
    user_id = current_user.id
    result = {"oauth": [], "products": [], "api_keys": []}

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # OAuth connections
        cur.execute(
            """SELECT provider, email, display_name, connected_at, disconnected_at
               FROM user_oauth_connections
               WHERE user_id = %s
               ORDER BY connected_at DESC""",
            (user_id,),
        )
        for row in cur.fetchall():
            result["oauth"].append(
                {
                    "provider": row["provider"],
                    "email": row.get("email"),
                    "display_name": row.get("display_name"),
                    "connected_at": (row["connected_at"].isoformat() if row.get("connected_at") else None),
                    "disconnected_at": (row["disconnected_at"].isoformat() if row.get("disconnected_at") else None),
                    "active": row.get("disconnected_at") is None,
                }
            )

        # API keys
        cur.execute(
            """SELECT id, key_prefix, product, name, created_at, last_used_at, revoked_at
               FROM user_api_keys
               WHERE user_id = %s
               ORDER BY created_at DESC""",
            (user_id,),
        )
        for row in cur.fetchall():
            result["api_keys"].append(
                {
                    "id": row["id"],
                    "key_prefix": row.get("key_prefix"),
                    "product": row.get("product"),
                    "name": row.get("name"),
                    "created_at": (row["created_at"].isoformat() if row.get("created_at") else None),
                    "last_used_at": (row["last_used_at"].isoformat() if row.get("last_used_at") else None),
                    "active": row.get("revoked_at") is None,
                }
            )

        # Product connections — check billing_subscriptions for active modules
        products = [
            {
                "id": "legal-watch",
                "name": "Legal Watch",
                "url": "https://legal.kytranempowerment.com",
            },
            {
                "id": "civic-watch",
                "name": "Civic Watch",
                "url": "https://civic.kytranempowerment.com",
            },
            {
                "id": "market-watch-viewer",
                "name": "Market Watch",
                "url": "https://market.kytranempowerment.com",
            },
            {
                "id": "gov-watch",
                "name": "Gov Watch",
                "url": "https://gov.kytranempowerment.com",
            },
            {
                "id": "kso",
                "name": "System Operations",
                "url": "https://server.kytranempowerment.com",
            },
            {
                "id": "kbs",
                "name": "Business Suite",
                "url": "https://business.kytranempowerment.com",
            },
        ]

        cur.execute(
            """SELECT module FROM billing_subscriptions
               WHERE user_id = %s AND status = 'active'""",
            (user_id,),
        )
        active_modules = {row["module"] for row in cur.fetchall()}

        for p in products:
            p["connected"] = p["id"] in active_modules
        result["products"] = products

    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Connections query failed: %s", e)
        return (
            jsonify({"success": False, "error": "Failed to load connections"}),
            500,
        )
    finally:
        if conn:
            conn.close()

    return jsonify({"success": True, **result})


# ============================================================================
# PRODUCT ACCESS API (Phase 2 Task 1)
# ============================================================================


@user_profile_bp.route("/api/product-access", methods=["GET"])
@login_required
def api_product_access():
    """Return active and locked products for the current user."""
    user_id = current_user.id
    active_slugs = set()
    active_products = []
    locked_products = []

    try:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ag.product_slug, mp.name, mp.url, mp.icon, mp.price_monthly
                    FROM access_grants ag
                    JOIN marketplace_products mp ON mp.slug = ag.product_slug
                    WHERE ag.user_id = %s
                      AND (ag.valid_until IS NULL OR ag.valid_until > NOW())
                    ORDER BY mp.slug
                    """,
                    (user_id,),
                )
                for row in cur.fetchall():
                    slug = row["product_slug"]
                    active_slugs.add(slug)
                    active_products.append(
                        {
                            "slug": slug,
                            "name": row["name"],
                            "url": row["url"] or "",
                            "icon": row["icon"] or "📦",
                            "price_monthly": float(row["price_monthly"] or 0),
                        }
                    )

                cur.execute(
                    "SELECT slug, name, url, icon, price_monthly FROM marketplace_products "
                    "WHERE is_free = FALSE ORDER BY slug"
                )
                for row in cur.fetchall():
                    slug = row["slug"]
                    if slug not in active_slugs:
                        locked_products.append(
                            {
                                "slug": slug,
                                "name": row["name"],
                                "icon": row["icon"] or "📦",
                                "price_monthly": float(row["price_monthly"] or 0),
                                "checkout_url": (
                                    "https://business.kytranempowerment.com/billing/checkout" f"?product={slug}"
                                ),
                            }
                        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Product access query failed: %s", e)
        return jsonify({"error": "Failed to load product access"}), 500

    return jsonify({"active": active_products, "locked": locked_products})


# ============================================================================
# USAGE STATS API (Phase 2 Task 1)
# ============================================================================


@user_profile_bp.route("/api/usage-stats", methods=["GET"])
@login_required
def api_usage_stats():
    """Return usage statistics for the current user."""
    user_id = current_user.id

    try:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT created_at FROM users WHERE id = %s", (user_id,))
                user_row = cur.fetchone()
                member_since = "—"
                if user_row and user_row["created_at"]:
                    member_since = user_row["created_at"].strftime("%Y-%m-%d")

                cur.execute(
                    "SELECT COUNT(*) AS total FROM bridge_jobs " "WHERE created_at > NOW() - INTERVAL '30 days'"
                )
                jobs_row = cur.fetchone()
                api_calls_30d = int(jobs_row["total"] or 0)

                cur.execute("SELECT COUNT(*) AS total FROM agents " "WHERE worker_type = 'ai' AND status = 'active'")
                agents_row = cur.fetchone()
                active_agents = int(agents_row["total"] or 0)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Usage stats query failed: %s", e)
        return jsonify({"error": "Failed to load usage stats"}), 500

    return jsonify(
        {
            "member_since": member_since,
            "api_calls_30d": api_calls_30d,
            "active_agents": active_agents,
        }
    )


def _shorten_ua(ua):
    """Extract a short browser/OS label from a user-agent string."""
    if not ua:
        return "Unknown"
    ua_lower = ua.lower()
    browser = "Browser"
    if "firefox" in ua_lower:
        browser = "Firefox"
    elif "edg" in ua_lower:
        browser = "Edge"
    elif "chrome" in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower:
        browser = "Safari"
    os_name = "OS"
    if "windows" in ua_lower:
        os_name = "Windows"
    elif "mac" in ua_lower:
        os_name = "macOS"
    elif "linux" in ua_lower:
        os_name = "Linux"
    elif "android" in ua_lower:
        os_name = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower:
        os_name = "iOS"
    return f"{browser} / {os_name}"
