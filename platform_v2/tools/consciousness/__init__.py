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

# team_routes removed — Team tab merged into Starbase Command Crew tab
from .insights_routes import register_insights_routes  # noqa: E402
from .github_routes import register_github_routes  # noqa: E402
from .integration_routes import register_integration_routes  # noqa: E402
from .code_health_routes import register_code_health_routes  # noqa: E402
from .dashboard_routes import register_dashboard_routes  # noqa: E402
from .language_routes import register_language_routes  # noqa: E402

# Register processing routes as nested blueprint
consciousness_bp.register_blueprint(processing_bp)

# Register knowledge routes (KB CRUD, search, ingestion, unified API)
register_knowledge_routes(consciousness_bp, admin_required)

# Team routes removed — merged into Starbase Command Crew tab

# Register insights routes (analytics, sessions, learning patterns, experiences)
register_insights_routes(consciousness_bp, admin_required)

# Register GitHub routes (indexing, search, dependencies)
register_github_routes(consciousness_bp, admin_required)

# Register integration routes (cross-module health)
register_integration_routes(consciousness_bp, admin_required)

# Register code health routes (metrics, audit progress)
register_code_health_routes(consciousness_bp, admin_required)

# Register dashboard routes (summary API)
register_dashboard_routes(consciousness_bp, admin_required)

# Register language/translation routes
register_language_routes(consciousness_bp, admin_required)

# Register Dev HQ routes (merged from standalone /dev-hq, Decision #433)
from .devhq_routes import register_devhq_routes

register_devhq_routes(consciousness_bp, admin_required)

# Loop startup moved to Autonomy module (2026-03-23)
# See: tools/autonomy/__init__.py

# Register station actions so Bridge ACTN tab can discover them
try:
    from services.action_registry import register_station_actions

    # Loop actions (analysis, embeddings, translate) migrated to Autonomy module (2026-03-23)
    register_station_actions(
        [
            {
                "action_key": "consciousness.github.reindex",
                "station_code": "ANALYTICS",
                "module_source": "consciousness",
                "label": "REINDEX",
                "description": "Reindex all GitHub repositories",
                "icon": "git",
                "color_class": "cyan",
                "sort_order": 30,
                "endpoint_path": "/tools/consciousness/github/reindex-all",
                "creates_job": True,
                "job_type": "github_reindex",
                "test_config": {
                    "capability": "code_analysis",
                    "prompt": "Analyze this code file summary and categorize it:\n\nFile: app.py\nLanguage: Python\nImports: flask, os, logging\nFunctions: create_app, register_blueprints\nClasses: none",
                    "system_prompt": "You are a code indexer. Categorize the file type and purpose in one sentence.",
                    "description": "Classify code file metadata",
                },
            },
        ]
    )
except Exception:
    pass  # Table may not exist yet (pre-migration)
