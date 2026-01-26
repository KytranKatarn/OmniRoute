"""
Project Builder Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

project_builder_bp = Blueprint('project_builder', __name__, url_prefix='/tools/project-builder')

from . import routes
