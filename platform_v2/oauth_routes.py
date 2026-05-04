"""
OAuth Routes - Google OAuth 2.0 Authentication
Provides social login functionality with Google Sign-In

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""

from flask import Blueprint, redirect, url_for, flash, current_app, session
from flask_login import login_user, current_user
from authlib.integrations.flask_client import OAuth
from app import User, create_user_session
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
from werkzeug.security import generate_password_hash

# Create blueprint
oauth_bp = Blueprint("oauth", __name__, url_prefix="/auth")

# Initialize OAuth
oauth = OAuth()


def init_oauth(app):
    """Initialize OAuth with Flask app"""
    oauth.init_app(app)

    # Register Google OAuth
    oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# GOOGLE OAUTH ROUTES
# ============================================================================


@oauth_bp.route("/google/login")
def google_login():
    """Initiate Google OAuth flow"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    # Always use the login callback URL — GOOGLE_REDIRECT_URI is for Work Suite OAuth
    redirect_uri = url_for("oauth.google_callback", _external=True)

    return oauth.google.authorize_redirect(redirect_uri)


@oauth_bp.route("/google/callback")
def google_callback():
    """Handle Google OAuth callback"""
    try:
        # Get access token
        token = oauth.google.authorize_access_token()

        # Get user info from Google
        user_info = token.get("userinfo")
        if not user_info:
            flash("Failed to get user information from Google", "error")
            return redirect(url_for("login"))

        # Extract user data
        google_id = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        if not google_id or not email:
            flash("Incomplete user information from Google", "error")
            return redirect(url_for("login"))

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if user exists by google_id
        cur.execute(
            """
            SELECT * FROM users WHERE google_id = %s
        """,
            (google_id,),
        )
        user_data = cur.fetchone()

        # If not found by google_id, check by email (honors verified alternate_emails)
        if not user_data:
            from services.account_link_service import find_user_by_any_email  # noqa: PLC0415

            user_data = find_user_by_any_email(email)

            if user_data:
                # Link existing account with Google
                cur.execute(
                    """
                    UPDATE users
                    SET google_id = %s,
                        oauth_provider = 'google',
                        oauth_picture = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                """,
                    (google_id, picture, user_data["id"]),
                )
                user_data = cur.fetchone()
                conn.commit()
                flash("Your account has been linked with Google", "success")

        # If user still doesn't exist, create new account
        if not user_data:
            # Generate username from email
            username = email.split("@")[0]
            base_username = username
            counter = 1

            # Ensure unique username
            while True:
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if not cur.fetchone():
                    break
                username = f"{base_username}{counter}"
                counter += 1

            # Create new user with free subscription
            cur.execute(
                """
                INSERT INTO users (
                    username, email, password_hash, role,
                    google_id, oauth_provider, oauth_picture,
                    subscription_tier, subscription_status,
                    is_active, email_verified
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """,
                (
                    username,
                    email,
                    generate_password_hash(os.urandom(32).hex()),  # Random password (Werkzeug scrypt)
                    "user",
                    google_id,
                    "google",
                    picture,
                    "free",
                    "active",
                    True,
                    True,  # Email verified since it comes from Google
                ),
            )
            user_data = cur.fetchone()
            conn.commit()

            flash(f"Welcome {name}! Your account has been created.", "success")
        else:
            flash(f"Welcome back {name}!", "success")

        # Check if 2FA is enabled for this user
        if user_data.get("totp_enabled", False):
            session["pending_2fa_user_id"] = user_data["id"]
            session["pending_2fa_username"] = user_data["username"]
            cur.close()
            conn.close()
            return redirect(url_for("verify_2fa"))

        cur.close()
        conn.close()

        # Create Flask-Login User object
        user = User(
            id=user_data["id"],
            username=user_data["username"],
            email=user_data["email"],
            role=user_data["role"],
            is_admin=user_data.get("is_admin", False),
            is_super_admin=user_data.get("is_super_admin", False),
            subscription_tier=user_data.get("subscription_tier", "free"),
            subscription_expires_at=user_data.get("subscription_expires_at"),
        )

        # Log in the user
        login_user(user, remember=True)
        create_user_session(user_data["id"])

        # Redirect to dashboard
        return redirect(url_for("dashboard"))

    except Exception as e:
        current_app.logger.error(f"OAuth callback error: {e}")
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for("login"))


# ============================================================================
# ACCOUNT LINKING (for already logged-in users)
# ============================================================================


@oauth_bp.route("/link/google")
def link_google():
    """Link existing account with Google"""
    if not current_user.is_authenticated:
        flash("Please log in first to link your account", "error")
        return redirect(url_for("login"))

    redirect_uri = url_for("oauth.link_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@oauth_bp.route("/link/google/callback")
def link_google_callback():
    """Handle Google account linking callback"""
    if not current_user.is_authenticated:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("login"))

    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get("userinfo")

        if not user_info:
            flash("Failed to get user information from Google", "error")
            return redirect(url_for("account_settings"))

        google_id = user_info.get("sub")
        picture = user_info.get("picture")

        conn = get_db_connection()
        cur = conn.cursor()

        # Update current user's account
        cur.execute(
            """
            UPDATE users
            SET google_id = %s,
                oauth_provider = 'google',
                oauth_picture = %s,
                updated_at = NOW()
            WHERE id = %s
        """,
            (google_id, picture, current_user.id),
        )

        conn.commit()
        cur.close()
        conn.close()

        flash("Your account has been successfully linked with Google", "success")
        return redirect(url_for("account_settings"))

    except Exception as e:
        current_app.logger.error(f"Account linking error: {e}")
        flash("Failed to link account. Please try again.", "error")
        return redirect(url_for("account_settings"))


# ============================================================================
# ACCOUNT UNLINKING
# ============================================================================


@oauth_bp.route("/unlink/google", methods=["POST"])
def unlink_google():
    """Unlink Google from account"""
    if not current_user.is_authenticated:
        flash("Please log in first", "error")
        return redirect(url_for("login"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Check if user has a password (can't unlink if OAuth is only login method)
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (current_user.id,))
        result = cur.fetchone()

        if not result or not result[0]:
            flash("Cannot unlink Google - please set a password first", "error")
            return redirect(url_for("account_settings"))

        # Unlink Google
        cur.execute(
            """
            UPDATE users
            SET google_id = NULL,
                oauth_provider = NULL,
                oauth_picture = NULL,
                updated_at = NOW()
            WHERE id = %s
        """,
            (current_user.id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        flash("Google has been unlinked from your account", "success")
        return redirect(url_for("account_settings"))

    except Exception as e:
        current_app.logger.error(f"Account unlinking error: {e}")
        flash("Failed to unlink account. Please try again.", "error")
        return redirect(url_for("account_settings"))
