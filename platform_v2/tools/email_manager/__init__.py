"""
Email Manager Module
"""

from .routes import email_manager_bp, admin_required  # noqa: F401

# Import IMAP routes to register them on the same blueprint
from . import imap_routes  # noqa: F401, E402

# Overview tab routes
from .overview_routes import register_overview_routes  # noqa: F401, E402

register_overview_routes(email_manager_bp, admin_required)

# Agents tab routes (mailbox list + provisioning)
from .mailbox_routes import register_mailbox_routes  # noqa: F401, E402

register_mailbox_routes(email_manager_bp, admin_required)

# Inbox tab routes
from .inbox_routes import register_inbox_routes  # noqa: F401, E402

register_inbox_routes(email_manager_bp, admin_required)

# Sent tab routes
from .sent_routes import register_sent_routes  # noqa: F401, E402

register_sent_routes(email_manager_bp, admin_required)

# Compose/Send routes
from .compose_routes import register_compose_routes  # noqa: F401, E402

register_compose_routes(email_manager_bp, admin_required)
