"""
CRM Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint
from rbac import admin_required

crm_bp = Blueprint("crm", __name__, url_prefix="/tools/crm")

from . import routes

# Billing tab routes
from tools.crm.billing_routes import register_billing_routes

register_billing_routes(crm_bp, admin_required)

# Billing webhook handlers
from tools.crm.billing_handlers import register_crm_billing_handlers

register_crm_billing_handlers()
