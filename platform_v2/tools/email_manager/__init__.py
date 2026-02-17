"""
Email Manager Module
"""

from .routes import email_manager_bp  # noqa: F401

# Import IMAP routes to register them on the same blueprint
from . import imap_routes  # noqa: F401, E402
