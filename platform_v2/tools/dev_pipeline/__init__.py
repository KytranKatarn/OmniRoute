"""
Dev Pipeline Module — Unified Development Tools

Consolidates Code Sentinel + Improvements Lab + Sandbox Manager into
a single module with 4 tabs: Scan, Proposals, Sandbox, Deploy.

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

dev_pipeline_bp = Blueprint(
    "dev_pipeline",
    __name__,
    url_prefix="/tools/dev-pipeline",
    template_folder="templates",
)

from . import routes  # noqa: F401, E402
from .routes import admin_required  # noqa: E402
from .scan_routes import register_scan_routes  # noqa: E402
from .proposal_routes import register_proposal_routes  # noqa: E402

# Register scan routes (Code Sentinel proxy)
register_scan_routes(dev_pipeline_bp, admin_required)

# Register proposal routes (Improvements Lab proxy)
register_proposal_routes(dev_pipeline_bp, admin_required)
