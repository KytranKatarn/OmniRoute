"""Media Studio — AI media generation hub.

Full LCARS module for generating images, video, and audio through
Bridge dispatch with GPU-tiered fleet routing.
"""

from flask import Blueprint

media_studio_bp = Blueprint(
    "media_studio",
    __name__,
    url_prefix="/tools/media-studio",
    template_folder="templates",
    static_folder="static",
)

from . import routes  # noqa: E402, F401
