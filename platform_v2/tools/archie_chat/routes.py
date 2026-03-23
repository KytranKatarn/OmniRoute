"""Page routes for ARCHIE Chat module."""

from functools import wraps
from flask import render_template, request, redirect, url_for
from flask_login import login_required, current_user


def admin_required(f):
    """Decorator to require admin access (local definition, matches other modules)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def register_routes(bp, _admin_required):
    """Register page-rendering routes."""

    @bp.route("/")
    @login_required
    def index():
        # Blueprint has template_folder="templates", so path is relative
        return render_template("archie_chat.html")
