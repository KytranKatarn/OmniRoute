"""
User Profile Module
====================
Personal profile page for all authenticated users.
Shows profile info, accessible modules, and notifications.
"""

from flask import Blueprint

user_profile_bp = Blueprint("user_profile", __name__, url_prefix="/tools/my-profile")

from . import routes  # noqa: E402, F401
