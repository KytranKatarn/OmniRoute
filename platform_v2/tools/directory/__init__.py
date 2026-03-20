"""
A.R.C.H.I.E. EMPLOYEE DIRECTORY Module
=======================================
Corporate team page with org chart, profiles, and live agent chat.
"""

from .routes import bp as directory_bp
from flask_login import login_required  # noqa: F401
from rbac import require_permission, Permission

admin_required = require_permission(Permission.ADMIN_ACCESS)

from .chat_routes import register_chat_routes

register_chat_routes(directory_bp, admin_required)

__all__ = ["directory_bp"]
