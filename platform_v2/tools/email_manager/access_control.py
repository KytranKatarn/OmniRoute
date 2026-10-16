"""Email HQ — access control helpers.

Provides:
  get_visible_mailbox_ids(user) → list[int] | None
      None  = unrestricted (admin path — no WHERE IN filter applied)
      list  = own/owned business mailboxes plus explicit grants

  email_access_required
      Drop-in replacement for admin_required on user-facing email routes.
      Passes for ADMIN/SUPER_ADMIN (ADMIN_ACCESS) OR COLLABORATOR with
      EMAIL_INBOX_VIEW permission.
"""

from __future__ import annotations

import logging

from database import get_db_cursor
from rbac import Permission, require_any_permission, has_permission

logger = logging.getLogger(__name__)


def _is_admin(user) -> bool:
    """True when the user should see all mailboxes with no filter.

    Use the same effective permission as the route gate. A raw role string
    must not bypass RBAC and silently reveal every mailbox.
    """
    return has_permission(Permission.ADMIN_ACCESS, user)


def get_visible_mailbox_ids(user) -> list[int] | None:
    """Return the set of mailbox IDs the given user is allowed to access.

    Returns:
        None  — user is an admin; caller should apply NO mailbox filter.
        list  — caller must add ``AND mailbox_id = ANY(%s)`` to all queries.
                May be empty. A shared department is NOT mailbox ownership.
    """
    if _is_admin(user):
        return None  # fast path — no SQL overhead for admins

    ids: set[int] = set()

    try:
        with get_db_cursor() as (conn, cur):
            # Resolve through Account Center's stored user, never a request-
            # supplied email/department. Personal mailbox -> stable agent_id
            # -> specifically owned business boxes. Unassigned boxes stay hidden.
            cur.execute(
                """SELECT DISTINCT mb.id
                   FROM users u
                   JOIN email_mailboxes own ON lower(own.address) = lower(u.email)
                       AND own.mailbox_type = 'human_agent' AND own.active = TRUE
                   JOIN email_mailboxes mb ON mb.active = TRUE AND
                       (mb.id = own.id OR (mb.mailbox_type = 'business'
                           AND mb.owner_agent_id = own.owner_agent_id))
                   WHERE u.id = %s AND u.is_active = TRUE""",
                (user.id,),
            )
            ids.update(row["id"] for row in cur.fetchall())

            # Explicit grants remain authoritative; inactive boxes never appear.
            cur.execute(
                "SELECT g.mailbox_id FROM user_mailbox_grants g "
                "JOIN email_mailboxes mb ON mb.id = g.mailbox_id "
                "JOIN users u ON u.id = g.user_id "
                "WHERE g.user_id = %s AND mb.active = TRUE AND u.is_active = TRUE",
                (user.id,),
            )
            ids.update(row["mailbox_id"] for row in cur.fetchall())
    except Exception:
        logger.exception("get_visible_mailbox_ids failed for user %s", getattr(user, "id", "?"))
        return []  # fail-closed: show nothing rather than everything

    return sorted(ids)


# Drop-in replacement for admin_required on user-facing Email HQ routes.
# Allows ADMIN_ACCESS (admins) OR EMAIL_INBOX_VIEW (human agents with COLLABORATOR role).
email_access_required = require_any_permission(
    Permission.ADMIN_ACCESS,
    Permission.EMAIL_INBOX_VIEW,
)
