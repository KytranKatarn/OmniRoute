"""
Email Intelligence IMAP Routes — Inbox, Settings, Analysis, Drafts

Registered on the existing email_manager_bp blueprint.

Compatibility shim: the route implementations were split into three modules
so each stays under 600 lines. Importing this module registers all of them and
re-exports the public helpers for backwards compatibility.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

# Importing each submodule runs its @email_manager_bp.route decorators and
# registers the endpoints on the shared blueprint.
from .routes import email_manager_bp as email_manager_bp

from .imap_settings_routes import (  # noqa: F401
    get_db,
    get_imap_settings,
    create_imap_setting,
    update_imap_setting,
    delete_imap_setting,
    test_imap_setting,
    test_smtp_setting,
    get_smtp_accounts,
)
from .imap_inbox_routes import (  # noqa: F401
    get_inbox,
    get_inbox_stats,
    batch_analyze,
    bulk_action,
    get_email_detail,
    get_email_thread,
    toggle_star,
    toggle_read,
    archive_email,
    delete_email,
)
from .imap_actions_routes import (  # noqa: F401
    analyze_email,
    generate_draft,
    file_to_kb,
    check_inbox_now,
    get_drafts,
    update_draft,
    send_draft,
)
