"""
Consciousness Module - A.R.C.H.I.E.'s Dynamic Learning System

This ADMIN-ONLY module manages:
- Conversation memories (auto-learned from interactions)
- Team Awareness (agent directory, performance tracking)
- Analytics (knowledge growth, usage patterns)

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

consciousness_bp = Blueprint(
    "consciousness",
    __name__,
    url_prefix="/tools/consciousness",
    template_folder="templates",
)

from . import routes  # noqa: F401, E402
from .routes import admin_required  # noqa: E402
from .processing_routes import processing_bp  # noqa: E402
from .knowledge_routes import register_knowledge_routes  # noqa: E402

# Register processing routes as nested blueprint
consciousness_bp.register_blueprint(processing_bp)

# Register knowledge routes (KB CRUD, search, ingestion, unified API)
register_knowledge_routes(consciousness_bp, admin_required)
