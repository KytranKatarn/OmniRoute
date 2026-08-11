"""
Fitness Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

fitness_bp = Blueprint("fitness", __name__, url_prefix="/tools/fitness")

from . import routes  # noqa: E402, F401
