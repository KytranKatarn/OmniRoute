"""Improvements Lab — DEPRECATED.

Consolidated into Dev Pipeline (/tools/dev-pipeline#proposals).
This stub provides redirects for bookmarks and old links.
"""

from flask import Blueprint, redirect

improvements_bp = Blueprint("improvements", __name__, url_prefix="/tools/improvements-lab")


@improvements_bp.route("/")
def index():
    return redirect("/tools/dev-pipeline#proposals", code=302)


@improvements_bp.route("/redirect-to-pipeline")
def redirect_to_pipeline():
    return redirect("/tools/dev-pipeline#proposals", code=302)
