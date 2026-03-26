"""
OAuth 2.0 Provider — Authorization Code Flow
Allows standalone products to authenticate users via "Sign in with Kytran".

Endpoints:
  GET  /oauth/authorize  — issues auth code (requires login)
  POST /oauth/token       — exchanges code for JWT access token

Tables: oauth_clients, oauth_codes (created by Task 1 migration)
"""

import secrets
from datetime import datetime, timedelta

import jwt
from flask import Blueprint, redirect, request, jsonify
from flask_login import login_required, current_user

from database import get_db_cursor

oauth_provider_bp = Blueprint("oauth_provider", __name__, url_prefix="/oauth")

JWT_SECRET = "fallback-secret"


def init_oauth_provider(app):
    """Bind JWT_SECRET to Flask app config and register the blueprint."""
    global JWT_SECRET
    JWT_SECRET = app.config.get("SECRET_KEY", "fallback-secret")
    app.register_blueprint(oauth_provider_bp)


# ============================================================================
# GET /oauth/authorize — issue an authorization code
# ============================================================================


@oauth_provider_bp.route("/authorize")
@login_required
def authorize():
    client_id = request.args.get("client_id")
    redirect_uri = request.args.get("redirect_uri")

    if not client_id or not redirect_uri:
        return jsonify({"error": "missing client_id or redirect_uri"}), 400

    # Validate client
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT redirect_uri FROM oauth_clients WHERE client_id = %s AND is_active = true",
            (client_id,),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"error": "invalid client_id"}), 400

    if row[0] != redirect_uri:
        return jsonify({"error": "redirect_uri mismatch"}), 400

    # Generate code and store with 5-minute expiry
    code = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO oauth_codes (code, client_id, user_id, redirect_uri, expires_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (code, client_id, current_user.id, redirect_uri, expires_at),
        )

    # Redirect back to the client with the code
    separator = "&" if "?" in redirect_uri else "?"
    return redirect(f"{redirect_uri}{separator}code={code}")


# ============================================================================
# POST /oauth/token — exchange code for JWT
# ============================================================================


@oauth_provider_bp.route("/token", methods=["POST"])
def token():
    data = request.get_json(silent=True) or {}
    grant_type = data.get("grant_type")
    code = data.get("code")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    redirect_uri = data.get("redirect_uri")

    if grant_type != "authorization_code":
        return jsonify({"error": "unsupported_grant_type"}), 400

    if not all([code, client_id, client_secret, redirect_uri]):
        return jsonify({"error": "missing required fields"}), 400

    # Validate client credentials
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT client_secret FROM oauth_clients WHERE client_id = %s AND is_active = true",
            (client_id,),
        )
        client_row = cur.fetchone()

    if not client_row or client_row[0] != client_secret:
        return jsonify({"error": "invalid_client"}), 401

    # Validate and consume the authorization code
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """SELECT user_id, redirect_uri, expires_at, used
               FROM oauth_codes
               WHERE code = %s AND client_id = %s""",
            (code, client_id),
        )
        code_row = cur.fetchone()

        if not code_row:
            return jsonify({"error": "invalid_grant"}), 400

        user_id, stored_uri, expires_at, used = code_row

        if used:
            return jsonify({"error": "code_already_used"}), 400
        if datetime.utcnow() > expires_at:
            return jsonify({"error": "code_expired"}), 400
        if stored_uri != redirect_uri:
            return jsonify({"error": "redirect_uri_mismatch"}), 400

        # Mark code as used
        cur.execute("UPDATE oauth_codes SET used = true WHERE code = %s", (code,))

        # Fetch user info
        cur.execute(
            "SELECT id, username, email, role FROM users WHERE id = %s",
            (user_id,),
        )
        user_row = cur.fetchone()

    if not user_row:
        return jsonify({"error": "user_not_found"}), 400

    uid, username, email, role = user_row

    # Generate JWT
    now = datetime.utcnow()
    payload = {
        "sub": uid,
        "username": username,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    access_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    return jsonify(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "user": {
                "id": uid,
                "username": username,
                "email": email,
                "role": role,
            },
        }
    )
