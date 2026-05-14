"""
OAuth 2.0 Provider — Authorization Code Flow
Allows standalone products to authenticate users via "Sign in with Kytran".

Endpoints:
  GET  /oauth/authorize  — issues auth code (requires login)
  POST /oauth/token       — exchanges code for JWT access token

Tables: oauth_clients, oauth_codes (created by Task 1 migration)
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import psycopg2
import jwt
from flask import Blueprint, redirect, request, jsonify
from flask_login import login_required, current_user

from database import get_db_cursor


def _verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    computed = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    return computed == code_challenge


oauth_provider_bp = Blueprint("oauth_provider", __name__, url_prefix="/oauth")

JWT_SECRET: str | None = None


def init_oauth_provider(app):
    """Bind JWT_SECRET to Flask app config and register the blueprint.

    Fails loudly at startup if SECRET_KEY is missing or is the legacy
    placeholder — signing JWTs with a known value would allow forged tokens.
    """
    global JWT_SECRET
    secret = app.config.get("SECRET_KEY")
    if not secret or secret in ("fallback-secret", "dev-secret-key-change-in-production"):
        raise RuntimeError(
            "SECRET_KEY must be set to a strong, non-default value before "
            "initializing oauth_provider (got missing or placeholder)."
        )
    JWT_SECRET = secret
    app.register_blueprint(oauth_provider_bp)


# ============================================================================
# GET /oauth/authorize — issue an authorization code
# ============================================================================


@oauth_provider_bp.route("/authorize")
@login_required
def authorize():
    client_id = request.args.get("client_id")
    redirect_uri = request.args.get("redirect_uri")
    state = request.args.get("state", "")

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

    if row["redirect_uri"] != redirect_uri:
        return jsonify({"error": "redirect_uri mismatch"}), 400

    # Capture optional PKCE parameters
    code_challenge = request.args.get("code_challenge") or None
    code_challenge_method = request.args.get("code_challenge_method", "S256") if code_challenge else None
    if code_challenge_method and code_challenge_method not in ("S256", "plain"):
        return jsonify({"error": "unsupported code_challenge_method"}), 400

    # Generate code and store with 5-minute expiry
    code = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO oauth_codes
                   (code, client_id, user_id, redirect_uri, expires_at,
                    code_challenge, code_challenge_method)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                code,
                client_id,
                current_user.id,
                redirect_uri,
                expires_at,
                code_challenge,
                code_challenge_method,
            ),
        )

    # Redirect back to the client with the code + state (OAuth 2.0 spec)
    separator = "&" if "?" in redirect_uri else "?"
    callback = f"{redirect_uri}{separator}code={code}"
    if state:
        callback += f"&state={state}"
    return redirect(callback)


# ============================================================================
# POST /oauth/token — exchange code for JWT
# ============================================================================


@oauth_provider_bp.route("/token", methods=["POST"])
def token():
    # Accept both JSON and form-encoded POST data
    data = request.get_json(silent=True) or request.form or {}
    grant_type = data.get("grant_type")
    code = data.get("code")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    redirect_uri = data.get("redirect_uri")
    code_verifier = data.get("code_verifier") or None

    # ── Refresh token grant ────────────────────────────────────────────────
    if grant_type == "refresh_token":
        incoming_rt = data.get("refresh_token", "")
        if not incoming_rt:
            return jsonify({"error": "invalid_request", "error_description": "refresh_token required"}), 400

        new_rt = secrets.token_urlsafe(32)
        now_rt = datetime.now(timezone.utc)

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Lock the token row to prevent concurrent refresh races
                cur.execute(
                    """SELECT rt.user_id, rt.client_id,
                              u.id, u.username, u.email, u.role, u.subscription_tier
                       FROM oauth_refresh_tokens rt
                       JOIN users u ON u.id = rt.user_id
                       WHERE rt.token = %s
                         AND rt.revoked = FALSE
                         AND rt.expires_at > NOW()
                         AND u.is_active = TRUE
                       FOR UPDATE""",
                    (incoming_rt,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "invalid_grant"}), 400

                # Rotate in the same transaction
                cur.execute(
                    "UPDATE oauth_refresh_tokens SET revoked = TRUE WHERE token = %s",
                    (incoming_rt,),
                )
                cur.execute(
                    """INSERT INTO oauth_refresh_tokens (token, client_id, user_id, expires_at)
                       VALUES (%s, %s, %s, NOW() + INTERVAL '30 days')""",
                    (new_rt, row["client_id"], row["id"]),
                )
        except psycopg2.Error:
            return jsonify({"error": "server_error"}), 503
        except Exception:
            return jsonify({"error": "invalid_grant"}), 400

        rt_payload = {
            "sub": str(row["id"]),
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "tier": row["subscription_tier"] or "free",
            "is_owner": (row["subscription_tier"] == "kytran" or row["username"] == "kytran"),
            "iat": now_rt,
            "exp": now_rt + timedelta(hours=8),
        }
        new_at = jwt.encode(rt_payload, JWT_SECRET, algorithm="HS256")

        return jsonify(
            {
                "access_token": new_at,
                "token_type": "Bearer",
                "expires_in": 28800,
                "refresh_token": new_rt,
            }
        )
    # ── End refresh token grant ────────────────────────────────────────────

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

    if not client_row or client_row["client_secret"] != client_secret:
        return jsonify({"error": "invalid_client"}), 401

    # Validate and consume the authorization code
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """SELECT user_id, redirect_uri, expires_at, used,
                      code_challenge, code_challenge_method
               FROM oauth_codes
               WHERE code = %s AND client_id = %s""",
            (code, client_id),
        )
        code_row = cur.fetchone()

        if not code_row:
            return jsonify({"error": "invalid_grant"}), 400

        if code_row["used"]:
            return jsonify({"error": "code_already_used"}), 400
        if datetime.now(timezone.utc).replace(tzinfo=None) > code_row["expires_at"]:
            return jsonify({"error": "code_expired"}), 400
        if code_row["redirect_uri"] != redirect_uri:
            return jsonify({"error": "redirect_uri_mismatch"}), 400

        # Verify PKCE if the code was issued with a challenge
        if code_row["code_challenge"]:
            if not code_verifier:
                return jsonify({"error": "code_verifier required for PKCE"}), 400
            method = code_row["code_challenge_method"] or "S256"
            if method == "S256":
                if not _verify_pkce_s256(code_verifier, code_row["code_challenge"]):
                    return jsonify({"error": "invalid_pkce_verifier"}), 400
            elif method == "plain":
                if code_verifier != code_row["code_challenge"]:
                    return jsonify({"error": "invalid_pkce_verifier"}), 400

        user_id = code_row["user_id"]

        # Mark code as used
        cur.execute("UPDATE oauth_codes SET used = true WHERE code = %s", (code,))

        # Fetch user info
        cur.execute(
            "SELECT id, username, email, role, subscription_tier FROM users WHERE id = %s",
            (user_id,),
        )
        user_row = cur.fetchone()

    if not user_row:
        return jsonify({"error": "user_not_found"}), 400

    uid = user_row["id"]
    username = user_row["username"]
    email = user_row["email"]
    role = user_row["role"]
    subscription_tier = user_row["subscription_tier"] or "free"
    is_owner = subscription_tier == "kytran" or username == "kytran"

    # Generate JWT
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uid),
        "username": username,
        "email": email,
        "role": role,
        "tier": subscription_tier,
        "is_owner": is_owner,
        "iat": now,
        "exp": now + timedelta(hours=8),
    }
    access_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Issue a refresh token — store in oauth_refresh_tokens (30-day TTL)
    refresh_token_value = secrets.token_urlsafe(32)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO oauth_refresh_tokens (token, client_id, user_id)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (token) DO NOTHING""",
                (refresh_token_value, client_id, uid),
            )
    except Exception:
        refresh_token_value = ""

    _token_resp = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 28800,
        "user": {
            "id": uid,
            "username": username,
            "email": email,
            "role": role,
            "subscription_tier": subscription_tier,
            "is_owner": is_owner,
        },
    }
    if refresh_token_value:
        _token_resp["refresh_token"] = refresh_token_value
    return jsonify(_token_resp)
