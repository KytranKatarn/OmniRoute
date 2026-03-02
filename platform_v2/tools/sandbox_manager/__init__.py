"""Sandbox Manager — DEPRECATED.

Consolidated into Dev Pipeline (/tools/dev-pipeline#sandbox).
This stub provides redirects for bookmarks and old links.
"""

from flask import Blueprint, redirect

sandbox_manager_bp = Blueprint("sandbox_manager", __name__, url_prefix="/tools/sandbox-manager")


@sandbox_manager_bp.route("/")
def index():
    return redirect("/tools/dev-pipeline#sandbox", code=302)


@sandbox_manager_bp.route("/redirect-to-pipeline")
def redirect_to_pipeline():
    return redirect("/tools/dev-pipeline#sandbox", code=302)
