"""Kytran Auth routes — "Sign in with Kytran" SSO for Kytran Business Suite.

Drop-in alongside the existing local auth_bp. Registers:
  /auth/kytran/login      — initiates OAuth flow
  /auth/kytran/callback   — handles callback from ARCHIE hub
  /api/me                 — returns current user profile + tier
  /auth/kytran/logout     — clears Kytran session

Usage in app.py:
    from core.kytran_auth_routes import kytran_sso_bp
    app.register_blueprint(kytran_sso_bp)
"""

import os
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, session, url_for

kytran_sso_bp = Blueprint("kytran_sso", __name__)

PRODUCT_CLIENT_ID = os.environ.get("KYTRAN_CLIENT_ID", "kbs")

TIER_LEVELS = {"free": 0, "viewer": 1, "pro": 2}


def resolve_tier(user):
    """Resolve the highest tier from user entitlements."""
    if not user:
        return "free"
    entitlements = user.get("entitlements", [])
    base = PRODUCT_CLIENT_ID.replace("-viewer", "").replace("-pro", "")
    if f"{base}-pro" in entitlements:
        return "pro"
    if f"{base}-viewer" in entitlements or PRODUCT_CLIENT_ID in entitlements:
        return "viewer"
    if user.get("role") == "admin":
        return "pro"
    return "free"


def get_current_kytran_user():
    """Return the Kytran SSO user from session, or None."""
    return session.get("kytran_user")


def kytran_tier_required(min_tier):
    """Decorator: require a minimum Kytran subscription tier."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = session.get("kytran_user")
            if not user:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"success": False, "error": "Authentication required"}), 401
                return redirect(url_for("kytran_login", next=request.url))
            current_level = TIER_LEVELS.get(resolve_tier(user), 0)
            required_level = TIER_LEVELS.get(min_tier, 0)
            if current_level < required_level:
                return jsonify({
                    "success": False,
                    "error": f"Requires {min_tier} tier",
                    "current_tier": resolve_tier(user),
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


@kytran_sso_bp.route("/api/me")
def api_me():
    """Return current Kytran user profile and tier."""
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


@kytran_sso_bp.route("/auth/kytran/logout")
def kytran_logout():
    """Clear Kytran SSO session and redirect to landing."""
    session.pop("kytran_user", None)
    return redirect("/")
