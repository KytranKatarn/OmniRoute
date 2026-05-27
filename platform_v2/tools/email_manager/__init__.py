"""
Email Manager Module
"""

from .routes import email_manager_bp, admin_required  # noqa: F401

# Access control: email_access_required opens user-facing routes to COLLABORATOR
# (EMAIL_INBOX_VIEW permission) in addition to admins (ADMIN_ACCESS permission).
# Admin-only routes (provisioning, sync, rules) keep the plain admin_required.
from .access_control import email_access_required  # noqa: F401, E402

# Import IMAP routes to register them on the same blueprint
from . import imap_routes  # noqa: F401, E402

# Overview tab routes — ADMIN ONLY until T3279 injects get_visible_mailbox_ids() filter
from .overview_routes import register_overview_routes  # noqa: F401, E402

register_overview_routes(email_manager_bp, admin_required)

# Agents tab routes (mailbox list + provisioning) — ADMIN ONLY
from .mailbox_routes import register_mailbox_routes  # noqa: F401, E402

register_mailbox_routes(email_manager_bp, admin_required)

# Inbox tab routes — ADMIN ONLY until T3280 injects get_visible_mailbox_ids() filter
from .inbox_routes import register_inbox_routes  # noqa: F401, E402

register_inbox_routes(email_manager_bp, admin_required)

# Sent tab routes — ADMIN ONLY until T3281 injects get_visible_mailbox_ids() filter
from .sent_routes import register_sent_routes  # noqa: F401, E402

register_sent_routes(email_manager_bp, admin_required)

# Compose/Send routes — ADMIN ONLY until T3282 audits From-mailbox ownership check
from .compose_routes import register_compose_routes  # noqa: F401, E402

register_compose_routes(email_manager_bp, admin_required)

# Email HQ routes — ADMIN ONLY until T3283 injects get_visible_mailbox_ids() filter
from .hq_routes import register_hq_routes  # noqa: F401, E402

register_hq_routes(email_manager_bp, admin_required)

# Email messages API (three-panel layout — sidebar, list, body, actions)
# User-facing; queries are filtered by get_visible_mailbox_ids() inside.
from .messages_routes import register_email_messages_routes  # noqa: F401, E402

register_email_messages_routes(email_manager_bp, email_access_required)

# Email rules engine (Phase 6) — ADMIN ONLY (rule management)
from .rules_routes import register_email_rules_routes  # noqa: F401, E402

register_email_rules_routes(email_manager_bp, admin_required)
