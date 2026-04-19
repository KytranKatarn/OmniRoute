"""
Auth blueprint for the standalone Media Hub — /login, /logout.
Imports users.authenticate + login_user to populate the Flask-Login session.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from users import authenticate

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(request.args.get("next") or url_for("media_hub.index"))

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
                nxt = request.args.get("next") or url_for("media_hub.index")
                return redirect(nxt)
            error = "Invalid credentials."

    return render_template("login.html", error=error), (401 if error else 200)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))
