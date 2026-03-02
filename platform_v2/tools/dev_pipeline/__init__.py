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
from .sandbox_routes import register_sandbox_routes  # noqa: E402
from .deploy_routes import register_deploy_routes  # noqa: E402
from .station_routes import register_station_routes  # noqa: E402

# Register all route groups (service layer — no more proxy imports)
register_scan_routes(dev_pipeline_bp, admin_required)
register_proposal_routes(dev_pipeline_bp, admin_required)
register_sandbox_routes(dev_pipeline_bp, admin_required)
register_deploy_routes(dev_pipeline_bp, admin_required)
register_station_routes(dev_pipeline_bp, admin_required)
