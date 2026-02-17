"""
DOC Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

doc_bp = Blueprint("doc", __name__, url_prefix="/tools/doc")

from . import routes
