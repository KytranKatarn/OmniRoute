"""
Invoicing Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

invoicing_bp = Blueprint('invoicing', __name__, url_prefix='/tools/invoicing')

from . import routes
