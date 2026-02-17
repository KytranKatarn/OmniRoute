"""
Therapy Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

therapy_bp = Blueprint("therapy", __name__, url_prefix="/tools/therapy")

from . import routes
