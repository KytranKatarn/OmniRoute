"""
Agent Academy — Dashboard + Navigation Routes
"""

import logging
from functools import wraps

from flask import render_template, jsonify, abort
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def admin_required(f):
    """Require admin access."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            abort(403)
        return f(*args, **kwargs)

    return decorated


from . import agent_academy_bp  # noqa: E402


@agent_academy_bp.route("/")
@admin_required
def index():
    """Agent Academy dashboard — single-page with 5 tabs."""
    return render_template("agent_academy.html")


@agent_academy_bp.route("/api/status")
@admin_required
def api_status():
    """Health check endpoint."""
    return jsonify({"status": "ok", "module": "agent_academy"})
