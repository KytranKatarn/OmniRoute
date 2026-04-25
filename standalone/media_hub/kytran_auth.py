"""Kytran Auth SDK — "Sign in with Kytran" OAuth client for Flask apps.

Usage:
    from kytran_auth import KytranAuth

    kytran_auth = KytranAuth()
    kytran_auth.init_app(app)

Env vars required:
    KYTRAN_CLIENT_ID       — OAuth client ID (e.g., "kso")
    KYTRAN_CLIENT_SECRET   — OAuth client secret
    KYTRAN_AUTH_URL        — ARCHIE hub URL (e.g., "http://192.168.1.200:3000")
    KYTRAN_REDIRECT_URI    — Callback URL for this product
"""

import base64
import hashlib
import os
import secrets
from functools import wraps

import requests
from flask import flash, redirect, request, session, url_for, jsonify
from flask_login import current_user as _flask_login_current_user


def _login_url():
    """Return the login URL, falling back to /login if auth.login isn't registered."""
    try:
        return url_for("auth.login")
    except Exception:
        return "/login"


class KytranAuth:
    def __init__(self, app=None):
        self.client_id = None
        self.client_secret = None
        self.auth_url = None
        self.redirect_uri = None
        # Strict by default: block login when client_id is missing from the
        # user's entitlements. Media Hub opts out (family access) by setting
        # KYTRAN_AUTH_ENFORCE_ENTITLEMENT=false — policy moves into the
        # on_login callback instead.
        self.enforce_entitlement = True
        self.app = None
        self._on_login = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Configure OAuth settings and register auth routes."""
        self.app = app
        self.client_id = app.config.get("KYTRAN_CLIENT_ID") or os.environ.get("KYTRAN_CLIENT_ID", "")
        self.client_secret = app.config.get("KYTRAN_CLIENT_SECRET") or os.environ.get("KYTRAN_CLIENT_SECRET", "")
        self.auth_url = app.config.get("KYTRAN_AUTH_URL") or os.environ.get("KYTRAN_AUTH_URL", "http://192.168.1.200:3000")
        self.redirect_uri = app.config.get("KYTRAN_REDIRECT_URI") or os.environ.get("KYTRAN_REDIRECT_URI", "")
        self.enforce_entitlement = (
            os.environ.get("KYTRAN_AUTH_ENFORCE_ENTITLEMENT", "true").lower() != "false"
        )

        self._register_routes(app)

    def _register_routes(self, app):
        """Register /auth/kytran/login and /auth/kytran/callback routes."""

        sdk = self

        @app.route("/auth/kytran/login")
        def kytran_login():
            state = secrets.token_urlsafe(32)
            session["oauth_state"] = state
            # Validate and store next URL — reject cross-origin targets (open redirect)
            from urllib.parse import urlparse, urljoin as _urljoin
            _raw_next = request.args.get("next") or "/"
            _ref = urlparse(request.host_url)
            _test = urlparse(_urljoin(request.host_url, _raw_next))
            session["oauth_next"] = (
                _raw_next
                if _test.scheme in ("http", "https") and _ref.netloc == _test.netloc
                else "/"
            )

            # PKCE — generate code_verifier and S256 code_challenge
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(code_verifier.encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            session["oauth_code_verifier"] = code_verifier

            authorize_url = (
                f"{sdk.auth_url}/oauth/authorize"
                f"?client_id={sdk.client_id}"
                f"&redirect_uri={sdk.redirect_uri}"
                f"&response_type=code"
                f"&state={state}"
                f"&code_challenge={code_challenge}"
                f"&code_challenge_method=S256"
            )
            return redirect(authorize_url)

        @app.route("/auth/kytran/callback")
        def kytran_callback():
            state = request.args.get("state")
            if state != session.pop("oauth_state", None):
                flash(
                    "Sign-in failed: your session expired mid-flow. Please try again.",
                    "error",
                )
                return redirect(_login_url())

            code = request.args.get("code")
            if not code:
                error = request.args.get("error", "unknown")
                flash(f"Sign-in was not completed: {error}.", "error")
                return redirect(_login_url())

            code_verifier = session.pop("oauth_code_verifier", None)
            token_payload = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": sdk.client_id,
                "client_secret": sdk.client_secret,
                "redirect_uri": sdk.redirect_uri,
            }
            if code_verifier:
                token_payload["code_verifier"] = code_verifier

            try:
                token_resp = requests.post(
                    f"{sdk.auth_url}/oauth/token",
                    data=token_payload,
                    timeout=10,
                )
                if token_resp.status_code != 200:
                    flash(
                        "Sign-in failed: could not complete token exchange. Please try again.",
                        "error",
                    )
                    return redirect(_login_url())
                token_data = token_resp.json()
            except Exception:
                flash("Sign-in failed: network error during token exchange.", "error")
                return redirect(_login_url())

            access_token = token_data.get("access_token")
            if not access_token:
                flash("Sign-in failed: no access token received. Please try again.", "error")
                return redirect(_login_url())

            try:
                userinfo_resp = requests.get(
                    f"{sdk.auth_url}/oauth/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if userinfo_resp.status_code != 200:
                    flash(
                        "Sign-in failed: could not retrieve your profile. Please try again.",
                        "error",
                    )
                    return redirect(_login_url())
                userinfo = userinfo_resp.json()
            except Exception:
                flash("Sign-in failed: network error fetching profile.", "error")
                return redirect(_login_url())

            entitlements = userinfo.get("entitlements", [])
            if sdk.enforce_entitlement and sdk.client_id not in entitlements:
                flash(
                    f"Access not enabled for this product. "
                    f"Your subscriptions: {', '.join(entitlements) or 'none'}. "
                    f"Manage at {sdk.auth_url}.",
                    "error",
                )
                return redirect(_login_url())

            session["kytran_user"] = {
                "sub": userinfo.get("sub"),
                "username": userinfo.get("username"),
                "email": userinfo.get("email"),
                "name": userinfo.get("name"),
                "role": userinfo.get("role"),
                "entitlements": entitlements,
                "product_tiers": userinfo.get("product_tiers", {}),
                "access_token": access_token,
            }

            if sdk._on_login:
                sdk._on_login(session["kytran_user"])

            # Verify Flask-Login session was actually established.
            # _on_login may silently fail (DB error, inactive account) and skip
            # login_user() — if so, redirecting would bounce the user back to
            # login with no explanation, creating a confusing loop.
            if not _flask_login_current_user.is_authenticated:
                session.pop("kytran_user", None)
                flash(
                    "Sign-in failed: your Kytran account could not be linked "
                    "to a Media Hub profile. Please contact admin.",
                    "error",
                )
                return redirect(_login_url())

            next_url = session.pop("oauth_next", "/")
            return redirect(next_url)

    def on_login(self, callback):
        """Register a callback for when SSO login succeeds."""
        self._on_login = callback
        return callback

    def login_required(self, f):
        """Decorator: check session for Kytran SSO user, redirect if not found."""
        @wraps(f)
        def decorated(*args, **kwargs):
            if "kytran_user" not in session:
                return redirect(url_for("kytran_login", next=request.url))
            return f(*args, **kwargs)
        return decorated

    def get_current_user(self):
        """Return current Kytran user from session, or None."""
        return session.get("kytran_user")

    def has_entitlement(self, entitlement):
        """Check if current user has a specific product entitlement."""
        user = self.get_current_user()
        if not user:
            return False
        return entitlement in user.get("entitlements", [])
