"""
Improvements Lab - Standalone Module Routes
============================================
Renders the Improvements Lab standalone dashboard.
API endpoints remain in admin/routes.py for compatibility.
"""

from flask import Blueprint, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps

improvements_lab_bp = Blueprint("improvements_lab", __name__, url_prefix="/tools/improvements-lab")


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not getattr(current_user, "is_admin", False):
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


@improvements_lab_bp.route("/")
@login_required
@admin_required
def index():
    """DEPRECATED: Redirect to Dev Pipeline Proposals tab."""
    return redirect("/tools/dev-pipeline#proposals", code=302)
