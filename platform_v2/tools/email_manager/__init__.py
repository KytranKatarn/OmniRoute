"""
Email Manager Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

email_manager_bp = Blueprint("email_manager", __name__, url_prefix="/tools/email-manager")

from . import routes  # noqa: F401, E402
from . import imap_routes  # noqa: F401, E402 - Email Intelligence IMAP routes
