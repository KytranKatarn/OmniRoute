"""
Plex Stack Module - DEPRECATED 2026-02-03
Merged into media_hub module.
Unified management interface for Plex media server ecosystem
"""

from flask import Blueprint  # noqa: F401

plex_stack_bp = Blueprint("plex_stack", __name__, url_prefix="/tools/plex-stack")

from . import routes  # noqa: F401, E402
