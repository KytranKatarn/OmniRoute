"""
Account Center Module
=====================
Unified interface for managing accounts, permissions, subscriptions, and activity.
"""

from flask import Blueprint

account_center_bp = Blueprint("account_center", __name__, url_prefix="/tools/account-center")

from . import routes
from .notify_routes import register_notify_routes
from .email_link_routes import register_email_link_routes

register_notify_routes(account_center_bp)
register_email_link_routes(account_center_bp)

from .routes import admin_required
from .demo_routes import register_demo_routes

register_demo_routes(account_center_bp, admin_required)
