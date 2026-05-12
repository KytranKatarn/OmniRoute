"""
Auth blueprint for the standalone Media Hub — /login, /logout.
Imports users.authenticate + login_user to populate the Flask-Login session.
"""

from urllib.parse import urlparse, urljoin

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from users import authenticate, is_sso_only_account

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
