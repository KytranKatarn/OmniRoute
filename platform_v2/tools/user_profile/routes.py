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
