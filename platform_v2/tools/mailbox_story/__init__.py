"""Mailbox Story Extractor — local-sovereign PST intelligence (Applications & Concepts).

Upload a .pst mailbox -> a LOCAL AI reconstructs the account's story. Phase 1b: upload +
readpst extraction + the extracted-email table. ALL processing is local (files on local disk,
enrichment on local-only fleet LLMs in Phase 2). Admin-gated.

Design: .claude/plans/2026-06-16-mailbox-story-extractor-design.md
"""

from functools import wraps

from flask import Blueprint, redirect, url_for
from flask_login import current_user

mailbox_story_bp = Blueprint(
    "mailbox_story",
    __name__,
    url_prefix="/tools/mailbox-story",
)


def admin_required(f):
    """Owner-only gate (defense in depth alongside the registry minimum_role=ADMIN)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


from . import routes  # noqa: E402, F401
