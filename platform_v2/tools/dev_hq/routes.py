"""Dev HQ Routes - Admin Only, Hub Only"""

import os
from flask import render_template, abort
from flask_login import login_required, current_user
from . import dev_hq_bp


def admin_hub_only(f):
    """Decorator: require admin role + hub deployment mode."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        if os.getenv("DEPLOYMENT_MODE", "hub") == "business_node":
            abort(404)
        return f(*args, **kwargs)

    return decorated


@dev_hq_bp.route("/")
@login_required
@admin_hub_only
def index():
    """Dev HQ main page."""
    return render_template("dev_hq.html")
