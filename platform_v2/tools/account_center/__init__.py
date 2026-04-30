"""
Account Center Module
=====================
Unified interface for managing accounts, permissions, subscriptions, and activity.
"""

from flask import Blueprint

account_center_bp = Blueprint("account_center", __name__, url_prefix="/tools/account-center")

from . import routes
from .notify_routes import register_notify_routes

register_notify_routes(account_center_bp)
