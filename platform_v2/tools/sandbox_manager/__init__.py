"""
Sandbox Manager Module
Per-module sandbox testing environments for safe code deployment

DEPRECATED: UI consolidated into Dev Pipeline module (/tools/dev-pipeline#sandbox).
API routes remain active for proxy layer compatibility.
"""

from flask import Blueprint

sandbox_manager_bp = Blueprint("sandbox_manager", __name__, url_prefix="/tools/sandbox-manager")

from . import routes  # noqa: F401, E402

# Redirect index to Dev Pipeline Sandbox tab
from flask import redirect  # noqa: E402


@sandbox_manager_bp.route("/redirect-to-pipeline")
def redirect_to_pipeline():
    return redirect("/tools/dev-pipeline#sandbox", code=302)
