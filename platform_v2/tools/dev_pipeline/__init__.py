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
