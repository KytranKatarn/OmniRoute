"""Market Watch auth — tier-based access control using KytranAuth SDK."""

import os
import sqlite3
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, session, url_for

from db import get_db

auth_bp = Blueprint("auth", __name__)

# Tier hierarchy (higher index = more access)
TIER_LEVELS = {"free": 0, "viewer": 1, "ai": 2}


def resolve_tier(user):
    """Resolve the highest tier from user entitlements."""
    if not user:
        return "free"
    entitlements = user.get("entitlements", [])
    if "market-watch-ai" in entitlements:
        return "ai"
    if "market-watch-viewer" in entitlements:
        return "viewer"
    return "free"


def get_current_tier():
    """Get the current user's tier from session."""
    user = session.get("kytran_user")
    if not user:
        return "free"
    return resolve_tier(user)


def is_admin():
    """Check if the current user is an admin."""
    user = session.get("kytran_user")
    if not user:
        return False
    return user.get("role") == "admin"


def tier_required(min_tier):
    """Decorator: require a minimum subscription tier.

    Usage:
        @tier_required("viewer")   # viewer + ai + admin
        @tier_required("ai")       # ai + admin only
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = session.get("kytran_user")
            if not user:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"success": False, "error": "Authentication required"}), 401
                return redirect(url_for("kytran_login", next=request.url))

            current_tier = resolve_tier(user)
            current_level = TIER_LEVELS.get(current_tier, 0)
            required_level = TIER_LEVELS.get(min_tier, 0)

            if current_level < required_level:
                return jsonify({
                    "success": False,
                    "error": f"Requires {min_tier} tier",
                    "current_tier": current_tier,
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    """Decorator: require admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def upsert_local_user(user_data):
    """Cache user profile in local SQLite on login."""
    tier = resolve_tier(user_data)
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO users (kytran_sub, username, email, name, role, tier, last_login)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(kytran_sub) DO UPDATE SET
                   username=excluded.username, email=excluded.email,
                   name=excluded.name, role=excluded.role,
                   tier=excluded.tier, last_login=CURRENT_TIMESTAMP""",
            (
                user_data.get("sub"),
                user_data.get("username"),
                user_data.get("email"),
                user_data.get("name"),
                user_data.get("role", "user"),
                tier,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --- Routes ---

@auth_bp.route("/api/me")
def api_me():
    """Return current user profile and tier."""
    user = session.get("kytran_user")
    if not user:
        return jsonify({"authenticated": False, "tier": "free"})
    return jsonify({
        "authenticated": True,
        "username": user.get("username"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "tier": resolve_tier(user),
        "is_admin": user.get("role") == "admin",
    })


@auth_bp.route("/auth/logout")
def logout():
    """Clear session and redirect to landing."""
    session.clear()
    return redirect("/")
