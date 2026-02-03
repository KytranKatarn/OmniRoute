"""
Analytics Dashboard Module - DEPRECATED 2026-02-03
Status: Merged into CRM module at /tools/crm/analytics
"""

from flask import Blueprint

analytics_bp = Blueprint("analytics", __name__, url_prefix="/tools/analytics-dashboard")
