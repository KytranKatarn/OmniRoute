"""
Media Hub Module
================
Unified management interface for media server ecosystem.
Supports Plex/Jellyfin + Sonarr/Radarr/Prowlarr/Overseerr/SABnzbd

Features:
- Smart search (local library first, then discovery)
- Library browser with filters
- Media request management
- Upcoming episode calendar
- Service configuration with auto-discovery
- Abstraction layer for Plex/Jellyfin migration
"""

from flask import Blueprint

media_hub_bp = Blueprint("media_hub", __name__, url_prefix="/tools/media-hub")

from . import routes  # noqa: F401, E402
from .auth import install_auth  # noqa: E402

install_auth(media_hub_bp)
