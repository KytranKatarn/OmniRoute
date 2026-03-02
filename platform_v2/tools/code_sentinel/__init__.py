"""Code Sentinel — DEPRECATED.

Consolidated into Dev Pipeline (/tools/dev-pipeline#scan).
This stub provides redirects for bookmarks and old links.
"""

from flask import Blueprint, redirect

code_sentinel_bp = Blueprint("code_sentinel", __name__, url_prefix="/tools/code_sentinel")


@code_sentinel_bp.route("/")
def index():
    return redirect("/tools/dev-pipeline#scan", code=302)


@code_sentinel_bp.route("/redirect-to-pipeline")
def redirect_to_pipeline():
    return redirect("/tools/dev-pipeline#scan", code=302)
