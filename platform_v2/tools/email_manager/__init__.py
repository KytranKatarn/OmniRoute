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

# Overview tab routes — scoped by get_visible_mailbox_ids() (T3279)
from .overview_routes import register_overview_routes  # noqa: F401, E402

register_overview_routes(email_manager_bp, email_access_required)

# Agents tab routes (mailbox list + provisioning) — ADMIN ONLY
from .mailbox_routes import register_mailbox_routes  # noqa: F401, E402

register_mailbox_routes(email_manager_bp, admin_required)

# Inbox tab routes — scoped by get_visible_mailbox_ids() (T3280)
from .inbox_routes import register_inbox_routes  # noqa: F401, E402

register_inbox_routes(email_manager_bp, email_access_required)

# Sent tab routes — scoped by get_visible_mailbox_ids() (T3281)
from .sent_routes import register_sent_routes  # noqa: F401, E402

register_sent_routes(email_manager_bp, email_access_required)

# Compose/Send routes — From-mailbox ownership enforced (T3282)
from .compose_routes import register_compose_routes  # noqa: F401, E402

register_compose_routes(email_manager_bp, email_access_required)

# Email HQ routes — scoped by get_visible_mailbox_ids() (T3283)
# real_admin_required keeps assign/oversight-scan/oversight-tickets strictly admin-only
from .hq_routes import register_hq_routes  # noqa: F401, E402

register_hq_routes(email_manager_bp, email_access_required, admin_required)

# Email messages API (three-panel layout — sidebar, list, body, actions)
# User-facing; queries are filtered by get_visible_mailbox_ids() inside.
from .messages_routes import register_email_messages_routes  # noqa: F401, E402

register_email_messages_routes(email_manager_bp, email_access_required)

# Email rules engine (Phase 6) — ADMIN ONLY (rule management)
from .rules_routes import register_email_rules_routes  # noqa: F401, E402

register_email_rules_routes(email_manager_bp, admin_required)

# SLA dashboard — response-time metrics per mailbox (T3282)
from .sla_routes import register_sla_routes  # noqa: F401, E402

register_sla_routes(email_manager_bp, email_access_required)

# Human-agent reply SLA — per-agent reply-time metrics from email_reply_events (#3282)
from .human_sla_routes import register_human_sla_routes  # noqa: F401, E402

register_human_sla_routes(email_manager_bp, email_access_required)

# SSE stream — real-time new-mail push (T3279)
from .sync_routes import register_sync_routes  # noqa: F401, E402

register_sync_routes(email_manager_bp, email_access_required)

# Smart Inbox settings (Slice 5: notify/digest/quiet-hours/digest-time) — ADMIN ONLY
from .settings_routes import register_settings_routes  # noqa: F401, E402

register_settings_routes(email_manager_bp, admin_required)
