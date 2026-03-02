"""Dev Pipeline — main routes and admin_required decorator."""

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

from rbac import Permission, has_permission, audit_log

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


from . import dev_pipeline_bp  # noqa: E402


@dev_pipeline_bp.route("/")
@login_required
@admin_required
def index():
    """Dev Pipeline main page — renders 4-tab LCARS interface."""
    return render_template("tools/dev_pipeline.html")


@dev_pipeline_bp.route("/api/status")
@login_required
def status():
    """Health check endpoint."""
    return jsonify(
        {
            "module": "dev_pipeline",
            "status": "active",
            "healthy": True,
        }
    )
