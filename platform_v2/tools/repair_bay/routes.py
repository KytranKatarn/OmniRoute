"""Repair Bay — main routes and admin_required decorator."""

import logging
from functools import wraps

from flask import (
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    flash,
)
from flask_login import current_user, login_required

from rbac import Permission, has_permission
from logging_config import audit_log

logger = logging.getLogger(__name__)


def admin_required(f):
    """Decorator to require admin access."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permission.ADMIN_ACCESS, current_user):
            audit_log(
                "ADMIN_ACCESS_DENIED",
                {
                    "route": request.endpoint,
                    "user_id": (current_user.id if current_user.is_authenticated else None),
                },
                success=False,
            )
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


from . import repair_bay_bp  # noqa: E402


@repair_bay_bp.route("/")
@login_required
@admin_required
def index():
    """Repair Bay main page — renders 4-tab LCARS interface."""
    return render_template("tools/repair_bay.html")


@repair_bay_bp.route("/api/status")
@login_required
def status():
    """Health check endpoint."""
    return jsonify(
        {
            "module": "repair_bay",
            "status": "active",
            "healthy": True,
        }
    )
