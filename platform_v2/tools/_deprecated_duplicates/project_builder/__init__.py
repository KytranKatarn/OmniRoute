"""
Project Builder Module (Placeholder)
Status: Coming Soon
DEPRECATED 2026-02-03: Using project_manager instead
"""

from flask import Blueprint

from . import routes  # noqa: E402, F401

project_builder_bp = Blueprint("project_builder", __name__, url_prefix="/tools/project-builder")
