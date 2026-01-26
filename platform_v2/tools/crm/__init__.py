"""
CRM Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

crm_bp = Blueprint('crm', __name__, url_prefix='/tools/crm')

from . import routes
