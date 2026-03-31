"""Media Studio — AI media generation hub.

Full LCARS module for generating images, video, and audio through
Bridge dispatch with GPU-tiered fleet routing.
"""

from functools import wraps

from flask import Blueprint, redirect, url_for
from flask_login import current_user

media_studio_bp = Blueprint(
    "media_studio",
    __name__,
    url_prefix="/tools/media-studio",
    template_folder="templates",
    static_folder="static",
)


def admin_required(f):
    """Require admin access — matches pattern used across all modules."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


from . import routes  # noqa: E402, F401
from .social_video_routes import register_social_video_routes  # noqa: E402

register_social_video_routes(media_studio_bp, admin_required)
