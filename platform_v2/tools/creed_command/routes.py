"""C.R.E.E.D. Command — main routes and admin_required decorator (scaffold, P0)."""

import logging
from functools import wraps

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from rbac import Permission, has_permission
from logging_config import audit_log

logger = logging.getLogger(__name__)


def admin_required(f):
    """Decorator to require admin access (matches the platform module pattern)."""

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


from . import creed_command_bp  # noqa: E402


@creed_command_bp.route("/")
@login_required
@admin_required
def creed_command_home():
    """C.R.E.E.D. Command Center — E.T.H.O.S. work dashboard (tabbed shell)."""
    return render_template("creed_command.html")


@creed_command_bp.route("/api/status")
def creed_command_status():
    """Unauthenticated health/status endpoint (used by the module registry)."""
    return jsonify(
        {
            "healthy": True,
            "module": "creed_command",
            "agent": "E.T.H.O.S.",
            "phase": "P0 scaffold",
        }
    )
