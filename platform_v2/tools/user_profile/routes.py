"""
User Profile Routes
API endpoints for user profile, accessible modules, and password management.
"""

from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from psycopg2.extras import RealDictCursor

from . import user_profile_bp
from database import get_db_connection


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

    if len(new_password) < 8:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "New password must be at least 8 characters",
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
