"""
Media Studio Module — Image, Video, and Audio generation via AI Bridge
"""

from flask import Blueprint

media_studio_bp = Blueprint("media_studio", __name__, url_prefix="/tools/media-studio")

from . import routes
