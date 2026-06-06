"""Page routes for ARCHIE Chat module."""

from functools import wraps
from flask import redirect, url_for
from flask_login import current_user


def admin_required(f):
    """Decorator to require admin access (local definition, matches other modules)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def register_routes(bp, _admin_required):
    """Register page-rendering routes."""

    # Canonical chat is the independent A.R.C.H.I.E. Comms layer
    # (archie.kytranempowerment.com/chat) — it survives platform restarts and is the
    # single source of truth. The platform no longer serves its own chat UI; this route
    # redirects to the canonical surface (Comms enforces its own Kytran OAuth, so no
    # platform login gate here). API routes in this module are left intact for back-compat.
    CANONICAL_CHAT_URL = "https://archie.kytranempowerment.com/chat"

    @bp.route("/")
    def index():
        return redirect(CANONICAL_CHAT_URL, code=308)
