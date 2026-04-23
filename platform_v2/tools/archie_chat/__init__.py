"""
ARCHIE Chat Module — Chat with ARCHIE's agent fleet.
Uses ADR-045 route registration pattern.
"""

from flask import Blueprint

archie_chat_bp = Blueprint(
    "archie_chat",
    __name__,
    url_prefix="/tools/archie-chat",
    template_folder="templates",
)

from .routes import register_routes as register_page_routes  # noqa: E402
from .api_routes import register_routes as register_api_routes  # noqa: E402
from .ha_bridge import register_ha_routes  # noqa: E402
from .code_routes import register_code_routes  # noqa: E402

register_page_routes(archie_chat_bp, None)
register_api_routes(archie_chat_bp, None)
register_ha_routes(archie_chat_bp)
register_code_routes(archie_chat_bp)
