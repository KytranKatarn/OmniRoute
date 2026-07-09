"""
Auth blueprint for the standalone Media Hub — /login, /logout.
Imports users.authenticate + login_user to populate the Flask-Login session.
"""

from urllib.parse import urlparse, urljoin

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from users import authenticate, get_user_by_username, is_sso_only_account

auth_bp = Blueprint("auth", __name__)


def _safe_next(default):
    """Return the ?next= URL only if it points to the same host (prevents open redirect)."""
    target = request.args.get("next") or ""
    if not target:
        return default
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    if test.scheme in ("http", "https") and ref.netloc == test.netloc:
        return target
    return default


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next("/maven/discover"))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            error = "Username and password are required."
        else:
            user = authenticate(username, password)
            if user:
                login_user(user)
                return redirect(_safe_next("/maven/discover"))
            if is_sso_only_account(username):
                error = "This account uses Kytran sign-in. Use the 'Sign in with Kytran Empowerment' button above."
            else:
                error = "Invalid credentials."

    return render_template("login.html", error=error), (401 if error else 200)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/api/qa/auth", methods=["POST"])
def qa_auth():
    """Internal QA authentication — lets P.R.O.B.E.'s qa_spec_runner establish a
    Flask-Login session via the shared ARCHIE_QA_TOKEN (the media_hub 'claude'
    account is SSO-only, so the form-login fallback 401s).

    SECURITY (hardened per the 2026-07-09 review): the hmac ARCHIE_QA_TOKEN is the
    ONLY real gate. The internal-IP check is weak defence-in-depth ONLY — behind the
    published-port DNAT every caller appears as the docker gateway (an RFC1918
    address), so it does NOT bound who can call this; never rely on it. To cap the
    blast radius of a leaked token, the requested username is DELIBERATELY IGNORED
    and this endpoint always logs in a FIXED, NON-ADMIN QA account (QA_AUTH_USER,
    default 'qa_probe'). It therefore can never mint an admin session or impersonate
    a real user, and fails closed if that account is missing / inactive / admin.
    Only logs in an existing user — never creates one.

    Body: {token} -> {success, username} | error."""
    import hmac
    import ipaddress
    import os

    qa_token = os.environ.get("ARCHIE_QA_TOKEN", "")
    if not qa_token:
        return jsonify({"error": "QA auth disabled"}), 403
    ip = request.remote_addr or ""
    try:
        is_internal = ip in ("127.0.0.1", "::1") or ipaddress.ip_address(ip).is_private
    except ValueError:
        is_internal = False
    if not is_internal:  # weak defence-in-depth; the token below is the real gate
        return jsonify({"error": "QA auth only available from internal networks"}), 403
    data = request.get_json(silent=True) or {}
    if not hmac.compare_digest(str(data.get("token", "")), qa_token):
        return jsonify({"error": "Invalid QA token"}), 401
    # Fixed, non-admin QA identity — the requested username is intentionally NOT used,
    # so a leaked token can never escalate to admin or impersonate a real account.
    qa_user = os.environ.get("QA_AUTH_USER", "qa_probe")
    user = get_user_by_username(qa_user)
    if not user or user.is_admin:
        return jsonify({"error": "QA account unavailable"}), 403
    login_user(user, remember=True)
    return jsonify({"success": True, "username": user.username})
