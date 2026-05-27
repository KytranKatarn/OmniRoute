"""Email HQ — access control helpers.

Provides:
  get_visible_mailbox_ids(user) → list[int] | None
      None  = unrestricted (admin path — no WHERE IN filter applied)
      list  = mailbox IDs the user may access (dept + explicit grants)

  email_access_required
      Drop-in replacement for admin_required on user-facing email routes.
      Passes for ADMIN/SUPER_ADMIN (ADMIN_ACCESS) OR COLLABORATOR with
      EMAIL_INBOX_VIEW permission.
"""

from __future__ import annotations

import logging

from database import get_db_cursor
from rbac import Permission, require_any_permission

logger = logging.getLogger(__name__)


def _is_admin(user) -> bool:
    """True when the user should see all mailboxes with no filter.

    Checks the User object's boolean flags first (most reliable), then falls
    back to the raw role string for any future role naming changes.
    DB stores roles as lowercase ('admin') so we compare case-insensitively.
    """
    if getattr(user, "is_admin", False) or getattr(user, "is_super_admin", False):
        return True
    role = (getattr(user, "role", "") or "").lower()
    return role in ("admin", "super_admin")


def get_visible_mailbox_ids(user) -> list[int] | None:
    """Return the set of mailbox IDs the given user is allowed to access.

    Returns:
        None  — user is an admin; caller should apply NO mailbox filter.
        list  — caller must add ``AND mailbox_id = ANY(%s)`` to all queries.
                May be an empty list if the user has no dept + no grants.
    """
    if _is_admin(user):
        return None  # fast path — no SQL overhead for admins

    dept = getattr(user, "agent_department", None)
    ids: set[int] = set()

    try:
        with get_db_cursor() as (conn, cur):
            # 1. All mailboxes in the user's department
            if dept:
                cur.execute(
                    "SELECT id FROM email_mailboxes WHERE department = %s AND active = TRUE",
                    (dept,),
                )
                ids.update(row["id"] for row in cur.fetchall())

            # 2. Explicit per-user grants (shared inboxes, cross-dept supervisors)
            cur.execute(
                "SELECT mailbox_id FROM user_mailbox_grants WHERE user_id = %s",
                (user.id,),
            )
            ids.update(row["mailbox_id"] for row in cur.fetchall())
    except Exception:
        logger.exception("get_visible_mailbox_ids failed for user %s", getattr(user, "id", "?"))
        return []  # fail-closed: show nothing rather than everything

    return list(ids)


# Drop-in replacement for admin_required on user-facing Email HQ routes.
# Allows ADMIN_ACCESS (admins) OR EMAIL_INBOX_VIEW (human agents with COLLABORATOR role).
email_access_required = require_any_permission(
    Permission.ADMIN_ACCESS,
    Permission.EMAIL_INBOX_VIEW,
)
