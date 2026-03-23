"""Page routes for ARCHIE Chat module."""

from flask import render_template
from flask_login import login_required
from rbac import admin_required  # noqa: F401 — exported for ADR-045 pattern


def register_routes(bp, _admin_required):
    """Register page-rendering routes."""

    @bp.route("/")
    @login_required
    def index():
        # Blueprint has template_folder="templates", so path is relative
        return render_template("archie_chat.html")
