"""WTF Hub — internal Bridge dispatch surface + newsroom mail Inbox."""

from functools import wraps

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import current_user

from rbac import Permission, has_permission
from logging_config import audit_log

wtf_hub_bp = Blueprint("wtf_hub", __name__, url_prefix="/tools/wtf-hub")


def admin_required(f):
    """Require admin access (matches the platform module pattern)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permission.ADMIN_ACCESS, current_user):
            audit_log(
                "ADMIN_ACCESS_DENIED",
                {
                    "route": request.endpoint,
                    "user_id": (current_user.id if current_user.is_authenticated else None),
                },
                success=False,
            )
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


from . import routes  # noqa: E402, F401
from .mail_routes import register_mail_routes  # noqa: E402

register_mail_routes(wtf_hub_bp, admin_required)
