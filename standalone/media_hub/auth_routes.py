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
    Flask-Login session via the shared ARCHIE_QA_TOKEN instead of a password/SSO
    flow (the media_hub 'claude' account is SSO-only, so the form-login fallback
    401s). Triple-gated: env token must be set (403), caller must be on an internal
    /RFC1918 network (403 — behind the published-port DNAT every legit caller is the
    docker gateway), and the token must match via constant-time compare (401). Only
    logs in an EXISTING active user — never creates one. Mirrors KSO
    (kytran_system_operations/auth.py qa_auth) + KB #270283/#270289.

    Body: {token, username?} -> {success, username} | error."""
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
    if not is_internal:
        return jsonify({"error": "QA auth only available from internal networks"}), 403
    data = request.get_json(silent=True) or {}
    if not hmac.compare_digest(str(data.get("token", "")), qa_token):
        return jsonify({"error": "Invalid QA token"}), 401
    username = (data.get("username") or "probe").strip()
    user = get_user_by_username(username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    login_user(user, remember=True)
    return jsonify({"success": True, "username": user.username})
