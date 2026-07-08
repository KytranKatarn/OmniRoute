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

import os

from flask import Blueprint

media_hub_bp = Blueprint(
    "media_hub",
    __name__,
    url_prefix="/tools/media-hub",
    template_folder="templates",
    static_folder="static",
)

from . import routes  # noqa: F401, E402
from .auth import install_auth  # noqa: E402

install_auth(media_hub_bp)


@media_hub_bp.context_processor
def _media_hub_template_context():
    """Inject `base_template` so media_hub.html can extend either the
    platform base or its own standalone base.

    Flip with MEDIA_HUB_STANDALONE=1 — without it, behavior is identical
    to pre-#2151 (extends platform base.html).
    """
    standalone = os.getenv("MEDIA_HUB_STANDALONE", "").lower() in ("1", "true", "yes")
    return {"base_template": "media_hub_base.html" if standalone else "base.html"}
